"""One connected client.

The session reads frames from the socket, and hands each event to the window and gadget it
names (see ui.py). Sign-on happens here too:

    client                         server
    HELLO (version, build, ...) ->
                                <- HELLO (version, session id)
                                <- UPDATE + files       (only if the client's build is too old)
    LOGIN (flags, name, pw)     ->
                                <- LOGIN_RESULT (ok, message)
                                <- MENU (the menu bar) and the welcome window (on success)

A new-user LOGIN with an empty name and password starts the sign-up wizard instead
(signup.py): no LOGIN_RESULT until it's accepted or cancelled, and only its window's events
(WIZARD_EVENTS) are handled before sign-on.
"""

import asyncio
import inspect
import logging
import time
import traceback

from . import db as dbmod
from . import karma
from . import serverlog
from .protocol import (TOAST_NO_SLOT, clean_text, S, C, Writer, Deframer, ProtocolError, VERSION, LOGIN_NEW_USER,
                       SELECT_DOUBLE, SERVER_WIN_FIRST, SERVER_WIN_LAST, NOTIFY_SLOTS,
                       NOTIFY_HINT_MAX, SLOT_STATUS, Icon, WFlag, Caps, palette_rgb, SPRITES,
                       SPRITE_W, SPRITE_H, SPRITE_COLOURS,
                       RESOURCE_SLOTS, RESOURCE_SIZE,
                       RESOURCE_CHUNK)

log = logging.getLogger("meganet")

FIRST_DYNAMIC_WIN = 0x40     # ids below this are the fixed screens in screens.py
WIN_LOADING_RES = 55         # "Loading Chess": a resource coming (send_resource)

# What the sign-up wizard's window may send before sign-on (each starts with u8 win)
WIZARD_EVENTS = frozenset((C.CLICK, C.VALUE, C.SELECT, C.TEXT, C.WIN_CLOSED))
# The client's answers to S.LOCAL_DIR / SAVE_BEGIN / LOAD_FILE (filelib.py)
LOCAL_REPLIES = frozenset((C.FILE_ACK, C.LOCAL_ENTRY, C.LOCAL_DONE, C.UP_BEGIN, C.UP_DATA,
                           C.UP_END))


class Session:
    def __init__(self, server, reader, writer, session_id):
        self.server = server
        self.reader = reader
        self.writer = writer
        self.id = session_id
        self.user = None             # screen name once signed on
        self.user_id = None          # users.id once signed on
        self.role_id = None          # users.role_id (see load_permissions)
        self.role = None             # the role's name
        self.perms = frozenset()     # the role's permission keys, cached: see can()
        self.build = None            # client build from HELLO
        self.caps = 0                # and what it can do (protocol.Caps)
        self.storage = None          # filelib.Storage: requests to the client's disks
        self.updating = False        # True after a forced update was sent
        self.windows = {}            # win id -> ui.Window
        self.menu = None             # the ui.Menu last sent (MENU_PICKs are checked against it)
        self.game = None             # games.base.Player while in a game
        self.notify = {}             # menu-bar icons shown: slot -> (icon, hint)
        self.desk = []               # desktop icons sent (desktop.py), slot order
        self.resources = {}          # S.RESOURCE slot -> the key of what this client holds
        self.picture = None          # the S.PICTURE showing (gallery.Show): gets C.PIC_KEY
        self.canvas = None           # Paint running (gallery.paint.Paint): gets C.CANVAS
        self.previous_login = None   # the sign-on before this one (My Account's Last Login)
        self.chat_lines = 0          # lines said in chat (karma: CHAT_LINES make a point)
        self.status = "available"    # Status menu: available / away / offline (presence.py)
        self.auto_away = False       # away because of no activity (back with the next one)
        self.last_active = time.time()   # the last message that wasn't a PING
        self.suspicious = 0          # events for things never offered (karma.suspicious)
        self.pw_locked_until = 0     # Reset Password refused until then (wrong passwords)
        self.signup = None           # signup.Wizard while the New User wizard runs
        self.conn = None             # the server log's connection number (its first row)
        self.closed = False

    # ---- the server log (serverlog.py): console and database ----

    def log(self, msg, level=serverlog.INFO, area=None):
        """Log a line about this session. The area is the calling module's (filelib.py:
        "files") unless given."""
        self.server.serverlog.write(msg, level, area or serverlog.caller_area(), self)

    def warn(self, msg, area=None):
        """A refusal or a failure: shown with "Warnings, errors" in the Server Log."""
        self.log(msg, serverlog.WARNING, area or serverlog.caller_area())

    def error(self, msg, area=None):
        self.log(msg, serverlog.ERROR, area or serverlog.caller_area())

    # ---- permissions ----

    def can(self, key):
        """True if the signed-on user's role holds permission `key` (permissions.py).
        Cached; the server refreshes it when an admin changes this user's role or the role."""
        return self.user is not None and key in self.perms

    def load_permissions(self):
        """Re-read this user's role and its permissions from the database."""
        row = self.server.db.user(user_id=self.user_id)
        self.role_id = row["role_id"] if row else None
        self.role = row["role"] if row else None
        self.perms = frozenset(self.server.db.user_permissions(self.user_id))

    # ---- sending ----

    def send(self, msg_type, w=None):
        if self.closed:
            return
        self.writer.write((w or Writer()).frame(msg_type))

    def alert(self, title, text, icon=0):
        self.send(S.ALERT, Writer().u8(icon).str(title).str(text))

    def open_window(self, window):
        """Send a window to the client. An open window with the same id is replaced in place:
        no WIN_CLOSE first (the client empties a window when its id is opened again, and keeps
        the old one on screen until the new one's WIN_DONE: a wizard's steps don't flash)."""
        if window.win_id is None:
            window.win_id = self.free_window_id()
        if not SERVER_WIN_FIRST <= window.win_id <= SERVER_WIN_LAST:
            raise ValueError("window id %r is not a server id (1-$EF)" % window.win_id)
        old = self.windows.get(window.win_id)
        if old is not None and old is not window:
            del self.windows[old.win_id]           # (replaced: its on_close isn't called)
            old.shown = False
        window.session = self
        window.shown = True
        self.windows[window.win_id] = window
        window.send()

    def close_window(self, window):
        if self.windows.get(window.win_id) is window:
            del self.windows[window.win_id]
            self.send(S.WIN_CLOSE, Writer().u8(window.win_id))
        window.shown = False

    def free_window_id(self):
        for win_id in range(FIRST_DYNAMIC_WIN, SERVER_WIN_LAST + 1):
            if win_id not in self.windows:
                return win_id
        raise RuntimeError("no free window ids")

    def set_menu(self, menu):
        """Send the menu bar (ui.Menu); it replaces the one the client had. None clears it."""
        self.menu = menu
        if menu is None:
            return self.send(S.MENU, Writer().u8(0))
        menu.session = self
        return self.send(S.MENU, menu.encode())

    def toast(self, text, seconds=6, slot=None):
        """A short message at the bottom right of the client's screen (S.TOAST) that doesn't
        take the keyboard or mouse; a click on it acts as a NOTIFY_CLICK of `slot`."""
        self.send(S.TOAST, Writer().u8(max(1, min(255, seconds)))
                  .u8(TOAST_NO_SLOT if slot is None else slot).str(clean_text(text)[:72]))

    def sound(self, sound):
        """Play one of the client's sounds (S.SOUND)."""
        self.send(S.SOUND, Writer().u8(int(sound)))

    def send_resource(self, slot, key, data, title=None):
        """Put `data` (at most RESOURCE_SIZE bytes: a grid's tiles, say) in the client's
        resource slot `slot` (S.RESOURCE, RESOURCE_CHUNK at a time; S.RESOURCE_PACKED to
        Caps.PICTURE clients, which unpack PackBits), unless this connection
        already holds `key` there. The client keeps it in attic RAM until the slot is
        overwritten; nothing goes to its disks. With `title` ("Chess"), a "Loading Chess"
        window with a progress bar shows while it comes: its updates go between the chunks,
        so the client moves the bar as the data arrives, and the window closes after the
        last one."""
        if not 0 <= slot < RESOURCE_SLOTS or len(data) > RESOURCE_SIZE:
            raise ValueError("bad resource slot %r or size %d" % (slot, len(data)))
        if self.resources.get(slot) == key:
            return False
        bar = win = None
        if title:
            from .ui import Window, Label, Progress, MARGIN
            win = Window.centred("Loading %s" % title, 260, 40, win_id=WIN_LOADING_RES,
                                 flags=WFlag.MODAL)
            win.add(Label(MARGIN, 4, 260 - 2 * MARGIN, 10, "Loading the game's pictures..."))
            bar = win.add(Progress(MARGIN, 20, 260 - 2 * MARGIN))
            win.show(self)
        packed = bool(self.caps & Caps.PICTURE)  # (clients that unpack: about a third)
        for done, msg_type, w in resource_messages(slot, data, packed):
            self.send(msg_type, w)
            if bar is not None:
                bar.set_percent(100 * done // len(data))
        if win is not None:
            win.close()
        self.resources[slot] = key
        self.log("resource %r: %d bytes to slot %d" % (key, len(data), slot))
        return True

    # ---- the server's sprites (Caps.SPRITES): pictures from a resource slot over the GUI ----

    def sprite_show(self, n, window, slot, offset, w, h, pos, colours, stride=None, step=1):
        """S.SPRITE: sprite n (0 .. SPRITES-1) becomes the picture at byte `offset` of resource
        slot `slot`: w pixels across (at most 16), `step` bytes apart (2: every second, for art
        drawn 2 screen pixels to 1), h rows (at most 64), `stride` bytes apart (default
        w * step). `colours` = the palette indexes it shows (at most 15: the rest is
        see-through). It shows at `pos` (x, y) in `window`'s client area and stays there.
        False (nothing sent) for clients without Caps.SPRITES or a window not shown."""
        if not self.caps & Caps.SPRITES or not window.shown:
            return False
        if not (0 <= n < SPRITES and 1 <= w <= SPRITE_W and 1 <= h <= SPRITE_H
                and 1 <= step and len(colours) <= SPRITE_COLOURS):
            raise ValueError("bad sprite %r: %dx%d, step %d, %d colours"
                             % (n, w, h, step, len(colours)))
        stride = w * step if stride is None else stride
        msg = (Writer().u8(n).u8(window.win_id).u8(slot).u16(offset).u8(w).u8(h).u16(stride)
               .u8(step).u16(pos[0]).u8(pos[1]).u8(len(colours)))
        for c in colours:
            r, g, b = palette_rgb(c)
            msg.u8(c).u8(r).u8(g).u8(b)
        self.send(S.SPRITE, msg)
        return True

    def sprite_move(self, n, start, end, frames, hide=False):
        """S.SPRITE_MOVE: sprite n (shown at `start`) glides to `end` in `frames` frames (50 a
        second), then goes if `hide`. Positions in the same window's client area."""
        if not self.caps & Caps.SPRITES or frames < 1:
            return False

        def step(a, b):
            return max(-32768, min(32767, round((b - a) * 256 / frames))) & 0xFFFF
        self.send(S.SPRITE_MOVE, Writer().u8(n).u16(step(start[0], end[0]))
                  .u16(step(start[1], end[1])).u8(frames).u8(1 if hide else 0))
        return True

    def sprite_off(self, n=0xFF):
        """S.SPRITE_OFF: sprite n gone (0xFF: all)."""
        if self.caps & Caps.SPRITES:
            self.send(S.SPRITE_OFF, Writer().u8(n))

    def fly(self, window, slot, offset, w, h, start, end, frames, colours, step=1, n=0):
        """A picture flies from `start` to `end` in `frames` frames, then goes: sprite_show
        then sprite_move(hide). False for clients without Caps.SPRITES."""
        if not self.sprite_show(n, window, slot, offset, w, h, start, colours, step=step):
            return False
        return self.sprite_move(n, start, end, frames, hide=True)

    def set_notify(self, slot, icon, hint=""):
        """Show icon `icon` in menu-bar slot `slot` (S.NOTIFY), or remove it with Icon.NONE.
        Sent only when it changes. NOTIFY_CLICKs are accepted only for slots shown here."""
        if not 0 <= slot < NOTIFY_SLOTS:
            raise ValueError("bad notify slot %r" % slot)
        icon, hint = Icon(icon), str(hint)[:NOTIFY_HINT_MAX]
        if icon == Icon.NONE:
            if self.notify.pop(slot, None) is None:
                return
        elif self.notify.get(slot) == (icon, hint):
            return
        else:
            self.notify[slot] = (icon, hint)
        self.send(S.NOTIFY, Writer().u8(slot).u8(icon).str(hint))

    def disconnect(self):
        self.closed = True
        self.writer.close()

    # ---- receiving ----

    async def run(self):
        """Read and handle frames until the client goes away."""
        deframer = Deframer()
        try:
            while True:
                chunk = await self.reader.read(4096)
                if not chunk:
                    break
                for msg_type, r in deframer.push(chunk):
                    try:
                        await self.handle(msg_type, r)
                    except ProtocolError:
                        raise
                    except Exception:            # a bug in a screen or game: log it, go on
                        self.error("error handling message $%02X:\n%s"
                                   % (msg_type, traceback.format_exc().rstrip()),
                                   area=serverlog.error_area())
                await self.writer.drain()
        except ProtocolError as e:
            self.warn("bad stream: %s" % e, area="conn")
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.closed = True
            self.writer.close()

    async def handle(self, msg_type, r):
        if msg_type == C.HELLO:
            if self.build is not None:       # (once a connection: a second one could change
                return self.warn("second HELLO ignored")    # caps or force an update)
            return self.on_hello(r)
        if msg_type == C.LOGIN:
            return await self.on_login(r)
        if msg_type == C.PING:
            return self.send(S.PONG)
        if self.user is not None and not (   # (the client's own PINGs aren't the user, and
                msg_type == C.NOTIFY_CLICK and r.peek_u8() == SLOT_STATUS):  # an auto-Away
            self.server.screens.presence.activity(self)   # dot clicked goes to Available)
        if self.user is None and not (
                msg_type in WIZARD_EVENTS and self.signup is not None
                and self.signup.win is not None and r.peek_u8() == self.signup.win.win_id):
            self.log("message $%02X before sign-on, ignored" % msg_type)
            return
        if msg_type == C.VALUE:
            win, gid = r.u8(), r.u8()
            g = self.gadget(win, gid)
            if g:
                g.handle_value(r.str())
        elif msg_type == C.CLICK:
            g = self.gadget(r.u8(), r.u8())
            if g and not g.enabled:          # greyed out (the client ignores clicks on it;
                self.log("click on disabled %s ignored" % g.text)   # this one crossed)
            elif g:
                await call(g.handle_click())
        elif msg_type == C.SELECT:
            win, gid, v = r.u8(), r.u8(), r.u16()
            g = self.gadget(win, gid)
            if g:
                await call(g.handle_select(v & ~SELECT_DOUBLE & 0xFFFF, bool(v & SELECT_DOUBLE)))
        elif msg_type == C.TEXT:
            win, gid, n = r.u8(), r.u8(), r.u8()
            lines = [r.str() for _ in range(n)]
            g = self.gadget(win, gid)
            if g:
                g.handle_text(lines)
        elif msg_type == C.LIST_NEED:
            win, gid, first, n = r.u8(), r.u8(), r.u16(), r.u8()
            g = self.gadget(win, gid)
            if g:
                g.handle_need(first, n)
        elif msg_type == C.KEY:
            win, gid, key = r.u8(), r.u8(), r.u8()
            g = self.gadget(win, gid)
            if g:
                await call(g.handle_key(key))
        elif msg_type == C.WIN_CLOSED:
            window = self.windows.pop(r.u8(), None)
            if window:
                window.shown = False
                await call(window.handle_closed())
        elif msg_type == C.MENU_PICK:
            item_id = r.u8()
            if self.menu is None:
                self.log("menu pick %d ignored: no menu" % item_id)
            elif item_id not in self.menu and item_id not in self.menu.hidden:
                karma.suspicious(self, "menu pick %d: never sent" % item_id)
            else:
                await call(self.menu.handle_pick(item_id))
        elif msg_type == C.NOTIFY_CLICK:
            slot = r.u8()
            if slot not in self.notify:
                karma.suspicious(self, "notify click %d: no icon there" % slot)
            else:
                await call(self.server.screens.notify_click(self, slot))
        elif msg_type == C.DESK_OPEN:
            slot = r.u8()
            if slot >= len(self.desk) or self.desk[slot] is None:
                karma.suspicious(self, "desk open %d: no icon there" % slot)
            else:
                await call(self.server.screens.desktop.open(self, slot))
        elif msg_type == C.PIC_KEY:
            key = r.u8()
            if self.picture is None:
                self.log("picture key %d ignored: no picture showing" % key)
            else:
                await call(self.picture.on_key(key))
        elif msg_type == C.CANVAS:
            event, x, y = r.u8(), r.u16(), r.u8()
            if self.canvas is None:
                self.log("canvas event %d ignored: not painting" % event)
            else:
                await call(self.canvas.on_mouse(event, x, y))
        elif msg_type in LOCAL_REPLIES:      # the client's storage (filelib.Storage)
            from .filelib import Storage
            Storage.of(self).handle(msg_type, r)
        else:
            self.log("unknown message $%02X" % msg_type)

    def gadget(self, win, gid):
        window = self.windows.get(win)
        g = window.gadgets.get(gid) if window else None
        if g is None:
            karma.suspicious(self, "event for unknown gadget %d:%d" % (win, gid))
        return g

    # ---- sign-on ----

    def on_hello(self, r):
        version, self.build, self.caps, name = r.u8(), r.u16(), r.u8(), r.str()
        self.log("hello v%d build %d caps $%02X %s" % (version, self.build, self.caps, name))
        self.send(S.HELLO, Writer().u8(VERSION).u16(self.id))
        updates = self.server.updates
        if updates.needs(self.build):
            self.updating = True
            updates.push(self)
        # Otherwise nothing: the client shows its own sign-on window and sends LOGIN.

    def login_result(self, ok, message):
        self.send(S.LOGIN_RESULT, Writer().u8(1 if ok else 0).str(message))

    async def on_login(self, r):
        flags, name, password = r.u8(), r.str().strip(), r.str()
        if flags & LOGIN_NEW_USER and not name and not password:
            refused = self.login_refused()           # New User: the sign-up wizard
            if refused:
                return self.login_result(False, refused)
            return self.server.screens.signup.start(self)
        if self.signup is not None:                  # a LOGIN replaces a wizard
            self.signup.abandon()
        ok, message = await self.check_login(flags, name, password)
        if ok:
            self.sign_on(name, message, new=bool(flags & LOGIN_NEW_USER))
        else:
            self.warn("sign-on as %r refused: %s" % (name[:20], message), area="login")
            self.login_result(False, message)

    def sign_on(self, name, message, new=False, welcome=True, after=None):
        """LOGIN_RESULT ok, then the session is signed on as `name` (an existing account):
        the menu bar, the welcome window and the rest (screens.signed_on)."""
        self.login_result(True, message)
        self.user = self.server.db.canonical_name(name)
        self.user_id = self.server.db.user(name)["id"]
        self.previous_login = self.server.db.record_login(self.user_id)
        self.load_permissions()
        self.log("signed on as %s (%s, build %s)%s" % (self.user, self.role, self.build,
                                                      " (new user)" if new else ""),
                 area="login")
        self.server.screens.signed_on(self, welcome=welcome, after=after)

    def login_refused(self):
        """Why no LOGIN can be taken now, or None."""
        if self.build is None:
            return "Say HELLO first."
        if self.updating:
            return "Please let the update finish."
        if self.user is not None:
            return "You are already signed on."
        return None

    async def check_login(self, flags, name, password):
        refused = self.login_refused()
        if refused:
            return False, refused
        db = self.server.db
        if flags & LOGIN_NEW_USER:
            problem = dbmod.check_new_name(name) or dbmod.check_new_password(password)
            if problem:
                return False, problem
            if self.server.screens.signup.reserved(name, exclude=self):
                return False, "The name %s is taken." % name
            pw_hash = await asyncio.to_thread(dbmod.hash_password, password)
            if not db.create_user(name, pw_hash):
                return False, "The name %s is taken." % name
            return True, "Welcome to MegaNet, %s!" % name
        stored = db.password_hash(name)
        good = stored is not None and await asyncio.to_thread(
            dbmod.verify_password, password, stored)
        if not good:
            return False, "Wrong screen name or password."
        if self.server.find_user(name):
            return False, "%s is already signed on." % db.canonical_name(name)
        return True, "Welcome back, %s." % db.canonical_name(name)


def resource_messages(slot, data, packed=False):
    """The messages that put `data` in resource slot `slot`: [(bytes done after it, type,
    Writer)]. `packed`: S.RESOURCE_PACKED (Caps.PICTURE clients), else S.RESOURCE."""
    out = []
    if packed:
        from .gallery.picture import packed_chunks
        chunks = packed_chunks(data)
        for i, (offset, part) in enumerate(chunks):
            done = chunks[i + 1][0] if i + 1 < len(chunks) else len(data)
            out.append((done, S.RESOURCE_PACKED, Writer().u8(slot).u16(offset).bytes(part)))
        return out
    for offset in range(0, len(data), RESOURCE_CHUNK):
        out.append((min(len(data), offset + RESOURCE_CHUNK), S.RESOURCE,
                    Writer().u8(slot).u16(offset).bytes(data[offset:offset + RESOURCE_CHUNK])))
    return out


async def call(result):
    """Await a callback's result if it was an async def."""
    if inspect.isawaitable(result):
        await result
