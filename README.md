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
  Members, Admin, Help), chat rooms (a Lobby, moderators' and members' rooms, private rooms), a two-player tic-tac-toe game, chess (a lobby to pick an opponent, a picture board, every rule enforced, chat beside the board), and admin windows for
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
- **Server Log:** everything the server logs (connections, sign-ons and failed ones, what
  people do in each area, refusals, crashes with their tracebacks) is kept in the database
  as well, for admins to read in Admin > Server Log... with filters by area, level, user and
  text, and a whole session at a time. System Settings says how many days it's kept.
- **The real Ethernet path hasn't been tried on a MEGA65 yet.**

Build and run
-------------

Client: `build.bat` assembles `client-src/main.asm` and writes `target/meganet.d81`. `run.bat`
builds it and starts Xemu. On a MEGA65, plug in Ethernet on a network with DHCP, run the
server on a PC, type its IP address on the sign-on screen, and click Sign On. The first time,
click New User instead: a step-by-step sign-up (screen name, password, about you, about me, then
a review page with Accept) creates the account and signs you in.

Xemu has no network on Windows, so there are two ways to run the client against the server in
Xemu:

**Live, in Xemu (interactive):** run `private\tools\bridge.bat`. It builds the client with
`build.bat bridge` and starts the server and Xemu in a normal window. Then
`private/tools/xemu_bridge.py` carries the client's network traffic to and from the server
through Xemu's monitor port, replacing mega-ip and the Ethernet chip; everything else is real.
Sign on with any server address, using New User the first time. It's slower than a real
network: a few KB a second. `private/tools/bridge_test.py` runs the same thing headless.
Afterwards, `build.bat` makes the normal disk again.

**Replay (scripted):**
1. `python private/tools/record_mock.py` records a session from the real server.
2. `build.bat mock private\temp\mock\session.bin` builds the client with that recording in
   place of the network.

It goes with the scripted test in `TODO.md`: type `scott` / `secret` / any address, click New
User, then People Connection, then type `hello` and Send.

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
