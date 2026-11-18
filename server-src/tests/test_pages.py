"""Help > Page Admin and Getting Around: paging an admin who is signed on (the icon, the first
click wins, a private chat, Cancel, a queue), and leaving a message when none is."""

import asyncio

from meganet import permissions, ui
from meganet.mail import WIN_COMPOSE
from meganet.pages import WIN_PAGING, WIN_NO_ADMIN, WIN_TO_ADMINS, WIN_ADMIN_MSGS
from meganet.protocol import Kind, Icon, SLOT_PAGE, SLOT_ADMIN_MAIL, SLOT_MAIL
from meganet.screens import WIN_HELP, M_ADMIN_MSGS
from meganet.session import FIRST_DYNAMIC_WIN
from tests.test_roles import RolesBase, gadget_of, has_text, status_of


class PagesBase(RolesBase):
    async def sign_in(self, name, password="secret"):
        """An existing account signs on again."""
        c = await self.client(name)
        c.send_hello()
        await c.wait_for(lambda: c.hello, "HELLO")
        ok, msg = await self.login(c, name, password)
        self.assertTrue(ok, msg)
        await c.wait_window("Welcome")
        return c

    async def sign_off(self, c):
        await c.close()
        self.clients.remove(c)
        for _ in range(500):                         # the server notices the close
            if self.server.find_user(c.name) is None:
                return
            await asyncio.sleep(0.01)
        self.fail("%s still signed on" % c.name)

    async def moderator(self, name):
        c = await self.signed_on(name)
        d = self.server.db
        n = c.menus_received
        self.assertIsNone(d.set_user_role(d.user(name)["id"], d.role_by_name("Moderator")["id"]))
        self.server.permissions_changed(user_id=d.user(name)["id"])
        await c.wait_for(lambda: c.menus_received > n, "menu re-sent")
        self.assertNotIn("Admin", c.menu_titles(), "Moderators answer pages, no Admin menu")
        return c

    def chat_win(self, c):
        return next((w for w in c.windows.values() if w.done and w.title.startswith("Chat with")),
                    None)

    def chat_lines(self, c):
        w = self.chat_win(c)
        return w.gadgets[gadget_of(w, Kind.TEXTVIEW)]["lines"] if w else []

    async def say(self, c, text):
        w = self.chat_win(c)
        c.value(w.id, gadget_of(w, Kind.TEXTBOX), text)
        c.click_text(w.id, "Send")


class HelpMenuTest(PagesBase):
    async def test_getting_around(self):
        self.assertEqual(self.bob.menu_items("Help"), ["About MegaNet", "Getting Around",
                                                       "Page Admin"])
        self.bob.pick("Getting Around")
        win = await self.bob.wait_window("Getting Around")
        self.assertEqual(win.id, WIN_HELP)
        self.assertEqual(win.pos, ui.centre(400, 128))
        lines = win.gadgets[gadget_of(win, Kind.TEXTVIEW)]["lines"]
        self.assertTrue(any("TAB" in line and "RETURN" in line for line in lines), lines)
        self.assertTrue(any("Exit" in line for line in lines), lines)
        self.bob.click_text(WIN_HELP, "OK")
        await self.bob.wait_for(lambda: WIN_HELP not in self.bob.windows, "closed")

    async def test_new_permission(self):
        d = self.server.db
        for role, has in (("New User", False), ("Member", False), ("Moderator", True),
                          ("Sysop", True)):
            self.assertEqual(permissions.ADMIN_PAGES in d.role_permissions(
                d.role_by_name(role)["id"]), has, role)
        self.assertEqual(permissions.get(permissions.ADMIN_PAGES).description,
                         "Answer pages from users")


class PageOnlineTest(PagesBase):
    async def test_page_chat_and_first_click_wins(self):
        alice, bob = self.alice, self.bob
        carol = await self.moderator("carol")
        bob.pick("Page Admin")
        paging = await bob.wait_window("Page Admin")
        self.assertEqual(paging.id, WIN_PAGING)
        paging.find("Paging an admin...")
        for admin in (alice, carol):
            await admin.wait_for(lambda a=admin: a.icon(SLOT_PAGE) == Icon.PAGE, "page icon")
            self.assertEqual(admin.hint(SLOT_PAGE), "bob is paging you")
        self.assertEqual(bob.icon(SLOT_PAGE), Icon.NONE, "users don't get the icon")

        carol.notify_click(SLOT_PAGE)                     # the first click wins
        await bob.wait_for(lambda: self.chat_win(bob), "bob's chat")
        await carol.wait_for(lambda: self.chat_win(carol), "carol's chat")
        await alice.wait_for(lambda: alice.icon(SLOT_PAGE) == Icon.NONE, "alice's icon gone")
        self.assertEqual(carol.icon(SLOT_PAGE), Icon.NONE)
        self.assertNotIn(WIN_PAGING, bob.windows)
        self.assertEqual(self.chat_win(bob).title, "Chat with carol")
        self.assertEqual(self.chat_win(carol).title, "Chat with bob")
        self.assertGreaterEqual(self.chat_win(bob).id, FIRST_DYNAMIC_WIN)
        alice.notify_click(SLOT_PAGE)                     # too late: ignored
        await self.roundtrip(alice)
        self.assertIsNone(self.chat_win(alice))

        await self.say(bob, "Hello, I need help")
        await carol.wait_for(lambda: "bob: Hello, I need help" in self.chat_lines(carol), "line")
        self.assertIn("bob: Hello, I need help", self.chat_lines(bob))
        await self.say(carol, "Sure, what's up?")
        await bob.wait_for(lambda: "carol: Sure, what's up?" in self.chat_lines(bob), "reply")
        self.assertIn("carol: Sure, what's up?", self.chat_lines(carol))

        # Closing one side ends it; the other reads on but can't send.
        carol.close_box(self.chat_win(carol).id)
        await bob.wait_for(lambda: "* carol left the chat" in self.chat_lines(bob), "left")
        await self.say(bob, "Still there?")
        await bob.wait_for(lambda: "* The chat has ended." in self.chat_lines(bob), "ended")
        self.assertNotIn("bob: Still there?", self.chat_lines(bob))
        bob.close_box(self.chat_win(bob).id)
        await self.roundtrip(bob)
        self.assertEqual(self.server.screens.pages.chats, [])

    async def test_cancel_and_queue(self):
        alice = self.alice
        dave = await self.signed_on("dave")
        erin = await self.signed_on("erin")
        dave.pick("Page Admin")
        await dave.wait_window("Page Admin")
        await alice.wait_for(lambda: alice.hint(SLOT_PAGE) == "dave is paging you", "1 page")
        erin.pick("Page Admin")
        await erin.wait_window("Page Admin")
        await alice.wait_for(lambda: alice.hint(SLOT_PAGE) == "2 users are paging", "2 pages")
        self.bob.pick("Page Admin")
        await alice.wait_for(lambda: alice.hint(SLOT_PAGE) == "3 users are paging", "3 pages")
        # Cancel withdraws bob's page.
        self.bob.click_text(WIN_PAGING, "Cancel")
        await alice.wait_for(lambda: alice.hint(SLOT_PAGE) == "2 users are paging", "cancelled")
        self.assertNotIn(WIN_PAGING, self.bob.windows)
        # The icon opens the oldest page: dave's.
        alice.notify_click(SLOT_PAGE)
        await dave.wait_for(lambda: self.chat_win(dave), "dave's chat")
        await alice.wait_for(lambda: alice.hint(SLOT_PAGE) == "erin is paging you", "1 left")
        self.assertIn(WIN_PAGING, erin.windows)
        self.assertEqual(self.chat_win(alice).title, "Chat with dave")
        # A second chat at the same time gets its own window id.
        alice.notify_click(SLOT_PAGE)
        await erin.wait_for(lambda: self.chat_win(erin), "erin's chat")
        await alice.wait_for(lambda: alice.icon(SLOT_PAGE) == Icon.NONE, "no pages left")
        await alice.wait_for(lambda: len([w for w in alice.windows.values()
                                          if w.done and w.title.startswith("Chat with")]) == 2,
                             "two chats")
        self.assertEqual(len({w.id for w in alice.windows.values()
                              if w.title.startswith("Chat with")}), 2)
        # Signing off ends the chat for the other side.
        await dave.close()
        self.clients.remove(dave)
        chat = next(w for w in alice.windows.values() if w.title == "Chat with dave")
        await alice.wait_for(lambda: "* dave left the chat" in
                             chat.gadgets[gadget_of(chat, Kind.TEXTVIEW)]["lines"], "dave left")

    async def test_forged_notify_clicks(self):
        bob = self.bob
        dave = await self.signed_on("dave")
        dave.pick("Page Admin")
        await self.alice.wait_for(lambda: self.alice.icon(SLOT_PAGE) == Icon.PAGE, "page")
        for slot in (SLOT_PAGE, SLOT_ADMIN_MAIL, SLOT_MAIL, 3, 200):
            bob.notify_click(slot)
        bob.pick_id(M_ADMIN_MSGS)
        await self.roundtrip(bob)
        self.assertIsNone(self.chat_win(bob))
        self.assertNotIn(WIN_ADMIN_MSGS, bob.windows)
        self.assertEqual(bob.alerts, [])
        # Past the session's check, straight at the handler: refused for want of admin.pages.
        self.server.screens.pages.notify_click(self.session("bob"), SLOT_PAGE)
        self.server.screens.pages.open_messages(self.session("bob"))
        await bob.wait_for(lambda: bob.alerts, "refusal")
        self.assertEqual(len(self.server.screens.pages.queue), 1, "dave still waiting")
        self.assertIn(WIN_PAGING, dave.windows)
        # An admin whose permission went (the icon still on screen) is refused too.
        self.session("alice").perms = frozenset({"chat.use"})
        self.alice.notify_click(SLOT_PAGE)
        await self.alice.wait_for(lambda: self.alice.icon(SLOT_PAGE) == Icon.NONE, "icon gone")
        self.assertIsNone(self.chat_win(self.alice))
        self.assertEqual(len(self.server.screens.pages.queue), 1)

    async def test_last_admin_leaves(self):
        self.bob.pick("Page Admin")
        await self.alice.wait_for(lambda: self.alice.icon(SLOT_PAGE) == Icon.PAGE, "page")
        await self.alice.close()
        self.clients.remove(self.alice)
        await self.bob.wait_for(lambda: has_text(self.bob, WIN_NO_ADMIN, "No admin is "
                                                 "available right now."), "no-admin dialog")
        self.assertNotIn(WIN_PAGING, self.bob.windows)
        self.assertEqual(self.server.screens.pages.queue, [])


class PageOfflineTest(PagesBase):
    async def test_leave_a_message_then_admin_reads_it(self):
        bob, d = self.bob, self.server.db
        await self.sign_off(self.alice)
        bob.pick("Page Admin")
        await bob.wait_for(lambda: has_text(bob, WIN_NO_ADMIN, "No admin is available right "
                                            "now."), "no admin")
        dialog = bob.windows[WIN_NO_ADMIN]
        self.assertEqual(dialog.pos, ui.centre(400, 52))
        dialog.find("Would you like to leave a message for the admins?")
        bob.click_text(WIN_NO_ADMIN, "Yes")
        win = await bob.wait_window("Message to the Admins")
        self.assertEqual(win.id, WIN_TO_ADMINS)
        self.assertEqual(win.pos, ui.centre(544, 152))
        subject, body = gadget_of(win, Kind.TEXTBOX, 0), gadget_of(win, Kind.EDIT)
        bob.click_text(WIN_TO_ADMINS, "Send")
        await bob.wait_for(lambda: status_of(win) == "Write something first.", "empty")
        bob.value(WIN_TO_ADMINS, subject, "Can't download")
        bob.text(WIN_TO_ADMINS, body, ["The File Library is missing.", "Can you help?"])
        bob.click_text(WIN_TO_ADMINS, "Send")
        await bob.wait_for(lambda: bob.alerts, "thanks")
        self.assertNotIn(WIN_TO_ADMINS, bob.windows)
        self.assertEqual(bob.alerts[-1], ("Message Sent", "Your message is waiting for the admins."))
        msgs = d.admin_messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual((msgs[0]["name"], msgs[0]["subject"], msgs[0]["text"], msgs[0]["read"]),
                         ("bob", "Can't download", "The File Library is missing.\nCan you help?",
                          0))

        alice = await self.sign_in("alice")
        await alice.wait_for(lambda: alice.icon(SLOT_ADMIN_MAIL) == Icon.MAIL, "mail icon")
        self.assertEqual(alice.hint(SLOT_ADMIN_MAIL), "1 message from users")
        self.assertEqual(bob.icon(SLOT_ADMIN_MAIL), Icon.NONE)
        alice.notify_click(SLOT_ADMIN_MAIL)
        win = await alice.wait_window("Messages from users")
        self.assertEqual(win.pos, ui.centre(632, 152))
        listbox = gadget_of(win, Kind.LISTBOX)
        rows = win.gadgets[listbox]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].startswith("bob ") and rows[0].endswith(" *"), rows)
        self.assertLessEqual(len(rows[0]), ui.ListBox.ROW_MAX)
        alice.select(WIN_ADMIN_MSGS, listbox, 0)

        def shown():
            w = alice.windows.get(WIN_ADMIN_MSGS)
            return w and w.done and "Can you help?" in w.gadgets[gadget_of(w, Kind.TEXTVIEW)][
                "lines"]
        await alice.wait_for(shown, "message shown")
        win = alice.windows[WIN_ADMIN_MSGS]
        lines = win.gadgets[gadget_of(win, Kind.TEXTVIEW)]["lines"]
        self.assertEqual(lines[0], "From: bob")
        self.assertIn("Subject: Can't download", lines)
        await alice.wait_for(lambda: alice.icon(SLOT_ADMIN_MAIL) == Icon.NONE, "icon gone")
        self.assertEqual(d.admin_messages()[0]["read"], 1)
        await alice.wait_for(lambda: win.gadgets[gadget_of(win, Kind.LISTBOX)]["rows"][0]
                             .endswith(":%s" % rows[0][-4:-2]), "read mark")

        # Mark as Unread: the star and the envelope come back; picking it reads it again.
        alice.click_text(WIN_ADMIN_MSGS, "Mark as Unread")
        await alice.wait_for(lambda: has_text(alice, WIN_ADMIN_MSGS, "Marked as unread."),
                             "marked")
        await alice.wait_for(lambda: alice.icon(SLOT_ADMIN_MAIL) == Icon.MAIL, "icon back")
        self.assertEqual(d.admin_messages()[0]["read"], 0)
        await alice.wait_for(lambda: win.gadgets[gadget_of(win, Kind.LISTBOX)]["rows"][0]
                             .endswith(" *"), "unread mark")
        alice.select(WIN_ADMIN_MSGS, gadget_of(win, Kind.LISTBOX), 0)
        await alice.wait_for(lambda: alice.icon(SLOT_ADMIN_MAIL) == Icon.NONE, "read again")
        self.assertEqual(d.admin_messages()[0]["read"], 1)

        # Reply: the private-message composer, to bob, "Re: ..."; it lands in his inbox.
        alice.click_text(WIN_ADMIN_MSGS, "Reply...")
        comp = await alice.wait_window("New Message")
        to_box, subj_box = gadget_of(comp, Kind.TEXTBOX, 0), gadget_of(comp, Kind.TEXTBOX, 1)
        self.assertEqual(comp.text(to_box), "bob")
        self.assertEqual(comp.text(subj_box), "Re: Can't download")
        alice.text(WIN_COMPOSE, gadget_of(comp, Kind.EDIT), ["Fixed now.", "Try again."])
        n = len(alice.alerts)
        alice.click_text(WIN_COMPOSE, "Send")
        await alice.wait_for(lambda: len(alice.alerts) > n, "sent")
        self.assertEqual(alice.alerts[-1], ("Message Sent", "Your message to bob has been sent."))
        self.assertNotIn(WIN_COMPOSE, alice.windows)
        got = d.inbox(d.user("bob")["id"])
        self.assertEqual([(m["from_name"], m["subject"], m["body"]) for m in got],
                         [("alice", "Re: Can't download", "Fixed now.\nTry again.")])
        await bob.wait_for(lambda: bob.icon(SLOT_MAIL) == Icon.MAIL, "bob's envelope")
        alerts_before = len(alice.alerts)

        # A new message while she's signed on: the icon comes back.
        d.add_admin_message(d.user("bob")["id"], "", ["One more thing"])
        self.server.screens.pages.messages_changed()
        await alice.wait_for(lambda: alice.icon(SLOT_ADMIN_MAIL) == Icon.MAIL, "icon again")
        # Delete the read one.
        alice.click_text(WIN_ADMIN_MSGS, "Delete")
        await alice.wait_for(lambda: has_text(alice, WIN_ADMIN_MSGS, "Deleted."), "deleted")
        self.assertEqual([m["text"] for m in d.admin_messages()], ["One more thing"])
        # Without admin.pages the window's handlers refuse.
        self.session("alice").perms = frozenset({"chat.use"})
        win = alice.windows[WIN_ADMIN_MSGS]
        alice.select(WIN_ADMIN_MSGS, gadget_of(win, Kind.LISTBOX), 0)   # refused: not picked
        alice.click_text(WIN_ADMIN_MSGS, "Delete")       # so Delete stays greyed: ignored
        await alice.wait_for(lambda: len(alice.alerts) == alerts_before + 1, "refusal")
        self.assertFalse(alice.enabled(WIN_ADMIN_MSGS, "Delete"))
        self.assertEqual(len(d.admin_messages()), 1)
        self.assertEqual(d.admin_messages()[0]["read"], 0)

    async def test_admin_paging_with_no_other_admin(self):
        """An admin who pages, with no other admin on, gets the message flow."""
        self.alice.pick("Page Admin")
        await self.alice.wait_for(lambda: WIN_NO_ADMIN in self.alice.windows, "no admin")
        self.alice.click_text(WIN_NO_ADMIN, "No")
        await self.alice.wait_for(lambda: WIN_NO_ADMIN not in self.alice.windows, "closed")
