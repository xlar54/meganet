"""The screens the server sends: the menu bar, the welcome window, Who's Online, My Account
and the chat lobby. More areas come later.

Fixed window ids (all below session.FIRST_DYNAMIC_WIN):
    1 = welcome, 2 = the chat room you are in (chat.py), 26-27 chat, 3 = games (games/lobby.py),
    4-7 = administration (admin.py), 8 = Who's Online, 9 = My Account, 10 = User Search,
    11 = the Message of the Day editor (admin.py), 12 = Help > Getting Around,
    13-16 = Page Admin and the messages to the admins (pages.py),
    17-18 = Private Messages (mail.py), 19 = Reset Password (account.py),
    22-25 = Message Boards (boards.py),
    20 = the New User sign-up wizard (signup.py, before sign-on);
    private chats with an admin take dynamic ids

The menu bar (MENU_TREE) offers only what the user's role allows (permissions.py), and every
item checks its permission again when it's picked, since a client can send any MENU_PICK it
likes. Picks of ids that weren't in the menu sent to that session are ignored (ui.Menu).
"""

import time

from . import __version__
from . import permissions as perms
from .account import Account, WIN_ACCOUNT
from .admin import Admin
from .boards import Boards
from .chat import Chat
from .desktop import Desktop
from .polls import Polls
from .im import IMs
from .presence import Presence, STATUSES, LABELS
from . import karma
from .mail import Mail
from .pages import Pages
from .signup import Signup
from .protocol import (WFlag, GFlag, MENU_SEPARATOR, VERSION, SLOT_PAGE, SLOT_ADMIN_MAIL,
                       SLOT_MAIL, SLOT_NEW_USER, SLOT_IM, MENU_MY_ACCOUNT, MENU_LATE, Icon,
                       S, Writer, clean_text, BROADCAST_MAX, BROADCAST_SECS)
from .ui import Window, Button, Label, TextBox, ListBox, TextView, Menu, add_buttons, closer

WIN_WELCOME = 1
WIN_LOBBY = 2
WIN_WHO = 8
WIN_SEARCH = 10
WIN_HELP = 12
SEARCH_MAX = 100             # rows a search shows

# Menu ids. They are fixed, so an item keeps its id whichever others a user's role hides.
# Titles 1-$0F; each title's items in its own block of 16.
M_AREAS, M_MEMBERS, M_HELP = 0x01, 0x02, 0x04
M_ADMIN = MENU_LATE              # $E0: right of the client's Window menu
M_BOARDS, M_CHAT, M_NEWS, M_FILES, M_GAMES = 0x10, 0x11, 0x12, 0x13, 0x14
M_GALLERY, M_MUSIC, M_MAIL = 0x15, 0x16, 0x17
M_VOTING = 0x18
M_WHO, M_MEMBERS_SEP, M_SEARCH = 0x20, 0x21, 0x23     # $21: no longer used (was a separator)
M_ACCOUNT = MENU_MY_ACCOUNT      # $22: sent by the client's own MegaNet > My Account
M_ROLES, M_USERS, M_MOTD, M_ADMIN_MSGS = 0x30, 0x31, 0x32, 0x33
M_ABOUT, M_GETTING_AROUND, M_PAGE_ADMIN = 0x40, 0x41, 0x42
M_STATUS = 0x05                  # the last title before the client's Window menu
M_AVAILABLE, M_AWAY, M_OFFLINE = 0x50, 0x51, 0x52
M_SETTINGS = 0x34
M_BROADCAST = 0x35
STATUS_ITEMS = dict(zip((M_AVAILABLE, M_AWAY, M_OFFLINE), STATUSES))
WIN_WHO_W, WIN_WHO_H = 300, 136

# (id, label, permission or None for everyone signed on, action name on Screens)
MENU_TREE = [
    (M_AREAS, "Areas", [
        (M_NEWS, "News", "news.read", "coming_soon"),
        (M_BOARDS, "Message Boards", "boards.read", "open_boards"),
        (M_CHAT, "Chat Rooms", "chat.use", "open_chat"),
        (M_MAIL, "Private Messages", perms.MAIL_USE, "open_mail"),
        (M_GALLERY, "Art Gallery", "gallery.view", "coming_soon"),
        (M_MUSIC, "SID Music", "music.listen", "coming_soon"),
        (M_FILES, "File Library", "files.download", "coming_soon"),
        (M_GAMES, "Games", "games.play", "open_games"),
        (M_VOTING, "Voting", perms.POLLS_VOTE, "open_voting"),
    ]),
    (M_MEMBERS, "Members", [
        (M_WHO, "Who's Online", None, "open_who"),
        (M_SEARCH, "User Search...", None, "open_search"),
    ]),
    (M_HELP, "Help", [
        (M_ABOUT, "About MegaNet", None, "about"),
        (M_GETTING_AROUND, "Getting Around", None, "getting_around"),
        (M_PAGE_ADMIN, "Page Admin", None, "page_admin"),
    ]),
    # Your status: the current one is marked "*" (menu_for). Right before Window.
    (M_STATUS, "Status", [
        (M_AVAILABLE, "Available", None, "set_status"),
        (M_AWAY, "Away", None, "set_status"),
        (M_OFFLINE, "Offline", None, "set_status"),
    ]),
    # Only for admins (is_admin: Moderators answer pages but don't get it), each item only
    # with its key. Its id puts it right of the client's Window menu.
    (M_ADMIN, "Admin", [
        (M_USERS, "User Editor...", perms.ADMIN_USERS, "open_users"),
        (M_ROLES, "Roles...", perms.ADMIN_ROLES, "open_roles"),
        (M_MOTD, "Message of the Day...", perms.ADMIN_MOTD, "open_motd"),
        (M_ADMIN_MSGS, "Messages from users...", perms.ADMIN_PAGES, "open_admin_messages"),
        (M_SETTINGS, "System Settings...", perms.ADMIN_SETTINGS, "open_settings"),
        (M_BROADCAST, "Broadcast...", perms.ADMIN_BROADCAST, "open_broadcast"),
    ]),
]

DENIED = "Your account can't use %s."
ADMIN_KEYS = (perms.ADMIN_USERS, perms.ADMIN_ROLES, perms.ADMIN_MOTD, perms.ADMIN_SETTINGS,
              perms.ADMIN_BROADCAST)


def is_admin(session):
    """An admin: may edit users, roles or the message of the day (admin.pages alone, a
    Moderator's, isn't enough). Only admins get the Admin menu."""
    return any(session.can(k) for k in ADMIN_KEYS)


TITLE_NEEDS = {M_ADMIN: is_admin}     # titles shown only when this says so


def version_line():
    """The welcome window's version line."""
    return "MegaNet server %s (protocol %d)" % (__version__, VERSION)


def who_row(viewer, s):
    """Who's Online: the name and (Status); admins see the role too."""
    status = "(%s)" % LABELS[s.status]
    if is_admin(viewer):
        return ("%-11s%-12s%s" % (s.user, status, s.role or "-"))[:33]
    return "%-11s%s" % (s.user, status)


class Screens:
    def __init__(self, server):
        self.server = server
        self.chat = Chat(server)
        self.admin = Admin(server)
        self.pages = Pages(server)
        self.mail = Mail(server)
        self.boards = Boards(server)
        self.account = Account(server)
        self.signup = Signup(server)
        self.who = {}                # session -> its open Who's Online window
        self.presence = Presence(server)
        self.ims = IMs(server)
        self.desktop = Desktop(self)
        self.polls = Polls(server)

    def signed_on(self, session, welcome=True, after=None):
        """Everything a session gets on signing on. The desktop icons come first, under a
        "One moment..." window; then the welcome window, or (`welcome` False) `after()`: the
        sign-up wizard's "account set up" window, which shows the welcome after it."""
        self.send_menu(session)
        then = (lambda: self.welcome(session)) if welcome else after
        self.desktop.start(session, then)
        self.pages.signed_on(session)
        self.mail.signed_on(session)
        self.new_users_changed()          # (a new account is a new user for the admins)
        karma.earn(self.server, session.user_id, "signed on")
        self.refresh_who()

    def notify_click(self, session, slot):
        """C.NOTIFY_CLICK for a slot whose icon this session was sent (session.py checks)."""
        if slot in (SLOT_PAGE, SLOT_ADMIN_MAIL):
            return self.pages.notify_click(session, slot)
        if slot == SLOT_MAIL:
            return self.mail.notify_click(session, slot)
        if slot == SLOT_IM:
            return self.ims.notify_click(session, slot)
        if slot == SLOT_NEW_USER:
            new = self.server.db.new_users()
            return self.admin.open_users(session, new[0]["id"] if new else None)
        return None

    def new_users_changed(self):
        """The person icon for every signed-on holder of admin.users while there are users
        in the default role (New User); gone when there are none."""
        n = len(self.server.db.new_users())
        for s in self.online():
            if n and s.can(perms.ADMIN_USERS):
                s.set_notify(SLOT_NEW_USER, Icon.PERSON,
                             "1 new user" if n == 1 else "%d new users" % n)
            else:
                s.set_notify(SLOT_NEW_USER, Icon.NONE)

    # ---- the menu bar ----

    def menu_for(self, session):
        """The Menu this session may use: items filtered by session.can(), separators tidied,
        and titles left out when none of their items are left."""
        menu = Menu()
        for title_id, title, items in MENU_TREE:
            if title_id in TITLE_NEEDS and not TITLE_NEEDS[title_id](session):
                continue
            allowed = [it for it in items if it[2] is None or session.can(it[2])]
            # no separator at the start, the end, or twice in a row
            tidy = []
            for it in allowed:
                if it[1] == MENU_SEPARATOR and (not tidy or tidy[-1][1] == MENU_SEPARATOR):
                    continue
                tidy.append(it)
            while tidy and tidy[-1][1] == MENU_SEPARATOR:
                tidy.pop()
            if not tidy:
                continue
            menu.title(title_id, title)
            for item_id, label, key, action in tidy:
                if item_id in STATUS_ITEMS:              # the current status is marked
                    label = ("* " if STATUS_ITEMS[item_id] == session.status else "  ") + label
                if label == MENU_SEPARATOR:
                    menu.separator(item_id, title_id)
                else:
                    menu.item(item_id, title_id, label, self._pick(key, getattr(self, action)))
        # MegaNet > My Account is on the client's own menu: always accepted, never sent.
        menu.client_item(M_ACCOUNT, "My Account", self._pick(None, self.open_account))
        return menu

    def send_menu(self, session):
        self.menu_for(session).show(session)

    def _pick(self, key, action):
        """Wrap a menu action so it re-checks `key` when picked."""
        def pick(item):
            session = item.session
            if key is not None and not session.can(key):
                name = item.label.rstrip(".")
                session.log("refused menu %s: no %s" % (name, key))
                return session.alert(name, DENIED % name)
            return action(session, item)
        return pick

    # ---- menu actions: fn(session, item) ----

    def set_status(self, session, item):
        self.presence.set(session, STATUS_ITEMS[item.id])

    def open_settings(self, session, item=None):
        return self.admin.open_settings(session)

    def open_broadcast(self, session, item=None):
        return self.admin.open_broadcast(session)

    def broadcast(self, sender, text):
        """A message to everyone signed on (S.BROADCAST): the bottom row, yellow on red."""
        line = ("To all users:  " + clean_text(text).strip())[:BROADCAST_MAX]
        for s in self.online():
            s.send(S.BROADCAST, Writer().u8(BROADCAST_SECS).str(line))
        sender.log("broadcast: %s" % text)
        return len(self.online())

    def open_files(self, session, item=None):
        return session.alert("File Library", "Coming soon.")

    def status_changed(self, session):
        """Someone's status changed: their Status menu, and everyone's Who's Online."""
        self.send_menu(session)
        self.refresh_who()
        self.pages.refresh_icons()                # (an offline admin isn't paged)

    def coming_soon(self, session, item):
        session.alert(item.label, "Coming soon.")

    def open_chat(self, session, item=None):
        return self.chat.open(session)

    def open_games(self, session, item=None):
        return self.server.games.open(session)

    def open_roles(self, session, item):
        return self.admin.open_roles(session)

    def open_users(self, session, item):
        return self.admin.open_users(session)

    def open_motd(self, session, item):
        return self.admin.open_motd(session)

    def open_admin_messages(self, session, item):
        return self.pages.open_messages(session)

    def open_boards(self, session, item=None):
        return self.boards.open(session)

    def open_voting(self, session, item=None):
        return self.polls.open(session)

    def open_mail(self, session, item):
        return self.mail.open_inbox(session)

    def page_admin(self, session, item):
        return self.pages.page_admin(session)

    GETTING_AROUND = [
        "The menu bar along the top of the screen takes you everywhere. Click a title to "
        "drop down its menu, then click an item.",
        "",
        "Areas: chat, private messages, games and the other parts of MegaNet. Members: who's "
        "online, finding people, your account. Help: this, and Page Admin to ask an admin "
        "for help.",
        "",
        "Window (at the right end of the bar) lists your open windows: pick one to bring it "
        "to the front. Close a window with the box in its title bar.",
        "",
        "In a window, TAB moves to the next box and RETURN presses the button with the "
        "heavy border.",
        "",
        "MegaNet > Exit signs off and goes back to BASIC.",
    ]

    def getting_around(self, session, item=None):
        win = Window.centred("Getting Around", 400, 128, win_id=WIN_HELP, minimize=False)
        win.add(TextView(8, 4, 384, 100, self.GETTING_AROUND))
        add_buttons(win, [("OK", closer, GFlag.DEFAULT)], centre=True)
        win.show(session)

    def about(self, session, item):
        session.alert("About MegaNet", "MegaNet: a graphical BBS for the MEGA65. Server %s, "
                      "protocol version %d, %d signed on." % (__version__, VERSION,
                                                              len(self.visible(session))))

    def open_who(self, session, item=None):
        win = Window("Who's Online", 632 - WIN_WHO_W - 8 - 2, 24, WIN_WHO_W, WIN_WHO_H,
                     win_id=WIN_WHO, on_close=self._who_closed)
        win.count = win.add(Label(8, 2, 284, 10, ""))
        win.people = win.add(ListBox(8, 14, 284, 100, on_select=self._who_pick))
        win.im = win.add(Button(8, 118, 136, 16, "Send Message...", on_click=self._who_im))
        win.sessions, win.picked, win.viewer = [], None, session
        self.who[session] = win
        self._fill_who(win, session, send=False)
        win.show(session)

    def _who_pick(self, listbox, index, double):
        win = listbox.window
        if listbox.selected is None or listbox.selected >= len(win.sessions):
            return None
        win.picked = win.sessions[listbox.selected]
        self._who_buttons(win)
        return self._who_im(win.im) if double and win.im.enabled else None

    def _who_buttons(self, win, send=True):
        """Send Message... needs someone picked who can be messaged; if a rule stops it
        (New Users, a role without im.send), the top line says why."""
        viewer = win.viewer
        why = self.ims.rule(viewer, None if win.picked is viewer else win.picked)
        win.im.enable(win.picked is not None and self.ims.problem(viewer, win.picked) is None)
        text = why or win.count_text
        if send:
            win.count.set_text(text)
        else:
            win.count.text = text

    def _who_im(self, button):
        win = button.window
        viewer, partner = win.session, win.picked
        problem = self.ims.problem(viewer, partner)
        if problem:
            return viewer.alert("Instant Message", problem)
        return self.ims.open(viewer, partner)

    def open_account(self, session, item=None):
        return self.account.open(session)

    # ---- User Search ----

    def open_search(self, session, item=None):
        win = Window("User Search", 140, 30, 360, 140,
                     win_id=WIN_SEARCH)
        win.add(Label(8, 4, 48, 10, "Name:"))
        win.find = win.add(TextBox(56, 2, 200, 12))
        win.add(Button(264, 0, 88, 16, "Search", GFlag.DEFAULT, on_click=self._search))
        win.count = win.add(Label(8, 22, 344, 10, "Type part of a name, or nothing for everyone."))
        win.results = win.add(ListBox(8, 34, 344, 102))
        win.show(session)

    def _search(self, button):
        win = button.window
        find = win.find.value.strip()
        online = {s.user.lower() for s in self.visible(button.session)}
        found = self.server.db.users(find)
        rows = []
        for u in found[:SEARCH_MAX]:
            since = time.strftime("%Y-%m-%d", time.localtime(u["created"]))
            rows.append("%-17s%-11s%s%s" % (u["name"], (u["role"] or "-")[:10], since,
                                            " *" if u["name"].lower() in online else ""))
        if not found:
            win.count.set_text("Nobody matches \"%s\"." % find[:20])
        else:
            more = " (first %d)" % SEARCH_MAX if len(found) > SEARCH_MAX else ""
            win.count.set_text("%d found%s.  * = signed on now" % (len(found), more))
        win.results.set_rows(rows)

    # ---- the welcome window ----

    WELCOME_W, WELCOME_H = 416, 146          # client area; the window is centred
    MOTD_VIEW = (8, 14, 400, 98)             # the message of the day's TextView in it
    VERSION_Y = 114                          # the server's version, centred under it

    @classmethod
    def motd_columns(cls):
        """Characters per line of the message of the day on the client (it wraps there)."""
        return TextView(*cls.MOTD_VIEW).columns()

    def welcome(self, session, motd=None):
        """The welcome window: the user's role, the message of the day in a read-only text
        view (one APPEND per line; the client wraps and scrolls), and OK. `motd` replaces the
        saved message (the editor's Preview)."""
        lines = self.server.db.motd() if motd is None else list(motd)
        win = Window.centred("Welcome, %s" % session.user, self.WELCOME_W, self.WELCOME_H,
                             flags=WFlag.CLOSE | WFlag.MOVABLE, win_id=WIN_WELCOME,
                             minimize=False)
        win.add(Label(8, 2, 400, 10, "Message of the Day", GFlag.CENTRE))
        win.motd = win.add(TextView(*self.MOTD_VIEW, lines))
        win.version = win.add(Label(8, self.VERSION_Y, 400, 10, version_line(), GFlag.CENTRE))
        add_buttons(win, [("OK", closer, GFlag.DEFAULT)], centre=True)
        win.show(session)
        return win

    # ---- Who's Online ----

    def online(self):
        return [s for s in self.server.sessions if s.user is not None and not s.closed]

    def visible(self, viewer):
        """The signed-on users `viewer` may see (Offline ones only for admins)."""
        return [s for s in self.online() if Presence.visible(viewer, s)]

    def _fill_who(self, win, viewer, send=True):
        people = sorted(self.visible(viewer), key=lambda s: s.user.lower())
        win.sessions = people
        rows = [who_row(viewer, s) for s in people]
        win.count_text = "%d signed on" % len(people)
        if win.picked not in people:
            win.picked = None
        if send:
            win.people.set_rows(rows)
            if win.picked is not None:
                win.people.selected = people.index(win.picked)
                win.people.set_value(win.people.selected)
        else:
            win.people.rows = rows
        self._who_buttons(win, send)

    def refresh_who(self):
        for viewer, win in list(self.who.items()):
            self._fill_who(win, viewer)

    def im_rules_changed(self):
        """Who may message whom changed (System Settings, a role): Send buttons follow."""
        self.ims.settings_changed()
        for win in list(self.who.values()):
            if win.shown:
                self._who_buttons(win)

    def _who_closed(self, window):
        self.who.pop(window.session, None)

    # ---- keeping things in step ----

    def permissions_changed(self, session, old):
        """An admin changed the user's role or its permissions; `old` is (perms, role name)
        from before. Re-send the menu bar, and leave the areas they may no longer use."""
        self.chat.permissions_changed(session)
        self.admin.permissions_changed(session, old[0])
        self.pages.permissions_changed(session)
        self.mail.permissions_changed(session)
        self.boards.permissions_changed(session)
        self.polls.permissions_changed(session)
        self.new_users_changed()
        self.im_rules_changed()
        self.desktop.refresh(session)
        if (session.perms, session.role) == old:
            return
        self.send_menu(session)
        win = session.windows.get(WIN_WELCOME)
        if win is not None and hasattr(win, "role"):
            win.role.set_text("Role: %s" % (session.role or "none"))
        self.account.role_changed(session)
        if session.role != old[1]:
            self.refresh_who()

    def disconnected(self, session):
        self.chat.disconnected(session)
        self.admin.disconnected(session)
        self.mail.disconnected(session)
        self.boards.disconnected(session)
        self.polls.disconnected(session)
        self.ims.disconnected(session)
        self.pages.disconnected(session)
        self.who.pop(session, None)
        if session.user is not None:
            self.refresh_who()
