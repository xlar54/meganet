"""Client updates: a newer MegaNet disk, offered to older clients when they connect.

Releasing a client: build it (client-src/VERSION says its build, and the oldest client that may
still sign on), and put target/meganet.d81 in the server's filelibs/meganet_client/ folder
(any name ending .d81: deploy.ps1 -PublishClient does it). The server reads the VERSION file
build.bat put on each disk (d81.py); the highest build there is the release. The folder is
the File Library's "MegaNet Client" library (made when the first disk appears, with an entry
for each disk), so anyone can also download it by hand.

When a client connects (HELLO's build) and the release is newer, the server shows the update
window before the Sign On (WIN_UPDATE): the versions, and
  - Download (the D81 to the SD card's root as MEGANETn.D81: filelib.Download, which every
    client with Caps.SD_WRITE already does: it stages the image, checks its CRC and writes
    it, never over a file that's there) and Later; or, when the client is older than the
    release's "oldest", Download and Disconnect, and it can't sign on.
Afterwards it says how to start the new disk (mount it as drive 8, reset). The disk the
client runs from isn't touched, so a dropped connection can't leave half an update.
"""

import os
import re

from . import d81
from .filelib import Download, Storage
from .protocol import Caps, GFlag, LOCAL_SD, LocalStatus, WFlag
from .ui import Label, Window, add_buttons

CLIENT_TITLE, CLIENT_FOLDER = "MegaNet Client", "meganet_client"
WIN_UPDATE = 0x49
W, H = 400, 90                           # (a line holds 48 characters)


def parse_version(text):
    """A VERSION file's text -> {"build": n, "oldest": n}, or None."""
    out = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.fullmatch(r"([a-z]+)\s*=\s*(\d+)", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    if "build" not in out:
        return None
    out.setdefault("oldest", 1)
    out["oldest"] = min(out["oldest"], out["build"])
    return out


def sd_name(build):
    """The update's 8.3 name on the SD card: MEGANET7.D81, then MN000012.D81."""
    base = "MEGANET%d" % build
    return (base if len(base) <= 8 else "MN%06d" % (build % 1000000)) + ".D81"


class Updates:
    def __init__(self, server):
        self.server = server
        self.disks = {}                  # path -> ((mtime, size), version or None)
        os.makedirs(self.folder(), exist_ok=True)

    @property
    def files(self):
        return self.server.screens.files

    def folder(self):
        return os.path.join(self.server.filelibs_dir, CLIENT_FOLDER)

    def library(self):
        """The "MegaNet Client" library's row, made if there's a disk to put in it."""
        db = self.files.db
        lib = next((x for x in db.libraries() if x["folder"] == CLIENT_FOLDER), None)
        if lib is None:
            lib_id = db.create_library(CLIENT_TITLE, CLIENT_FOLDER,
                                       "The MegaNet client, newest first: download one to "
                                       "your SD card and mount it as drive 8.")
            lib = db.library(lib_id) if lib_id else None
        return lib

    def releases(self):
        """[(version dict, path, size)] for the disks in the folder that say their version,
        newest first; each gets a library entry the first time it's seen."""
        out = []
        try:
            names = sorted(os.listdir(self.folder()))
        except OSError:
            return out
        for name in names:
            path = os.path.join(self.folder(), name)
            if not name.lower().endswith(".d81") or not os.path.isfile(path):
                continue
            st = os.stat(path)
            stamp = (st.st_mtime, st.st_size)
            got = self.disks.get(path)
            if got is None or got[0] != stamp:
                try:
                    with open(path, "rb") as f:
                        text = d81.read(f.read(), "VERSION")
                    version = parse_version(text.decode("latin-1")) if text else None
                except (OSError, ValueError):
                    version = None
                got = self.disks[path] = (stamp, version)
                if version is not None:
                    self.listed(name, version, st.st_size)
            if got[1] is not None:
                out.append((got[1], path, st.st_size))
        out.sort(key=lambda r: -r[0]["build"])
        return out

    def listed(self, name, version, size):
        """A library entry for the disk in `name` (once)."""
        lib = self.library()
        if lib is None:
            return
        db = self.files.db
        if db.library_file_by_path(lib["id"], name) is None:
            db.add_library_file(lib["id"], "MEGANET %d" % version["build"], "D81",
                                "MegaNet version %d." % version["build"], name, size)
            self.files.changed()

    def latest(self):
        r = self.releases()
        return r[0] if r else None

    def state(self, build):
        """None (up to date, or no release), "optional" or "required"."""
        rel = self.latest()
        if rel is None or build >= rel[0]["build"]:
            return None
        return "required" if build < rel[0]["oldest"] else "optional"

    # ---- the window, before the Sign On ----

    def offer(self, session):
        """After HELLO: the update window if there's a newer client."""
        state = self.state(session.build)
        if state is None:
            return False
        rel = self.latest()
        new = rel[0]["build"]
        session.updating = state == "required"
        session.log("client build %d, release %d: update %s" % (session.build, new, state))
        win = Window.centred("MegaNet Update", W, H, win_id=WIN_UPDATE,
                             flags=WFlag.MODAL | WFlag.MOVABLE)
        win.add(Label(8, 4, W - 16, 10, "MegaNet version %d is ready: you have version %d."
                      % (new, session.build), flags=GFlag.BOLD))
        if state == "required":
            lines = ["This server needs version %d or newer to sign on." % rel[0]["oldest"]]
        else:
            lines = ["You can sign on as you are, or get it first."]
        if session.caps & Caps.SD_WRITE:
            lines += ["Download saves it on your SD card as",
                      "%s. Your disk now stays as it is." % sd_name(new)]
            buttons = [("Download", lambda b: self.download(session), GFlag.DEFAULT)]
        else:
            lines += ["Your MegaNet can't save to an SD card:",
                      "ask the Sysop for the new disk."]
            buttons = []
        for i, text in enumerate(lines):
            win.add(Label(8, 18 + 12 * i, W - 16, 10, text))
        buttons.append(("Disconnect", lambda b: self.disconnect(session), 0)
                       if state == "required" else
                       ("Later", lambda b: self.later(session), 0))
        add_buttons(win, buttons)
        session.before_sign_on.add(WIN_UPDATE)
        win.show(session)
        return True

    def later(self, session):
        session.before_sign_on.discard(WIN_UPDATE)
        w = session.windows.get(WIN_UPDATE)
        if w is not None:
            w.close()

    def disconnect(self, session):
        session.log("update declined: disconnected")
        session.disconnect()

    def download(self, session):
        rel = self.latest()
        if rel is None or not session.caps & Caps.SD_WRITE:
            return None
        w = session.windows.get(WIN_UPDATE)
        if w is not None:
            w.close()
        if Storage.of(session).job is not None:
            return session.alert("MegaNet Update", "Wait for the transfer that's running.")
        lib = self.library()
        name = os.path.basename(rel[1])
        f = self.files.db.library_file_by_path(lib["id"], name) if lib else None
        try:
            with open(rel[1], "rb") as fh:
                data = fh.read()
        except OSError:
            return session.alert("MegaNet Update", "The server couldn't read the new disk.")
        if f is None:
            return session.alert("MegaNet Update", "The new disk isn't in its library.")
        session.before_sign_on.add(self.files.WIN_TRANSFER)
        UpdateDownload(self, session, f, sd_name(rel[0]["build"]), data, rel[0]).start()
        return None

    def done(self, session, path, version, ok):
        """The download's over: how to start the new disk (or, if it failed, what now)."""
        session.before_sign_on.add(WIN_UPDATE)
        win = Window.centred("MegaNet Update", W, H, win_id=WIN_UPDATE,
                             flags=WFlag.MODAL | WFlag.MOVABLE)
        if ok:
            lines = ["Saved %s: MegaNet version %d." % (path, version["build"]),
                     "To start it, hold RESTORE for the Freeze Menu,",
                     "press 0 for drive 8 and pick %s," % path,
                     "then reset the MEGA65."]
        else:
            lines = ["The new disk didn't arrive: try again, or get",
                     "it later from File Library > %s." % CLIENT_TITLE]
        for i, text in enumerate(lines):
            win.add(Label(8, 4 + 12 * i, W - 16, 10, text))
        if session.updating:                     # (required: nothing more to do here)
            add_buttons(win, [("Disconnect", lambda b: self.disconnect(session),
                               GFlag.DEFAULT)] + ([] if ok else [
                ("Try Again", lambda b: self.download(session), 0)]))
        else:
            add_buttons(win, [("OK", lambda b: self.later(session), GFlag.DEFAULT)])
        win.show(session)


class _Browser:
    """What filelib's Download needs of a File Library window: the session, the library."""

    def __init__(self, files, session):
        self.files, self.session = files, session
        self.db = files.db


class UpdateDownload(Download):
    """filelib.Download of the new disk to the SD card's root; then Updates.done."""

    def __init__(self, updates, session, f, path, data, version):
        super().__init__(_Browser(updates.files, session), f, LOCAL_SD, path, data)
        self.updates, self.version = updates, version

    def on_done(self, status, text):
        if self.over:
            return
        super().on_done(status, text)
        session, files = self.session, self.updates.files
        session.before_sign_on.discard(files.WIN_TRANSFER)
        ok = status in (LocalStatus.OK, LocalStatus.EXISTS)    # (EXISTS: got it before)
        session.log("update download %s: %s" % (self.path, "done" if status == LocalStatus.OK
                                                else "already there" if ok
                                                else "failed (%d)" % status))
        w = session.windows.get(files.WIN_TRANSFER)
        if w is not None:
            w.close()
        self.updates.done(session, self.path, self.version, ok)
