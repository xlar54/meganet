"""Chat rooms (one at a time, permanent and member rooms, private ones), moderation (kick,
mute, ban, unban, topic, Karma +/-) and Karma Points (gains, losses, alerts, User Editor)."""

import time

from meganet import karma
from meganet.admin import WIN_USERS, WIN_KARMA
from meganet.chat import WIN_ROOM, WIN_ROOMS, WIN_UNBAN
from meganet.protocol import GFlag, Kind
from tests.test_pages import PagesBase
from tests.test_roles import gadget_of, has_text, status_of


class ChatBase(PagesBase):
    def room(self, c):
        return c.windows.get(WIN_ROOM)

    def lines(self, c):
        w = self.room(c)
        return w.gadgets[gadget_of(w, Kind.TEXTVIEW)]["lines"] if w and w.done else []

    def people(self, c):
        w = self.room(c)
        return w.gadgets[gadget_of(w, Kind.LISTBOX)]["rows"] if w and w.done else []

    async def enter(self, c, title="Lobby"):
        """Areas > Chat Rooms opens the list (not the Lobby): pick the room, Go."""
        c.windows.pop(WIN_ROOM, None)
        return await c.enter_room(title)

    async def say(self, c, text):
        w = self.room(c)
        c.value(WIN_ROOM, gadget_of(w, Kind.TEXTBOX), text)
        c.click_text(WIN_ROOM, "Send")

    async def rooms(self, c):
        c.windows.pop(WIN_ROOMS, None)
        c.click_text(WIN_ROOM, "Rooms...")
        return await c.wait_window("Chat Rooms")

    def room_rows(self, c):
        w = c.windows.get(WIN_ROOMS)
        return w.gadgets[gadget_of(w, Kind.LISTBOX)]["rows"] if w and w.done else []

    async def go_to(self, c, name, private=False, title=None):
        w = c.windows[WIN_ROOMS]
        c.value(WIN_ROOMS, gadget_of(w, Kind.TEXTBOX), name)
        if private:
            c.select(WIN_ROOMS, gadget_of(w, Kind.CHECKBOX), 1)
        c.windows.pop(WIN_ROOM, None)
        c.click_text(WIN_ROOMS, "Create Room")
        if title:
            return await c.wait_window(title)
        return None

    async def pick_person(self, c, name):
        await c.wait_for(lambda: any(r.startswith(name) for r in self.people(c)), name)
        i = next(i for i, r in enumerate(self.people(c)) if r.startswith(name))
        c.select(WIN_ROOM, gadget_of(self.room(c), Kind.LISTBOX), i)
        await c.wait_for(lambda: status_of(self.room(c)).startswith(name + ": Karma"), "picked")

    def karma(self, name):
        return self.server.db.user(name)["karma"]

    def set_role(self, name, role):
        d = self.server.db
        self.assertIsNone(d.set_user_role(d.user(name)["id"], d.role_by_name(role)["id"]))
        self.server.permissions_changed(user_id=d.user(name)["id"])


class RoomsTest(ChatBase):
    async def test_rooms_one_at_a_time_member_and_private(self):
        alice, bob = self.alice, self.bob
        await self.enter(bob)
        await self.enter(alice)
        await bob.wait_for(lambda: self.people(bob) == ["alice", "bob"], "both in the Lobby")
        await self.say(bob, "hi")
        await alice.wait_for(lambda: "bob: hi" in self.lines(alice), "line")

        # bob (New User) can't make rooms
        await self.rooms(bob)
        self.assertFalse(has_text(bob, WIN_ROOMS, "New Room"), "moderators only")
        await self.go_to(bob, "Bobs")
        await bob.wait_for(lambda: status_of(bob.windows[WIN_ROOMS]) ==
                           "There is no room called Bobs, and you can't make rooms.", "refused")

        # as a Member he can: a private member room; he leaves the Lobby for it
        self.set_role("bob", "Member")
        await bob.wait_for(lambda: self.server.screens.chat.where.get(self.session("bob")),
                           "still in")
        await self.rooms(bob)
        await self.go_to(bob, "Secret", private=True, title="Secret")
        self.assertNotIn(WIN_ROOMS, bob.windows)
        await alice.wait_for(lambda: self.people(alice) == ["alice"], "bob left the Lobby")
        self.assertIn("* bob has left the room", self.lines(alice))
        # alice (moderator) sees it, marked; carol doesn't, but can go in by name
        await self.rooms(alice)
        await alice.wait_for(lambda: any(r.startswith("Secret") for r in self.room_rows(alice)),
                             "listed for moderators")
        row = next(r for r in self.room_rows(alice) if r.startswith("Secret"))
        self.assertTrue(row.endswith(" private"), row)       # (one word: it fits the list)
        # Create Room greys itself while the name box is empty (the client does it as you
        # type), under a line and a bold "Create A Room"
        w = alice.windows[WIN_ROOMS]
        go = next(g for g in w.gadgets.values() if g["text"] == "Create Room")
        head = next(g for g in w.gadgets.values() if g["text"] == "Create A Room")
        self.assertTrue(head["flags"] & GFlag.BOLD)
        self.assertTrue(any(g["kind"] == Kind.GROUP for g in w.gadgets.values()), "the line")
        self.assertTrue(go["flags"] & GFlag.NEEDTEXT and go["flags"] & GFlag.DISABLED)
        self.assertEqual(go.get("value"), gadget_of(w, Kind.TEXTBOX))
        carol = await self.signed_on("carol")
        await self.enter(carol)
        await self.rooms(carol)
        self.assertFalse(any(r.startswith("Secret") for r in self.room_rows(carol)))
        await self.go_to(carol, "secret", title="Secret")
        await bob.wait_for(lambda: self.people(bob) == ["bob", "carol"], "carol came in")

        # the member room goes when the last one leaves
        bob.close_box(WIN_ROOM)
        await carol.wait_for(lambda: self.people(carol) == ["carol"], "bob left")
        carol.close_box(WIN_ROOM)
        await self.roundtrip(carol)
        self.assertIsNone(self.server.screens.chat.find("Secret"))
        self.assertNotIn(self.session("carol"), self.server.screens.chat.where)

    async def test_moderator_rooms_and_topic(self):
        alice, d = self.alice, self.server.db
        await self.enter(alice)
        await self.rooms(alice)
        w = alice.windows[WIN_ROOMS]
        alice.value(WIN_ROOMS, gadget_of(w, Kind.TEXTBOX), "MEGA65 Talk")
        alice.click_text(WIN_ROOMS, "New Room")
        await alice.wait_for(lambda: status_of(w) == "Made MEGA65 Talk.", "made")
        self.assertIn("MEGA65 Talk", [r["name"] for r in d.chat_rooms()])
        await self.enter(self.bob)
        await self.rooms(self.bob)
        await self.go_to(self.bob, "mega65 talk", title="MEGA65 Talk")
        # the topic: the line typed, shown to everyone in the room and kept
        await self.go_to(alice, "MEGA65 Talk", title="MEGA65 Talk")
        alice.value(WIN_ROOM, gadget_of(self.room(alice), Kind.TEXTBOX), "Bring your demos")
        alice.click_text(WIN_ROOM, "Topic")
        await self.bob.wait_for(lambda: has_text(self.bob, WIN_ROOM, "Topic: Bring your demos"),
                                "topic")
        self.assertEqual(next(r["topic"] for r in d.chat_rooms() if r["name"] == "MEGA65 Talk"),
                         "Bring your demos")
        # deleting it puts everyone out; the Lobby can't be deleted
        await self.rooms(alice)
        rows = self.room_rows(alice)
        alice.select(WIN_ROOMS, gadget_of(alice.windows[WIN_ROOMS], Kind.LISTBOX),
                     next(i for i, r in enumerate(rows) if r.startswith("MEGA65 Talk")))
        alice.click_text(WIN_ROOMS, "Delete Room")
        await self.bob.wait_for(lambda: ("MEGA65 Talk", "alice closed this room.")
                                in self.bob.alerts, "told")
        self.assertNotIn(WIN_ROOM, self.bob.windows)
        rows = self.room_rows(alice)
        alice.select(WIN_ROOMS, gadget_of(alice.windows[WIN_ROOMS], Kind.LISTBOX),
                     next(i for i, r in enumerate(rows) if r.startswith("Lobby")))
        await alice.wait_for(lambda: not alice.enabled(WIN_ROOMS, "Delete Room") and
                             alice.enabled(WIN_ROOMS, "Go"), "the Lobby picked: no Delete")
        self.server.screens.chat.lists[self.session("alice")]._delete(None)   # past the UI
        await alice.wait_for(lambda: status_of(alice.windows[WIN_ROOMS]) == "The Lobby stays.",
                             "kept")


class ModerationTest(ChatBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.enter(self.bob)
        await self.enter(self.alice)

    async def test_mute_kick_ban_unban(self):
        alice, bob = self.alice, self.bob
        k = self.karma("bob")
        self.assertFalse(has_text(bob, WIN_ROOM, "Kick"), "no moderator buttons for bob")
        await self.pick_person(alice, "bob")
        alice.click_text(WIN_ROOM, "Mute")
        await bob.wait_for(lambda: "* bob was muted by alice" in self.lines(bob), "muted")
        await bob.wait_for(lambda: "bob (muted)" in self.people(bob), "marked")
        await self.say(bob, "let me talk")
        await bob.wait_for(lambda: status_of(self.room(bob)) == "You are muted in this room.",
                           "refused")
        self.assertNotIn("bob: let me talk", self.lines(alice))
        self.assertEqual(self.karma("bob"), k - 1)
        alice.click_text(WIN_ROOM, "Unmute")
        await bob.wait_for(lambda: "* bob may talk again" in self.lines(bob), "unmuted")

        alice.click_text(WIN_ROOM, "Kick")
        await bob.wait_for(lambda: ("Lobby", "alice removed you from Lobby.") in bob.alerts, "k")
        self.assertNotIn(WIN_ROOM, bob.windows)
        self.assertEqual(self.karma("bob"), k - 4)
        await self.enter(bob)                            # kicked, not banned: back in
        await self.pick_person(alice, "bob")
        alice.click_text(WIN_ROOM, "Ban")
        await bob.wait_for(lambda: ("Lobby", "alice banned you from Lobby.") in bob.alerts, "b")
        self.assertEqual(self.karma("bob"), max(0, k - 9))
        bob.pick("Chat Rooms")
        await bob.wait_for(lambda: WIN_ROOM not in bob.windows and
                           self.session("bob") not in self.server.screens.chat.where, "out")
        self.assertNotIn(self.session("bob"), self.server.screens.chat.rooms["lobby"].windows)

        alice.click_text(WIN_ROOM, "Unban...")
        unban = await alice.wait_window("Unban")
        unban.find("Let back into Lobby:")
        alice.click_text(WIN_UNBAN, "Unban")
        await alice.wait_for(lambda: status_of(self.room(alice)) == "bob may come back into Lobby.",
                             "unbanned")
        await self.enter(bob)

    async def test_karma_buttons_and_protection(self):
        alice, bob = self.alice, self.bob
        await self.pick_person(alice, "bob")
        k = self.karma("bob")
        alice.click_text(WIN_ROOM, "Karma +")
        await alice.wait_for(lambda: status_of(self.room(alice)).startswith(
            "bob: Karma Points %d" % (k + 5)), "up")
        alice.click_text(WIN_ROOM, "Karma -")
        await alice.wait_for(lambda: status_of(self.room(alice)).startswith(
            "bob: Karma Points %d" % k), "down")
        alice.click_text(WIN_ROOM, "Karma -")             # a third today: refused
        await alice.wait_for(lambda: status_of(self.room(alice)) ==
                             "You have rated bob 2 times today already.", "limit")
        log = self.server.db.karma_log(self.server.db.user("bob")["id"])
        self.assertEqual([(e["delta"], e["by_name"]) for e in log[:2]], [(-5, "alice"), (5, "alice")])

        # a moderator can't act on an admin (or another moderator); an admin can on a moderator
        self.set_role("bob", "Moderator")
        await bob.wait_for(lambda: has_text(bob, WIN_ROOM, "Kick"), "bob's moderator buttons")
        await self.pick_person(bob, "alice")
        self.assertFalse(bob.enabled(WIN_ROOM, "Kick"), "greyed out for an admin")
        self.server.screens.chat.where[self.session("bob")].windows[
            self.session("bob")]._kick(None)                      # and refused past the UI
        await bob.wait_for(lambda: status_of(self.room(bob)) == "You can't do that to alice.",
                           "protected")
        await self.pick_person(alice, "bob")
        alice.click_text(WIN_ROOM, "Mute")
        await alice.wait_for(lambda: "bob (muted)" in self.people(alice), "admin over moderator")


class KarmaTest(ChatBase):
    async def test_new_users_start_low_and_earn(self):
        d, server = self.server.db, self.server
        bob = d.user("bob")
        self.assertEqual(bob["karma"], karma.NEW_KARMA + 1, "+1 for signing on today")
        self.assertEqual(d.user("alice")["karma"], 100, "the first account")
        self.assertIsNone(karma.earn(server, bob["id"], "signed on"), "once a day")
        # a board post: +1, twice a day at most
        for _ in range(3):
            karma.earn(server, bob["id"], "board post")
        self.assertEqual(self.karma("bob"), karma.NEW_KARMA + 3)
        # chatting: a point every CHAT_LINES lines
        await self.enter(self.bob)
        for i in range(karma.CHAT_LINES):
            await self.say(self.bob, "line %d" % i)
        await self.bob.wait_for(lambda: "bob: line %d" % (karma.CHAT_LINES - 1)
                                in self.lines(self.bob), "all said")
        self.assertEqual(self.karma("bob"), karma.NEW_KARMA + 4)
        # after a loss, no automatic gains for CLEAN_DAYS
        karma.lose(server, bob["id"], "muted in chat")
        d.conn.execute("DELETE FROM karma_log WHERE reason = 'chat'")
        self.assertIsNone(karma.earn(server, bob["id"], "chat"))
        # and automatic gains stop at AUTO_CEILING
        d.conn.execute("DELETE FROM karma_log")
        d.conn.execute("UPDATE users SET karma = ? WHERE id = ?", (karma.AUTO_CEILING, bob["id"]))
        karma.earn(server, bob["id"], "board post")
        self.assertEqual(self.karma("bob"), karma.AUTO_CEILING)

    async def test_low_karma_alerts_the_admins(self):
        d, server = self.server.db, self.server
        bob = d.user("bob")
        karma.change(server, bob["id"], -5, "test")             # 21 -> 16: no alert
        self.assertEqual(d.admin_messages(), [])
        karma.change(server, bob["id"], -6, "disrespectful", by=self.session("alice"))
        msgs = d.admin_messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["subject"], "Karma alert: bob")
        self.assertIn("fell to 10 (Low)", msgs[0]["text"])
        self.assertIn("disrespectful (by alice)", msgs[0]["text"])

    async def test_forged_events_cost_karma_once(self):
        k = self.karma("bob")
        for i in range(karma.SUSPICIOUS_LIMIT * 2):
            self.bob.click(0x3F, i + 1)                 # windows bob was never sent
        await self.roundtrip(self.bob)
        self.assertEqual(self.karma("bob"), k - 5)
        self.assertEqual(self.server.db.karma_log(self.server.db.user("bob")["id"])[0]["reason"],
                         "suspicious client activity")

    async def test_user_editor_karma(self):
        alice, d = self.alice, self.server.db
        d.change_karma(d.user("bob")["id"], -15, "test")
        alice.pick("User Editor...")
        win = await alice.wait_window("User Editor")
        alice.click_text(WIN_USERS, "Low Karma")
        lst = gadget_of(win, Kind.LISTBOX)
        await alice.wait_for(lambda: [r.split()[0] for r in win.gadgets[lst]["rows"]] == ["bob"],
                             "only bob is low")
        alice.select(WIN_USERS, lst, 0)
        box = gadget_of(win, Kind.TEXTBOX, 5)                 # added last: the karma box
        await alice.wait_for(lambda: win.text(box) == "6", "bob's karma")
        win.find("Very low")
        alice.value(WIN_USERS, box, "40")
        alice.click_text(WIN_USERS, "Save")
        await alice.wait_for(lambda: status_of(win) == "Saved bob.", "saved")
        self.assertEqual(self.karma("bob"), 40)
        alice.click_text(WIN_USERS, "History")
        hist = await alice.wait_window("Karma History")
        lines = hist.gadgets[gadget_of(hist, Kind.TEXTVIEW)]["lines"]
        self.assertEqual(lines[0], "bob: Karma Points 40 (OK)")
        self.assertTrue(lines[2].endswith("+34 = 40  set by an admin (alice)"), lines[2])
        self.assertIn(WIN_KARMA, alice.windows)


class BannedFromLobbyTest(ChatBase):
    async def test_list_says_why(self):
        """Areas > Chat Rooms opens the room list; Go on the Lobby for someone banned from it
        says why on the list's status line, not silence."""
        chat, bob = self.server.screens.chat, self.bob
        chat.bans.setdefault("lobby", set()).add(self.server.db.user("bob")["id"])
        bob.pick("Chat Rooms")
        w = await bob.wait_window("Chat Rooms")
        self.assertNotIn(WIN_ROOM, bob.windows, "not straight into the Lobby")
        await bob.wait_for(lambda: self.room_rows(bob), "rows")
        bob.select(WIN_ROOMS, gadget_of(w, Kind.LISTBOX), 0)
        bob.click_text(WIN_ROOMS, "Go")
        await bob.wait_for(lambda: status_of(w) == "You are banned from Lobby.", "told")
        self.assertNotIn(WIN_ROOM, bob.windows)
