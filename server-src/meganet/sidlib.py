"""Areas > SID Music (music.listen): libraries of C64 SID tunes, played by the client in the
background (sidplay.asm) while you do other things. Built on the File Library (filelib.py):
libraries are folders under the server's sidlibs/ (sidlibs/<title in lower case>), with the
same access rows per role (See, Listen, Upload), approvals and moderator tools
(music.moderate). Only PSID tunes that pass sidcheck.py's 6502 check go in: an upload, or a
file a moderator adds from the library's folder (Add...).

    $40 = SID Music: the libraries, then a library's tunes (Title, Author, Year, Songs; the
          picked one's details below): Play, Stop, Song > (the next song of a tune with
          several), Upload (a PSID from drive 8-11 as PRG / SEQ / USR, or a .SID file on
          the SD card: checked once it arrives, and not kept if it fails), Back;
          moderators also Add..., Edit..., Delete, Approve
    $41-$47 = its dialogs (filelib.py's: New / Edit Library, Add / Edit Tune, Upload, the
          transfer, Access, Delete)
    $48 = Now Playing: the tune, its author, playing / paused and the song; Pause / Resume,
          Stop, Song >, SID Music... (the library, the tune picked)

While a tune plays the menu bar shows a note (SLOT_MUSIC: Icon.NOTE, greyed when paused,
Icon.NOTE_PAUSED); clicking it opens Now Playing. The tune plays until Stop, another tune, or
signing off; the client's own sounds (the doorbell...) pause it while they play. Plays are
counted (the files' "downloads").
"""

import asyncio
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor

from . import permissions as perms
from . import sidcheck
from .filelib import FileLibrary, Browser, plural
from .protocol import Caps, GFlag, Icon, Local, SLOT_MUSIC, WFlag
from .ui import Label, Window, add_buttons

TITLE_W, AUTHOR_W = 22, 14               # the list's columns (47 characters in all)

# The tune checks run here: another process (a thread would still share the server's one
# Python interpreter lock), one at a time (uploads wait their turn)
_pool = None


def _checker():
    global _pool
    if _pool is None:                    # (spawned, not forked: a fork would copy the running
        _pool = ProcessPoolExecutor(     # server, its sockets and threads)
            max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    return _pool


def _reset_checker():
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
    _pool = None


UPLOADS_GIVEN = "music_upload_given"     # settings: done once


def give_members_uploads(db):
    """Once: every role that may upload art (gallery.upload: Members and up) may upload SID
    tunes too. (music.upload is one of the first permissions: a database made before SID
    Music had it for the Sysop only. An admin can take it away again in Roles.)"""
    if db.setting(UPLOADS_GIVEN):
        return
    for role in db.roles():
        keys = db.role_permissions(role["id"])
        if perms.GALLERY_UPLOAD in keys and perms.MUSIC_UPLOAD not in keys:
            db.set_role_permissions(role["id"], keys | {perms.MUSIC_UPLOAD})
    db.set_setting(UPLOADS_GIVEN, "1")
WIN_NOW = 0x48                           # Now Playing
NOW_W, NOW_H = 344, 62


class SidLibrary(FileLibrary):
    KIND = "sid"
    TITLE = "SID Music"
    NOUN = "SID music libraries"
    ROOT_ATTR = "sidlibs_dir"
    ROOT_NAME = "sidlibs"
    SEE, UPLOAD, MODERATE = perms.MUSIC_LISTEN, perms.MUSIC_UPLOAD, perms.MUSIC_MODERATE
    (WIN_FILES, WIN_LIB_EDIT, WIN_FILE_EDIT, WIN_DOWNLOAD, WIN_TRANSFER, WIN_UPLOAD, WIN_ACCESS,
     WIN_DELETE) = range(0x40, 0x48)
    TYPES = ["SID"]
    ACCESS_LABELS = ("See", "Listen", "Upload")
    SD_HINT = "Click a folder to open it, or a .SID file to send it."

    def sd_wanted(self, kind, name):
        return kind == Local.FILE and name.upper().endswith(".SID")

    def __init__(self, server):
        super().__init__(server)
        self.tunes = {}                  # real path -> ((mtime, size), Psid or None)
        give_members_uploads(server.db)

    CHECKING = "Checking the tune..."

    def upload_type(self, kind):
        return "SID"

    def data_problem(self, data):
        return sidcheck.problem(data)

    def check_data(self, data, then):
        """The 6502 check takes a second or more (up to sidcheck.CHECK_SECS): it runs in
        another process, one at a time, so the server goes on serving everyone meanwhile;
        then(problem) is called back here when it's done."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:                     # (no event loop: just do it)
            return then(self.data_problem(data))

        def done(fut):
            try:
                problem = fut.result()
            except Exception as e:               # (the checker process died: start afresh)
                _reset_checker()
                problem = "The tune couldn't be checked (%s): try again." % (
                    type(e).__name__)
            then(problem)
        loop.run_in_executor(_checker(), sidcheck.problem, data).add_done_callback(done)
        return None

    def tune(self, lib, f):
        """The tune in file entry `f` (its header and C64 data), or None if it's gone or
        isn't one any more. Read again only when the file changes."""
        path = self.file_path(lib, f["path"])
        try:
            st = os.stat(path) if path else None
        except OSError:
            st = None
        if st is None:
            return None
        stamp = (st.st_mtime, st.st_size)
        got = self.tunes.get(path)
        if got is None or got[0] != stamp:
            try:
                with open(path, "rb") as fh:
                    psid = sidcheck.parse(fh.read())
            except (OSError, sidcheck.TuneError):
                psid = None
            got = self.tunes[path] = (stamp, psid)
        return got[1]

    # ---- playing (one tune a session: session.sid_now) ----

    @staticmethod
    def now(session):
        """What this session's client is playing: {lib_id, file_id, title, author, song,
        songs, paused}, or None."""
        return session.sid_now if session.sid_playing is not None else None

    def now_text(self, session):
        now = self.now(session)
        if now is None:
            return None
        return ("%s %s%s." % ("Paused:" if now["paused"] else "Playing", now["title"],
                              " (song %d of %d)" % (now["song"] + 1, now["songs"])
                              if now["songs"] > 1 else ""))[:68]

    def start(self, session, lib, f, song=None):
        """Play file entry `f` (song `song`, 0-based; None: the tune's own start song).
        Returns what to say: why not, or what's playing."""
        if not session.caps & Caps.SID:
            return "Your MegaNet client can't play SID music: it needs an update."
        t = self.tune(lib, f)
        if t is None:
            return "That tune's file is missing or damaged."
        song = t.start - 1 if song is None else song % t.songs
        path = self.file_path(lib, f["path"])
        key = "sid %d %d" % (f["id"], int(os.path.getmtime(path)))
        session.play_sid(t, song, key)
        session.sid_now = dict(lib_id=lib["id"], file_id=f["id"], title=t.name or f["name"],
                               author=t.author, song=song, songs=t.songs, paused=False)
        if song == t.start - 1:
            self.db.count_download(f["id"])
        session.log("plays %s (song %d) from %s" % (f["path"], song + 1, lib["title"]))
        self.show_state(session)
        self.changed()
        return self.now_text(session)

    def stop(self, session):
        if self.now(session) is None:
            return "Nothing is playing."
        session.stop_sid()
        session.sid_now = None
        self.show_state(session)
        return "Stopped."

    def pause(self, session, paused):
        now = self.now(session)
        if now is None:
            return "Nothing is playing."
        if now["paused"] != paused:
            session.pause_sid(paused)
            now["paused"] = paused
            self.show_state(session)
        return self.now_text(session)

    def next_song(self, session):
        now = self.now(session)
        if now is None:
            return "Play a tune first; then Song > goes through its songs."
        if now["songs"] < 2:
            return "This tune has only one song."
        lib = self.db.library(now["lib_id"])
        f = self.db.library_file(now["file_id"]) if lib else None
        if f is None or not self.can_download(session, lib):
            return "That tune isn't in SID Music any more."
        return self.start(session, lib, f, now["song"] + 1)

    def show_state(self, session):
        """The menu bar's note, Now Playing and the SID Music window: as things are."""
        now = self.now(session)
        if now is None:
            session.set_notify(SLOT_MUSIC, Icon.NONE)
        else:
            session.set_notify(SLOT_MUSIC, Icon.NOTE_PAUSED if now["paused"] else Icon.NOTE,
                               self.now_text(session)[:40])
        np = getattr(session, "now_playing", None)
        if np is not None and np.win is not None and np.win.shown:
            if now is None:
                np.win.close()
            else:
                np.show()
        b = self.browsers.get(session)
        if b is not None and b.win is not None and b.win.shown and b.view == "files":
            b.say(self.now_text(session) or "Stopped.")

    def notify_click(self, session, slot):
        if slot != SLOT_MUSIC:
            return None
        if self.now(session) is None:
            return self.show_state(session)       # (gone: the icon goes too)
        np = getattr(session, "now_playing", None) or NowPlaying(self, session)
        session.now_playing = np
        return np.show()

    def permissions_changed(self, session):
        super().permissions_changed(session)
        if not session.can(self.SEE) and self.now(session) is not None:
            self.stop(session)


class NowPlaying:
    """The window the menu bar's note opens (WIN_NOW): what's playing, and its controls."""

    def __init__(self, music, session):
        self.music, self.session = music, session
        self.win = None

    def show(self):
        now = self.music.now(self.session)
        if now is None:
            return None
        win = Window.centred("Now Playing", NOW_W, NOW_H, win_id=WIN_NOW,
                             flags=WFlag.CLOSE | WFlag.MOVABLE)
        win.add(Label(8, 4, NOW_W - 16, 10, now["title"][:41], flags=GFlag.BOLD))
        win.add(Label(8, 16, NOW_W - 16, 10, ("by %s" % now["author"] if now["author"]
                                               else "")[:41]))
        win.add(Label(8, 28, NOW_W - 16, 10, (
            "Paused" if now["paused"] else "Playing") + (
            ", song %d of %d" % (now["song"] + 1, now["songs"]) if now["songs"] > 1 else "")))
        add_buttons(win, [("Resume" if now["paused"] else "Pause", self._pause, GFlag.DEFAULT),
                          ("Stop", self._stop, 0), ("Song >", self._next, 0),
                          ("SID Music", self._open, 0)])
        self.win = win
        win.show(self.session)
        return self

    def _ok(self):
        if not self.session.can(self.music.SEE):
            self.win.close()
            return False
        return True

    def _pause(self, button):
        if self._ok():
            now = self.music.now(self.session)
            self.music.pause(self.session, not (now and now["paused"]))

    def _stop(self, button):
        if self._ok():
            self.music.stop(self.session)

    def _next(self, button):
        if self._ok():
            said = self.music.next_song(self.session)
            if said and not said.startswith(("Playing", "Paused")):
                self.session.toast(said[:72])

    def _open(self, button):
        """SID Music, at the library playing, the tune picked."""
        if not self._ok():
            return None
        now = self.music.now(self.session)
        self.win.close()
        b = self.music.browsers.get(self.session) or SidBrowser(self.music, self.session)
        lib = self.music.db.library(now["lib_id"]) if now else None
        if lib is not None and self.music.can_see(self.session, lib):
            b.view, b.lib_id, b.file_id = "files", lib["id"], now["file_id"]
        else:
            b.view, b.lib_id, b.file_id = "libs", None, None
        return b.show()


class SidBrowser(Browser):
    """The SID Music window: filelib.Browser with a tune list and Play / Stop / Song >."""

    # the tunes
    def _rows_files(self, lib):
        rows = super()._rows_files(lib)          # (sets self.filelist and self.ids)
        out = []
        for f in self.filelist:
            t = self.files.tune(lib, f)
            title = (t.name if t and t.name else f["name"])[:TITLE_W]
            author = (t.author if t else "?")[:AUTHOR_W]
            year = (t.released[:4] if t and t.released[:4].isdigit() else "")
            out.append("%s %-*s %-*s %4s %2s" % (" " if f["approved"] else "?", TITLE_W, title,
                                                 AUTHOR_W, author, year,
                                                 t.songs if t else "?"))
        return out if len(out) == len(rows) else rows

    def _heading(self, lib):
        if self.view == "libs":
            return super()._heading(lib)
        held = lib["held"] if self.mod else 0
        return "%s: %s%s" % (lib["title"], plural(lib["files"], "tune"),
                             ", %d waiting for approval" % held if held else "")

    def _about(self):
        if self.view == "libs":
            return super()._about()
        f = self.db.library_file(self.file_id) if self.file_id in self.ids else None
        lib = self.library()
        if f is None or lib is None:
            return []
        t = self.files.tune(lib, f)
        if t is None:
            return ["%s: the file is missing or isn't a tune any more." % f["path"]]
        lines = ["%s by %s%s" % (t.name or f["name"], t.author or "?",
                                 " (%s)" % t.released if t.released else ""),
                 "%s, %s %s, %s%s" % (plural(t.songs, "song"), t.clock, t.model,
                                      plural(f["downloads"], "play"),
                                      ", from %s" % f["uploader_name"]
                                      if f["uploader_name"] else "")]
        if not f["approved"]:
            lines.append("(Waiting for a moderator to approve it.)")
        return lines + (f["description"].split("\n") if f["description"] else [])

    def _show_files(self, a, lib, status):
        rows = self._rows_files(lib)
        self.head = a.heading(self._heading(lib))
        self.list = a.list(rows, self._pick_file, about=True, about_lines=self._about(),
                           columns="  %-*s %-*s %4s %2s" % (TITLE_W, "Title", AUTHOR_W,
                                                            "Author", "Year", "#"))
        if self.file_id in self.ids:
            self.list.selected = self.ids.index(self.file_id)
        self.about = a.about_view
        self.need = []
        self.buttons_shown = self._rights(lib)
        if self.buttons_shown[0]:
            self.need.append(a.command("Play", self._download, default=True))
            a.pair(("Stop", self._stop), ("Song >", self._next_song))
        if self.buttons_shown[1]:                    # (side by side: room for Admin Tools)
            a.pair(("Upload", self._upload), ("Back", self._back))
        else:
            a.command("Back", self._back)
        if self.mod:
            a.section("Admin Tools")
            add_b, edit_b = a.pair(("Add...", self._add_file), ("Edit...", self._edit_file))
            delete_b, self.approve = a.pair(("Delete", self._delete_file),
                                            ("Approve", self._approve))
            self.need += [edit_b, delete_b]
        if status is None:
            status = self.files.now_text(self.session) or (
                "Pick a tune, then Play." if rows else "No tunes here yet.")
        self.status = a.status(status)

    # ---- playing (SidLibrary does it: the menu bar's note and Now Playing follow) ----

    def _download(self, button):
        """Play (the File Library's Download: double-clicking a tune plays it too)."""
        if not self._ok() or self.view != "files":
            return None
        lib = self._lib()
        if lib is None:
            return None
        if not self.files.can_download(self.session, lib):
            return self.say("You can't listen to this library.")
        f = self._file()
        if f is None:
            return None
        if not f["approved"] and not self.mod:
            return self.say("It can be played once a moderator approves it.")
        return self.say(self.files.start(self.session, lib, f) or "")

    def _stop(self, button):
        if self._ok():
            self.say(self.files.stop(self.session))

    def _next_song(self, button):
        if not self._ok() or self.view != "files":
            return None
        now = self.files.now(self.session)
        if now is None or now["file_id"] != self.file_id:
            return self.say("Play the tune first; then Song > goes through its songs.")
        return self.say(self.files.next_song(self.session))


SidLibrary.BROWSER = SidBrowser
