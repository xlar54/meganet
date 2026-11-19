"""A fake MegaNet client for the tests: it speaks the real protocol over TCP and keeps a model
of the windows the server has opened, the way the MEGA65 client will."""

import asyncio
import zlib

from meganet.protocol import (Local, LocalStatus, LOCAL_SD, LOCAL_MAX, FILE_CHUNK, UP_CHUNK,
                              BROADCAST_MAX, DESK_SLOTS, DESK_ICON_W, DESK_ICON_H, DESK_LABEL_MAX,
                              DESK_CLEAR, GFlag, S, C, Kind, Writer, Deframer, LOGIN_NEW_USER, MENU_FIRST,
                              MENU_LAST, MENU_SEPARATOR, NOTIFY_SLOTS, NOTIFY_HINT_MAX, Icon,
                              window_fits, DROPDOWN_ROWS, DROPDOWN_NONE, EDIT_LINES,
                              EDIT_COLS_MAX)

TIMEOUT = 5.0
ROW_MAX = 63             # list box / drop-down rows
INNER = 6 + 11           # a drop-down's or EDIT's margins plus its arrow button / scroll bar


def columns(kind, w):
    """Characters a DROPDOWN shows, or an EDIT line holds, at width w."""
    n = (w - INNER) // 8
    return min(n, EDIT_COLS_MAX) if kind == Kind.EDIT else n


class FakeWindow:
    def __init__(self, win_id, title):
        self.id = win_id
        self.title = title
        self.done = False
        self.gadgets = {}      # gid -> dict(kind, text, value, rows, lines)

    def find(self, text):
        """The gadget id of the gadget whose text is `text`."""
        for gid, g in self.gadgets.items():
            if g["text"] == text:
                return gid
        raise KeyError("no gadget %r in %r" % (text, self.title))

    def text(self, gid):
        return self.gadgets[gid]["text"]


class FakeStorage:
    """The client's disks, as S.LOCAL_DIR / SAVE_BEGIN / LOAD_FILE see them:
    drives = {unit: {"name": disk name, "files": {name: (Local kind, bytes)}}} and sd = nested
    dicts of folders, with bytes for files ("GAMES": {"ELITE.D81": b"..."})."""

    def __init__(self):
        self.drives = {}
        self.sd = None           # None: no SD card
        self.save = None         # the download arriving: dict(req, dev, kind, size, path, data)
        self.hold_acks = False   # True: don't FILE_ACK data (the window test)
        self.damage = False      # True: uploads arrive with a wrong CRC
        self.saves = []          # (dev, path) saved, in order
        self.cancelled = []      # reqs cancelled
        self.max_ahead = 0       # the most bytes of FILE_DATA ever unacknowledged

    def sd_folder(self, parts):
        node = self.sd
        for p in parts:
            node = node.get(p) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                return None
        return node

    def done(self, c, req, status, text=""):
        c.send(C.LOCAL_DONE, Writer().u8(req).u8(status).str(text))

    def handle(self, c, t, r):
        if t == S.LOCAL_DIR:
            req, dev, path = r.u8(), r.u8(), r.str()
            if dev == LOCAL_SD:
                node = self.sd_folder([p for p in path.split("/") if p]) if self.sd is not None \
                    else None
                if node is None:
                    return self.done(c, req, LocalStatus.NO_DEVICE if self.sd is None
                                     else LocalStatus.NOT_FOUND)
                for name, v in node.items():
                    kind = (Local.DIR if isinstance(v, dict) else Local.D81 if
                            name.endswith(".D81") else Local.D64 if name.endswith(".D64")
                            else Local.FILE)
                    c.send(C.LOCAL_ENTRY, Writer().u8(req).u8(kind)
                           .u32(0 if isinstance(v, dict) else len(v)).str(name).str(name))
                return self.done(c, req, LocalStatus.OK)
            d = self.drives.get(dev)
            if d is None:
                return self.done(c, req, LocalStatus.NO_DEVICE, "74,DRIVE NOT READY,00,00")
            c.send(C.LOCAL_ENTRY, Writer().u8(req).u8(Local.HEADER).u32(0).str(d["name"]))
            for name, (kind, data) in d["files"].items():
                c.send(C.LOCAL_ENTRY, Writer().u8(req).u8(kind).u32((len(data) + 253) // 254)
                       .str(name))
            c.send(C.LOCAL_ENTRY, Writer().u8(req).u8(Local.FREE).u32(3000).str("BLOCKS FREE."))
            return self.done(c, req, LocalStatus.OK)
        if t == S.SAVE_BEGIN:
            req, dev, kind, size, path = r.u8(), r.u8(), r.u8(), r.u32(), r.str()
            assert size <= LOCAL_MAX, "SAVE_BEGIN of %d bytes" % size
            if dev == LOCAL_SD:
                parts = path.split("/")
                node = self.sd_folder(parts[:-1]) if self.sd is not None else None
                if node is None:
                    return self.done(c, req, LocalStatus.NO_DEVICE if self.sd is None
                                     else LocalStatus.NOT_FOUND)
                if parts[-1] in node:
                    return self.done(c, req, LocalStatus.EXISTS)
            else:
                d = self.drives.get(dev)
                if d is None:
                    return self.done(c, req, LocalStatus.NO_DEVICE, "74,DRIVE NOT READY,00,00")
                if path in d["files"]:
                    return self.done(c, req, LocalStatus.EXISTS, "63,FILE EXISTS,00,00")
            self.save = dict(req=req, dev=dev, kind=kind, size=size, path=path,
                             data=bytearray())
            return c.send(C.FILE_ACK, Writer().u32(0))
        if t == S.FILE_DATA:
            s = self.save
            offset = r.u32()
            assert offset == len(s["data"]), "FILE_DATA out of order"
            part = r.rest()
            assert len(part) <= FILE_CHUNK, "FILE_DATA of %d bytes" % len(part)
            s["data"] += part
            s["acked"] = s.get("acked", 0)
            self.max_ahead = max(self.max_ahead, len(s["data"]) - s["acked"])
            if not self.hold_acks:
                s["acked"] = len(s["data"])
                c.send(C.FILE_ACK, Writer().u32(len(s["data"])))
            return None
        if t == S.FILE_END:
            s, self.save = self.save, None
            crc = r.u32()
            if crc != zlib.crc32(s["data"]) or len(s["data"]) != s["size"]:
                return self.done(c, s["req"], LocalStatus.BAD_CRC)
            if s["dev"] == LOCAL_SD:
                parts = s["path"].split("/")
                self.sd_folder(parts[:-1])[parts[-1]] = bytes(s["data"])
            else:
                self.drives[s["dev"]]["files"][s["path"]] = (s["kind"], bytes(s["data"]))
            self.saves.append((s["dev"], s["path"]))
            return self.done(c, s["req"], LocalStatus.OK)
        if t == S.LOAD_FILE:
            req, dev, kind, path = r.u8(), r.u8(), r.u8(), r.str()
            if dev == LOCAL_SD:
                parts = path.split("/")
                node = self.sd_folder(parts[:-1]) if self.sd is not None else None
                data = node.get(parts[-1]) if node is not None else None
            else:
                d = self.drives.get(dev)
                data = d["files"].get(path, (None, None))[1] if d else None
            if data is None or isinstance(data, dict):
                return self.done(c, req, LocalStatus.NOT_FOUND, "62,FILE NOT FOUND,00,00")
            c.send(C.UP_BEGIN, Writer().u8(req).u32(len(data)))
            for i in range(0, len(data), UP_CHUNK):
                c.send(C.UP_DATA, Writer().u8(req).bytes(data[i:i + UP_CHUNK]))
            return c.send(C.UP_END, Writer().u8(req).u32(zlib.crc32(data) ^ (1 if self.damage
                                                                             else 0)))
        if t == S.LOCAL_CANCEL:
            req = r.u8()
            self.cancelled.append(req)
            if self.save is not None and self.save["req"] == req:
                self.save = None
        return None

    def ack_all(self, c):
        """Acknowledge what has arrived (after hold_acks)."""
        s = self.save
        if s is not None:
            s["acked"] = len(s["data"])
            c.send(C.FILE_ACK, Writer().u32(len(s["data"])))


class FakeClient:
    def __init__(self, name="fake"):
        self.name = name
        self.windows = {}        # open windows: id -> FakeWindow
        self.alerts = []         # (title, text)
        self.toasts = []         # (seconds, slot or None, text)
        self.broadcasts = []     # (seconds, text)
        self.sounds = []         # S.SOUND numbers, in order
        self.login_results = []  # (ok, message)
        self.hello = None        # (version, session id)
        self.update = None       # (build, nfiles, message)
        self.files = []          # [name, size, bytearray, crc]
        self.messages = []       # every (type) received, in order
        self.menu = []           # the menu bar: [(id, parent, label)] from the last S.MENU
        self.menus_received = 0  # how many S.MENU messages have come
        self.notify = {}         # menu-bar icons: slot -> (icon, hint)  (icon 0 removes one)
        self.desk = {}           # desktop icons: slot -> (line 1, line 2, pixels)
        self.events = []         # ("open" / "close" / "icon", window title or slot), in order
        self.storage = FakeStorage()   # drives 8-11 and an SD card (the File Library)
        self._changed = asyncio.Event()

    async def connect(self, port):
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", port)
        self._task = asyncio.create_task(self._read())

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except ConnectionError:
            pass
        self._task.cancel()

    # ---- sending ----

    def send(self, msg_type, w=None):
        self.writer.write((w or Writer()).frame(msg_type))

    def send_hello(self, build=100, caps=0):
        self.send(C.HELLO, Writer().u8(1).u16(build).u8(caps).str("fakeclient"))

    def send_login(self, name, password, new=False):
        self.send(C.LOGIN, Writer().u8(LOGIN_NEW_USER if new else 0).str(name).str(password))

    def desk_labels(self):
        return [(" ".join(x for x in self.desk[s][:2] if x)) for s in sorted(self.desk)]

    def desk_open(self, label):
        slot = next(s for s in self.desk if " ".join(x for x in self.desk[s][:2] if x) == label)
        self.send(C.DESK_OPEN, Writer().u8(slot))

    def click(self, win, gid):
        # Like the real client: every EDIT gadget's lines go first (C.TEXT), as VALUE does for
        # text boxes in the real client (here the tests send VALUE themselves).
        w = self.windows.get(win)
        for egid, g in sorted(w.gadgets.items()) if w else ():
            if g["kind"] == Kind.EDIT:
                self.send_text(win, egid, g["lines"])
        self.send(C.CLICK, Writer().u8(win).u8(gid))

    def send_text(self, win, gid, lines):
        lines = list(lines)
        while lines and not lines[-1]:          # trailing empty lines are dropped
            lines.pop()
        w = Writer().u8(win).u8(gid).u8(len(lines))
        for line in lines:
            w.str(line)
        self.send(C.TEXT, w)

    def text(self, win, gid, lines):
        """Type `lines` into EDIT gadget gid (kept, and sent again before each CLICK)."""
        g = self.windows[win].gadgets[gid]
        assert g["kind"] == Kind.EDIT, "text() on a gadget that isn't an EDIT"
        g["lines"] = list(lines)[:EDIT_LINES]
        self.send_text(win, gid, g["lines"])

    def pick_dropdown(self, win, gid, index):
        """Pick row `index` of DROPDOWN gid (the client sends SELECT at once)."""
        g = self.windows[win].gadgets[gid]
        assert g["kind"] == Kind.DROPDOWN, "pick_dropdown() on a gadget that isn't a DROPDOWN"
        assert 0 <= index < len(g["rows"]), "no row %d" % index
        g["value"] = index
        self.select(win, gid, index)

    def click_text(self, win, text):
        """Click the button labelled `text`. (A test may click right after a SELECT that
        enables it, before the SET_FLAGS has arrived: the server handles both in order.)"""
        self.click(win, self.windows[win].find(text))

    def enabled(self, win, text):
        w = self.windows.get(win)
        if w is None or not w.done:
            return False
        g = next((g for g in w.gadgets.values() if g["text"] == text), None)
        if g is not None and g["flags"] & GFlag.NEEDTEXT:      # as the client: the box decides
            box = w.gadgets.get(g.get("value"))
            return bool(box and box.get("typed", box["text"]))
        return g is not None and not g["flags"] & GFlag.DISABLED

    def value(self, win, gid, text):
        g = self.windows.get(win) and self.windows[win].gadgets.get(gid)
        if g:
            g["typed"] = text
        self.send(C.VALUE, Writer().u8(win).u8(gid).str(text))

    def select(self, win, gid, index, double=False):
        self.send(C.SELECT, Writer().u8(win).u8(gid).u16(index | (0x8000 if double else 0)))

    # ---- the menu bar ----

    def menu_titles(self):
        return [label for _id, parent, label in self.menu if parent == 0]

    def menu_items(self, title):
        """The labels under `title`, in order (separators included as "-")."""
        ids = [i for i, parent, label in self.menu if parent == 0 and label == title]
        if not ids:
            return []
        return [label for _id, parent, label in self.menu if parent == ids[0]]

    def menu_id(self, label):
        """The id of the item (not a title or separator) labelled `label`."""
        for item_id, parent, text in self.menu:
            if parent != 0 and text == label and text != MENU_SEPARATOR:
                return item_id
        raise KeyError("no menu item %r in %r" % (label, self.menu))

    def pick_id(self, item_id):
        self.send(C.MENU_PICK, Writer().u8(item_id))

    def pick(self, label):
        """Pick the menu item labelled `label`, as the user would."""
        self.pick_id(self.menu_id(label))

    def notify_click(self, slot):
        """Click the menu-bar icon in `slot` (the client leaves it there)."""
        self.send(C.NOTIFY_CLICK, Writer().u8(slot))

    def icon(self, slot):
        return self.notify.get(slot, (Icon.NONE, ""))[0]

    def hint(self, slot):
        return self.notify.get(slot, (Icon.NONE, ""))[1]

    def close_box(self, win):
        self.windows.pop(win, None)
        self.send(C.WIN_CLOSED, Writer().u8(win))

    # ---- waiting ----

    async def wait_for(self, predicate, what="condition"):
        """Wait until predicate() is true (checked after every received message)."""
        async def loop():
            while not predicate():
                self._changed.clear()
                await self._changed.wait()
        try:
            await asyncio.wait_for(loop(), TIMEOUT)
        except asyncio.TimeoutError:
            raise AssertionError("%s: timed out waiting for %s" % (self.name, what)) from None

    async def wait_window(self, title_start):
        """Wait for a window whose title starts with `title_start` to be drawn; return it."""
        def find():
            for w in self.windows.values():
                if w.done and w.title.startswith(title_start):
                    return w
            return None
        await self.wait_for(lambda: find() is not None, "window %r" % title_start)
        return find()

    async def enter_room(self, name="Lobby", via=None):
        """Into chat room `name` as a user would: Areas > Chat Rooms (or `via()`: the desktop
        icon, say) opens the room list; pick the room's row, Go. Returns the room window."""
        CHAT_ROOMS = 26                          # (chat.WIN_ROOMS)
        self.windows.pop(CHAT_ROOMS, None)
        (via or (lambda: self.pick("Chat Rooms")))()
        rl = await self.wait_window("Chat Rooms")
        lb = next(g for g in sorted(rl.gadgets) if rl.gadgets[g]["kind"] == Kind.LISTBOX)
        await self.wait_for(lambda: any(r.split("  ")[0].strip() == name
                                        for r in rl.gadgets[lb].get("rows", [])), "row " + name)
        rows = rl.gadgets[lb]["rows"]
        index = next(i for i, r in enumerate(rows) if r.split("  ")[0].strip() == name)
        self.select(CHAT_ROOMS, lb, index)
        self.click_text(CHAT_ROOMS, "Go")
        return await self.wait_window(name)

    def all_lines(self, win, gid):
        return self.windows[win].gadgets[gid]["lines"] if win in self.windows else []

    # ---- receiving ----

    async def _read(self):
        d = Deframer()
        while True:
            chunk = await self.reader.read(4096)
            if not chunk:
                break
            for t, r in d.push(chunk):
                try:
                    self._handle(t, r)
                except KeyError:
                    # An update for a window or gadget this side has already dropped (a test
                    # popped it to wait for the next one): the real client ignores those too.
                    if t not in (S.SET_TEXT, S.SET_VALUE, S.LIST_ROWS, S.APPEND, S.SET_FLAGS,
                                 S.FOCUS, S.WIN_DONE):
                        raise
                self.messages.append(t)
            self._changed.set()

    def _handle(self, t, r):
        if t == S.HELLO:
            self.hello = (r.u8(), r.u16())
        elif t == S.LOGIN_RESULT:
            self.login_results.append((bool(r.u8()), r.str()))
        elif t == S.WIN_OPEN:
            win, x, y, w, h, _flags = r.u8(), r.u16(), r.u8(), r.u16(), r.u8(), r.u8()
            assert 1 <= win <= 0xEF, "server used a client window id"
            self.windows[win] = FakeWindow(win, r.str())
            self.events.append(("open", self.windows[win].title))
            self.windows[win].size = (w, h)
            self.windows[win].pos = (x, y)
            self.windows[win].flags = _flags
            # w/h are the client area: with the client's frame it must fit the screen, below
            # the menu bar
            assert window_fits(x, y, w, h), \
                "window %r (%d,%d %dx%d) doesn't fit the screen below the menu bar" % (
                    self.windows[win].title, x, y, w, h)
        elif t == S.MENU:
            n = r.u8()
            menu = []
            titles = set()
            for _ in range(n):
                item_id, parent, label = r.u8(), r.u8(), r.str()
                assert MENU_FIRST <= item_id <= MENU_LAST, "server used a client menu id"
                assert item_id not in {m[0] for m in menu}, "duplicate menu id %d" % item_id
                assert parent == 0 or parent in titles, "menu %d: parent %d is not a title" % (
                    item_id, parent)
                if parent == 0:
                    titles.add(item_id)
                menu.append((item_id, parent, label))
            assert not r.rest(), "bytes left over in MENU"
            self.menu = menu
            self.menus_received += 1
        elif t == S.GADGET:
            win, gid, kind = r.u8(), r.u8(), r.u8()
            x, y, w, h, _flags = r.u16(), r.u8(), r.u16(), r.u8(), r.u8()
            text = r.str()
            cw, ch = self.windows[win].size
            assert x + w <= cw and y + h <= ch, \
                "gadget %r (%d,%d %dx%d) sticks out of window %r (%dx%d)" % (
                    text, x, y, w, h, self.windows[win].title, cw, ch)
            if kind == Kind.DROPDOWN:
                assert h == 12, "drop-down %d:%d is %d high, not 12" % (win, gid, h)
                assert columns(kind, w) >= 1, "drop-down %d:%d too narrow" % (win, gid)
            elif kind == Kind.EDIT:
                assert columns(kind, w) >= 1 and (h - 6) // 8 >= 1,                     "EDIT %d:%d (%dx%d) has no room for a line" % (win, gid, w, h)
            self.windows[win].gadgets[gid] = dict(
                kind=kind, text=text, value=DROPDOWN_NONE if kind == Kind.DROPDOWN else 0,
                rows=[], lines=[], box=(x, y, w, h), flags=_flags)
        elif t == S.DESK_ICON:
            slot, one, two = r.u8(), r.str(), r.str()
            assert 0 <= slot < DESK_SLOTS, "desktop slot %d" % slot
            if not one:
                assert not two and not r.rest(), "a removed desktop icon carries nothing"
                self.desk.pop(slot, None)
            else:
                assert len(one) <= DESK_LABEL_MAX and len(two) <= DESK_LABEL_MAX, "label"
                px = r.rest()
                assert len(px) == DESK_ICON_W * DESK_ICON_H, "icon is %d bytes" % len(px)
                assert all(p < 16 or p == DESK_CLEAR for p in px), "icon colours 0-15"
                self.desk[slot] = (one, two, px)
                self.events.append(("icon", slot))
        elif t == S.SOUND:
            self.sounds.append(r.u8())
        elif t == S.BROADCAST:
            secs, text = r.u8(), r.str()
            assert len(text) <= BROADCAST_MAX, "broadcast too long for the row"
            self.broadcasts.append((secs, text))
        elif t == S.TOAST:
            secs, slot = r.u8(), r.u8()
            self.toasts.append((secs, None if slot == 0xFF else slot, r.str()))
        elif t == S.SET_FLAGS:
            win, gid, flags = r.u8(), r.u8(), r.u8()
            self.windows[win].gadgets[gid]["flags"] = flags
        elif t == S.WIN_DONE:
            self.windows[r.u8()].done = True
        elif t == S.WIN_CLOSE:
            gone = self.windows.pop(r.u8(), None)
            self.events.append(("close", gone.title if gone else None))
        elif t == S.SET_TEXT:
            win, gid = r.u8(), r.u8()
            g = self.windows[win].gadgets[gid]
            g["text"] = r.str()
            if g["kind"] == Kind.TEXTVIEW and g["text"] == "":   # empties a text view
                g["lines"] = []
            if g["kind"] == Kind.EDIT:
                assert g["text"] == "", "SET_TEXT on an EDIT must be \"\" (empty it)"
                g["lines"] = []
        elif t == S.SET_VALUE:
            win, gid = r.u8(), r.u8()
            g = self.windows[win].gadgets[gid]
            g["value"] = r.u16()
            if g["kind"] == Kind.DROPDOWN:
                assert g["value"] == DROPDOWN_NONE or g["value"] < len(g["rows"]),                     "drop-down %d:%d selection %d out of range" % (win, gid, g["value"])
        elif t == S.LIST_ROWS:
            win, gid, total, first, n = r.u8(), r.u8(), r.u16(), r.u16(), r.u8()
            g = self.windows[win].gadgets[gid]
            rows = g["rows"][:total] + [None] * (total - len(g["rows"]))
            for i in range(n):
                rows[first + i] = r.str()
            g["rows"] = rows
            if g["kind"] == Kind.DROPDOWN:
                assert total <= DROPDOWN_ROWS, "drop-down with %d rows" % total
                assert None not in rows, "drop-down rows must all be sent at once"
                assert all(len(row) <= ROW_MAX for row in rows), "drop-down row too long"
        elif t == S.APPEND:
            win, gid = r.u8(), r.u8()
            g = self.windows[win].gadgets[gid]
            line = r.str()
            if g["kind"] == Kind.EDIT:
                assert len(line) <= columns(Kind.EDIT, g["box"][2]),                     "EDIT %d:%d line longer than its width: %r" % (win, gid, line)
                assert len(g["lines"]) < EDIT_LINES, "EDIT %d:%d over %d lines" % (
                    win, gid, EDIT_LINES)
            g["lines"].append(line)
        elif t == S.ALERT:
            r.u8()
            self.alerts.append((r.str(), r.str()))
        elif t == S.NOTIFY:
            slot, icon, hint = r.u8(), r.u8(), r.str()
            assert slot < NOTIFY_SLOTS, "notify slot %d" % slot
            assert icon in set(Icon), "unknown notify icon %d" % icon
            assert len(hint) <= NOTIFY_HINT_MAX, "notify hint too long: %r" % hint
            assert not r.rest(), "bytes left over in NOTIFY"
            if icon == Icon.NONE:
                self.notify.pop(slot, None)
            else:
                self.notify[slot] = (Icon(icon), hint)
        elif t == S.UPDATE:
            self.update = (r.u16(), r.u8(), r.str())
        elif t in (S.LOCAL_DIR, S.SAVE_BEGIN, S.LOAD_FILE, S.LOCAL_CANCEL):
            self.storage.handle(self, t, r)
        elif t in (S.FILE_DATA, S.FILE_END) and self.storage.save is not None:
            self.storage.handle(self, t, r)
        elif t == S.FILE_BEGIN:
            size = r.u32()
            self.files.append([r.str(), size, bytearray(), None])
        elif t == S.FILE_DATA:
            offset = r.u32()
            assert offset == len(self.files[-1][2])
            self.files[-1][2] += r.rest()
        elif t == S.FILE_END:
            self.files[-1][3] = r.u32()
