"""Areas > Private Messages: send to a user who is signed off (the envelope icon at sign-on),
read, reply, the Sent folder, delete on each side, unknown recipients, and mail.use enforced."""
import re

from meganet import permissions, ui
from meganet.mail import WIN_INBOX, WIN_COMPOSE, message_row
from meganet.protocol import Kind, Icon, SLOT_MAIL
from meganet.screens import M_MAIL
from tests.test_pages import PagesBase
from tests.test_roles import gadget_of, has_text, status_of


DATE = re.compile(r" +\d\d-\d\d \d\d:\d\d")     # (rows: name, subject, date, " *")


class MailTest(PagesBase):
    def boxes(self, c):
        win = c.windows[WIN_COMPOSE]
        return win, [gadget_of(win, Kind.TEXTBOX, i) for i in range(2)]   # to, subject

    def body(self, c):
        return gadget_of(c.windows[WIN_COMPOSE], Kind.EDIT)

    async def compose(self, c, to, subject, lines, opened=False):
        """Write and send a message from the New Message window (opened from the inbox)."""
        if not opened:
            c.click_text(WIN_INBOX, "New...")
        await c.wait_window("New Message")
        win, (to_box, subj_box) = self.boxes(c)
        if to is not None:
            c.value(WIN_COMPOSE, to_box, to)
        if subject is not None:
            c.value(WIN_COMPOSE, subj_box, subject)
        c.text(WIN_COMPOSE, self.body(c), lines)        # the text area's lines
        n = len(c.alerts)
        c.click_text(WIN_COMPOSE, "Send")
        return win, n

    async def inbox(self, c):
        c.pick("Private Messages")
        return await c.wait_window("Private Messages")

    def rows(self, c):
        """The inbox rows without their date and time (checked to be there)."""
        win = c.windows[WIN_INBOX]
        rows = win.gadgets[gadget_of(win, Kind.LISTBOX)]["rows"]
        for r in rows:
            assert DATE.search(r), r
        return [DATE.sub("", r).rstrip() for r in rows]

    def view(self, c):
        win = c.windows.get(WIN_INBOX)
        return win.gadgets[gadget_of(win, Kind.TEXTVIEW)]["lines"] if win and win.done else []

    async def read(self, c, index, expect):
        c.select(WIN_INBOX, gadget_of(c.windows[WIN_INBOX], Kind.LISTBOX), index)
        await c.wait_for(lambda: expect in self.view(c), "message shown")
        return self.view(c)

    async def test_send_read_reply_sent_delete(self):
        alice, d = self.alice, self.server.db
        await self.sign_off(self.bob)
        self.assertEqual(self.alice.menu_items("Areas")[3], "Private Messages")
        win = await self.inbox(alice)
        self.assertEqual(win.pos, ui.centre(ui.AREA_W, ui.AREA_H))
        win.find("Inbox: 0 messages, 0 unread")
        win, n = await self.compose(alice, "BOB", "Hello", ["Hi Bob,", "", "Chess on Friday?"])
        self.assertEqual(win.pos, ui.centre(544, 168))
        await alice.wait_for(lambda: len(alice.alerts) > n, "sent")
        self.assertEqual(alice.alerts[-1], ("Message Sent", "Your message to bob has been sent."))
        self.assertNotIn(WIN_COMPOSE, alice.windows)

        bob = await self.sign_in("bob")
        await bob.wait_for(lambda: bob.icon(SLOT_MAIL) == Icon.MAIL, "envelope at sign-on")
        self.assertEqual(bob.hint(SLOT_MAIL), "1 unread private message")
        bob.notify_click(SLOT_MAIL)
        win = await bob.wait_window("Private Messages")
        self.assertEqual(self.rows(bob), ["alice      Hello *"])
        self.assertTrue(all(len(r) <= ui.ListBox.ROW_MAX for r in self.rows(bob)))
        win.find("Inbox: 1 message, 1 unread")
        lines = await self.read(bob, 0, "Chess on Friday?")
        self.assertEqual(lines[0], "From: alice")
        self.assertTrue(lines[1].startswith("Date: "))
        self.assertEqual(lines[2:], ["Subject: Hello", "", "Hi Bob,", "", "Chess on Friday?"])
        await bob.wait_for(lambda: bob.icon(SLOT_MAIL) == Icon.NONE, "icon gone")
        self.assertEqual(self.rows(bob), ["alice      Hello"])

        # Mark as Unread: the star, the count and the envelope come back; the message stays
        # on show; picking it again reads it.
        bob.click_text(WIN_INBOX, "Mark as Unread")
        await bob.wait_for(lambda: has_text(bob, WIN_INBOX, "Marked as unread."), "marked")
        self.assertEqual(self.rows(bob), ["alice      Hello *"])
        bob.windows[WIN_INBOX].find("Inbox: 1 message, 1 unread")
        await bob.wait_for(lambda: bob.icon(SLOT_MAIL) == Icon.MAIL, "envelope back")
        self.assertIn("Chess on Friday?", self.view(bob))
        await self.read(bob, 0, "Chess on Friday?")
        await bob.wait_for(lambda: bob.icon(SLOT_MAIL) == Icon.NONE, "read again")
        self.assertEqual(self.rows(bob), ["alice      Hello"])

        # Reply: To and "Re: subject" filled in; alice (signed on) gets the icon.
        bob.click_text(WIN_INBOX, "Reply...")
        await bob.wait_window("New Message")
        cwin, (to_box, subj_box) = self.boxes(bob)
        self.assertEqual((cwin.text(to_box), cwin.text(subj_box)), ("alice", "Re: Hello"))
        _, n = await self.compose(bob, None, None, ["Yes please!"], opened=True)
        await bob.wait_for(lambda: len(bob.alerts) > n, "sent")
        await alice.wait_for(lambda: alice.icon(SLOT_MAIL) == Icon.MAIL, "alice's envelope")
        await alice.wait_for(lambda: self.rows(alice) == ["bob        Re: Hello *"],
                             "alice's open inbox updated")

        # The Sent folder, and back.
        bob.click_text(WIN_INBOX, "Show Sent")
        await bob.wait_for(lambda: has_text(bob, WIN_INBOX, "Sent: 1 message"), "sent folder")
        self.assertEqual(self.rows(bob), ["alice      Re: Hello"])
        bob.windows[WIN_INBOX].find("Show Inbox")
        lines = await self.read(bob, 0, "Yes please!")
        self.assertEqual(lines[0], "To: alice")
        bob.click_text(WIN_INBOX, "Show Inbox")
        await bob.wait_for(lambda: has_text(bob, WIN_INBOX, "Inbox: 1 message, 0 unread"),
                           "inbox again")

        # Delete on each side: bob deletes the message he got; alice still has it in Sent.
        first = d.inbox(d.user("bob")["id"])[0]["id"]
        await self.read(bob, 0, "Chess on Friday?")
        bob.click_text(WIN_INBOX, "Delete")
        await bob.wait_for(lambda: has_text(bob, WIN_INBOX, "Inbox: 0 messages, 0 unread"),
                           "deleted")
        self.assertEqual(d.inbox(d.user("bob")["id"]), [])
        self.assertEqual([m["id"] for m in d.sent_messages(d.user("alice")["id"])], [first])
        alice.click_text(WIN_INBOX, "Show Sent")
        await alice.wait_for(lambda: has_text(alice, WIN_INBOX, "Sent: 1 message"), "her Sent")
        await self.read(alice, 0, "Chess on Friday?")
        alice.click_text(WIN_INBOX, "Delete")
        await alice.wait_for(lambda: has_text(alice, WIN_INBOX, "Sent: 0 messages"), "deleted")
        self.assertIsNone(d.private_message(first), "gone once both sides deleted it")
        self.assertEqual(alice.icon(SLOT_MAIL), Icon.MAIL, "bob's reply is still unread")

    async def test_compose_checks(self):
        bob = self.bob
        await self.inbox(bob)
        win, _ = await self.compose(bob, "nobody", "Hi", ["Hello?"])
        await bob.wait_for(lambda: status_of(win) == "There is no user called nobody.", "unknown")
        self.assertEqual(self.server.db.inbox(self.server.db.user("alice")["id"]), [])
        # An empty message is refused; the window stays, so the To box can be fixed.
        to_box = self.boxes(bob)[1][0]
        bob.text(WIN_COMPOSE, self.body(bob), ["", "  "])
        bob.click_text(WIN_COMPOSE, "Send")
        await bob.wait_for(lambda: status_of(win) == "Write something first.", "empty")
        bob.value(WIN_COMPOSE, to_box, "Alice")
        bob.text(WIN_COMPOSE, self.body(bob), ["Hello?", ""])
        n = len(bob.alerts)
        bob.click_text(WIN_COMPOSE, "Send")
        await bob.wait_for(lambda: len(bob.alerts) > n, "sent")
        self.assertNotIn(WIN_COMPOSE, bob.windows, "Send closes the window")
        self.assertEqual(bob.alerts[-1], ("Message Sent", "Your message to alice has been sent."))
        msgs = self.server.db.inbox(self.server.db.user("alice")["id"])
        self.assertEqual([(m["from_name"], m["subject"], m["body"]) for m in msgs],
                         [("bob", "Hi", "Hello?")])
        self.assertEqual(DATE.sub("", message_row(msgs[0], False)).rstrip(), "bob        Hi *")
        self.assertEqual(DATE.sub("", message_row(msgs[0], True)).rstrip(), "alice      Hi")
        self.assertLessEqual(len(message_row(msgs[0], False)), 47, "fits the width of the list")

    async def test_without_mail_use(self):
        d = self.server.db
        nu = d.role_by_name("New User")["id"]
        self.assertIn(permissions.MAIL_USE, d.role_permissions(nu), "New User has it")
        d.send_private_message(d.user("alice")["id"], d.user("bob")["id"], "x", ["y"])
        self.server.screens.mail.changed(d.user("bob")["id"])
        await self.bob.wait_for(lambda: self.bob.icon(SLOT_MAIL) == Icon.MAIL, "envelope")
        await self.inbox(self.bob)
        self.assertIsNone(d.set_role_permissions(nu, d.role_permissions(nu) -
                                                 {permissions.MAIL_USE}))
        self.server.permissions_changed(role_id=nu)
        bob = self.bob
        await bob.wait_for(lambda: "Private Messages" not in bob.menu_items("Areas"), "menu")
        await bob.wait_for(lambda: WIN_INBOX not in bob.windows, "inbox closed")
        await bob.wait_for(lambda: bob.icon(SLOT_MAIL) == Icon.NONE, "envelope gone")
        # Forged: the menu id, the icon, clicks in windows he hasn't got.
        bob.pick_id(M_MAIL)
        bob.notify_click(SLOT_MAIL)
        for win in (WIN_INBOX, WIN_COMPOSE):
            for gid in range(1, 12):
                bob.click(win, gid)
        await self.roundtrip(bob)
        self.assertNotIn(WIN_INBOX, bob.windows)
        self.assertEqual(bob.alerts, [])
        # Straight at the module, and an inbox left open after the key went.
        mail = self.server.screens.mail
        mail.open_inbox(self.session("bob"))
        await bob.wait_for(lambda: bob.alerts, "refusal")
        self.assertEqual(bob.alerts[-1], ("Private Messages",
                                          "Your account can't use Private Messages."))
        self.assertNotIn(WIN_INBOX, bob.windows)
        alice = self.alice
        await self.inbox(alice)
        self.session("alice").perms = frozenset({"chat.use"})
        self.assertFalse(alice.enabled(WIN_INBOX, "Reply..."), "nothing picked: greyed")
        for button in ("New...", "Reply...", "Delete", "Show Sent"):   # (2 greyed: ignored)
            alice.click_text(WIN_INBOX, button)
        await alice.wait_for(lambda: len(alice.alerts) == 2, "2 refusals")
        self.assertNotIn(WIN_COMPOSE, alice.windows)
