# MegaNet server

The server for MegaNet, a graphical multi-user BBS for the MEGA65. It is plain Python 3.11 or
later with nothing to install: only the standard library (asyncio, sqlite3, hashlib, json,
zlib, unittest).

The server owns all content and logic. It tells each client which windows and gadgets to show;
the MEGA65 client draws them and sends back what the user did ("button 5 clicked"). The whole
design is in [../docs/DESIGN.md](../docs/DESIGN.md), and the wire format in
[meganet/protocol.py](meganet/protocol.py).

## Running

```
cd server-src
python -m meganet                   # port 6400, database data/meganet.db
python -m meganet --port 6401 --db C:\bbs\meganet.db --updates C:\bbs\updates
python -m meganet --motd motd.txt   # load the message of the day from a text file
```

| Option | Default | |
|---|---|---|
| `--port` | 6400 | TCP port |
| `--host` | 0.0.0.0 | address to listen on |
| `--db` | `data/meganet.db` | SQLite file, created (with its tables) on first run |
| `--updates` | `updates/` | folder with `manifest.json` and the client files for forced updates; no manifest = updates off |
| `--filelibs` | `filelibs/` | the file libraries' folders, one per library (made as needed) |
| `--motd` | | text file to load into the message of the day at start (it replaces the saved one; see below) |
| `--cafile` | | a PEM file of trusted certificates for the Web Browser's https, for a Python with no list of its own (an MSYS2 Python without its `ca-certificates` package) |

Stop it with Ctrl+C.

## Testing

```
cd server-src
python -m unittest -v
```

The tests start a real server on a random port with an in-memory database, and connect fake
clients over TCP (`tests/fakeclient.py`, which keeps a model of the client's windows). They
cover the deframer with split and merged chunks, sign-on (new user, wrong and right password,
name rules), the menu bar, two clients chatting in the lobby, two clients playing tic-tac-toe
to a win, the forced update, and roles (`tests/test_roles.py`: the first user is Sysop, the
menu filtered per role and re-sent when the role changes, forged admin clicks and menu picks are
refused, Who's Online, an admin edits a role and moves a user while they're signed on, the
last-admin protection, migrating an old database), and the message of the day
(`tests/test_motd.py`: the welcome window is centred and shows it, an admin adds, replaces,
deletes, previews and saves lines and a new sign-on sees them, forged picks and clicks are
refused, `--motd FILE`), Page Admin (`tests/test_pages.py`: the page icon to two admins, the
first click wins, the private chat both ways, Cancel, a queue of pages, the chat ending, the last
admin signing off, forged NOTIFY_CLICKs; with no admin on, a message is stored and an admin who
signs on later gets the icon, reads it and deletes it), private messages (`tests/test_mail.py`:
to a signed-off user who gets the icon at sign-on, read, reply, the Sent folder, delete on each
side, unknown recipients, `mail.use` enforced), and My Account (`tests/test_account.py`: opened
by MENU_PICK $22, the layout, save and reload through the drop-downs and C.TEXT, invalid and
partial dates, clearing to "--", Cancel, too many About Me lines, an old-style About Me, Last
Login, Reset Password), and the New User wizard (`tests/test_signup.py`: the six steps and
their layout, the account, profile and admin message saved, the admin's envelope icon, the
alert last; taken, held and bad names, passwords, dates, emails, Back keeping every value,
Cancel at steps 1 and 4 and the close box followed by a normal sign-on on the same connection,
forged events before sign-on, two sessions racing for a name, the first account). The fake client also fails any window that doesn't fit below the menu
bar, any gadget outside its window, any malformed NOTIFY, and a DropDown or Edit sent against
its rules (`pick_dropdown()` and `text()` drive them; `click()` sends C.TEXT for the window's
Edit gadgets first, as the real client does).

## Layout

| File | What |
|---|---|
| `meganet/protocol.py` | Message numbers, gadget kinds, flags; `Writer`, `Reader`, `Deframer` |
| `meganet/ui.py` | `Window` and the gadget classes (`Button`, `Label`, `TextBox`, `Password`, `ListBox`, `DropDown`, `TextView`, `TextArea` (Edit), `CheckBox`, `Radio`, `Progress`...), mirroring the client's GUI; `Menu` for the menu bar |
| `meganet/session.py` | One per connection: reads frames, sign-on, sends events to windows and gadgets |
| `meganet/server.py` | The listener and the shared state; `python -m meganet` runs `main()` here |
| `meganet/db.py` | SQLite: users (PBKDF2-SHA256 password hashes), roles and their permissions, settings, and every area's tables |
| `meganet/filelib.py` | Areas > File Library: libraries, their files, downloads and uploads through the client's disks (`Storage`) |
| `meganet/internet/` | Areas > Internet: services from outside, found at start-up like games (`base.Integration`); the text Web Browser (`web.py`, with `webtext.py`: fetching and HTML to text) |
| `meganet/permissions.py` | The registry of permission keys, and the default roles |
| `meganet/screens.py` | The menu bar (`MENU_TREE`), the welcome window with the message of the day, Who's Online, Help > Getting Around |
| `meganet/chat.py` | Chat rooms: the room window, the room list, moderation |
| `meganet/karma.py` | Karma Points: gains, losses, alerts to the admins |
| `meganet/admin.py` | The Roles, Users and Message of the Day windows |
| `meganet/account.py` | My Account (the profile) and Reset Password |
| `meganet/signup.py` | The New User sign-up wizard (before sign-on) |
| `meganet/pages.py` | Help > Page Admin: paging, the private chat with an admin, messages to the admins, Admin > Messages from users |
| `meganet/mail.py` | Areas > Private Messages: inbox, Sent folder, compose |
| `meganet/compose.py` | The message composer (To, Subject, a text area, Send / Cancel) used by pages.py and mail.py |
| `meganet/updates.py` | Forced client updates from `updates/manifest.json` |
| `meganet/serverlog.py` | The server log: every line kept in the database too, and Admin > Server Log to read it |
| `meganet/games/` | The games framework (`base.py`, `lobby.py`, `challenge.py`: a game's lobby for picking an opponent) and the games themselves (`tictactoe.py`; `chess.py` with `chess_rules.py` and the piece art `chess_art.py`; `one.py` with `one_rules.py` and the card art `one_art.py`) |
| `tests/` | unittest tests and the fake client |

## Sign-on

```
client                          server
HELLO (version, build, caps, name) ->
                                <- HELLO (version, session id)
                                <- UPDATE + FILE_BEGIN/DATA/END...   (only if the build is old)
LOGIN (flags, name, password)   ->
                                <- LOGIN_RESULT (ok, message)
                                <- MENU (the menu bar), the welcome window   (on success)
```

The client draws its own sign-on window (window ids `$F0`-`$FF` are the client's; the server
uses 1-`$EF`). LOGIN flag bit 0 asks for a new account. Screen names are 3-10 letters, digits
or single spaces, case-insensitive; passwords need 4 characters.

### New User: the sign-up wizard (`meganet/signup.py`)

The client's **New User** button sends LOGIN with bit 0 set and an **empty** name and password.
The server then opens the wizard instead of answering (a LOGIN with bit 0 and a name still
creates the account at once, for old clients and the tests):

```
LOGIN (new user, "", "")        ->
                                <- the wizard, window 20, step 1   (no LOGIN_RESULT yet)
CLICK / VALUE / SELECT / TEXT / WIN_CLOSED for window 20 ->        (only these, only window 20)
                                <- window 20 again for each step
Cancel or the close box         -> <- WIN_CLOSE 20, LOGIN_RESULT 0 "Sign-up cancelled."
OK (Terms of Service agreed)    -> <- WIN_CLOSE 20, LOGIN_RESULT 1, MENU, the welcome window...,
                                      then ALERT "Welcome to MegaNet!" (last: in front)
```

After a cancel the connection stays open for another LOGIN. The window is 448x152, centred,
modal, with a close box (= Cancel). Every step has "Step n of 6" at the top left, a status line
(y 120) and its buttons at the bottom right (y 134, 64x16): Back (not on step 1), Next (the
default; OK on step 6) and Cancel.

| Step | Title | Fields |
|---|---|---|
| 1 | New User: Screen Name | a welcome, the rule; Screen name: TextBox (124, 62) 96 wide; First Name and Last Name (required): TextBoxes (124, 77 / 92) 166 wide |
| 2 | New User: Password | the rule from `db.check_new_password` + "Type it twice."; Password and Confirm: Password boxes (124, 50 / 65) 160 wide |
| 3 | New User: About You | "optional, change it later in MegaNet > My Account"; Birthdate: Month / Day / Year drop-downs (as My Account), Location and Email Address: TextBoxes 260 wide |
| 4 | New User: About Me | an Edit area (124, 46) 260x70: My Account's 30-character lines, all 8 lines visible |
| 5 | New User: Review | Screen name, Name (first and last), Password (stars), Birthdate ("21 Jun 1985" or "not given"), Location, Email Address, the first two About Me lines; Back, Next, Cancel |
| 6 | New User: Terms of Service | "Please read our Terms of Service, then agree to join."; the Terms (`db.tos()`) in a TextView (4, 28) 433x76, exactly 52 characters wide, scrolled to the top; a check box "I have read and agree to the Terms of Service."; OK (default) greyed out until the box is ticked, Back, Cancel |

The values are kept on the server between steps, so Back shows them again (Back doesn't check
anything). Next checks its step: the name with `db.check_new_name`, not an existing account in
any case ("That name is taken, please try another."), and not held by another session's wizard,
then the first and last names (`db.check_real_name`: required, letters, spaces, ' - and ., at
most 20 characters);
the passwords match the rule and each other; the date, email and lengths as My Account checks
them; at most 8 About Me lines. OK checks every step again and shows the first one with a
problem, and that the box is ticked (a forged click on the greyed-out OK is dropped anyway).
A good step 1 **holds the name** until the wizard ends (OK, Cancel, another
LOGIN or the connection going), and an old-style new-user LOGIN can't take a held name either.

OK creates the account (the default role; the very first account is Sysop) and saves the
profile and when they agreed to the Terms (`users.tos_agreed`). Unless it is the first account, it adds an admin message (subject "New user", "<name>
has just signed up. Please check their access (Admin > User Editor).") from the new user and refreshes
the admins' envelope icons, as a Page Admin message does. Then the usual sign-on, and the alert
"Account set up! An admin has been told and will upgrade your access." (the first account gets
"Account set up! As the first member, you are the Sysop." instead).

## The menu bar

After sign-on the server sends a `MENU` (the bar across the top of the screen, America Online /
Windows 95 style) and the welcome window (the user's role, the message of the day, the
server's version centred under it, and OK to close it; see below). The version is
`meganet.__version__`; Help > About MegaNet shows it too. The client puts its own MegaNet menu first and its **Window** menu after
the server's titles; titles with ids $E0-$EF (`protocol.MENU_LATE`: Admin) go right of Window.
The tree is `MENU_TREE` in `meganet/screens.py`:

| Title (id) | Items (id) | Needs |
|---|---|---|
| Areas (1) | News ($12), Message Boards ($10), Chat Rooms ($11), Private Messages ($17), Art Gallery ($15), SID Music ($16), File Library ($13), Games ($14) | `news.read`, `boards.read`, `chat.use`, `mail.use`, `gallery.view`, `music.listen`, `files.download`, `games.play` |
| Members (2) | Who's Online ($20), User Search... ($23) | everyone |
| Help (4) | About MegaNet ($40), Getting Around ($41), Page Admin ($42) | everyone |
| Admin ($E0, right of Window) | User Editor... ($31), Roles... ($30), Message of the Day... ($32), Terms of Service... ($37), Messages from users... ($33) | `admin.users`, `admin.roles`, `admin.motd`, `admin.tos`, `admin.pages` |

**My Account ($22)** is the first item of the client's own MegaNet menu. The server never sends
it in MENU, but accepts a MENU_PICK of $22 from any signed-on session (`ui.Menu.client_item`,
`protocol.MENU_MY_ACCOUNT`). $21 (the old Members separator) is no longer used.

An item is sent only if the user's role has its key; a title with no items left is left out
(a role with no permissions sees only Members and Help). Ids are fixed, whichever items a role
hides. A `MENU_PICK` for an id that wasn't in the menu last sent to that session (a title, a
separator, or a forged id) is ignored, except $22; a picked item checks its key again and answers
"Your account can't use ..." if it has gone. *Who's Online* lists the signed-on users and their
roles and keeps itself up to date. *Getting Around* (window 12, 400x128) is a placeholder help
text: the menu bar, the Window menu, TAB and RETURN, MegaNet > Exit.

To add an item, add a row to `MENU_TREE` (id, label, permission key or None, the name of a
`Screens` method taking `(session, item)`). For other menus, build a `ui.Menu` and
`menu.show(session)`; it replaces the bar.

## Roles and permissions

Every user has one **role**, and a role is a set of **permission keys**. The server asks
`session.can("chat.use")` before it offers or opens anything; the menu bar shows only the
areas the user's role allows, and every handler checks again, because a client can send a CLICK
for a button or a MENU_PICK for an item it was never given.

| Key | | New User | Member | Moderator | Sysop |
|---|---|---|---|---|---|
| `chat.use` | Chat in the lobby | x | x | x | x |
| `chat.rooms` | Make chat rooms (member rooms) | | x | x | x |
| `games.play` | Play games | x | x | x | x |
| `boards.read` | Read message boards | x | x | x | x |
| `news.read` | Read the news | x | x | x | x |
| `boards.post` | Post on message boards | | x | x | x |
| `files.download` | Download files (the File Library) | | x | x | x |
| `im.send` | Send instant messages | | x | x | x |
| `chat.moderate` | Moderate chat | | | x | x |
| `boards.moderate` | Moderate boards | | | x | x |
| `news.post` | Post, edit and delete news bulletins (Areas > News) | | | | x |
| `files.upload` | Upload files to the File Library | | | x | x |
| `files.moderate` | Manage file libraries: libraries, file entries, access, approvals | | | x | x |
| `gallery.view` | Look at the Art Gallery (View, Slideshow) | x | x | x | x |
| `gallery.upload` | Upload IFF pictures to the Art Gallery | | x | x | x |
| `gallery.moderate` | Manage galleries; edit and delete anyone's pictures | | | x | x |
| `admin.users` | Assign users to roles | | | | x |
| `admin.roles` | Edit roles and their permissions | | | | x |
| `admin.motd` | Edit the message of the day | | | | x |
| `admin.tos` | Edit the terms of service (new: roles with `admin.motd` get it) | | | | x |
| `admin.pages` | Answer pages from users (and read their messages) | | | x | x |
| `admin.settings` | System Settings (Auto-Away, New Users' instant messages) | | | | x |
| `admin.broadcast` | Broadcast a line to everyone signed on | | | | x |
| `admin.log` | Read the server log (Admin > Server Log) | | | | x |
| `polls.vote` | Vote in polls (Areas > Voting) | x | x | x | x |
| `polls.manage` | Set up and delete polls | | | x | x |
| `mail.use` | Use private messages | x | x | x | x |

These four roles are made the first time the server opens a database. After that they are
ordinary rows: an admin can rename them, change their permissions, add roles and delete them.

- **The first account ever created becomes Sysop**, so a fresh install always has an admin.
  New accounts after that get the **default role** (New User at first; an admin changes it with
  "Make Default" in the Roles window; it's kept in the `settings` table).
- **There is always someone who can edit roles.** The server refuses any change that would
  leave no user whose role has `admin.roles`: moving the last one to another role, taking the
  key away from their role, or deleting it.
- A role that still has users can't just be deleted: Delete offers to move them to the default
  role first. The default role itself can't be deleted until another role is the default.
- **Changes apply at once**, also to users who are signed on: their permissions are re-read,
  their menu bar is sent again (and the role on their welcome and My Account windows updated),
  and they are taken out of areas they may no longer use (the chat rooms, a game's queue, the
  admin windows).
- An older database (users without `role_id`) is migrated when the server opens it: the oldest
  user becomes Sysop and everyone else gets the default role.

**Administration** (the Admin menu, right of the Window menu, only for admins: holders of
`admin.users`, `admin.roles` or `admin.motd` (`screens.is_admin`). Moderators have
`admin.pages` and answer pages through the menu-bar icons, but get no Admin menu. Each item
needs its own key):

- *Roles...*: the list of roles with their user counts (`*` marks the default). Pick one to edit
  its name (Rename), its level (sort order) and a check box per permission, in two columns of
  eight, with Prev / Next pages when there are more. Save writes the level and permissions.
  New Role, Delete and Make Default are there too.
- *User Editor...* (window 6, 608x171): every user and their role on the left. Type part of a
  name and click Find to narrow the list (a single match is selected for you). Pick a user to
  edit, on the right, their First and Last Name, Email and Location, and their Role (a
  drop-down); Joined and Last Login are shown. Save checks the fields as My Account does
  (accounts from before real names were asked for may keep them blank) and keeps Birthdate and
  About Me as the user left them. *Set Password...* (window 4, modal) sets a new password, typed
  twice; the old one isn't needed.
- **New users:** while any user is still in the default role (New User), every signed-on
  holder of `admin.users` gets a person icon (`Icon.PERSON`, a black pawn) in notify slot 4
  (`SLOT_NEW_USER`, left of the envelopes), hint "N new users". It is updated when someone
  signs up and whenever roles or users change (`Admin.changed` -> `Screens.new_users_changed`),
  and goes once nobody is left in the default role. A click opens the User Editor at the oldest
  new user.
- *Message of the Day...*: see below.

## Message of the day

Every user sees the message of the day in the welcome window at sign-on: a window centred on
the screen (window 1, client area 416x134, at 108,29) titled "Welcome, *name*", with a
"Role: *X*" label, a read-only text view (400x100) holding the message, a one-line hint ("No
access yet: ask the sysop." for a role that can use no area) and OK. The server sends one
`APPEND` per line; the client word-wraps each one to the view (47 characters a line, after its
margins and scroll bar) and scrolls, so a line is a paragraph and an empty line is a blank
line. Open welcome windows aren't changed when the message is saved; users see it at their
next sign-on.

It is kept in the `settings` table (key `motd`, a JSON list of lines; `db.motd()` /
`db.set_motd()`). A new database starts with a short welcome. Lines are ASCII (anything else
becomes `?`, tabs become spaces), at most 255 characters, and at most 64 of them (the client
keeps 128 wrapped lines); trailing blank lines are dropped.

There are two ways to change it:

- **On the PC:** write a text file (UTF-8, one paragraph per line) and start the server with
  `--motd FILE`. It replaces the saved message every time the server starts with it.
- **On the MEGA65:** Admin > *Message of the Day...* (needs `admin.motd`), a line editor in a
  centred window (window 11, client area 544x158). The list shows each line as "nn " plus its
  first 27 characters (list rows hold 31); picking a row puts the line in the text box below
  (63 characters at most: a longer line from a file shows its start, and Replace would cut it).
  Replace, Insert before, Add at end and Delete use the text box; Preview opens the welcome
  window with the edited lines, as users will see it; Save stores them, Cancel (or the close
  box) throws them away. Every handler checks `admin.motd` again.

### The Terms of Service

New users read and agree to them as the last step of sign-up (above); `users.tos_agreed` records
when. They're kept in the settings table (`db.tos()` / `set_tos()`, key `tos`) as 4 pages of at
most 32 lines (the client's text areas hold 32), each line at most 52 characters: the reader's
width, so a line typed is a line read. A new database starts with a standard online-service
agreement (`db.DEFAULT_TOS`: accounts, acceptable use, your content, moderation, privacy, files,
no warranty, liability, changes, contact). Change it on the MEGA65 with Admin > *Terms of
Service...* (`admin.tos`): a page at a time in a text area as wide as the reader, < and > to turn
the pages (edits kept), Save (refused if the text would run past the reader's 128 lines, or is
empty), Cancel. Users who agreed to an older text aren't asked again.

`ui.centre(w, h)` and `Window.centred(title, w, h, ...)` centre any window below the menu bar.

### Adding a permission

Register the key when your module is imported, then check it:

```python
from meganet import permissions

STICKY = permissions.register("boards.sticky", "Make sticky posts", like="boards.moderate")

if not session.can(STICKY):
    return session.alert("Boards", "You can't do that.")
```

The description is what the Roles window shows next to the check box (at most 24 characters).
The first time the server sees a new key it grants it to every role that holds `admin.roles`
and, with `like=`, to every role that holds that key. After that only admins change who has it
(taking a key away is never undone by a restart). Game plugins do the same: see
[meganet/games/README.md](meganet/games/README.md).

## Windows and dialogs

Every window and button follows the same rules (Windows 95 conventions; `ui.add_buttons`):

- **Every window has a close box** (title bar, right). The only exceptions are the client's
  own Connect and Sign On screens, which have nothing behind them. Every window can be moved.
- **Every window has a minimize box** (left of the close box; `WFlag.MINIMIZE`, which
  `ui.Window` adds by itself), except:
  - modal windows (`WFlag.MODAL`: confirmations, Set Password, Forum Access, Unban, the
    sign-up wizard; the client's alerts and Exit box);
  - small non-modal dialogs, given `minimize=False`: the Welcome box, Getting Around, System
    Settings and the two Page Admin boxes;
  - the client's Connect and Sign On screens.

  A minimized window is a title bar along the bottom of the screen (rows of 4, going up),
  behind every other window. The client does it all. A window the server sends again stays
  minimized, unless it's the answer to the user's own click or menu pick (for example
  Members > Who's Online again), which restores it.
- **Work windows** (Private Messages, Message Boards, a chat room, Chat Rooms, the User Editor,
  Roles, Who's Online, User Search, Messages from users, Games) **have no Close or Leave
  button.** The close box closes them (and leaves a chat room).
- **Area windows look alike** (`ui.AreaWindow`): every Areas entry window (News, Message
  Boards, Chat Rooms, Private Messages, File Library, Games, Internet, Voting), the views
  inside them (a forum's topics, a topic's posts, a library's files) and a game's lobby:
  - 560 x 160, centred; a heading line with a summary ("2 libraries.");
  - the list on the left (400 wide; a column heading over it when its rows have columns),
    and under it, when there is one, the picked item: its description, the message, the post;
  - the commands in a column on the right (136 wide): the main one first, the default
    (Open, Read, Go, Join, Vote, Reply..., Download...); then the others for everyone; then,
    only for those allowed, **Admin Tools** under a line and a bold heading (pairs of short
    commands side by side);
  - a status line at the bottom: what to do next, or what just happened.
  - A click on a row picks it; a double click does the main command.
  `tests/test_layout.py` checks every area as the Sysop and as a New User (no Admin Tools).
- **Dialogs end in a row of command buttons:** the command first, then Cancel (`OK  Cancel`,
  `Send  Cancel`, `Yes  No`).
  - Message boxes (a line or two of text, alerts, "Delete X?", Exit) centre the row under the
    text.
  - Dialogs with fields (My Account, passwords, Forum Access, Unban, the composer, the Message
    of the Day editor, the sign-up wizard) put it at the bottom right.
  - The close box does what Cancel does.
- **RETURN presses the command** (the button with the heavy border), except in a Delete
  confirmation, where it presses Cancel.
- **Every delete asks first** ("Delete X?", Delete / Cancel): `ui.confirm()` makes the box,
  and its action checks again that it's allowed and the thing is still there.
- **Refusals** (a client asking for what its role can't do) say "Your account can't use
  *area*." for an area, "Only moderators can do that." for moderators' tools, and "You don't
  have permission to do that." in Admin windows; all are logged as warnings.
- **Buttons are 16 high and at least 72 wide, 8 apart.**
- **A button that can't do anything now is greyed out:**
  - Reply..., Delete, Open, Read, Rename, Lock, Access..., Kick, Save, Set Password... and
    the like are greyed until something is picked in the list.
  - Mark as Unread is greyed until the message is read, and Unban... until someone is banned.
  - Kick, Mute, Ban and Karma +/- are greyed for yourself and for people you may not act on.
  - Chat Rooms' Delete is greyed for the Lobby and for member rooms.
  - How it works: `Gadget.enable(on)` sends `S.SET_FLAGS` (`$1D`: win, gid, flags) when it
    changes. The client draws a disabled button etched and ignores clicks on it, and the
    server ignores clicks on it too. The handlers still check, since a client can send any
    click.
- **Labels are in Title Case.** They end in "..." when the button opens a dialog that asks for
  more (New..., Reply..., New Topic..., Access..., Unban..., Rooms..., Set Password...,
  Reset Password...). Menu items do the same.

## Menu-bar icons (NOTIFY)

`session.set_notify(slot, icon, hint)` puts a small icon button at the right end of the
client's menu bar (S.NOTIFY; slot 0 is the rightmost), and `Icon.NONE` removes it. It is sent only
when it changes, and a C.NOTIFY_CLICK is passed on (to `Screens.notify_click`) only for a slot
the session was sent; the handler then checks the permission again. The client leaves the icon
there after a click: the server removes it when it's done.

| Slot | Icon | Hint | Who | Click |
|---|---|---|---|---|
| 0 | 7 / 8 / 9 (green / yellow / dark grey dot) | "Status: Away" | everyone, always | Available -> Away, otherwise -> Available |
| 1 | 1 (page, flashing) | "bob is paging you" / "3 users are paging" | `admin.pages` | take the oldest page |
| 2 | 2 (mail) | "2 messages from users" | `admin.pages` | Admin > Messages from users |
| 3 | 2 (mail) | "1 unread private message" | `mail.use` | the Private Messages inbox |
| 4 | 5 (person) | "2 new users" | `admin.users` | the User Editor at the oldest new user |
| 5 | 6 (speech bubble) | "2 new messages from bob" | anyone | the conversation with unread messages |
| 6 | 10 (newspaper) | "2 unread news bulletins" | `news.read` | Areas > News |

The slots are the `protocol.SLOT_*` constants; use those, not the numbers.

**Sounds:** `S.SOUND` `$24` (u8 `Sound`; `session.sound()`) has the client play one of its
own sounds on the SID, on both speakers (`client-src/sound.asm`). `Sound.CHIME` (1) is a
two-note "ding-dong". Every admin who can answer gets it once when someone new starts paging,
with the flashing icon. A hint changing ("3 users are paging") doesn't chime again.

## Page Admin

Help > Page Admin (`meganet/pages.py`) asks for anyone whose role has `admin.pages`.

- **An admin is signed on** (other than the user): the user gets "Page Admin" (window 13,
  240x40, "Paging an admin..." and Cancel) and every admin the page icon. The first admin to click
  it takes the oldest waiting page: the icon goes for every admin (or shows the next page), the
  paging window closes, and both get "Chat with *name*" (360x140, a dynamic window id from `$40`,
  cascaded so several can be open): a TextView, a TextBox and Send. Each line goes to both as
  "*name*: text". Closing either window (or signing off) ends it: the other side gets "* *name*
  left the chat" and can still read; Send then says "* The chat has ended.". Cancel or the close
  box withdraws the page. If the last admin goes while a page waits, the user gets the no-admin
  dialog instead.
- **No admin is signed on:** "No admin is available right now. Would you like to leave a message
  for the admins?" (window 14, 400x52) with Yes and No. Yes opens "Message to the Admins"
  (window 15, 544x152): a Subject box, the message in an editable text area, Send and Cancel
  (`compose.py`). Send closes it and shows a "Message Sent" box. It is stored in `admin_messages` (id, from_user, sent,
  subject, text, read). Admins get the slot 2 icon while unread messages wait (at sign-on, and
  when a new one comes).
- **Admin > Messages from users...** (window 16, 600x152, `admin.pages`): a list ("*" = unread,
  from, date) and a TextView with the picked message (From, Date, Subject, the text); Reply,
  Delete and Mark as Unread (the close box closes it). Mark as Unread puts the picked message's "*" back for every
  admin, and their icons come back. Reply opens the private-message composer (`mail.py`) to the sender with
  "Re: *subject*", so the answer lands in their Private Messages inbox. Picking a message marks it read (the window is sent again, since a TextView only
  appends); the icon goes when nothing is unread.

## Private Messages

Areas > Private Messages (`meganet/mail.py`, `mail.use`):

- **Inbox** (window 17, 632x160): a list (from, subject, date and time, " *" if unread; 37
  characters) and a TextView with the picked message (From, Date, Subject, then the body); New,
  Reply, Delete, Sent (switches to the Sent folder, where the button says Inbox and rows show the
  recipient) and Mark as Unread (inbox only); the close box closes it. Picking a message fills the reading pane in
  place (`TextView.set_lines`: SET_TEXT "" empties a text view, then APPENDs) and marks it read.
  Mark as Unread puts the picked message's " *" back (and the envelope icon, slot 3); it stays
  in the reading pane. A new message updates an open inbox in place. Every member with
  `mail.use` gets the envelope while they have unread messages, admin or not.
- **New Message** (window 18, 544x168): To (any case; it must be an existing user), Subject,
  and the body in an editable text area (up to 32 lines), as for the message to the admins.
  Send closes it and shows "Message Sent". Reply fills in To and
  "Re: *subject*".
- `private_messages` (id, from_user, to_user, sent, subject, body, read, del_sender,
  del_recip): a message stays until both sides have deleted it. The recipient, if signed on,
  gets the slot 3 icon; otherwise at their next sign-on.

## Voting

**Areas > Voting** (`meganet/polls.py`; `polls.vote`, everyone from New User up):
- **The Voting window** (32) lists the polls, newest first, each with its state: "open",
  "until 11-30" (it has an end date), "voted" or "ended".
  - Picking one shows its description (more background on the question) and its choices.
  - Pick a choice and **Vote** (or double-click it). Everyone votes once in each poll: the
    database keeps one vote per person per poll, and Vote is greyed once you have voted.
    Your choice is marked "*".
  - **Results** (or a double-click on the poll) opens a window with a bar for each choice,
    its votes and its share, and the total. It follows new votes while it's open.
- **After the end date** nobody can vote. The choices list shows each one's share and
  Results shows the graph.
- **Moderators and up** (`polls.manage`) also get **New...** and **Delete** under Admin
  Tools.
  - New... asks for a question (up to 60 characters), a description in a text area (up
    to 600 characters), 2-6 choices (up to 30 characters) and an end date as YYYY-MM-DD,
    blank for none. Voting stops at the end of that day.
  - Delete asks first, and takes the poll's votes with it.
- Tables: `polls`, `poll_choices`, `poll_votes`.

## News

**Areas > News** (`meganet/news.py`; `news.read`, everyone from New User up):
- **Unread news:** a bulletin is unread until you open it, and again after it's edited (the
  `news_reads` table keeps the version each user read). While any are unread you have the
  newspaper icon (slot 6, "2 unread news bulletins"; a click opens News), and closing the
  welcome window at sign-on asks "There are 2 unread news bulletins. Would you like to read
  them now?" (window 39: Read Now opens News, Later). When read tracking first started, each
  user's bulletins from before their last sign-on were counted as read; new users start with
  everything unread.
- **The News window** (36) lists the bulletins, newest first: "*" if it's unread, then the
  day and the headline; the heading counts them. **Mark All Read** marks them all.
- **Read** (or a double-click) opens the picked one to read (window 40, modal): the headline
  and who posted it (and who edited it last) centred at the top, then the text in a view
  exactly as wide as the composer's text area, so every line reads as it was written; OK
  closes it. An open one follows edits, and closes if the bulletin is deleted.
- **Holders of `news.post`** (only the Sysop in a new database; give it to any role in
  Admin > Roles) also get **New...**, **Edit...** and **Delete** under Admin Tools; Edit and
  Delete act on the picked bulletin.
  - New... and Edit... open the message composer (`compose.py`, window 37), with a Headline
    box and the same text area as the boards and private messages. Edit starts with the
    bulletin's headline and text, and the button says Save rather than Post.
  - Delete asks first (window 38).
  - Every open News window follows changes straight away.
- **At sign-on**, if there are new bulletins, closing the welcome window brings up "There are
  N new news bulletins. Would you like to read them now?" (window 39, modal): **Read Now**
  opens News, **Later** closes it. It comes once per sign-on, and not after the Message of
  the Day editor's Preview.
- Table: `news` (headline, body, author, posted, edited, editor).

## File Library

**Areas > File Library** (`meganet/filelib.py`; `files.download`, Member and up), listed like
the chat rooms:
- **Libraries** each have a title, a description and their own folder on the server:
  `filelibs/` and the title in lower case with spaces as underscores (`C64 Games` ->
  `filelibs/c64_games`). Renaming a library renames its folder; deleting one keeps the folder.
- **The window** (41) lists the libraries the user may see, with the picked one's description
  under the list. **Open** shows its files (name, type, size, date added, downloads) with the
  picked file's description, **Download...**, **Upload...** (when allowed) and **Back**.
- **Moderators** (`files.moderate`) get, under **Admin Tools**:
  - **New... / Edit...** a library: title, description, and "Uploads show at once" (off:
    uploads wait until a moderator **Approve**s them); **Delete**; **Access...** (per role:
    See, Download, Upload; no row = all three).
  - In a library, **Add... / Edit...** a file entry: Filename, Type (PRG SEQ USR D64 D81),
    Description, Server Path (a file inside the library's folder; `..` and absolute paths are
    refused). **Delete** (optionally the file on the server too). Bulk adding of files copied
    into a folder is still to come.
- **Downloads:** PRG, SEQ and USR go to drive 8-11 under a name (16 characters); D64 and D81
  go to a folder of the SD card the user browses, under an 8.3 name. Nothing is ever
  overwritten: a name that's taken is refused before anything is sent. A transfer window
  shows a progress bar and the bytes so far, and Close when it's over.
- **Uploads:** from drive 8-11 (its directory) or the SD card (its folders and images), with a
  Filename and a Description. The file is stored as `filelibs/<folder>/<name>.<type>`. Held
  uploads are seen only by moderators and the uploader (marked `?`); the moderators get a
  toast, and the uploader gets one when it's approved.
- **The client's disks** are reached through `S.LOCAL_DIR` / `SAVE_BEGIN` / `LOAD_FILE`
  (`docs/DESIGN.md`, "File transfers and local storage"). `HELLO`'s caps say which the client
  can do, and the server only offers those.

## Broadcast

**Admin > Broadcast...** (`admin.broadcast`; window 31, a small dialog) sends one line to
everyone signed on. Send is greyed until something is typed.
- Every client shows "To all users:  *message*" across the whole bottom row of the screen,
  yellow on red, for 20 seconds or until clicked (`S.BROADCAST` `$23`: seconds, text of at
  most 79 characters).
- It takes no input, and a toast arriving meanwhile goes one row up.
- The server log records who sent what.

## Server Log

Everything the server logs goes to the console as before, and into the database's `log`
table (`meganet/serverlog.py`), so admins can read it without the console.

- **What's in it:**
  - Every `session.log()` line: connections (with the address), sign-ons, failed sign-ons,
    and what people do in each area (posts, uploads, downloads, moderators' and admins'
    changes). Chat lines and message texts aren't logged, only that something was sent.
  - `session.warn()`: refusals (no permission), suspicious client messages (karma),
    failed transfers.
  - Errors: a crash in a message handler is logged with its traceback, under the area
    whose code crashed; so is a crashed background task (asyncio) and anything else on the
    `meganet` logger.
- **Each row has** the time, the level (info, warning, error), the area (`serverlog.AREAS`:
  by default the module that logged it, so `filelib.py` is `files`), the session number,
  the screen name then, and the text. Rows from one connection share a connection number
  (the id of its "connected from" row), so the sign-on before the name is known can be
  found too.
- **Admin > Server Log...** (`admin.log`, window 49):
  - Filters: Area, Show (Everything / Warnings, errors / Errors only), User (part of a
    screen name) and Find (part of the text). Search runs them; the list shows the newest
    200 matches, Older and Newer page through the rest (they count back from the newest
    row when Search ran, so new rows don't shift the pages).
  - A row's mark after the time: `!` a warning, `#` an error. Picking a row shows all of it
    below, tracebacks included.
  - **Session** (or a double click) shows every row of that row's connection, whatever the
    filters say; the button reads **All** then, and goes back to them.
- **How long:** rows older than System Settings' "Keep log" days (default 90, at most
  3650) are deleted at start-up and once an hour.

## Desktop icons

`meganet/desktop.py`: icons down the left and right edges of the client's desktop, under the
windows. Each is a 32x16 picture (the client's pixels are twice as tall, so it looks square)
with a label of one or two lines.
- **Left:** **Chat**, **Message Boards**, **File Library** (Members and up, `files.download`;
  "Coming soon." for now) and **Games**.
- **Right:** **Who's Online** (two people), **News** (a newspaper; `news.read`) and **Voting**
  (a ballot going into a box; `polls.vote`).
- **Server-driven:** `ICONS` are text pictures, one character a pixel (`PALETTE` maps them to
  the GUI's colours 0-15, `.` is see-through). `DESKTOP` (left) and `DESKTOP_RIGHT` list the
  icons with the permission each needs and the action it runs. Only icons the user may use
  are sent, and each column follows permission changes.
- **Messages:** `S.DESK_ICON` `$1F` (slot, two label lines, 512 bytes of pixels; an empty
  line 1 removes the icon). Slots 0-7 fill columns of 4 from the left edge, slots 8-11
  (`DESK_LEFT` up) the column at the right edge; a client older than that ignores slots
  8-11. A double click sends `C.DESK_OPEN` `$8C` (slot).
- **At sign-on**, a **"One moment..."** window opens first: modal, with no close box and a
  progress bar. It stays while the icons arrive one at a time (`PACE` = 0.15 s between them),
  then it closes and the welcome window opens. For a new account, the "account set up"
  window opens instead.
- The client keeps the icons in attic RAM only for the session. Signing off clears them,
  and nothing is written to disk.

## Status, Who's Online and instant messages

**Status** (the menu right before Window; `meganet/presence.py`):
- Available (the default at sign-on), Away or Offline. The current one is marked "*".
- **The status dot:** the menu bar shows it as a dot just left of the connectivity icon
  (`SLOT_STATUS`): green Available, yellow Away, dark grey Offline. Clicking it switches
  Available to Away, and Away or Offline to Available.
- **Auto-Away:** after a number of minutes without activity an Available user becomes Away,
  and back with their next activity. Activity is any message except the client's own
  connectivity PINGs and a click on the status dot (so clicking the dot while auto-Away
  goes to Available, not back to Away).
  - Admins set the minutes in **Admin > System Settings...** (window 29, `admin.settings`;
    the `away_minutes` setting, default 10, 0 = never). The same window has **New users can
    send instant messages** (off by default: it gives or takes `im.send` from the role new
    accounts get, so the Roles window shows the same) and **New users can receive instant
    messages** (on by default; the `im_new_users_receive` setting).
  - An Away picked by hand stays until changed.
- **Offline** users are hidden from everyone but admins (`screens.is_admin`): in Who's Online,
  User Search's "*" and instant messages. Pages don't go to an Offline admin.

**Who's Online** (window 8, 300x136) and **User Search** have a minimize box
(`WFlag.MINIMIZE`, which the client handles by itself).

**Who's Online:**
- One row each: name and (Status). Admins also see the role, and the Offline users.
- **Send Message...** (greyed until someone you can message is picked, or without `im.send`;
  a double-click does the same) opens the instant-message window.

**Instant messages** (`meganet/im.py`; sending needs `im.send`, Members and up; anyone
receives unless System Settings stops New Users receiving):
- When a rule stops a message (the sender's role can't send, or the person picked is a New
  User who can't receive), Send / Send Message... is greyed and the reason shows: on Who's
  Online's top line, and once in the IM window ("New users can't send messages.").
- "IM: *name*" (a dynamic window id, 360x120): the conversation, a line to type, Send.
- **Arriving, they don't interrupt.** If your window for that person isn't open, you get a
  **toast** and the **speech-bubble icon** (slot 5) until you read them.
  - The toast (`S.TOAST` `$1E`) is a short yellow line at the bottom right of the screen for
    8 seconds. It isn't a window: nothing takes the keyboard or the mouse from what you're
    doing.
  - Clicking the toast or the icon opens the conversation with unread messages.
- Messages to someone Away are delivered, and the sender is told once ("bob is away").
  Offline counts as not signed on, except for admins.
- Conversations live in memory while both are signed on (the last 100 lines), so closing and
  opening the window keeps them. A partner signing off is noted in the window.

## Message Boards

Areas > Message Boards (`meganet/boards.py`, `boards.read`). Forums hold topics, and topics hold
posts. **New** means posted since the user's previous sign-on (`session.previous_login`; on
a first sign-on everything is new), so it is the same for the whole session.

- **One window** (22, 560x160) shows one of three views and is sent again as you move between
  them:
  - **Forums:** name, topics, new posts, "locked" (and "limited" for moderators, when a role's
    access is cut); a heading with the new posts since the last sign-on; Open (or a
    double-click).
  - **A forum:** its topics, the most recently posted in first ("*" = new posts in it,
    subject, who started it, replies, last post); Read, New Topic, Back.
  - **A topic:** its posts ("*" = new, author, date), the picked one under them (Subject,
    From, Date, the text). It opens at the first new post. Reply, Back. A drop-down on the
    column heading's row (`AreaWindow.list_option`, its right edge on the list's) puts them
    **By Date** (oldest first, the default) or **Newest** first; the picked post stays
    picked, and the order is kept for the rest of the session.
- **Writing** (window 23, `compose.py`): New Topic asks for a subject and the text, Reply
  for the text. You need `boards.post`, the forum's Post access for your role, and the forum
  not locked. After Send the window shows the topic at your post. Everyone with the boards
  open sees new topics and posts at once.
- **Moderators** (`boards.moderate`, Moderator and Sysop) see every forum and get more controls:
  - In the forums view: a Forum name box, New, Rename, Delete (asks first, window 25; it
    takes the topics and posts with it), Lock / Unlock and Access....
  - Locked: nobody but moderators may post, and reading goes on.
  - Access... (window 24, modal): a Read and a Post check box per role (up to 6 roles);
    Post implies Read. Roles marked "*" have no `boards.read` at all.
  - A role's row is stored only when it differs from the default, which is read and post as
    far as the role's own permissions allow (`forum_access`).
  - In a forum: Delete Topic. In a topic: Delete Post; the topic goes with its last post.
    Both ask first (window 25).
  - Every handler checks `boards.moderate` (or read/post) again.
- **Tables:**
  - `forums` (id, name, locked, created);
  - `forum_access` (forum_id, role_id, can_read, can_post);
  - `topics` (id, forum_id, subject, author, created, last_post);
  - `posts` (id, topic_id, author, posted, body).
- A new database starts with one forum, General.

## Chat Rooms

Areas > Chat Rooms (`meganet/chat.py`, `chat.use`; also the Chat desktop icon) takes you
back to your room, or else opens the Chat Rooms list to pick one from (not straight into the
Lobby). You are in one room at a time: joining another leaves the one you were in.

- **The room** (window 2, 624x160, titled with the room's name):
  - the topic, the conversation (488 px wide), and who is here (a 112 px list at the right
    under "Here (* muted)": "*" marks the muted);
  - moderators get their buttons in a row under the conversation (their window is 171
    high, the conversation 9 px shorter);
  - a line to type (it has the keyboard when the room opens) with Send, plus Rooms... and
    the close box leaves. RETURN sends.
- **Chat Rooms** (window 26, 400x160) lists the rooms and how many people are in each.
  - Go joins the room picked in the list.
  - Under a line and a bold **Create A Room** heading: Room name, Private and **Create
    Room**. It makes a member room (`chat.rooms`, Members and up), or joins the room of that
    name if there is one, private ones included (the way into a private room).
- **Kinds of room:**
  - Permanent rooms are kept in `chat_rooms` (name, topic, private). A new database has the
    Lobby, and the Lobby can't be deleted.
  - Member rooms live in memory and go when the last person leaves.
  - A private room isn't listed, except to moderators, and is joined by typing its name.
- **Moderators** (`chat.moderate`):
  - In the room: Kick, Mute / Unmute, Ban, Unban... (window 27), Karma + / Karma - (for the
    person picked; picking someone shows their Karma Points), and Topic (sets the line typed
    as the topic; typing nothing clears it).
  - In Chat Rooms, under Admin Tools: New (a permanent room, named in the Name box) and
    Delete (asks first, window 50, saying how many are in it; then everyone in it is told
    and put out). Everyone gets Make A Room: Name, Private and Create.
  - Kick: out of the room. Mute: no talking there until unmuted or they leave. Ban: out, and
    kept out until unbanned or the server restarts (a member room's bans go with it).
  - Moderators can't act on other moderators, unless they are an admin (`admin.users`) acting
    on a moderator who isn't.
  - A moderator gives one user Karma +/- at most twice a day.

## Karma Points

Every user has Karma Points, 0-100 (`users.karma`, `meganet/karma.py`): how well they behave.

- **Starting points:** new accounts start at 20 (Low). The first account starts at 100.
  Accounts from before karma start at 50.
- **Levels:** under 10 Very low, under 30 Low, under 60 OK, under 85 Good, else Excellent.
- **Gains, automatic, while all goes well:**
  - +1 a message-board post, at most 2 a day;
  - +1 every 25 chat lines, at most 2 a day;
  - +1 for signing on, once a day.
  - Nothing is gained within 7 days of any loss, and automatic gains stop at 70.
- **Losses:**
  - kicked -3, banned -5, muted -1;
  - a moderator's Karma - is -5 (Karma + is +5);
  - suspicious client activity -5, once a session: after 5 events for things the server never
    sent (forged menu picks, icon clicks, clicks on windows or gadgets that aren't there).
- **Alerts:** falling to 10 or below sends the admins a "Karma alert" message (Admin >
  Messages from users) with the reason and who did it.
- **The User Editor:**
  - shows Karma on its own row (with its level), and in the list;
  - Save sets it (logged "set by an admin");
  - Low Karma lists everyone under 30, lowest first; All Users goes back;
  - History (window 28) shows the last 30 changes, their reasons and who made them.
- Every change goes in `karma_log` (user, by, delta, karma, reason, at).

## My Account

MegaNet > My Account (client menu, MENU_PICK $22; `meganet/account.py`): window 9, centred,
client area 388x171. Labels in one column (x 4, 112 wide), fields in a second (x 124, 260
wide: 8 px after "Email Address:"), rows 14 px apart (tight, so Karma Points fits in the
client's 171):

| Row | Gadgets (x, y, w, h) |
|---|---|
| Username | Label (124, 4, 96, 10); "Role: ..." Label (220, 4, 164, 10) |
| First Name | TextBox (124, 16, 166, 12): required, 20 characters |
| Last Name | TextBox (124, 30, 166, 12): required, 20 characters |
| Email Address | TextBox (124, 44, 260, 12): 63 characters, scrolls |
| Location | TextBox (124, 58, 260, 12) |
| Birthdate | DropDown Month (124, 72, 48, 12) "--", Jan..Dec; Day (176, 72, 40, 12) "--", 1..31; Year (220, 72, 56, 12) "--", this year down to 1960 |
| About Me | Edit (124, 86, 260, 30): 3 lines visible, 30 characters a line, up to 8 lines |
| Last Login | Label (124, 119): the sign-on before this one |
| Karma Points | Label (124, 133): the user's karma and its level, "42 (OK)" (shown, not edited) |
| status | Label (4, 143, 380, 10): 47 characters |
| buttons | Reset Password... (4, 153, 144, 16); OK (248, 153, 64, 16, default); Cancel (320, 153, 64, 16) |

OK checks the first and last names (required: letters, spaces, ' - and ., at most 20
characters; an account made before they existed must fill them in to save), the email (empty, or something@host.domain, at most 63 characters, as for Location),
the birthdate (all three "--" = none; otherwise all three set, a day that exists in that month
and year, not in the future) and About Me (at most 8 lines once wrapped to 30 characters). If
all is well it saves and closes the window; otherwise it stays open and says what's wrong in
the status line. Cancel (and the close box) closes without saving. The birthdate is stored as
YYYY-MM-DD or empty; a stored year before 1960 (the old form allowed 1900 on) is added to the
Year list so it isn't lost. About Me is stored as lines joined with "\n"; one saved by the old
three-box form (lines up to 63 characters) is kept as it is and shown wrapped to 30 characters.
The fields are `users` columns (first_name, last_name, email, location, birthdate, about,
last_login), added to an
older database with ALTER TABLE; `last_login` is read and then updated at each sign-on
(`db.record_login`).

**Reset Password** (window 19, 320x84, modal): Current password, New password, Confirm; OK and
Cancel. It checks the current password, the rules for new ones (4 characters) and that the two
match, and reports in its status line. Three wrong current passwords close it, and it is refused
for a minute after that.

## Adding a screen

Build a `Window`, add gadgets with callbacks, show it:

```python
from meganet.ui import Window, Button, TextBox

win = Window("Find a user", 200, 50, 240, 60, win_id=20)
name = win.add(TextBox(8, 8, 150, 12))
win.add(Button(166, 6, 60, 16, "Find", on_click=lambda b: b.session.alert("Find", name.value)))
win.show(session)
```

Fixed screens use window ids below `$40` (`screens.py` lists them: 1-19 are taken); leave `win_id` out and the
session picks a free id from `$40` up. Keep windows below the menu bar: `y >= 11` and
`y + h + 18 <= 200`, so the client area is at most 632x171 (`protocol.window_fits`).
`Window.centred("Title", w, h, win_id=...)` places a window in the middle of that area.

## Internet

**Areas > Internet** (`internet.use`: Members and up at first) opens window 56, a list of
services from outside MegaNet; pick one and Open (or double-click). Each is a module in
`meganet/internet/` with an `Integration` subclass (`name`, `description`, `permission`,
`open(session)`, `disconnected`, `permissions_changed`), found at start-up; give it its own
key with `permissions.register(..., like="internet.use")`.

**Web Browser** (`internet.web`; `internet/web.py`, window 57, 624x166): web pages as text.
- Type an address (`https://` is added) or some words (a DuckDuckGo search: its result
  links are unwrapped to the real sites), then Go or RETURN. Back goes to the page before
  (kept, not fetched again; 20 of them).
- The page: its title, the text on the left (wrapped to the view, 120 lines a page: Prev
  Page / Next Page), the links on the right: link n is [n] in the text; a click opens it.
  The text view opens at the top (`TextView.set_lines(top=True)`: SET_VALUE scrolls it).
- What it does with HTML (`webtext.py`): scripts, styles, `<nav>`, and elements that are
  `hidden`, `aria-hidden` or `role="navigation"` are left out; with a `<main>`, only it is
  shown. Headings h1/h2 in capitals, lists with `*` / `1.`, `<pre>` kept, pictures as their
  `[alt text]`, text boxes as `[______]`. Everything becomes plain ASCII (curly quotes
  straight, accents off).
- Pages load in the background (a task and a thread): "Loading ..." shows, the session can
  do anything else, and another Go replaces the load. 15 s at most, 1 MB at most; only
  `text/html` and `text/plain`.
- **Safety:** only http and https, and never a host with a private, loopback, link-local or
  multicast address, redirects included, so the server can't be used to reach its own
  network. Every URL goes in the Server Log (area `internet`). The server's own HTTPS is
  verified with Python's certificate list, or `--cafile`.
- Not yet: forms (only the address box searches), cookies and sign-ins, pictures.

## Art Gallery

**Areas > Art Gallery** (`gallery.view`; `meganet/gallery/`, windows 58-63) has two views in
one area window (58), like the File Library:
- **The galleries:** title and pictures; the picked one's description under the list; Open
  (or double-click). Holders of `gallery.moderate` (Moderators and up) get Admin Tools: New...
  and Edit... (window 59: Title, Description) and Delete (window 63: the pictures go too).
- **A gallery's pictures:** title, artist, date added; under the list the picked one's size,
  colours, views and description. View (or double-click) and Slideshow for everyone;
  Upload and Paint with `gallery.upload` (Members and up); Back. Edit... (window 60: Title,
  Description) and Delete for moderators (Admin Tools) and for a picture's own artist (Your
  Pictures).
- **View** shows the picture over the whole screen; any key or click goes back.
  **Slideshow** starts at the picked picture: Space or a click shows the next, Esc (or a
  right click) goes back, and so does Space on the last one ("That was the last picture.").
  While a picture shows, the next one goes to the client in the background; if it isn't all
  there when Space comes, the desktop comes back with a Loading window (62: what, a progress
  bar, Cancel) until it is. A picture the client still holds from before isn't sent again.
- **Upload** (window 61): a drive (8-11), an IFF file from its directory (PRG, SEQ or USR),
  a Title (from the file name) and a Description. It comes over like a File Library upload
  (the transfer window, 45), then the server reads it: anything that isn't a picture it can
  show is refused with the reason, nothing kept. Up to 512 KB.
- **On the server:** each picture is the uploaded IFF, `galleries/<gallery id>/<picture
  id>.iff` (`--galleries` moves the folder), with its row in `gallery_pictures`. Shown, it's
  converted (`gallery/picture.py`; 8 kept): ILBM or PBM, 1-8 planes, ByteRun1 or not, EHB,
  HAM6 / HAM8 (median cut to 255 colours); fitted to 320x200 (shown doubled across: a lores
  picture) or 640x200 (wider ones), keeping its shape (from the size and CAMG; BMHD's aspect
  only when it's far from that, as many programs write 1:1), centred on its darkest colour,
  which is also the border; colour 255 (the client's colour-RAM colour) is moved to the
  nearest other. The pixels go in the client's framebuffer order, PackBits-packed
  (`S.RESOURCE_PACKED`) into resource slots 2-3 or 4-5 (two pictures; a hires one takes both
  of its pair), paced 4 KB ahead of the network. Clients without `Caps.PICTURE` are told
  they can't show pictures.
- **Paint** (`gallery/paint.py`; with `gallery.upload`, clients with `Caps.CANVAS`): the
  server keeps the picture (320x200, 32 colours) and does all the painting; the client shows
  it as its desktop (`S.CANVAS`: the windows open then are hidden, and the menu bar), sends
  the mouse on it (`C.CANVAS`), and gets back the pixels that changed (`S.CANVAS_RECT`,
  packed). While the button is held the client draws a freehand stroke, or a line's or a
  box's 1-pixel outline, at once (`S.CANVAS_PEN`); the server's answer then covers it.
  - Paint (next to Upload) starts a new picture, or asks "This One" / "New" when the picked
    picture is yours (or you're a moderator). Painting on one needs it to be 320x200 with
    up to 32 colours.
  - The tool window (over the picture: drag it, or minimize it to see everything): Draw,
    Line, Box, Oval, Fill, Pick; Solid (filled boxes and ovals); Size (a square brush of
    1-8); the 32-colour palette (a GRID, the colour framed; a right click on the picture
    picks the colour under it); Undo (8 steps), Clear, Save..., Done.
  - Save... (title, description) writes an ILBM into the gallery: a new picture, or the one
    you're painting on again (clients that held it get it again: the cache key has the
    file's time). Done or the close box asks "Leave Paint?" if there are changes not saved.
  - The picture goes to resource slot 6, the palette swatches to slot 7. Palette entries
    16-47 hold its colours (`CANVAS_FIRST`), so the GUI's 0-15 stay for the tool window.
- Not yet: editing a palette's colours, text, brushes cut from the picture, magnify,
  painting on pictures of more than 32 colours; uploads from the SD card; thumbnails.

## Adding a game

Drop a Python file into `meganet/games/` with a `Game` subclass and restart the server. See
[meganet/games/README.md](meganet/games/README.md).

**Chess** (`games/chess.py`) is the first game with a lobby and a picture board:
- Areas > Games > Chess > Join opens the **Chess Lobby** (window 51): everyone waiting, and
  the games being played. Pick someone and Challenge... (or double-click them); they get
  "X challenges you to a game of Chess." with Accept / Decline (window 52, and a chime). One
  challenge out at a time (Cancel withdraws it); challenging someone who has challenged you
  starts the game. Leaving the lobby, or starting a game, calls off every challenge to and
  from you, and the others get a toast.
- The game window (a dynamic id, 624x156): the board from your side, the status ("Your move
  (White)", "Check!", "bob offers a draw."), a chat with the moves in it ("12. Nf3"), and
  Offer Draw (it becomes Accept Draw for the other player; the offer lapses when they move),
  Resign (asks first, window 53), Rematch (both click it: colours swap) and Lobby. Closing the
  window or signing off during a game loses it.
- Click a piece of yours: red frame; its moves show as dots, captures with a red frame. Click
  one to move; promotion asks for the piece (window 54). The last move's squares have a gold
  frame. Moves out of turn, illegal moves and clicks on the other side's pieces do nothing.
- The tiles (28 of 32 x 16 bytes, 14 KB) go to resource slot 1 once a connection
  (`session.send_resource`), under a "Loading Chess" window (55, modal) whose progress bar
  moves as they arrive; clients without `Caps.GRID` are refused at the lobby. Clients with
  `Caps.PICTURE` get them packed (`S.RESOURCE_PACKED`, PackBits): 3 KB instead of 14.

**One** (`games/one.py`, rules in `one_rules.py`, the cards in `one_art.py`) is the card game
for 2-4, by the usual official rules: 108 cards; match the colour, number or symbol, or play
a Wild; Skip, Reverse (a Skip with two), Draw Two, Wild, and Wild Draw Four (only with
nothing of the colour, but you may bluff: the next player may challenge; guilty draws 4,
otherwise the challenger draws 6); draw one, and play it at once if it goes or Pass; call
One! on your last card or be caught for 2; the round's winner scores the others' cards
(numbers face value, actions 20, Wilds 50) and the first to 500 wins.
- Areas > Games > One > Join asks (a dynamic window) **Wait for Others** (the queue: four
  start at once; Start Now with two or three) or **vs Computer...** (1-3 computer players,
  and the game starts). Any game with `computer = True` gets this question.
- The table (a dynamic id, 624x134): the others in the order they play next (">" whose turn,
  their cards and scores), the draw pile and the top card (a Wild shows the colour named), the
  colour to match, two status lines, your hand (12 x 2 cards, sorted, cyan-framed when they
  can be played; "<" / ">" page through more than 24), Draw / Pass / One! / Catch! / Next
  Round, the play-by-play and chat, and Leave (back to the Games window). A Wild asks for its
  colour; a Wild Draw Four played at you asks Challenge / Draw 4 (both modal, dynamic ids).
- The computer waits 1.5 s before each move (`tick()`), names its best colour, plays a Wild
  Draw Four only honestly, attacks a player down to two cards, challenges a quarter of the
  time, and catches a forgotten One! half the time. A person who leaves is replaced by the
  computer; the game ends when no people are left.
- The cards: 64 tiles of 32 x 22 (45 KB, 17 KB packed) in resource slot 8. Every pixel is
  doubled across (checked when the module loads), so a card is exactly one 16-colour hardware
  sprite.
- Cards fly (`Caps.SPRITES` clients, `session.fly`, the two sprites in turn): a card played lifts out of the
  hand (or from that player's row) and flies to the pile, which keeps showing the card under
  it until it lands; a card drawn flies from the deck, face up into your hand (to the cell it
  will take, left empty till then) or face down to the other player's row; several drawn fly
  one after another. 14 frames a flight (`MEGANET_ONE_FLY_FRAMES` slows them down for tests).

## Sprites over the GUI

Clients with `Caps.SPRITES` (`client-src/sprites.asm`) have two sprites the server can make
from any picture it has sent to a resource slot (a grid's tiles, say), and move over the
screen above every window (below the pointer):

| Call | Does |
|---|---|
| `session.sprite_show(n, window, slot, offset, w, h, pos, colours, stride=None, step=1)` | Sprite n (0-1) becomes the picture at byte `offset` of resource slot `slot`: `w` pixels across (up to 16) `step` bytes apart, `h` rows (up to 64) `stride` bytes apart. `colours` lists the palette indexes it shows (up to 15, `protocol.palette_rgb` knows them); every other byte is see-through. It shows at `pos` in `window`'s client area and stays. |
| `session.sprite_move(n, start, end, frames, hide=False)` | It glides from `start` to `end` in `frames` frames (50 a second), then goes if `hide`. |
| `session.sprite_off(n=0xFF)` | Gone (0xFF: both). |
| `session.fly(window, slot, offset, w, h, start, end, frames, colours, step=1, n=0)` | Show, glide and go: a card played, a piece taken. |

Each returns False, sending nothing, to a client without the capability, so a game works the
same without it. A sprite is 16 pixels across in 320-wide units, so 32 screen pixels: art
drawn with every pixel doubled across (as One's cards and chess's pieces are) is one sprite at
full detail with `step=2`. One's flights (`games/one.py`) are the example.

## Publishing a client update

Copy the built client files into `updates/` and write `updates/manifest.json`. The client is
the program and its overlays (`MEGANET`, `OVL0`, `OVL1`: `client-src/overlays.asm`); send them
all, since they are built together:

```json
{"build": 3, "message": "New version", "files": ["CLIENT", "OVL0"]}
```

Every client whose build is lower is sent the files before it may sign on.
