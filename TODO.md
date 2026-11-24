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
- [x] Live desktop (`desk.asm`, `livedesk.py`): ticker, Online now line, icon badges (tested
      in Xemu through the bridge: drawn, scrolling, hidden under a window)
- [ ] Live desktop next: shimmer the logo's stripes (palette cycling), smooth 1-2 pixel
      ticker scrolling (check the speed on real hardware), a "today" panel under the logo
- [x] Released as client 2.1 (build 3): older clients ignore the messages
- [x] Connect window: DHCP or Static IP (the Static Address window: IP, mask, gateway, DNS;
      tested in Xemu through the bridge, which has no stack of its own)
- [ ] Static IP on a real MEGA65 (mega-ip restarted with the addresses); keep the addresses
      on disk between sessions
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
- [x] Client updates (2026-11-22, branch client-update): client-src/VERSION (build, oldest)
      compiled in and put on the disk; a newer D81 in the server's filelibs/meganet_client/
      ("MegaNet Client" library) is offered to older clients before they sign on: Download
      (to the SD card as MEGANE21.D81 (MEGANET cut short with the version's digits), by the File Library's download) and Later, or
      Disconnect when too old. deploy.ps1 -PublishClient. Tried in Xemu: the offer window
- [ ] Update in place (no remounting): write the files to the running disk under temp
      names, scratch, rename, restart; needs new client code (a DOS command message)
- [x] File download to disk (storage.asm, through kstream rather than kfile)
- [ ] Faster transfers: a D81 took about 15 minutes each way on the live server (upload
      2.3 KB/s, download 4.4 KB/s). The server now quick-ACKs (2026-11-22). The vendored
      mega-ip (client-src/mega-ip) now has a 2 KB send ring with a sliding window, Nagle's
      rule, single bytes sent at the next poll, the MSS option (1460) on SYN/SYN-ACK and a
      2,920-byte receive window (two full frames). On mega-ip's simulator at 100 ms RTT:
      upload 2.0 -> 16 KB/s, download 10 -> 29 KB/s. Not yet tried on a MEGA65; once it
      works, copy it to the mega-ip repo with its tests (private/temp/megaip_upstream/)
      and update mega-ip's README (ML send byte, window, the zero-window limitation)
- [ ] Copy lib/gui into the project template (see private/CLAUDE.md) once it settles

## Server (server-src/, Python)
- [x] Port from Node to Python (stdlib asyncio + sqlite3), LOGIN / new user, game plugins with a
      tic-tac-toe demo; unittest tests with fake clients over TCP
- [x] User roles with admin-editable permissions (`permissions.py`, `admin.py`): first user is
      Sysop, Roles and Users windows, `session.can()` enforced on the menu, lobby and games
- [x] Check the role permissions in the boards, news, files and IM areas as they're written
      (`boards.post`, `boards.moderate`, `chat.moderate`, `news.post`, `files.upload`,
      `files.moderate`, `im.send`)
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
- [x] NOTIFY / NOTIFY_CLICK menu-bar icons (`session.set_notify`; now slots 1 pages, 2 admin
      messages, 3 private mail; clicks only for slots shown, permission re-checked)
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
- [x] Chess (2026-11-19): a lobby to pick an opponent (games/challenge.py, any 2-player
      game can use it), a GRID board with tiles in an attic resource slot (client
      lib/gui/grid.asm, S.RESOURCE, S.CELLS, Caps.GRID), every rule enforced (perft-checked),
      chat, promotion, draw offers, resign, rematch. Played in Xemu against a fake client:
      the board, moves both ways, move dots and frames, chat
- [ ] Chess: clocks (a time control picked in the challenge); a move list to scroll back;
      Tic-Tac-Toe could use the lobby too; spectators; saving finished games (PGN)
- [ ] Chess: not tried in Xemu yet: a capture, castling, the promotion dialog, Offer
      Draw / Resign / Rematch / Lobby (all covered by the server tests with fake clients)
- [x] One (2026-11-20): the card game for 2-4 by the official rules, Wait for Others or vs
      Computer (1-3), cards as GRID tiles (sent packed). Tried in Xemu: Join's question,
      the table and the cards, the computer's move. Server tests cover every rule, the
      dialogs, One! / Catch!, scoring and leaving
- [x] One's cards fly (2026-11-20): first S.FLY, then (2026-11-21) the general server
      sprites: S.SPRITE / SPRITE_MOVE / SPRITE_OFF, Caps.SPRITES (client sprites.asm on
      lib/hwsprite.asm hws_from_bitmap, also in the template). Tried in Xemu: drawn cards in
      flight on both sprites
- [x] Overlays (2026-11-21): the File Library's disk and SD code (OVL0) and the Art
      Gallery's pictures and Paint (OVL1) in attic, one window (client-src/overlays.asm).
      Tried in Xemu: a download to drive 8, an upload from it, Paint (a box, Done, Leave),
      a picture shown. Not tried: the SD card paths since the move (filessd*, filesd64)
- [ ] Sprites: use them for chess (the piece glides along its move; a piece follows the
      pointer while dragged)
- [ ] One: not tried in Xemu yet: playing a card yourself (and its flight to the pile), the
      colour and challenge dialogs, paging a long hand, two people at one table. On real
      hardware: the sprite's palette bank and the card sprite's position.
- [ ] Client space: about 1.9 KB left (1.5 KB in the bridge build). Next things to move to
      an overlay of their own (the window takes up to 5.9 KB, no resident cost but a stub
      each): the sign-on screens (login.asm's windows), Exit
- [ ] One: ideas: a turn timer (the computer plays for someone who's away), a stronger
      computer (it never bluffs), a high-score list
- [x] Areas > Internet (2026-11-19): integrations found at start-up (internet/), and a
      text Web Browser (internet.web): pages as text with numbered links, search from the
      address box, Back, pages of 120 lines, private addresses refused, URLs in the Server
      Log. Tried in Xemu: mega65.org, a link, a DuckDuckGo search
- [ ] Web Browser: forms (GET and POST: text boxes, check boxes, Submit), cookies per user
      (sign-ins), a Home / bookmarks list, Find on the page, downloading a file into the
      File Library or to the client's disks, reading a site's own "reader" markup better
      (Wikipedia's language list comes first)
- [x] News Feeds (2026-11-21): Internet > News Feeds (internet/feeds.py, feedparse.py: RSS
      2.0, RSS 1.0 / RDF, Atom), 17 common feeds to start with (db.DEFAULT_FEEDS, checked
      working), a shared 10-minute cache, Open in Browser, moderators add (tried first) and
      remove feeds. Tried in Xemu: BBC News live, a story's summary
- [ ] News Feeds: an address longer than 63 characters can't be typed (the client's text
      boxes); per-user favourite feeds; new-story counts
- [ ] Internet: a picture viewer for the web (a headless browser's screenshots in an attic
      viewport, links as hot spots, clicks sent back), Gopher / Gemini
- [ ] This machine's MSYS2 Python has no certificate list: the bridge tests export the
      Windows roots to private/temp/winroots.pem and pass --cafile
- [ ] Resources: the client could say in HELLO which slots it still holds (attic survives
      a reset), so a reconnect skips the chess and One tiles (3 KB and 17 KB packed)
- [x] Bank and credits (2026-11-21): users.credits and a ledger (credit_log), starting
      credits, earning with daily limits (bank.EARN: games played and won, a poker hand,
      board posts, chat lines, votes, an active hour), gifts (with a private message),
      loans (one at a time, daily compound interest, a share of earnings repays it, overdue
      blocks gifts and poker), Areas > Bank and its desktop icon, My Account's Credits,
      the User Editor's Credits and statement (History), Admin > Bank Settings... Tried in
      Xemu: the Bank window
- [x] Texas Hold'em (2026-11-21): no-limit, 2-6, real credits (buy in 100-1,000, cashed out
      on leaving; db.poker_chips gives them back if the server stops), side pots, the
      computer (Monte Carlo hand strength and pot odds), a 30 s turn timer (sat out after
      two), people sit down at a running table. The table: a green felt Grid (35 tiles) with
      cards, the button and chips drawn on its tiles per viewer (TileCache); cards dealt one
      at a time as sprites. Tried in Xemu: buying in, a hand against two computers, the deal
- [x] Poker chat (2026-11-21): a chat panel at the right of the table (with the dealer's
      lines), what someone says shown at their seat for 6 s, now and then a remark from a
      computer. The seats moved to three along each long side to make room. Tried in Xemu:
      a line typed and sent with RETURN, at the seat and in the chat
- [x] Poker winner (2026-11-21): ka-ching (Sound.KACHING, a new client sound; sound.asm now
      plays lists of notes) and gold stars flashing either side of the winner's "Wins N"
      for 2 s. Tried in Xemu: the sound played to its end, both stars shown
- [x] Doorbell (2026-11-22): new instant and private messages ring a Westminster doorbell
      (Sound.DOORBELL, a new client sound); My Account's "Ring when Away" (on by default)
      lets it ring while Away. Tried in Xemu: an IM from another user rang all four notes;
      the checkbox in My Account
- [x] Long lists showed garbage past row 20 on a MEGA65 (2026-11-22; the Server Log): the
      server sent 20 rows and expected LIST_NEED for the rest, which the client never sends.
      Now the server sends every row the client holds (128, 16 to a message); the fake client
      checks every row arrives and no frame passes the client's 2 KB limit. Tried in Xemu
- [ ] Lists longer than 128 rows show only the first 128 (the client's limit): the Server
      Log pages at 128; file libraries, boards and the user list could pass it one day
- [x] SID Music (2026-11-22, branch sid-music): SID tune libraries like the File Library
      (sidlibs/), tunes checked in a 6502 before they go in (sidcheck.py), played by the
      client in the background (sidplay.asm), paused by its own sounds. Tried in Xemu:
      private/sid's three tunes play (50 and 60 calls a second), the doorbell pauses and
      resumes one, Play from the SID Music window
- [x] SID Music's menu-bar note (2026-11-22): while a tune plays (greyed when paused); it
      opens Now Playing: Pause / Resume, Stop, Song >, SID Music. Tried in Xemu: the note,
      the window, Pause holding the tune (play calls stopped), the Admin title kept whole
- [ ] SID Music: RSID tunes and ones loading at $C000+ (relocation?); the CIA rate a tune
      sets in its init (now 60 Hz); a desktop icon
- [ ] Poker: pre-action boxes (check/fold); showing who won with a
      flight of chips to the winner; the house's credits (vs Computer) are made and lost from
      nothing: watch Bank Settings' totals; table stakes other than 5/10
- [ ] Bank: a richest-users list; gifts only from accounts older than a day (new accounts
      made to give their starting credits away)
- [x] Terms of Service (2026-11-21): the last sign-up step (read, tick "I agree", OK greyed
      out until then; users.tos_agreed), the Sysop's editor (Admin > Terms of Service...,
      admin.tos, 4 pages of 32 lines), a standard default text. Tried in Xemu: the step, the
      tick and OK, the editor
- [ ] Terms of Service: ask existing users to agree again when the Terms change (a version
      number, a window at sign-on)
- [x] Unread news (2026-11-21): per-user read tracking (db news_reads, the version read),
      the newspaper icon (NOTIFY slot 6, icon 10; the client has 8 slots now), the offer
      after the welcome window counts unread ones, Mark All Read. Tried in Xemu: the icon,
      the offer, News from Read Now
- [x] Areas menu: News, Message Boards, Chat Rooms, Art Gallery, SID Music, File Library,
      Games; Members > User Search (name contains, any case; * = signed on now)
- [x] **Art Gallery** (`gallery/`; `gallery.view`, `gallery.upload`, `gallery.moderate`):
      galleries (moderators New / Edit / Delete), pictures listed with title, artist and
      date; View (any key back), Slideshow (Space next, Esc back, the next one sent ahead;
      a Loading window with a progress bar when it isn't there yet); Upload... an IFF from
      drive 8-11; moderators and the artist Edit... / Delete a picture. The server decodes
      the IFF (ILBM / PBM, EHB, HAM) and sends framebuffer-ordered pixels, PackBits-packed
      (S.PICTURE, S.RESOURCE_PACKED, C.PIC_KEY; client-src/picture.asm). Tested in Xemu over
      the bridge: View of deluxepaint65's tut.iff (about 50 s for its 28 KB packed), the
      Loading window, Space back to the desktop
- [x] Art Gallery: **Paint**, run on the server (`gallery/paint.py`; client-src/canvas.asm):
      the picture as the client's desktop, the tool window over it (Draw, Line, Box, Oval,
      Fill, Pick, Solid, Size, a 32-colour palette, Undo, Clear, Save..., Done), freehand
      strokes and line / box outlines drawn on the client at once. Tested in Xemu over the
      bridge: a new picture, a stroke, a box (its outline while dragged), Save, Done / Leave
- [ ] Paint: edit the palette's colours; an oval's outline while dragging (the client
      shows its box); text; brushes cut from the picture; magnify; pictures of more than
      32 colours (palette entries 16-254 are free: 239)
- [ ] **The client is nearly full**: 623 bytes left below $D000 (175 in the bridge build,
      below $CD00). The next client feature needs lib/overlay.asm (code swapped in from
      attic), or moving data under the KERNAL ROM
- [ ] Art Gallery: uploads from the SD card (the client reads only D64 / D81 images there
      now); a download of a picture to a drive; thumbnails; PNG / GIF uploads (from the web)
- [ ] Art Gallery: test on real hardware (the full-screen copy, $D020 / $D021, the pointer
      sprites off and on, the palette given back)
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
- [x] Status dot on the menu bar, left of the Wi-Fi icon (green / yellow / dark grey; a click
      toggles Available / Away). Notify slots renumbered: status 0, pages 1 ... IMs 5. The
      dark grey dot hasn't been looked at in Xemu yet (same drawing code as the other two)
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
- [x] File Library (`filelib.py`): libraries with their own `filelibs/<title>` folders, a
      title and description, per-role See / Download / Upload, an approve-uploads setting;
      moderators' file entries (Filename, Type, Description, Server Path); downloads and
      uploads with a progress bar; FILE_DATA paced by FILE_ACK (4 KB window)
- [x] Client storage (`storage.asm`): drive 8-11 directories, saving PRG / SEQ / USR, reading
      them for uploads; SD card folders and reading D64 / D81 images (HYPPO) - tested in Xemu
      over the bridge (drive 8 download and upload; SD listing; an 800 KB D81 read into attic)
- [x] **Write D64 / D81 images to the SD card** (`sdwrite.asm`): raw sector writes, a
      contiguous run of clusters, both FATs, the 8.3 entry, FSInfo marked unknown, metadata
      read back. Tested in Xemu with the real HYPPO (`-skipconfigfile -sdimg`) on scratch
      cards made by `private/tools/fat32img.py`: a D81 written byte-identical, the card
      checks clean, HYPPO lists it at once
- [ ] **Try SD card writing on a real MEGA65, with a backed-up or spare card first.** Also: a
      card with more than one FAT32 partition (the writer takes the one HYPPO's default drive
      is); 32 KB clusters (tested: 512 bytes and 4 KB, in a folder and in the root, and a
      name that's taken being refused); a folder whose clusters are full (refused, not
      grown); mounting a downloaded image (`d81attach`)
- [ ] File Library: bulk add of files copied into a library's folder
- [x] Client memory: frame buffers and the GUI's gadget texts moved under the KERNAL
      (`$E000-$FEFF`); about 5 KB free again
- [ ] File Library on real hardware: drives 9-11 (real IEC drives), the SD card, the ROM swap
      around disk calls (`disk_begin`), a whole D81 upload (the bridge is too slow: ~500 B/s)
- [ ] File Library: a CBM drive's subdirectories (CBM partitions) aren't listed or entered
- [x] Server Log (`serverlog.py`, `admin.log`): every log line kept in the database too, with
      area, level, connection and user; Admin > Server Log... with filters, pages, details and
      a whole session; errors with tracebacks; kept for System Settings' "Keep log" days
- [ ] Server Log: check the window (632x168) with long lists and a traceback on real hardware;
      export to a file? a live view that follows new rows?

## From the review (2026-11-18)
- [x] Fixed: request numbers could pile up until the server hung (forged Upload... clicks);
      Cancel after FILE_END said "Cancelled" while the client wrote the file (now greyed);
      Chat Rooms / the Chat icon emptied the room's conversation; poll end dates crashed on
      far-off years; non-ASCII digits crashed System Settings and karma; Offline admins were
      still paged; User Search showed roles to everyone; a second HELLO was taken;
      Settings / Broadcast / Karma History stayed open after the right went; Make Default
      didn't refresh IM rules; the file views didn't follow Download access changes;
      transfers went on after the right went; empty uploads; refusal wording;
      Delete Topic / Post / Room now ask first
- [x] Fixed (client): SD uploads of D64s were a part-sector too long (the server refused
      them); 8.3 names not checked before writing (a long or empty name could make a bad
      entry); paths over 64 characters were cut short (now 127, refused beyond); a drive
      save could scratch an existing file on an error, and a failed close left a splat
      file; drive names weren't checked (`*` would scratch the disk); FAT32 boot sector
      checks (FAT32 really, mirrored FATs, sizes, the root, chain ranges); a 2-3 s SD busy
      timeout; the upload stopped (and `st_mode` reset) when the connection goes; `net_send`
      fails at once with no connection; `tx_str` can't overrun a frame; long names ended at
      their length byte
- [ ] Library and forum Access windows list only 6 roles, and a role made later can see
      every limited library or forum (no row = allowed): page the dialog, and give new
      roles a row
- [ ] The quick new-user LOGIN (a name with LOGIN_NEW_USER: tests and old clients) skips the
      sign-up wizard's admin message; the person icon still shows the new user
- [ ] A deleted library's folder stays on disk, and a new library with that folder name
      takes its old files; descriptions' line lengths differ between areas
- [ ] Private Messages and Messages from users still delete without asking (each side's
      copy only); decide whether they should ask too
- [ ] SD writes: data sectors aren't read back (the bookkeeping sectors are)
