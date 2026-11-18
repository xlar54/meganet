# MegaNet TODO

## Client (client-src/, 45GS02 assembly)
- [x] 640x200 FCM desktop, two-sprite mouse pointer
- [x] GUI library `lib/gui/`: windows (overlap, z-order, drag, close box, modal), buttons, labels,
      text and password boxes, focus, TAB, RETURN = default button; Win95 look
- [x] Sign-on screen: logo, screen name / password / server address, Sign On and New User;
      fields checked, IP parsed (tested in Xemu with injected keys and clicks)
- [x] Network (`net.asm`): eth.bin at $42000 through a MAP trampoline (weather65's method),
      DHCP, connect to login_ip:6400, polled ~5 times a frame from the main loop
- [x] Protocol (`proto.asm`): HELLO, LOGIN, LOGIN_RESULT, windows, gadgets, SET_TEXT,
      SET_VALUE, FOCUS, ALERT, WIN_DONE, LIST_ROWS, APPEND -> gui; CLICK (with VALUE for the
      window's text boxes first), SELECT, WIN_CLOSED, KEY -> server
- [x] Replay build for Xemu (`build.bat mock FILE`, `private/tools/record_mock.py`): sign-on,
      main menu, lobby, chat and list selection tested; the sent bytes match the recording
- [ ] **Test the real network on a MEGA65** (Xemu has none): DHCP, connect, sign-on, chat
- [ ] On a lost connection mid-session: tested only in code reading (login_lost)
- [x] GUI: list box (select, double-click), text view (word wrap, 64 lines)
- [x] GUI: menu bar with drop-downs (server's MENU / MENU_PICK; the client's own Help menu at
      sign-on), built-in Window menu to switch windows; windows kept below the bar
- [x] MegaNet menu (client's own, first on the bar): Exit with a confirm, back to BASIC's
      READY (tested in Xemu); no menu bar on the sign-on screen
- [ ] Test Exit to BASIC on real hardware (CHARPTR / ROM restore differ there)
- [ ] GUI: toolbar of icon buttons under the menu bar (quieter than AOL's: small 16-colour
      icons with labels, flat buttons that bevel when pressed); icons sent once as RESOURCE
      and cached in attic
- [ ] GUI: scroll bars, check box, radio, progress bar
- [x] GUI: minimize (a title bar along the bottom; Who's Online has it)
- [ ] GUI: maximize / resize (gadgets anchored to edges); drag outline
- [ ] GUI: proportional font, focus rectangle
- [ ] Remember the server address and screen name (kfile)
- [ ] Overlay layout once the program nears $C800 (resident core + GUI/file/updater overlays)
- [ ] Stub loader `MEGANET` -> `CLIENT` + overlays; build number stamped by build.bat
- [ ] Updater: stage in attic, check CRCs, write under temp names, scratch, rename, restart
- [ ] File download to disk via kfile
- [ ] Copy lib/gui into the project template (see private/CLAUDE.md) once it settles

## Server (server-src/, Python)
- [x] Port from Node to Python (stdlib asyncio + sqlite3), LOGIN / new user, game plugins with a
      tic-tac-toe demo; unittest tests with fake clients over TCP
- [x] User roles with admin-editable permissions (`permissions.py`, `admin.py`): first user is
      Sysop, Roles and Users windows, `session.can()` enforced on the menu, lobby and games
- [ ] Check the role permissions in the boards, news, files and IM areas as they're written
      (`boards.post`, `boards.moderate`, `chat.moderate`, `news.post`, `files.upload`, `im.send`)
- [x] Menu bar (MENU / MENU_PICK) instead of the main-menu window: Areas, Members (Who's
      Online, My Account), Admin, Help; filtered per role, re-sent on role changes, picks
      re-checked; windows kept below the 11-row bar (client area at most 632x171)
- [x] Message of the Day: server setting (`motd`, JSON lines), `admin.motd`, centred welcome
      window with a read-only TextView of it, Admin > Message of the Day... line editor
      (Replace / Insert before / Add at end / Delete / Preview / Save / Cancel), `--motd FILE`;
      `ui.centre` / `Window.centred` for centred dialogs
- [ ] Check the welcome (416x134) and Message of the Day editor (544x158) layouts on the real
      client, with its scroll bars; centre the other dialogs too (`Window.centred`)
- [ ] Check the Roles and Users window layouts on the real client and adjust sizes
- [x] NOTIFY / NOTIFY_CLICK menu-bar icons (`session.set_notify`; slots 0 pages, 1 admin
      messages, 2 private mail; clicks only for slots shown, permission re-checked)
- [x] Help > Getting Around (placeholder text) and Page Admin: `admin.pages`, page icon to every
      admin, first click takes the oldest page, private chat (dynamic window ids), Cancel, queue,
      fall back to "leave a message" when no admin is on; `admin_messages`, Admin > Messages
      from users ($33)
- [ ] Write the real Getting Around help (and maybe a help browser)
- [ ] Page Admin: show which admin is answering in the paging window; log the chats?
- [x] Areas > Private Messages (`mail.use`): inbox / Sent folder, compose in a text area,
      reply, delete per side, envelope icon (slot 2) at sign-on and on arrival
- [ ] Private messages: address book / pick a recipient from a list; size limits per user
- [x] My Account redesign (client menu, MENU_PICK $22): profile fields (email, location,
      birthdate, about, last login), validation, Reset Password with a retry limit
- [x] DropDown (kind 12) and Edit (kind 13, C.TEXT $8B) gadgets (`ui.DropDown`, `ui.TextArea`);
      My Account relaid out with them: 388x171, half-width Email / Location, Month / Day / Year
      drop-downs, an 8-line About Me area, Reset Password / OK / Cancel
- [x] New User sign-up wizard (`signup.py`, window 20; LOGIN new-user with no name): screen
      name (held while signing up), password, about you, about me, review; Back keeps values;
      Accept creates the account, tells the admins (admin message + envelope) and signs on
      with a welcome alert; Cancel / close box = LOGIN_RESULT 0 "Sign-up cancelled."
- [ ] Check the sign-up wizard layout (448x152) on the real client; a max-length for text
      boxes in GADGET would let the screen-name box stop at 10 characters
- [ ] Use Edit areas for the message composer and the Message of the Day editor (now a line at
      a time)
- [ ] Check the My Account (388x171), inbox (600x160), composer (544x152) and chat (360x140)
      layouts on the real client
- [ ] Screen-wide handlers; FOCUS after windows open
- [ ] More games for meganet/games/ (and a real-time one using RAWKEYS + tick())
- [x] Areas menu: News, Message Boards, Chat Rooms, Art Gallery, SID Music, File Library,
      Games; Members > User Search (name contains, any case; * = signed on now)
- [ ] **Art Gallery** (`gallery.view`, `gallery.upload`): a list of pictures with title and
      artist; viewing sends the image to the client, which shows it full-screen in the FCM
      framebuffer and returns to the desktop on a key or click. The client decodes IFF ILBM
      (ByteRun1) itself, starting from deluxepaint65's `ovr-iff.asm`. Upload: pick an IFF
      file on the MEGA65's disk (kstream), send it in FILE_DATA chunks, and have the server
      check and store it. The server could also convert PNG/GIF uploads from a web page later.
- [ ] **SID Music** (`music.listen`, `music.upload`): stream it as SID register frames, about
      25 bytes per 1/50 s frame, about 1.3 KB/s, which mega-ip carries easily. The server runs
      the tune's own 6502 player code in an emulated 6502 (Python) and sends the SID writes
      for each frame. The client buffers about 1 s and writes them to the real SID from its
      frame IRQ, so the MEGA65's own SIDs play it, with no PCM and no tune code on the client.
      Upload: .sid (PSID) files.
- [x] Message boards (`boards.py`): forums > topics > posts, new since the last sign-on,
      moderator New / Rename / Delete / Lock / per-role Access, Delete Topic / Post
- [ ] Message boards: try the window (560x160) on the real client; edit your own posts; more
      than 6 roles in the Access window; quoting in replies; a forum description; sticky topics
- [x] Chat rooms (`chat.py`): room list, permanent / member / private rooms, one at a time,
      moderator kick / mute / ban / unban / topic; Karma Points (`karma.py`) with automatic
      gains, losses, admin alerts, User Editor karma, Low Karma list and History
- [ ] Chat: whisper / instant messages; ignore a user; bans that survive a restart; karma
      shown somewhere for users themselves (My Account?)
- [x] Status menu (Available / Away / Offline), Auto-Away (Admin > System Settings), Who's
      Online with statuses (Offline only for admins), instant messages with a toast and the
      speech-bubble icon
- [x] System Settings: whether New Users can send and receive instant messages
- [x] Page Admin: a chime (S.SOUND, the SID) with the flashing icon
- [ ] IM: a sound for the toast (S.SOUND is there now); an "ignore" list; history after sign-off
- [x] Desktop icons from the server (Chat, Message Boards), with a "One moment..." progress
      window while they arrive at sign-on
- [x] Desktop icons for the File Library and Games; Admin > Broadcast... (the bottom row,
      yellow on red, for everyone)
- [x] Desktop icons down the right edge (slots 8-11): Who's Online, News, Voting
- [ ] Desktop icons: Private Messages; outlines that show on the black desktop; keyboard
      selection; dragging them
- [x] Areas > Voting: polls with a question, a description, 2-6 choices and an end date;
      one vote each; Results as a bar graph
- [ ] Voting: hiding results until you've voted (an option per poll);
      editing a poll before anyone has voted
- [x] Areas > News: bulletins; news.post writes, edits and deletes them in the composer;
      "new news, read it now?" after the welcome window
- [ ] News: a notify icon when a bulletin is posted while you're on
- [ ] File library
- [ ] Pace FILE_DATA by FILE_ACK
