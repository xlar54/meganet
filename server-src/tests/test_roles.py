"""Roles and permissions: the first user is Sysop, admins edit roles and move users, and the
server enforces it all (also for clients that send clicks for buttons they weren't given)."""

import os
import sqlite3
import tempfile
import unittest

from meganet import db, permissions
from meganet.admin import WIN_ROLES, WIN_USERS, WIN_CONFIRM, WIN_SET_PASSWORD
from meganet.protocol import Kind
from meganet.screens import (WIN_WELCOME, WIN_LOBBY, WIN_WHO, WIN_ACCOUNT, M_ADMIN, M_ROLES,
                             M_USERS, M_CHAT, M_FILES, M_MEMBERS_SEP, WIN_SEARCH, M_ACCOUNT)
from tests.test_server import ServerTest


def gadget_of(win, kind, nth=0):
    """The gid of the nth gadget of `kind` in a FakeWindow."""
    return [gid for gid, g in sorted(win.gadgets.items()) if g["kind"] == kind][nth]


def has_text(c, win_id, text):
    """True once window `win_id` is fully drawn on client `c` with a gadget showing `text`."""
    w = c.windows.get(win_id)
    return bool(w and w.done and any(g["text"] == text for g in w.gadgets.values()))


def status_of(win):
    """The status line: the last label in the window."""
    return win.text(gadget_of(win, Kind.LABEL, -1))


class RolesBase(ServerTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.alice = await self.signed_on("alice")          # first account: Sysop
        self.bob = await self.signed_on("bob")              # second: New User

    def session(self, name):
        return self.server.find_user(name)

    async def roundtrip(self, c):
        """Make sure the server has handled everything `c` sent: open the Games window and
        wait for it (the server handles a client's messages in order)."""
        c.windows.pop(3, None)
        c.pick("Games")
        await c.wait_window("Games")

    async def open_admin(self, c, which):
        c.pick(which + "...")                   # the Admin menu: "Roles..." / "User Editor..."
        return await c.wait_window(which)

    async def pick_row(self, c, win, listbox, start):
        """Select the list row that starts with `start`."""
        await c.wait_for(lambda: win.gadgets[listbox]["rows"], "list rows")
        rows = win.gadgets[listbox]["rows"]
        index = next(i for i, r in enumerate(rows) if r.lstrip("*").startswith(start))
        c.select(win.id, listbox, index)
        return index

    async def edit_role(self, c, role):
        roles = await self.open_admin(c, "Roles")
        await self.pick_row(c, roles, gadget_of(roles, Kind.LISTBOX), role)
        await c.wait_for(lambda: status_of(roles) == "Editing %s." % role, "editing " + role)
        return roles

    async def move_user(self, c, name, role):
        users = c.windows.get(WIN_USERS) or await self.open_admin(c, "User Editor")
        who = gadget_of(users, Kind.LABEL, 2)                        # after "Find:", "Username:"
        users.gadgets[gadget_of(users, Kind.LABEL, -1)]["text"] = ""     # status
        users.gadgets[who]["text"] = ""
        c.value(WIN_USERS, gadget_of(users, Kind.TEXTBOX), name)
        c.click_text(WIN_USERS, "Find")
        await c.wait_for(lambda: users.text(who) == name, "user found")
        users.gadgets[gadget_of(users, Kind.LABEL, -1)]["text"] = ""
        await self.pick_row(c, users, gadget_of(users, Kind.DROPDOWN), role)
        c.click_text(WIN_USERS, "Save")
        await c.wait_for(lambda: status_of(users), "status after Save")
        return status_of(users)


class RolesTest(RolesBase):

    async def test_first_user_is_sysop(self):
        self.assertEqual(self.session("alice").role, "Sysop")
        self.assertEqual(self.alice.menu_titles(), ["Areas", "Members", "Help", "Status", "Admin"])
        self.assertEqual(self.alice.menu_items("Admin"), ["User Editor...", "Roles...",
                                                          "Message of the Day...",
                                                          "Messages from users...",
                                                          "System Settings...",
                                                          "Broadcast..."])
        self.assertTrue(self.session("alice").can(permissions.ADMIN_ROLES))
        for key in permissions.keys():
            self.assertTrue(self.session("alice").can(key), key)

    async def test_new_user_has_no_admin(self):
        self.assertEqual(self.session("bob").role, "New User")
        self.assertEqual(self.bob.menu_titles(), ["Areas", "Members", "Help", "Status"])
        # files.download is Member and up
        self.assertEqual(self.bob.menu_items("Areas"), ["News", "Message Boards", "Chat Rooms",
                                                        "Private Messages", "Art Gallery",
                                                        "SID Music", "Games"])
        s = self.session("bob")
        self.assertTrue(s.can("chat.use") and s.can("games.play") and s.can("boards.read"))
        self.assertFalse(s.can("boards.post") or s.can(permissions.ADMIN_USERS))

        # Forged picks of ids bob was never sent (the Admin title and items, File Library, a
        # client id, a separator), and clicks on gadgets of the admin windows.
        for item_id in (M_ADMIN, M_ROLES, M_USERS, M_FILES, M_MEMBERS_SEP, 0xF0, 0xFF, 0):
            self.bob.pick_id(item_id)
        for win in (WIN_ROLES, WIN_USERS, WIN_CONFIRM, WIN_SET_PASSWORD):
            for gid in range(1, 6):
                self.bob.click(win, gid)
        await self.roundtrip(self.bob)
        for title in ("Roles", "User Editor", "Delete Role", "Set Password"):
            self.assertFalse(any(w.title == title for w in self.bob.windows.values()), title)
        self.assertEqual(self.bob.alerts, [], "ids that weren't sent are ignored")
        self.assertEqual([r["name"] for r in self.server.db.roles()],
                         ["New User", "Member", "Moderator", "Sysop"], "nothing changed")

    async def test_stale_admin_menu_is_refused(self):
        """An Admin item that was sent, but whose permission has gone since (and the new menu
        hasn't reached the client), is refused when picked."""
        s = self.session("alice")
        s.perms = frozenset({"chat.use"})                    # the menu wasn't re-sent
        self.alice.pick("Roles...")
        self.alice.pick("User Editor...")
        await self.alice.wait_for(lambda: len(self.alice.alerts) >= 2, "refusals")
        self.assertEqual(self.alice.alerts, [("Roles", "Your account can't use Roles."),
                                             ("User Editor", "Your account can't use User Editor.")])
        self.assertNotIn(WIN_ROLES, self.alice.windows)
        self.assertNotIn(WIN_USERS, self.alice.windows)
        # And straight at the admin module, past the menu:
        self.server.screens.admin.open_roles(s)
        await self.alice.wait_for(lambda: len(self.alice.alerts) == 3, "refusal")
        self.assertNotIn(WIN_ROLES, self.alice.windows)

    async def test_admin_handlers_check_permissions(self):
        """Even with an admin window open, a user without the permission is refused."""
        status = await self.move_user(self.alice, "bob", "Sysop")
        self.assertEqual(status, "bob is now Sysop.")
        await self.bob.wait_for(lambda: "Admin" in self.bob.menu_titles(), "bob's Admin menu")
        await self.bob.wait_for(lambda: self.session("bob").role == "Sysop",
                                "bob's welcome window updated")
        roles = await self.open_admin(self.bob, "Roles")
        # The permission goes away but (pretend) the window stayed open on bob's screen.
        self.session("bob").perms = frozenset({"chat.use"})
        self.bob.click_text(roles.id, "New Role")
        await self.bob.wait_for(lambda: ("Administration", "You don't have permission to do "
                                         "that.") in self.bob.alerts, "refusal")
        self.assertIsNone(self.server.db.role_by_name("New Role"))

    async def test_take_chat_away_from_new_users(self):
        self.bob.pick("Chat Rooms")
        await self.bob.wait_window("Lobby")

        roles = await self.edit_role(self.alice, "New User")
        chat = roles.find("Chat in the lobby")
        self.assertEqual(roles.gadgets[chat]["value"], 1, "New User has chat.use")
        self.alice.select(WIN_ROLES, chat, 0)                # untick it
        self.alice.click_text(WIN_ROLES, "Save")
        await self.alice.wait_for(lambda: status_of(roles) == "Saved New User.", "saved")
        self.assertNotIn("chat.use", self.server.db.role_permissions(
            self.server.db.role_by_name("New User")["id"]))

        # bob, still connected: out of the lobby, and the menu no longer offers it.
        await self.bob.wait_for(lambda: WIN_LOBBY not in self.bob.windows, "bob kicked")
        await self.bob.wait_for(lambda: self.bob.menu_items("Areas") == [
            "News", "Message Boards", "Private Messages", "Art Gallery", "SID Music", "Games"],
            "menu without chat")
        self.assertFalse(self.session("bob").can("chat.use"))
        self.bob.pick_id(M_CHAT)                             # forged: no longer in his menu
        self.server.screens.chat.join(self.session("bob"), "Lobby")  # and straight at it
        await self.roundtrip(self.bob)
        self.assertNotIn(WIN_LOBBY, self.bob.windows)
        self.assertIn(("Chat Rooms", "Your account can't use the chat rooms."),
                      self.bob.alerts)
        self.assertNotIn(self.session("bob"), self.server.screens.chat.where)

        # A new account gets the same role, so no chat either.
        carol = await self.signed_on("carol")
        self.assertNotIn("Chat Rooms", carol.menu_items("Areas"))

    async def test_move_user_to_moderator(self):
        status = await self.move_user(self.alice, "bob", "Moderator")
        self.assertEqual(status, "bob is now Moderator.")
        self.assertEqual(self.server.db.user("bob")["role"], "Moderator")
        await self.bob.wait_for(lambda: self.session("bob").role == "Moderator",
                                "bob's welcome window shows Moderator")
        s = self.session("bob")
        self.assertTrue(s.can("chat.moderate") and s.can("boards.post"))
        self.assertFalse(s.can(permissions.ADMIN_ROLES))
        await self.bob.wait_for(lambda: "File Library" in self.bob.menu_items("Areas"),
                                "File Library (Member and up)")
        # Moderators answer pages, but only admins get the Admin menu.
        self.assertNotIn("Admin", self.bob.menu_titles())
        # The user list shows the new role.
        users = self.alice.windows[WIN_USERS]
        rows = users.gadgets[gadget_of(users, Kind.LISTBOX)]["rows"]
        self.assertTrue(any(r.startswith("bob") and "Moderato" in r for r in rows), rows)

    async def test_last_admin_is_protected(self):
        dbase = self.server.db
        # alice can't move herself out of Sysop...
        status = await self.move_user(self.alice, "alice", "Member")
        self.assertEqual(status, "alice is the last user who can edit roles.")
        self.assertEqual(dbase.user("alice")["role"], "Sysop")
        # ...nor take admin.roles away from Sysop...
        roles = await self.edit_role(self.alice, "Sysop")
        self.alice.click_text(WIN_ROLES, "Next >")           # (the admin keys are on page 2)

        def page2():
            win = self.alice.windows.get(WIN_ROLES)
            return win is not None and win.done and any(
                g["text"] == "Admin: edit roles" for g in win.gadgets.values())
        await self.alice.wait_for(page2, "roles page 2")
        roles = self.alice.windows[WIN_ROLES]
        box = roles.find("Admin: edit roles")
        self.alice.select(WIN_ROLES, box, 0)
        self.alice.click_text(WIN_ROLES, "Save")
        await self.alice.wait_for(lambda: status_of(roles).startswith("Nobody else"), "refused")
        self.assertIn(permissions.ADMIN_ROLES,
                      dbase.role_permissions(dbase.role_by_name("Sysop")["id"]))
        await self.alice.wait_for(lambda: roles.gadgets[box]["value"] == 1, "box ticked again")
        # ...nor delete the Sysop role (its users would move to New User).
        self.alice.click_text(WIN_ROLES, "Delete")
        confirm = await self.alice.wait_window("Delete Role")
        self.alice.click_text(confirm.id, "Move and Delete")
        await self.alice.wait_for(lambda: status_of(roles) ==
                                  "That would leave nobody who can edit roles.", "refused")
        self.assertIsNotNone(dbase.role_by_name("Sysop"))
        # The default role can't be deleted, even though it has users.
        self.assertIn("make another one the default", dbase.delete_role(dbase.default_role_id()))
        # Once bob is Sysop too, alice may step down.
        self.assertIsNone(dbase.set_user_role(dbase.user("bob")["id"],
                                              dbase.role_by_name("Sysop")["id"]))
        self.assertIsNone(dbase.set_user_role(dbase.user("alice")["id"],
                                              dbase.role_by_name("Member")["id"]))
        self.assertEqual(dbase.admin_count(), 1)

    async def test_new_rename_default_delete(self):
        dbase = self.server.db
        roles = await self.open_admin(self.alice, "Roles")
        self.alice.click_text(WIN_ROLES, "New Role")
        await self.alice.wait_for(lambda: status_of(roles).startswith("Made New Role"), "made")
        name = gadget_of(roles, Kind.TEXTBOX)
        self.alice.value(WIN_ROLES, name, "Guest")
        self.alice.click_text(WIN_ROLES, "Rename")
        await self.alice.wait_for(lambda: status_of(roles) == "Renamed to Guest.", "renamed")
        box = roles.find("Play games")
        self.alice.select(WIN_ROLES, box, 1)
        self.alice.click_text(WIN_ROLES, "Save")
        await self.alice.wait_for(lambda: status_of(roles) == "Saved Guest.", "saved")
        self.alice.click_text(WIN_ROLES, "Make Default")
        await self.alice.wait_for(lambda: status_of(roles) == "New users now get Guest.", "dflt")
        listbox = gadget_of(roles, Kind.LISTBOX)
        await self.alice.wait_for(lambda: "*Guest (0)" in roles.gadgets[listbox]["rows"], "*")

        dave = await self.signed_on("dave")
        self.assertEqual(self.session("dave").role, "Guest")
        self.assertEqual(dave.menu_titles(), ["Areas", "Members", "Help", "Status"])
        self.assertEqual(dave.menu_items("Areas"), ["Games"])
        self.assertEqual(self.session("dave").perms, {"games.play"})

        # Guest has a user and is the default: it can't go until another role is the default.
        self.alice.click_text(WIN_ROLES, "Delete")
        await self.alice.wait_for(lambda: "make another one the default" in status_of(roles),
                                  "refused")
        await self.pick_row(self.alice, roles, listbox, "Member")
        self.alice.click_text(WIN_ROLES, "Make Default")
        await self.alice.wait_for(lambda: status_of(roles) == "New users now get Member.", "dflt")
        await self.pick_row(self.alice, roles, listbox, "Guest")
        await self.alice.wait_for(lambda: status_of(roles) == "Editing Guest.", "editing")
        self.alice.click_text(WIN_ROLES, "Delete")
        confirm = await self.alice.wait_window("Delete Role")
        self.alice.click_text(confirm.id, "Move and Delete")
        await self.alice.wait_for(lambda: status_of(roles) == "Deleted Guest.", "deleted")
        self.assertIsNone(dbase.role_by_name("Guest"))
        self.assertEqual(dbase.user("dave")["role"], "Member")
        await dave.wait_for(lambda: self.session("dave").role == "Member", "dave moved")
        await dave.wait_for(lambda: "File Library" in dave.menu_items("Areas"), "dave's menu")


class MenuTest(RolesBase):
    """The menu bar: filtered per role, re-sent when the role changes, and its own windows."""

    async def test_user_search(self):
        self.bob.pick("User Search...")
        win = await self.bob.wait_window("User Search")
        listbox = gadget_of(win, Kind.LISTBOX)
        self.bob.value(WIN_SEARCH, gadget_of(win, Kind.TEXTBOX), "AL")   # any case, part of a name
        self.bob.click_text(WIN_SEARCH, "Search")
        await self.bob.wait_for(lambda: win.gadgets[listbox]["rows"], "search results")
        rows = win.gadgets[listbox]["rows"]
        self.assertEqual(len(rows), 1, rows)
        self.assertTrue(rows[0].startswith("alice") and "Sysop" in rows[0] and rows[0].endswith(" *"),
                        rows)
        self.bob.value(WIN_SEARCH, gadget_of(win, Kind.TEXTBOX), "zz")
        self.bob.click_text(WIN_SEARCH, "Search")
        await self.bob.wait_for(lambda: win.gadgets[listbox]["rows"] == [], "no results")
        self.assertTrue(any(g["text"].startswith("Nobody matches") for g in win.gadgets.values()))

    def make_role(self, name, keys):
        dbase = self.server.db
        role_id = dbase.create_role(name, 50)
        self.assertIsNone(dbase.set_role_permissions(role_id, set(keys)))
        self.server.screens.admin.changed()                  # open role lists show it
        return role_id

    async def test_menu_per_role(self):
        # My Account moved to the client's own MegaNet menu (MENU_PICK $22, never sent).
        self.assertEqual(self.alice.menu_items("Members"), ["Who's Online", "User Search..."])
        self.assertEqual(self.alice.menu_items("Help"), ["About MegaNet", "Getting Around",
                                                          "Page Admin"])
        # Only one of the two admin keys: only that item, under Admin.
        self.make_role("Helper", ["chat.use", permissions.ADMIN_USERS])
        status = await self.move_user(self.alice, "bob", "Helper")
        self.assertEqual(status, "bob is now Helper.")
        await self.bob.wait_for(lambda: self.bob.menu_items("Admin") == ["User Editor..."], "Admin")
        self.assertEqual(self.bob.menu_items("Areas"), ["Chat Rooms"])
        self.bob.pick("User Editor...")
        await self.bob.wait_window("User Editor")
        self.bob.pick_id(M_ROLES)                            # forged: not in his menu
        await self.roundtrip_users(self.bob)
        self.assertNotIn(WIN_ROLES, self.bob.windows)
        # No permissions at all: no Areas and no Admin; Members and Help are always there.
        self.make_role("Nobody", [])
        await self.move_user(self.alice, "bob", "Nobody")
        await self.bob.wait_for(lambda: self.bob.menu_titles() == ["Members", "Help", "Status"], "bare")
        await self.bob.wait_for(lambda: WIN_USERS not in self.bob.windows, "Users closed")
        carol_role = self.server.db.role_by_name("Nobody")["id"]
        self.server.db.set_default_role(carol_role)
        carol = await self.signed_on("carol")
        self.assertEqual(carol.menu_titles(), ["Members", "Help", "Status"])

    async def roundtrip_users(self, c):
        """Like roundtrip, for a user without games: re-pick Users and wait for it."""
        c.windows.pop(WIN_USERS, None)
        c.pick("User Editor...")
        await c.wait_window("User Editor")

    async def test_menu_resent_after_role_change(self):
        n = self.bob.menus_received
        await self.move_user(self.alice, "bob", "Sysop")
        await self.bob.wait_for(lambda: self.bob.menus_received > n, "MENU re-sent")
        self.assertEqual(self.bob.menu_titles(), ["Areas", "Members", "Help", "Status", "Admin"])
        await self.open_admin(self.bob, "Roles")
        # Back to Member: the Admin menu goes, and so does the Roles window.
        n = self.bob.menus_received
        await self.move_user(self.alice, "bob", "Member")
        await self.bob.wait_for(lambda: self.bob.menus_received > n, "MENU re-sent")
        self.assertNotIn("Admin", self.bob.menu_titles())
        await self.bob.wait_for(lambda: WIN_ROLES not in self.bob.windows, "Roles closed")
        # A save that changes nothing for bob's role doesn't re-send his menu.
        n = self.bob.menus_received
        roles = await self.edit_role(self.alice, "Moderator")
        self.alice.click_text(WIN_ROLES, "Save")
        await self.alice.wait_for(lambda: status_of(roles) == "Saved Moderator.", "saved")
        await self.roundtrip(self.bob)
        self.assertEqual(self.bob.menus_received, n)
        # A role change for bob's own role's permissions does.
        self.alice.windows.pop(WIN_ROLES)                    # wait for the redrawn one
        roles = await self.edit_role(self.alice, "Member")
        self.alice.select(WIN_ROLES, roles.find("Play games"), 0)
        self.alice.click_text(WIN_ROLES, "Save")
        await self.bob.wait_for(lambda: "Games" not in self.bob.menu_items("Areas"),
                                "Games gone from bob's menu")

    async def test_whos_online(self):
        self.alice.pick("Who's Online")
        who = await self.alice.wait_window("Who's Online")
        listbox = gadget_of(who, Kind.LISTBOX)
        rows = lambda: [r.split() for r in who.gadgets[listbox]["rows"]]
        self.assertEqual(rows(), [["alice", "(Available)", "Sysop"], ["bob", "(Available)", "New", "User"]])
        who.find("2 signed on")
        carol = await self.signed_on("carol")
        await self.alice.wait_for(lambda: len(rows()) == 3, "carol in the list")
        self.assertTrue(has_text(self.alice, WIN_WHO, "3 signed on"))
        await self.move_user(self.alice, "carol", "Member")
        await self.alice.wait_for(lambda: ["carol", "(Available)", "Member"] in rows(), "carol's new role")
        await self.bob.close()
        self.clients.remove(self.bob)
        await self.alice.wait_for(lambda: [r[0] for r in rows()] == ["alice", "carol"],
                                  "bob gone")
        # Closed: no more updates sent to it.
        self.alice.close_box(WIN_WHO)
        await self.roundtrip(self.alice)
        self.assertNotIn(self.session("alice"), self.server.screens.who)
        await carol.close()
        self.clients.remove(carol)
        await self.roundtrip(self.alice)
        self.assertNotIn(WIN_WHO, self.alice.windows)

    async def test_my_account_and_about(self):
        self.bob.pick_id(M_ACCOUNT)                  # the client's MegaNet > My Account
        acct = await self.bob.wait_window("My Account")
        acct.find("bob")
        acct.find("Role: New User")
        self.bob.pick("About MegaNet")
        await self.bob.wait_for(lambda: self.bob.alerts, "about box")
        self.assertEqual(self.bob.alerts[0][0], "About MegaNet")
        self.assertIn("2 signed on", self.bob.alerts[0][1])
        # The welcome window closes with OK.
        self.bob.click_text(WIN_WELCOME, "OK")
        await self.bob.wait_for(lambda: WIN_WELCOME not in self.bob.windows, "welcome closed")
        self.assertIn(WIN_ACCOUNT, self.bob.windows)


class UserEditorTest(RolesBase):
    async def test_edit_details_and_password(self):
        dbase = self.server.db
        bob_id = dbase.user("bob")["id"]
        dbase.set_profile(bob_id, "Bob", "Jones", "bob@example.com", "Leeds", "1970-01-02",
                          ["about bob"])
        c = self.alice
        win = await self.open_admin(c, "User Editor")
        listbox = gadget_of(win, Kind.LISTBOX)
        await self.pick_row(c, win, listbox, "bob")
        first, last, email, location = (gadget_of(win, Kind.TEXTBOX, i) for i in range(1, 5))
        await c.wait_for(lambda: win.text(first) == "Bob", "bob's details")
        self.assertEqual([win.text(g) for g in (last, email, location)],
                         ["Jones", "bob@example.com", "Leeds"])
        role = win.gadgets[gadget_of(win, Kind.DROPDOWN)]
        await c.wait_for(lambda: role["value"] < len(role["rows"]) and
                         role["rows"][role["value"]] == "New User", "bob's role")

        # A bad first name is refused; good ones are saved, birthdate and About Me kept.
        c.value(WIN_USERS, first, "B0b")
        c.click_text(WIN_USERS, "Save")
        await c.wait_for(lambda: status_of(win).startswith("Names hold"), "refused")
        for gid, text in ((first, "Robert"), (email, ""), (location, "York")):
            c.value(WIN_USERS, gid, text)
        c.click_text(WIN_USERS, "Save")
        await c.wait_for(lambda: status_of(win) == "Saved bob.", "saved")
        u = dbase.user("bob")
        self.assertEqual((u["first_name"], u["last_name"], u["email"], u["location"],
                          u["birthdate"], u["about"], u["role"]),
                         ("Robert", "Jones", "", "York", "1970-01-02", "about bob", "New User"))

        # Set Password: must match, then bob signs on with it.
        c.click_text(WIN_USERS, "Set Password...")
        pw = await c.wait_window("Set Password")
        boxes = [gadget_of(pw, Kind.PASSWORD, i) for i in (0, 1)]
        c.value(pw.id, boxes[0], "newpass")
        c.value(pw.id, boxes[1], "other")
        c.click_text(pw.id, "OK")
        await c.wait_for(lambda: pw.text(gadget_of(pw, Kind.LABEL, 0)) ==
                         "The passwords don't match.", "mismatch")
        c.value(pw.id, boxes[1], "newpass")
        c.click_text(pw.id, "OK")
        await c.wait_for(lambda: status_of(win) == "Set a new password for bob.", "set")
        self.assertNotIn(pw.id, c.windows)
        await self.bob.close()
        self.clients.remove(self.bob)
        b2 = await self.client("bob2")
        b2.send_hello()
        await b2.wait_for(lambda: b2.hello, "HELLO")
        ok, msg = await self.login(b2, "bob", "newpass")
        self.assertTrue(ok, msg)

    async def test_old_account_without_names(self):
        """Accounts from before real names were required can still be saved blank."""
        status = await self.move_user(self.alice, "bob", "Member")
        self.assertEqual(status, "bob is now Member.")


class NewUserIconTest(RolesBase):
    async def test_person_icon(self):
        from meganet.protocol import Icon, SLOT_NEW_USER
        alice, bob = self.alice, self.bob
        await alice.wait_for(lambda: alice.icon(SLOT_NEW_USER) == Icon.PERSON, "person icon")
        self.assertEqual(alice.hint(SLOT_NEW_USER), "1 new user")
        self.assertEqual(bob.icon(SLOT_NEW_USER), Icon.NONE, "only admins get it")
        carol = await self.signed_on("carol")
        await alice.wait_for(lambda: alice.hint(SLOT_NEW_USER) == "2 new users", "2")
        self.assertEqual(carol.icon(SLOT_NEW_USER), Icon.NONE)

        # A click opens the User Editor at the oldest new user.
        alice.notify_click(SLOT_NEW_USER)
        win = await alice.wait_window("User Editor")
        self.assertEqual(win.text(gadget_of(win, Kind.LABEL, 2)), "bob")

        await self.move_user(alice, "bob", "Member")
        await alice.wait_for(lambda: alice.hint(SLOT_NEW_USER) == "1 new user", "bob done")
        await self.move_user(alice, "carol", "Member")
        await alice.wait_for(lambda: alice.icon(SLOT_NEW_USER) == Icon.NONE, "icon gone")
        # An admin who signs on later gets it too, once there is a new user again.
        await self.signed_on("dave")
        await alice.wait_for(lambda: alice.icon(SLOT_NEW_USER) == Icon.PERSON, "back")


class RolesPagingTest(RolesBase):
    async def test_more_permissions_than_fit(self):
        extra = [permissions.register("test.extra%d" % i, "Extra thing %d" % i) for i in range(6)]
        try:
            self.server.db.sync_permissions()
            roles = await self.edit_role(self.alice, "Sysop")
            roles.find("Page 1/2")
            self.alice.click_text(WIN_ROLES, "Next >")
            await self.alice.wait_for(lambda: has_text(self.alice, WIN_ROLES, "Page 2/2"), "p2")
            roles = self.alice.windows[WIN_ROLES]
            box = roles.find("Extra thing 5")
            self.assertEqual(roles.gadgets[box]["value"], 1, "Sysop got the new key")
            self.alice.select(WIN_ROLES, box, 0)
            self.alice.click_text(WIN_ROLES, "Save")
            await self.alice.wait_for(lambda: status_of(roles) == "Saved Sysop.", "saved")
            keys = self.server.db.role_permissions(self.server.db.role_by_name("Sysop")["id"])
            self.assertNotIn("test.extra5", keys)
            self.assertIn("test.extra4", keys)
            self.assertIn("chat.use", keys, "boxes on the other page kept")
        finally:
            for key in extra:
                del permissions._registry[key]


class DatabaseRolesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "old.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_migrate_old_database(self):
        conn = sqlite3.connect(self.path)
        conn.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                                pw_hash TEXT NOT NULL, created INTEGER NOT NULL);
            INSERT INTO users (name, pw_hash, created) VALUES ('Old Sysop', 'x', 1);
            INSERT INTO users (name, pw_hash, created) VALUES ('Old User', 'x', 2);
        """)
        conn.commit()
        conn.close()

        d = db.Database(self.path)
        cols = [r["name"] for r in d.conn.execute("PRAGMA table_info(users)")]
        for col in ("role_id", "email", "location", "birthdate", "about", "last_login"):
            self.assertIn(col, cols)
        tables = {r[0] for r in d.conn.execute("SELECT name FROM sqlite_master")}
        self.assertTrue({"admin_messages", "private_messages"} <= tables)
        self.assertEqual(d.user("old sysop")["role"], "Sysop")
        self.assertEqual(d.user("old user")["role"], "New User")
        d.close()

        d = db.Database(self.path)                       # opening it again changes nothing
        self.assertEqual([(u["name"], u["role"]) for u in d.users()],
                         [("Old Sysop", "Sysop"), ("Old User", "New User")])
        self.assertEqual(len(d.roles()), 4)
        self.assertTrue(d.create_user("Newbie", "x"))
        self.assertEqual(d.user("newbie")["role"], "New User")
        d.close()

    def test_plugin_permission_follows_like(self):
        d = db.Database(self.path)
        key = permissions.register("games.testonly", "Play the test game", like="games.play")
        try:
            d.sync_permissions()
            for r in d.roles():
                self.assertIn(key, d.role_permissions(r["id"]), r["name"])
            # An admin takes it away from New User; the next start doesn't give it back.
            nu = d.role_by_name("New User")["id"]
            d.set_role_permissions(nu, d.role_permissions(nu) - {key})
            d.sync_permissions()
            self.assertNotIn(key, d.role_permissions(nu))
        finally:
            del permissions._registry[key]
            d.close()

    def test_new_core_permission_goes_to_admins_only(self):
        d = db.Database(self.path)
        key = permissions.register("test.newthing", "A new feature")
        try:
            d.sync_permissions()
            self.assertIn(key, d.role_permissions(d.role_by_name("Sysop")["id"]))
            self.assertNotIn(key, d.role_permissions(d.role_by_name("Moderator")["id"]))
        finally:
            del permissions._registry[key]
            d.close()


if __name__ == "__main__":
    unittest.main()
