# MegaNet design

MegaNet is a graphical, multi-user online service for the MEGA65, in the style of mid-90s
point-and-click services. It has a fat client and a thin protocol. The **server** (Python,
`server-src/`) owns all content and logic, and tells the client which windows and gadgets to
show. The **client** (45GS02 assembly, `client-src/`) draws a Windows 95-style desktop, runs the
widgets itself, and sends the server meaningful events: "button 5 clicked", "text box 3 now
holds 'hello'", "row 12 double-clicked". It never sends raw mouse moves.

## Client

### Screen and look

- **640x200, 256 colours, Full Colour Mode** (`lib/fcm640.asm` + `lib/draw640.asm`). Win95
  widgets need 640 pixels across to fit a usable amount of text. 200 lines is tight, so the
  font is 8x8 (`font8`). A proportional font comes later.
- Win95 look: a grey face (`#C0C0C0`) with 3-D bevels (a white/light top-left and a dark-grey/
  black bottom-right, swapped when pressed), navy title bars with white bold text, a sunken white
  field for text boxes and lists, a desktop teal and a taskbar along the bottom row. It
  needs about 8 palette entries; the rest are free for icons and pictures.
- **Mouse pointer = hardware sprite** (`lib/hwsprite.asm`; there's no Xemu X offset in H640),
  so moving it never redraws anything. The 1351 mouse uses `lib/mouse.asm`.
- **Redraw by window**, back to front, into the framebuffer that isn't on screen, then flip. A
  window drag shows only an XOR-style outline (Win95 did this too) and redraws when it's
  released. Fills are DMA jobs, so a full-screen redraw should take a frame or two at 40 MHz.
  This still has to be measured.

### Sign-on screen

The client draws these itself (`client-src/login.asm`), over the MegaNet logo
(`client-src/assets/logo.png`, a slanted wordmark with rainbow stripes in the MEGA65 style)
on a dark backdrop. There are two windows, one after the other:

1. **Connect.** The network starts by itself. The window shows the MEGA65's own address once
   DHCP has given one, and asks for the server's address. **Connect** opens the TCP
   connection and sends `HELLO`.
2. **Sign On**, once connected. It asks for the screen name and password. It has three buttons:
   - **Sign On** sends `LOGIN`.
   - **New User** sends `LOGIN` with the new-user flag and an empty name and password,
     which starts the server's step-by-step sign-up wizard.
   - **Back** closes the connection and returns to Connect.

The server answers with `LOGIN_RESULT`, then sends its menus. A refusal or a cancelled
sign-up leaves the Sign On window up, with the reason on its status line.

While the client waits for the server, the pointer is an hourglass and clicks are ignored.
That covers connecting, the wait for a sign-on answer, and up to 1.5 s after a click or menu
pick (`gui_busy`). The server's alerts are word-wrapped over up to 4 lines.

### After sign-on

The same black backdrop and logo stay behind the windows, with a menu bar across the top (no bar
on the sign-on screen). The bar is:
- the client's own **MegaNet** menu, always first (`client-src/exit.asm`, ids `$F8+`). Its
  **Exit** asks "are you sure", drops the connection, copies back the ROM image saved to attic
  at boot (the framebuffer uses the ROM area), and returns to BASIC's READY prompt
  (`lib/kstream.asm` `kst_to_basic`);
- the server's menus, from `MENU`;
- the built-in **Window** menu, last.

### Widget toolkit (`client-src/lib/gui/`, independent of MegaNet: see its README)

| Gadget | Local behaviour (no network round-trip) |
|---|---|
| Window | title bar, close box, drag, z-order, focus; modal windows block the ones behind them |
| Button | pressed look while held; the click is sent on release inside the button; DEFAULT = RETURN |
| Label | static text, clipped |
| Text box / password | caret, typing, cursor keys, DEL, scrolling inside the box; it sends VALUE before any CLICK in the same window, so the server sees the current contents |
| List box | scroll bar, keyboard and wheel scrolling, selection, double-click; the client holds up to 128 rows, and the server sends all of them (16 to a LIST_ROWS) whenever the list is shown or changes. The client never asks for rows: `LIST_NEED` is in the protocol, but the client doesn't send it, so a row the server didn't send would show stale memory |
| Text view | scrolling multi-line text (chat, articles); APPEND adds lines; old lines are dropped from a ring in attic |
| Check box / radio | toggles locally, then sends SELECT |
| Progress bar | set by the server (downloads, updates) |
| Menu bar | pull-down menus defined by the server; picks are sent as MENU_PICK |
| Alert | modal OK box, drawn entirely by the client |
| Image / icon | server-sent resources, cached in attic by id + version |

The gadget tables live in chip RAM, and text and list contents live in attic. Window ids and
gadget ids are one byte each.

### Networking

- **mega-ip** gives Ethernet, ARP, DHCP, DNS and TCP. MegaNet uses it the way weather65 does
  (the weather65 project's `src/net.asm`, proven on hardware). `eth.bin` is loaded at boot to
  `$42000` and called through a MAP trampoline below `$2000`. It uses weather65's copy, which has
  the receive-rotate fix. Its receive ring is at `$50000-$515FF`, so the 640x200 framebuffer is at
  `$20000` (the ROM area, unprotected after the takeover). `docs/MEGA65_NOTES.md` section 13 has
  the pacing rules.
- The MEGA65 always gets its address by DHCP. The server port is fixed (6400). The user types the
  server's IP address on the sign-on screen.
- The poll pump runs from the main loop, not the IRQ. Received bytes go through a deframer that
  matches `server-src/meganet/protocol.py`.
- The current stack keeps a single connection and one TX segment in flight. That's fine for UI
  traffic, but it limits download speed to about one segment per round trip. Before file
  downloads matter, measure it and, if needed, allow more segments in flight (this belongs in
  mega-ip itself).

### Code size

The GUI, the network stack and the protocol don't fit together below `$C800`. They use
`lib/overlay.asm`: a resident core (network, deframer, framebuffer, mouse and event loop) plus
overlays for the widget renderer, file transfer and the updater, and later the games.

## Protocol

It runs over a single TCP connection (port 6400 by default). Each frame is `u16 length` (LE,
counting the type and the payload), `u8 type` and then the payload. Strings are `u8 length` +
ASCII. The authoritative list of messages is [`server-src/meganet/protocol.py`](../server-src/meganet/protocol.py).

- Server -> client (`$01`-`$7F`): build a window (`WIN_OPEN`, a `GADGET` for each gadget, then
  `WIN_DONE`, which tells the client to draw it), change gadgets (`SET_TEXT`, `SET_VALUE`,
  `LIST_ROWS`, `APPEND`, `FOCUS`), `MENU`, `ALERT`, `NOTIFY`, `PONG`, file transfer
  (`FILE_BEGIN/DATA/END`), resources, and `UPDATE`.
- Client -> server (`$80`-`$FF`): `HELLO`, `CLICK`, `VALUE`, `SELECT`, `LIST_NEED`, `MENU_PICK`,
  `WIN_CLOSED`, `KEY` (raw keys, only for gadgets flagged RAWKEYS: games), `FILE_ACK`,
  `NOTIFY_CLICK`, `TEXT`, `PING`.
- **Is the server still there?** `PING` (`$8F`, no payload) is answered with `PONG` (`$1C`, no
  payload), signed on or not. The client counts any frame from the server as a sign of life.
  Signed on, after 30 seconds with nothing from the server it sends `PING`; if nothing at all
  comes back within 10 seconds, its connectivity icon (a Wi-Fi fan at the very right of the
  menu bar) gets a red X, and it sends `PING` every 10 seconds until something arrives, which
  puts the plain fan back. Clicking the icon pings at once (`client-src/link.asm`). `PONG`
  doesn't count as the answer to a click (the hourglass stays until the real one).
- **New User sign-up:** `LOGIN` with flags bit 0 (new user) and an **empty** screen name and
  password starts the server's sign-up wizard (window 20) instead of answering at once. While
  it runs the session isn't signed on, but `CLICK`, `VALUE`, `SELECT`, `TEXT` and `WIN_CLOSED`
  for the wizard's window (and only that window) are handled; everything else is still ignored
  until sign-on. Cancel or the close box at any step closes the window and sends
  `LOGIN_RESULT` 0 "Sign-up cancelled."; the connection stays open, and another `LOGIN` (Sign
  On or New User) may follow. Accept creates the account and then sends `LOGIN_RESULT` 1, the
  normal sign-on (`MENU`, the welcome window, icons) and, last so it's in front, an `ALERT`
  "Welcome to MegaNet!". `LOGIN` with bit 0 and a non-empty name still creates the account
  directly (old clients, tests).
- Gadget kinds (`GADGET`'s `u8 kind`): 1 Label, 2 Button, 3 TextBox, 4 Password, 5 ListBox,
  6 CheckBox, 7 Radio, 8 TextView, 9 Progress, 10 Image, 11 Group, 12 DropDown, 13 Edit.
  - **DropDown (12)**, a drop-down list (combo box), 12 high. Its rows come in `LIST_ROWS` like
    a ListBox's: at most 128 rows of at most 63 characters, all sent after its `GADGET`.
    `SET_VALUE` sets the selection (the row index, `$FFFF` for none). The client draws the
    selected row's text and a down-arrow button 11 px wide at the right, so the text room is
    (w - 6 - 11) / 8 characters. When the user picks a row it sends `SELECT` (win, gid, index)
    at once.
  - **Edit (13)**, an editable multi-line text area: sunken white, with a scroll bar 11 px
    wide inside its right edge. Lines are (w - 6 - 11) / 8 characters (at most 63), and
    (h - 6) / 8 lines are visible. Initial contents: one `APPEND` per line, after its `GADGET`
    and before `WIN_DONE`; `SET_TEXT` with "" empties it. The client keeps at most 32 lines and
    wraps typing at the line width.
  - **`TEXT` (`$8B`)**: `u8 win`, `u8 gid`, `u8 n`, then n x `str` (the lines; trailing empty
    lines dropped). Before it sends a `CLICK`, the client sends a `TEXT` for every Edit gadget
    of that window, as it sends `VALUE` for text boxes.
- Window coordinates are relative to the screen, and gadget coordinates are relative to the
  window's client area.
- **The menu bar** (America Online / Windows 95 style) takes the top `MENU_BAR_H` = 11 pixel
  rows of the screen.
  - `MENU` (`$18`): `u8 n`, then n entries of (`u8 id`, `u8 parent`, `str label`). Parent 0
    is a title on the bar; otherwise it is the id of the title the item drops down from, in the
    order sent. A label of `-` is a separator line.
  - Each `MENU` **replaces** the whole server menu; `MENU` with n = 0 clears it. The server
    sends it after a good `LOGIN_RESULT` and again whenever the user's permissions change.
  - Ids 1-`$EF` are the server's, `$F0`-`$FF` the client's own: the client adds its own
    "Window" menu (the open windows, to switch between them) at the right end of the bar. The
    server never sends one.
  - `MENU_PICK` (`$85`): `u8 id`, sent when the user picks an item. Titles and separators are
    never picked. The server ignores an id that wasn't in the last menu it sent that session,
    and checks the item's permission again before acting on it.
  - **`$22` is My Account, on the client's own MegaNet menu** (its first item). The client sends
    `MENU_PICK $22` for it. The server never sends `$22` in `MENU` but always accepts it from a
    signed-on session (`protocol.MENU_MY_ACCOUNT`).
- **Menu-bar icons:** `NOTIFY` (`$1B`): `u8 slot` (0-6; clients before the newspaper had
  0-5 and ignore slot 6), `u8 icon`, `str hint`. The client draws a
  small icon button at the right end of its menu bar: slot 0 is the rightmost (just left of the
  client's own connectivity icon, which is always at the very end), slot 1 left of it, and so
  on; the icons shown are packed together with no gaps for empty slots. Icon 0 removes the slot's icon, 1 = page / alert (flashing, to get attention), 2 =
  mail / messages waiting, 5 = a person, 6 = a speech bubble, 7 / 8 / 9 = a green / yellow /
  dark grey dot, 10 = a newspaper (unread news) (3 and 4 are the client's own Wi-Fi icons). The hint is a short text (at most 40 characters) the client may show;
  the server always sends one.
  - `NOTIFY_CLICK` (`$8A`): `u8 slot`, the user clicked that slot's icon. The client doesn't
    remove the icon itself; the server sends `NOTIFY` icon 0 when it's done with it.
  - The server's slots: 0 = your status (always shown, so it sits right next to the
    connectivity icon), 1 = a user is paging the admins (admins only), 2 = messages from users
    to the admins (admins only), 3 = unread private messages, 4 = new users, 5 = instant
    messages (`protocol.SLOT_*`). It ignores a `NOTIFY_CLICK` for a
    slot it hasn't given that session an icon in, and checks the permission again.
- **WIN_OPEN's width and height are the client area**, the space for the gadgets. The client
  adds its own frame and title bar: `FRAME_W` = 8 more across and `FRAME_H` = 18 more down
  (`protocol.py`, matching `GUI_FRAME_W/H` in `lib/gui/gui.asm`). So the server never depends
  on how big the client's title bar is.
  - Windows stay below the menu bar. A window fits when x + w + 8 <= 640, y >= 11 and
    y + h + 18 <= 200, so the client area is at most 632x171 (`CLIENT_MAX_W/H`,
    `window_fits()`).
  - The client moves a window that doesn't fit up or left, and clamps it below the bar.
  - The server tests' fake client fails any window that doesn't fit, any gadget that sticks
    out of its window, and any malformed `MENU` (a client id, a duplicate id, a parent that
    isn't a title). It also checks the new kinds: a DropDown is 12 high with all its rows (at
    most 128, 63 characters each) sent at once and a selection in range; an Edit has room for
    a line, gets only lines that fit its width (at most 32), and `SET_TEXT` on it is always "".

## File transfers and local storage

Raw binary over the same TCP stream, in `FILE_DATA` chunks of up to 1 KB, with a CRC-32 at the
end. No XMODEM: TCP already makes the stream reliable.

The File Library (`server-src/meganet/filelib.py`) runs every window on the server. The client
(`client-src/storage.asm`) only does what needs its own disks, when the server asks:

- **What the client can do** comes in `HELLO`'s caps byte (`protocol.Caps`): bit 0 drives 8-11
  (PRG, SEQ, USR through the KERNAL), bit 1 reading the SD card (folders, D64 / D81 images),
  bit 2 writing images to the SD card. The server only offers what the caps allow.
- **Devices:** `dev` 8-11 is a CBM drive unit; `dev` 0 is the SD card. An SD path is folder
  names from the root joined by `/`, with the file's 8.3 name last (`GAMES/ELITE.D81`). The
  client matches each part against the 8.3 names HYPPO's `readdir` gives, so long names in
  any case work.
- **Requests** carry a `u8 req`; every reply carries it back, and the server drops replies to
  requests it has given up on. `LOCAL_CANCEL (req)` stops one.
- **A directory:** `LOCAL_DIR (req, dev, path)` -> a `LOCAL_ENTRY (req, kind, u32 size, str
  name[, str long name])` per entry, then `LOCAL_DONE (req, status, str text)`. On a drive,
  the size is in blocks, and the disk name (`HEADER`) and the blocks free (`FREE`) come as
  entries too. On the SD card, the size is in bytes and the long file name follows.
- **A download:** `SAVE_BEGIN (req, dev, kind, u32 size, path)`. The client checks the device
  answers and that no file of that name is there (**saves never overwrite**), then answers
  `FILE_ACK 0`, or `LOCAL_DONE` with the problem. The server then sends `FILE_DATA`, keeping
  at most `FILE_WINDOW` (4 KB) beyond the client's last `FILE_ACK`, and `FILE_END (crc)`. The
  client stages it in attic (`$8300000`, at most `LOCAL_MAX` = 1 MB), keeps the CRC as it
  comes, checks it, writes the file and answers `LOCAL_DONE`.
- **An upload:** `LOAD_FILE (req, dev, kind, path)`. The client reads the file into attic and
  sends `UP_BEGIN (req, u32 size)`, then `UP_DATA (req, bytes)` of at most 240 bytes, a few
  frames each main-loop pass so the GUI keeps going, then `UP_END (req, crc)`. If it can't, it
  answers `LOCAL_DONE` instead.
- **Statuses** (`protocol.LocalStatus`): OK, NO_DEVICE, NOT_FOUND, EXISTS, DISK_FULL, BAD_CRC,
  IO_ERROR (the drive's own message is the text), UNSUPPORTED, TOO_BIG, CANCELLED.
- **The SD card** is read through HYPPO (`opendir`/`readdir`/`chdir`/`openfile`/`readfile`).
  HYPPO can't write files (`mkfile`, `writefile` and `rmfile` are documented as not
  implemented), so images are written by the client's own FAT32 code with raw sector writes
  (`client-src/sdwrite.asm`): new files only, in one contiguous run of clusters so HYPPO can
  mount them, both FATs, an 8.3 entry, every metadata sector read back. Tested in Xemu
  against the real HYPPO and a scratch card image, not yet on a real card.

The forced update (below) uses `FILE_BEGIN` instead of `SAVE_BEGIN`.

## Forced auto-update

1. `HELLO` carries the client's **build number** (`u16`), stamped in by `build.bat`.
2. The server compares it with `server-src/updates/manifest.json`. If the client is older, it
   sends `UPDATE` (new build, number of files, message) instead of the sign-on screen, then each
   file as `FILE_BEGIN/DATA/END`.
3. The client shows a progress window, stages every file in attic, checks each CRC, and only
   then writes them to disk.
4. To make writing safe, the disk holds a tiny **stub** (`MEGANET`, run by `AUTOBOOT.C65`) that
   loads the real client (`CLIENT`) and its overlays. The updater replaces only `CLIENT` and the
   overlays, never the stub. It writes each file under a temporary name, scratches the old one,
   then renames the new one (DOS command channel). A dropped connection or a power cut therefore
   leaves the old version or the new one, never half of each. Afterwards it restarts through the
   stub.
5. Publishing an update: build, copy the client files into `server-src/updates/`, and bump
   `build` in the manifest. Every client that connects after that is updated before it can sign on.

## Server

- **Python 3.11 or later, standard library only** (asyncio, sqlite3, hashlib, json, zlib,
  unittest), so anyone can run it and hack on it without installing anything. Run it with
  `python -m meganet` in `server-src/` (`--port`, default 6400; `--db`; `--updates`;
  `--motd FILE`).
- **Storage: SQLite** (`sqlite3`), a single file, `server-src/data/meganet.db` by default,
  created on first run. Users (PBKDF2-SHA256 password hashes with a salt) are in use; boards,
  messages and files have stub tables. IMs, news and chat logs come later.
- **Roles and permissions:** every user has one role (`users.role_id`); a role is a set of
  permission keys (`role_permissions`) from a registry in `meganet/permissions.py` that
  features and game plugins add to (`permissions.register(key, description, like=...)`).
  Defaults: New User (chat, games, read boards and news), Member (also post, download, IMs),
  Moderator (also moderate chat and boards), Sysop (everything, including `admin.users`,
  `admin.roles` and `admin.motd`). The first account becomes Sysop; later ones get the default role (a setting).
  The server never lets the last user with `admin.roles` lose it. `session.can(key)` is cached
  per session and refreshed, with the menu bar, when an admin changes that user's role or the
  role. The menu bar offers only what the user may do, and every handler checks again on the
  server. The Roles and Users windows (`meganet/admin.py`) are built from the ordinary gadgets.
- **Menu bar instead of a main-menu window:** after sign-on the server sends `MENU` with
  Areas (News, Message Boards, Chat Rooms, Private Messages, Art Gallery, SID Music, File Library, Games), Members (Who's
  Online, User Search), Admin (right of the client's Window menu: User Editor..., Roles..., Message of the Day..., Terms of Service..., Messages from users...; only with `admin.*`)
  and Help (About MegaNet, Getting Around, Page Admin), each
  item filtered by `session.can()` and a title left out when it has no items left. The tree is
  `MENU_TREE` in `screens.py`; `ui.Menu` builds and sends it, and checks picks against it.
- **Welcome window and message of the day:** after sign-on a closable welcome window, centred
  on the screen below the menu bar (`ui.centre` / `Window.centred`: x = (640 - (w + 8)) / 2,
  y = 11 + (189 - (h + 18)) / 2), shows the user's role and the **message of the day** in a
  read-only TextView (400x100) with a scroll bar. The server sends one APPEND per line and the
  client wraps it (47 characters a line), so each line is a paragraph. The message is a server
  setting (`settings` key `motd`, a JSON list of at most 64 ASCII lines), with a short default
  on a new database. Sysops change it on the PC (`--motd FILE` loads a text file at start) or
  on the MEGA65 with Admin > Message of the Day... (`admin.motd`), a line editor (written before the
  client had the Edit gadget): a list of the lines (rows cut to "nn " + 27 characters),
  a 63-character text box for the picked line, Replace / Insert before / Add at end / Delete,
  Preview (the welcome window as users see it), Save and Cancel. Edits stay on the server until
  Save; open welcome windows aren't updated, users see the new message at their next sign-on.
- **Page Admin** (Help menu, `meganet/pages.py`): with an admin (`admin.pages`, Moderator and
  Sysop by default) signed on, the user waits in a "Paging an admin..." window (Cancel withdraws
  it) and every admin gets the flashing page icon (NOTIFY slot 1; "3 users are paging" when
  several wait). The first admin to click it takes the oldest page; both get a private chat
  window (dynamic window ids). Closing either side ends the chat. With no admin on (or when the
  last one leaves), the user may leave a message instead (`admin_messages` table); admins get the
  mail icon (slot 2) while unread ones wait, and read and delete them in Admin > Messages from
  users. Getting Around (Help) is a placeholder help text for now.
- **Private messages** (Areas, `mail.use`, everyone by default; `meganet/mail.py`): an inbox and a
  Sent folder (list + TextView), New / Reply / Delete, and a composer: To, Subject, the body in an
  editable text area (Kind.EDIT), Send and Cancel. Send closes it and shows a "Message Sent"
  box (`meganet/compose.py`, shared with the message to the admins and meant for the message
  boards). Stored in `private_messages`,
  kept until both sides delete it. Unread mail shows the envelope icon (slot 3), also at sign-on.
- **Message boards** (Areas, `boards.read`; `meganet/boards.py`): forums > topics > posts in
  one window with three views; "new" = since the previous sign-on. `boards.post` and the
  forum's per-role Read / Post access decide who writes. Moderators (`boards.moderate`) create,
  rename, delete, lock and set the access of forums, and delete topics and posts, from the same
  window.
- **Status and instant messages** (`meganet/presence.py`, `meganet/im.py`):
  - A Status menu (Available / Away / Offline) and Auto-Away after idle minutes (Admin >
    System Settings).
  - A status dot on the menu bar, just left of the connectivity icon: green Available,
    yellow Away, dark grey Offline. Clicking it toggles Available / Away.
  - Who's Online shows statuses; Offline users only show to admins.
  - Instant messages arrive as a toast at the bottom right (`S.TOAST` `$1E`, drawn by the
    client over everything, taking no input) plus a speech-bubble icon, never a window that
    steals the keyboard.
- **Voting** (`meganet/polls.py`): polls set up by moderators, one vote each, a bar graph
  of the results (Progress gadgets), and an optional end date after which only the results
  show.
- **Chat rooms** (`meganet/chat.py`): one room at a time. There are permanent rooms
  (moderators) and member rooms (`chat.rooms`, gone when empty); either kind can be private.
  Moderators kick, mute, ban, unban, set the topic and give Karma +/-.
- **Karma Points** (`meganet/karma.py`): 0-100 per user. New users start Low, and points come
  slowly for posting and chatting without incident. Moderators and incidents take them away,
  and admins are alerted at 10 or below. Admins see and set them, with their history, in the
  User Editor.
- **Windows and dialogs** follow one set of rules (see `server-src/README.md`, "Windows and
  dialogs"):
  - every window has a close box (only the Connect and Sign On screens don't);
  - work windows have no Close button;
  - dialogs end in `[Command] [Cancel]`, centred in message boxes and bottom right in forms;
  - buttons are at least 72 wide; "..." marks a button that opens a dialog;
  - a button that can't act yet (nothing picked) is greyed out: `S.SET_FLAGS` (`$1D`: win,
    gid, flags) changes a gadget's flags after the window is open;
  - every area window has one layout (`ui.AreaWindow`, 560 x 160): a heading, the list on
    the left (with the picked item under it), a column of commands on the right with the
    main one first and Admin Tools last, only for those allowed, and a status line.
- **New users** (admins with `admin.users`): a black pawn icon (slot 4, icon 5) while anyone is
  still in the default role; a click opens Admin > User Editor at the oldest one.
- **My Account** (the client's MegaNet menu, `MENU_PICK $22`; `meganet/account.py`): a centred
  form (388x171) with labels in one column and fields in another: Username (with "Role: ..."
  beside it), First Name and Last Name (required: letters, spaces, ' - and ., up to 20
  characters), Email Address and Location (63-character text boxes, 260 wide, that scroll), Birthdate (Month, Day and Year
  drop-downs, each with "--" = not set; stored as YYYY-MM-DD or empty), About Me (an Edit area
  showing 3 lines of 30 characters, up to 8 lines kept), Last Login (the previous sign-on);
  a status line; Reset Password at the bottom left (a modal dialog: current,
  new and confirm; three wrong tries close it), OK (default: checks the names, the email, the date and the
  About Me length, saves and closes, or stays open with the problem in the status line) and
  Cancel (closes without saving) at the bottom right. New `users` columns (first_name, last_name, email, location,
  birthdate, about, last_login) are added to older databases with ALTER TABLE; an About Me
  saved by the older three-box form is kept and shown wrapped to the area's width.
- **Object model that mirrors the client's GUI** (`meganet/ui.py`): the server builds `Window`
  objects out of `Gadget` objects (`Button`, `Label`, `TextBox`, `Password`, `ListBox`,
  `DropDown`, `TextView`, `TextArea` (Edit), `CheckBox`, `Radio`, `Progress`...) with
  `on_click` / `on_select` callbacks.
  Since a TextView only appends, a window that shows another document (a picked message) is
  sent again. A
  window sends itself (WIN_OPEN, each GADGET followed by its initial contents such as list rows,
  then WIN_DONE), keeps the client's VALUE updates per gadget (`gadget.value`; an Edit's TEXT
  lines in `gadget.lines`, a DropDown's selection in `gadget.selected`), and closes itself.
- **Sign-on:** after HELLO the server answers HELLO, then either forces the update or waits for
  `LOGIN` (flags bit 0 = new user, name, password) and answers `LOGIN_RESULT`. The client draws
  its own sign-on window. Window ids `$F0`-`$FF` are the client's; the server uses 1-`$EF`.
- **New User wizard** (`meganet/signup.py`; started by a new-user `LOGIN` with no name): one
  centred, modal window (id 20, 448x152) sent again for each of six steps, each with "Step n
  of 6", a status line and Back / Next (default) / Cancel at the bottom right: 1 screen name
  (checked with `db.check_new_name`, not taken in any case, not held by another session's
  wizard), 2 password and confirm (`db.check_new_password`, must match), 3 about you (optional:
  Birthdate drop-downs, Location, Email, with My Account's checks), 4 About Me (optional: an
  Edit area as wide as My Account's, all 8 lines visible), 5 review (every value on labels, the
  password as stars), 6 the Terms of Service (the Sysop's text, edited in Admin > Terms of
  Service...; a check box "I have read and agree", OK greyed out until it's ticked). Values stay
  on the server between steps, so Back shows them again; Next checks its step and OK checks them
  all again. A name is held from a good step 1 until the wizard ends. OK: the account (default
  role; the first account is Sysop) with its profile and when they agreed to the Terms, an `admin_messages` entry "New user" from the new user ("<name> has
  just signed up. Please check their access (Admin > User Editor).") and the admins' envelope icons
  (skipped for the first account), then the sign-on and the welcome alert ("Account set up! An
  admin has been told and will upgrade your access.").
- Modules (`server-src/meganet/`): `protocol.py` (framing and message numbers), `ui.py`,
  `session.py` (one per connection), `server.py` (listener and shared state), `db.py`,
  `permissions.py`, `screens.py` (menu bar, welcome, Who's Online, Getting Around, chat lobby),
  `admin.py` (Roles, Users and Message of the Day windows), `account.py` (My Account),
  `signup.py` (the New User wizard),
  `pages.py` (Page Admin), `mail.py` (private messages), `compose.py`,
  `updates.py`, and `games/`.
- **Games are plugins:** each module in `meganet/games/` with a `Game` subclass (name,
  description, min/max players; hooks `start`, `on_click`, `on_select`, `on_key`, `on_leave`,
  optional `tick`) is found at start-up and listed in the Games window, which also matches
  waiting players. Tic-tac-toe, built only from buttons, is the example
  (`meganet/games/README.md`). A game with `challenge = True` gets a lobby instead
  (`games/challenge.py`): players wait there, pick an opponent and challenge them.
- **Chess** (`games/chess.py`, rules in `chess_rules.py`): the lobby, then a window with the
  board (a `GRID` gadget, 8 x 8 tiles of 32 x 16 pixels sent once a connection to resource
  slot 1), ranks and files from your own side, two status lines, a chat with the moves in it,
  Offer Draw / Resign / Rematch / Lobby. Every rule is enforced: castling, en passant,
  promotion (a dialog), check, checkmate, stalemate, and the automatic draws (insufficient
  material, fifty moves, threefold repetition). No clocks yet.
- **One** (`games/one.py`, rules in `one_rules.py`, cards in `one_art.py`): the card game for
  2-4 by the usual official rules (Wild Draw Four challenges, calling One!, scoring to 500).
  Join asks "Wait for Others" (the queue) or "vs Computer..." (1-3 computer players, played
  by `tick()`); a player who leaves is replaced by the computer. The table: two `GRID`s (the
  piles; the hand, 12 x 2 cards of 32 x 22, 64 tiles in resource slot 8), the others' card
  counts in play order, the play-by-play and chat. Cards played and drawn fly between the
  hand, the rows and the piles (below).
- **Texas Hold'em** (`games/poker.py`, rules in `poker_rules.py`, art in `poker_art.py`):
  no-limit poker for 2-6 played for the bank's credits. The table is one `GRID` (13 x 5
  tiles of 32 x 22 in resource slot 9: a green felt stadium with a wooden rail, 35 distinct
  tiles); cards, the dealer button and the pot's chips are drawn onto the cell's own felt
  tile and sent to each viewer as needed (`session.send_resource_at`, a per-viewer
  `TileCache` in tiles 35-63: a full table needs 24), so everyone sees their own cards face
  up and the others' face down. Items are placed in table pixels and may span two tiles
  (`poker_art.compose` draws each tile's part). You sit at the bottom in the middle, the
  others clockwise, three seats along each long side; their labels are above and below the
  table, and the chat panel is at the right (a `TextView` with the dealer's lines, a
  `TextBox` with Send as the default button). Cards are dealt one at a time as sprites from
  the dealer button.
- **The bank** (`bank.py`): `users.credits` and the `credit_log` ledger; earning
  (`Bank.earn`, daily limits, called by games through `Game.credit`), gifts, loans, Areas >
  Bank, Admin > Bank Settings.
- **The server's sprites** (`Caps.SPRITES` clients, `client-src/sprites.asm`, built on
  `lib/hwsprite.asm` `hws_from_bitmap`): `S.SPRITE` (`$32`: `u8 n, u8 win, u8 slot, u16
  offset, u8 w, u8 h, u16 stride, u8 step, u16 x, u8 y, u8 c, c x (u8 colour, r, g, b)`) makes
  server sprite n (0-1: hardware sprites 6-7) from any picture in a resource slot (w pixels
  up to 16, `step` bytes apart; h rows up to 64, `stride` apart; the c colours listed, the
  rest see-through) at (x, y) in a window's client area wherever the window is now.
  `S.SPRITE_MOVE` (`$33`: `u8 n, s16 dx, s16 dy, u8 frames, u8 hide`) glides it (8.8 fixed
  point, the fraction starting at a half so it ends to the nearest pixel), then hides it if
  asked; `S.SPRITE_OFF` (`$34`: `u8 n`, `$FF` both). The sprites' colours go into palette
  bank 1 (with the GUI's, for the pointer), so the screen's never change; the two share the
  tall-sprite height (the taller one's: rows past a sprite's own are see-through). The server
  holds back what a flying card covers (the pile, the cell) until it lands (`session.fly`,
  `games/one.py`).
- **Overlays** (`client-src/overlays.asm`, `lib/overlay.asm`): the File Library's disk and
  SD-card code (`storage.asm`, `sdwrite.asm`: OVL0) and the Art Gallery's pictures and Paint
  (`picture.asm`, `canvas.asm`: OVL1) live in attic and take turns in one window
  (`OVL_BASE`-`$CFFF`, `$CCFF` in the bridge build), reached through `#FAR` stubs; the
  variables the resident part reads (`st_mode`, `pic_on`) are resident.
- **Internet** (`meganet/internet/`): Areas > Internet lists integrations, plugins found at
  start-up like games. The first is a text Web Browser: the server fetches pages (never on a
  private network), turns HTML into wrapped ASCII with numbered links, and shows it in a
  TextView with the links in a ListBox. Later: forms, then a rendered-page viewer (a
  headless browser's screenshots in an attic viewport, clicks sent back). The second is News
  Feeds (`internet/feeds.py`): RSS / Atom (`feedparse.py`) fetched the browser's way, a
  three-pane reader (feeds, stories, the picked story's summary), Open in Browser.
- **Grids and resources** (`Caps.GRID` clients): `S.RESOURCE` (`$30`: `u8 slot, u16 offset,
  bytes`, at most 1024) fills one of 16 attic slots of 64 KB; a `GRID` gadget (kind 14; its
  text is 7 bytes, each + 1: cols, rows, tile w, tile h, slot, mark colours 1 and 2) shows
  tiles from a slot; `S.CELLS` (`$29`: `u8 win, u8 gid, u8 first, u8 n, n bytes`) sets its
  cells (bits 0-5 the tile, bit 7 / 6 a frame in mark colour 1 / 2). A click on a cell sends
  `C.SELECT` with the cell number. Palette entries 240-254 are fixed game colours
  (`protocol.GAME_COLOURS`) for the tiles.
- **Art Gallery** (`meganet/gallery/`): galleries (moderators make, edit and delete them) of
  IFF pictures, uploaded from a drive. The server reads the IFF (ILBM or PBM, 1-8 planes,
  EHB, HAM6/8 cut to 255 colours), fits it to 320x200 (shown doubled across) or 640x200,
  and puts the pixels in the client's framebuffer order, so the client only copies them in
  (`client-src/picture.asm`, a few hundred bytes). View shows one; Slideshow goes on with
  Space and sends the next picture while one shows.
- **Pictures** (`Caps.PICTURE` clients): `S.RESOURCE_PACKED` (`$2C`) is `S.RESOURCE` with
  PackBits bytes; `S.PICTURE` (`$2A`: `u8 slot, u8 mode, u8 border, u8 n, n x rgb`) shows the
  slot's pixels over the whole screen with that palette, while the GUI is held (it takes
  messages but draws nothing); keys and clicks go back as `C.PIC_KEY` (`$93`), and
  `S.PICTURE_END` (`$2B`) brings the desktop back. In Full Colour Mode a pixel of 0 shows
  `$D021`, so the client keeps that at 0 (palette entry 0) and puts the border colour only
  in `$D020`.
- **Paint** (`gallery/paint.py`, `client-src/canvas.asm`; `Caps.CANVAS`): the server keeps
  the picture and paints; the client's desktop shows it. `S.CANVAS` (`$2D`: slot, colours)
  hides the open windows and the menu bar and puts the picture (slot 6, lores framebuffer
  order, palette entries 16 on) behind everything (`gui_desk_hook`); the mouse on it goes
  back as `C.CANVAS` (`$94`: event, x, y in picture pixels); `S.CANVAS_RECT` (`$2F`) brings
  the changed pixels (PackBits rows); `S.CANVAS_PEN` (`$31`) says what to draw at once while
  the button is held (a freehand stroke, or a line's or box's outline: Bresenham, the same
  on both sides), so drawing doesn't wait for the network. `S.CANVAS_END` (`$2E`) gives the
  desktop back. The tool window is an ordinary server window over the picture.
- `tests/` (`python -m unittest`) runs a real server on a random port with fake clients over
  TCP: sign-on, the menu bar, the lobby, a tic-tac-toe match, the forced update, roles and
  permissions, the message of the day, Page Admin, private messages, My Account, the New User
  wizard, and the deframer. A test
  client like this is how the server is developed without a MEGA65.

## Testing the client

- **Xemu's Ethernet emulation needs a TAP device, and (to be checked) it may only work on Linux
  builds.** If it doesn't work on this Windows machine, the client gets a **debug transport**:
  received frames come from a buffer that the harness pokes over uartmon, and sent frames go to a
  buffer the harness peeks. The GUI and protocol can then be tested headless in Xemu without a
  network. mega-ip's own Python simulator (`mega-ip/tools/sim`) covers the TCP side.
- Real hardware is the final test for networking.
