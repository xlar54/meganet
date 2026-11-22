"""Areas > SID Music (sidlib.py): SID tune libraries built on the File Library. Tunes listed
from their headers, played (the C64 data in resource slot 10, then S.SID_PLAY), stopped,
stepped through their songs; uploads and moderators' Add... only for tunes that pass the
6502 check; clients without Caps.SID told they need an update."""

import os
import time

from meganet import filelib, sidlib
from meganet.protocol import Caps, Icon, Kind, Local, SLOT_MUSIC
from meganet.session import SID_SLOT
from meganet.sidlib import SidLibrary, WIN_NOW
from tests.test_pages import PagesBase
from tests.test_roles import gadget_of
from tests.test_sidcheck import psid, play, GOOD

W = SidLibrary.WIN_FILES
TUNE = psid(GOOD, name=b"Good Tune")
TWO = psid(GOOD, name=b"Two Songs", songs=2)
BAD = psid(play(0x58), name=b"Bad Tune")              # CLI: refused


class SidBase(PagesBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.root = self.server.sidlibs_dir
        for c in (self.alice, self.bob):              # (they play SID tunes)
            c.caps |= Caps.SID
            self.session(c.name).caps |= Caps.SID

    def library(self, title, tunes=(), auto=True):
        """A library made in the database, with tunes [(path, data)] in its folder."""
        d = self.server.db
        folder = filelib.folder_for(title)
        lib_id = d.create_library(title, folder, "About " + title, auto, kind="sid")
        os.makedirs(os.path.join(self.root, folder), exist_ok=True)
        for path, data in tunes:
            with open(os.path.join(self.root, folder, path), "wb") as f:
                f.write(data)
            d.add_library_file(lib_id, path.split(".")[0].upper(), "SID", "", path, len(data),
                               kind="sid")
        return lib_id

    def rows(self, c):
        w = c.windows[W]
        return w.gadgets[gadget_of(w, Kind.LISTBOX)]["rows"]

    async def pick_row(self, c, win_id, start):
        w = c.windows[win_id]
        lb = gadget_of(w, Kind.LISTBOX)
        await c.wait_for(lambda: any(r and r.strip().startswith(start)
                                     for r in w.gadgets[lb]["rows"]), "row %r" % start)
        c.select(win_id, lb, next(i for i, r in enumerate(w.gadgets[lb]["rows"])
                                  if r and r.strip().startswith(start)))

    async def into(self, c, title):
        c.windows.pop(W, None)
        c.pick("SID Music")
        await c.wait_window("SID Music")
        await self.pick_row(c, W, title)
        c.click_text(W, "Open")
        c.windows.pop(W, None)
        return await c.wait_window("SID Music: " + title)

    def status(self, c):
        w = c.windows[W]
        return w.text(gadget_of(w, Kind.LABEL, -1))


class SidMusicTest(SidBase):
    async def test_list_play_stop(self):
        bob, d = self.bob, self.server.db
        lib_id = self.library("Classics", [("good.sid", TUNE), ("two.sid", TWO)])
        await self.into(bob, "Classics")
        rows = self.rows(bob)
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].startswith("  Good Tune "), rows[0])
        self.assertIn("Someone", rows[0])
        self.assertTrue(rows[0].endswith("2026  1"), rows[0])
        # Play: the C64 data to slot 10, then SID_PLAY
        await self.pick_row(bob, W, "Good Tune")
        await bob.wait_for(lambda: bob.enabled(W, "Play"), "Play on")
        bob.click_text(W, "Play")
        await bob.wait_for(lambda: bob.sid is not None, "SID_PLAY")
        s = bob.sid
        self.assertEqual((s["slot"], s["load"], s["init"], s["play"], s["song"], s["rate"]),
                         (SID_SLOT, 0x1000, 0x1000, 0x1003, 0, 50))
        self.assertEqual(s["data"], bytes(GOOD))
        await bob.wait_for(lambda: self.status(bob).startswith("Playing Good Tune"), "status")
        self.assertEqual(d.library_files(lib_id, kind="sid")[0]["downloads"], 1, "a play")
        # Song > on a tune with one song; then Stop
        bob.click_text(W, "Song >")
        await bob.wait_for(lambda: "only one song" in self.status(bob), "one song")
        bob.click_text(W, "Stop")
        await bob.wait_for(lambda: bob.sid is None, "SID_STOP")
        self.assertEqual(self.status(bob), "Stopped.")

    async def test_songs_and_cia_rate(self):
        bob = self.bob
        self.library("Multi", [("two.sid", psid(GOOD, name=b"Two Songs", songs=2,
                                                speed=0b10))])
        await self.into(bob, "Multi")
        await self.pick_row(bob, W, "Two Songs")
        await bob.wait_for(lambda: bob.enabled(W, "Play"), "Play on")
        bob.click_text(W, "Play")
        await bob.wait_for(lambda: bob.sid is not None, "SID_PLAY")
        self.assertEqual((bob.sid["song"], bob.sid["rate"]), (0, 50))
        bob.click_text(W, "Song >")
        await bob.wait_for(lambda: bob.sid["song"] == 1, "song 2")
        self.assertEqual(bob.sid["rate"], 60, "song 2 is CIA-timed: 60 a second")
        await bob.wait_for(lambda: "(song 2 of 2)" in self.status(bob), "status")
        n = len(bob.messages)
        bob.click_text(W, "Song >")                   # round to song 1; the data isn't resent
        await bob.wait_for(lambda: bob.sid["song"] == 0, "song 1 again")
        self.assertEqual(len(bob.sids), 3)

    async def test_a_client_without_sid(self):
        carol = await self.signed_on("carol")         # (no Caps.SID)
        self.library("Classics", [("good.sid", TUNE)])
        await self.into(carol, "Classics")
        await self.pick_row(carol, W, "Good Tune")
        await carol.wait_for(lambda: carol.enabled(W, "Play"), "Play on")
        carol.click_text(W, "Play")
        await carol.wait_for(lambda: "needs an update" in self.status(carol), "told")
        self.assertIsNone(carol.sid)

    async def test_add_checks_the_tune(self):
        alice = self.alice
        lib_id = self.library("Added")
        folder = os.path.join(self.root, "added")
        for name, data in (("good.sid", TUNE), ("bad.sid", BAD), ("not.sid", b"hello" * 50)):
            with open(os.path.join(folder, name), "wb") as f:
                f.write(data)
        await self.into(alice, "Added")
        for path, said in (("bad.sid", "turns interrupts on"), ("not.sid", "Not a SID tune"),
                           ("good.sid", "Added GOOD.")):
            alice.click_text(W, "Add...")
            dlg = await alice.wait_window("Add File")
            boxes = [g for g, x in sorted(dlg.gadgets.items()) if x["kind"] == Kind.TEXTBOX]
            alice.value(dlg.id, boxes[0], path.split(".")[0].upper())
            alice.value(dlg.id, boxes[1], path)
            alice.click_text(dlg.id, "OK")
            if said.startswith("Added"):
                await alice.wait_for(lambda: dlg.id not in alice.windows, "added")
                await alice.wait_for(lambda: self.status(alice) == said, said)
            else:
                await alice.wait_for(lambda: any(said in (g.get("text") or "")
                                                 for g in dlg.gadgets.values()), said)
                alice.click_text(dlg.id, "Cancel")
                await alice.wait_for(lambda: dlg.id not in alice.windows, "closed")
            alice.windows.pop(dlg.id, None)
        self.assertEqual([f["path"] for f in self.server.db.library_files(lib_id, kind="sid")],
                         ["good.sid"])

    async def test_upload_from_a_drive(self):
        bob, d = self.bob, self.server.db
        member = d.role_by_name("Member")["id"]
        d.set_role_permissions(member, d.role_permissions(member) | {"music.upload"})
        d.set_user_role(d.user("bob")["id"], member)
        self.server.permissions_changed(user_id=d.user("bob")["id"])
        await bob.wait_for(lambda: self.session("bob").can("music.upload"), "bob may upload")
        lib_id = self.library("Uploads")
        bob.storage.drives[8] = {"name": "MUSIC", "files": {"GOOD TUNE": (Local.PRG, TUNE),
                                                            "BAD TUNE": (Local.PRG, BAD)}}
        self.session("bob").caps = Caps.DRIVES | Caps.SD_READ | Caps.SID
        await self.into(bob, "Uploads")
        for name, said in (("BAD TUNE", "turns interrupts on"), ("GOOD TUNE", "Done:")):
            bob.click_text(W, "Upload")
            win = SidLibrary.WIN_UPLOAD
            bob.windows.pop(win, None)
            await bob.wait_for(lambda: win in bob.windows and bob.windows[win].done, "dialog")
            dlg = bob.windows[win]
            sources = next(x for x in dlg.gadgets.values() if x["kind"] == Kind.DROPDOWN)
            self.assertEqual(sources["rows"], ["Drive 8", "Drive 9", "Drive 10", "Drive 11",
                                               "SD card"])
            await self.pick_row(bob, win, name)
            await bob.wait_for(lambda: dlg.text(gadget_of(dlg, Kind.TEXTBOX)) == name, "named")
            bob.click_text(win, "Upload")
            tw = SidLibrary.WIN_TRANSFER
            await bob.wait_for(lambda: tw in bob.windows and any(
                g["text"] == "Close" for g in bob.windows[tw].gadgets.values()), "over")
            t = bob.windows[tw]
            self.assertIn(said, t.text(gadget_of(t, Kind.LABEL, -1)))
            bob.click_text(tw, "Close")
            await bob.wait_for(lambda: tw not in bob.windows, "closed")
        f = d.library_files(lib_id, kind="sid")
        self.assertEqual([(x["name"], x["type"]) for x in f], [("GOOD TUNE", "SID")])
        with open(os.path.join(self.root, "uploads", f[0]["path"]), "rb") as fh:
            self.assertEqual(fh.read(), TUNE)

    async def test_the_server_answers_while_a_tune_is_checked(self):
        """A slow check (this tune's init counts down 2.6 million cycles: a second or two
        in the 6502) runs in another process: bob's clicks are answered meanwhile."""
        alice, bob = self.alice, self.bob
        slow = psid([0xA9, 0x08, 0x85, 0x10,             # lda #8 / sta $10
                     0xA2, 0x00, 0xA0, 0x00,             # ldx #0 / ldy #0
                     0x88, 0xD0, 0xFD,                   # dey / bne
                     0xCA, 0xD0, 0xF8,                   # dex / bne (ldy #0)
                     0xC6, 0x10, 0xD0, 0xF2,             # dec $10 / bne (ldx #0)
                     0x60, 0x60], play=0x1013, name=b"Slow Tune")
        self.library("Added")
        with open(os.path.join(self.root, "added", "slow.sid"), "wb") as f:
            f.write(slow)
        await self.into(alice, "Added")
        alice.click_text(W, "Add...")
        dlg = await alice.wait_window("Add File")
        boxes = [g for g, x in sorted(dlg.gadgets.items()) if x["kind"] == Kind.TEXTBOX]
        alice.value(dlg.id, boxes[0], "SLOW")
        alice.value(dlg.id, boxes[1], "slow.sid")
        alice.click_text(dlg.id, "OK")
        await alice.wait_for(lambda: any(g.get("text") == "Checking the tune..."
                                         for g in dlg.gadgets.values()), "checking")
        t0 = time.monotonic()
        bob.pick("Who's Online")                         # meanwhile: answered at once
        await bob.wait_window("Who's Online")
        self.assertLess(time.monotonic() - t0, 0.5, "the server answered during the check")
        self.assertIn(dlg.id, alice.windows, "(still checking)")
        await alice.wait_for(lambda: dlg.id not in alice.windows, "checked and added")
        await alice.wait_for(lambda: self.status(alice) == "Added SLOW.", "added")

    async def test_the_menu_bar_note_and_now_playing(self):
        """Playing: a note in the menu bar (greyed when paused); its window pauses, resumes,
        goes to the next song, stops (the note goes) and opens SID Music at the tune."""
        bob = self.bob
        self.library("Multi", [("two.sid", TWO)])
        await self.into(bob, "Multi")
        await self.pick_row(bob, W, "Two Songs")
        await bob.wait_for(lambda: bob.enabled(W, "Play"), "Play on")
        self.assertEqual(bob.icon(SLOT_MUSIC), Icon.NONE)
        bob.click_text(W, "Play")
        await bob.wait_for(lambda: bob.icon(SLOT_MUSIC) == Icon.NOTE, "the note")
        self.assertEqual(bob.hint(SLOT_MUSIC), "Playing Two Songs (song 1 of 2).")
        # the note opens Now Playing
        bob.notify_click(SLOT_MUSIC)
        now = await bob.wait_window("Now Playing")
        texts = [g["text"] for g in now.gadgets.values()]
        self.assertIn("Two Songs", texts)
        self.assertIn("by Someone", texts)
        self.assertIn("Playing, song 1 of 2", texts)
        # Pause: the client holds it; the note greys; the window says so
        bob.click_text(WIN_NOW, "Pause")
        await bob.wait_for(lambda: bob.sid.get("paused") is True, "SID_PAUSE 1")
        await bob.wait_for(lambda: bob.icon(SLOT_MUSIC) == Icon.NOTE_PAUSED, "greyed")
        await bob.wait_for(lambda: any(g["text"] == "Paused, song 1 of 2" for g in
                                       bob.windows[WIN_NOW].gadgets.values()), "paused")
        self.assertIn("Paused: Two Songs", self.status(bob))
        bob.click_text(WIN_NOW, "Resume")
        await bob.wait_for(lambda: bob.sid.get("paused") is False, "SID_PAUSE 0")
        await bob.wait_for(lambda: bob.icon(SLOT_MUSIC) == Icon.NOTE, "black again")
        # Song >: the next song, from here too
        bob.click_text(WIN_NOW, "Song >")
        await bob.wait_for(lambda: bob.sid["song"] == 1, "song 2")
        await bob.wait_for(lambda: any(g["text"] == "Playing, song 2 of 2" for g in
                                       bob.windows[WIN_NOW].gadgets.values()), "song 2")
        # SID Music: the library, the tune picked
        bob.windows.pop(W, None)
        bob.click_text(WIN_NOW, "SID Music")
        w = await bob.wait_window("SID Music: Multi")
        lb = gadget_of(w, Kind.LISTBOX)
        await bob.wait_for(lambda: w.gadgets[lb].get("value") == 0, "the tune picked")
        # Stop: the note and the window go
        bob.notify_click(SLOT_MUSIC)
        await bob.wait_window("Now Playing")
        bob.click_text(WIN_NOW, "Stop")
        await bob.wait_for(lambda: bob.sid is None, "SID_STOP")
        await bob.wait_for(lambda: bob.icon(SLOT_MUSIC) == Icon.NONE, "the note goes")
        await bob.wait_for(lambda: WIN_NOW not in bob.windows, "Now Playing closes")

    async def test_upload_from_the_sd_card(self):
        """A Member uploads .SID files from the SD card: only those are listed; each is
        checked once it has arrived; a bad one isn't kept, and the full reason comes in an
        alert (it's longer than the transfer window's line)."""
        bob, d = self.bob, self.server.db
        member = d.role_by_name("Member")["id"]
        self.assertIn("music.upload", d.role_permissions(member), "Members may upload")
        d.set_user_role(d.user("bob")["id"], member)
        self.server.permissions_changed(user_id=d.user("bob")["id"])
        await bob.wait_for(lambda: self.session("bob").can("music.upload"), "bob may upload")
        lib_id = self.library("Uploads")
        bob.storage.sd = {"MUSIC": {"LOVE.SID": TUNE, "BAD.SID": BAD, "GAME.D81": b"x" * 9,
                                    "README.TXT": b"hi"}}
        self.session("bob").caps = Caps.SD_READ | Caps.SID
        await self.into(bob, "Uploads")
        win, tw = SidLibrary.WIN_UPLOAD, SidLibrary.WIN_TRANSFER
        for name, said in (("BAD.SID", "Not kept"), ("LOVE.SID", "Done:")):
            bob.click_text(W, "Upload")
            bob.windows.pop(win, None)
            await bob.wait_for(lambda: win in bob.windows and bob.windows[win].done, "dialog")
            dlg = bob.windows[win]
            await self.pick_row(bob, win, "MUSIC/")
            lb = gadget_of(dlg, Kind.LISTBOX)
            await bob.wait_for(lambda: any("LOVE.SID" in (r or "") for r in
                                           dlg.gadgets[lb]["rows"]), "the folder")
            rows = [r for r in dlg.gadgets[lb]["rows"] if r]
            self.assertEqual(len(rows), 3, "../, BAD.SID and LOVE.SID only: %r" % rows)
            await self.pick_row(bob, win, name)
            await bob.wait_for(lambda: dlg.text(gadget_of(dlg, Kind.TEXTBOX)) ==
                               name.split(".")[0], "named")
            n = len(bob.alerts)
            bob.click_text(win, "Upload")
            await bob.wait_for(lambda: tw in bob.windows and any(
                g["text"] == "Close" for g in bob.windows[tw].gadgets.values()), "over")
            t = bob.windows[tw]
            line = t.text(gadget_of(t, Kind.LABEL, -1))
            if said == "Done:":
                self.assertTrue(line.startswith("Done:"), line)
            else:
                self.assertIn("interrupts", line)
                await bob.wait_for(lambda: len(bob.alerts) > n, "the whole reason")
                self.assertIn("BAD wasn't added: It turns interrupts on (CLI)",
                              bob.alerts[-1][1])
                self.assertFalse(os.listdir(os.path.join(self.root, "uploads")), "not kept")
            bob.click_text(tw, "Close")
            await bob.wait_for(lambda: tw not in bob.windows, "closed")
        f = d.library_files(lib_id, kind="sid")
        self.assertEqual([(x["name"], x["type"]) for x in f], [("LOVE", "SID")])

    async def test_members_given_uploads_once(self):
        """An older database: music.upload was the Sysop's only. Once, every role that may
        upload art gets it too; taken away again in Roles, it stays away."""
        d = self.server.db
        member = d.role_by_name("Member")["id"]
        d.set_role_permissions(member, d.role_permissions(member) - {"music.upload"})
        d.set_setting(sidlib.UPLOADS_GIVEN, "")
        sidlib.give_members_uploads(d)
        self.assertIn("music.upload", d.role_permissions(member))
        d.set_role_permissions(member, d.role_permissions(member) - {"music.upload"})
        sidlib.give_members_uploads(d)
        self.assertNotIn("music.upload", d.role_permissions(member), "only once")

    async def test_separate_from_the_file_library(self):
        """Same titles allowed in both; the File Library doesn't see SID libraries."""
        d = self.server.db
        self.library("Games")
        self.assertIsNotNone(d.create_library("Games", "games"))
        self.assertEqual([x["title"] for x in d.libraries()], ["Games"])
        self.assertEqual([x["title"] for x in d.libraries(kind="sid")], ["Games"])
        self.assertTrue(os.path.isdir(os.path.join(self.root, "games")))
        self.assertNotEqual(self.root, self.server.filelibs_dir)
