"""The Status menu (Available / Away / Offline), Auto-Away, Who's Online with statuses,
instant messages (toast + speech-bubble icon), and Admin > System Settings."""

from meganet import im
from meganet.account import WIN_ACCOUNT
from meganet.admin import WIN_SETTINGS
from meganet.mail import WIN_COMPOSE, WIN_INBOX
from meganet.protocol import Kind, Icon, MENU_MY_ACCOUNT, SLOT_IM, SLOT_STATUS, Sound
from meganet.session import RING_GAP
from meganet.screens import WIN_WHO, M_AVAILABLE, M_AWAY, M_OFFLINE
from tests.test_pages import PagesBase
from tests.test_roles import gadget_of, status_of


class PresenceBase(PagesBase):
    def who_rows(self, c):
        w = c.windows.get(WIN_WHO)
        return w.gadgets[gadget_of(w, Kind.LISTBOX)]["rows"] if w and w.done else []

    async def open_who(self, c):
        c.windows.pop(WIN_WHO, None)
        c.pick("Who's Online")
        return await c.wait_window("Who's Online")

    def set_role(self, name, role):
        d = self.server.db
        self.assertIsNone(d.set_user_role(d.user(name)["id"], d.role_by_name(role)["id"]))
        self.server.permissions_changed(user_id=d.user(name)["id"])

    async def pick_who(self, c, name):
        await c.wait_for(lambda: any(r.startswith(name) for r in self.who_rows(c)), name)
        w = c.windows[WIN_WHO]
        i = next(i for i, r in enumerate(self.who_rows(c)) if r.startswith(name))
        c.select(WIN_WHO, gadget_of(w, Kind.LISTBOX), i)


class StatusTest(PresenceBase):
    async def test_status_menu_and_whos_online(self):
        alice, bob = self.alice, self.bob                  # alice: Sysop (an admin)
        self.assertEqual(bob.menu_items("Status"), ["* Available", "  Away", "  Offline"])
        await self.open_who(bob)
        await self.open_who(alice)
        self.assertEqual(self.who_rows(bob), ["alice      (Available)", "bob        (Available)"])
        self.assertTrue(self.who_rows(alice)[0].startswith("alice      (Available) Sysop"))

        alice.pick_id(M_AWAY)
        await bob.wait_for(lambda: "alice      (Away)" in self.who_rows(bob), "alice away")
        await alice.wait_for(lambda: alice.menu_items("Status")[1] == "* Away", "marked")
        # Offline: gone for bob, still there (marked) for the admin herself
        alice.pick_id(M_OFFLINE)
        await bob.wait_for(lambda: self.who_rows(bob) == ["bob        (Available)"], "hidden")
        await alice.wait_for(lambda: any("(Offline)" in r for r in self.who_rows(alice)), "x")
        # bob Offline: the admin still sees him, marked
        bob.pick_id(M_OFFLINE)
        await alice.wait_for(lambda: any(r.startswith("bob        (Offline)")
                                         for r in self.who_rows(alice)), "bob offline")
        # User Search's "*" (signed on now) follows too
        carol = await self.signed_on("carol")
        carol.pick("User Search...")
        s = await carol.wait_window("User Search")
        carol.click_text(s.id, "Search")
        rows = lambda: s.gadgets[gadget_of(s, Kind.LISTBOX)]["rows"]
        await carol.wait_for(lambda: len(rows()) == 3, "everyone")
        self.assertFalse(any(r.endswith(" *") for r in rows() if r.startswith(("alice", "bob"))))
        alice.pick_id(M_AVAILABLE)
        await bob.wait_for(lambda: "alice      (Available)" in self.who_rows(bob), "back")

    async def test_status_dot(self):
        bob, s = self.bob, self.session("bob")
        dot = lambda: (bob.icon(SLOT_STATUS), bob.hint(SLOT_STATUS))
        await bob.wait_for(lambda: dot() == (Icon.AVAILABLE, "Status: Available"), "green")
        bob.notify_click(SLOT_STATUS)                    # click: Away
        await bob.wait_for(lambda: dot() == (Icon.AWAY, "Status: Away"), "yellow")
        self.assertEqual(bob.menu_items("Status")[1], "* Away")
        bob.notify_click(SLOT_STATUS)                    # and back
        await bob.wait_for(lambda: bob.icon(SLOT_STATUS) == Icon.AVAILABLE, "green again")
        bob.pick_id(M_OFFLINE)                           # the menu moves it too
        await bob.wait_for(lambda: bob.icon(SLOT_STATUS) == Icon.OFFLINE, "grey")
        bob.notify_click(SLOT_STATUS)                    # Offline -> Available
        await bob.wait_for(lambda: bob.icon(SLOT_STATUS) == Icon.AVAILABLE, "from offline")
        # Auto-Away: the click itself isn't the activity that ends it, and goes to Available
        presence = self.server.screens.presence
        presence.set_away_minutes(1)
        s.last_active -= 120
        presence.check()
        await bob.wait_for(lambda: bob.icon(SLOT_STATUS) == Icon.AWAY, "auto away")
        bob.notify_click(SLOT_STATUS)
        await bob.wait_for(lambda: bob.icon(SLOT_STATUS) == Icon.AVAILABLE, "auto ended")
        await self.roundtrip(bob)
        self.assertEqual((s.status, s.auto_away), ("available", False))

    async def test_auto_away(self):
        presence, bob = self.server.screens.presence, self.bob
        s = self.session("bob")
        presence.set_away_minutes(1)
        s.last_active -= 30
        presence.check()
        self.assertEqual(s.status, "available", "not yet")
        s.last_active -= 60
        presence.check()
        self.assertEqual((s.status, s.auto_away), ("away", True))
        await bob.wait_for(lambda: bob.menu_items("Status")[1] == "* Away", "bob's menu")
        await self.open_who(bob)                         # any activity: Available again
        await bob.wait_for(lambda: bob.menu_items("Status")[0] == "* Available", "back")
        # Away picked by hand stays, activity or not; 0 minutes turns Auto-Away off
        bob.pick_id(M_AWAY)
        await bob.wait_for(lambda: s.status == "away", "away by hand")
        await self.open_who(bob)
        self.assertEqual(s.status, "away")
        bob.pick_id(M_AVAILABLE)
        await bob.wait_for(lambda: s.status == "available", "available")
        presence.set_away_minutes(0)
        s.last_active -= 10000
        presence.check()
        self.assertEqual(s.status, "available")

    async def test_offline_admin_is_not_paged(self):
        self.alice.pick_id(M_OFFLINE)
        await self.alice.wait_for(lambda: self.session("alice").status == "offline", "offline")
        self.bob.pick("Page Admin")
        await self.bob.wait_window("Page Admin")
        self.assertTrue(any(g["text"] == "No admin is available right now."
                            for g in self.bob.windows[14].gadgets.values()))


class InstantMessageTest(PresenceBase):
    async def test_send_toast_icon_reply(self):
        alice, bob = self.alice, self.bob
        # bob (New User) has no im.send: Send Message... stays greyed
        await self.open_who(bob)
        await self.pick_who(bob, "alice")
        await bob.wait_for(lambda: bob.windows[WIN_WHO].done, "who")
        await self.roundtrip(bob)
        self.assertFalse(bob.enabled(WIN_WHO, "Send Message..."))
        self.assertEqual(status_of(bob.windows[WIN_WHO]), "New users can't send messages.")
        self.set_role("bob", "Member")
        await self.open_who(bob)
        await self.pick_who(bob, "alice")
        await bob.wait_for(lambda: bob.enabled(WIN_WHO, "Send Message..."), "enabled")
        bob.click_text(WIN_WHO, "Send Message...")
        im = await bob.wait_window("IM: alice")
        bob.value(im.id, gadget_of(im, Kind.TEXTBOX), "hi alice")
        bob.click_text(im.id, "Send")
        view = lambda c, w: c.windows[w.id].gadgets[gadget_of(w, Kind.TEXTVIEW)]["lines"]
        await bob.wait_for(lambda: "bob: hi alice" in view(bob, im), "bob's own line")
        # alice: a toast and the bubble, no window
        await alice.wait_for(lambda: alice.toasts, "toast")
        self.assertEqual(alice.toasts[-1], (8, SLOT_IM, "IM from bob: hi alice"))
        await alice.wait_for(lambda: alice.icon(SLOT_IM) == Icon.BUBBLE, "bubble")
        self.assertEqual(alice.hint(SLOT_IM), "1 new message from bob")
        self.assertFalse(any(w.title.startswith("IM:") for w in alice.windows.values()))
        # the icon (or the toast) opens the conversation; it's read now
        alice.notify_click(SLOT_IM)
        aim = await alice.wait_window("IM: bob")
        self.assertEqual(view(alice, aim), ["bob: hi alice"])
        await alice.wait_for(lambda: alice.icon(SLOT_IM) == Icon.NONE, "icon gone")
        # alice answers: bob's window is open, so no toast for him
        alice.value(aim.id, gadget_of(aim, Kind.TEXTBOX), "hello bob")
        alice.click_text(aim.id, "Send")
        await bob.wait_for(lambda: "alice: hello bob" in view(bob, im), "reply")
        self.assertEqual(bob.toasts, [])
        # a New User can't send, but gets messages and opens them (Send greyed)
        carol = await self.signed_on("carol")
        self.server.screens.ims.send(self.session("bob"), self.session("carol"), "hi carol")
        await carol.wait_for(lambda: carol.icon(SLOT_IM) == Icon.BUBBLE, "carol's bubble")
        carol.notify_click(SLOT_IM)
        cim = await carol.wait_window("IM: bob")
        self.assertEqual(view(carol, cim), ["bob: hi carol", "* New users can't send messages."])
        self.assertFalse(carol.enabled(cim.id, "Send"))
        # alice goes Away: bob is told once; Offline: bob can't reach her
        alice.pick_id(M_AWAY)
        await alice.wait_for(lambda: self.session("alice").status == "away", "away")
        for text in ("one", "two"):
            bob.value(im.id, gadget_of(im, Kind.TEXTBOX), text)
            bob.click_text(im.id, "Send")
        await bob.wait_for(lambda: "bob: two" in view(bob, im), "sent")
        self.assertEqual(sum("is away" in l for l in view(bob, im)), 1)
        alice.pick_id(M_OFFLINE)
        await alice.wait_for(lambda: self.session("alice").status == "offline", "offline")
        bob.value(im.id, gadget_of(im, Kind.TEXTBOX), "three")
        bob.click_text(im.id, "Send")
        await bob.wait_for(lambda: "* alice isn't signed on." in view(bob, im), "refused")
        self.assertNotIn("bob: three", view(alice, aim))


class DoorbellTest(PresenceBase):
    """A new instant or private message rings the doorbell (Sound.DOORBELL): always while
    Available, while Away only with My Account's "Ring when Away" (on by default), and once
    for a burst."""

    def rings(self, c):
        return c.sounds.count(Sound.DOORBELL)

    async def test_instant_messages(self):
        alice, bob = self.alice, self.bob
        ims, a, b = self.server.screens.ims, self.session("alice"), self.session("bob")
        ims.send(b, a, "hello")                          # (her window isn't open)
        await alice.wait_for(lambda: self.rings(alice) == 1, "the doorbell")
        ims.send(b, a, "are you there?")                 # (a burst: once)
        await self.roundtrip(alice)
        self.assertEqual(self.rings(alice), 1)
        a.last_ring = -RING_GAP                          # (later)
        alice.pick_id(M_AWAY)                            # Away: rings (the default is on)
        await alice.wait_for(lambda: a.status == "away", "away")
        ims.send(b, a, "knock knock")
        await alice.wait_for(lambda: self.rings(alice) == 2, "rings while Away")
        a.last_ring, a.ring_away = -RING_GAP, False      # unticked: Away is quiet
        ims.send(b, a, "anyone?")
        await self.roundtrip(alice)
        self.assertEqual(self.rings(alice), 2)
        alice.pick_id(M_AVAILABLE)                       # back: rings whatever the option
        await alice.wait_for(lambda: a.status == "available", "available")
        ims.send(b, a, "there you are")
        await alice.wait_for(lambda: self.rings(alice) == 3, "rings when Available")
        self.assertEqual(self.rings(bob), 0, "not the sender")

    async def test_private_message_and_the_option(self):
        alice, bob = self.alice, self.bob
        a = self.session("alice")
        bob.pick("Private Messages")
        await bob.wait_window("Private Messages")
        bob.click_text(WIN_INBOX, "New...")
        win = await bob.wait_window("New Message")
        bob.value(WIN_COMPOSE, gadget_of(win, Kind.TEXTBOX, 0), "alice")
        bob.value(WIN_COMPOSE, gadget_of(win, Kind.TEXTBOX, 1), "hi")
        bob.text(WIN_COMPOSE, gadget_of(win, Kind.EDIT), ["ding dong"])
        bob.click_text(WIN_COMPOSE, "Send")
        await alice.wait_for(lambda: self.rings(alice) == 1, "the doorbell for mail")
        # My Account: the box, ticked; untick it and OK: saved, and the session follows
        alice.pick_id(MENU_MY_ACCOUNT)
        acc = await alice.wait_window("My Account")
        box = gadget_of(acc, Kind.CHECKBOX)
        self.assertEqual(acc.gadgets[box]["text"], "Ring when Away")
        self.assertEqual(acc.gadgets[box].get("value"), 1, "on by default")
        alice.select(WIN_ACCOUNT, box, 0)
        for i, name in enumerate(("Alice", "Smith")):    # (required to save)
            alice.value(WIN_ACCOUNT, gadget_of(acc, Kind.TEXTBOX, i), name)
        alice.click_text(WIN_ACCOUNT, "OK")
        await alice.wait_for(lambda: WIN_ACCOUNT not in alice.windows, "saved")
        self.assertFalse(a.ring_away)
        self.assertEqual(self.server.db.user("alice")["ring_away"], 0)
        alice.pick_id(MENU_MY_ACCOUNT)
        acc = await alice.wait_window("My Account")
        self.assertFalse(acc.gadgets[gadget_of(acc, Kind.CHECKBOX)].get("value"), "unticked")


class SettingsTest(PresenceBase):
    async def test_system_settings(self):
        alice = self.alice
        self.assertIn("System Settings...", alice.menu_items("Admin"))
        alice.pick("System Settings...")
        win = await alice.wait_window("System Settings")
        box = gadget_of(win, Kind.TEXTBOX)
        self.assertEqual(win.text(box), "10")
        alice.value(WIN_SETTINGS, box, "lots")
        alice.click_text(WIN_SETTINGS, "OK")
        await alice.wait_for(lambda: status_of(win).startswith("Auto-Away: a number"), "bad")
        alice.value(WIN_SETTINGS, box, "25")
        alice.click_text(WIN_SETTINGS, "OK")
        await alice.wait_for(lambda: WIN_SETTINGS not in alice.windows, "closed")
        self.assertEqual(self.server.screens.presence.away_minutes(), 25)
        self.assertNotIn("Admin", self.bob.menu_titles())

    async def test_new_user_im_settings(self):
        alice, bob = self.alice, self.bob                  # bob: New User
        carol = await self.signed_on("carol")              # carol: New User too
        self.set_role("carol", "Member")
        # defaults: New Users receive but don't send
        alice.pick("System Settings...")
        win = await alice.wait_window("System Settings")
        boxes = [g for g, v in win.gadgets.items() if v["kind"] == Kind.CHECKBOX]
        self.assertEqual([win.gadgets[g].get("value", 0) for g in boxes], [0, 1])
        # New Users may send now, and can't receive
        alice.select(WIN_SETTINGS, boxes[0], 1)
        alice.select(WIN_SETTINGS, boxes[1], 0)
        alice.click_text(WIN_SETTINGS, "OK")
        await alice.wait_for(lambda: WIN_SETTINGS not in alice.windows, "closed")
        await bob.wait_for(lambda: self.session("bob").can("im.send"), "bob can send")
        # carol picks bob (a New User): greyed, and the top line says why
        await self.open_who(carol)
        await self.pick_who(carol, "bob")
        await carol.wait_for(lambda: status_of(carol.windows[WIN_WHO]) ==
                             "New users can't receive messages.", "why")
        self.assertFalse(carol.enabled(WIN_WHO, "Send Message..."))
        # bob can send to carol (a Member)
        await self.open_who(bob)
        await self.pick_who(bob, "carol")
        await bob.wait_for(lambda: bob.enabled(WIN_WHO, "Send Message..."), "bob may send")
        self.assertEqual(status_of(bob.windows[WIN_WHO]), "3 signed on")
        # back to the defaults: bob's open Who's Online follows at once
        im.set_new_users_receive(self.server.db, True)
        self.assertIsNone(im.set_new_users_send(self.server.db, False))
        self.server.permissions_changed()
        self.server.screens.im_rules_changed()
        await bob.wait_for(lambda: not bob.enabled(WIN_WHO, "Send Message..."), "bob greyed")
        await bob.wait_for(lambda: status_of(bob.windows[WIN_WHO]) ==
                           "New users can't send messages.", "bob told")


class BroadcastTest(PresenceBase):
    async def test_broadcast(self):
        alice, bob = self.alice, self.bob                  # alice: Sysop
        self.assertNotIn("Broadcast...", bob.menu_items("Admin") if "Admin" in bob.menu_titles()
                         else [])
        alice.pick("Broadcast...")
        win = await alice.wait_window("Broadcast")
        self.assertFalse(alice.enabled(win.id, "Send"))    # nothing typed yet
        alice.value(win.id, gadget_of(win, Kind.TEXTBOX), "Server restart in 5 minutes")
        self.assertTrue(alice.enabled(win.id, "Send"))
        alice.click_text(win.id, "Send")
        line = (20, "To all users:  Server restart in 5 minutes")
        await bob.wait_for(lambda: line in bob.broadcasts, "bob got it")
        await alice.wait_for(lambda: line in alice.broadcasts, "and alice")
        self.assertNotIn(win.id, alice.windows)
        # bob can't send one, even by asking for the window
        self.server.screens.open_broadcast(self.session("bob"))
        await self.roundtrip(bob)
        self.assertFalse(any(w.title == "Broadcast" for w in bob.windows.values()))
