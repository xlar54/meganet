"""Client updates (updates.py): a newer disk in filelibs/meganet_client/ is offered to older
clients when they connect; Download puts it on their SD card (filelib.Download), Later lets
them sign on as they are, and a client older than the disk's "oldest" can't sign on until it
has it. The disks' versions come from the VERSION file on each (d81.py)."""

import asyncio
import os
import unittest

from meganet import d81, updates
from meganet.protocol import Caps, Kind
from meganet.updates import WIN_UPDATE, parse_version, sd_name
from tests.test_server import ServerTest


def disk(files):
    """A D81 image with `files` {name: bytes} (each in one sector chain from track 41)."""
    img = bytearray(819200)
    t, s = 41, 0
    dirsec = ((40 - 1) * 40 + 3) * 256
    for i, (name, data) in enumerate(files.items()):
        e = dirsec + i * 32
        img[e + 2] = 0x82                            # a closed PRG
        img[e + 3], img[e + 4] = t, s
        img[e + 5:e + 21] = name.encode("latin-1").ljust(16, b"\xa0")
        chunks = [data[k:k + 254] for k in range(0, len(data), 254)] or [b""]
        for n, chunk in enumerate(chunks):
            off = ((t - 1) * 40 + s) * 256
            if n + 1 < len(chunks):
                s += 1
                img[off], img[off + 1] = t, s
            else:
                img[off], img[off + 1] = 0, len(chunk) + 1
            img[off + 2:off + 2 + len(chunk)] = chunk
        s += 1
    return bytes(img)


def client_disk(build, oldest=1, vname=None):
    text = b"build=%d\noldest=%d\n" % (build, oldest)
    if vname:
        text += b"name=%s\n" % vname.encode()
    return disk({"MEGANET": b"\x01\x20" + bytes(600), "VERSION": text})


class VersionTest(unittest.TestCase):
    def test_d81_and_version(self):
        img = client_disk(7, 3)
        self.assertEqual([f[0] for f in d81.files(img)], ["MEGANET", "VERSION"])
        self.assertEqual(len(d81.read(img, "meganet")), 602)
        self.assertEqual(parse_version(d81.read(img, "version").decode()),
                         {"build": 7, "oldest": 3, "name": "7"})
        self.assertIsNone(d81.read(img, "nothing"))
        self.assertIsNone(parse_version("hello"))
        self.assertEqual(parse_version("# a comment\nbuild = 4\n"),
                         {"build": 4, "oldest": 1, "name": "4"})
        self.assertEqual(parse_version("build=3\nname=2.1\noldest=1\n"),
                         {"build": 3, "oldest": 1, "name": "2.1"})
        with self.assertRaises(ValueError):
            d81.files(b"short")

    def test_sd_names(self):
        self.assertEqual(sd_name("2"), "MEGANET2.D81")
        self.assertEqual(sd_name("2.1"), "MEGANE21.D81")
        self.assertEqual(sd_name("3.0"), "MEGANE30.D81")


class UpdateTest(ServerTest):
    def put_disk(self, build, oldest=1, name="meganet.d81", vname=None):
        folder = os.path.join(self.server.filelibs_dir, updates.CLIENT_FOLDER)
        data = client_disk(build, oldest, vname)
        with open(os.path.join(folder, name), "wb") as f:
            f.write(data)
        return data

    async def connect(self, name, build, caps=Caps.SD_READ | Caps.SD_WRITE):
        c = await self.client(name)
        c.send_hello(build, caps)
        await c.wait_for(lambda: c.hello, "HELLO")
        return c

    def texts(self, w):
        out = [g["text"] for g in w.gadgets.values() if g["kind"] == Kind.LABEL]
        for t in out:                                   # (what the window's labels hold)
            assert len(t) <= 48, "a line too long for the update window: %r" % t
        return out

    async def test_no_disk_no_offer(self):
        c = await self.signed_on("alice", build=1)
        self.assertNotIn(WIN_UPDATE, c.windows)
        self.assertEqual(self.server.db.libraries(), [], "no library until there's a disk")

    async def test_up_to_date(self):
        self.put_disk(5)
        c = await self.signed_on("alice", build=5)
        self.assertNotIn(WIN_UPDATE, c.windows)

    async def test_optional_later(self):
        self.put_disk(5)
        c = await self.connect("old", 2)
        w = await c.wait_window("MegaNet Update")
        self.assertIn("MegaNet 5 is ready: you have version 2.", self.texts(w))
        self.assertIn("You can sign on as you are, or get it first.", self.texts(w))
        self.assertTrue(c.enabled(WIN_UPDATE, "Later"))
        c.click_text(WIN_UPDATE, "Later")
        await c.wait_for(lambda: WIN_UPDATE not in c.windows, "closed")
        ok, msg = await self.login(c, "frank", "pass1", new=True)
        self.assertTrue(ok, msg)
        # the library: made for the disk, with an entry for it
        libs = self.server.db.libraries()
        self.assertEqual([(x["title"], x["folder"]) for x in libs],
                         [("MegaNet Client", "meganet_client")])
        f = self.server.db.library_files(libs[0]["id"])[0]
        self.assertEqual((f["name"], f["type"], f["path"]), ("MEGANET 5", "D81", "meganet.d81"))

    async def test_named_and_only_the_newest_listed(self):
        self.put_disk(2, name="meganet2.d81")
        c = await self.signed_on("alice", build=2)              # (the server looks)
        self.put_disk(3, name="meganet3.d81", vname="2.1")
        c = await self.connect("old", 2)
        w = await c.wait_window("MegaNet Update")
        self.assertIn("MegaNet 2.1 is ready: you have version 2.", self.texts(w))
        lib = self.server.db.libraries()[0]
        files = self.server.db.library_files(lib["id"], held=True)
        self.assertEqual([(f["name"], f["path"]) for f in files],
                         [("MEGANET 2.1", "meganet3.d81")], "the older disk isn't listed")

    async def test_signing_on_closes_the_offer(self):
        self.put_disk(5)
        c = await self.connect("old", 3)
        await c.wait_window("MegaNet Update")
        ok, msg = await self.login(c, "frank", "pass1", new=True)
        self.assertTrue(ok, msg)
        await c.wait_for(lambda: WIN_UPDATE not in c.windows, "closed by signing on")

    async def test_download_to_the_sd_card(self):
        data = self.put_disk(5)
        self.put_disk(4, name="older.d81")              # (the newest is the one offered)
        c = await self.connect("old", 3)
        c.storage.sd = {"GAMES": {}}
        await c.wait_window("MegaNet Update")
        c.click_text(WIN_UPDATE, "Download")
        await c.wait_for(lambda: "MEGANET5.D81" in c.storage.sd, "saved")
        self.assertEqual(bytes(c.storage.sd["MEGANET5.D81"]), data)
        c.windows.pop(WIN_UPDATE, None)
        w = await c.wait_window("MegaNet Update")
        self.assertIn("Saved MEGANET5.D81: MegaNet version 5.", self.texts(w))
        c.click_text(WIN_UPDATE, "OK")
        await c.wait_for(lambda: WIN_UPDATE not in c.windows, "closed")
        ok, msg = await self.login(c, "frank", "pass1", new=True)
        self.assertTrue(ok, msg)
        # again: it's there already, which is fine
        c2 = await self.connect("again", 3)
        c2.storage.sd = {"MEGANET5.D81": b"x"}
        await c2.wait_window("MegaNet Update")
        c2.click_text(WIN_UPDATE, "Download")
        await c2.wait_for(lambda: any(t.startswith("Saved MEGANET5") for w in c2.windows.values()
                                      for t in self.texts(w)), "told")

    async def test_required(self):
        self.put_disk(5, oldest=4)
        c = await self.connect("old", 3)
        w = await c.wait_window("MegaNet Update")
        self.assertIn("This server needs version 4 or newer to sign on.", self.texts(w))
        self.assertFalse(any(g["text"] == "Later" for g in w.gadgets.values()))
        ok, msg = await self.login(c, "frank", "pass1", new=True)
        self.assertFalse(ok)
        self.assertIn("needs a newer MegaNet", msg)
        c.click_text(WIN_UPDATE, "Disconnect")
        for _ in range(200):                             # (the server closes the connection)
            if c._task.done():
                break
            await asyncio.sleep(0.02)
        self.assertTrue(c._task.done(), "disconnected")

    async def test_required_but_newer_than_oldest_is_fine(self):
        self.put_disk(5, oldest=4)
        c = await self.connect("old", 4)
        await c.wait_window("MegaNet Update")           # (offered, but may sign on)
        ok, msg = await self.login(c, "frank", "pass1", new=True)
        self.assertTrue(ok, msg)

    async def test_a_client_that_cant_save_to_sd(self):
        self.put_disk(5)
        c = await self.connect("old", 3, caps=Caps.NONE)
        w = await c.wait_window("MegaNet Update")
        self.assertIn("Your MegaNet can't save to an SD card:", self.texts(w))
        self.assertFalse(any(g["text"] == "Download" for g in w.gadgets.values()))
