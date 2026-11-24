MegaNet
=======

A graphical, multi-user online service for the MEGA65. It looks like a mid-90s point-and-click
online service: windows, menus, buttons, list boxes and dialogs in a Windows 95 style, with
message boards, live chat, news, file downloads, instant messages and games.

- `client-src/`: the MEGA65 client, in 45GS02 assembly (64tass). It draws the GUI and runs the
  widgets itself, then sends the server what the user did (clicks, text, selections).
- `server-src/`: the server, in Python (standard library only). It handles many connections, owns all the content (in
  SQLite), and tells each client which windows and gadgets to show. It can force clients to
  update to the latest build.

The design and the protocol are in [docs/DESIGN.md](docs/DESIGN.md). MEGA65 technical notes are
in [docs/MEGA65_NOTES.md](docs/MEGA65_NOTES.md). Remaining work is in [TODO.md](TODO.md).

Status: early.
- **Server:** signs users on (accounts and roles in SQLite), then sends a menu bar (Areas,
  Members, Admin, Help), chat rooms (a Lobby, moderators' and members' rooms, private rooms), a two-player tic-tac-toe game, chess (a lobby to pick an opponent, a picture board, every rule enforced, chat beside the board), **One** (the card game for 2-4: match the colour or number, Skips, Reverses, Draw Twos, Wilds, call One! on your last card; wait for other players or play against 1-3 computer players; cards played and drawn fly across the table as hardware sprites), **Texas Hold'em** (no-limit poker for 2-6 at a green felt table, for real credits; wait for others or play 1-5 computer players; cards are dealt one at a time from the dealer; chat at the table, shown at the speaker's seat), **Blackjack** (1-3 players against the dealer at a green table with big cards, for credits; Join opens a table at once, others sit down as they come; chat at the table), **Tank Duel** (2-4 tanks on a random hilly field: set the angle and power with buttons, mind the wind, Fire; craters and damage; people or 1-3 computer tanks), and admin windows for
  roles and users. Tested with fake clients.
- **Client:** has its Windows 95-style GUI library (`client-src/lib/gui/`), the sign-on
  screen, the menu bar (its own **MegaNet** menu first, with Exit back to BASIC), and the
  network and protocol code. In Xemu's replay build it signs on, uses the menus, opens the
  lobby, chats, and exits to BASIC.
- **File Library:** libraries of files that the client downloads to drive 8-11 (PRG, SEQ,
  USR) and uploads from them or from the SD card (D64, D81 images). The client works with
  its disks through the KERNAL and HYPPO (`client-src/storage.asm`), putting the ROM back
  for each KERNAL disk call, because the framebuffer lives where the ROM was. Images go onto
  the SD card through the client's own FAT32 writer (`client-src/sdwrite.asm`: new files
  only, contiguous). It is tested in Xemu on scratch card images, **not yet on a real card:
  back your card up before trying it.**
- **Internet:** Areas > Internet lists services from outside MegaNet. The first is a text
  **Web Browser**: the server fetches the page and turns it into text with numbered links
  (no JavaScript, no pictures); words in the address box search the web. It never opens
  addresses on the server's own network. **News Feeds** reads RSS and Atom feeds as text
  (BBC, NPR, The Guardian, Ars Technica, Hacker News, Slashdot, NASA, Hackaday, Indie Retro
  News and more to start with; moderators add and remove them), and opens a story in the
  Web Browser.
- **Bank:** every user has **credits**: a starting balance (set by the Sysop), more for
  playing games (extra for a win at chess, One or Tic-Tac-Toe), message board posts, chat,
  voting, and every hour signed on and active, each with a daily limit. Areas > Bank shows
  the balance and a statement of every change, gives credits to another user (they get a
  private message), and lends credits at daily interest (part of what you earn repays it;
  an overdue loan stops gifts and poker). Poker is played with credits. My Account shows
  the balance; admins set it in the User Editor and change the rules in Admin > Bank
  Settings...
- **Art Gallery:** galleries of IFF pictures (Deluxe Paint's format) that moderators set up
  and members upload to from a drive. View shows a picture over the whole screen; Slideshow
  steps through them with Space (Esc stops). The server reads and converts the IFF, so the
  client only copies the pixels to the screen (`client-src/picture.asm`). **Paint** draws
  your own (Draw, Line, Box, Oval, Fill, a 32-colour palette, Undo, Save): the server keeps
  the picture and paints, the client shows it full screen and draws strokes at once while
  the server's answer comes (`client-src/canvas.asm`).
- **SID Music:** libraries of C64 SID tunes, built like the File Library. Play one and it
  keeps playing in the background while you use the rest of MegaNet; the doorbell and the
  client's other sounds pause it while they play. The client runs the tune's own C64 code
  in memory of its own (`client-src/sidplay.asm`), so the server checks every tune in a 6502
  first and refuses any that would touch more than its memory and the SID
  (`server-src/meganet/sidcheck.py`).
- **Live desktop:** the signed-on desktop shows what's happening
  (`server-src/meganet/livedesk.py`, `client-src/desk.asm`):
  - a **ticker** along the bottom, scrolling right to left behind a red NOW tag. It carries
    sign-ons, new members, new topics and replies, new files, news, new pictures and
    paintings, and game wins. Each member only sees events about things they may use, such
    as a forum they can read.
  - an **Online now** line above it, with a green dot before each name (Offline members are
    left out, as in Who's Online).
  - **badges** on the desktop icons:
    - Message Boards: new posts by others since you last looked or last signed on;
    - Chat: a green dot while anyone is chatting;
    - Games: people waiting for a player;
    - Who's Online: how many are on.

    Numbers go 1-9, then "10+".

  The server sends only what changed, and checks every 10 seconds as well. The ticker moves
  one character every 8 frames. It stays still under windows, toasts, broadcasts, pictures
  and Paint, and catches up at the next redraw. Older clients ignore all of this.
- **Client memory:** code used now and then lives in attic RAM as overlays and takes turns
  in one window (`client-src/overlays.asm`):
  - the File Library's disk and SD-card work (`OVL0`);
  - the Art Gallery's pictures and Paint (`OVL1`);
  - the live desktop (`OVL2`);
  - in the debug build, the connection log (`OVL3`).

  The disk has `MEGANET` and the overlay files, built together.
- **Updates:** the client's version is `client-src/VERSION`, also on the disk as `VERSION`.
  - `build` is a whole number that the client and server compare.
  - `name` (for example 2.1) is what the Connect screen, the update window and the library
    show.

  Put a newer `meganet.d81` in the server's `filelibs/meganet_client/` and older clients are
  offered it when they connect. The "MegaNet Client" library lists only the newest disk, and
  publishing removes the older ones. Download saves it on their SD card as `MEGANETn.D81`
  (n is the build). Members too old for the server must download it before signing on. See
  `server-src/README.md`, "Publishing a client update".
- **Server Log:** everything the server logs (connections, sign-ons and failed ones, what
  people do in each area, refusals, crashes with their tracebacks) is kept in the database
  as well, for admins to read in Admin > Server Log... with filters by area, level, user and
  text, and a whole session at a time. System Settings says how many days it's kept.
- **The real Ethernet path hasn't been tried on a MEGA65 yet.**

Build and run
-------------

Client: `build.bat` assembles `client-src/main.asm` and writes `target/meganet.d81`, the disk
for a real MEGA65. `run.bat` builds it and starts Xemu. On a MEGA65, plug in Ethernet on a
network with DHCP, run the server on a PC (or use a hosted one), check its IP address on the
sign-on screen, and click Connect, then Sign On. Without DHCP, pick **Static IP** on the
Connect window: Connect then asks for the IP address, subnet mask, gateway and (if you like)
a DNS server, and starts the network with them. The address starts filled in with the first
line of `private/server_address.txt` (or `MEGANET_SERVER`), when there is one: the build writes
it to `client-src/gen/server.asm`, so it stays out of git. The first time,
click New User instead: a step-by-step sign-up (screen name, password, about you, about me, then
a review page, then the Terms of Service to read and agree to) creates the account and signs
you in. The Sysop edits the Terms in Admin > Terms of Service...

Xemu has no network on Windows, so there are two ways to run the client against the server in
Xemu:

**Live, in Xemu (interactive):** run `private\tools\bridge.bat`. It builds the client with
`build.bat bridge` and starts the server and Xemu in a normal window. Then
`private/tools/xemu_bridge.py` carries the client's network traffic to and from the server
through Xemu's monitor port, replacing mega-ip and the Ethernet chip; everything else is real.
Sign on with any server address, using New User the first time. It's slower than a real
network: a few KB a second. `private/tools/bridge_test.py` runs the same thing headless.

The two test builds below have **no Ethernet**, so they write their own disks,
`target/meganet-bridge.d81` and `target/meganet-mock.d81`, and say "Xemu test build: no
Ethernet." on the Connect window. `target/meganet.d81` is always the real build.

**Replay (scripted):**
1. `python private/tools/record_mock.py` records a session from the real server.
2. `build.bat mock private\temp\mock\session.bin` builds the client with that recording in
   place of the network.

It goes with the scripted test in `TODO.md`: type `scott` / `secret` / any address, click New
User, then People Connection, then type `hello` and Send.

**Debug build (connection log):** `build.bat debug` writes `target/meganet-debug.d81`. This is
the real Ethernet client plus a connection log (`client-src/netlog.asm`), for a member whose
connection fails. The footer says "Version N debug". The log opens by itself when a connection
fails, and F1 opens it at any time. It has:
- the client's state and totals;
- mega-ip's addresses, TCP state, send queue, windows and sequence numbers, both now and as
  they were at the last failure;
- the last 64 events: messages each way (type, length and the first two bytes), network and
  screen changes, TCP state changes, resends, the peer's window closing, and failures with
  mega-ip's event bits.

Save writes it all as a SEQ file, `MEGANET-LOG` on drive 8, in ASCII with CR LF line ends.
`c1541 -attach meganet-debug.d81 -read "meganet-log,s" log.txt` gets it off the disk. This build
has 60 gadgets rather than 80, because the log uses the rest of their space. `build.bat bridge
debug` makes the same build for Xemu (`meganet-bridge-debug.d81`). `bridge_test.py netlog` and
`netlogsave` test it, with `BRIDGE_D81` set to that disk and `MON_PORT` set if another Xemu
already has port 4510.

Controls: the mouse (port 1) for everything; TAB moves between text boxes; RETURN presses a
window's default button.

Server: `cd server-src`, then `python -m meganet` (listens on port 6400; `--port` and `--db`
change the port and the database file). `python -m unittest` runs the tests. It needs Python
3.11 or later and nothing else. See [server-src/README.md](server-src/README.md).

Bundled tools
-------------

The repo root includes three Windows command-line tools that `build.bat` runs. Each one is
covered by its own licence.

| Tool | Used for | Project | Source |
|---|---|---|---|
| `64tass.exe` (v1.60.3243) | Assembler | [64tass](https://tass64.sourceforge.net/) | [SourceForge](https://sourceforge.net/projects/tass64/) |
| `c1541.exe` (VICE 3.6.1) | Writing the D81 | [VICE](https://vice-emu.sourceforge.io/) | [SourceForge](https://sourceforge.net/projects/vice-emu/) |
| `petcat.exe` (VICE 3.6.1) | Tokenising BASIC 65 | [VICE](https://vice-emu.sourceforge.io/) | [SourceForge](https://sourceforge.net/projects/vice-emu/) |

The client uses the TCP/IP stack from mega-ip (Ethernet, ARP, DHCP, DNS, TCP).
