"""Every Areas entry window has the same layout (ui.AreaWindow): 560 x 160, centred, a heading
line, the list on the left, the commands in a column on the right (the main one first, the
default), and a status line at the bottom. Checked as the Sysop, so every Admin Tools
section is there too, and as a New User, who sees none."""

from meganet import ui
from meganet.protocol import Kind, GFlag
from tests.test_server import ServerTest

AREAS = ["News", "Message Boards", "Chat Rooms", "Private Messages", "File Library", "Games",
         "Internet", "Voting"]


class LayoutTest(ServerTest):
    def check(self, c, title):
        w = next(w for w in c.windows.values() if w.done and w.title == title)
        self.assertEqual(w.size, (ui.AREA_W, ui.AREA_H), title)
        self.assertEqual(w.pos, ui.centre(ui.AREA_W, ui.AREA_H), title)
        gads = sorted(w.gadgets.values(), key=lambda g: g["box"][1])
        heading = gads[0]
        self.assertEqual((heading["kind"], heading["box"][:2]), (Kind.LABEL, (8, 2)),
                         "%s: the heading first" % title)
        lists = [g for g in gads if g["kind"] == Kind.LISTBOX]
        self.assertTrue(lists, title)
        self.assertEqual((lists[0]["box"][0], lists[0]["box"][2]), (8, ui.AREA_LIST_W),
                         "%s: the list on the left" % title)
        status = [g for g in gads if g["kind"] == Kind.LABEL and g["box"][1] == ui.AREA_H - 12]
        self.assertEqual(len(status), 1, "%s: one status line" % title)
        buttons = [g for g in gads if g["kind"] == Kind.BUTTON]
        for b in buttons:
            x, y, bw, bh = b["box"]
            self.assertTrue(ui.AREA_COL_X <= x and x + bw <= ui.AREA_COL_X + ui.AREA_COL_W,
                            "%s: %r is in the command column" % (title, b["text"]))
            self.assertLessEqual(y + bh, ui.AREA_BOTTOM, title)
            self.assertLessEqual(8 * len(b["text"]), bw - 4,
                                 "%s: %r fits its button" % (title, b["text"]))
        first = min(buttons, key=lambda b: (b["box"][1], b["box"][0]))
        self.assertEqual(first["box"][1], ui.AREA_TOP, "%s: a command at the top" % title)
        self.assertTrue(first["flags"] & GFlag.DEFAULT, "%s: the main one, default" % title)
        for g in gads:                                   # nothing on the right of the column
            self.assertLessEqual(g["box"][0] + g["box"][2], ui.AREA_W - 8,
                                 "%s: %r in the margin" % (title, g["text"]))
        return w

    async def open(self, c, area):
        c.pick(area)
        await c.wait_for(lambda: any(w.done and w.title == area for w in c.windows.values()),
                         area)

    async def test_every_area_as_sysop(self):
        a = await self.signed_on("alice")                # (the first account: Sysop)
        self.assertEqual([t for t in a.menu_items("Areas") if t in AREAS], AREAS)
        for area in AREAS:
            await self.open(a, area)
            w = self.check(a, area)
            if area not in ("Games", "Internet", "Private Messages"):    # (nothing to manage)
                self.assertTrue(any(g["text"] == "Admin Tools" for g in w.gadgets.values()),
                                "%s: Admin Tools for the Sysop" % area)
        # a view inside an area: a forum's topics
        boards = next(w for w in a.windows.values() if w.title == "Message Boards")
        lb = next(gid for gid, g in boards.gadgets.items() if g["kind"] == Kind.LISTBOX)
        a.select(boards.id, lb, 0)
        a.click_text(boards.id, "Open")
        await a.wait_for(lambda: any(w.done and w.title == "Message Boards: General"
                                     for w in a.windows.values()), "the forum")
        self.check(a, "Message Boards: General")

    async def test_no_admin_tools_for_new_users(self):
        await self.signed_on("alice")
        b = await self.signed_on("bob")                  # a New User
        for area in [x for x in AREAS if x in b.menu_items("Areas")]:
            await self.open(b, area)
            w = self.check(b, area)
            self.assertFalse(any(g["text"] == "Admin Tools" for g in w.gadgets.values()),
                             "%s: no Admin Tools for a New User" % area)
