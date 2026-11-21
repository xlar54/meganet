"""Administration: the User Editor, Roles and Message of the Day windows (for holders of
admin.users / admin.roles / admin.motd), opened from the Admin menu on the menu bar
(screens.py).

    4 = Set Password (modal, from the User Editor): new password twice, OK, Cancel
    5 = Roles: the list of roles; pick one to edit its name, level and permissions;
        New Role, Rename, Delete, Save, and "Make Default" (the role new accounts get)
    6 = User Editor: a Find box and the list of users with their roles; for the one picked,
        First / Last Name, Email, Location, a Role drop-down, Joined and Last Login; Save and
        Set Password
    7 = "Delete a role that still has users?" (moves them to the default role)
    11 = Message of the Day: a line editor (list of lines, a text box for the picked one)

Every handler checks session.can() itself before it changes anything: the windows are only
offered to admins, but a client can send any CLICK or MENU_PICK it likes, and an admin can
lose the right while a window is open (the window closes then too).
"""

import asyncio
import textwrap
import time

from . import db as dbmod
from . import im
from . import karma
from . import permissions as perms
from .account import length_problem
from .db import MOTD_MAX_LINES
from .protocol import WFlag, GFlag, clean_text
from .ui import add_buttons, closer
from .ui import (Window, Button, Label, TextBox, Password, ListBox, DropDown, CheckBox, TextView,
                 TextArea)

WIN_SET_PASSWORD = 4
WIN_KARMA = 28                   # a user's karma history (from the User Editor)
WIN_SETTINGS = 29                # Admin > System Settings...
WIN_BROADCAST = 31               # Admin > Broadcast...
LOW_KARMA = 30                   # the User Editor's Low Karma list: below this
WIN_ROLES = 5
WIN_USERS = 6
WIN_CONFIRM = 7
WIN_MOTD = 11

PER_COLUMN = 8                  # permission check boxes per column in the Roles window
PER_PAGE = PER_COLUMN * 2
NEW_ROLE = "New Role"


def refuse(session, what, key):
    session.warn("refused %s: no %s" % (what, key))
    session.alert("Administration", "You don't have permission to do that.")


def guarded(key):
    """Decorator for a gadget callback: run it only if the session holds `key`."""
    def wrap(fn):
        def run(self, gadget, *args):
            session = gadget.session
            if not session.can(key):
                return refuse(session, fn.__name__, key)
            return fn(self, gadget, *args)
        run.__name__ = fn.__name__
        return run
    return wrap


class Admin:
    def __init__(self, server):
        self.server = server
        self.roles_eds = {}      # session -> RolesEditor
        self.users_eds = {}      # session -> UsersEditor
        self.motd_eds = {}       # session -> MotdEditor
        self.tos_eds = {}        # session -> TosEditor

    @property
    def db(self):
        return self.server.db

    @staticmethod
    def allowed(session):
        return (session.can(perms.ADMIN_ROLES) or session.can(perms.ADMIN_USERS)
                or session.can(perms.ADMIN_MOTD) or session.can(perms.ADMIN_PAGES))

    # ---- opening the windows (the Admin menu's items, screens.py) ----

    def open_roles(self, session):
        if not session.can(perms.ADMIN_ROLES):
            return refuse(session, "open_roles", perms.ADMIN_ROLES)
        return RolesEditor(self, session).show()

    def open_users(self, session, user_id=None):
        """The User Editor; `user_id` picked in it (the person icon: the oldest new user)."""
        if not session.can(perms.ADMIN_USERS):
            return refuse(session, "open_users", perms.ADMIN_USERS)
        ed = UsersEditor(self, session)
        if user_id is not None and self.db.user(user_id=user_id) is not None:
            ed.user_id = user_id
        return ed.show()

    def open_motd(self, session):
        if not session.can(perms.ADMIN_MOTD):
            return refuse(session, "open_motd", perms.ADMIN_MOTD)
        ed = self.motd_eds.get(session)
        if ed is not None and ed.win is not None and ed.win.shown:
            return ed.show()             # already open: bring it back, edits kept
        return MotdEditor(self, session).show()

    def open_tos(self, session):
        if not session.can(perms.ADMIN_TOS):
            return refuse(session, "open_tos", perms.ADMIN_TOS)
        ed = self.tos_eds.get(session)
        if ed is not None and ed.win is not None and ed.win.shown:
            return ed.show()             # already open: bring it back, edits kept
        return TosEditor(self, session).show()

    # ---- System Settings (admin.settings) ----

    def open_settings(self, session):
        """A dialog with the server-wide settings: Auto-Away's idle minutes, and whether New
        Users may send and receive instant messages."""
        if not session.can(perms.ADMIN_SETTINGS):
            return refuse(session, "open_settings", perms.ADMIN_SETTINGS)
        presence, db = self.server.screens.presence, self.server.db
        win = Window.centred("System Settings", 360, 106,
                             flags=WFlag.CLOSE | WFlag.MOVABLE, win_id=WIN_SETTINGS,
                             minimize=False)
        win.add(Label(8, 6, 88, 10, "Auto-Away:"))
        win.away = win.add(TextBox(96, 4, 40, 12, str(presence.away_minutes())))
        win.add(Label(144, 6, 208, 10, "idle minutes (0 = never)"))
        win.im_send = win.add(CheckBox(8, 22, 344, 12, "New users can send instant messages",
                                       checked=im.new_users_send(db)))
        win.im_receive = win.add(CheckBox(8, 36, 344, 12,
                                          "New users can receive instant messages",
                                          checked=im.new_users_receive(db)))
        win.add(Label(8, 54, 88, 10, "Keep log:"))
        win.log_days = win.add(TextBox(96, 52, 40, 12, str(self.server.serverlog.days())))
        win.add(Label(144, 54, 208, 10, "days (Server Log)"))
        win.status = win.add(Label(8, 70, 344, 10, ""))
        add_buttons(win, [("OK", self._settings_ok, GFlag.DEFAULT), ("Cancel", closer, 0)])
        win.show(session)
        return win

    # ---- Broadcast (admin.broadcast) ----

    def open_broadcast(self, session):
        """A line to send to everyone signed on: the bottom row of their screens."""
        if not session.can(perms.ADMIN_BROADCAST):
            return refuse(session, "open_broadcast", perms.ADMIN_BROADCAST)
        win = Window.centred("Broadcast", 400, 62, flags=WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_BROADCAST, minimize=False)
        win.add(Label(8, 4, 384, 10, "A message to everyone signed on:"))
        win.text = win.add(TextBox(8, 16, 384, 12))
        send, _ = add_buttons(win, [("Send", self._broadcast_send, GFlag.DEFAULT),
                                    ("Cancel", closer, 0)])
        send.needs = win.text                   # (greyed until something is typed)
        win.show(session)
        return win

    @guarded(perms.ADMIN_BROADCAST)
    def _broadcast_send(self, button):
        win, session = button.window, button.session
        text = clean_text(win.text.value).strip()
        if not text:
            return None
        win.close()
        self.server.screens.broadcast(session, text)
        return None

    @guarded(perms.ADMIN_SETTINGS)
    def _settings_ok(self, button):
        win, session = button.window, button.session
        text = win.away.value.strip()
        from .presence import AWAY_MINUTES_MAX
        if not (text.isascii() and text.isdigit()) or int(text) > AWAY_MINUTES_MAX:
            return win.status.set_text("Auto-Away: a number of minutes, 0 to %d."
                                       % AWAY_MINUTES_MAX)
        from .serverlog import LOG_DAYS_MAX
        days = win.log_days.value.strip()
        if not (days.isascii() and days.isdigit()) or not 1 <= int(days) <= LOG_DAYS_MAX:
            return win.status.set_text("Keep log: a number of days, 1 to %d." % LOG_DAYS_MAX)
        db = self.server.db
        send, receive = win.im_send.checked, win.im_receive.checked
        if send != im.new_users_send(db):
            problem = im.set_new_users_send(db, send)
            if problem:
                return win.status.set_text(problem)
            self.server.permissions_changed(role_id=db.default_role_id())
        im.set_new_users_receive(db, receive)
        self.server.screens.presence.set_away_minutes(int(text))
        self.server.screens.im_rules_changed()
        if int(days) != self.server.serverlog.days():
            self.server.serverlog.set_days(int(days))
        session.log("admin: auto-away after %s minutes; new users IM send %s, receive %s; "
                    "log kept %s days" % (text, "on" if send else "off",
                                          "on" if receive else "off", days))
        return win.close()

    # ---- keeping things in step ----

    def changed(self):
        """Roles or users changed: refresh every open admin window's lists."""
        for ed in list(self.roles_eds.values()) + list(self.users_eds.values()):
            ed.refresh()
        self.server.screens.new_users_changed()      # someone left New User, or it moved

    def permissions_changed(self, session, old_perms):
        """`session`'s permissions changed: close the admin windows it may no longer use."""
        if not session.can(perms.ADMIN_ROLES) and session in self.roles_eds:
            self.roles_eds[session].close()
        if not session.can(perms.ADMIN_USERS) and session in self.users_eds:
            self.users_eds[session].close()
        if not session.can(perms.ADMIN_MOTD) and session in self.motd_eds:
            self.motd_eds[session].close()
        if not session.can(perms.ADMIN_TOS) and session in self.tos_eds:
            self.tos_eds[session].close()
        for win_id, key in ((WIN_SETTINGS, perms.ADMIN_SETTINGS),
                            (WIN_BROADCAST, perms.ADMIN_BROADCAST),
                            (WIN_KARMA, perms.ADMIN_USERS)):
            win = session.windows.get(win_id)
            if win is not None and not session.can(key):
                win.close()

    def disconnected(self, session):
        self.roles_eds.pop(session, None)
        self.users_eds.pop(session, None)
        self.motd_eds.pop(session, None)
        self.tos_eds.pop(session, None)


class RolesEditor:
    """One admin's Roles window. Edits stay here (pending) until Save."""

    def __init__(self, admin, session):
        self.admin = admin
        self.session = session
        self.role_ids = []           # list row -> role id
        self.role_id = None          # the role being edited
        self.pending = set()         # its permission keys as ticked (not saved yet)
        self.page = 0
        self.win = None

    @property
    def db(self):
        return self.admin.db

    def show(self):
        old = self.admin.roles_eds.get(self.session)
        if old is not None and old is not self and self.role_id is None:
            self.role_id, self.pending, self.page = old.role_id, old.pending, old.page
        self.admin.roles_eds[self.session] = self
        keys = perms.all_permissions()
        pages = max(1, (len(keys) + PER_PAGE - 1) // PER_PAGE)
        self.page = min(self.page, pages - 1)

        win = Window("Roles", 16, 11, 608, 170, win_id=WIN_ROLES, on_close=self._closed)
        win.add(Label(8, 2, 150, 10, "Roles (users):"))
        self.list = win.add(ListBox(8, 14, 150, 118, on_select=self._pick))
        win.add(Button(8, 136, 72, 16, "New Role", on_click=self._new))
        self.need = [win.add(Button(86, 136, 72, 16, "Delete", on_click=self._delete))]

        win.add(Label(168, 2, 40, 10, "Name:"))
        self.name = win.add(TextBox(216, 1, 160, 12))
        self.need.append(win.add(Button(384, 0, 64, 14, "Rename", on_click=self._rename)))
        win.add(Label(456, 2, 48, 10, "Level:"))
        self.level = win.add(TextBox(512, 1, 40, 12))

        self.boxes = []
        for i, p in enumerate(keys[self.page * PER_PAGE:(self.page + 1) * PER_PAGE]):
            col, row = divmod(i, PER_COLUMN)
            cb = win.add(CheckBox(168 + col * 216, 20 + row * 13, 208, 12,
                                  p.description[:perms.DESCRIPTION_MAX],
                                  on_select=self._tick))
            cb.perm = p.key
            self.boxes.append(cb)

        self.need.append(win.add(Button(168, 136, 64, 16, "Save", GFlag.DEFAULT,
                                        on_click=self._save)))
        self.need.append(win.add(Button(240, 136, 104, 16, "Make Default",
                                        on_click=self._make_default)))
        if pages > 1:
            win.add(Label(384, 140, 80, 10, "Page %d/%d" % (self.page + 1, pages)))
            win.add(Button(464, 136, 56, 16, "< Prev", on_click=lambda b: self._turn(b, -1)))
            win.add(Button(528, 136, 56, 16, "Next >", on_click=lambda b: self._turn(b, 1)))
        self.status = win.add(Label(8, 158, 590, 10, "* = the role new users get"))
        self.win = win
        self.list.rows = self.rows()
        self._fill()
        win.show(self.session)
        if self.role_id in self.role_ids:
            self.list.set_value(self.role_ids.index(self.role_id))

    def close(self):
        self.admin.roles_eds.pop(self.session, None)
        for win_id in (WIN_ROLES, WIN_CONFIRM):
            win = self.session.windows.get(win_id)
            if win is not None:
                win.close()

    def _closed(self, window):
        if self.admin.roles_eds.get(self.session) is self:
            del self.admin.roles_eds[self.session]

    def rows(self):
        default = self.db.default_role_id()
        roles = self.db.roles()
        self.role_ids = [r["id"] for r in roles]
        return ["%s%s (%d)" % ("*" if r["id"] == default else "", r["name"], r["users"])
                for r in roles]

    def refresh(self):
        """Someone changed the roles: update the list (the edit in progress stays)."""
        self.list.set_rows(self.rows())
        if self.role_id not in self.role_ids:
            self.role_id = None
            self.pending = set()
            self._fill(send=True)
        else:
            self.list.selected = self.role_ids.index(self.role_id)
            self.list.set_value(self.list.selected)

    def _fill(self, send=False):
        """Put the selected role's name, level and pending permissions into the gadgets."""
        role = self.db.role(self.role_id) if self.role_id is not None else None
        name = role["name"] if role else ""
        level = str(role["level"]) if role else ""
        if send:
            self.name.set_text(name)
            self.level.set_text(level)
        else:
            self.name.text = self.name.value = name
            self.level.text = self.level.value = level
        for cb in self.boxes:
            if send:
                cb.set_checked(cb.perm in self.pending)
            else:
                cb.checked = cb.perm in self.pending
        for b in self.need:                  # (they need a role picked)
            b.enable(role is not None)

    def say(self, text):
        self.status.set_text(text)

    def _selected_role(self):
        if self.role_id is None:
            self.say("Pick a role first.")
        return self.role_id

    # ---- handlers ----

    @guarded(perms.ADMIN_ROLES)
    def _pick(self, listbox, index, double):
        if listbox.selected is None:
            return
        self.role_id = self.role_ids[listbox.selected]
        self.pending = self.db.role_permissions(self.role_id)
        self._fill(send=True)
        role = self.db.role(self.role_id)
        self.say("Editing %s." % role["name"])

    @guarded(perms.ADMIN_ROLES)
    def _tick(self, checkbox, index, double):
        if self.role_id is None:
            checkbox.set_checked(False)
            return self.say("Pick a role first.")
        if checkbox.checked:
            self.pending.add(checkbox.perm)
        else:
            self.pending.discard(checkbox.perm)
        return None

    @guarded(perms.ADMIN_ROLES)
    def _turn(self, button, step):
        self.page += step
        self.page = max(0, self.page)
        self.show()

    @guarded(perms.ADMIN_ROLES)
    def _new(self, button):
        names = {r["name"].lower() for r in self.db.roles()}
        name, n = NEW_ROLE, 1
        while name.lower() in names:
            n += 1
            name = "%s %d" % (NEW_ROLE, n)
        self.role_id = self.db.create_role(name, 0)
        self.pending = set()
        self.session.log("admin: new role %s" % name)
        self.admin.changed()
        self._fill(send=True)
        self.say("Made %s: give it a name and permissions, then Save." % name)

    @guarded(perms.ADMIN_ROLES)
    def _rename(self, button):
        if self._selected_role() is None:
            return
        name = self.name.value.strip()
        problem = check_role_name(name)
        if problem is None:
            problem = self.db.rename_role(self.role_id, name)
        if problem:
            return self.say(problem)
        self.session.log("admin: role %d renamed %s" % (self.role_id, name))
        self.admin.changed()
        self.admin.server.permissions_changed(role_id=self.role_id)   # menus show the role
        return self.say("Renamed to %s." % name)

    @guarded(perms.ADMIN_ROLES)
    def _save(self, button):
        if self._selected_role() is None:
            return
        try:
            level = int(self.level.value.strip())
            if not 0 <= level <= 999:
                raise ValueError
        except ValueError:
            return self.say("The level is a number from 0 to 999.")
        known = set(perms.keys())
        # Keys this server doesn't know (a plugin that's gone) are kept as they are.
        keys = self.pending & known | (self.db.role_permissions(self.role_id) - known)
        problem = self.db.set_role_permissions(self.role_id, keys)
        if problem:
            self.pending = self.db.role_permissions(self.role_id)
            self._fill(send=True)
            return self.say(problem)
        self.db.set_role_level(self.role_id, level)
        role = self.db.role(self.role_id)
        self.session.log("admin: role %s = %s" % (role["name"], " ".join(sorted(keys))))
        self.admin.changed()
        self.admin.server.permissions_changed(role_id=self.role_id)
        return self.say("Saved %s." % role["name"]) if self.win.shown else None

    @guarded(perms.ADMIN_ROLES)
    def _make_default(self, button):
        if self._selected_role() is None:
            return
        self.db.set_default_role(self.role_id)
        role = self.db.role(self.role_id)
        self.session.log("admin: default role %s" % role["name"])
        self.admin.changed()
        self.admin.server.screens.im_rules_changed()    # (who counts as a new user moved)
        self.say("New users now get %s." % role["name"])

    @guarded(perms.ADMIN_ROLES)
    def _delete(self, button):
        if self._selected_role() is None:
            return None
        role = self.db.role(self.role_id)
        n = next(r["users"] for r in self.db.roles() if r["id"] == self.role_id)
        if n == 0:
            return self._do_delete(None)
        default = self.db.role(self.db.default_role_id())
        if default is None or default["id"] == self.role_id:
            return self.say("%s is the role for new users: make another one the default first."
                            % role["name"])
        win = Window.centred("Delete Role", 280, 54, flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_CONFIRM)
        win.add(Label(8, 4, 264, 10, "%s has %d user%s. Move them to"
                      % (role["name"], n, "" if n == 1 else "s")))
        win.add(Label(8, 14, 264, 10, "%s and delete it?" % default["name"]))
        win.role_id, win.move_to = self.role_id, default["id"]
        add_buttons(win, [("Move and Delete", self._confirm, 0),
                          ("Cancel", closer, GFlag.DEFAULT)], centre=True)
        win.show(self.session)
        return None

    @guarded(perms.ADMIN_ROLES)
    def _confirm(self, button):
        win = button.window
        win.close()
        if win.role_id != self.role_id:
            return None
        return self._do_delete(win.move_to)

    def _do_delete(self, move_to):
        old_id = self.role_id
        role = self.db.role(old_id)
        problem = self.db.delete_role(old_id, move_to)
        if problem:
            return self.say(problem)
        self.session.log("admin: deleted role %s" % role["name"])
        self.role_id, self.pending = None, set()
        self.admin.changed()
        if move_to is not None:                   # its users, signed on, are in move_to now
            self.admin.server.permissions_changed(role_id=old_id)
        self._fill(send=True)
        return self.say("Deleted %s." % role["name"])


def when(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "Never"


class UsersEditor:
    """One admin's User Editor window: find a user on the left; on the right their first and
    last name, email address, location and role, Save, and Set Password (a modal dialog: the
    admin types the new password twice, no current password needed). Birthdate and About Me
    are the user's own (My Account) and are kept as they are."""

    W, H = 608, 171                  # (= protocol.CLIENT_MAX_H)
    BUTTONS_Y = 140                  # both button rows, under the list and the fields
    LIST_W = 224
    LX, LW = 244, 96                 # the right side's labels ("Last Login:" is 11 characters)
    FX = LX + LW + 8                 # 348: its fields
    FW = W - 8 - FX                  # 252
    REAL_W = 6 + 8 * dbmod.REAL_NAME_MAX
    ROLE_W = 6 + 8 * 16 + 11         # role names are 1-16 characters
    ROW = 15

    def __init__(self, admin, session):
        self.admin = admin
        self.session = session
        self.find = ""
        self.low = False             # the list shows only low karma (Low Karma)
        self.user_ids = []           # list row -> user id
        self.role_ids = []           # role drop-down row -> role id
        self.user_id = None
        self.win = None

    @property
    def db(self):
        return self.admin.db

    def show(self):
        self.admin.users_eds[self.session] = self
        win = Window.centred("User Editor", self.W, self.H, win_id=WIN_USERS,
                             flags=WFlag.CLOSE | WFlag.MOVABLE, on_close=self._closed)
        win.add(Label(8, 4, 40, 10, "Find:"))
        self.find_box = win.add(TextBox(52, 2, 124, 12))
        win.add(Button(184, 0, 48, 16, "Find", GFlag.DEFAULT, on_click=self._find))
        self.list = win.add(ListBox(8, 20, self.LIST_W, self.BUTTONS_Y - 24, self.user_rows(),
                                    on_select=self._pick))
        win.add(Button(8, self.BUTTONS_Y, 108, 16, "Low Karma", on_click=self._low))
        win.add(Button(124, self.BUTTONS_Y, 108, 16, "All Users", on_click=self._all))
        y = 2

        def label(text):
            win.add(Label(self.LX, y + 2, self.LW, 10, text))

        label("Username:")
        self.who = win.add(Label(self.FX, y + 2, self.FW, 10, "Pick a user."))
        y += self.ROW
        label("First Name:")
        self.first = win.add(TextBox(self.FX, y, self.REAL_W, 12))
        y += self.ROW
        label("Last Name:")
        self.last = win.add(TextBox(self.FX, y, self.REAL_W, 12))
        y += self.ROW
        label("Email:")
        self.email = win.add(TextBox(self.FX, y, self.FW, 12))
        y += self.ROW
        label("Location:")
        self.location = win.add(TextBox(self.FX, y, self.FW, 12))
        y += self.ROW
        label("Role:")
        self.roles = win.add(DropDown(self.FX, y, self.ROLE_W, self.role_rows()))
        y += self.ROW
        label("Karma:")
        karma_y = y                      # (its box is added last: the others keep their ids)
        y += self.ROW
        label("Joined:")
        self.joined = win.add(Label(self.FX, y + 2, self.FW, 10, ""))
        y += self.ROW
        label("Last Login:")
        self.last_login = win.add(Label(self.FX, y + 2, self.FW, 10, ""))
        self.need = add_buttons(win, [("Save", self._save, 0),
                                      ("Set Password...", self._set_password, 0),
                                      ("History", self._history, 0)], y=self.BUTTONS_Y)
        for b in self.need:                  # (they need a user picked: _fill keeps them)
            b.enable(self.user_id is not None)
        self.karma = win.add(TextBox(self.FX, karma_y, 40, 12))      # (3 digits show whole)
        self.karma_word = win.add(Label(self.FX + 48, karma_y + 2, 96, 10, ""))
        self.status = win.add(Label(8, self.H - 12, self.W - 16, 10, ""))
        self.win = win
        if self.user_id in self.user_ids:          # a user to start with (the person icon)
            self._show_user(send=False)
        win.show(self.session)
        if self.list.selected is not None:
            self.list.set_value(self.list.selected)

    def close(self):
        self.admin.users_eds.pop(self.session, None)
        for win_id in (WIN_SET_PASSWORD, WIN_USERS):
            win = self.session.windows.get(win_id)
            if win is not None:
                win.close()

    def _closed(self, window):
        if self.admin.users_eds.get(self.session) is self:
            del self.admin.users_eds[self.session]
        pw = self.session.windows.get(WIN_SET_PASSWORD)
        if pw is not None:
            pw.close()

    def user_rows(self):
        users = self.db.low_karma_users(LOW_KARMA) if self.low else self.db.users(self.find)
        self.user_ids = [u["id"] for u in users]
        return ["%-11s%-9s%3d" % (u["name"], (u["role"] or "-")[:8], u["karma"]) for u in users]

    def role_rows(self):
        roles = self.db.roles()
        self.role_ids = [r["id"] for r in roles]
        return [r["name"] for r in roles]

    def say(self, text):
        self.status.set_text(text)

    def refresh(self):
        """Someone changed the users or roles: new lists. The fields being edited stay; the
        role drop-down shows the user's role as stored."""
        self.list.set_rows(self.user_rows())
        rows = self.role_rows()
        user = self.db.user(user_id=self.user_id) if self.user_id is not None else None
        if user is not None and self.user_id not in self.user_ids:
            self.roles.set_rows(rows, self._role_row(user))   # (out of the list, e.g. Low
            return                                           # Karma: still being edited)
        if user is None:
            self.user_id = None
            self.roles.set_rows(rows)
            self._fill(None, send=True)
            return
        self.roles.set_rows(rows, self._role_row(user))
        self.list.selected = self.user_ids.index(self.user_id)
        self.list.set_value(self.list.selected)

    def _role_row(self, user):
        return self.role_ids.index(user["role_id"]) if user["role_id"] in self.role_ids else None

    def _fill(self, user, send=True):
        """Put `user`'s details (None: blank) into the fields."""
        get = (lambda k: user[k] or "") if user is not None else (lambda k: "")
        values = [(self.who, user["name"] if user is not None else "Pick a user."),
                  (self.first, get("first_name")), (self.last, get("last_name")),
                  (self.email, get("email")), (self.location, get("location")),
                  (self.joined, when(user["created"]) if user is not None else ""),
                  (self.last_login, when(user["last_login"]) if user is not None else ""),
                  (self.karma, str(user["karma"]) if user is not None else ""),
                  (self.karma_word, karma.level(user["karma"]) if user is not None else "")]
        role = self._role_row(user) if user is not None else None
        for gadget, text in values:
            if send:
                gadget.set_text(text)
            else:
                gadget.text = text
                if isinstance(gadget, TextBox):
                    gadget.value = text
        if send:
            self.roles.set_selected(role)
        else:
            self.roles.selected = role
        for b in self.need:
            b.enable(user is not None)

    def _show_user(self, send=True):
        user = self.db.user(user_id=self.user_id)
        self.list.selected = self.user_ids.index(self.user_id)
        if send:
            self.list.set_value(self.list.selected)
        self._fill(user, send)

    # ---- handlers ----

    @guarded(perms.ADMIN_USERS)
    def _low(self, button):
        """Only the users with Karma Points below LOW_KARMA, lowest first."""
        self.low = True
        self.list.set_rows(self.user_rows())
        n = len(self.user_ids)
        self.say("%d user%s below %d Karma Points." % (n, "" if n == 1 else "s", LOW_KARMA)
                 if n else "Nobody is below %d Karma Points." % LOW_KARMA)

    @guarded(perms.ADMIN_USERS)
    def _all(self, button):
        self.low, self.find = False, ""
        self.find_box.set_text("")
        self.list.set_rows(self.user_rows())
        self.say("")

    @guarded(perms.ADMIN_USERS)
    def _history(self, button):
        if self.user_id is None:
            return self.say("Pick a user first.")
        user = self.db.user(user_id=self.user_id)
        lines = ["%s: Karma Points %s" % (user["name"], karma.describe(user["karma"])), ""]
        for e in self.db.karma_log(self.user_id):
            lines.append("%s %+d = %d  %s%s" % (
                time.strftime("%m-%d %H:%M", time.localtime(e["at"])), e["delta"], e["karma"],
                e["reason"], " (%s)" % e["by_name"] if e["by_name"] else ""))
        if len(lines) == 2:
            lines.append("No changes yet.")
        win = Window.centred("Karma History", 440, 128, flags=WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_KARMA)
        win.add(TextView(8, 4, 424, 100, lines))
        add_buttons(win, [("OK", closer, GFlag.DEFAULT)], centre=True)
        win.show(self.session)
        return None

    @guarded(perms.ADMIN_USERS)
    def _find(self, button):
        self.low = False
        self.find = self.find_box.value.strip()
        self.list.set_rows(self.user_rows())
        self.say("%d user%s found." % (len(self.user_ids),
                                       "" if len(self.user_ids) == 1 else "s"))
        if len(self.user_ids) == 1:
            self.user_id = self.user_ids[0]
            self._show_user()
        elif self.user_id not in self.user_ids:
            self.user_id = None
            self._fill(None)

    @guarded(perms.ADMIN_USERS)
    def _pick(self, listbox, index, double):
        if listbox.selected is None:
            return
        self.user_id = self.user_ids[listbox.selected]
        self._show_user()
        self.say("")

    @guarded(perms.ADMIN_USERS)
    def _save(self, button):
        if self.user_id is None:
            return self.say("Pick a user first.")
        if self.roles.selected is None:
            return self.say("Pick a role first.")
        user = self.db.user(user_id=self.user_id)
        if user is None:
            return self.say("That user is gone.")
        first = clean_text(self.first.value).strip()
        last = clean_text(self.last.value).strip()
        email = clean_text(self.email.value).strip()
        location = clean_text(self.location.value).strip()
        # Accounts from before real names were asked for have none: they may stay blank.
        names_blank = not (first or last or user["first_name"] or user["last_name"])
        problem = ((None if names_blank else dbmod.real_names_problem(first, last))
                   or dbmod.check_email(email) or length_problem(email, location))
        new_karma = self.karma.value.strip()
        if new_karma != str(user["karma"]):
            if not (new_karma.isascii() and new_karma.isdigit()) or not 0 <= int(new_karma) <= dbmod.KARMA_MAX:
                problem = problem or "Karma Points are 0 to %d." % dbmod.KARMA_MAX
        if problem:
            return self.say(problem)
        role_id = self.role_ids[self.roles.selected]
        new_role = role_id != user["role_id"]
        problem = self.db.set_user_role(self.user_id, role_id)
        if problem:
            self.say(problem)
            return self.roles.set_selected(self._role_row(user))
        about = (user["about"] or "").split("\n") if user["about"] else []
        self.db.set_profile(self.user_id, first, last, email, location,
                            user["birthdate"] or "", about)
        if new_karma != str(user["karma"]):
            karma.change(self.admin.server, self.user_id, int(new_karma) - user["karma"],
                         "set by an admin", by=self.session)
            self.karma_word.set_text(karma.level(int(new_karma)))
        role = self.db.role(role_id)
        self.session.log("admin: saved user %s (%s)" % (user["name"], role["name"]))
        self.admin.changed()
        if new_role:
            self.admin.server.permissions_changed(user_id=self.user_id)
        if self.win.shown:
            self.say("%s is now %s." % (user["name"], role["name"]) if new_role
                     else "Saved %s." % user["name"])
        return None

    @guarded(perms.ADMIN_USERS)
    def _set_password(self, button):
        if self.user_id is None:
            return self.say("Pick a user first.")
        user = self.db.user(user_id=self.user_id)
        win = Window.centred("Set Password", 320, 70,
                             flags=WFlag.CLOSE | WFlag.MODAL | WFlag.MOVABLE,
                             win_id=WIN_SET_PASSWORD)
        win.user_id = self.user_id
        win.msg = win.add(Label(8, 4, 304, 10, "A new password for %s:" % user["name"]))
        win.add(Label(8, 20, 136, 10, "New password:"))
        win.new = win.add(Password(152, 18, 160, 12))
        win.add(Label(8, 35, 136, 10, "Confirm:"))
        win.confirm = win.add(Password(152, 33, 160, 12))
        add_buttons(win, [("OK", self._password_ok, GFlag.DEFAULT), ("Cancel", closer, 0)])
        win.show(self.session)
        return None

    @guarded(perms.ADMIN_USERS)
    async def _password_ok(self, button):
        win = button.window
        new, confirm = win.new.value, win.confirm.value
        problem = dbmod.check_new_password(new)
        if problem is None and new != confirm:
            problem = "The passwords don't match."
        if problem:
            return win.msg.set_text(problem)
        user = self.db.user(user_id=win.user_id)
        if user is None:
            win.close()
            return self.say("That user is gone.")
        pw_hash = await asyncio.to_thread(dbmod.hash_password, new)
        self.db.set_password(win.user_id, pw_hash)
        self.session.log("admin: set the password of %s" % user["name"])
        win.close()
        return self.say("Set a new password for %s." % user["name"]) if self.win.shown else None


def motd_for_editor(lines, cols):
    """The stored message as editor lines: each stored line wrapped to `cols` characters (the
    welcome window's width, so what's typed is what users see); blank lines kept."""
    out = []
    for line in lines:
        if not line.strip():
            out.append("")
        else:
            out.extend(textwrap.wrap(line, cols) or [""])
    return out


class MotdEditor:
    """One admin's Message of the Day window: the message in an editable text area exactly as
    wide as the welcome window's view, so each line here is a line users see. Preview shows
    the welcome window with it; Save stores it; Cancel (or the close box) drops the edits."""

    W, H = 416, 158
    AREA = (8, 14, 400, 118)     # as wide as screens.Screens.MOTD_VIEW (a test checks);
                                 # 14 lines show, it scrolls to 32

    def __init__(self, admin, session):
        self.admin = admin
        self.session = session
        self.cols = TextArea(*self.AREA).columns()
        self.lines = motd_for_editor(admin.db.motd(), self.cols)[:TextArea.CLIENT_LINES]
        self.win = None

    @property
    def db(self):
        return self.admin.db

    def show(self):
        self.admin.motd_eds[self.session] = self
        win = Window.centred("Message of the Day", self.W, self.H, win_id=WIN_MOTD,
                             flags=WFlag.CLOSE | WFlag.MOVABLE, on_close=self._closed)
        win.add(Label(8, 2, 400, 10, "Message of the Day", GFlag.CENTRE))
        self.area = win.add(TextArea(*self.AREA, lines=self.lines))
        y = self.AREA[1] + self.AREA[3] + 6
        self.status = win.add(Label(8, y + 3, 168, 10, "Edit, then Save."))
        add_buttons(win, [("Preview", self._preview, 0), ("Save", self._save, 0),
                          ("Cancel", self._cancel, 0)], y=y)
        self.win = win
        win.show(self.session)

    def close(self):
        self.admin.motd_eds.pop(self.session, None)
        win = self.session.windows.get(WIN_MOTD)
        if win is not None:
            win.close()

    def _closed(self, window):
        if self.admin.motd_eds.get(self.session) is self:
            del self.admin.motd_eds[self.session]

    def say(self, text):
        self.status.set_text(text)

    def _typed(self):
        """The text area's lines (the client sent them before the click), kept pending."""
        self.lines = [clean_text(l).rstrip() for l in self.area.lines][:TextArea.CLIENT_LINES]
        return self.lines

    # ---- handlers ----

    @guarded(perms.ADMIN_MOTD)
    def _preview(self, button):
        self.admin.server.screens.welcome(self.session, motd=self._typed())
        self.say("Preview open.")

    @guarded(perms.ADMIN_MOTD)
    def _save(self, button):
        self.lines = self.db.set_motd(self._typed())
        self.session.log("admin: message of the day saved (%d lines)" % len(self.lines))
        self.close()
        self.session.alert("Message of the Day", "Saved. Users see it when they next sign on.")

    @guarded(perms.ADMIN_MOTD)
    def _cancel(self, button):
        self.close()


class TosEditor:
    """One admin's Terms of Service window (a dynamic id): the Terms, a page at a time (the
    client's text areas hold 32 lines), in a text area exactly as wide as the sign-up's
    reader, so each line here is a line new users read. < and > turn the pages (edits kept);
    Save stores all four (if they fit the reader); Cancel (or the close box) drops the edits."""

    W, H = 448, 158
    AREA = (8, 14, 8 * dbmod.TOS_COLS + TextArea.PAD + 11, 118)   # TOS_COLS characters

    def __init__(self, admin, session):
        self.admin = admin
        self.session = session
        self.pages = admin.db.tos()
        self.page = 0
        self.win = None

    @property
    def db(self):
        return self.admin.db

    def show(self):
        self.admin.tos_eds[self.session] = self
        if self.win is not None and self.win.shown:
            self.win.close()
        win = Window.centred("Terms of Service", self.W, self.H, on_close=self._closed,
                             flags=WFlag.CLOSE | WFlag.MOVABLE)
        self.head = win.add(Label(8, 2, 432, 10, self._heading(), GFlag.CENTRE))
        self.area = win.add(TextArea(*self.AREA, lines=self.pages[self.page]))
        y = self.AREA[1] + self.AREA[3] + 6
        self.prev_b = win.add(Button(8, y, 24, 16, "<", on_click=self._prev))
        self.next_b = win.add(Button(36, y, 24, 16, ">", on_click=self._next))
        self.status = win.add(Label(68, y + 3, 200, 10, "Edit, then Save."))
        add_buttons(win, [("Save", self._save, 0), ("Cancel", self._cancel, 0)], y=y)
        self._buttons()
        self.win = win
        win.show(self.session)
        return self

    def _heading(self):
        return "Terms of Service: page %d of %d" % (self.page + 1, dbmod.TOS_PAGES)

    def _buttons(self):
        self.prev_b.enable(self.page > 0)
        self.next_b.enable(self.page < dbmod.TOS_PAGES - 1)

    def close(self):
        self.admin.tos_eds.pop(self.session, None)
        if self.win is not None:
            self.win.close()

    def _closed(self, window):
        if self.admin.tos_eds.get(self.session) is self:
            del self.admin.tos_eds[self.session]

    def say(self, text):
        self.status.set_text(text)

    def _typed(self):
        """The page on screen as typed (the client sent it before the click), kept."""
        self.pages[self.page] = [clean_text(l).rstrip() for l in self.area.lines]
        return self.pages

    def _turn(self, step):
        self._typed()
        self.page = max(0, min(dbmod.TOS_PAGES - 1, self.page + step))
        self.area.set_lines(self.pages[self.page])
        self.head.set_text(self._heading())
        self._buttons()

    # ---- handlers ----

    @guarded(perms.ADMIN_TOS)
    def _prev(self, button):
        self._turn(-1)

    @guarded(perms.ADMIN_TOS)
    def _next(self, button):
        self._turn(1)

    @guarded(perms.ADMIN_TOS)
    def _save(self, button):
        problem = dbmod.tos_problem(self._typed())
        if problem:
            return self.say(problem[:25]) if len(problem) <= 25 else                 self.session.alert("Terms of Service", problem)
        self.pages = self.db.set_tos(self.pages)
        self.session.log("admin: terms of service saved (%d lines)"
                         % len(dbmod.tos_text(self.pages)))
        self.close()
        self.session.alert("Terms of Service", "Saved. New users agree to them as they join.")
        return None

    @guarded(perms.ADMIN_TOS)
    def _cancel(self, button):
        self.close()


def check_role_name(name):
    if not 1 <= len(name) <= 16:
        return "Role names are 1-16 characters."
    if not all(" " <= ch <= "~" for ch in name):
        return "Role names are plain letters, digits and punctuation."
    return None
