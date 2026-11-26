"""Windows and gadgets: the server-side half of the client's GUI.

The server builds Window objects out of Gadget objects; the client draws them and runs them
locally, then reports what the user did. Each gadget class matches one gadget kind in the
client's toolkit (client-src/gui/).

    win = Window("Hello", 100, 40, 200, 80, win_id=5)
    name = win.add(TextBox(10, 10, 120, 12))
    win.add(Button(10, 40, 60, 16, "OK", on_click=lambda b: print(name.value)))
    win.show(session)

Callbacks get the gadget as their argument; gadget.window and gadget.session lead back to the
rest. A callback may be a plain function or an `async def`.

Coordinates of a window are on the 640x200 screen, below the menu bar; gadget coordinates are
relative to the window's client area. Gadget ids are 1-255 within the window; add() numbers
them for you.

The menu bar at the top of the screen is a Menu of MenuItems (at the end of this file); a
session has at most one, and showing another replaces it.
"""

from .protocol import (S, Kind, WFlag, GFlag, Writer, SELECT_DOUBLE, MENU_FIRST, MENU_LAST,
                       MENU_SEPARATOR, MEGANET_MENU, SCREEN_W, SCREEN_H, MENU_BAR_H, FRAME_W, FRAME_H,
                       DROPDOWN_ROWS, DROPDOWN_NONE, EDIT_LINES, EDIT_COLS_MAX,
                       GRID_PARAMS, GRID_CELLS_MAX)

CHAR_W = 8                  # the client's font is 8x8
SCROLLBAR_W = 11            # list boxes and text views draw a scroll bar inside their right edge


def centre(w, h):
    """(x, y) that centres a window with client area w x h in the screen below the menu bar
    (the client adds FRAME_W / FRAME_H for its frame and title bar)."""
    x = (SCREEN_W - (w + FRAME_W)) // 2
    y = MENU_BAR_H + (SCREEN_H - MENU_BAR_H - (h + FRAME_H)) // 2
    return max(0, x), max(MENU_BAR_H, y)


# ---- how windows and buttons look (docs/DESIGN.md "Windows and dialogs") ----
# Every window has a close box. Work windows (lists, rooms, editors) have no Close button: the
# close box closes them. Dialogs end in a row of command buttons: the command first, then
# Cancel; centred under the text in a message box ("Delete X?", Yes / No), at the bottom right
# in a dialog with fields. Buttons are BUTTON_H high and at least BUTTON_W wide, BUTTON_GAP
# apart; a label ends in "..." when the button opens a dialog that asks for more.
BUTTON_W, BUTTON_H, BUTTON_GAP = 72, 16, 8
MARGIN = 8                        # from the window's edges


def button_width(text):
    return max(BUTTON_W, 8 * len(text) + 16)


def add_buttons(win, specs, y=None, centre=False):
    """A dialog's command buttons in one row: specs = [(text, on_click, flags), ...] in order
    (the command first, Cancel last). At the bottom of `win` (or at y), right-aligned, or
    centred. Returns the Buttons."""
    widths = [button_width(t) for t, _, _ in specs]
    total = sum(widths) + BUTTON_GAP * (len(specs) - 1)
    x = (win.w - total) // 2 if centre else win.w - MARGIN - total
    y = win.h - BUTTON_H - 4 if y is None else y
    out = []
    for (text, fn, flags), w in zip(specs, widths):
        out.append(win.add(Button(x, y, w, BUTTON_H, text, flags, on_click=fn)))
        x += w + BUTTON_GAP
    return out


def closer(button):
    """on_click for a Cancel / OK that only closes its window."""
    button.window.close()


def confirm(session, title, lines, action, win_id, command="Delete"):
    """A modal "are you sure?" box: one or two lines (38 characters each), `command`, then
    Cancel as the default (RETURN doesn't delete). `action()` runs after the box closes;
    it should check again that it's still allowed and the thing is still there."""
    def go(button):
        button.window.close()
        return action()
    lines = [str(line)[:38] for line in lines][:2]
    win = Window.centred(title, 320, 26 + 12 * len(lines),
                         flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE, win_id=win_id)
    for i, line in enumerate(lines):
        win.add(Label(MARGIN, 4 + 12 * i, 320 - 2 * MARGIN, 10, line))
    add_buttons(win, [(command, go, 0), ("Cancel", closer, GFlag.DEFAULT)], centre=True)
    win.show(session)
    return win


# ---- area windows: every Areas entry window, and the views inside an area, look alike ----
#
#   +------------------------------------------------------------------+
#   | heading: a summary ("3 forums, 2 new since your last sign-on.")  |
#   | +--------------------------------------+  [ Main command    ]    |
#   | | the list (a column heading over it   |  [ other commands  ]    |
#   | |  when it has columns)                |  ------------------     |
#   | |                                      |     Admin Tools         |
#   | +--------------------------------------+  [ New ] [ Edit  ]      |
#   | +--------------------------------------+  [ Del ] [ ...   ]      |
#   | | the picked item: description, text   |                         |
#   | +--------------------------------------+                         |
#   | status: what to do next, or what just happened                    |
#   +------------------------------------------------------------------+
#
# 560 x 160, centred. The main command is the default button (RETURN), at the top of the
# command column; commands for everyone come under it; then, only for those allowed,
# "Admin Tools" under a line. Commands that need something picked are greyed until it is.
AREA_W, AREA_H = 560, 160
AREA_LIST_W = 400                 # the left side: the list and what's under it
AREA_COL_X, AREA_COL_W = 416, 136 # the command column
AREA_HALF_W = 66                  # two commands side by side in it
AREA_TOP = 14                     # the list's top (AREA_TOP + 12 under a column heading)
AREA_BOTTOM = 144                 # the left side's bottom (the status line is under it)


class AreaWindow:
    """Builds an area window in the layout above (an area module keeps the gadgets):

        a = AreaWindow(TITLE, WIN_X, on_close=...)
        head = a.heading("2 libraries.")
        lst = a.list(rows, on_select, about=True)       # about: a TextView under the list
        a.command("Open", on_click, default=True)
        if moderator:
            a.section("Admin Tools")
            a.pair(("New...", new), ("Edit...", edit))
        status = a.status("Pick a library and Open it.")
        a.win.show(session)
    """

    def __init__(self, title, win_id, on_close=None, h=AREA_H):
        self.win = Window.centred(title, AREA_W, h, flags=WFlag.CLOSE | WFlag.MOVABLE,
                                  win_id=win_id, on_close=on_close)
        self.h = h
        self.col_y = AREA_TOP
        self.about_view = None

    def heading(self, text):
        return self.win.add(Label(MARGIN, 2, AREA_W - 2 * MARGIN, 10, text))

    def list(self, rows, on_select, columns=None, about=False, about_h=42, about_lines=(),
             columns_w=AREA_LIST_W):
        """The list on the left: under a column heading if `columns` is given (`columns_w`
        wide: less leaves room on its row, for list_option()), and with a TextView (`about_h`
        high) under it for the picked item if `about`."""
        top = AREA_TOP
        if columns is not None:
            self.win.add(Label(MARGIN, AREA_TOP, columns_w, 10, columns))
            top += 12
        bottom = AREA_BOTTOM - (about_h + 4 if about else 0)
        lst = self.win.add(ListBox(MARGIN, top, AREA_LIST_W, bottom - top, rows,
                                   on_select=on_select))
        if about:
            self.about_view = self.win.add(TextView(MARGIN, bottom + 4, AREA_LIST_W, about_h,
                                                    about_lines))
        return lst

    def list_option(self, rows, selected, on_select, w=80):
        """A drop-down on the column heading's row, its right edge on the list's (a sort
        order, say). Give list() columns_w <= AREA_LIST_W - w - 8 so they don't meet."""
        return self.win.add(DropDown(MARGIN + AREA_LIST_W - w, AREA_TOP - 2, w, rows,
                                     selected=selected, on_select=on_select))

    def command(self, text, on_click, default=False, needs=None):
        """A command the whole column wide, under the last."""
        b = self.win.add(Button(AREA_COL_X, self.col_y, AREA_COL_W, BUTTON_H, text,
                                GFlag.DEFAULT if default else GFlag.NONE, needs=needs,
                                on_click=on_click))
        self.col_y += BUTTON_H + 4
        return b

    def pair(self, left, right=None):
        """Two commands side by side: (text, on_click) or (text, on_click, needs=box)."""
        out = []
        for i, spec in enumerate((left, right)):
            if spec is None:
                continue
            text, fn = spec[0], spec[1]           # (one: the left half)
            needs = spec[2] if len(spec) > 2 else None
            out.append(self.win.add(Button(AREA_COL_X + i * (AREA_HALF_W + 4), self.col_y,
                                           AREA_HALF_W, BUTTON_H, text, needs=needs,
                                           on_click=fn)))
        self.col_y += BUTTON_H + 4
        return out if right is not None else out[0]

    def section(self, title="Admin Tools"):
        """A line across the column and a bold heading: the commands under it are apart
        from the ones above (Admin Tools: only for those allowed)."""
        self.win.add(Group(AREA_COL_X, self.col_y + 2, AREA_COL_W, 2))
        self.win.add(Label(AREA_COL_X, self.col_y + 8, AREA_COL_W, 10, title,
                           GFlag.BOLD | GFlag.CENTRE))
        self.col_y += 22

    def field(self, label, text="", label_w=48):
        """A label and a text box on one row of the column; returns the box."""
        self.win.add(Label(AREA_COL_X, self.col_y + 2, label_w, 10, label))
        box = self.win.add(TextBox(AREA_COL_X + label_w, self.col_y,
                                   AREA_COL_W - label_w, 12, text))
        self.col_y += 16
        return box

    def check(self, text):
        box = self.win.add(CheckBox(AREA_COL_X, self.col_y, AREA_COL_W, 12, text))
        self.col_y += 16
        return box

    def check_and_command(self, text, command, on_click, needs=None, command_w=58):
        """A check box and a short command on one row: (the box, the button)."""
        box = self.win.add(CheckBox(AREA_COL_X, self.col_y + 2, AREA_COL_W - command_w - 4,
                                    12, text))
        b = self.win.add(Button(AREA_COL_X + AREA_COL_W - command_w, self.col_y, command_w,
                                BUTTON_H, command, needs=needs, on_click=on_click))
        self.col_y += BUTTON_H + 4
        return box, b

    def status(self, text=""):
        assert self.col_y <= self.h - 12, "the command column runs into the status line"
        return self.win.add(Label(MARGIN, self.h - 12, AREA_W - 2 * MARGIN, 10, text))


class Gadget:
    """One gadget. Subclasses set `kind` and add the behaviour of that kind."""

    kind = None

    def __init__(self, x, y, w, h, text="", flags=GFlag.NONE, gid=None,
                 on_click=None, on_select=None, on_key=None):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.text = text
        self.flags = flags
        self.gid = gid
        self.window = None
        self.on_click = on_click        # fn(gadget)
        self.on_select = on_select      # fn(gadget, index, double)
        self.on_key = on_key            # fn(gadget, ascii)   (RAWKEYS gadgets only)
        self.value = ""                 # last value the client sent (text box text, etc.)

    @property
    def session(self):
        return self.window.session if self.window else None

    @property
    def shown(self):
        return self.window is not None and self.window.shown

    def _send(self, msg_type, w):
        if self.shown:
            self.window.session.send(msg_type, w)

    def encode(self):
        return (Writer().u8(self.window.win_id).u8(self.gid).u8(self.kind)
                .u16(self.x).u8(self.y).u16(self.w).u8(self.h).u8(int(self.wire_flags()))
                .str(self.text))

    def wire_flags(self):
        """The flags the client gets (a Button with needs= adds NEEDTEXT)."""
        return self.flags

    def send_contents(self):
        """Sent after the S.GADGET message, before WIN_DONE: initial rows, value..."""

    # ---- server -> client changes ----

    def set_text(self, text):
        self.text = text
        self._send(S.SET_TEXT, Writer().u8(self.window.win_id).u8(self.gid).str(text))

    def set_value(self, value):
        self._send(S.SET_VALUE, Writer().u8(self.window.win_id).u8(self.gid).u16(value))

    def focus(self):
        self._send(S.FOCUS, Writer().u8(self.window.win_id).u8(self.gid))

    @property
    def enabled(self):
        return not self.flags & GFlag.DISABLED

    def enable(self, on=True):
        """Grey a button out (on=False) or back; sent (S.SET_FLAGS) only when it changes.
        Before the window is shown it just sets the flag the GADGET message carries."""
        flags = (self.flags & ~GFlag.DISABLED) | (GFlag.NONE if on else GFlag.DISABLED)
        if flags == self.flags:
            return
        self.flags = flags
        if self.shown:                   # (not shown yet: GADGET carries the flags; a
            self._send(S.SET_FLAGS,      # dynamic window has no id before it's shown)
                       Writer().u8(self.window.win_id).u8(self.gid)
                       .u8(int(self.wire_flags())))

    # ---- client -> server events (called by the window) ----

    def handle_value(self, text):
        self.value = text

    def handle_click(self):
        return self.on_click(self) if self.on_click else self.window.unhandled(self, "click")

    def handle_select(self, index, double):
        if self.on_select:
            return self.on_select(self, index, double)
        return self.window.unhandled(self, "select", index, double)

    def handle_key(self, ascii_code):
        if self.on_key:
            return self.on_key(self, ascii_code)
        return self.window.unhandled(self, "key", ascii_code)

    def handle_need(self, first, n):
        pass

    def handle_text(self, lines):
        if self.session:
            self.session.log("C.TEXT for %d:%d, not an EDIT, ignored"
                             % (self.window.win_id, self.gid))


class Label(Gadget):
    kind = Kind.LABEL


class Button(Gadget):
    """needs=a TextBox in the same window: the client greys the button out while that box is
    empty, as it's typed in (GFlag.NEEDTEXT). The handler still checks what it gets."""
    kind = Kind.BUTTON

    def __init__(self, x, y, w, h, text="", flags=GFlag.NONE, needs=None, **kw):
        super().__init__(x, y, w, h, text, flags, **kw)
        self.needs = needs

    def wire_flags(self):
        if self.needs is None:
            return self.flags
        flags = self.flags | GFlag.NEEDTEXT
        return flags if self.needs.value else flags | GFlag.DISABLED

    def send_contents(self):
        if self.needs is not None:
            self.set_value(self.needs.gid)

class TextBox(Gadget):
    """A one-line text field. `value` holds what the client last sent (C.VALUE). The client
    sends VALUE before any CLICK in the same window, so a button handler sees the current text."""
    kind = Kind.TEXTBOX
    MAX_CHARS = 63          # the client's text boxes hold at most this many characters
    LONG_CHARS = 124        # ... or this many with GFlag.LONG (client 2.2 on; two such boxes
                            # at a time, others hold MAX_CHARS)

    def __init__(self, x, y, w, h=12, text="", **kw):
        super().__init__(x, y, w, h, text, **kw)
        self.value = text

    def set_text(self, text):
        super().set_text(text)
        self.value = text


class Password(TextBox):
    """A text box that shows stars."""
    kind = Kind.PASSWORD


class CheckBox(Gadget):
    """The client toggles it locally and sends SELECT with 1 (checked) or 0. `checked` follows."""
    kind = Kind.CHECKBOX

    def __init__(self, x, y, w, h, text="", checked=False, **kw):
        super().__init__(x, y, w, h, text, **kw)
        self.checked = checked

    def send_contents(self):
        if self.checked:
            self.set_value(1)

    def set_checked(self, checked):
        self.checked = bool(checked)
        self.set_value(1 if checked else 0)

    def handle_select(self, index, double):
        self.checked = bool(index)
        if self.on_select:
            return self.on_select(self, index, double)


class Radio(CheckBox):
    kind = Kind.RADIO


class ListBox(Gadget):
    """A scrolling list. The server keeps all the rows and sends the client every one it can
    hold (CLIENT_ROWS), CHUNK rows to a LIST_ROWS message, whenever the window opens or the
    rows change. (The client never asks for rows: it has no LIST_NEED. It draws all `total`
    rows from its own block, so a row it wasn't sent shows whatever that memory held: on real
    hardware, garbage.) `selected` is the last row the client selected."""
    kind = Kind.LISTBOX
    CLIENT_ROWS = 128       # the rows a client list holds (gui.asm GUI_LIST_ROWS)
    CHUNK = 16              # rows to a message: 16 x (1 + 63) bytes stays well under the
                            # client's biggest frame (proto.asm PF_MAX, 2048; bigger ones it drops)
    ROW_MAX = 63            # the client cuts rows after this many characters

    def __init__(self, x, y, w, h, rows=(), **kw):
        super().__init__(x, y, w, h, "", **kw)
        self.rows = list(rows)
        self.selected = None

    def send_contents(self):
        self.send_all()

    def send_all(self):
        """Every row the client holds, CHUNK at a time (an empty list: just its total)."""
        n = min(len(self.rows), self.CLIENT_ROWS)
        for first in range(0, max(n, 1), self.CHUNK):
            self.send_rows(first, min(self.CHUNK, n - first))

    def send_rows(self, first, n):
        part = self.rows[first:first + min(n, 255)]
        w = (Writer().u8(self.window.win_id).u8(self.gid)
             .u16(len(self.rows)).u16(first).u8(len(part)))
        for row in part:
            w.str(row)
        self._send(S.LIST_ROWS, w)

    def set_rows(self, rows):
        self.rows = list(rows)
        if self.selected is not None and self.selected >= len(self.rows):
            self.selected = None
        self.send_all()

    def handle_select(self, index, double):
        self.selected = index if index < len(self.rows) else None
        if self.on_select:
            return self.on_select(self, index, double)

    def handle_need(self, first, n):
        self.send_rows(first, n)


class TextView(Gadget):
    """Scrolling read-only text: chat, articles, the message of the day. append() adds a line
    at the bottom. The client word-wraps each line to the view's width (columns()), keeps the
    last CLIENT_LINES wrapped lines, and draws a scroll bar; an empty line is a blank line."""
    kind = Kind.TEXTVIEW
    KEEP_LINES = 200        # lines kept on the server (re-sent if the window is shown again)
    CLIENT_LINES = 128      # wrapped lines the client keeps
    PAD = 6                 # the client's inner margins, left + right

    def __init__(self, x, y, w, h, lines=(), **kw):
        super().__init__(x, y, w, h, "", **kw)
        self.lines = list(lines)

    def columns(self):
        """Characters per line on the client, after its margins and scroll bar."""
        return (self.w - self.PAD - SCROLLBAR_W) // CHAR_W

    def send_contents(self):
        for line in self.lines:
            self._append(line)

    def append(self, line):
        self.lines.append(line)
        del self.lines[:-self.KEEP_LINES]
        self._append(line)

    def append_spaced(self, line):
        """append(), after a blank line unless it's the first: chat messages stand apart."""
        if self.lines:
            self.append("")
        self.append(line)

    def set_lines(self, lines, top=False):
        """Replace what it shows, in place: SET_TEXT "" empties it on the client, then an
        APPEND a line (the client redraws it once, at its next frame). It follows the new
        lines down, as a chat does; top=True scrolls it back to the first line after
        (SET_VALUE 0: a page to read from the start)."""
        self.lines = list(lines)[-self.KEEP_LINES:]
        if self.shown:
            self._send(S.SET_TEXT, Writer().u8(self.window.win_id).u8(self.gid).str(""))
            for line in self.lines:
                self._append(line)
            if top:
                self.scroll_to(0)

    def scroll_to(self, line):
        """Scroll the client's view to wrapped line `line` (0 = the top; past the end, the
        last lines)."""
        self.set_value(line)

    def _append(self, line):
        self._send(S.APPEND, Writer().u8(self.window.win_id).u8(self.gid).str(line))


class DropDown(ListBox):
    """A drop-down list (combo box), 12 high. All its rows (at most MAX_ROWS) are sent when
    the window opens, then its selection. `selected` is the row index, or None. The client
    sends SELECT as soon as the user picks a row; on_select(gadget, index, double) runs then."""
    kind = Kind.DROPDOWN
    MAX_ROWS = DROPDOWN_ROWS
    PAD = 6                 # the client's inner margins, left + right

    def __init__(self, x, y, w, rows=(), selected=None, h=12, **kw):
        super().__init__(x, y, w, h, **kw)
        self._check(rows)
        self.rows = list(rows)
        self.selected = selected if selected is not None and selected < len(self.rows) else None

    def _check(self, rows):
        if len(rows) > self.MAX_ROWS:
            raise ValueError("a DropDown holds at most %d rows" % self.MAX_ROWS)

    def columns(self):
        """Characters of the selected row the client shows (left of its arrow button)."""
        return (self.w - self.PAD - SCROLLBAR_W) // CHAR_W

    def send_contents(self):
        self.send_all()                 # (CHUNK rows a message: 128 long rows in one would be
        self.set_value(DROPDOWN_NONE if self.selected is None else self.selected)   # too big)

    def set_rows(self, rows, selected=None):
        """New rows (and selection: None = none)."""
        self._check(rows)
        self.rows = list(rows)
        self.send_all()
        self.set_selected(selected)

    def set_selected(self, index):
        self.selected = index if index is not None and 0 <= index < len(self.rows) else None
        self.set_value(DROPDOWN_NONE if self.selected is None else self.selected)

    @property
    def selected_text(self):
        return None if self.selected is None else self.rows[self.selected]

    def handle_select(self, index, double):
        self.selected = index if index < len(self.rows) else None    # $FFFF: none
        if self.on_select:
            return self.on_select(self, index, double)


class TextArea(Gadget):
    """An editable multi-line text area (Kind.EDIT) with a scroll bar. `lines` is what the
    client last sent (C.TEXT, before any CLICK in the window; trailing empty lines dropped), or
    the initial lines until then. The client wraps typing at columns() characters and keeps at
    most CLIENT_LINES lines."""
    kind = Kind.EDIT
    CLIENT_LINES = EDIT_LINES
    PAD = 6                 # the client's inner margins: left + right, and top + bottom

    def __init__(self, x, y, w, h, lines=(), **kw):
        super().__init__(x, y, w, h, "", **kw)
        self.lines = list(lines)

    def columns(self):
        """Characters per line on the client, after its margins and scroll bar."""
        return min(EDIT_COLS_MAX, (self.w - self.PAD - SCROLLBAR_W) // CHAR_W)

    def visible_lines(self):
        return (self.h - self.PAD) // CHAR_W

    def send_contents(self):
        for line in self.lines[:self.CLIENT_LINES]:
            self._send(S.APPEND, Writer().u8(self.window.win_id).u8(self.gid).str(line))

    def set_lines(self, lines):
        """Replace the contents on the client: SET_TEXT "" empties it, then an APPEND a line."""
        self.lines = list(lines)
        self._send(S.SET_TEXT, Writer().u8(self.window.win_id).u8(self.gid).str(""))
        self.send_contents()

    def set_text(self, text):
        self.set_lines(text.split("\n") if text else [])

    def handle_text(self, lines):
        lines = list(lines)
        while lines and not lines[-1]:
            lines.pop()
        self.lines = lines
        self.value = "\n".join(lines)


class Progress(Gadget):
    """A progress bar: sunken white, filled navy from the left. set_percent(p), 0-100
    (S.SET_VALUE)."""
    kind = Kind.PROGRESS

    def __init__(self, x, y, w, h=12, percent=0, **kw):
        super().__init__(x, y, w, h, "", **kw)
        self.percent = percent

    def send_contents(self):
        if self.percent:
            self.set_value(self.percent)

    def set_percent(self, percent):
        self.percent = max(0, min(100, int(percent)))
        self.set_value(self.percent)


class Grid(Gadget):
    """A board of picture tiles (Kind.GRID; clients with Caps.GRID): cols x rows cells of
    tile_w x tile_h pixels, the tiles in resource slot `slot` (session.send_resource). Each
    cell is a tile number (0-63), plus GRID_MARK1 / GRID_MARK2 for a frame in mark colour 1
    / 2. set_cells() sends only what changed. A click on a cell calls
    on_select(grid, cell, double)."""
    kind = Kind.GRID

    def __init__(self, x, y, cols, rows, tile_w, tile_h, slot, marks=(9, 12), cells=None,
                 **kw):
        if not 0 < cols * rows <= GRID_CELLS_MAX:
            raise ValueError("a grid has 1-%d cells" % GRID_CELLS_MAX)
        self.params = bytes(v + 1 for v in (cols, rows, tile_w, tile_h, slot) + tuple(marks))
        assert len(self.params) == GRID_PARAMS
        super().__init__(x, y, cols * tile_w, rows * tile_h, "", **kw)
        self.cols, self.rows = cols, rows
        self.cells = list(cells) if cells else [0] * (cols * rows)

    def encode(self):
        # (the parameters are bytes, not text: Writer.str would clean them)
        return (Writer().u8(self.window.win_id).u8(self.gid).u8(self.kind)
                .u16(self.x).u8(self.y).u16(self.w).u8(self.h).u8(int(self.wire_flags()))
                .u8(len(self.params)).bytes(self.params))

    def send_contents(self):
        self._send_cells(0, self.cells)

    def set_cells(self, cells):
        cells = list(cells)
        changed = [i for i, (a, b) in enumerate(zip(self.cells, cells)) if a != b]
        self.cells = cells
        if changed:
            first, last = changed[0], changed[-1]
            self._send_cells(first, cells[first:last + 1])

    def _send_cells(self, first, values):
        if not self.shown:
            return
        for i in range(0, len(values), 255):
            part = values[i:i + 255]
            self._send(S.CELLS, Writer().u8(self.window.win_id).u8(self.gid).u8(first + i)
                       .u8(len(part)).bytes(part))

    def handle_select(self, index, double):
        if index >= len(self.cells):
            return None
        return super().handle_select(index, double)


class Image(Gadget):
    """Shows a resource (sent with S.RESOURCE). `text` names it for now."""
    kind = Kind.IMAGE


class Group(Gadget):
    """A labelled frame around other gadgets."""
    kind = Kind.GROUP


class Window:
    """A window and its gadgets. Build it, then show() it on a session.

    `win_id` must be 1-$EF (the client keeps $F0-$FF). Leave it as None and the session picks
    a free one. `on_close(window)` runs when the user clicks the close box.
    """

    def __init__(self, title, x, y, w, h, flags=WFlag.CLOSE | WFlag.MOVABLE, win_id=None,
                 on_close=None, minimize=None):
        """minimize: a minimize box (WFlag.MINIMIZE). By default every window but a modal
        one has it; pass False for a non-modal dialog (OK / Cancel and such)."""
        self.title = title
        self.x, self.y, self.w, self.h = x, y, w, h
        if minimize is None:
            minimize = not flags & WFlag.MODAL
        self.flags = flags | WFlag.MINIMIZE if minimize else flags & ~WFlag.MINIMIZE
        self.win_id = win_id
        self.on_close = on_close
        self.gadgets = {}           # gid -> Gadget
        self.session = None
        self.shown = False
        # Fallback for gadgets without their own callback: fn(gadget, event, *args).
        # Games use it to route every event in their window to Game.on_click / on_key.
        self.on_event = None

    @classmethod
    def centred(cls, title, w, h, **kw):
        """A window with client area w x h, centred on the screen below the menu bar."""
        x, y = centre(w, h)
        return cls(title, x, y, w, h, **kw)

    def add(self, gadget):
        """Add a gadget and return it. Its id is the next free one unless it already has one."""
        if gadget.gid is None:
            gadget.gid = max(self.gadgets, default=0) + 1
        if not 1 <= gadget.gid <= 255 or gadget.gid in self.gadgets:
            raise ValueError("bad or duplicate gadget id %r" % gadget.gid)
        gadget.window = self
        self.gadgets[gadget.gid] = gadget
        return gadget

    def __getitem__(self, gid):
        return self.gadgets[gid]

    @property
    def values(self):
        """{gid: value} for every gadget, as the client last reported them."""
        return {gid: g.value for gid, g in self.gadgets.items()}

    def show(self, session):
        session.open_window(self)

    def send(self):
        """Send WIN_OPEN, every GADGET (plus its initial contents), then WIN_DONE."""
        s = self.session
        s.send(S.WIN_OPEN, Writer().u8(self.win_id).u16(self.x).u8(self.y)
               .u16(self.w).u8(self.h).u8(self.flags).str(self.title))
        for g in self.gadgets.values():
            s.send(S.GADGET, g.encode())
            g.send_contents()
        s.send(S.WIN_DONE, Writer().u8(self.win_id))

    def close(self):
        """Close it on the client (does not call on_close)."""
        if self.session:
            self.session.close_window(self)

    def unhandled(self, gadget, event, *args):
        if self.on_event:
            return self.on_event(gadget, event, *args)
        if self.session:
            self.session.log("no handler for %s on %d:%d" % (event, self.win_id, gadget.gid))

    def handle_closed(self):
        if self.on_close:
            return self.on_close(self)


class MenuItem:
    """One entry of a Menu: a title on the bar (parent 0), an item, or a separator ("-").
    `on_pick(item)` runs when the user picks it; item.session leads back to the session."""

    def __init__(self, menu, item_id, parent, label, on_pick=None):
        self.menu = menu
        self.id = item_id
        self.parent = parent
        self.label = label
        self.on_pick = on_pick

    @property
    def session(self):
        return self.menu.session

    @property
    def pickable(self):
        return self.parent != 0 and self.label != MENU_SEPARATOR


class Menu:
    """The server's menu bar: titles across the top, each with a drop-down list of items.

        menu = Menu()
        go = menu.title(1, "Areas")
        menu.item(16, go, "Chat Rooms", on_pick=lambda item: ...)
        menu.separator(17, go)
        menu.show(session)

    Ids are 1-$EF and unique (the client keeps $F0-$FF for its own Window menu). Items drop
    down in the order they're added. Showing a menu replaces the whole bar; an empty Menu
    clears it.
    """

    def __init__(self):
        self.entries = {}            # id -> MenuItem, in the order added
        self.hidden = {}             # id -> MenuItem picked from the client's own menu
        self.session = None

    def _add(self, item_id, parent, label, on_pick=None):
        if (not MENU_FIRST <= item_id <= MENU_LAST or item_id in self.entries
                or item_id in self.hidden):
            raise ValueError("bad or duplicate menu id %r" % item_id)
        if parent not in (0, MEGANET_MENU) and (parent not in self.entries
                                                 or self.entries[parent].parent != 0):
            raise ValueError("menu id %r: parent %r is not a title" % (item_id, parent))
        if len(self.entries) == 255:
            raise ValueError("too many menu entries")
        item = MenuItem(self, item_id, parent, label, on_pick)
        self.entries[item_id] = item
        return item

    def title(self, item_id, label):
        """Add a title to the bar; returns its id (the parent for its items)."""
        return self._add(item_id, 0, label).id

    def item(self, item_id, parent, label, on_pick=None):
        return self._add(item_id, parent, label, on_pick)

    def separator(self, item_id, parent):
        return self._add(item_id, parent, MENU_SEPARATOR)

    def client_item(self, item_id, label, on_pick):
        """An item the client's own menu sends (e.g. MegaNet > My Account, $22): not sent in
        MENU, but a MENU_PICK of its id is accepted."""
        if not MENU_FIRST <= item_id <= MENU_LAST or item_id in self.entries:
            raise ValueError("bad or duplicate menu id %r" % item_id)
        item = MenuItem(self, item_id, -1, label, on_pick)
        self.hidden[item_id] = item
        return item

    def __contains__(self, item_id):
        return item_id in self.entries

    def show(self, session):
        session.set_menu(self)

    def encode(self):
        w = Writer().u8(len(self.entries))
        for e in self.entries.values():
            w.u8(e.id).u8(e.parent).str(e.label)
        return w

    def handle_pick(self, item_id):
        """C.MENU_PICK: run the item's callback. Ids this menu doesn't have (never sent to
        this session, or gone since), titles and separators are ignored."""
        item = self.entries.get(item_id) or self.hidden.get(item_id)
        if item is None or not item.pickable or item.on_pick is None:
            if self.session:
                self.session.log("menu pick %d ignored: not in this menu" % item_id)
            return None
        return item.on_pick(item)


__all__ = ["Window", "Gadget", "Label", "Button", "TextBox", "Password", "CheckBox", "Radio",
           "ListBox", "DropDown", "TextView", "TextArea", "Progress", "Image", "Group", "Menu", "MenuItem",
           "SELECT_DOUBLE", "centre", "add_buttons", "button_width", "closer", "BUTTON_W",
           "BUTTON_H"]
