"""Areas > File Library (filelib.py): libraries with their own folders under filelibs/,
per-role access, moderators' entries for the files, downloads to drives 8-11 and the SD card,
and uploads from them (held for approval when the library says so). The fake client's
FakeStorage plays the MEGA65's disks."""

import os
import unittest
import zlib

from meganet import filelib
from meganet.filelib import (WIN_FILES, WIN_LIB_EDIT, WIN_FILE_EDIT, WIN_DOWNLOAD,
                             WIN_TRANSFER, WIN_UPLOAD, WIN_ACCESS, WIN_DELETE)
from meganet.protocol import Caps, Kind, Local, FILE_WINDOW
from tests.test_pages import PagesBase
from tests.test_roles import gadget_of, status_of

ALL = Caps.DRIVES | Caps.SD_READ | Caps.SD_WRITE


class NamesTest(unittest.TestCase):
    def test_folders_paths_and_names(self):
        self.assertEqual(filelib.folder_for("C64 Games"), "c64_games")
        self.assertEqual(filelib.folder_for("Apps & Tools!"), "apps__tools")
        self.assertEqual(filelib.folder_for("..."), "library")
        self.assertEqual(filelib.tidy_path("sub\\game.prg"), "sub/game.prg")
        for bad in ("../secret.db", "/etc/passwd", "c:/x", "a/../../b", ""):
            self.assertIsNone(filelib.tidy_path(bad), bad)
        self.assertEqual(filelib.sd_name("Elite Disk 1", "D81"), "ELITE_DI.D81")
        self.assertIsNone(filelib.check_sd_name("ELITE.D81", "D81"))
        self.assertIsNotNone(filelib.check_sd_name("ELITE.D64", "D81"))
        self.assertIsNotNone(filelib.check_sd_name("TOOLONGNAME.D81", "D81"))
        self.assertIsNone(filelib.check_cbm_name("GAME 1"))
        self.assertIsNotNone(filelib.check_cbm_name("A,B"))
        self.assertIsNotNone(filelib.check_cbm_name("@0:X"))
        self.assertIsNotNone(filelib.check_image("D81", 1000))
        self.assertIsNone(filelib.check_image("D64", 174848))


class FileLibraryBase(PagesBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.root = self.server.filelibs_dir
        d = self.server.db
        self.assertIsNone(d.set_user_role(d.user("bob")["id"], d.role_by_name("Member")["id"]))
        self.server.permissions_changed(user_id=d.user("bob")["id"])
        await self.bob.wait_for(lambda: "File Library" in self.bob.menu_items("Areas"),
                                "bob can use the library")

    def library(self, title, auto=True, files=()):
        """A library made straight in the database, with files [(name, type, path, data)]."""
        d = self.server.db
        folder = filelib.folder_for(title)
        lib_id = d.create_library(title, folder, "About " + title, auto)
        os.makedirs(os.path.join(self.root, folder), exist_ok=True)
        for name, ftype, path, data in files:
            with open(os.path.join(self.root, folder, path), "wb") as f:
                f.write(data)
            d.add_library_file(lib_id, name, ftype, "", path, len(data))
        return lib_id

    async def open_files(self, c):
        c.windows.pop(WIN_FILES, None)
        c.pick("File Library")
        return await c.wait_window("File Library")

    def rows(self, c):
        w = c.windows[WIN_FILES]
        return w.gadgets[gadget_of(w, Kind.LISTBOX)]["rows"]

    async def pick_row(self, c, win_id, start):
        w = c.windows[win_id]
        lb = gadget_of(w, Kind.LISTBOX)
        await c.wait_for(lambda: any(r and r.strip().startswith(start)
                                     for r in w.gadgets[lb]["rows"]), "row %r" % start)
        index = next(i for i, r in enumerate(w.gadgets[lb]["rows"])
                     if r and r.strip().startswith(start))
        c.select(win_id, lb, index)

    async def into(self, c, title):
        """Open the File Library and the library called `title`."""
        await self.open_files(c)
        await self.pick_row(c, WIN_FILES, title)
        c.click_text(WIN_FILES, "Open")
        c.windows.pop(WIN_FILES, None)
        return await c.wait_window("File Library: " + title)

    async def dialog(self, c, win_id):
        c.windows.pop(win_id, None)
        await c.wait_for(lambda: win_id in c.windows and c.windows[win_id].done, "window")
        return c.windows[win_id]

    async def transfer_over(self, c):
        """Wait for the transfer window's Cancel to become Close; its status line."""
        await c.wait_for(lambda: WIN_TRANSFER in c.windows and any(
            g["text"] == "Close" for g in c.windows[WIN_TRANSFER].gadgets.values()),
            "transfer over")
        w = c.windows[WIN_TRANSFER]
        return w.text(gadget_of(w, Kind.LABEL, -1))


class LibrariesTest(FileLibraryBase):
    async def test_new_edit_delete_library(self):
        alice, bob, d = self.alice, self.bob, self.server.db
        w = await self.open_files(bob)
        self.assertEqual(w.text(gadget_of(w, Kind.LABEL)), "There are no file libraries yet.")
        self.assertFalse(any(g["text"] == "New..." for g in w.gadgets.values()), "mods only")

        await self.open_files(alice)
        alice.click_text(WIN_FILES, "New...")
        dlg = await alice.wait_window("New Library")
        alice.value(WIN_LIB_EDIT, gadget_of(dlg, Kind.TEXTBOX), "C64 Games")
        alice.text(WIN_LIB_EDIT, gadget_of(dlg, Kind.EDIT), ["Games for the C64 mode.", "Enjoy!"])
        alice.click_text(WIN_LIB_EDIT, "OK")
        await alice.wait_for(lambda: WIN_LIB_EDIT not in alice.windows, "made")
        self.assertTrue(os.path.isdir(os.path.join(self.root, "c64_games")))
        lib = d.libraries()[0]
        self.assertEqual((lib["title"], lib["folder"], lib["description"], lib["auto_approve"]),
                         ("C64 Games", "c64_games", "Games for the C64 mode.\nEnjoy!", 1))
        await bob.wait_for(lambda: self.rows(bob) and self.rows(bob)[0].startswith("C64 Games"),
                           "bob's list follows")
        # its description shows under the list when it's picked
        await self.pick_row(bob, WIN_FILES, "C64 Games")
        bw = bob.windows[WIN_FILES]
        await bob.wait_for(lambda: bw.gadgets[gadget_of(bw, Kind.TEXTVIEW)]["lines"] ==
                           ["Games for the C64 mode.", "Enjoy!"], "description")

        # Edit: a new title renames the folder; uploads now held
        await self.pick_row(alice, WIN_FILES, "C64 Games")
        alice.click_text(WIN_FILES, "Edit...")
        dlg = await alice.wait_window("Edit Library")
        self.assertEqual(dlg.text(gadget_of(dlg, Kind.TEXTBOX)), "C64 Games")
        alice.value(WIN_LIB_EDIT, gadget_of(dlg, Kind.TEXTBOX), "Commodore Games")
        alice.select(WIN_LIB_EDIT, gadget_of(dlg, Kind.CHECKBOX), 0)
        alice.click_text(WIN_LIB_EDIT, "OK")
        await alice.wait_for(lambda: WIN_LIB_EDIT not in alice.windows, "saved")
        self.assertFalse(os.path.exists(os.path.join(self.root, "c64_games")))
        self.assertTrue(os.path.isdir(os.path.join(self.root, "commodore_games")))
        lib = d.library(lib["id"])
        self.assertEqual((lib["title"], lib["folder"], lib["auto_approve"]),
                         ("Commodore Games", "commodore_games", 0))

        # a second library may not take a title (any case) that's in use
        alice.click_text(WIN_FILES, "New...")
        dlg = await alice.wait_window("New Library")
        alice.value(WIN_LIB_EDIT, gadget_of(dlg, Kind.TEXTBOX), "commodore games")
        alice.click_text(WIN_LIB_EDIT, "OK")
        await alice.wait_for(lambda: "already" in status_of(alice.windows[WIN_LIB_EDIT]), "taken")
        alice.click_text(WIN_LIB_EDIT, "Cancel")

        # Delete: the entries go, the folder stays
        await self.pick_row(alice, WIN_FILES, "Commodore Games")
        alice.click_text(WIN_FILES, "Delete")
        await alice.wait_window("Delete Library")
        alice.click_text(WIN_DELETE, "Delete")
        await bob.wait_for(lambda: self.rows(bob) == [], "gone for bob")
        self.assertTrue(os.path.isdir(os.path.join(self.root, "commodore_games")))

    async def test_access_per_role(self):
        alice, bob, d = self.alice, self.bob, self.server.db
        self.library("Games")
        self.library("Staff Only")
        w = await self.open_files(bob)
        self.assertEqual([r.split()[0] for r in self.rows(bob)], ["Games", "Staff"])
        await self.open_files(alice)
        await self.pick_row(alice, WIN_FILES, "Staff Only")
        alice.click_text(WIN_FILES, "Access...")
        acc = await alice.wait_window("Library Access")
        boxes = [gid for gid, g in sorted(acc.gadgets.items()) if g["kind"] == Kind.CHECKBOX]
        roles = [r["name"] for r in d.roles()]
        member = roles.index("Member")
        for gid in boxes[member * 3: member * 3 + 3]:             # See, Download, Upload off
            alice.select(WIN_ACCESS, gid, 0)
        alice.click_text(WIN_ACCESS, "OK")
        await bob.wait_for(lambda: [r.split()[0] for r in self.rows(bob)] == ["Games"],
                           "Staff Only gone for bob")
        lib = next(x for x in d.libraries() if x["title"] == "Staff Only")
        self.assertEqual(d.library_access(lib["id"])[d.role_by_name("Member")["id"]],
                         (False, False, False))
        # a forged open of it does nothing
        b = self.server.screens.files.browsers[self.session("bob")]
        self.assertFalse(self.server.screens.files.can_see(self.session("bob"), lib))
        b.lib_id, b.view = lib["id"], "files"
        b.show()
        await bob.wait_for(lambda: bob.windows.get(WIN_FILES) and bob.windows[WIN_FILES].done
                           and bob.windows[WIN_FILES].title == "File Library", "back to list")


class FilesTest(FileLibraryBase):
    async def test_add_edit_and_download_to_a_drive(self):
        alice, bob, d = self.alice, self.bob, self.server.db
        lib_id = self.library("Games")
        data = bytes(range(256)) * 20 + b"\x01\x08"              # 5,122 bytes: six chunks
        with open(os.path.join(self.root, "games", "game.prg"), "wb") as f:
            f.write(data)
        await self.into(alice, "Games")
        alice.click_text(WIN_FILES, "Add...")
        dlg = await alice.wait_window("Add File")
        boxes = [gid for gid, g in sorted(dlg.gadgets.items()) if g["kind"] == Kind.TEXTBOX]
        # a path out of the library's folder is refused
        alice.value(WIN_FILE_EDIT, boxes[0], "GAME")
        alice.value(WIN_FILE_EDIT, boxes[1], "../../data/meganet.db")
        alice.click_text(WIN_FILE_EDIT, "OK")
        await alice.wait_for(lambda: "inside filelibs/games" in status_of(
            alice.windows[WIN_FILE_EDIT]), "refused")
        alice.value(WIN_FILE_EDIT, boxes[1], "nothere.prg")
        alice.click_text(WIN_FILE_EDIT, "OK")
        await alice.wait_for(lambda: "no file nothere.prg" in status_of(
            alice.windows[WIN_FILE_EDIT]), "missing")
        alice.value(WIN_FILE_EDIT, boxes[1], "game.prg")
        alice.text(WIN_FILE_EDIT, gadget_of(dlg, Kind.EDIT), ["A fun game."])
        alice.click_text(WIN_FILE_EDIT, "OK")
        await alice.wait_for(lambda: WIN_FILE_EDIT not in alice.windows, "added")
        f = d.library_files(lib_id)[0]
        self.assertEqual((f["name"], f["type"], f["path"], f["size"], f["description"]),
                         ("GAME", "PRG", "game.prg", len(data), "A fun game."))

        # bob downloads it to drive 8; the server never runs more than FILE_WINDOW ahead
        self.session("bob").caps = Caps.DRIVES
        bob.storage.drives[8] = {"name": "WORK", "files": {}}
        await self.into(bob, "Games")
        self.assertTrue(self.rows(bob)[0].strip().startswith("GAME"))
        await self.pick_row(bob, WIN_FILES, "GAME")
        bob.click_text(WIN_FILES, "Download...")
        dlg = await self.dialog(bob, WIN_DOWNLOAD)
        self.assertEqual(dlg.text(gadget_of(dlg, Kind.TEXTBOX)), "GAME")
        bob.click_text(WIN_DOWNLOAD, "Download")
        self.assertEqual(await self.transfer_over(bob), "Done: saved as GAME.")
        self.assertEqual(bob.storage.drives[8]["files"]["GAME"], (Local.PRG, data))
        self.assertLessEqual(bob.storage.max_ahead, FILE_WINDOW)
        self.assertEqual(d.library_file(f["id"])["downloads"], 1)
        # again: the name is taken on the disk, so nothing is overwritten
        bob.click_text(WIN_TRANSFER, "Close")
        bob.click_text(WIN_FILES, "Download...")
        await self.dialog(bob, WIN_DOWNLOAD)
        bob.click_text(WIN_DOWNLOAD, "Download")
        self.assertIn("already a file with that name", await self.transfer_over(bob))
        bob.click_text(WIN_TRANSFER, "Close")
        # to drive 9, where nothing answers
        dlg = None
        bob.click_text(WIN_FILES, "Download...")
        dlg = await self.dialog(bob, WIN_DOWNLOAD)
        bob.pick_dropdown(WIN_DOWNLOAD, gadget_of(dlg, Kind.DROPDOWN), 1)
        bob.click_text(WIN_DOWNLOAD, "Download")
        self.assertIn("Nothing answers", await self.transfer_over(bob))

        # Edit: the entry changes; a held flag shows nowhere for approved files
        await self.pick_row(alice, WIN_FILES, "GAME")
        alice.click_text(WIN_FILES, "Edit...")
        dlg = await alice.wait_window("Edit File")
        boxes = [gid for gid, g in sorted(dlg.gadgets.items()) if g["kind"] == Kind.TEXTBOX]
        alice.value(WIN_FILE_EDIT, boxes[0], "GAME V2")
        alice.value(WIN_FILE_EDIT, boxes[1], "game.prg")
        alice.click_text(WIN_FILE_EDIT, "OK")
        await bob.wait_for(lambda: self.rows(bob)[0].strip().startswith("GAME V2"), "renamed")

    async def test_window_paces_by_acks(self):
        bob = self.bob
        data = os.urandom(9000)
        self.library("Games", files=[("BIG", "SEQ", "big.seq", data)])
        self.session("bob").caps = Caps.DRIVES
        bob.storage.drives[8] = {"name": "WORK", "files": {}}
        bob.storage.hold_acks = True
        await self.into(bob, "Games")
        await self.pick_row(bob, WIN_FILES, "BIG")
        bob.click_text(WIN_FILES, "Download...")
        await self.dialog(bob, WIN_DOWNLOAD)
        bob.click_text(WIN_DOWNLOAD, "Download")
        await bob.wait_for(lambda: bob.storage.save and len(bob.storage.save["data"]) ==
                           FILE_WINDOW, "a window's worth")
        await self.roundtrip(bob)
        self.assertEqual(len(bob.storage.save["data"]), FILE_WINDOW, "no more without acks")
        bob.storage.hold_acks = False
        bob.storage.ack_all(bob)
        self.assertEqual(await self.transfer_over(bob), "Done: saved as BIG.")
        self.assertEqual(bob.storage.drives[8]["files"]["BIG"], (Local.SEQ, data))

    async def test_download_an_image_to_the_sd_card(self):
        bob = self.bob
        image = bytes(range(256)) * 3200                           # 819,200: a D81
        self.library("Disks", files=[("ELITE", "D81", "elite.d81", image)])
        bob.storage.sd = {"GAMES": {"OLD.D81": b"x" * 819200}, "README.TXT": b"hi"}
        await self.into(bob, "Disks")
        await self.pick_row(bob, WIN_FILES, "ELITE")
        # a client without SD writing is told so
        bob.alerts.clear()
        bob.click_text(WIN_FILES, "Download...")
        await bob.wait_for(lambda: bob.alerts, "can't")
        self.assertIn("can't write to it", bob.alerts[-1][1])
        self.session("bob").caps = ALL
        bob.click_text(WIN_FILES, "Download...")
        dlg = await self.dialog(bob, WIN_DOWNLOAD)
        lb = gadget_of(dlg, Kind.LISTBOX)
        await bob.wait_for(lambda: dlg.gadgets[lb]["rows"] == ["GAMES/"], "the card's folders")
        self.assertEqual(dlg.text(gadget_of(dlg, Kind.TEXTBOX)), "ELITE.D81")
        bob.select(WIN_DOWNLOAD, lb, 0)                             # into GAMES
        await bob.wait_for(lambda: dlg.gadgets[lb]["rows"] == ["../  (up a folder)",
                                                               "    OLD.D81"], "in GAMES")
        tb = gadget_of(dlg, Kind.TEXTBOX)
        bob.value(WIN_DOWNLOAD, tb, "bad name.d81")
        bob.click_text(WIN_DOWNLOAD, "Download")
        await bob.wait_for(lambda: "8.3" in status_of(bob.windows[WIN_DOWNLOAD]), "8.3 names")
        bob.value(WIN_DOWNLOAD, tb, "elite.d81")                    # (upper case on the card)
        bob.click_text(WIN_DOWNLOAD, "Download")
        self.assertEqual(await self.transfer_over(bob), "Done: saved as ELITE.D81.")
        self.assertEqual(bob.storage.sd["GAMES"]["ELITE.D81"], image)
        self.assertEqual(bob.storage.saves, [(0, "GAMES/ELITE.D81")])


class UploadTest(FileLibraryBase):
    async def test_upload_held_then_approved(self):
        alice, bob, d = self.alice, self.bob, self.server.db
        lib_id = self.library("Uploads", auto=False)
        nu = d.role_by_name("Member")["id"]
        self.assertIsNone(d.set_role_permissions(nu, d.role_permissions(nu) | {"files.upload"}))
        self.server.permissions_changed(role_id=nu)
        carol = await self.signed_on("carol")
        self.assertIsNone(d.set_user_role(d.user("carol")["id"], nu))
        self.server.permissions_changed(user_id=d.user("carol")["id"])
        await carol.wait_for(lambda: "File Library" in carol.menu_items("Areas"), "carol")

        program = b"\x01\x08" + bytes(range(200)) * 3
        bob.storage.drives[8] = {"name": "BOBS DISK", "files": {"HELLO": (Local.PRG, program),
                                                                "NOTES": (Local.SEQ, b"hi")}}
        self.session("bob").caps = Caps.DRIVES
        await self.into(bob, "Uploads")
        bob.click_text(WIN_FILES, "Upload...")
        dlg = await self.dialog(bob, WIN_UPLOAD)
        await self.pick_row(bob, WIN_UPLOAD, "HELLO")
        await bob.wait_for(lambda: dlg.text(gadget_of(dlg, Kind.TEXTBOX)) == "HELLO", "named")
        self.assertIn("Disk: BOBS DISK", [g["text"] for g in dlg.gadgets.values()][2])
        bob.value(WIN_UPLOAD, gadget_of(dlg, Kind.TEXTBOX), "HELLO")
        bob.text(WIN_UPLOAD, gadget_of(dlg, Kind.EDIT), ["Says hello."])
        alice.toasts.clear()
        bob.click_text(WIN_UPLOAD, "Upload")
        self.assertEqual(await self.transfer_over(bob), "Done: a moderator will look at it.")
        with open(os.path.join(self.root, "uploads", "hello.prg"), "rb") as f:
            self.assertEqual(f.read(), program)
        f = d.library_files(lib_id, held=True)[0]
        self.assertEqual((f["name"], f["type"], f["approved"], f["description"]),
                         ("HELLO", "PRG", 0, "Says hello."))
        await alice.wait_for(lambda: alice.toasts, "the moderators hear of it")
        self.assertIn("needs approving", alice.toasts[-1][2])
        # bob sees his own, marked; carol doesn't see it at all
        await bob.wait_for(lambda: self.rows(bob) and self.rows(bob)[0].startswith("? HELLO"),
                           "bob's held upload")
        await self.into(carol, "Uploads")
        self.assertEqual(self.rows(carol), [])

        # alice approves it: everyone sees it, bob hears
        await self.into(alice, "Uploads")
        await self.pick_row(alice, WIN_FILES, "? HELLO")
        await alice.wait_for(lambda: alice.enabled(WIN_FILES, "Approve"), "Approve on")
        bob.toasts.clear()
        alice.click_text(WIN_FILES, "Approve")
        await carol.wait_for(lambda: len(self.rows(carol)) == 1, "carol sees it")
        await bob.wait_for(lambda: bob.toasts, "bob hears")
        self.assertEqual(bob.toasts[-1][2], "Your upload HELLO is now in Uploads.")
        self.assertEqual(d.library_files(lib_id)[0]["approved"], 1)

    async def test_upload_an_image_from_the_sd_card(self):
        alice, d = self.alice, self.server.db
        lib_id = self.library("Disks")
        image = os.urandom(174848)                                  # a D64
        alice.storage.sd = {"C64": {"GAME.D64": image, "BAD.D64": b"x" * 100}}
        self.session("alice").caps = ALL
        await self.into(alice, "Disks")
        alice.click_text(WIN_FILES, "Upload...")
        dlg = await self.dialog(alice, WIN_UPLOAD)
        src = gadget_of(dlg, Kind.DROPDOWN)
        sources = dlg.gadgets[src]["rows"]
        self.assertEqual(sources[-1], "SD card")
        alice.pick_dropdown(WIN_UPLOAD, src, len(sources) - 1)
        await self.pick_row(alice, WIN_UPLOAD, "C64/")
        await self.pick_row(alice, WIN_UPLOAD, "BAD.D64")
        alice.click_text(WIN_UPLOAD, "Upload")
        await alice.wait_for(lambda: "isn't a D64 image" in status_of(alice.windows[WIN_UPLOAD]),
                             "a bad image is refused")
        await self.pick_row(alice, WIN_UPLOAD, "GAME.D64")
        await alice.wait_for(lambda: dlg.text(gadget_of(dlg, Kind.TEXTBOX)) == "GAME", "named")
        alice.value(WIN_UPLOAD, gadget_of(dlg, Kind.TEXTBOX), "GAME")
        alice.click_text(WIN_UPLOAD, "Upload")
        self.assertEqual(await self.transfer_over(alice), "Done: GAME is in Disks.")
        f = d.library_files(lib_id)[0]
        self.assertEqual((f["type"], f["path"], f["size"], f["approved"]),
                         ("D64", "game.d64", 174848, 1))
        with open(os.path.join(self.root, "disks", "game.d64"), "rb") as fh:
            self.assertEqual(zlib.crc32(fh.read()), zlib.crc32(image))

    async def test_damaged_upload_is_dropped(self):
        alice, d = self.alice, self.server.db
        lib_id = self.library("Disks")
        alice.storage.drives[8] = {"name": "X", "files": {"HELLO": (Local.PRG, b"\x01\x08ab")}}
        alice.storage.damage = True
        self.session("alice").caps = Caps.DRIVES
        await self.into(alice, "Disks")
        alice.click_text(WIN_FILES, "Upload...")
        dlg = await self.dialog(alice, WIN_UPLOAD)
        await self.pick_row(alice, WIN_UPLOAD, "HELLO")
        await alice.wait_for(lambda: dlg.text(gadget_of(dlg, Kind.TEXTBOX)) == "HELLO", "named")
        alice.value(WIN_UPLOAD, gadget_of(dlg, Kind.TEXTBOX), "HELLO")
        alice.click_text(WIN_UPLOAD, "Upload")
        self.assertEqual(await self.transfer_over(alice), "It arrived damaged. Try again.")
        self.assertEqual(d.library_files(lib_id, held=True), [])
        self.assertEqual(os.listdir(os.path.join(self.root, "disks")), [])
