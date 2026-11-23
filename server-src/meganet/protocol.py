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
# The client's own MegaNet title: the server may put items under it as a parent (MegaNet >
# System Stats). Clients up to build 2 add them after their own items (below Exit).
MEGANET_MENU = 0xF8

# S.NOTIFY: u8 slot, u8 icon, str hint. The client draws a small icon button at the right end of
# its menu bar: slot 0 is the rightmost (after the client's own connectivity icon, which is
# always at the very end), slot 1 left of it, and so on; shown icons are packed with no gaps. Icon 0 removes the slot's
# icon. The hint (at most NOTIFY_HINT_MAX characters) is a short text the client may show.
# C.NOTIFY_CLICK (u8 slot) says the user clicked that slot's icon; the client leaves the icon
# there, and the server sends icon 0 when it's done with it. The server's slots:
NOTIFY_SLOTS = 8          # (clients from before the newspaper have 6, before SID Music 7:
                          # they ignore the slots they don't have)
NOTIFY_HINT_MAX = 40
SLOT_STATUS = 0          # your status, always shown: a green / yellow / dark grey dot
SLOT_PAGE = 1            # a user is paging the admins (admins only)
SLOT_ADMIN_MAIL = 2      # messages from users to the admins (admins only)
SLOT_MAIL = 3            # unread private messages
SLOT_NEW_USER = 4        # users still in the default role (admins with admin.users only)
SLOT_IM = 5              # instant messages not read yet
SLOT_NEWS = 6            # unread news bulletins (news.py)
SLOT_MUSIC = 7           # a SID tune playing or paused (sidlib.py): Now Playing
TOAST_NO_SLOT = 0xFF


class Sound(IntEnum):
    """S.SOUND sounds (the client's own, played on its SID)."""
    CHIME = 1            # a two-note "ding-dong": someone is paging (with the flashing icon)
    KACHING = 2          # a cash register: you won a poker hand (older clients play nothing)
    DOORBELL = 3         # a four-note Westminster doorbell: a new instant or private message
                         # (session.ring: not while Away unless My Account says so)


class Icon(IntEnum):
    """S.NOTIFY icons."""
    NONE = 0             # remove the slot's icon
    PAGE = 1             # page / alert (flashing, to get attention)
    MAIL = 2             # mail / messages waiting
    PERSON = 5           # a person (a pawn): new users to look at
    BUBBLE = 6           # a speech bubble: instant messages
                         # (3 and 4 are the client's own Wi-Fi icons)
    AVAILABLE = 7        # status dots (SLOT_STATUS): green
    AWAY = 8             # yellow
    OFFLINE = 9          # dark grey
    NEWS = 10            # a folded newspaper: unread news
    NOTE = 11            # two beamed music notes: a SID tune playing (SLOT_MUSIC)
    NOTE_PAUSED = 12     # the notes greyed: paused


class S(IntEnum):
    """Server -> client messages ($01-$7F)."""
    HELLO = 0x01         # u8 version, u16 session id
    LOGIN_RESULT = 0x02  # u8 ok (1/0), str message
    WIN_OPEN = 0x10      # u8 win, u16 x, u8 y, u16 w, u8 h, u8 flags, str title
    WIN_CLOSE = 0x11     # u8 win
    GADGET = 0x12        # u8 win, u8 gid, u8 kind, u16 x, u8 y, u16 w, u8 h, u8 flags, str text
    SET_TEXT = 0x13      # u8 win, u8 gid, str text
    SET_VALUE = 0x14     # u8 win, u8 gid, u16 value  (checkbox state, list selection, progress;
                         # a text view's scroll: the wrapped line at its top)
    LIST_ROWS = 0x15     # u8 win, u8 gid, u16 total, u16 first, u8 n, n x str
    APPEND = 0x16        # u8 win, u8 gid, str line  (chat, terminal-style views)
    FOCUS = 0x17         # u8 win, u8 gid
    MENU = 0x18          # u8 n, n x (u8 id, u8 parent, str label)   parent 0 = top bar;
                         # replaces the whole server menu ("-" = separator; see MENU_FIRST)
    ALERT = 0x19         # u8 icon, str title, str text  (client draws a modal OK box)
    WIN_DONE = 0x1A      # u8 win  (all gadgets sent: the client may draw the window now)
    NOTIFY = 0x1B        # u8 slot (0-6), u8 icon, str hint  (an icon button at the right end
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
    FILE_BEGIN = 0x20    # u32 size, str name  (an update's file; see UPDATE)
    FILE_DATA = 0x21     # u32 offset, bytes...  (at most FILE_CHUNK; after FILE_BEGIN or
                         # SAVE_BEGIN)
    FILE_END = 0x22      # u32 crc32 (zlib.crc32 of the whole file)
    # The client's local storage (the File Library; see "Local storage" in docs/DESIGN.md).
    # dev 8-11 = a CBM drive unit (through the KERNAL), dev 0 = the SD card (LOCAL_SD). An SD
    # path is folder names from the card's root joined by "/" ("" = the root), and for a file
    # its 8.3 name last ("GAMES/ELITE.D81"). req numbers a request: replies carry it, and the
    # server ignores replies to a request it has given up on.
    LOCAL_DIR = 0x25     # u8 req, u8 dev, str path  (a drive's directory, or an SD folder):
                         # the client answers C.LOCAL_ENTRY per entry, then C.LOCAL_DONE
    SAVE_BEGIN = 0x26    # u8 req, u8 dev, u8 kind (Local), u32 size, str path  (a drive file's
                         # name, or an SD path): the client checks it can (the device answers,
                         # no file of that name) and answers C.FILE_ACK 0, or C.LOCAL_DONE with
                         # the trouble. Then FILE_DATA..., FILE_END; the client stages it all,
                         # checks the CRC, writes it, and answers C.LOCAL_DONE
    LOAD_FILE = 0x27     # u8 req, u8 dev, u8 kind, str path  (send me that file): the client
                         # answers C.UP_BEGIN, C.UP_DATA..., C.UP_END, or C.LOCAL_DONE (trouble)
    LOCAL_CANCEL = 0x28  # u8 req  (stop that request; the client answers nothing)
    CELLS = 0x29         # u8 win, u8 gid, u8 first, u8 n, n x u8  (a GRID gadget's cells
                         # first .. first+n-1: bits 0-5 the tile, bit 6 / bit 7 a frame in the
                         # grid's mark colour 2 / 1; the client redraws the grid)
    RESOURCE = 0x30      # u8 slot (0-15), u16 offset, bytes...  (at most RESOURCE_CHUNK):
                         # stored in the client's resource slot (64 KB of attic each) at
                         # offset. A GRID's tiles live in one: tile t at t * tile_w * tile_h,
                         # row by row, a byte (palette index) a pixel
    # A picture over the whole screen (the Art Gallery). Clients with Caps.PICTURE only.
    PICTURE = 0x2A       # u8 slot, u8 mode (PIC_LORES / PIC_HIRES), u8 border, u8 n (1-255),
                         # n x (r, g, b): the pixels are in resource slot `slot` on (two slots
                         # for hires; see gallery/picture.py for their order), the colours
                         # palette entries 0..n-1, the screen's border colour `border`. The client hides its desktop and draws nothing else until
                         # S.PICTURE_END (it still takes messages, and keeps their changes for
                         # then); keys and clicks go to the server as C.PIC_KEY. Another
                         # PICTURE while one shows replaces it
    PICTURE_END = 0x2B   # (nothing)  back to the desktop: its palette, everything drawn again
    RESOURCE_PACKED = 0x2C   # u8 slot, u16 offset, PackBits bytes...  (at most RESOURCE_CHUNK;
                         # gallery/picture.py packed_chunks): as RESOURCE, unpacked from offset
                         # on (wrapping inside the slot). Caps.PICTURE clients only
    # Paint (gallery/paint.py): a picture the server keeps, as the desktop. Caps.CANVAS only.
    CANVAS = 0x2D        # u8 slot, u8 n (1-239), n x (r, g, b): the picture in resource slot
                         # `slot` (320x200 in the lores framebuffer order of
                         # gallery/picture.py, each byte a palette entry: CANVAS_FIRST + its
                         # colour) becomes the desktop, its colours palette entries
                         # CANVAS_FIRST on. The windows open now are hidden, and the menu bar,
                         # until CANVAS_END; windows opened after it show over the picture.
                         # Presses, moves and releases on it come as C.CANVAS. Again while it
                         # shows: new colours
    CANVAS_END = 0x2E    # (nothing)  the desktop, the hidden windows and the menu bar back
    CANVAS_RECT = 0x2F   # u16 x, u8 y, u16 w, u8 h, PackBits of w * h bytes, row by row
                         # (palette entries): those pixels of the picture changed
    # The server's sprites (Caps.SPRITES; session.sprite_show / sprite_move / sprite_off /
    # fly): SPRITES hardware sprites made by the client from any picture in a resource slot
    SPRITE = 0x32        # u8 n, u8 win, u8 slot, u16 offset, u8 w (1-16), u8 h (1-64),
                         # u16 stride, u8 step, u16 x, u8 y, u8 c, c x (u8 colour, r, g, b):
                         # sprite n is the picture at `offset` in slot `slot` (w pixels `step`
                         # bytes apart, h rows `stride` apart), its colours the c listed (any
                         # other byte see-through), at (x, y) in window win's client area
    SPRITE_MOVE = 0x33   # u8 n, s16 dx, s16 dy, u8 frames, u8 hide: it moves (dx, dy) a frame
                         # (8.8 fixed point) for `frames` frames, then goes if hide is 1
    SPRITE_OFF = 0x34    # u8 n ($FF: all): gone
    SID_PLAY = 0x35      # u8 slot, u16 load, u16 length, u16 init, u16 play, u8 song (0-based),
                         # u8 rate (play calls a second: 50 or 60)  (Caps.SID: the C64 data of
                         # a checked PSID tune is in the resource slot; the client plays it in
                         # the background, pausing while its own sounds play: sidplay.asm)
    SID_STOP = 0x36      # (nothing)  the tune stops
    SID_PAUSE = 0x37     # u8 paused (1: hold it where it is, its SIDs muted; 0: carry on)
    CANVAS_PEN = 0x31    # u8 mode (CanvasPen), u8 colour (a palette entry), u8 size (1-16):
                         # what the client draws at once while the mouse is held, before the
                         # server's CANVAS_RECT comes
    UPDATE = 0x40      # u16 new build, u8 nfiles, str message  (forced: the client shows a
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
    FILE_ACK = 0x88      # u32 bytes received so far (the server keeps at most FILE_WINDOW
                         # bytes unacknowledged); 0 after S.SAVE_BEGIN = ready
    LOGIN = 0x89         # u8 flags (bit 0 = new user), str screen name, str password
    NOTIFY_CLICK = 0x8A  # u8 slot  (the user clicked the S.NOTIFY icon in that slot)
    TEXT = 0x8B          # u8 win, u8 gid, u8 n, n x str  (an EDIT gadget's lines, trailing
                         # empty lines dropped; sent for every EDIT of the window before a
                         # CLICK, as VALUE is for text boxes)
    DESK_OPEN = 0x8C     # u8 slot  (the S.DESK_ICON in that slot was double-clicked)
    LOCAL_ENTRY = 0x8D   # u8 req, u8 kind (Local), u32 size, str name  (S.LOCAL_DIR's answer,
                         # one per entry: size in bytes on the SD card, in blocks on a drive;
                         # Local.HEADER = the disk's name, Local.FREE = blocks free)
    LOCAL_DONE = 0x8E    # u8 req, u8 status (LocalStatus), str text  (a request is over; text
                         # = the drive's own message, or "")
    PING = 0x8F          # (nothing)  "are you there?": the server answers S.PONG. The client
                         # sends it after 30 s with nothing from the server, and shows its
                         # connectivity icon with an X if no answer comes in 10 s
    UP_BEGIN = 0x90      # u8 req, u32 size  (S.LOAD_FILE's file follows)
    UP_DATA = 0x91       # u8 req, bytes...  (at most UP_CHUNK, in order)
    UP_END = 0x92        # u8 req, u32 crc32
    PIC_KEY = 0x93       # u8 key  (while an S.PICTURE shows: the key's ASCII code, Esc = 27, a
                         # left click = PIC_CLICK, a right click = Esc)
    CANVAS = 0x94        # u8 event (CanvasEvent), u16 x, u8 y  (on S.CANVAS's picture, in its
                         # pixels: 0-319, 0-199; moves only while the button is held, and only
                         # when the picture pixel changes)


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
    # A grid of picture tiles (board games). The GADGET text is 7 bytes, each value + 1 (so
    # none is 0): cols, rows, tile w, tile h, resource slot, mark colour 1, mark colour 2; w and
    # h are cols * tile w, rows * tile h. The cells (all 0 at first) come in S.CELLS; a click on
    # cell n (row * cols + col) sends C.SELECT (win, gid, n). Clients with Caps.GRID only.
    GRID = 14


GRID_PARAMS = 7          # the GRID gadget text's bytes
GRID_CELLS_MAX = 256     # cells in one grid at most (the client keeps 256 a grid)
GRID_TILE_MASK = 0x3F    # S.CELLS: bits 0-5 the tile
GRID_MARK1 = 0x80        # bit 7: a frame in mark colour 1
GRID_MARK2 = 0x40        # bit 6: a frame in mark colour 2
# The client's palette: entries 0-15 are the GUI's, 240-254 these fixed colours for game
# art (tools/build_assets.py GAME_COLOURS must match). Tiles may use any of them.
GAME_FIRST = 240
GAME_COLOURS = [
    (240, 217, 181), (181, 136, 99),             # 240 / 241: light and dark squares
    (250, 248, 240), (190, 184, 172),            # 242 / 243: white pieces, their shade
    (40, 36, 34), (120, 112, 104),               # 244 / 245: black pieces, their highlight
    (205, 210, 106), (170, 162, 58),             # 246 / 247: last-move squares (light, dark)
    (90, 100, 60), (118, 150, 86),               # 248: move dots; 249 green squares
    (238, 238, 210), (200, 40, 40),              # 250 cream squares; 251 red
    (60, 120, 200), (230, 190, 40), (20, 20, 20),    # 252 blue; 253 gold; 254 near black
]
GUI_RGB = list(zip(     # palette entries 0-15: the client's GUI colours (lib/gui/gui.asm GUIPAL_*)
    [0, 255, 192, 128, 223, 0, 0, 16, 255, 192, 0, 64, 0, 8, 255, 0],
    [0, 255, 192, 128, 223, 0, 128, 132, 255, 0, 128, 64, 0, 8, 255, 255],
    [0, 255, 192, 128, 223, 128, 128, 208, 225, 0, 0, 64, 255, 24, 0, 255]))


def palette_rgb(index):
    """(r, g, b) of a palette entry the server knows: the GUI's (0-15) or the game colours."""
    if index < 16:
        return GUI_RGB[index]
    if GAME_FIRST <= index < GAME_FIRST + len(GAME_COLOURS):
        return GAME_COLOURS[index - GAME_FIRST]
    raise ValueError("palette entry %d isn't a fixed colour" % index)


SPRITES = 2              # the server's sprites (S.SPRITE n): 0 and 1
SPRITE_W, SPRITE_H, SPRITE_COLOURS = 16, 64, 15     # a sprite's pixels across, rows, colours
RESOURCE_SLOTS = 16
RESOURCE_SIZE = 0x10000  # bytes a slot
RESOURCE_CHUNK = 1024    # S.RESOURCE bytes at most
PIC_LORES, PIC_HIRES = 0, 1      # S.PICTURE modes: 320x200 (pixels doubled across), 640x200
PIC_CLICK = 1            # C.PIC_KEY: a left click
PIC_ESC = 27
CANVAS_FIRST = 16        # S.CANVAS: the palette entry of the picture's colour 0
CANVAS_COLOURS = 239     # (entries 16-254)
CANVAS_W, CANVAS_H = 320, 200


class CanvasPen(IntEnum):
    """S.CANVAS_PEN modes: what the client draws at once while the mouse is held."""
    NONE = 0             # nothing (the server's answer shows it)
    FREE = 1             # the brush (a square `size` across) along the pointer
    LINE = 2             # a 1-pixel line from the press to the pointer, gone at the release
    BOX = 3              # a box's 1-pixel outline from the press to the pointer, the same


class CanvasEvent(IntEnum):
    """C.CANVAS events."""
    DOWN = 1
    MOVE = 2
    UP = 3
    RIGHT = 4            # a right click
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
    BOLD = 64            # a label's text in bold (older clients draw it plain)


BROADCAST_MAX = 79       # S.BROADCAST: characters across the bottom row
BROADCAST_SECS = 20
DESK_SLOTS = 12          # S.DESK_ICON slots: 0-7 in columns from the left edge, top to
DESK_LEFT = 8            # bottom; 8-11 down the right edge (older clients ignore those)
DESK_ICON_W, DESK_ICON_H = 32, 16   # (640x200 pixels are twice as tall: it looks square)
DESK_LABEL_MAX = 10      # characters a label line
DESK_CLEAR = 0xFF        # a transparent pixel

class Caps(IntFlag):
    """C.HELLO's caps byte: what the client can do."""
    NONE = 0
    DRIVES = 1           # CBM drives 8-11: directories, saving and reading PRG / SEQ / USR
    SD_READ = 2          # the SD card: folders, and reading D64 / D81 images (uploads)
    SD_WRITE = 4         # writing D64 / D81 images to the SD card (downloads)
    GRID = 8             # Kind.GRID gadgets, S.CELLS and S.RESOURCE (board games)
    PICTURE = 16         # S.PICTURE / PICTURE_END / RESOURCE_PACKED, C.PIC_KEY (Art Gallery)
    CANVAS = 32          # S.CANVAS / CANVAS_END / CANVAS_RECT / CANVAS_PEN, C.CANVAS (Paint)
    SPRITES = 64         # S.SPRITE / SPRITE_MOVE / SPRITE_OFF (One's flying cards)
    SID = 128            # S.SID_PLAY / SID_STOP: SID tunes in the background (SID Music)


class Local(IntEnum):
    """Local storage kinds: C.LOCAL_ENTRY's kind, and S.SAVE_BEGIN's / S.LOAD_FILE's."""
    HEADER = 0           # a drive's disk name (the directory's first line)
    DIR = 1              # an SD folder
    PRG = 2
    SEQ = 3
    USR = 4
    REL = 5
    DEL = 6
    D81 = 7
    D64 = 8
    FILE = 9             # any other SD file
    FREE = 15            # a drive's "blocks free" (size = the blocks)


class LocalStatus(IntEnum):
    """C.LOCAL_DONE's status."""
    OK = 0
    NO_DEVICE = 1        # nothing answers at that unit, or no SD card
    NOT_FOUND = 2        # no such file or folder
    EXISTS = 3           # a file of that name is already there (saves never overwrite)
    DISK_FULL = 4        # no room (on an SD card: no free run long enough for an image)
    BAD_CRC = 5          # what arrived doesn't match FILE_END's CRC (nothing was written)
    IO_ERROR = 6         # the drive or card said something else (the text has it)
    UNSUPPORTED = 7      # this client can't do that
    TOO_BIG = 8          # more than the client can stage (LOCAL_MAX)
    CANCELLED = 9


LOCAL_SD = 0             # S.LOCAL_DIR / SAVE_BEGIN / LOAD_FILE dev: the SD card
LOCAL_DRIVES = (8, 9, 10, 11)
LOCAL_MAX = 1 << 20      # the biggest file the client stages in attic (a D81 is 819,200)
FILE_CHUNK = 1000        # S.FILE_DATA bytes at most: with its 7-byte header a frame fits
                         # mega-ip's 1024-byte receive window, so none is split in two
FILE_WINDOW = 8 * FILE_CHUNK  # bytes sent ahead of the client's last FILE_ACK (whole chunks):
                              # more than a TCP window (mega-ip's is 2,920), so the
                              # FILE_ACKs never hold the stream back
UP_CHUNK = 240           # C.UP_DATA bytes at most (the client's frames are under 256 bytes)

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
