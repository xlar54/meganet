"""Areas > File Library (files.download): libraries, each a list of files, listed like the
chat rooms. Each library has a title, a description, its own folder on the server
(filelibs/<title in lower case, spaces as underscores>), access rows per role (See, Download,
Upload) and a setting for uploads: shown at once, or held until a moderator approves them.

    41 = File Library: one window with two views, re-sent as the user moves between them:
         - the libraries (title, files; the picked one's description below); Open. Holders of
           files.moderate also get, under "Admin Tools": New..., Edit..., Delete, Access...
         - a library's files (name, type, size, added, downloads; the picked one's description
           below); Download..., Upload... (when allowed), Back; moderators also Add...,
           Edit..., Delete and Approve (for held uploads)
    42 = New Library / Edit Library (modal): Title, Description, "Uploads show at once"
    43 = Add File / Edit File (modal): Filename, Type, Description, Server Path
    44 = Download (modal): PRG / SEQ / USR to drive 8-11 under a name; D64 / D81 to a folder
         of the SD card under an 8.3 name (the folders come from the client)
    45 = the transfer: what, a progress bar, Cancel (Close when it's over)
    46 = Upload (modal): from drive 8-11 or the SD card, a file picked from its directory, a
         Filename and a Description
    47 = Library Access (modal): per role, See / Download / Upload
    48 = Delete Library? / Delete File? (modal)

Who may do what:
- See a library: files.download, and its access row for the user's role allows seeing (no
  row: allowed). Moderators (files.moderate) see every library.
- Download from it: seeing it, and the row allows downloading. Upload to it: seeing it,
  files.upload, and the row allows uploading. Moderators may do both everywhere.
- Held uploads are seen only by moderators and by whoever uploaded them.
- Every handler checks again, since a client can send any CLICK.

The client's own storage (drives, the SD card) is reached through S.LOCAL_DIR / SAVE_BEGIN /
LOAD_FILE (protocol.py): Storage below runs one session's requests. What the client can do
comes in HELLO's caps (protocol.Caps).
"""

import os
import re
import time
import zlib

from . import permissions as perms
from .compose import refuse, MOD_ONLY
from .protocol import (S, C, Writer, WFlag, GFlag, clean_text, Caps, Local, LocalStatus,
                       LOCAL_SD, LOCAL_DRIVES, LOCAL_MAX, FILE_CHUNK, FILE_WINDOW, UP_CHUNK)
from .ui import (add_buttons, closer, Window, Button, Label, TextBox, ListBox, TextView,
                 TextArea, CheckBox, DropDown, Progress, Group, AreaWindow)

SEE, UPLOAD, MODERATE = perms.FILES_DOWNLOAD, perms.FILES_UPLOAD, perms.FILES_MODERATE

(WIN_FILES, WIN_LIB_EDIT, WIN_FILE_EDIT, WIN_DOWNLOAD, WIN_TRANSFER, WIN_UPLOAD, WIN_ACCESS,
 WIN_DELETE) = range(41, 49)
TITLE = "File Library"
W, H = 560, 160
ACCESS_ROLES = 6

TITLE_MAX = 24                   # a library's title
NAME_MAX = 16                    # a file's name: a CBM file name
LOCAL_PATH_MAX = 127             # what the client takes in a path (storage.asm ST_PATH_MAX)
DESC_LINES = 8                   # descriptions: lines of a text area
TYPES = ["PRG", "SEQ", "USR", "D64", "D81"]
DRIVE_TYPES = ("PRG", "SEQ", "USR")              # to drives 8-11
IMAGE_TYPES = ("D64", "D81")                      # to the SD card
KINDS = {"PRG": Local.PRG, "SEQ": Local.SEQ, "USR": Local.USR, "D64": Local.D64,
         "D81": Local.D81}
TYPE_OF = {v: k for k, v in KINDS.items()}
# the sizes a disk image may have (D64: 35 or 40 tracks, with or without error bytes)
IMAGE_SIZES = {"D64": (174848, 175531, 196608, 197376), "D81": (819200, 822400)}
CBM_BAD = set('",:*?=')
SD_NAME_RE = re.compile(r"[A-Z0-9_\-!#$%&()@^{}~]{1,8}\.(D64|D81)")


def when(t, fmt="%y-%m-%d"):
    return time.strftime(fmt, time.localtime(t))


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def size_text(n):
    """A short size for a list column: 300, 9.5K, 800K."""
    if n < 1000:
        return str(n)
    if n < 10240:
        return "%.1fK" % (n / 1024)
    return "%dK" % (n // 1024)


def folder_for(title):
    """A library's folder under filelibs/: the title in lower case, spaces as underscores,
    other characters that don't belong in a folder name dropped."""
    s = re.sub(r"[^a-z0-9_.\-]", "", title.strip().lower().replace(" ", "_")).strip("._")
    return s[:40] or "library"


def check_title(title):
    if not 1 <= len(title) <= TITLE_MAX:
        return "Library titles are 1-%d characters." % TITLE_MAX
    if not all(" " <= ch <= "~" for ch in title):
        return "Library titles are plain letters, digits and punctuation."
    return None


def check_cbm_name(name):
    """None if `name` is a good file name for a CBM drive."""
    if not 1 <= len(name) <= NAME_MAX:
        return "File names are 1-%d characters." % NAME_MAX
    if not all(" " <= ch <= "~" for ch in name):
        return "File names are plain letters, digits and punctuation."
    if CBM_BAD & set(name) or name[0] in "@$#":
        return "File names can't hold \" , : * ? = or start with @ $ #."
    return None


def sd_name(name, ftype):
    """The 8.3 name a file gets on the SD card by default: ELITE.D81."""
    base = re.sub(r"[^A-Z0-9_\-]", "", name.upper().replace(" ", "_"))[:8] or "IMAGE"
    return "%s.%s" % (base, ftype)


def check_sd_name(name, ftype):
    if not SD_NAME_RE.fullmatch(name) or not name.endswith("." + ftype):
        return "SD card names are 8.3: up to 8 letters or digits, then .%s." % ftype
    return None


def check_image(ftype, size):
    sizes = IMAGE_SIZES.get(ftype)
    if sizes and size not in sizes:
        return "That isn't a %s image: they're %s bytes, and it's %s." % (
            ftype, " or ".join("{:,}".format(s) for s in sizes[:2]), "{:,}".format(size))
    return None


def tidy_path(path):
    """A server path as typed, relative to a library's folder ("/" or "\\" between folders),
    or None if it leaves the folder (an absolute path, a drive, "..")."""
    p = path.strip().replace("\\", "/")
    if not p or p.startswith("/") or ":" in p:
        return None
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def tidy_lines(lines, n=DESC_LINES):
    out = [clean_text(s).rstrip() for s in lines][:n]
    while out and not out[-1]:
        out.pop()
    return out


class LibraryDB:
    """The database as one kind of library sees it: the library methods (db.py) with `kind`
    filled in; everything else as it is."""
    METHODS = frozenset((
        "libraries", "library", "create_library", "update_library", "delete_library",
        "library_access", "set_library_access", "library_files", "library_file",
        "library_file_by_path", "add_library_file", "update_library_file",
        "approve_library_file", "delete_library_file", "count_download"))

    def __init__(self, db, kind):
        self._db, self._kind = db, kind

    def __getattr__(self, name):
        attr = getattr(self._db, name)
        if name in self.METHODS:
            kind = self._kind
            return lambda *a, **kw: attr(*a, kind=kind, **kw)
        return attr


class FileLibrary:
    """Areas > File Library. Its settings are class attributes, so another kind of library
    (sidlib.py: SID Music) is a subclass with its own."""
    KIND = "files"                       # the database's tables (db.LIBRARY_TABLES)
    TITLE = "File Library"
    NOUN = "file libraries"              # ("There are no file libraries yet.")
    ROOT_ATTR = "filelibs_dir"           # the server's folder for them, and its name
    ROOT_NAME = "filelibs"
    SEE, UPLOAD, MODERATE = SEE, UPLOAD, MODERATE
    (WIN_FILES, WIN_LIB_EDIT, WIN_FILE_EDIT, WIN_DOWNLOAD, WIN_TRANSFER, WIN_UPLOAD, WIN_ACCESS,
     WIN_DELETE) = (WIN_FILES, WIN_LIB_EDIT, WIN_FILE_EDIT, WIN_DOWNLOAD, WIN_TRANSFER,
                    WIN_UPLOAD, WIN_ACCESS, WIN_DELETE)
    TYPES = TYPES                        # Add File / Edit File's types
    ACCESS_LABELS = ("See", "Download", "Upload")
    UPLOAD_SD = True                     # uploads from the SD card too (disk images)
    SD_HINT = "Click a folder to open it, or an image to send it."

    def sd_wanted(self, kind, name):
        """Which SD card files the Upload window lists (`kind` Local, `name` 8.3)."""
        return kind in (Local.D64, Local.D81)
    BROWSER = None                       # its window's class (None: Browser)

    def __init__(self, server):
        self.server = server
        self.root = getattr(server, self.ROOT_ATTR)
        os.makedirs(self.root, exist_ok=True)
        self.browsers = {}               # session -> Browser
        self._db = None

    @property
    def db(self):
        if self._db is None or self._db._db is not self.server.db:
            self._db = LibraryDB(self.server.db, self.KIND)
        return self._db

    # ---- paths on the server ----

    def folder_path(self, lib):
        return os.path.join(self.root, lib["folder"])

    def file_path(self, lib, path):
        """The real path of `path` (relative to the library's folder), or None if it isn't
        inside the folder after all (a link pointing out)."""
        base = os.path.realpath(self.folder_path(lib))
        full = os.path.realpath(os.path.join(base, path))
        return full if os.path.commonpath([base, full]) == base and full != base else None

    def unique_path(self, lib, name, ftype):
        """A new file name in the library's folder for an upload: my_game.prg, my_game_2.prg"""
        base = re.sub(r"[^a-z0-9_\-]", "", name.lower().replace(" ", "_"))[:32] or "file"
        n = 1
        while True:
            rel = "%s%s.%s" % (base, "" if n == 1 else "_%d" % n, ftype.lower())
            if not os.path.exists(os.path.join(self.folder_path(lib), rel)) and \
                    self.db.library_file_by_path(lib["id"], rel) is None:
                return rel
            n += 1

    # ---- who may do what ----

    def moderator(self, session):
        return session.can(self.MODERATE)

    # ---- what a library takes (another kind of library checks more) ----

    def upload_type(self, kind):
        """The type an upload of `kind` (Local) is kept as."""
        return TYPE_OF[kind]

    def data_problem(self, data):
        """None if `data` (an upload, or a file Add File points at) may go in; else why not."""
        return None

    CHECKING = None                      # what to say while check_data works (None: at once)

    def check_data(self, data, then):
        """Check `data` (data_problem), then call then(problem). Here at once; a library whose
        check is slow does it elsewhere and calls back later (sidlib.py), so `then` must
        look again at whatever may have changed meanwhile."""
        then(self.data_problem(data))

    def _row(self, session, lib):
        return self.db.library_access(lib["id"]).get(session.role_id, (True, True, True))

    def can_see(self, session, lib):
        if lib is None or not session.can(self.SEE):
            return False
        return self.moderator(session) or self._row(session, lib)[0]

    def can_download(self, session, lib):
        return self.can_see(session, lib) and (self.moderator(session)
                                                or self._row(session, lib)[1])

    def can_upload(self, session, lib):
        return (self.can_see(session, lib) and session.can(self.UPLOAD)
                and (self.moderator(session) or self._row(session, lib)[2]))

    def may_see_file(self, session, f):
        return bool(f["approved"]) or self.moderator(session) or f["uploader"] == session.user_id

    def libraries_for(self, session):
        return [lib for lib in self.db.libraries() if self.can_see(session, lib)]

    # ---- opening, and keeping everyone's windows in step ----

    def open(self, session):
        if not session.can(self.SEE):
            return refuse(session, self.TITLE, self.SEE)
        b = self.browsers.get(session) or (self.BROWSER or Browser)(self, session)
        b.view, b.lib_id, b.file_id = "libs", None, None
        return b.show()

    def changed(self):
        for b in list(self.browsers.values()):
            b.refresh()

    def permissions_changed(self, session):
        st = getattr(session, "storage", None)
        job = st.job if st is not None else None
        if job is not None and not session.can(self.UPLOAD if isinstance(job, Upload) else self.SEE):
            job.stop("Stopped: your account can't do that now.")
        b = self.browsers.get(session)
        if b is None:
            return
        if not session.can(self.SEE):
            b.close()
        else:
            b.show()                     # (the moderator buttons may come or go)

    def disconnected(self, session):
        self.browsers.pop(session, None)
        st = getattr(session, "storage", None)
        if st is not None:
            st.pending.clear()

    def tell_moderators(self, text):
        for s in self.server.sessions:
            if s.user is not None and not s.closed and s.can(self.MODERATE):
                s.toast(text, 8)


# ---------------------------------------------------------------------------------------------
# The client's storage: one session's requests (S.LOCAL_DIR / SAVE_BEGIN / LOAD_FILE)
# ---------------------------------------------------------------------------------------------

class Storage:
    """The requests running on one session's client storage. Each is an object with any of
    on_entry(kind, size, name, long), on_done(status, text), on_ack(n), on_up_begin(size),
    on_up_data(data), on_up_end(crc); replies to requests not here are ignored."""

    def __init__(self, session):
        self.session = session
        self.pending = {}                # req -> request object
        self.next_req = 0
        self.job = None                  # the transfer running (one at a time)

    @classmethod
    def of(cls, session):
        st = getattr(session, "storage", None)
        if st is None:
            st = session.storage = cls(session)
        return st

    def caps(self):
        return Caps(getattr(self.session, "caps", 0) & 0xFF)

    def start(self, request):
        """Give `request` a number (1-255) and wait for its replies. Only one directory
        listing is wanted at a time (one dialog shows one), so a new one drops any other;
        and should 254 ever be pending, the oldest goes."""
        if isinstance(request, DirRequest):
            for req, other in list(self.pending.items()):
                if isinstance(other, DirRequest):
                    del self.pending[req]
        while len(self.pending) >= 254:
            del self.pending[next(iter(self.pending))]
        self.next_req = self.next_req % 255 + 1
        while self.next_req in self.pending:
            self.next_req = self.next_req % 255 + 1
        request.req = self.next_req
        self.pending[request.req] = request
        return request.req

    def finish(self, request):
        if self.pending.get(getattr(request, "req", None)) is request:
            del self.pending[request.req]

    def cancel(self, request):
        if self.pending.get(getattr(request, "req", None)) is request:
            del self.pending[request.req]
            self.session.send(S.LOCAL_CANCEL, Writer().u8(request.req))

    def list_dir(self, dev, path, on_done):
        req = self.start(DirRequest(on_done))
        self.session.log("local request %d: directory of %s %r" % (req, dev, path))
        self.session.send(S.LOCAL_DIR, Writer().u8(req).u8(dev).str(path))
        return req

    def handle(self, msg_type, r):
        if msg_type == C.FILE_ACK:
            n = r.u32()
            job = self.job
            if job is not None and hasattr(job, "on_ack") and job.req in self.pending:
                return job.on_ack(n)
            return None
        req = r.u8()
        request = self.pending.get(req)
        if request is None:
            return None                  # (cancelled, or finished: a late reply)
        if msg_type == C.LOCAL_ENTRY:
            kind, size, name = r.u8(), r.u32(), r.str()
            long = r.str() if r.peek_u8() is not None else ""
            if hasattr(request, "on_entry"):
                request.on_entry(kind, size, name, long)
        elif msg_type == C.LOCAL_DONE:
            status, text = r.u8(), r.str()
            self.session.log("local request %d done: status %d %s" % (req, status, text))
            self.finish(request)
            if hasattr(request, "on_done"):
                request.on_done(status, text)
        elif msg_type == C.UP_BEGIN and hasattr(request, "on_up_begin"):
            request.on_up_begin(r.u32())
        elif msg_type == C.UP_DATA and hasattr(request, "on_up_data"):
            request.on_up_data(r.rest())
        elif msg_type == C.UP_END and hasattr(request, "on_up_end"):
            self.finish(request)
            request.on_up_end(r.u32())
        return None


class DirRequest:
    def __init__(self, on_done):
        self.entries = []                # (kind, size, name, long)
        self.callback = on_done

    def on_entry(self, kind, size, name, long):
        if len(self.entries) < 1000:
            self.entries.append((kind, size, clean_text(name), clean_text(long)))

    def on_done(self, status, text):
        self.callback(status, text, self.entries)


STATUS_TEXT = {
    LocalStatus.NO_DEVICE: "Nothing answers there: is the drive on, or the card in?",
    LocalStatus.NOT_FOUND: "That file or folder isn't there.",
    LocalStatus.EXISTS: "There's already a file with that name: pick another name.",
    LocalStatus.DISK_FULL: "There's no room for it.",
    LocalStatus.BAD_CRC: "It arrived damaged, so nothing was written. Try again.",
    LocalStatus.IO_ERROR: "The disk said no.",
    LocalStatus.UNSUPPORTED: "Your MegaNet client can't do that.",
    LocalStatus.TOO_BIG: "It's too big for your MegaNet client.",
    LocalStatus.CANCELLED: "Cancelled.",
}


def status_text(status, text):
    try:
        msg = STATUS_TEXT.get(LocalStatus(status), "Something went wrong (%d)." % status)
    except ValueError:
        msg = "Something went wrong (%d)." % status
    return ("%s  (%s)" % (msg, text) if text else msg)[:68]


def device_name(dev):
    return "the SD card" if dev == LOCAL_SD else "drive %d" % dev


# ---------------------------------------------------------------------------------------------
# One user's File Library window
# ---------------------------------------------------------------------------------------------

class Browser:
    def __init__(self, files, session):
        self.files = files
        self.session = session
        self.view = "libs"
        self.lib_id = self.file_id = None
        self.ids = []
        self.win = None

    @property
    def db(self):
        return self.files.db

    @property
    def mod(self):
        return self.files.moderator(self.session)

    def say(self, text):
        if self.win is not None and self.win.shown:
            self.status.set_text(text)

    def close(self):
        self.files.browsers.pop(self.session, None)
        for win_id in (self.files.WIN_LIB_EDIT, self.files.WIN_FILE_EDIT, self.files.WIN_DOWNLOAD, self.files.WIN_UPLOAD, self.files.WIN_ACCESS,
                       self.files.WIN_DELETE, self.files.WIN_FILES):
            win = self.session.windows.get(win_id)
            if win is not None:
                win.close()

    def _closed(self, window):
        if self.files.browsers.get(self.session) is self:
            del self.files.browsers[self.session]

    def library(self):
        return self.db.library(self.lib_id) if self.lib_id is not None else None

    # ---- the two views ----

    def show(self, status=None):
        self.files.browsers[self.session] = self
        lib = self.library()
        if self.view == "files" and not self.files.can_see(self.session, lib):
            self.view, self.lib_id = "libs", None
            lib = None
        title = self.files.TITLE if self.view == "libs" else "%s: %s" % (self.files.TITLE, lib["title"])
        a = AreaWindow(title, self.files.WIN_FILES, on_close=self._closed)
        win = self.win = a.win
        getattr(self, "_show_" + self.view)(a, lib, status)
        self.buttons()
        win.show(self.session)
        if self.list.selected is not None:
            self.list.set_value(self.list.selected)
        return self

    def refresh(self):
        if self.win is None or not self.win.shown:
            return None
        lib = self.library()
        if self.view == "files" and not self.files.can_see(self.session, lib):
            self.view = "libs"
            return self.show("That library is gone." if lib is None else
                             "You can't use that library now.")
        if self.view == "files" and self._rights(lib) != self.buttons_shown:
            return self.show()
        keep = self.lib_id if self.view == "libs" else self.file_id
        self.list.set_rows(getattr(self, "_rows_" + self.view)(lib))
        if keep in self.ids:
            self.list.selected = self.ids.index(keep)
            self.list.set_value(self.list.selected)
        else:
            self.list.selected = None
            if self.view == "libs":
                self.lib_id = None
            else:
                self.file_id = None
        self.head.set_text(self._heading(lib))
        self.about.set_lines(self._about())
        self.buttons()
        return None

    def picked(self):
        pid = self.lib_id if self.view == "libs" else self.file_id
        return pid if pid in self.ids else None

    def buttons(self):
        on = self.picked() is not None
        for b in self.need:
            b.enable(on)
        if self.view == "files" and self.mod:
            f = self.db.library_file(self.file_id) if on else None
            self.approve.enable(bool(f and not f["approved"]))

    def _heading(self, lib):
        if self.view == "libs":
            n = len(self.libs)
            if not n:
                return "There are no %s yet." % self.files.NOUN
            return "%d librar%s." % (n, "y" if n == 1 else "ies")
        held = lib["held"] if self.mod else 0
        return "%s: %s%s" % (lib["title"], plural(lib["files"], "file"),
                             ", %d waiting for approval" % held if held else "")

    def _about(self):
        """The picked library's or file's description, below the list."""
        if self.view == "libs":
            lib = self.db.library(self.lib_id) if self.lib_id in self.ids else None
            return lib["description"].split("\n") if lib and lib["description"] else (
                [] if lib is None else ["(No description.)"])
        f = self.db.library_file(self.file_id) if self.file_id in self.ids else None
        if f is None:
            return []
        lines = ["%s %s, {:,} bytes, %s%s".format(f["size"]) % (
            f["name"], f["type"], plural(f["downloads"], "download"),
            ", from %s" % f["uploader_name"] if f["uploader_name"] else "")]
        if not f["approved"]:
            lines.append("(Waiting for a moderator to approve it.)")
        return lines + (f["description"].split("\n") if f["description"] else [])

    # the libraries
    def _rows_libs(self, lib=None):
        self.libs = self.files.libraries_for(self.session)
        self.ids = [x["id"] for x in self.libs]
        rows = []
        for x in self.libs:
            extra = ""
            if self.mod:
                access = self.db.library_access(x["id"])
                flags = (["%d held" % x["held"]] if x["held"] else []) + (
                    ["limited"] if any(not all(v) for v in access.values()) else [])
                extra = " ".join(flags)
            rows.append(("%-*s %4d file%s %s" % (TITLE_MAX, x["title"], x["files"],
                                                 " " if x["files"] == 1 else "s",
                                                 extra)).rstrip())
        return rows

    def _show_libs(self, a, lib, status):
        rows = self._rows_libs()
        self.head = a.heading(self._heading(None))
        self.list = a.list(rows, self._pick_lib, about=True, about_lines=self._about())
        if self.lib_id in self.ids:
            self.list.selected = self.ids.index(self.lib_id)
        self.about = a.about_view
        self.need = [a.command("Open", self._open_lib, default=True)]
        if self.mod:
            a.section("Admin Tools")
            new_b, edit_b = a.pair(("New...", self._new_lib), ("Edit...", self._edit_lib))
            self.need += [edit_b, a.pair(("Delete", self._delete_lib)),
                          a.command("Access...", self._access)]
        if status is None:
            status = "Pick a library and Open it." if rows else (
                "New... makes one." if self.mod else "There are no %s yet." % self.files.NOUN)
        self.status = a.status(status)

    # a library's files
    def _rows_files(self, lib):
        fs = [f for f in self.db.library_files(lib["id"], held=True)
              if self.files.may_see_file(self.session, f)]
        self.filelist = fs
        self.ids = [f["id"] for f in fs]
        return ["%s %-*s %-3s %6s %s %4d" % (" " if f["approved"] else "?", NAME_MAX,
                                             f["name"][:NAME_MAX], f["type"],
                                             size_text(f["size"]), when(f["added"]),
                                             f["downloads"]) for f in fs]

    def _rights(self, lib):
        """(Download..., Upload...) shown in the files view."""
        return (self.files.can_download(self.session, lib), self.files.can_upload(self.session, lib))

    def _show_files(self, a, lib, status):
        rows = self._rows_files(lib)
        self.head = a.heading(self._heading(lib))
        self.list = a.list(rows, self._pick_file, about=True, about_lines=self._about(),
                           columns="  %-*s %-3s %6s %-8s %4s" % (
                               NAME_MAX, "Name", "Typ", "Size", "Added", "Got"))
        if self.file_id in self.ids:
            self.list.selected = self.ids.index(self.file_id)
        self.about = a.about_view
        self.need = []
        self.buttons_shown = self._rights(lib)          # (refresh: re-shown if they change)
        if self.buttons_shown[0]:
            self.need.append(a.command("Download...", self._download, default=True))
        if self.buttons_shown[1]:
            a.command("Upload...", self._upload)
        a.command("Back", self._back)
        if self.mod:
            a.section("Admin Tools")
            add_b, edit_b = a.pair(("Add...", self._add_file), ("Edit...", self._edit_file))
            delete_b, self.approve = a.pair(("Delete", self._delete_file),
                                            ("Approve", self._approve))
            self.need += [edit_b, delete_b]
        if status is None:
            status = "Pick a file to read about it." if rows else "No files here yet."
        self.status = a.status(status)

    # ---- handlers: everyone ----

    def _ok(self):
        if not self.session.can(self.files.SEE):
            refuse(self.session, self.files.TITLE, self.files.SEE)
            self.close()
            return False
        return True

    def _lib(self):
        """The library in view, if this user may still see it (else back to the list)."""
        lib = self.library()
        if not self.files.can_see(self.session, lib):
            self.view, self.lib_id = "libs", None
            self.show("That library is gone." if lib is None else "You can't use that library.")
            return None
        return lib

    def _pick_lib(self, listbox, index, double):
        if not self._ok() or listbox.selected is None or self.view != "libs":
            return None
        self.lib_id = self.ids[listbox.selected]
        self.buttons()
        if double:
            return self._open_lib(None)
        self.about.set_lines(self._about())
        return self.say("")

    def _open_lib(self, button):
        if not self._ok() or self.view != "libs":
            return None
        if self.lib_id not in self.ids:
            return self.say("Pick a library first.")
        if self._lib() is None:
            return None
        self.view, self.file_id = "files", None
        return self.show()

    def _pick_file(self, listbox, index, double):
        if not self._ok() or listbox.selected is None or self.view != "files":
            return None
        self.file_id = self.ids[listbox.selected]
        self.buttons()
        self.about.set_lines(self._about())
        if double and self.files.can_download(self.session, self.library()):
            return self._download(None)
        return self.say("")

    def _back(self, button):
        if self._ok():
            self.view = "libs"
            self.show()

    def _file(self):
        """The picked file, if it's still there and this user may see it."""
        f = self.db.library_file(self.file_id) if self.file_id in self.ids else None
        if f is None or not self.files.may_see_file(self.session, f):
            self.say("Pick a file first.")
            return None
        return f

    def _download(self, button):
        if not self._ok() or self.view != "files":
            return None
        lib = self._lib()
        if lib is None:
            return None
        if not self.files.can_download(self.session, lib):
            return self.say("You can't download from this library.")
        f = self._file()
        if f is None:
            return None
        if not f["approved"] and not self.mod:
            return self.say("It can be downloaded once a moderator approves it.")
        return DownloadDialog(self, lib, f).show()

    def _upload(self, button):
        if not self._ok() or self.view != "files":
            return None
        lib = self._lib()
        if lib is None:
            return None
        if not self.files.can_upload(self.session, lib):
            return self.say("You can't upload to this library.")
        return UploadDialog(self, lib).show()

    # ---- handlers: moderators ----

    def _mod_ok(self):
        if not self.session.can(self.files.MODERATE):
            refuse(self.session, self.files.TITLE, self.files.MODERATE, MOD_ONLY)
            return False
        return self._ok()

    def _picked_lib(self):
        lib = self.db.library(self.lib_id) if self.lib_id in self.ids else None
        if lib is None:
            self.say("Pick a library first.")
        return lib

    def _new_lib(self, button):
        if self._mod_ok() and self.view == "libs":
            LibraryDialog(self, None).show()

    def _edit_lib(self, button):
        if self._mod_ok() and self.view == "libs":
            lib = self._picked_lib()
            if lib is not None:
                LibraryDialog(self, lib).show()

    def _delete_lib(self, button):
        if not self._mod_ok() or self.view != "libs":
            return None
        lib = self._picked_lib()
        if lib is None:
            return None
        n = len(self.db.library_files(lib["id"], held=True))
        win = Window.centred("Delete Library", 400, 62,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE, win_id=self.files.WIN_DELETE)
        win.lib_id = lib["id"]
        win.add(Label(8, 4, 384, 10, "Delete %s and its %d file entr%s?" % (
            lib["title"], n, "y" if n == 1 else "ies")))
        win.add(Label(8, 16, 384, 10, "The folder %s/%s stays on the server." % (self.files.ROOT_NAME, lib["folder"])))
        win.add(Label(8, 28, 384, 10, "This can't be undone."))
        add_buttons(win, [("Delete", self._confirm_delete_lib, 0),
                          ("Cancel", closer, GFlag.DEFAULT)], centre=True)
        win.show(self.session)
        return None

    def _confirm_delete_lib(self, button):
        win = button.window
        win.close()
        if not self._mod_ok():
            return None
        lib = self.db.library(win.lib_id)
        if lib is None:
            return None
        self.db.delete_library(lib["id"])
        self.session.log("deleted library %s" % lib["title"])
        self.lib_id = None
        if self.view == "libs":
            self.show("Deleted %s." % lib["title"])
        self.files.changed()
        return None

    def _access(self, button):
        if not self._mod_ok() or self.view != "libs":
            return None
        lib = self._picked_lib()
        if lib is None:
            return None
        roles = self.db.roles()[:ACCESS_ROLES]
        access = self.db.library_access(lib["id"])
        h = 30 + 13 * len(roles) + 34
        win = Window.centred("Library Access", 400, h,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE, win_id=self.files.WIN_ACCESS)
        win.lib_id = lib["id"]
        win.add(Label(8, 4, 384, 10, "Who may use %s?" % lib["title"]))
        win.add(Label(8, 18, 160, 10, "Role"))
        win.boxes = []
        for i, r in enumerate(roles):
            y = 30 + 13 * i
            see, down, up = access.get(r["id"], (True, True, True))
            keys = self.db.role_permissions(r["id"])
            win.add(Label(8, y + 1, 152, 10, (r["name"] + ("" if self.files.SEE in keys else " *"))[:19]))
            see_l, down_l, up_l = self.files.ACCESS_LABELS
            sb = win.add(CheckBox(160, y, 56, 12, see_l, see))
            db_ = win.add(CheckBox(224, y, 88, 12, down_l, down))
            ub = win.add(CheckBox(320, y, 72, 12, up_l, up))
            win.boxes.append((r["id"], sb, db_, ub))
        y = 30 + 13 * len(roles) + 2
        win.add(Label(8, y + 2, 384, 10, "* no %s at all (Admin > Roles)" % self.files.NOUN))
        add_buttons(win, [("OK", self._access_ok, GFlag.DEFAULT), ("Cancel", closer, 0)],
                    y=y + 16)
        win.show(self.session)
        return None

    def _access_ok(self, button):
        win = button.window
        win.close()
        if not self._mod_ok():
            return None
        lib = self.db.library(win.lib_id)
        if lib is None:
            return None
        access = self.db.library_access(lib["id"])
        for role_id, sb, db_, ub in win.boxes:
            access[role_id] = (sb.checked or db_.checked or ub.checked, db_.checked, ub.checked)
        access = {k: v for k, v in access.items() if v != (True, True, True)}
        self.db.set_library_access(lib["id"], access)
        self.session.log("library %s access %r" % (lib["title"], access))
        self.files.changed()
        return self.say("Saved who may use %s." % lib["title"])

    def _add_file(self, button):
        if self._mod_ok() and self.view == "files":
            lib = self._lib()
            if lib is not None:
                FileDialog(self, lib, None).show()

    def _edit_file(self, button):
        if not self._mod_ok() or self.view != "files":
            return None
        lib = self._lib()
        f = self._file() if lib else None
        if f is not None:
            FileDialog(self, lib, f).show()
        return None

    def _delete_file(self, button):
        if not self._mod_ok() or self.view != "files":
            return None
        lib = self._lib()
        f = self._file() if lib else None
        if f is None:
            return None
        win = Window.centred("Delete File", 400, 62,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE, win_id=self.files.WIN_DELETE)
        win.file_id = f["id"]
        win.add(Label(8, 4, 384, 10, "Delete %s from %s?" % (f["name"], lib["title"])))
        win.remove = win.add(CheckBox(8, 18, 384, 12, ("Delete %s from the server too" % (
            f["path"]))[:46]))
        add_buttons(win, [("Delete", self._confirm_delete_file, 0),
                          ("Cancel", closer, GFlag.DEFAULT)], centre=True)
        win.show(self.session)
        return None

    def _confirm_delete_file(self, button):
        win = button.window
        win.close()
        if not self._mod_ok():
            return None
        f = self.db.library_file(win.file_id)
        lib = self.db.library(f["library_id"]) if f else None
        if lib is None:
            return None
        self.db.delete_library_file(f["id"])
        gone = ""
        if win.remove.checked:
            path = self.files.file_path(lib, f["path"])
            try:
                if path and os.path.isfile(path):
                    os.remove(path)
                    gone = " and removed it from the server"
            except OSError as e:
                gone = ", but couldn't remove it from the server (%s)" % e.strerror
        self.session.log("deleted file %s (%s)%s" % (f["name"], f["path"], gone))
        self.file_id = None
        self.files.changed()
        return self.say(("Deleted %s%s." % (f["name"], gone))[:68])

    def _approve(self, button):
        if not self._mod_ok() or self.view != "files":
            return None
        f = self._file()
        if f is None:
            return None
        if f["approved"]:
            return self.say("%s is already approved." % f["name"])
        self.db.approve_library_file(f["id"])
        lib = self.db.library(f["library_id"])
        self.session.log("approved %s in %s" % (f["name"], lib["title"]))
        up = next((s for s in self.files.server.sessions if s.user_id == f["uploader"]
                   and s.user is not None), None)
        if up is not None and up is not self.session:
            up.toast("Your upload %s is now in %s." % (f["name"], lib["title"]))
        self.files.changed()
        return self.say("Approved %s: everyone can see it now." % f["name"])


# ---------------------------------------------------------------------------------------------
# The moderators' dialogs
# ---------------------------------------------------------------------------------------------

class LibraryDialog:
    """New Library / Edit Library (its library's WIN_LIB_EDIT)."""
    W, H = 420, 124

    def __init__(self, browser, lib):
        self.b = browser
        self.lib_id = lib["id"] if lib else None
        self.lib = lib

    def show(self):
        lib = self.lib
        win = Window.centred("Edit Library" if lib else "New Library", self.W, self.H,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=self.b.files.WIN_LIB_EDIT)
        win.add(Label(8, 6, 96, 10, "Title:"))
        self.title = win.add(TextBox(112, 4, 300, 12, lib["title"] if lib else ""))
        win.add(Label(8, 20, 96, 10, "Folder:"))
        root = self.b.files.ROOT_NAME
        win.add(Label(112, 20, 300, 10, "%s/%s" % (root, lib["folder"]) if lib else
                      "%s/ and the title (spaces as _)" % root))
        win.add(Label(8, 36, 96, 10, "Description:"))
        self.desc = win.add(TextArea(112, 34, 300, 38,
                                     lib["description"].split("\n") if lib and
                                     lib["description"] else []))
        self.auto = win.add(CheckBox(112, 76, 300, 12, "Uploads show at once (no approval)",
                                     bool(lib["auto_approve"]) if lib else True))
        self.status = win.add(Label(8, 92, self.W - 16, 10, ""))
        add_buttons(win, [("OK", self._ok, GFlag.DEFAULT), ("Cancel", closer, 0)])
        self.win = win
        win.show(self.b.session)
        return win

    def _ok(self, button):
        b = self.b
        if not b._mod_ok():
            return self.win.close()
        title = clean_text(self.title.value).strip()
        problem = check_title(title)
        if problem:
            return self.status.set_text(problem)
        desc = "\n".join(tidy_lines(self.desc.lines))
        folder = folder_for(title)
        files, db = b.files, b.db
        other = next((x for x in db.libraries() if x["folder"] == folder
                      and x["id"] != self.lib_id), None)
        if other is not None:
            return self.status.set_text(("%s already uses %s/%s." % (
                other["title"], files.ROOT_NAME, folder))[:50])
        new_path = os.path.join(files.root, folder)
        if self.lib_id is None:
            lib_id = db.create_library(title, folder, desc, self.auto.checked)
            if lib_id is None:
                return self.status.set_text("There is already a library called %s." % title)
            os.makedirs(new_path, exist_ok=True)
            b.session.log("new library %s (%s/%s)" % (title, files.ROOT_NAME, folder))
            done = "Made %s, in %s/%s." % (title, files.ROOT_NAME, folder)
            b.lib_id = lib_id
        else:
            old = db.library(self.lib_id)
            if old is None:
                self.win.close()
                return b.say("That library is gone.")
            old_path = os.path.join(files.root, old["folder"])
            if folder != old["folder"] and os.path.exists(new_path) and os.path.exists(old_path):
                return self.status.set_text(("%s/%s is already on the server." % (
                    files.ROOT_NAME, folder))[:50])
            problem = db.update_library(self.lib_id, title, folder, desc, self.auto.checked)
            if problem:
                return self.status.set_text(problem[:50])
            try:
                if folder != old["folder"] and os.path.exists(old_path):
                    os.rename(old_path, new_path)
                os.makedirs(new_path, exist_ok=True)
            except OSError as e:
                db.update_library(self.lib_id, old["title"], old["folder"], old["description"],
                                  old["auto_approve"])
                return self.status.set_text(("Couldn't rename the folder: %s" % e.strerror)[:50])
            b.session.log("edited library %s -> %s (%s/%s)" % (old["title"], title,
                                                               files.ROOT_NAME, folder))
            done = "Saved %s." % title
        self.win.close()
        files.changed()
        b.show(done)
        return None


class FileDialog:
    """Add File / Edit File (WIN_FILE_EDIT): an entry for a file in the library's folder."""
    W, H = 440, 124

    def __init__(self, browser, lib, f):
        self.b, self.lib_id, self.f = browser, lib["id"], f
        self.folder = lib["folder"]

    def show(self):
        f = self.f
        win = Window.centred("Edit File" if f else "Add File", self.W, self.H,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=self.b.files.WIN_FILE_EDIT)
        win.add(Label(8, 6, 96, 10, "Filename:"))
        self.name = win.add(TextBox(112, 4, 6 + 8 * NAME_MAX, 12, f["name"] if f else ""))
        win.add(Label(264, 6, 40, 10, "Type:"))
        types = self.b.files.TYPES
        self.type = win.add(DropDown(312, 4, 64, types, types.index(f["type"]) if f else 0))
        win.add(Label(8, 20, 96, 10, "Description:"))
        self.desc = win.add(TextArea(112, 18, 320, 38, f["description"].split("\n")
                                     if f and f["description"] else []))
        win.add(Label(8, 62, 96, 10, "Server Path:"))
        self.path = win.add(TextBox(112, 60, 320, 12, f["path"] if f else ""))
        win.add(Label(112, 74, 320, 10, ("in %s/%s/ on the server" % (
            self.b.files.ROOT_NAME, self.folder))[:40]))
        self.status = win.add(Label(8, 88, self.W - 16, 10, ""))
        add_buttons(win, [("OK", self._ok, GFlag.DEFAULT), ("Cancel", closer, 0)])
        self.win = win
        win.show(self.b.session)
        return win

    def _ok(self, button):
        b = self.b
        if not b._mod_ok():
            return self.win.close()
        lib = b.db.library(self.lib_id)
        if lib is None:
            self.win.close()
            return b.say("That library is gone.")
        say = self.status.set_text
        path = tidy_path(clean_text(self.path.value))
        if path is None:
            return say("The server path is a file inside %s/%s/." % (
                b.files.ROOT_NAME, lib["folder"][:16]))
        real = b.files.file_path(lib, path)
        if real is None or not os.path.isfile(real):
            return say(("There's no file %s in %s/%s/." % (path, b.files.ROOT_NAME,
                                                         lib["folder"]))[:52])
        size = os.path.getsize(real)
        ftype = self.b.files.TYPES[self.type.selected or 0]
        name = clean_text(self.name.value).strip() or os.path.splitext(
            os.path.basename(path))[0].upper()[:NAME_MAX]
        problem = check_cbm_name(name) or check_image(ftype, size)
        if not problem and size > LOCAL_MAX:
            problem = "That's too big: the client takes files up to %d KB." % (LOCAL_MAX // 1024)
        if problem:
            return say(problem[:52])
        desc = "\n".join(tidy_lines(self.desc.lines))
        same = b.db.library_file_by_path(lib["id"], path)
        if same is not None and (self.f is None or same["id"] != self.f["id"]):
            return say(("%s already has an entry: %s." % (path, same["name"]))[:52])
        try:
            with open(real, "rb") as fh:
                data = fh.read()
        except OSError as e:
            return say(("Couldn't read it: %s" % e.strerror)[:52])
        if b.files.CHECKING:
            say(b.files.CHECKING)
        b.files.check_data(data, lambda problem: self._save(problem, path, name, ftype, desc,
                                                            size))
        return None

    def _save(self, problem, path, name, ftype, desc, size):
        """The file's data checked (perhaps a while later: look at everything again)."""
        b = self.b
        if not self.win.shown or not b.session.can(b.files.MODERATE):
            return None
        say = self.status.set_text
        if problem:
            return say(problem[:52])
        lib = b.db.library(self.lib_id)
        if lib is None:
            self.win.close()
            return b.say("That library is gone.")
        same = b.db.library_file_by_path(lib["id"], path)
        if same is not None and (self.f is None or same["id"] != self.f["id"]):
            return say(("%s already has an entry: %s." % (path, same["name"]))[:52])
        if self.f is None:
            b.file_id = b.db.add_library_file(lib["id"], name, ftype, desc, path, size,
                                              b.session.user_id)
            b.session.log("added file %s (%s) to %s" % (name, path, lib["title"]))
            done = "Added %s." % name
            b.files.server.screens.live.say("New in %s: %s" % (lib["title"], name),
                                            can=lambda v, l=lib: b.files.can_see(v, l))
        else:
            if b.db.library_file(self.f["id"]) is None:
                self.win.close()
                return b.say("That file entry is gone.")
            b.db.update_library_file(self.f["id"], name, ftype, desc, path, size)
            b.session.log("edited file %s (%s) in %s" % (name, path, lib["title"]))
            done = "Saved %s." % name
        self.win.close()
        b.files.changed()
        b.say(done)
        return None


# ---------------------------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------------------------

class DownloadDialog:
    """Where to put it (WIN_DOWNLOAD): a drive and a name, or an SD card folder and an 8.3
    name."""

    def __init__(self, browser, lib, f):
        self.b, self.lib_id, self.file_id = browser, lib["id"], f["id"]
        self.f = f
        self.image = f["type"] in IMAGE_TYPES
        self.sd_path = []                # SD folders from the root
        self.req = None
        self.rows = []                   # list row -> (kind, name)

    @property
    def session(self):
        return self.b.session

    def show(self):
        st = Storage.of(self.session)
        f, caps = self.f, st.caps()
        if st.job is not None:
            return self.session.alert("Download", "Wait for the transfer that's running.")
        if self.image and not caps & Caps.SD_WRITE:
            return self.session.alert("Download", "Disk images go onto the SD card, and your "
                                      "MegaNet client can't write to it yet.")
        if not self.image and not caps & Caps.DRIVES:
            return self.session.alert("Download", "Your MegaNet client can't write to its "
                                      "drives yet.")
        about = "%s (%s, {:,} bytes)".format(f["size"]) % (f["name"], f["type"])
        if not self.image:
            win = Window.centred("Download", 360, 84,
                                 flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                                 win_id=self.b.files.WIN_DOWNLOAD)
            win.add(Label(8, 4, 344, 10, ("Download " + about)[:43]))
            win.add(Label(8, 20, 112, 10, "Save to drive:"))
            self.drive = win.add(DropDown(128, 18, 48, [str(d) for d in LOCAL_DRIVES], 0))
            win.add(Label(8, 36, 112, 10, "Name on disk:"))
            self.name = win.add(TextBox(128, 34, 6 + 8 * NAME_MAX, 12, f["name"]))
            self.status = win.add(Label(8, 50, 344, 10, ""))
            add_buttons(win, [("Download", self._go, GFlag.DEFAULT), ("Cancel", closer, 0)])
        else:
            win = Window.centred("Download to the SD card", 440, 160,
                                 flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                                 win_id=self.b.files.WIN_DOWNLOAD, on_close=self._closed)
            win.add(Label(8, 2, 424, 10, ("Save " + about)[:53]))
            self.where = win.add(Label(8, 14, 424, 10, "Folder: /"))
            self.list = win.add(ListBox(8, 26, 424, 80, [], on_select=self._pick))
            win.add(Label(8, 112, 112, 10, "Name on card:"))
            self.name = win.add(TextBox(120, 110, 6 + 8 * 12, 12, sd_name(f["name"], f["type"])))
            self.status = win.add(Label(8, 126, 424, 10, "Reading the SD card..."))
            add_buttons(win, [("Download", self._go, GFlag.DEFAULT),
                              ("Cancel", self._cancel, 0)])
        self.win = win
        win.show(self.session)
        if self.image:
            self._list()
        return win

    # the SD card's folders
    def _list(self):
        st = Storage.of(self.session)
        if self.req is not None:
            st.pending.pop(self.req, None)
        self.where.set_text(("Folder: /" + "/".join(self.sd_path))[:53])
        self.req = st.list_dir(LOCAL_SD, "/".join(self.sd_path), self._listed)

    def _listed(self, status, text, entries):
        self.req = None
        if not self.win.shown:
            return None
        if status != LocalStatus.OK:
            self.rows = []
            self.list.set_rows([])
            return self.status.set_text(status_text(status, text))
        dirs = sorted((e for e in entries if e[0] == Local.DIR and e[2] not in (".", "..")),
                      key=lambda e: e[2])
        imgs = sorted((e for e in entries if e[0] in (Local.D64, Local.D81)), key=lambda e: e[2])
        self.rows = ([(Local.DIR, "..")] if self.sd_path else []) + \
            [(Local.DIR, e[2]) for e in dirs] + [(e[0], e[2]) for e in imgs]
        self.list.set_rows(["../  (up a folder)" if n == ".." else
                            "%s/" % n if k == Local.DIR else "    %s" % n for k, n in self.rows])
        return self.status.set_text("Click a folder to open it; the image goes in this one.")

    def _pick(self, listbox, index, double):
        if listbox.selected is None or listbox.selected >= len(self.rows):
            return None
        kind, name = self.rows[listbox.selected]
        if kind != Local.DIR:
            return self.status.set_text("%s is already there." % name)
        if name == "..":
            self.sd_path.pop()
        elif len(self.sd_path) < 8:
            self.sd_path.append(name)
        listbox.selected = None
        self.status.set_text("Reading the SD card...")
        return self._list()

    def _closed(self, window):
        if self.req is not None:
            Storage.of(self.session).pending.pop(self.req, None)
            self.req = None

    def _cancel(self, button):
        self._closed(None)
        button.window.close()

    def _go(self, button):
        b, session = self.b, self.session
        if not b._ok():
            return self.win.close()
        lib = b.db.library(self.lib_id)
        f = b.db.library_file(self.file_id)
        if f is None or not b.files.can_download(session, lib) or (
                not f["approved"] and not b.mod):
            self.win.close()
            return b.say("You can't download that now.")
        name = clean_text(self.name.value).strip()
        if self.image:
            name = name.upper()
            problem = check_sd_name(name, f["type"])
            dev, path = LOCAL_SD, "/".join(self.sd_path + [name])
        else:
            problem = check_cbm_name(name)
            dev = LOCAL_DRIVES[self.drive.selected or 0]
            path = name
        if problem:
            return self.status.set_text(problem[:53])
        if len(path) > LOCAL_PATH_MAX:
            return self.status.set_text("That folder is too deep: pick one nearer the top.")
        real = b.files.file_path(lib, f["path"])
        try:
            with open(real, "rb") as fh:
                data = fh.read(LOCAL_MAX + 1)
        except (OSError, TypeError):
            data = None
        if data is None:
            return self.status.set_text("That file is missing on the server.")
        if len(data) > LOCAL_MAX:
            return self.status.set_text("That file is too big to download.")
        self._closed(None)
        self.win.close()
        Download(b, f, dev, path, data).start()
        return None


class Transfer:
    """The transfer window (its library's WIN_TRANSFER: the Art Gallery's uploads, which have
    no library, use the File Library's) and the job behind it, one at a time a session."""
    W, H = 360, 70

    def __init__(self, browser, title, what):
        self.b = browser
        self.session = browser.session
        self.st = Storage.of(self.session)
        self.title, self.what = title, what
        self.over = False
        self.shown_pct = -1
        files = getattr(browser, "files", None)
        self.win_id = files.WIN_TRANSFER if files is not None else WIN_TRANSFER

    def open_window(self, status):
        win = Window.centred(self.title, self.W, self.H, flags=WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=self.win_id, on_close=self._closed, minimize=True)
        win.add(Label(8, 4, 344, 10, self.what[:43]))
        self.bar = win.add(Progress(8, 18, 344, 12))
        self.status = win.add(Label(8, 34, 344, 10, status))
        self.button = add_buttons(win, [("Cancel", self._button, 0)], centre=True)[0]
        self.win = win
        win.show(self.session)

    def progress(self, done, total):
        pct = 100 * done // total if total else 100
        if pct >= self.shown_pct + 2 or pct == 100:
            self.shown_pct = pct
            self.bar.set_percent(pct)
            self.status.set_text("{:,} of {:,} bytes".format(done, total))

    def end(self, text, ok):
        """It's over: say how it went; the button closes the window now."""
        self.over = True
        if self.st.job is self:
            self.st.job = None
        self.st.finish(self)
        if self.win.shown:
            if ok:
                self.bar.set_percent(100)
            self.status.set_text(text[:43])
            self.button.set_text("Close")
            self.button.enable(True)
        else:
            self.session.toast(("%s: %s" % (self.title, text))[:72])

    def _button(self, button):
        if not self.over:
            if not self.cancellable():   # (greyed out on the client: a click that crossed)
                return None
            self.st.cancel(self)
            self.end("Cancelled.", False)
            self.session.log("%s cancelled: %s" % (self.title.lower(), self.what))
        button.window.close()

    def _closed(self, window):
        if self.over:
            return
        if not self.cancellable():       # the client is writing it: let it finish (the
            return                       # result comes as a toast)
        self.st.cancel(self)             # the close box: it stops too
        self.over = True
        if self.st.job is self:
            self.st.job = None
        self.session.log("%s cancelled: %s" % (self.title.lower(), self.what))

    def cancellable(self):
        """False once the client may be writing the file (it can't stop then)."""
        return True

    def stop(self, text):
        """The server stops it (a permission went), if it still can."""
        if self.over or not self.cancellable():
            return
        self.st.cancel(self)
        self.end(text, False)
        self.session.warn("%s stopped: %s" % (self.title.lower(), self.what))


class Download(Transfer):
    def __init__(self, browser, f, dev, path, data):
        if dev == LOCAL_SD:
            what = "%s to %s" % (f["name"], path)
        elif path == f["name"]:
            what = "%s to drive %d" % (path, dev)
        else:
            what = "%s to drive %d as %s" % (f["name"], dev, path)
        super().__init__(browser, "Download", what)
        self.file_id, self.dev, self.path, self.data = f["id"], dev, path, data
        self.kind = KINDS[f["type"]]
        self.sent = self.acked = 0
        self.ready = self.end_sent = False

    def start(self):
        self.st.job = self
        req = self.st.start(self)
        self.open_window("Asking %s..." % device_name(self.dev))
        self.session.send(S.SAVE_BEGIN, Writer().u8(req).u8(self.dev).u8(self.kind)
                          .u32(len(self.data)).str(self.path))
        self.session.log("download %s to %s:%s" % (self.what, self.dev, self.path))

    def on_ack(self, n):
        if self.over:
            return
        if not self.ready:
            self.ready = True
        self.acked = max(self.acked, min(n, len(self.data)))
        while self.sent < len(self.data) and self.sent - self.acked < FILE_WINDOW:
            part = self.data[self.sent:self.sent + FILE_CHUNK]
            self.session.send(S.FILE_DATA, Writer().u32(self.sent).bytes(part))
            self.sent += len(part)
        if self.sent == len(self.data) and not self.end_sent:
            self.session.send(S.FILE_END, Writer().u32(zlib.crc32(self.data)))
            self.end_sent = True
            self.button.enable(False)    # it may start writing now: no stopping it
        self.progress(self.acked, len(self.data))
        if self.acked == len(self.data):
            self.status.set_text("Writing it to %s..." % device_name(self.dev))

    def cancellable(self):
        """Until FILE_END: the client writes nothing before it has the whole file, and a
        LOCAL_CANCEL sent before FILE_END reaches it before FILE_END does."""
        return not self.end_sent

    def on_done(self, status, text):
        if self.over:
            return
        if status == LocalStatus.OK:
            self.b.db.count_download(self.file_id)
            self.session.log("downloaded %s" % self.what)
            self.end("Done: saved as %s." % self.path.split("/")[-1], True)
            self.b.files.changed()
        else:
            self.session.warn("download failed (%d %s): %s" % (status, text, self.what))
            self.end(status_text(status, text), False)


# ---------------------------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------------------------

class UploadDialog:
    """Upload (WIN_UPLOAD): a source (drive 8-11, the SD card), a file from its directory, a
    name and a description."""
    W, H = 440, 171

    def __init__(self, browser, lib):
        self.b, self.lib_id = browser, lib["id"]
        self.sources = []                # (label, dev)
        self.sd_path = []
        self.rows = []                   # list row -> (kind, size, name, long)
        self.picked = None
        self.req = None

    @property
    def session(self):
        return self.b.session

    def show(self):
        st = Storage.of(self.session)
        caps = st.caps()
        if st.job is not None:
            return self.session.alert("Upload", "Wait for the transfer that's running.")
        if caps & Caps.DRIVES:
            self.sources += [("Drive %d" % d, d) for d in LOCAL_DRIVES]
        if caps & Caps.SD_READ and self.b.files.UPLOAD_SD:
            self.sources.append(("SD card", LOCAL_SD))
        if not self.sources:
            return self.session.alert("Upload", "Your MegaNet client can't read its disks yet.")
        win = Window.centred("Upload", self.W, self.H,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE, win_id=self.b.files.WIN_UPLOAD,
                             on_close=self._closed)
        win.add(Label(8, 4, 48, 10, "From:"))
        self.source = win.add(DropDown(56, 2, 96, [s[0] for s in self.sources], 0,
                                       on_select=self._source))
        self.where = win.add(Label(160, 4, 272, 10, ""))
        self.list = win.add(ListBox(8, 16, 424, 64, [], on_select=self._pick))
        win.add(Label(8, 86, 104, 10, "Filename:"))
        self.name = win.add(TextBox(112, 84, 6 + 8 * NAME_MAX, 12, ""))
        self.type = win.add(Label(264, 86, 168, 10, "Type: -"))
        win.add(Label(8, 100, 104, 10, "Description:"))
        self.desc = win.add(TextArea(112, 98, 320, 30, []))
        self.status = win.add(Label(8, 132, 424, 10, ""))
        add_buttons(win, [("Upload", self._go, GFlag.DEFAULT), ("Cancel", self._cancel, 0)])
        self.win = win
        win.show(self.session)
        self._list()
        return win

    @property
    def dev(self):
        return self.sources[self.source.selected or 0][1]

    def _source(self, dropdown, index, double):
        self.sd_path, self.picked = [], None
        self.name.set_text("")
        self.type.set_text("Type: -")
        return self._list()

    def _list(self):
        st = Storage.of(self.session)
        if self.req is not None:
            st.pending.pop(self.req, None)
        self.rows = []
        self.list.set_rows([])
        dev = self.dev
        self.where.set_text("/" + "/".join(self.sd_path) if dev == LOCAL_SD else "")
        self.status.set_text("Reading %s..." % device_name(dev))
        self.req = st.list_dir(dev, "/".join(self.sd_path) if dev == LOCAL_SD else "",
                               self._listed)

    def _listed(self, status, text, entries):
        self.req = None
        if not self.win.shown:
            return None
        if status != LocalStatus.OK:
            return self.status.set_text(status_text(status, text))
        if self.dev == LOCAL_SD:
            dirs = sorted((e for e in entries if e[0] == Local.DIR and e[2] not in (".", "..")),
                          key=lambda e: e[2])
            imgs = sorted((e for e in entries if self.b.files.sd_wanted(e[0], e[2])),
                          key=lambda e: e[2])
            self.rows = ([(Local.DIR, 0, "..", "")] if self.sd_path else []) + dirs + imgs
            rows = ["../  (up a folder)" if e[2] == ".." else
                    "%s/" % (e[3] or e[2]) if e[0] == Local.DIR else
                    "    %-12s %7s  %s" % (e[2], size_text(e[1]),
                                           e[3] if e[3] and e[3] != e[2] else "")
                    for e in self.rows]
            hint = self.b.files.SD_HINT
        else:
            head = next((e for e in entries if e[0] == Local.HEADER), None)
            free = next((e for e in entries if e[0] == Local.FREE), None)
            self.where.set_text(("Disk: %s%s" % (head[2] if head else "?",
                                                 ", %d blocks free" % free[1] if free else ""))
                                [:34])
            self.rows = [e for e in entries if e[0] in (Local.PRG, Local.SEQ, Local.USR)]
            rows = ["%-16s %s %4d blocks" % (e[2], TYPE_OF[e[0]], e[1]) for e in self.rows]
            hint = "Pick a file to send." if rows else "No PRG, SEQ or USR files on that disk."
        self.list.set_rows(rows)
        return self.status.set_text(hint)

    def _pick(self, listbox, index, double):
        if listbox.selected is None or listbox.selected >= len(self.rows):
            return None
        e = self.rows[listbox.selected]
        if e[0] == Local.DIR:
            if e[2] == "..":
                self.sd_path.pop()
            elif len(self.sd_path) < 8:
                self.sd_path.append(e[2])
            self.picked = None
            return self._list()
        self.picked = e
        base = e[2].rsplit(".", 1)[0] if self.dev == LOCAL_SD else e[2]
        self.name.set_text(base[:NAME_MAX])
        self.type.set_text("Type: %s" % self.b.files.upload_type(e[0]))
        return self.status.set_text("")

    def _closed(self, window):
        if self.req is not None:
            Storage.of(self.session).pending.pop(self.req, None)
            self.req = None

    def _cancel(self, button):
        self._closed(None)
        button.window.close()

    def _go(self, button):
        b, session = self.b, self.session
        if not b._ok():
            return self.win.close()
        lib = b.db.library(self.lib_id)
        if not b.files.can_upload(session, lib):
            self.win.close()
            return b.say("You can't upload to this library now.")
        if self.picked is None:
            return self.status.set_text("Pick a file to send first.")
        name = clean_text(self.name.value).strip()
        problem = check_cbm_name(name)
        if problem:
            return self.status.set_text(problem[:53])
        kind, size, src = self.picked[0], self.picked[1], self.picked[2]
        ftype = b.files.upload_type(kind)
        if self.dev == LOCAL_SD:
            problem = check_image(ftype, size)
            if problem:
                return self.status.set_text(problem[:53])
            path = "/".join(self.sd_path + [src])
            if len(path) > LOCAL_PATH_MAX:
                return self.status.set_text("That folder is too deep for MegaNet.")
        else:
            path = src
        desc = "\n".join(tidy_lines(self.desc.lines))
        self._closed(None)
        self.win.close()
        Upload(b, lib, self.dev, kind, path, name, desc).start()
        return None


class Upload(Transfer):
    def __init__(self, browser, lib, dev, kind, path, name, desc):
        super().__init__(browser, "Upload", "%s from %s" % (path, device_name(dev)))
        self.lib_id, self.dev, self.kind, self.path = lib["id"], dev, kind, path
        self.name, self.desc = name, desc
        self.size = None
        self.data = bytearray()

    def start(self):
        self.st.job = self
        req = self.st.start(self)
        self.open_window("Reading it from %s..." % device_name(self.dev))
        self.session.send(S.LOAD_FILE, Writer().u8(req).u8(self.dev).u8(self.kind)
                          .str(self.path))
        self.session.log("upload %s" % self.what)

    def fail(self, text):
        self.st.cancel(self)
        self.end(text, False)

    def on_up_begin(self, size):
        if self.over:
            return
        ftype = TYPE_OF.get(self.kind)
        problem = ("That's too big: up to %d KB." % (LOCAL_MAX // 1024) if size > LOCAL_MAX
                   else "That file is empty." if size == 0
                   else check_image(ftype, size))
        if problem:
            return self.fail(problem)
        self.size = size
        self.progress(0, size)

    def on_up_data(self, data):
        if self.over or self.size is None:
            return
        if len(data) > UP_CHUNK or len(self.data) + len(data) > self.size:
            return self.fail("The client sent more than it said it would.")
        self.data += data
        self.progress(len(self.data), self.size)

    def on_up_end(self, crc):
        if self.over:
            return
        if self.size is None or len(self.data) != self.size or zlib.crc32(self.data) != crc:
            self.session.warn("upload damaged: %s" % self.what)
            return self.end("It arrived damaged. Try again.", False)
        files, db = self.b.files, self.b.db
        lib = db.library(self.lib_id)
        if lib is None or not files.can_upload(self.session, lib):
            return self.end("You can't upload to that library now.", False)
        self.st.finish(self)             # (the client's part is over: a late reply is ignored)
        if files.CHECKING and self.win.shown:
            self.status.set_text(files.CHECKING[:43])
        files.check_data(bytes(self.data), self._checked)
        return None

    def _checked(self, problem):
        """The data checked (perhaps a while later: cancelled meanwhile, or the library gone,
        or the uploader's rights)."""
        if self.over:
            return None
        files, db = self.b.files, self.b.db
        if problem:                      # (not kept: it never reached the library's folder)
            self.session.log("upload refused (%s): %s" % (problem, self.what))
            self.end(problem, False)
            if len(problem) > 43:        # (more than the transfer window's line holds)
                self.session.alert("Upload", "%s wasn't added: %s" % (self.name, problem))
            return None
        lib = db.library(self.lib_id)
        if lib is None or not files.can_upload(self.session, lib):
            return self.end("You can't upload to that library now.", False)
        ftype = files.upload_type(self.kind)
        rel = files.unique_path(lib, self.name, ftype)
        try:
            os.makedirs(files.folder_path(lib), exist_ok=True)
            with open(os.path.join(files.folder_path(lib), rel), "xb") as fh:
                fh.write(self.data)
        except OSError as e:
            self.session.warn("upload not saved: %s" % e)
            return self.end("The server couldn't save it.", False)
        approved = bool(lib["auto_approve"]) or files.moderator(self.session)
        db.add_library_file(lib["id"], self.name, ftype, self.desc, rel, len(self.data),
                            self.session.user_id, approved)
        self.session.log("uploaded %s as %s/%s/%s%s" % (self.what, files.ROOT_NAME,
                                                       lib["folder"], rel,
                                                             "" if approved else " (held)"))
        if approved:
            self.end("Done: %s is in %s." % (self.name, lib["title"]), True)
            files.server.screens.live.say("New in %s: %s" % (lib["title"], self.name),
                                          can=lambda v, l=lib: files.can_see(v, l))
        else:
            self.end("Done: a moderator will look at it.", True)
            files.tell_moderators("%s uploaded %s to %s: it needs approving." % (
                self.session.user, self.name, lib["title"]))
        files.changed()

    def on_done(self, status, text):
        if not self.over:
            self.session.warn("upload failed (%d %s): %s" % (status, text, self.what))
            self.end(status_text(status, text), False)
