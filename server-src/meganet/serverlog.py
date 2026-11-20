"""The server log: every line the server logs, kept in the database for the admins to read
(Admin > Server Log..., permission admin.log) as well as printed on the console.

What goes in:
- session.log(text) / session.warn(text): a session's lines, with its connection, screen
  name and an area (by default the module that logged it: filelib.py -> "files").
- Anything else logged on the "meganet" logger (karma changes, start-up), and warnings and
  errors from other loggers (asyncio: a crashed background task), through LogHandler.
- A crash in a message handler: an error row with the traceback (session.run).

Each connection's rows share a connection number (the id of its "connected" row), so the
viewer can show one whole session, sign-on included. Rows older than the log_days setting
(System Settings, default LOG_DAYS) are deleted at start-up and then once an hour.

    49 = the Server Log window
"""

import logging
import sys
import time

from . import permissions as perms
from .protocol import GFlag, clean_text
from .ui import Window, Button, Label, TextBox, ListBox, DropDown, TextView

INFO, WARNING, ERROR = 0, 1, 2
LEVEL_NAMES = {INFO: "info", WARNING: "warning", ERROR: "error"}
LEVEL_MARKS = {INFO: " ", WARNING: "!", ERROR: "#"}       # in the viewer's rows
PY_LEVELS = {INFO: logging.INFO, WARNING: logging.WARNING, ERROR: logging.ERROR}

LOG_DAYS = 90                    # default for the log_days setting
LOG_DAYS_MAX = 3650
PRUNE_EVERY = 3600               # seconds between prunes while the server runs
TEXT_MAX = 8000                  # characters kept of one row (a traceback fits)

console = logging.getLogger("meganet")

# The areas, in the viewer's drop-down order, and the modules that log into each one
AREAS = ["server", "conn", "login", "account", "admin", "files", "chat", "boards", "mail",
         "news", "polls", "pages", "im", "karma", "games", "internet", "ui"]
MODULE_AREAS = {
    "server": "server", "db": "server", "serverlog": "server",
    "session": "conn", "updates": "conn", "presence": "conn",
    "signup": "login", "account": "account", "admin": "admin", "permissions": "admin",
    "filelib": "files", "chat": "chat", "boards": "boards", "mail": "mail",
    "compose": "mail", "news": "news", "polls": "polls", "pages": "pages", "im": "im",
    "karma": "karma", "screens": "ui", "desktop": "ui", "ui": "ui",
}


def area_of(module):
    """The area for a module name ("meganet.filelib", or a record's "filelib")."""
    if module.startswith("meganet.games") or module == "lobby":
        return "games"
    if module.startswith("meganet.internet"):
        return "internet"
    return MODULE_AREAS.get(module.rsplit(".", 1)[-1], "server")


def caller_area(depth=1):
    """The area of the code `depth` frames above the caller (1: whoever called the caller)."""
    return area_of(sys._getframe(depth + 1).f_globals.get("__name__", ""))


PLUMBING = ("meganet.session", "meganet.ui", "meganet.protocol", "meganet.db",
            "meganet.serverlog")


def error_area():
    """For an exception being handled: the area of the innermost feature module in its
    traceback (a crash in db.py called from filelib.py is "files")."""
    area, tb = "server", sys.exc_info()[2]
    while tb is not None:
        name = tb.tb_frame.f_globals.get("__name__", "")
        if name.startswith("meganet") and name not in PLUMBING:
            area = area_of(name)
        tb = tb.tb_next
    return area


class ServerLog:
    """The log of one Server: writes rows, prunes old ones, answers the viewer's queries."""

    def __init__(self, server):
        self.server = server
        self.last_prune = 0
        self.handler = LogHandler(self)
        console.setLevel(logging.INFO)              # (the handler needs the INFO records)
        console.addHandler(self.handler)
        logging.getLogger("asyncio").addHandler(self.handler)
        self.prune()

    @property
    def db(self):
        return self.server.db

    def close(self):
        console.removeHandler(self.handler)
        logging.getLogger("asyncio").removeHandler(self.handler)

    def days(self):
        try:
            days = int(self.db.setting("log_days", LOG_DAYS))
        except ValueError:
            days = LOG_DAYS
        return max(1, min(LOG_DAYS_MAX, days))

    def set_days(self, days):
        self.db.set_setting("log_days", max(1, min(LOG_DAYS_MAX, int(days))))
        self.prune()

    def prune(self, now=None):
        now = time.time() if now is None else now
        self.last_prune = now
        try:
            return self.db.prune_log(int(now - self.days() * 86400))
        except Exception:                           # (the log never breaks the server)
            return 0

    def write(self, text, level=INFO, area=None, session=None, user=None):
        """Print a line on the console and keep it. `session` gives the connection and the
        screen name; `user` names the user a session-less line is about (karma)."""
        text = str(text)
        if session is not None:
            who = "%d %s" % (session.id, session.user) if session.user else str(session.id)
            console.log(PY_LEVELS[level], "[%s] %s", who, text, extra={"serverlog": self})
        else:
            console.log(PY_LEVELS[level], "%s", text, extra={"serverlog": self})
        self.store(text, level, area or "server", session, user)

    def store(self, text, level, area, session=None, user=None):
        now = time.time()
        try:
            if session is not None:
                row = self.db.add_log(int(now), level, area, getattr(session, "conn", None),
                                      session.id, session.user_id, session.user,
                                      text[:TEXT_MAX])
                if getattr(session, "conn", 1) is None:     # its first row names the connection
                    session.conn = row
                    self.db.set_log_conn(row, row)
            else:
                self.db.add_log(int(now), level, area, None, None, None, user, text[:TEXT_MAX])
        except Exception:
            return                                  # (a closed database: a test's leftover)
        if now - self.last_prune > PRUNE_EVERY:
            self.prune(now)


class LogHandler(logging.Handler):
    """Keeps the records that didn't come through ServerLog.write: INFO and up from the
    "meganet" logger (karma, start-up), WARNING and up from asyncio."""

    def __init__(self, log):
        super().__init__(logging.INFO)
        self.log = log

    def emit(self, record):
        if getattr(record, "serverlog", None) is not None:      # already stored
            return
        if not record.name.startswith("meganet") and record.levelno < logging.WARNING:
            return
        level = (ERROR if record.levelno >= logging.ERROR else
                 WARNING if record.levelno >= logging.WARNING else INFO)
        try:
            text = record.getMessage()
            if record.exc_info:
                text += "\n" + logging.Formatter().formatException(record.exc_info)
        except Exception:
            return
        self.log.store(text, level, area_of(record.module), user=getattr(record, "user", None))


# ---- the viewer ----

WIN_LOG = 49
LOG_W, LOG_H = 632, 168
PAGE = 200                       # rows a page of the list holds
SHOW = [("Everything", INFO), ("Warnings, errors", WARNING), ("Errors only", ERROR)]
ALL_AREAS = "All areas"


def log_row(e):
    """One list row (the list shows 63 characters): when, ! / # for a warning / error, the
    area, the screen name (or #session before sign-on), the start of the text."""
    who = e["user"] or ("#%d" % e["session"] if e["session"] is not None else "")
    first = e["text"].split("\n", 1)[0]
    return "%s%s%-6s %-10s %s" % (time.strftime("%m-%d %H:%M", time.localtime(e["at"])),
                                   LEVEL_MARKS.get(e["level"], "?"), e["area"][:6],
                                   who[:10], clean_text(first))


def entry_lines(e):
    """The details pane: everything about the picked row."""
    head = "%s  %s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["at"])),
                           LEVEL_NAMES.get(e["level"], "?"), e["area"])
    if e["user"]:
        head += "  %s" % e["user"]
    if e["conn"] is not None:
        head += "  (session %d, connection %d)" % (e["session"], e["conn"])
    return [head] + [clean_text(line.expandtabs(4)) for line in e["text"].split("\n")]


class LogViewer:
    """One admin's Server Log window: filters (area, level, screen name, text), the newest
    matching rows a page at a time, the picked row in full, and Session: every row of the
    picked row's connection."""

    def __init__(self, logs, session):
        self.logs = logs
        self.session = session
        self.win = None
        self.area = None             # None: all
        self.min_level = INFO
        self.user = ""
        self.find = ""
        self.conn = None             # Session: only this connection's rows
        self.top = None              # the newest row id when the search ran (pages stay put)
        self.offset = 0
        self.total = 0
        self.entries = []

    @property
    def db(self):
        return self.logs.server.db

    def show(self):
        self.logs.viewers[self.session] = self
        win = Window.centred("Server Log", LOG_W, LOG_H, win_id=WIN_LOG, on_close=self._closed)
        win.add(Label(8, 4, 40, 10, "Area:"))
        self.area_dd = win.add(DropDown(48, 2, 96, [ALL_AREAS] + AREAS,
                                        selected=0 if self.area is None
                                        else AREAS.index(self.area) + 1))
        win.add(Label(152, 4, 40, 10, "Show:"))
        self.level_dd = win.add(DropDown(192, 2, 144, [s[0] for s in SHOW],
                                         selected=[s[1] for s in SHOW].index(self.min_level)))
        win.add(Label(344, 4, 40, 10, "User:"))
        self.user_box = win.add(TextBox(384, 2, 88, 12, self.user))
        win.add(Label(480, 4, 40, 10, "Find:"))
        self.find_box = win.add(TextBox(520, 2, 104, 12, self.find))
        self.list = win.add(ListBox(8, 20, 528, 96, [], on_select=self._pick))
        x = 544
        self.search_b = win.add(Button(x, 20, 80, 16, "Search", GFlag.DEFAULT,
                                       on_click=self._search))
        self.newer_b = win.add(Button(x, 40, 80, 16, "Newer", on_click=self._newer))
        self.older_b = win.add(Button(x, 60, 80, 16, "Older", on_click=self._older))
        self.conn_b = win.add(Button(x, 80, 80, 16, "Session", on_click=self._session))
        self.status = win.add(Label(x, 102, 80, 10, ""))
        self.view = win.add(TextView(8, 120, 616, 44, []))
        self.win = win
        self.query(fresh=self.top is None)
        win.show(self.session)
        return win

    def allowed(self):
        if not self.session.can(perms.ADMIN_LOG):
            self.session.warn("refused the server log: no %s" % perms.ADMIN_LOG)
            self.session.alert("Server Log", "You don't have permission to do that.")
            self.close()
            return False
        return True

    def query(self, fresh=False):
        """Fill the list with the page at self.offset (fresh: the newest rows as of now).
        Pages count back from the newest row when the search ran, so Older / Newer don't
        slide while new rows arrive. (Before the window is shown this only sets it up.)"""
        if fresh:
            self.top, self.offset = self.db.last_log_id(), 0
        self.entries, self.total = self.db.log_entries(
            area=self.area, min_level=self.min_level, user=self.user, text=self.find,
            conn=self.conn, top=self.top, limit=PAGE, offset=self.offset)
        self.list.set_rows([log_row(e) for e in self.entries])
        self.list.selected = None
        self.view.set_lines([])
        if self.total:
            self.status.set_text("%d-%d/%d" % (self.offset + 1, self.offset + len(self.entries),
                                               self.total))
        else:
            self.status.set_text("None found")
        self.conn_b.set_text("All" if self.conn is not None else "Session")
        self.buttons()

    def buttons(self):
        """Newer / Older while there are more; Session needs a picked row from a connection
        (as All, back to the filters, it's always on)."""
        self.newer_b.enable(self.offset > 0)
        self.older_b.enable(self.offset + len(self.entries) < self.total)
        e = self.picked()
        self.conn_b.enable(self.conn is not None or (e is not None and e["conn"] is not None))

    def picked(self):
        i = self.list.selected
        return self.entries[i] if i is not None and i < len(self.entries) else None

    def read_filters(self):
        i = self.area_dd.selected
        self.area = AREAS[i - 1] if i else None
        self.min_level = SHOW[self.level_dd.selected or 0][1]
        self.user = self.user_box.value.strip()
        self.find = self.find_box.value.strip()

    def _search(self, button):
        if not self.allowed():
            return
        self.read_filters()
        self.conn = None
        self.query(fresh=True)

    def _newer(self, button):
        if not self.allowed():
            return
        self.offset = max(0, self.offset - PAGE)
        self.query()

    def _older(self, button):
        if not self.allowed():
            return
        if self.offset + PAGE < self.total:
            self.offset += PAGE
        self.query()

    def _session(self, button):
        """Session: every row of the picked row's connection, whatever the filters say. All
        (shown while a session is): back to the filters."""
        if not self.allowed():
            return
        if self.conn is not None:
            self.conn = None
            return self.query(fresh=True)
        e = self.picked()
        if e is None or e["conn"] is None:
            return
        self.conn = e["conn"]
        self.query(fresh=True)

    def _pick(self, listbox, index, double):
        if not self.allowed():
            return
        e = self.picked()
        self.view.set_lines(entry_lines(e) if e else [])
        self.buttons()
        if double and e is not None and e["conn"] is not None and self.conn is None:
            self._session(None)

    def close(self):
        self.logs.viewers.pop(self.session, None)
        if self.win is not None:
            self.win.close()

    def _closed(self, window):
        if self.logs.viewers.get(self.session) is self:
            del self.logs.viewers[self.session]


class LogWindows:
    """The Server Log windows open, one per admin (screens.py hooks)."""

    def __init__(self, server):
        self.server = server
        self.viewers = {}            # session -> LogViewer

    def open(self, session):
        if not session.can(perms.ADMIN_LOG):
            session.warn("refused the server log: no %s" % perms.ADMIN_LOG)
            return session.alert("Server Log", "You don't have permission to do that.")
        viewer = self.viewers.get(session)
        if viewer is not None and viewer.win is not None and viewer.win.shown:
            return viewer.win.show(session)
        return LogViewer(self, session).show()

    def permissions_changed(self, session):
        if not session.can(perms.ADMIN_LOG) and session in self.viewers:
            self.viewers[session].close()

    def disconnected(self, session):
        self.viewers.pop(session, None)
