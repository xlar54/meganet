"""MegaNet wire protocol (see docs/DESIGN.md, "Protocol").

Every message is a frame:  u16 length (little-endian, counts type + payload), u8 type, payload.
Little-endian everywhere because the client is a 6502-family CPU. Strings are u8 length + ASCII
bytes (the client font is ASCII; anything else becomes '?', and strings stop at 255 bytes).
Screen coordinates: x u16 (0-639), y u8 (0-199). The screen is 640x200; the menu bar takes
its top MENU_BAR_H rows.

This file is the authoritative list of messages. The client's deframer must match it.
"""

from enum import IntEnum, IntFlag
import struct

VERSION = 1            # protocol version, sent in S.HELLO

SCREEN_W = 640
SCREEN_H = 200

# The menu bar takes the top MENU_BAR_H pixel rows of the screen; windows stay below it.
MENU_BAR_H = 11

# WIN_OPEN's w and h are the CLIENT AREA, where the gadgets go (gadget x/y are inside it).
# The client adds its own frame and title bar: FRAME_W more across, FRAME_H more down
# (client-src/lib/gui/gui.asm GUI_FRAME_W / GUI_FRAME_H). So a window fits on the screen when
# x + w + FRAME_W <= 640, y >= MENU_BAR_H and y + h + FRAME_H <= 200; the client moves one
# that doesn't (and clamps it below the bar).
FRAME_W = 8
FRAME_H = 18
CLIENT_MAX_W = SCREEN_W - FRAME_W                   # 632
CLIENT_MAX_H = SCREEN_H - MENU_BAR_H - FRAME_H      # 171


def window_fits(x, y, w, h):
    """True if a window with client area w x h at (x, y) fits on the screen below the bar."""
    return x + w + FRAME_W <= SCREEN_W and y >= MENU_BAR_H and y + h + FRAME_H <= SCREEN_H


# Window ids 1-$EF belong to the server. $F0-$FF are the client's own windows (its sign-on
# window, alerts, the update progress window...): the server never uses them.
SERVER_WIN_FIRST = 0x01
SERVER_WIN_LAST = 0xEF

# S.MENU: u8 n, then n x (u8 id, u8 parent, str label). parent 0 = a title on the bar,
# otherwise the id of the title it drops down from (items in the order sent). A label of "-"
# is a separator line. Each MENU replaces the whole server menu; n = 0 clears it. Ids 1-$EF
# are the server's; $F0-$FF are the client's own (its "Window" menu at the right end of the
# bar, which the client adds by itself). C.MENU_PICK (u8 id) reports a picked item; titles
# and separators are never picked. Titles go across in the order sent, then the client's
# Window menu; titles with ids MENU_LATE-$EF go right of Window instead (the Admin menu).
MENU_FIRST = 0x01
MENU_LAST = 0xEF
MENU_LATE = 0xE0
MENU_SEPARATOR = "-"
# The client's own MegaNet menu has My Account as its first item and sends MENU_PICK with this
# server id for it. It is never in the server's MENU, but the server always accepts it from a
# signed-on session.
MENU_MY_ACCOUNT = 0x22

# S.NOTIFY: u8 slot, u8 icon, str hint. The client draws a small icon button at the right end of
# its menu bar: slot 0 is the rightmost (after the client's own connectivity icon, which is
# always at the very end), slot 1 left of it, and so on; shown icons are packed with no gaps. Icon 0 removes the slot's
# icon. The hint (at most NOTIFY_HINT_MAX characters) is a short text the client may show.
# C.NOTIFY_CLICK (u8 slot) says the user clicked that slot's icon; the client leaves the icon
# there, and the server sends icon 0 when it's done with it. The server's slots:
NOTIFY_SLOTS = 5
NOTIFY_HINT_MAX = 40
SLOT_PAGE = 0            # a user is paging the admins (admins only)
SLOT_ADMIN_MAIL = 1      # messages from users to the admins (admins only)
SLOT_MAIL = 2            # unread private messages
SLOT_NEW_USER = 3        # users still in the default role (admins with admin.users only)
SLOT_IM = 4              # instant messages not read yet
TOAST_NO_SLOT = 0xFF


class Sound(IntEnum):
    """S.SOUND sounds (the client's own, played on its SID)."""
    CHIME = 1            # a two-note "ding-dong": someone is paging (with the flashing icon)


class Icon(IntEnum):
    """S.NOTIFY icons."""
    NONE = 0             # remove the slot's icon
    PAGE = 1             # page / alert (flashing, to get attention)
    MAIL = 2             # mail / messages waiting
    PERSON = 5           # a person (a pawn): new users to look at
    BUBBLE = 6           # a speech bubble: instant messages
                         # (3 and 4 are the client's own Wi-Fi icons)


class S(IntEnum):
    """Server -> client messages ($01-$7F)."""
    HELLO = 0x01         # u8 version, u16 session id
    LOGIN_RESULT = 0x02  # u8 ok (1/0), str message
    WIN_OPEN = 0x10      # u8 win, u16 x, u8 y, u16 w, u8 h, u8 flags, str title
    WIN_CLOSE = 0x11     # u8 win
    GADGET = 0x12        # u8 win, u8 gid, u8 kind, u16 x, u8 y, u16 w, u8 h, u8 flags, str text
    SET_TEXT = 0x13      # u8 win, u8 gid, str text
    SET_VALUE = 0x14     # u8 win, u8 gid, u16 value  (checkbox state, list selection, progress)
    LIST_ROWS = 0x15     # u8 win, u8 gid, u16 total, u16 first, u8 n, n x str
    APPEND = 0x16        # u8 win, u8 gid, str line  (chat, terminal-style views)
    FOCUS = 0x17         # u8 win, u8 gid
    MENU = 0x18          # u8 n, n x (u8 id, u8 parent, str label)   parent 0 = top bar;
                         # replaces the whole server menu ("-" = separator; see MENU_FIRST)
    ALERT = 0x19         # u8 icon, str title, str text  (client draws a modal OK box)
    WIN_DONE = 0x1A      # u8 win  (all gadgets sent: the client may draw the window now)
    NOTIFY = 0x1B        # u8 slot (0-3), u8 icon, str hint  (an icon button at the right end
                         # of the menu bar; see NOTIFY_SLOTS)
    PONG = 0x1C          # (nothing)  the answer to C.PING
    SET_FLAGS = 0x1D     # u8 win, u8 gid, u8 flags  (GFlag: e.g. DISABLED greys a button out
                         # and the client ignores clicks on it; redrawn)
    TOAST = 0x1E         # u8 seconds, u8 slot, str text  (a short line in a box at the bottom
                         # right for a while, over everything, taking no input; a click on it
                         # removes it and, unless slot is $FF, acts as a NOTIFY_CLICK of slot)
    DESK_ICON = 0x1F     # u8 slot, str line 1, str line 2, then (unless line 1 is empty, which
                         # removes the icon) DESK_ICON_W x DESK_ICON_H bytes of pixels, row by
                         # row: GUI colours 0-15, DESK_CLEAR = transparent. A desktop icon in
                         # the column at the left, Windows 95 style: a click selects it, a
                         # double click sends C.DESK_OPEN
    BROADCAST = 0x23     # u8 seconds, str text  (a message to everyone: the whole bottom row of
                         # the screen, yellow on red, over everything but a toast, for that
                         # long or until clicked; it takes no input. BROADCAST_MAX characters)
    SOUND = 0x24         # u8 sound (Sound): the client plays it on its SID
    FILE_BEGIN = 0x20    # u32 size, str name
    FILE_DATA = 0x21     # u32 offset, bytes...
    FILE_END = 0x22      # u32 crc32
    RESOURCE = 0x30      # u16 id, u8 version, u8 kind, bytes...  (icons etc., cached in attic)
    UPDATE = 0x40        # u16 new build, u8 nfiles, str message  (forced: the client shows a
                         # progress window, receives nfiles x FILE_BEGIN/DATA/END, writes them,
                         # reboots)


class C(IntEnum):
    """Client -> server messages ($80-$FF)."""
    HELLO = 0x80         # u8 protocol version, u16 client build, u8 caps, str client name
    CLICK = 0x81         # u8 win, u8 gid
    VALUE = 0x82         # u8 win, u8 gid, str text  (text box contents on submit / change)
    SELECT = 0x83        # u8 win, u8 gid, u16 index  (list selection; double-click sets bit 15)
    LIST_NEED = 0x84     # u8 win, u8 gid, u16 first, u8 n
    MENU_PICK = 0x85     # u8 id  (an item of the last S.MENU; never a title or separator)
    WIN_CLOSED = 0x86    # u8 win  (the user clicked the close box)
    KEY = 0x87           # u8 win, u8 gid, u8 ascii  (only for gadgets with the RAWKEYS flag)
    FILE_ACK = 0x88      # u32 offset received
    LOGIN = 0x89         # u8 flags (bit 0 = new user), str screen name, str password
    NOTIFY_CLICK = 0x8A  # u8 slot  (the user clicked the S.NOTIFY icon in that slot)
    TEXT = 0x8B          # u8 win, u8 gid, u8 n, n x str  (an EDIT gadget's lines, trailing
                         # empty lines dropped; sent for every EDIT of the window before a
                         # CLICK, as VALUE is for text boxes)
    DESK_OPEN = 0x8C     # u8 slot  (the S.DESK_ICON in that slot was double-clicked)
    PING = 0x8F          # (nothing)  "are you there?": the server answers S.PONG. The client
                         # sends it after 30 s with nothing from the server, and shows its
                         # connectivity icon with an X if no answer comes in 10 s


class Kind(IntEnum):
    """Gadget kinds (the u8 kind in S.GADGET)."""
    LABEL = 1
    BUTTON = 2
    TEXTBOX = 3
    PASSWORD = 4
    LISTBOX = 5
    CHECKBOX = 6
    RADIO = 7
    TEXTVIEW = 8
    PROGRESS = 9
    IMAGE = 10
    GROUP = 11
    # A drop-down list (combo box), 12 high. Rows come in LIST_ROWS like a ListBox's (at most
    # DROPDOWN_ROWS rows of at most 31 characters, all sent at once); SET_VALUE sets the
    # selection (the row index, $FFFF = none). The client draws the selected row's text and a
    # down-arrow button 11 px wide at the right, so it shows (w - 6 - 11) // 8
    # characters. Picking a row sends C.SELECT (win, gid, index) at once.
    DROPDOWN = 12
    # An editable multi-line text area: sunken white, a scroll bar 11 px wide inside its right
    # edge; lines of (w - 6 - 11) // 8 characters (at most EDIT_COLS_MAX), (h - 6) // 8 lines
    # visible. Initial contents: one APPEND per line after its GADGET, before WIN_DONE;
    # SET_TEXT "" empties it. The client keeps at most EDIT_LINES lines and wraps typing at the
    # line width. It sends C.TEXT with the lines before any CLICK in the window.
    EDIT = 13


DROPDOWN_ROWS = 128      # a DROPDOWN holds at most this many rows
DROPDOWN_NONE = 0xFFFF   # SET_VALUE / C.SELECT index for "no row selected"
EDIT_LINES = 32          # an EDIT holds at most this many lines
EDIT_COLS_MAX = 63       # and lines of at most this many characters


class WFlag(IntFlag):
    """Window flags (S.WIN_OPEN)."""
    NONE = 0
    CLOSE = 1            # has a close box
    MODAL = 2            # blocks the windows behind it
    MOVABLE = 4          # can be dragged
    MINIMIZE = 8         # has a minimize box: the client shrinks it to a title bar at the
                         # bottom of the screen and restores it by itself (the server isn't
                         # told; updates still arrive, and opening it again restores it)


class GFlag(IntFlag):
    """Gadget flags (S.GADGET)."""
    NONE = 0
    DEFAULT = 1          # RETURN presses this button
    DISABLED = 2
    RAWKEYS = 4          # send every key press as C.KEY (games)
    MULTILINE = 8
    CENTRE = 16          # a label's text centred in its width
    NEEDTEXT = 32        # a button the client greys out while one text box is empty (the
                         # box's gid comes after the GADGET as the button's S.SET_VALUE)


BROADCAST_MAX = 79       # S.BROADCAST: characters across the bottom row
BROADCAST_SECS = 20
DESK_SLOTS = 8           # S.DESK_ICON slots 0-7, top to bottom
DESK_ICON_W, DESK_ICON_H = 32, 16   # (640x200 pixels are twice as tall: it looks square)
DESK_LABEL_MAX = 10      # characters a label line
DESK_CLEAR = 0xFF        # a transparent pixel

LOGIN_NEW_USER = 0x01    # C.LOGIN flags bit 0
SELECT_DOUBLE = 0x8000   # C.SELECT index bit 15 = double-click


class ProtocolError(Exception):
    """The byte stream doesn't follow the protocol (the server drops the connection)."""


def clean_text(s):
    """Make a string safe for the client: printable ASCII only, at most 255 bytes."""
    s = "" if s is None else str(s)
    return "".join(ch if " " <= ch <= "~" else "?" for ch in s)[:255]


# ---- encoding ------------------------------------------------------------------------------

class Writer:
    """Builds one message. Chain the field methods, then call frame(type):

        Writer().u8(win).u8(gid).str("hello").frame(S.SET_TEXT)
    """

    def __init__(self):
        self.parts = bytearray()

    def u8(self, v):
        self.parts += struct.pack("<B", int(v) & 0xFF)
        return self

    def u16(self, v):
        self.parts += struct.pack("<H", int(v) & 0xFFFF)
        return self

    def u32(self, v):
        self.parts += struct.pack("<I", int(v) & 0xFFFFFFFF)
        return self

    def str(self, s):
        b = clean_text(s).encode("ascii")
        self.u8(len(b))
        self.parts += b
        return self

    def bytes(self, b):
        self.parts += bytes(b)
        return self

    def frame(self, msg_type):
        body = bytes([int(msg_type)]) + bytes(self.parts)
        if len(body) > 0xFFFF:
            raise ValueError("frame too long")
        return struct.pack("<H", len(body)) + body


class Reader:
    """Reads the fields of one received message, in order."""

    def __init__(self, buf):
        self.b = bytes(buf)
        self.p = 0

    def _take(self, n):
        if self.p + n > len(self.b):
            raise ProtocolError("message too short")
        v = self.b[self.p:self.p + n]
        self.p += n
        return v

    def u8(self):
        return self._take(1)[0]

    def peek_u8(self):
        """The next u8, left unread (None at the end of the message)."""
        return self.b[self.p] if self.p < len(self.b) else None

    def u16(self):
        return struct.unpack("<H", self._take(2))[0]

    def u32(self):
        return struct.unpack("<I", self._take(4))[0]

    def str(self):
        n = self.u8()
        return self._take(n).decode("latin-1")

    def rest(self):
        r = self.b[self.p:]
        self.p = len(self.b)
        return r


class Deframer:
    """Splits a TCP byte stream into frames.

    Call push() with each chunk as it arrives; it returns a list of (type, Reader) for every
    complete frame. A partial frame stays buffered until the rest arrives.
    """

    def __init__(self):
        self.buf = bytearray()

    def push(self, chunk):
        self.buf += chunk
        frames = []
        while len(self.buf) >= 2:
            length = self.buf[0] | (self.buf[1] << 8)
            if length == 0:
                raise ProtocolError("empty frame")
            if len(self.buf) < 2 + length:
                break
            body = bytes(self.buf[2:2 + length])
            del self.buf[:2 + length]
            frames.append((body[0], Reader(body[1:])))
        return frames
