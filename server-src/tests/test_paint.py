"""The Art Gallery's Paint (gallery/paint.py): the drawing itself, offline; then painting with
a fake client: the picture as its desktop (S.CANVAS), strokes and shapes (C.CANVAS ->
S.CANVAS_RECT), the tool window, Undo, saving into the gallery and leaving."""

import asyncio
import os
import unittest

from meganet.gallery import WIN_GALLERY
from meganet.gallery.iff import read_iff, write_ilbm
from meganet.gallery.paint import (Canvas, canvas_offset, line_points, to_slot, COLOURS,
                                   DEFAULT_PALETTE, Paint)
from meganet.gallery.picture import unpackbits
from meganet.protocol import (Caps, Kind, CanvasEvent, CanvasPen, CANVAS_FIRST, CANVAS_W,
                              CANVAS_H, RESOURCE_CHUNK, S, Reader)
from tests.test_gallery import GalleryBase, pattern
from tests.test_roles import gadget_of, status_of

DOWN, MOVE, UP, RIGHT = (CanvasEvent.DOWN, CanvasEvent.MOVE, CanvasEvent.UP,
                         CanvasEvent.RIGHT)


class DrawingTest(unittest.TestCase):
    def test_offsets_match_the_lores_layout(self):
        seen = set()
        for y in range(CANVAS_H):
            for x in range(CANVAS_W):
                sx = 2 * x
                want = ((y >> 3) * 5120 + (sx >> 3) * 64 + (y & 7) * 8 + (sx & 7)) >> 1
                self.assertEqual(canvas_offset(x, y), want)
                seen.add(want)
        self.assertEqual(len(seen), 64000)

    def test_lines(self):
        pts = list(line_points(3, 4, 10, 1))
        self.assertEqual((pts[0], pts[-1]), ((3, 4), (10, 1)))
        for (a, b), (c, d) in zip(pts, pts[1:]):           # each step a neighbour
            self.assertLessEqual(max(abs(a - c), abs(b - d)), 1)
        self.assertEqual(list(line_points(5, 5, 5, 5)), [(5, 5)])

    def test_shapes_and_fill(self):
        cv = Canvas()
        cv.brush(0, 0, 3, 4)                                 # 4 across from 1 up-left: clipped
        self.assertEqual([cv.get(x, 0) for x in range(4)], [3, 3, 3, 0])
        cv = Canvas()
        cv.box(10, 10, 20, 15, 2, 1, False)
        self.assertEqual((cv.get(10, 10), cv.get(20, 15), cv.get(15, 12)), (2, 2, 0))
        cv.fill(15, 12, 7)                                   # the inside only
        self.assertEqual((cv.get(15, 12), cv.get(11, 11), cv.get(25, 25), cv.get(10, 12)),
                         (7, 7, 0, 2))
        cv = Canvas()
        cv.oval(100, 50, 140, 70, 4, 1, True)
        self.assertEqual((cv.get(120, 60), cv.get(100, 50), cv.get(140, 60)), (4, 0, 4))
        cv.fill(0, 0, 9)
        self.assertEqual((cv.get(0, 199), cv.get(120, 60)), (9, 4))

    def test_rect_messages(self):
        cv = Canvas(pattern(CANVAS_W, CANVAS_H, COLOURS).pixels)
        msgs = cv.rect_messages([0, 0, CANVAS_W - 1, CANVAS_H - 1])
        rows = 0
        for w in msgs:
            r = Reader(bytes(w.parts))
            x, y, ww, h = r.u16(), r.u8(), r.u16(), r.u8()
            packed = r.rest()
            self.assertLessEqual(len(packed), RESOURCE_CHUNK)
            data = unpackbits(packed)
            self.assertEqual(len(data), ww * h)
            self.assertEqual(y, rows)
            self.assertEqual(data[:ww], bytes(v + CANVAS_FIRST for v in cv.px[y * 320:y * 320 + 320]))
            rows += h
        self.assertEqual(rows, CANVAS_H)


class PaintBase(GalleryBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.gid = self.gallery("Studio")

    async def paint(self, c, pick=None):
        """Into Studio and Paint (with `pick` picked first, if given): the tool window."""
        await self.into(c, "Studio")
        if pick:
            await self.pick_row(c, pick)
        c.click_text(WIN_GALLERY, "Paint")
        await c.wait_for(lambda: c.canvas is not None, "the canvas")
        return await c.wait_window("Paint")

    def tool(self, c, w, name):
        c.select(w.id, w.find(name), 1)

    async def until_same(self, c, what):
        """Wait until the client's picture shows what(pixels) and matches the server's."""
        server = self.server.find_user(c.name).canvas
        await c.wait_for(lambda: what(c.canvas_pixels()), "the drawing")
        await c.wait_for(lambda: c.canvas_pixels() == bytes(server.canvas.px), "in step")
        return server


class PaintTest(PaintBase):
    async def test_painting(self):
        bob = self.bob
        w = await self.paint(bob)
        self.assertIn(WIN_GALLERY, bob.hidden)                     # the gallery hidden
        self.assertEqual(bob.canvas["palette"], DEFAULT_PALETTE)
        await bob.wait_for(lambda: bob.pen is not None, "the pen")
        self.assertEqual(bob.pen, (CanvasPen.FREE, CANVAS_FIRST + 1, 1))
        self.assertEqual(bob.canvas_pixels(), bytes(64000))
        # a stroke
        bob.canvas_event(DOWN, 10, 10)
        bob.canvas_event(MOVE, 20, 10)
        bob.canvas_event(MOVE, 20, 14)
        bob.canvas_event(UP, 20, 14)
        server = await self.until_same(bob, lambda px: px[14 * 320 + 20] == 1)
        px = bob.canvas_pixels()
        self.assertTrue(all(px[10 * 320 + x] == 1 for x in range(10, 21)))
        self.assertTrue(all(px[y * 320 + 20] == 1 for y in range(10, 15)))
        # colour 5, a solid box, size 3
        grid = gadget_of(w, Kind.GRID)
        bob.select(w.id, grid, 5)
        await bob.wait_for(lambda: bob.pen[1] == CANVAS_FIRST + 5, "colour 5")
        self.assertEqual(w.gadgets[grid]["cells"][5] & 0x80, 0x80)
        self.tool(bob, w, "Box")
        bob.select(w.id, w.find("Solid"), 1)
        await bob.wait_for(lambda: bob.pen[0] == CanvasPen.BOX, "the box pen")
        bob.canvas_event(DOWN, 50, 50)
        bob.canvas_event(MOVE, 60, 55)
        bob.canvas_event(UP, 70, 60)
        await self.until_same(bob, lambda px: px[60 * 320 + 70] == 5)
        px = bob.canvas_pixels()
        self.assertEqual((px[55 * 320 + 60], px[60 * 320 + 70], px[61 * 320 + 70]), (5, 5, 0))
        # Fill the background with colour 9; right click picks colour 1 back
        self.tool(bob, w, "Fill")
        bob.select(w.id, grid, 9)
        await bob.wait_for(lambda: bob.pen == (CanvasPen.NONE, CANVAS_FIRST + 9, 1), "fill")
        bob.canvas_event(DOWN, 300, 190)
        bob.canvas_event(UP, 300, 190)
        await self.until_same(bob, lambda px: px[0] == 9)
        px = bob.canvas_pixels()
        self.assertEqual((px[0], px[55 * 320 + 60], px[10 * 320 + 15]), (9, 5, 1))
        bob.canvas_event(RIGHT, 15, 10)
        await bob.wait_for(lambda: bob.pen[1] == CANVAS_FIRST + 1, "picked colour 1")
        # Undo the fill
        bob.click_text(w.id, "Undo")
        await self.until_same(bob, lambda px: px[0] == 0)
        # an oval outline and a line, size 2
        self.tool(bob, w, "Oval")
        bob.select(w.id, w.find("Solid"), 0)
        size = gadget_of(w, Kind.DROPDOWN)
        bob.pick_dropdown(w.id, size, 1)
        await bob.wait_for(lambda: bob.pen == (CanvasPen.BOX, CANVAS_FIRST + 1, 2), "size 2")
        bob.canvas_event(DOWN, 150, 100)
        bob.canvas_event(UP, 200, 150)
        self.tool(bob, w, "Line")
        bob.canvas_event(DOWN, 0, 199)
        bob.canvas_event(UP, 319, 0)
        await self.until_same(bob, lambda px: px[319] == 1 and px[199 * 320] == 1)
        self.assertEqual(bob.canvas_pixels()[200 + 125 * 320], 1)  # the oval's right edge
        self.assertTrue(server.changed)

    async def test_save_and_leave(self):
        bob = self.bob
        w = await self.paint(bob)
        bob.canvas_event(DOWN, 5, 5)
        bob.canvas_event(UP, 5, 5)
        server = await self.until_same(bob, lambda px: px[5 * 320 + 5] == 1)
        # Done with changes: it asks; Cancel stays
        bob.click_text(w.id, "Done")
        ask = await bob.wait_window("Leave Paint")
        bob.click_text(ask.id, "Cancel")
        await asyncio.sleep(0.1)
        self.assertIsNotNone(bob.canvas)
        # Save... a new picture
        bob.click_text(w.id, "Save...")
        dlg = await bob.wait_window("Save Picture")
        bob.value(dlg.id, gadget_of(dlg, Kind.TEXTBOX), "First Try")
        bob.text(dlg.id, gadget_of(dlg, Kind.EDIT), ["A dot."])
        bob.click_text(dlg.id, "Save")
        await bob.wait_for(lambda: self.server.db.gallery_pictures(self.gid), "saved")
        p = self.server.db.gallery_pictures(self.gid)[0]
        self.assertEqual((p["title"], p["description"], p["artist_name"], p["colours"]),
                         ("First Try", "A dot.", "bob", 2))
        with open(os.path.join(self.server.galleries_dir, p["path"]), "rb") as f:
            img = read_iff(f.read())
        self.assertEqual(img.pixels, bytes(server.canvas.px))
        self.assertEqual(img.palette[:COLOURS], DEFAULT_PALETTE)
        # Save again: the same picture, written over
        bob.canvas_event(DOWN, 6, 6)
        bob.canvas_event(UP, 6, 6)
        await self.until_same(bob, lambda px: px[6 * 320 + 6] == 1)
        bob.click_text(w.id, "Save...")
        dlg = await bob.wait_window("Save Picture")
        bob.click_text(dlg.id, "Save")
        await bob.wait_for(lambda: not server.changed, "saved again")
        self.assertEqual(len(self.server.db.gallery_pictures(self.gid)), 1)
        # Done: no question now; the gallery back, the picture in it
        bob.click_text(w.id, "Done")
        await bob.wait_for(lambda: bob.canvas is None, "the desktop back")
        await bob.wait_for(lambda: any(r and r.startswith("First Try")
                                       for r in self.rows(bob)), "listed")
        self.assertIsNone(self.server.find_user("bob").canvas)

    async def test_paint_on_your_own(self):
        bob = self.bob
        d = self.server.db
        img = pattern(320, 200, 16, seed=4)
        pid = d.add_gallery_picture(self.gid, "Mine", "", 320, 200, 16, d.user("bob")["id"])
        rel = "%d/%d.iff" % (self.gid, pid)
        os.makedirs(os.path.join(self.server.galleries_dir, str(self.gid)), exist_ok=True)
        with open(os.path.join(self.server.galleries_dir, rel), "wb") as f:
            f.write(write_ilbm(img))
        d.set_gallery_picture_path(pid, rel)
        await self.into(bob, "Studio")
        await self.pick_row(bob, "Mine")
        bob.click_text(WIN_GALLERY, "Paint")
        ask = await bob.wait_window("Paint")
        bob.click_text(ask.id, "This One")
        await bob.wait_for(lambda: bob.canvas is not None, "the canvas")
        await bob.wait_window("Paint")
        await bob.wait_for(lambda: bob.canvas_pixels() == img.pixels, "the picture")
        self.assertEqual(bob.canvas["palette"][:16], img.palette)
        self.assertTrue(any(t == "Loading" for t, _ in bob.progress))   # (it was loading)

    async def test_too_many_colours_and_old_clients(self):
        self.gallery("Big", [("Lots", pattern(320, 200, 200))])
        d = self.server.db
        lots = d.gallery_pictures(d.galleries()[0]["id"] if d.galleries()[0]["title"] == "Big"
                                  else d.galleries()[1]["id"])[0]
        d.conn.execute("UPDATE gallery_pictures SET artist = ? WHERE id = ?",
                       (d.user("bob")["id"], lots["id"]))
        d.conn.commit()
        await self.into(self.bob, "Big")
        await self.pick_row(self.bob, "Lots")
        self.bob.click_text(WIN_GALLERY, "Paint")
        ask = await self.bob.wait_window("Paint")
        self.bob.click_text(ask.id, "This One")
        await self.bob.wait_for(lambda: self.bob.alerts, "refused")
        self.assertIn("up to 32 colours", self.bob.alerts[-1][1])
        carol = await self.signed_on("carol", caps=Caps.DRIVES | Caps.GRID | Caps.PICTURE)
        d.set_user_role(d.user("carol")["id"], d.role_by_name("Member")["id"])
        self.server.permissions_changed(user_id=d.user("carol")["id"])
        await asyncio.sleep(0.05)
        await self.into(carol, "Studio")
        carol.click_text(WIN_GALLERY, "Paint")
        await carol.wait_for(lambda: carol.alerts, "an alert")
        self.assertIn("can't paint", carol.alerts[-1][1])
        self.assertNotIn(S.CANVAS, carol.messages)

    async def test_close_box_and_disconnect(self):
        bob = self.bob
        w = await self.paint(bob)
        bob.close_box(w.id)                         # nothing changed: straight out
        await bob.wait_for(lambda: bob.canvas is None, "out")
        w = await self.paint(bob)
        bob.canvas_event(DOWN, 1, 1)
        bob.canvas_event(UP, 1, 1)
        await self.until_same(bob, lambda px: px[321] == 1)
        bob.close_box(w.id)                         # changed: asked; Cancel brings it back
        ask = await bob.wait_window("Leave Paint")
        bob.click_text(ask.id, "Cancel")
        await bob.wait_window("Paint")
        session = self.server.find_user("bob")
        await bob.close()
        self.clients.remove(bob)
        await asyncio.sleep(0.2)
        self.assertIsNone(session.canvas)


if __name__ == "__main__":
    unittest.main()
