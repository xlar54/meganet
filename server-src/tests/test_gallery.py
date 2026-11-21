"""Areas > Art Gallery (gallery/): IFF pictures read and written (iff.py), converted for the
client's screen and packed (picture.py), offline; then the area with fake clients: galleries
made by moderators, uploads from a drive, View and Slideshow (S.PICTURE / C.PIC_KEY)."""

import asyncio
import os
import struct
import unittest

from meganet.gallery import (WIN_GALLERY, WIN_GALLERY_EDIT, WIN_PICTURE_EDIT, WIN_UPLOAD,
                             WIN_LOADING, BUFFERS, Show)
from meganet.gallery import iff, picture
from meganet.gallery.iff import Image, read_iff, write_ilbm, IFFError, CAMG_HAM, CAMG_EHB
from meganet.gallery.picture import (to_screen, packed_chunks, unpackbits, image_from_screen,
                                     fit, quantise)
from meganet.filelib import WIN_TRANSFER
from meganet.protocol import (Caps, Kind, Local, PIC_LORES, PIC_HIRES, PIC_CLICK, PIC_ESC,
                              RESOURCE_CHUNK, S)
from tests.test_server import ServerTest
from tests.test_roles import gadget_of, status_of

CAPS = Caps.DRIVES | Caps.GRID | Caps.PICTURE | Caps.CANVAS


def pattern(w, h, ncol, seed=0):
    """A palette Image with stripes, blocks and a gradient: compresses, but not to nothing."""
    pal = [((i * 37 + seed) & 255, (i * 91) & 255, (i * 13 + 200) & 255) for i in range(ncol)]
    px = bytes(((x // 7) + (y // 5) * 3 + (x * y >> 9) + seed) % ncol
               for y in range(h) for x in range(w))
    return Image(w, h, palette=pal, pixels=px)


class IFFTest(unittest.TestCase):
    def test_ilbm_round_trip(self):
        for w, h, n in ((320, 200, 32), (17, 9, 2), (640, 200, 16), (100, 50, 256)):
            img = pattern(w, h, n)
            back = read_iff(write_ilbm(img))
            self.assertEqual((back.w, back.h), (w, h))
            self.assertEqual(back.pixels, img.pixels, (w, h, n))
            self.assertEqual(back.palette[:n], img.palette)

    def test_byterun1(self):
        for row in (b"", b"a", b"aaaa", b"abcabc", b"a" * 300 + b"xyz" + b"b" * 2,
                    bytes(range(256)) * 2):
            packed = iff.pack_byterun1(row)
            self.assertEqual(iff.unpack_byterun1(packed, 0, len(row))[0], row)

    def test_pbm(self):
        w, h = 5, 3
        px = bytes(range(15))
        body = b"".join(px[y * w:(y + 1) * w] + b"\0" for y in range(h))   # rows are even
        bmhd = struct.pack(">HHhhBBBBHBBhh", w, h, 0, 0, 8, 0, 0, 0, 0, 1, 1, w, h)
        chunks = (iff._chunk(b"BMHD", bmhd) + iff._chunk(b"CMAP", bytes(range(48)))
                  + iff._chunk(b"BODY", body))
        data = b"FORM" + struct.pack(">I", 4 + len(chunks)) + b"PBM " + chunks
        img = read_iff(data)
        self.assertEqual(img.pixels, px)
        self.assertEqual(img.palette[1], (3, 4, 5))

    def test_ehb_and_ham(self):
        img = pattern(32, 4, 64)
        img.palette = img.palette[:32]
        back = read_iff(write_ilbm(Image(32, 4, palette=img.palette + [(0, 0, 0)] * 32,
                                         pixels=img.pixels), camg=CAMG_EHB))
        self.assertEqual(back.palette[40], tuple(c // 2 for c in img.palette[8]))
        # HAM6: colour 1, then set red to 15, green to 0, blue to 8
        pal = [(0, 0, 0), (17, 34, 51)] + [(0, 0, 0)] * 62
        codes = bytes([1, 0x20 | 15, 0x30 | 0, 0x10 | 8])
        back = read_iff(write_ilbm(Image(4, 1, palette=pal, pixels=codes), camg=CAMG_HAM))
        self.assertIsNone(back.pixels)
        self.assertEqual(back.rgb, [(17, 34, 51), (255, 34, 51), (255, 0, 51), (255, 0, 136)])

    def test_bad_files(self):
        for data, why in ((b"hello", "isn't an IFF"), (b"FORM\0\0\0\x04ANIM", "isn't a picture"),
                          (b"FORM\0\0\0\x04ILBM", "no header")):
            with self.assertRaises(IFFError) as cm:
                read_iff(data)
            self.assertIn(why, str(cm.exception))
        good = write_ilbm(pattern(32, 8, 4))
        with self.assertRaises(IFFError):
            read_iff(good[:len(good) - 20])          # cut short


class ScreenTest(unittest.TestCase):
    def test_lores_and_hires_layout(self):
        for w, mode in ((320, PIC_LORES), (640, PIC_HIRES)):
            img = pattern(w, 200, 32)
            scr = to_screen(img)
            self.assertEqual(scr.mode, mode)
            self.assertEqual(len(scr.data), 64000 if mode == PIC_LORES else 128000)
            self.assertEqual(image_from_screen(scr).pixels, img.pixels)
        scr = to_screen(pattern(640, 200, 4))         # spot checks of the cell order
        img = pattern(640, 200, 4)
        for x, y in ((0, 0), (9, 0), (0, 9), (639, 199), (300, 77)):
            off = (y >> 3) * 5120 + (x >> 3) * 64 + (y & 7) * 8 + (x & 7)
            self.assertEqual(scr.data[off], img.pixels[y * 640 + x])

    def test_fitting(self):
        self.assertEqual(fit(pattern(320, 256, 2)), (PIC_LORES, 250, 200))    # PAL lores
        self.assertEqual(fit(pattern(640, 400, 2)), (PIC_HIRES, 640, 200))    # hires lace
        self.assertEqual(fit(pattern(320, 400, 2)), (PIC_LORES, 320, 200))    # lores lace
        self.assertEqual(fit(pattern(100, 50, 2)), (PIC_LORES, 100, 50))      # small: as is
        scr = to_screen(pattern(320, 256, 8, seed=3))
        img = image_from_screen(scr)
        self.assertEqual(img.pixels[0], scr.border)                           # round it
        self.assertEqual(sum(scr.palette[scr.border]), min(sum(c) for c in scr.palette))
        self.assertEqual(img.pixels[100 * 320 + 160], scr.data[
            ((100 >> 3) * 5120 + (320 >> 3) * 64 + (100 & 7) * 8) >> 1])

    def test_colour_255_and_true_colour(self):
        img = pattern(64, 8, 256)
        scr = to_screen(img)
        self.assertEqual(len(scr.palette), 255)
        self.assertNotIn(255, set(image_from_screen(scr).pixels))
        rgb = [((x * 4) & 255, (y * 30) & 255, (x * y) & 255) for y in range(8) for x in range(64)]
        pal, px = quantise(rgb, 255)
        self.assertLessEqual(len(pal), 255)
        self.assertEqual(len(px), len(rgb))
        err = max(abs(a - b) for c, i in zip(rgb, px) for a, b in zip(c, pal[i]))
        self.assertLess(err, 40)

    def test_packed_chunks(self):
        data = to_screen(pattern(320, 200, 32)).data
        chunks = packed_chunks(data)
        out = bytearray()
        for offset, part in chunks:
            self.assertLessEqual(len(part), RESOURCE_CHUNK)
            self.assertEqual(offset, len(out))
            out += unpackbits(part)
        self.assertEqual(bytes(out), data)
        self.assertLess(sum(len(p) for _, p in chunks), len(data))
        blank = packed_chunks(bytes(64000))
        self.assertLess(sum(len(p) for _, p in blank), 1100)


class GalleryBase(ServerTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.alice = await self.signed_on("alice", caps=CAPS)       # Sysop
        self.bob = await self.signed_on("bob", caps=CAPS)           # New User, then Member
        d = self.server.db
        d.set_user_role(d.user("bob")["id"], d.role_by_name("Member")["id"])
        self.server.permissions_changed(user_id=d.user("bob")["id"])
        await asyncio.sleep(0.05)

    def gallery(self, title, pictures=()):
        """A gallery made in the database, with pictures [(title, Image)] saved as IFFs."""
        d = self.server.db
        gid = d.create_gallery(title, "About " + title)
        for t, img in pictures:
            pid = d.add_gallery_picture(gid, t, "", img.w, img.h, img.colours_used(),
                                        d.user("alice")["id"])
            rel = "%d/%d.iff" % (gid, pid)
            path = os.path.join(self.server.galleries_dir, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(write_ilbm(img))
            d.set_gallery_picture_path(pid, rel)
        return gid

    def rows(self, c):
        w = c.windows[WIN_GALLERY]
        return w.gadgets[gadget_of(w, Kind.LISTBOX)]["rows"]

    async def pick_row(self, c, start, win_id=WIN_GALLERY):
        w = c.windows[win_id]
        lb = gadget_of(w, Kind.LISTBOX)
        await c.wait_for(lambda: any(r and r.startswith(start) for r in w.gadgets[lb]["rows"]),
                         "row %r" % start)
        c.select(win_id, lb, next(i for i, r in enumerate(w.gadgets[lb]["rows"])
                                  if r and r.startswith(start)))

    async def open_area(self, c):
        c.windows.pop(WIN_GALLERY, None)
        c.pick("Art Gallery")
        return await c.wait_window("Art Gallery")

    async def into(self, c, title):
        await self.open_area(c)
        await self.pick_row(c, title)
        c.click_text(WIN_GALLERY, "Open")
        c.windows.pop(WIN_GALLERY, None)
        return await c.wait_window("Art Gallery: " + title)


class GalleryTest(GalleryBase):
    async def test_moderators_make_galleries(self):
        a = await self.open_area(self.alice)
        self.assertIn("There are no galleries yet.", [g["text"] for g in a.gadgets.values()])
        self.alice.click_text(WIN_GALLERY, "New...")
        dlg = await self.alice.wait_window("New Gallery")
        self.alice.value(WIN_GALLERY_EDIT, gadget_of(dlg, Kind.TEXTBOX), "Pixel Art")
        self.alice.text(WIN_GALLERY_EDIT, gadget_of(dlg, Kind.EDIT), ["Small pictures."])
        self.alice.click_text(WIN_GALLERY_EDIT, "OK")
        await self.alice.wait_for(lambda: WIN_GALLERY in self.alice.windows and any(
            r and r.startswith("Pixel Art") for r in self.rows(self.alice)), "the gallery")
        g = self.server.db.galleries()[0]
        self.assertEqual((g["title"], g["description"]), ("Pixel Art", "Small pictures."))
        # bob (a Member) sees it, without the Admin Tools; New... from him is refused
        b = await self.open_area(self.bob)
        texts = [g["text"] for g in b.gadgets.values()]
        self.assertIn("Open", texts)
        self.assertNotIn("New...", texts)
        self.assertNotIn("Admin Tools", texts)
        # edit, then delete
        await self.pick_row(self.alice, "Pixel Art")
        self.alice.click_text(WIN_GALLERY, "Edit...")
        dlg = await self.alice.wait_window("Edit Gallery")
        self.alice.value(WIN_GALLERY_EDIT, gadget_of(dlg, Kind.TEXTBOX), "Pixels")
        self.alice.click_text(WIN_GALLERY_EDIT, "OK")
        await self.alice.wait_for(lambda: any(r and r.startswith("Pixels ")
                                              for r in self.rows(self.alice)), "renamed")
        await self.bob.wait_for(lambda: any(r and r.startswith("Pixels ")
                                            for r in self.rows(self.bob)), "bob sees it")
        self.alice.click_text(WIN_GALLERY, "Delete")
        await self.alice.wait_window("Delete Gallery")
        self.alice.click_text(63, "Delete")
        await self.bob.wait_for(lambda: not any(self.rows(self.bob)), "gone for bob")
        self.assertEqual(self.server.db.galleries(), [])

    async def test_view_a_picture(self):
        img = pattern(320, 200, 32)
        self.gallery("Paintings", [("Stripes", img)])
        w = await self.into(self.bob, "Paintings")
        self.assertTrue(any(r.startswith("Stripes") and "alice" in r for r in self.rows(self.bob)))
        await self.pick_row(self.bob, "Stripes")
        self.bob.click_text(WIN_GALLERY, "View")
        await self.bob.wait_for(lambda: self.bob.picture is not None, "the picture")
        p = self.bob.picture
        self.assertEqual(p["mode"], PIC_LORES)
        self.assertEqual(p["slot"], BUFFERS[0])
        self.assertEqual(p["data"], to_screen(img).data)
        self.assertEqual(p["palette"], img.palette)
        self.assertTrue(any(t == "Loading" for t, _ in self.bob.progress))
        self.assertLess(self.bob.packed_bytes, 64000)       # (it was packed)
        self.bob.pic_key(" ")
        await self.bob.wait_for(lambda: self.bob.picture is None, "back to the desktop")
        await self.bob.wait_for(lambda: "1 view" in " ".join(
            self.bob.windows[WIN_GALLERY].gadgets[gadget_of(
                self.bob.windows[WIN_GALLERY], Kind.TEXTVIEW)]["lines"]), "a view counted")
        self.assertIsNone(self.server.find_user("bob").picture)
        # again: it's still in the client's slot, so nothing is sent this time
        before = self.bob.resource_bytes
        self.bob.click_text(WIN_GALLERY, "View")
        await self.bob.wait_for(lambda: self.bob.picture is not None, "the picture again")
        self.assertEqual(self.bob.resource_bytes, before)
        self.bob.pic_key(PIC_CLICK)
        await self.bob.wait_for(lambda: self.bob.picture is None, "back again")

    async def test_slideshow(self):
        imgs = [pattern(320, 200, 16, seed=1), pattern(640, 200, 8, seed=2),
                pattern(320, 200, 4, seed=3)]
        self.gallery("Show", [("One", imgs[0]), ("Two", imgs[1]), ("Three", imgs[2])])
        await self.into(self.bob, "Show")
        await self.pick_row(self.bob, "One")
        self.bob.click_text(WIN_GALLERY, "Slideshow")
        await self.bob.wait_for(lambda: len(self.bob.pictures) == 1, "picture 1")
        show = self.server.find_user("bob").picture
        self.assertIsInstance(show, Show)
        await asyncio.wait_for(asyncio.shield(show.loaders[1].task), 5)    # the next, sent ahead
        ends = self.bob.messages.count(S.PICTURE_END)
        self.bob.pic_key(" ")
        await self.bob.wait_for(lambda: len(self.bob.pictures) == 2, "picture 2")
        self.assertEqual(self.bob.messages.count(S.PICTURE_END), ends)    # straight on
        p = self.bob.pictures[1]
        self.assertEqual((p["mode"], p["slot"]), (PIC_HIRES, BUFFERS[1]))
        self.assertEqual(p["data"], to_screen(imgs[1]).data)
        await asyncio.wait_for(asyncio.shield(show.loaders[0].task), 5)
        self.bob.pic_key(PIC_CLICK)
        await self.bob.wait_for(lambda: len(self.bob.pictures) == 3, "picture 3")
        self.assertEqual(self.bob.pictures[2]["data"], to_screen(imgs[2]).data)
        self.bob.pic_key(" ")                                  # past the last: back
        await self.bob.wait_for(lambda: self.bob.picture is None, "the end")
        await self.bob.wait_for(lambda: status_of(self.bob.windows[WIN_GALLERY])
                                == "That was the last picture.", "said so")
        # Esc leaves a slideshow at once; it starts at the picked picture
        await self.pick_row(self.bob, "Two")
        self.bob.click_text(WIN_GALLERY, "Slideshow")
        await self.bob.wait_for(lambda: len(self.bob.pictures) == 4, "from Two")
        self.assertEqual(self.bob.pictures[3]["data"], to_screen(imgs[1]).data)
        self.bob.pic_key(PIC_ESC)
        await self.bob.wait_for(lambda: self.bob.picture is None, "Esc")

    async def test_next_not_there_yet_shows_progress(self):
        imgs = [pattern(320, 200, 16, seed=s) for s in range(2)]
        self.gallery("Slow", [("A", imgs[0]), ("B", imgs[1])])
        await self.into(self.bob, "Slow")
        await self.pick_row(self.bob, "A")
        self.bob.click_text(WIN_GALLERY, "Slideshow")
        await self.bob.wait_for(lambda: len(self.bob.pictures) == 1, "picture 1")
        show = self.server.find_user("bob").picture
        show.loaders[1].task.cancel()                     # as if it's still on its way
        show.loaders.pop(1)
        n, m = len(self.bob.progress), len(self.bob.messages)
        self.bob.pic_key(" ")
        await self.bob.wait_for(lambda: len(self.bob.pictures) == 2, "picture 2")
        self.assertIn(S.PICTURE_END, self.bob.messages[m:])
        self.assertTrue(any(t == "Loading" for t, _ in self.bob.progress[n:]))
        self.assertEqual(self.bob.pictures[1]["data"], to_screen(imgs[1]).data)

    async def test_old_client_is_told(self):
        carol = await self.signed_on("carol")             # no Caps.PICTURE
        self.gallery("Old", [("Pic", pattern(32, 32, 4))])
        await self.into(carol, "Old")
        await self.pick_row(carol, "Pic")
        carol.click_text(WIN_GALLERY, "View")
        await carol.wait_for(lambda: carol.alerts, "an alert")
        self.assertIn("can't show pictures", carol.alerts[-1][1])
        self.assertNotIn(S.PICTURE, carol.messages)

    async def test_upload(self):
        self.gallery("Uploads")
        img = pattern(320, 200, 32, seed=5)
        self.bob.storage.drives[8] = {"name": "ART", "files": {
            "SUNSET.IFF": (Local.PRG, write_ilbm(img)), "README": (Local.SEQ, b"just text")}}
        await self.into(self.bob, "Uploads")
        self.bob.click_text(WIN_GALLERY, "Upload")
        dlg = await self.bob.wait_window("Upload Picture")
        await self.pick_row(self.bob, "README", WIN_UPLOAD)
        self.bob.value(WIN_UPLOAD, gadget_of(dlg, Kind.TEXTBOX), "Not a picture")
        self.bob.click_text(WIN_UPLOAD, "Upload")
        t = await self.bob.wait_window("Upload")
        await self.bob.wait_for(lambda: "isn't an IFF" in status_of(
            self.bob.windows.get(WIN_TRANSFER, t)), "refused")
        self.bob.click_text(WIN_TRANSFER, "Close")
        self.bob.click_text(WIN_GALLERY, "Upload")
        dlg = await self.bob.wait_window("Upload Picture")
        await self.pick_row(self.bob, "SUNSET.IFF", WIN_UPLOAD)
        tb = gadget_of(dlg, Kind.TEXTBOX)
        await self.bob.wait_for(lambda: dlg.gadgets[tb]["text"] == "Sunset", "title")
        self.bob.value(WIN_UPLOAD, tb, "Sunset")
        self.bob.click_text(WIN_UPLOAD, "Upload")
        await self.bob.wait_for(lambda: WIN_TRANSFER in self.bob.windows and
                                status_of(self.bob.windows[WIN_TRANSFER]).startswith("Done"),
                                "uploaded")
        await self.bob.wait_for(lambda: any(r and r.startswith("Sunset") and "bob" in r
                                            for r in self.rows(self.bob)), "listed")
        p = self.server.db.gallery_pictures(self.server.db.galleries()[0]["id"])[0]
        self.assertEqual((p["width"], p["height"], p["colours"], p["artist_name"]),
                         (320, 200, 32, "bob"))
        with open(os.path.join(self.server.galleries_dir, p["path"]), "rb") as f:
            self.assertEqual(read_iff(f.read()).pixels, img.pixels)

    async def test_who_may_change_pictures(self):
        gid = self.gallery("Mixed", [("Alices", pattern(32, 32, 4))])
        d = self.server.db
        pid = d.add_gallery_picture(gid, "Bobs", "", 8, 8, 2, d.user("bob")["id"])
        rel = "%d/%d.iff" % (gid, pid)
        with open(os.path.join(self.server.galleries_dir, rel), "wb") as f:
            f.write(write_ilbm(pattern(8, 8, 2)))
        d.set_gallery_picture_path(pid, rel)
        await self.into(self.bob, "Mixed")
        await self.pick_row(self.bob, "Alices")
        await self.bob.wait_for(lambda: not self.bob.enabled(WIN_GALLERY, "Delete"),
                                "not his: greyed")
        await self.pick_row(self.bob, "Bobs")
        await self.bob.wait_for(lambda: self.bob.enabled(WIN_GALLERY, "Edit..."), "his")
        self.bob.click_text(WIN_GALLERY, "Edit...")
        dlg = await self.bob.wait_window("Edit Picture")
        self.bob.value(WIN_PICTURE_EDIT, gadget_of(dlg, Kind.TEXTBOX), "Bob's Best")
        self.bob.click_text(WIN_PICTURE_EDIT, "OK")
        await self.bob.wait_for(lambda: any(r and r.startswith("Bob's Best")
                                            for r in self.rows(self.bob)), "renamed")
        self.bob.click_text(WIN_GALLERY, "Delete")
        await self.bob.wait_window("Delete Picture")
        self.bob.click_text(63, "Delete")
        await self.bob.wait_for(lambda: len(self.rows(self.bob)) == 1, "deleted")
        self.assertFalse(os.path.exists(os.path.join(self.server.galleries_dir, rel)))
        # a forged click on Delete for alice's picture is refused
        await self.pick_row(self.bob, "Alices")
        await asyncio.sleep(0.05)
        self.bob.click_text(WIN_GALLERY, "Delete")
        await asyncio.sleep(0.1)
        self.assertEqual(len(d.gallery_pictures(gid)), 1)


if __name__ == "__main__":
    unittest.main()
