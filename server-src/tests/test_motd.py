"""The message of the day: shown in the centred welcome window, edited by admins (admin.motd)
in the Message of the Day window, loaded from a file with --motd."""

import json
import os
import tempfile
import unittest

from meganet import db, permissions, ui
from meganet.admin import WIN_MOTD, MotdEditor, motd_for_editor
from meganet.protocol import Kind
from meganet.screens import Screens, WIN_WELCOME, M_MOTD
from meganet.server import Server
from tests.test_roles import RolesBase, gadget_of, status_of


def view_lines(c):
    win = c.windows[WIN_WELCOME]
    return win.gadgets[gadget_of(win, Kind.TEXTVIEW)]["lines"]


class MotdTest(RolesBase):

    async def test_welcome_is_centred_and_shows_the_motd(self):
        win = self.bob.windows[WIN_WELCOME]
        self.assertEqual(win.size, (416, 134))
        # x = (640 - (w + 8)) // 2, y = 11 + (189 - (h + 18)) // 2
        self.assertEqual(win.pos, ((640 - (416 + 8)) // 2, 11 + (189 - (134 + 18)) // 2))
        self.assertEqual(win.pos, (108, 29))
        self.assertEqual(ui.centre(416, 134), (108, 29))
        self.assertEqual(view_lines(self.bob), db.DEFAULT_MOTD)
        self.assertEqual(self.server.db.motd(), db.DEFAULT_MOTD)
        self.assertIsNotNone(self.server.db.setting(db.MOTD_KEY), "stored on a fresh database")
        self.assertEqual(Screens.motd_columns(), (400 - 6 - 11) // 8)
        self.assertIn("Message of the Day...", self.alice.menu_items("Admin"))
        self.assertNotIn("Admin", self.bob.menu_titles())

    async def editor(self, c):
        c.pick("Message of the Day...")
        return await c.wait_window("Message of the Day")

    async def do(self, c, win, button, status):
        """Click `button` in the editor and wait for the status line to say `status`."""
        win.gadgets[gadget_of(win, Kind.LABEL, -1)]["text"] = ""
        c.click_text(WIN_MOTD, button)
        await c.wait_for(lambda: status_of(win) == status, status)

    def area(self, win):
        return gadget_of(win, Kind.EDIT)

    async def test_admin_edits_and_saves(self):
        c, dbase = self.alice, self.server.db
        win = await self.editor(c)
        self.assertEqual(win.pos, ui.centre(MotdEditor.W, MotdEditor.H))
        # the text area is the welcome view's width: a line here is a line users see
        self.assertEqual(MotdEditor.AREA[2], Screens.MOTD_VIEW[2])
        cols = Screens.motd_columns()
        start = motd_for_editor(db.DEFAULT_MOTD, cols)
        self.assertEqual(win.gadgets[self.area(win)]["lines"], start)
        self.assertTrue(all(len(l) <= cols for l in start))
        self.assertGreater(len(start), len(db.DEFAULT_MOTD), "long lines were wrapped")

        lines = ["Hello from the sysop.", "", "Chess night on Friday!"]
        c.text(WIN_MOTD, self.area(win), lines)
        # Preview: the welcome window as users will see it, nothing saved
        c.windows.pop(WIN_WELCOME, None)
        await self.do(c, win, "Preview", "Preview open.")
        await c.wait_window("Welcome, alice")
        self.assertEqual(view_lines(c), lines)
        self.assertEqual(dbase.motd(), db.DEFAULT_MOTD, "Preview doesn't save")

        c.click_text(WIN_MOTD, "Save")
        await c.wait_for(lambda: WIN_MOTD not in c.windows, "editor closed")
        await c.wait_for(lambda: c.alerts, "saved alert")
        self.assertEqual(c.alerts[-1], ("Message of the Day",
                                        "Saved. Users see it when they next sign on."))
        self.assertEqual(dbase.motd(), lines)
        self.assertEqual(json.loads(dbase.setting(db.MOTD_KEY)), lines)
        self.assertEqual(view_lines(self.bob), db.DEFAULT_MOTD, "open windows aren't updated")
        carol = await self.signed_on("carol")
        self.assertEqual(view_lines(carol), lines)
        win = await self.editor(c)                      # it opens with the saved lines
        self.assertEqual(win.gadgets[self.area(win)]["lines"], lines)

    async def test_cancel_discards(self):
        c = self.alice
        win = await self.editor(c)
        c.text(WIN_MOTD, self.area(win), ["Not this."])
        c.click_text(WIN_MOTD, "Cancel")
        await c.wait_for(lambda: WIN_MOTD not in c.windows, "editor closed")
        self.assertEqual(self.server.db.motd(), db.DEFAULT_MOTD)

    async def test_non_admin_is_refused(self):
        bob = self.bob
        # Forged: the menu id bob was never sent, then clicks and a pick in a window he hasn't got.
        bob.pick_id(M_MOTD)
        for gid in range(1, 16):
            bob.click(WIN_MOTD, gid)
        bob.select(WIN_MOTD, 2, 0)
        await self.roundtrip(bob)
        self.assertNotIn(WIN_MOTD, bob.windows)
        self.assertEqual(bob.alerts, [])
        # Straight at the admin module, past the menu:
        self.server.screens.admin.open_motd(self.session("bob"))
        await bob.wait_for(lambda: bob.alerts, "refusal")
        self.assertEqual(bob.alerts, [("Administration", "You don't have permission to do that.")])
        self.assertNotIn(WIN_MOTD, bob.windows)

        # An admin whose permission went while the editor was open (the window stayed).
        c = self.alice
        win = await self.editor(c)
        self.session("alice").perms = frozenset({"chat.use"})
        c.text(WIN_MOTD, gadget_of(win, Kind.EDIT), ["Hacked"])
        for button in ("Preview", "Save"):
            c.click_text(WIN_MOTD, button)
        await c.wait_for(lambda: len(c.alerts) == 2, "2 refusals")
        self.assertTrue(all(a == ("Administration", "You don't have permission to do that.")
                            for a in c.alerts), c.alerts)
        self.assertEqual(self.server.db.motd(), db.DEFAULT_MOTD)

    async def test_losing_the_key_closes_the_editor(self):
        c, dbase = self.alice, self.server.db
        await self.editor(c)
        sysop = dbase.role_by_name("Sysop")["id"]
        self.assertIsNone(dbase.set_role_permissions(
            sysop, dbase.role_permissions(sysop) - {permissions.ADMIN_MOTD}))
        self.server.permissions_changed(role_id=sysop)
        await c.wait_for(lambda: WIN_MOTD not in c.windows, "editor closed")
        await c.wait_for(lambda: "Message of the Day..." not in c.menu_items("Admin"), "menu")
        c.pick_id(M_MOTD)
        await self.roundtrip(c)
        self.assertNotIn(WIN_MOTD, c.windows)


class MotdFileTest(unittest.IsolatedAsyncioTestCase):
    async def test_motd_file_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "motd.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("Welcome to the Board!\n\n\tTabbed line   \nCafé night\n\n\n")
            server = Server(":memory:", tmp, motd_file=path)
            try:
                self.assertEqual(server.db.motd(), ["Welcome to the Board!", "",
                                                    "    Tabbed line", "Caf? night"])
            finally:
                await server.stop()

    def test_tidy_limits(self):
        lines = db.tidy_motd(["x" * 300] + ["y"] * 100)
        self.assertEqual(len(lines), db.MOTD_MAX_LINES)
        self.assertEqual(len(lines[0]), db.MOTD_LINE_MAX)


if __name__ == "__main__":
    unittest.main()
