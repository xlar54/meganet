"""Skins (protocol.Skin, S.SKIN): the client's look. Sent at sign-on to clients from
SKIN_BUILD (never to older ones); picked in My Account's Preferences ("Look"), saved in
users.skin, sent at once with the desktop icons drawn again in its style (desktop.ICONS_PIN)."""

from meganet import desktop
from meganet.account import WIN_ACCOUNT
from meganet.protocol import (Kind, MENU_MY_ACCOUNT, S, Skin, SKIN_BUILD, SKIN_NAMES,
                              DESK_ICON_W, DESK_ICON_H)
from tests.test_server import ServerTest


class SkinTest(ServerTest):
    def look(self, win):
        """My Account's Look drop-down (the one after the birthdate's three), or None."""
        dd = [gid for gid, g in win.gadgets.items() if g["kind"] == Kind.DROPDOWN]
        return dd[3] if len(dd) > 3 else None

    async def open_account(self, c):
        """My Account, with the names filled in (OK needs them)."""
        c.windows.pop(WIN_ACCOUNT, None)
        c.pick_id(MENU_MY_ACCOUNT)
        win = await c.wait_window("My Account")
        boxes = [gid for gid, g in win.gadgets.items() if g["kind"] == Kind.TEXTBOX]
        for gid, text in zip(boxes[:2], ("Bob", "Smith")):
            c.value(WIN_ACCOUNT, gid, text)
        return win

    def icons_in(self, c, skin):
        """Whether every desktop icon the client has is that skin's picture."""
        by_label = {" ".join(x for x in label_lines if x): name for name, label_lines in
                    ((d[0], desktop.label_lines(d[1]))
                     for d in desktop.DESKTOP + desktop.DESKTOP_RIGHT)}
        return c.desk and all(
            px == desktop.pixels(by_label[" ".join(x for x in (one, two) if x)], skin)
            for one, two, px in c.desk.values())

    def test_every_picture_in_both_skins(self):
        for name in desktop.ICONS:
            for skin in SKIN_NAMES:
                self.assertEqual(len(desktop.pixels(name, skin)), DESK_ICON_W * DESK_ICON_H)
            self.assertIn(name, desktop.ICONS_PIN, "a Pinstripe picture for %s" % name)
            self.assertNotEqual(desktop.pixels(name, Skin.CLASSIC),
                                desktop.pixels(name, Skin.PINSTRIPE), name)
            used = {c for row in desktop.ICONS_PIN[name] for c in row}
            self.assertLessEqual(used, desktop.SKIN_STABLE,
                                 "%s uses a colour Dark redefines: %s"
                                 % (name, sorted(used - desktop.SKIN_STABLE)))

    async def test_classic_at_sign_on(self):
        c = await self.signed_on("alice", build=SKIN_BUILD)
        self.assertEqual(c.skins, [Skin.CLASSIC])
        self.assertLess(c.messages.index(S.SKIN), c.messages.index(S.MENU), "skin first")
        self.assertTrue(self.icons_in(c, Skin.CLASSIC))

    async def test_older_client_gets_no_skin(self):
        c = await self.signed_on("old", build=SKIN_BUILD - 1)    # (fakeclient asserts it)
        self.assertEqual(c.skins, [])
        win = await self.open_account(c)
        self.assertIsNone(self.look(win), "no Look for a client without skins")
        self.assertRaises(KeyError, win.find, "Look:")

    async def test_pick_pinstripe(self):
        c = await self.signed_on("bob", build=SKIN_BUILD)
        win = await self.open_account(c)
        look = self.look(win)
        self.assertEqual(win.gadgets[look]["rows"], ["Classic", "Pinstripe", "Dark"])
        self.assertEqual(win.gadgets[look]["value"], 0)
        win.find("Look:")
        c.pick_dropdown(WIN_ACCOUNT, look, 1)
        c.click_text(WIN_ACCOUNT, "OK")
        await c.wait_for(lambda: c.skin == Skin.PINSTRIPE, "S.SKIN Pinstripe")
        await c.wait_for(lambda: self.icons_in(c, Skin.PINSTRIPE), "the icons drawn again")
        self.assertEqual(self.server.db.user("bob")["skin"], Skin.PINSTRIPE)
        # it stays: shown in My Account, and sent at the next sign-on
        win = await self.open_account(c)
        self.assertEqual(win.gadgets[self.look(win)]["value"], 1)
        c2 = await self.client("bob again")
        c2.send_hello(SKIN_BUILD)
        await c2.wait_for(lambda: c2.hello, "HELLO")
        ok, msg = await self.login(c2, "bob", "secret")
        self.assertTrue(ok, msg)
        await c2.wait_for(lambda: c2.skin == Skin.PINSTRIPE and self.icons_in(c2, Skin.PINSTRIPE),
                          "Pinstripe at sign-on")
        # and back: OK with it unchanged sends nothing
        n = len(c2.skins)
        win = await self.open_account(c2)
        c2.click_text(WIN_ACCOUNT, "OK")
        await c2.wait_for(lambda: WIN_ACCOUNT not in c2.windows, "closed")
        self.assertEqual(len(c2.skins), n)
        win = await self.open_account(c2)
        c2.pick_dropdown(WIN_ACCOUNT, self.look(win), 2)
        c2.click_text(WIN_ACCOUNT, "OK")
        await c2.wait_for(lambda: c2.skin == Skin.DARK and self.icons_in(c2, Skin.DARK),
                          "Dark")
        self.assertTrue(self.icons_in(c2, Skin.PINSTRIPE), "Dark has the flat pictures")
        win = await self.open_account(c2)
        c2.pick_dropdown(WIN_ACCOUNT, self.look(win), 0)
        c2.click_text(WIN_ACCOUNT, "OK")
        await c2.wait_for(lambda: c2.skin == Skin.CLASSIC and self.icons_in(c2, Skin.CLASSIC),
                          "Classic again")
