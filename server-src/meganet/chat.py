"""Areas > Chat Rooms (chat.use): rooms with everyone in them seeing every line, one room at
a time.

    2  = the room you are in (titled with its name): the topic, the conversation (TextView),
         who is here (a narrow list at the right; "*" marks the muted), a line to type, Send,
         Rooms... (the close box leaves the room). Moderators (chat.moderate) also get a
         row of Kick, Mute / Unmute, Ban, Unban..., Karma +, Karma - (for the person picked
         in the list) under the conversation, and Topic (sets the line typed as the topic; nothing
         clears it). Picking a person shows a moderator their Karma Points.
    26 = Chat Rooms (what Areas > Chat Rooms opens, unless you're in a room): the listed
         rooms with how many are in each; Go; then under a line and "Create A Room", a Room
         name box, Private and Create Room (makes a member room: chat.rooms; or joins the
         room of that name, private ones too); moderators also Delete Room (under Go) and
         New Room (a permanent one)
    27 = Unban (moderators): a drop-down of who is banned from the room, Unban

Rooms:
- Permanent rooms are in the chat_rooms table; moderators make and delete them (the Lobby
  can't be deleted). A new database has the Lobby.
- Member rooms (chat.rooms) live only in memory and go when the last person leaves.
- Either kind can be private: not listed (except to moderators), joined by typing its name.
- Kick: out of the room (they may come back). Mute: no talking in that room until unmuted or
  they leave. Ban: kicked and kept out until unbanned or the server restarts (a member room's
  bans go with it). Moderators can't do these to other moderators, unless they are an admin
  (admin.users) acting on a moderator who isn't. Each costs the user Karma Points (karma.py).
"""

import time

from . import db as dbmod
from . import karma
from . import permissions as perms
from .protocol import WFlag, GFlag, clean_text, CLIENT_MAX_H
from .ui import (add_buttons, closer, Window, Button, Label, TextBox, ListBox, TextView,
                 CheckBox, DropDown, Group)

USE, MODERATE, ROOMS = "chat.use", "chat.moderate", perms.CHAT_ROOMS
WIN_ROOM = 2
WIN_ROOMS = 26
WIN_UNBAN = 27
TITLE = "Chat Rooms"
RATES_PER_DAY = 2                # Karma +/- one moderator may give one user a day


def refuse(session, key):
    """An action the user's role doesn't allow (chat.use, or chat.moderate for moderators)."""
    session.log("refused chat: no %s" % key)
    session.alert(TITLE, "Your account can't use the chat rooms." if key == USE
                  else "Only moderators can do that.")


def room_key(name):
    return name.strip().lower()


def check_room_name(name):
    if not 1 <= len(name) <= dbmod.ROOM_NAME_MAX:
        return "Room names are 1-%d characters." % dbmod.ROOM_NAME_MAX
    if not all(" " <= ch <= "~" for ch in name):
        return "Room names are plain letters, digits and punctuation."
    return None


class Room:
    def __init__(self, name, room_id=None, private=False, topic=""):
        self.name = name
        self.room_id = room_id           # chat_rooms id, or None: a member room
        self.private = private
        self.topic = topic
        self.windows = {}                # session -> RoomWindow
        self.muted = set()               # user ids

    @property
    def key(self):
        return room_key(self.name)

    @property
    def permanent(self):
        return self.room_id is not None


class Chat:
    def __init__(self, server):
        self.server = server
        self.rooms = {}                  # key -> Room with people in it, and member rooms
        self.where = {}                  # session -> Room
        self.lists = {}                  # session -> RoomList
        self.bans = {}                   # room key -> {user_id}

    @property
    def db(self):
        return self.server.db

    # ---- rooms ----

    def find(self, name):
        """The Room called `name` (any case): active, or permanent from the database."""
        key = room_key(name)
        if key in self.rooms:
            return self.rooms[key]
        row = next((r for r in self.db.chat_rooms() if room_key(r["name"]) == key), None)
        if row is None:
            return None
        room = Room(row["name"], row["id"], bool(row["private"]), row["topic"])
        self.rooms[key] = room
        return room

    def all_rooms(self):
        """Every room: the permanent ones and the active member rooms, by name."""
        for row in self.db.chat_rooms():
            self.find(row["name"])
        return sorted(self.rooms.values(), key=lambda r: r.key)

    def _tidy(self, room):
        """A room nobody is in: a member room goes (with its bans), a permanent one is
        forgotten until it's next used (its bans and topic stay)."""
        if room.windows or self.rooms.get(room.key) is not room:
            return
        if not room.permanent:
            self.bans.pop(room.key, None)
        del self.rooms[room.key]

    def changed(self):
        """Who is where changed: every open room list follows."""
        for rl in list(self.lists.values()):
            rl.refresh()

    # ---- joining and leaving ----

    def open(self, session):
        """Areas > Chat Rooms: back to your room if you're in one, else the list of rooms to
        pick from (not straight into the Lobby)."""
        if not session.can(USE):
            return refuse(session, USE)
        room = self.where.get(session)
        if room is not None:
            return room.windows[session].show()
        return self.open_list(session)

    def join(self, session, name, private=False, create=False):
        """Into room `name`; with `create`, a member room is made if there's none. Returns a
        problem (str) or None."""
        if not session.can(USE):
            refuse(session, USE)
            return "You can't use the chat rooms."
        room = self.find(name)
        if room is None:
            if not create:
                return "There is no room called %s." % name
            if not session.can(ROOMS):
                return "There is no room called %s, and you can't make rooms." % name
            room = Room(name, private=private)
            self.rooms[room.key] = room
            session.log("made member room %s%s" % (name, " (private)" if private else ""))
        if session.user_id in self.bans.get(room.key, ()):
            self._tidy(room)
            return "You are banned from %s." % room.name
        old = self.where.get(session)
        if old is room:
            room.windows[session].show()
            return None
        if old is not None:
            self.leave(session, closing=False)
        win = RoomWindow(self, room, session)
        room.windows[session] = win
        self.where[session] = room
        win.show()
        self.say(room, "* %s has entered the room" % session.user)
        self.refresh_people(room)
        self.changed()
        return None

    def leave(self, session, closing=True, quiet=False):
        """Out of their room (closing: their window too, if it's still open)."""
        room = self.where.pop(session, None)
        if room is None:
            return
        win = room.windows.pop(session, None)
        room.muted.discard(session.user_id)
        if closing and win is not None and win.win.shown:
            win.win.close()
        if not quiet:
            self.say(room, "* %s has left the room" % session.user)
        self.refresh_people(room)
        self._tidy(room)
        self.changed()

    def kick(self, session):
        """Out of the chat (they may no longer chat): windows close."""
        self.leave(session)
        rl = self.lists.pop(session, None)
        if rl is not None and rl.win.shown:
            rl.win.close()
        unban = session.windows.get(WIN_UNBAN)
        if unban is not None:
            unban.close()

    def permissions_changed(self, session):
        if not session.can(USE):
            return self.kick(session)
        room = self.where.get(session)
        if room is not None:                     # (the moderator buttons may come or go)
            room.windows[session].show(keep=True)
        rl = self.lists.get(session)
        if rl is not None and rl.win.shown:
            rl.show()
        return None

    def disconnected(self, session):
        self.leave(session, closing=False)
        self.lists.pop(session, None)

    # ---- talking ----

    def say(self, room, line):
        for w in room.windows.values():
            w.view.append(line)

    def refresh_people(self, room):
        for w in room.windows.values():
            w.fill_people()

    # ---- the room list ----

    def open_list(self, session):
        if not session.can(USE):
            return refuse(session, USE)
        rl = self.lists.get(session) or RoomList(self, session)
        return rl.show()

    # ---- moderators ----

    @staticmethod
    def protected(actor, target):
        """True if `actor` may not kick, mute, ban or rate `target`."""
        if target is actor:
            return True
        if not target.can(MODERATE):
            return False
        return not (actor.can(perms.ADMIN_USERS) and not target.can(perms.ADMIN_USERS))


class RoomWindow:
    W, H = 624, 160
    H_MAX = CLIENT_MAX_H                 # (171: the moderators' window)
    VIEW_H = 112                         # the conversation and who's here
    LIST_W = 112                         # who's here: a 10-character name and the "*" mark
    MOD_ROW = 20                         # moderators: a row of buttons under the conversation

    def __init__(self, chat, room, session):
        self.chat = chat
        self.room = room
        self.session = session
        self.people = []                 # list row -> session
        self.picked = None               # the session picked in the list
        self.win = None
        self.lines = []

    @property
    def mod(self):
        return self.session.can(MODERATE)

    def show(self, keep=False):
        """Send the window (keep: with the conversation so far, after a permissions change)."""
        lines = self.view.lines if keep and self.win is not None else []
        room, mod = self.room, self.mod
        # moderators' extra row comes out of the conversation's height (the client's windows
        # are at most CLIENT_MAX_H high)
        view_h = self.VIEW_H - (self.MOD_ROW - (self.H_MAX - self.H) if mod else 0)
        h = self.H_MAX if mod else self.H
        win = Window.centred(room.name, self.W, h, flags=WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_ROOM, on_close=self._closed)
        lx = self.W - 8 - self.LIST_W                # the people list, at the right
        self.topic = win.add(Label(8, 2, lx - 16, 10, self.topic_text()))
        win.add(Label(lx, 2, self.LIST_W, 10, "Here (* muted)"))
        self.view = win.add(TextView(8, 14, lx - 16, view_h, lines))
        self.list = win.add(ListBox(lx, 14, self.LIST_W, view_h, self.people_rows(),
                                    on_select=self._pick))
        self.on_person = []              # moderators' buttons for the person picked
        self.unban_button = None
        y = 14 + view_h + 2
        if mod:                          # a row of them under the conversation
            for i, (text, fn) in enumerate([("Kick", self._kick), ("Mute", self._mute),
                                            ("Ban", self._ban), ("Unban...", self._unban),
                                            ("Karma +", self._up), ("Karma -", self._down)]):
                b = win.add(Button(8 + i * 80, y, 76, 16, text, on_click=fn))
                if text == "Mute":
                    self.mute_button = b
                if text == "Unban...":
                    self.unban_button = b
                else:
                    self.on_person.append(b)
            y += self.MOD_ROW
        self.entry = win.add(TextBox(8, y + 2, 290, 12))
        win.add(Button(304, y, 56, 16, "Send", GFlag.DEFAULT, on_click=self._send))
        if mod:
            win.add(Button(366, y, 64, 16, "Topic", on_click=self._topic))
        win.add(Button(self.W - 8 - 88, y, 88, 16, "Rooms...", on_click=self._rooms))
        self.status = win.add(Label(8, y + 18, self.W - 16, 10, "You are in %s." % room.name))
        self.win = win
        self.buttons()
        win.show(self.session)
        self.entry.focus()               # type straight away
        return self

    def topic_text(self):
        return ("Topic: %s" % self.room.topic) if self.room.topic else (
            "%s%s" % (self.room.name, " (private)" if self.room.private else ""))

    def people_rows(self):
        self.people = sorted(self.room.windows, key=lambda s: s.user.lower())
        return [("*" if s.user_id in self.room.muted else "") + s.user for s in self.people]

    def fill_people(self):
        self.list.set_rows(self.people_rows())
        if self.picked in self.people:
            self.list.selected = self.people.index(self.picked)
            self.list.set_value(self.list.selected)
        else:
            self.picked = None
        self.buttons()

    def buttons(self):
        """Grey out the moderator buttons that can't be used: nobody (or someone protected)
        picked, nobody banned."""
        t = self.picked
        ok = t is not None and t in self.room.windows and not self.chat.protected(self.session, t)
        for b in self.on_person:
            b.enable(ok)
        if self.unban_button is not None:
            self.unban_button.enable(bool(self.chat.bans.get(self.room.key)))

    def say(self, text):
        self.status.set_text(text)

    def _closed(self, window):
        if self.room.windows.get(self.session) is self:
            self.chat.leave(self.session, closing=False)

    def _ok(self, key=USE):
        if not self.session.can(key):
            refuse(self.session, key)
            if key == USE:
                self.chat.kick(self.session)
            return False
        return self.room.windows.get(self.session) is self

    # ---- everyone ----

    def _send(self, button):
        if not self._ok():
            return None
        text = clean_text(self.entry.value).strip()
        if not text:
            return None
        if self.session.user_id in self.room.muted:
            return self.say("You are muted in this room.")
        self.entry.set_text("")
        self.chat.say(self.room, "%s: %s" % (self.session.user, text))
        s = self.session
        s.chat_lines += 1
        if s.chat_lines % karma.CHAT_LINES == 0:
            karma.earn(self.chat.server, s.user_id, "chat")
        return None

    def _pick(self, listbox, index, double):
        if not self._ok() or listbox.selected is None:
            return None
        self.picked = self.people[listbox.selected]
        self.buttons()
        if self.mod:
            u = self.chat.db.user(user_id=self.picked.user_id)
            muted = self.picked.user_id in self.room.muted
            self.mute_button.set_text("Unmute" if muted else "Mute")
            return self.say("%s: Karma Points %s." % (u["name"], karma.describe(u["karma"])))
        return None

    def _rooms(self, button):
        if self._ok():
            self.chat.open_list(self.session)

    def _leave(self, button):
        if self.room.windows.get(self.session) is self:
            self.chat.leave(self.session)

    # ---- moderators ----

    def _target(self):
        """The picked person, if a moderator may act on them; else says why."""
        if not self._ok(MODERATE):
            return None
        t = self.picked
        if t is None or t not in self.room.windows:
            self.say("Pick someone in the list first.")
            return None
        if self.chat.protected(self.session, t):
            self.say("You can't do that to %s." % ("yourself" if t is self.session else t.user))
            return None
        return t

    def _kick(self, button):
        t = self._target()
        if t is None:
            return None
        self.session.log("chat: kicked %s from %s" % (t.user, self.room.name))
        self.chat.leave(t, quiet=True)
        self.chat.say(self.room, "* %s was asked to leave by %s" % (t.user, self.session.user))
        t.alert(self.room.name, "%s removed you from %s." % (self.session.user, self.room.name))
        karma.lose(self.chat.server, t.user_id, "kicked from chat", by=self.session)
        return self.say("Kicked %s." % t.user)

    def _ban(self, button):
        t = self._target()
        if t is None:
            return None
        self.chat.bans.setdefault(self.room.key, set()).add(t.user_id)
        self.session.log("chat: banned %s from %s" % (t.user, self.room.name))
        self.chat.leave(t, quiet=True)
        self.chat.say(self.room, "* %s was banned from the room by %s" % (t.user,
                                                                         self.session.user))
        t.alert(self.room.name, "%s banned you from %s." % (self.session.user, self.room.name))
        karma.lose(self.chat.server, t.user_id, "banned from a chat room", by=self.session)
        return self.say("Banned %s." % t.user)

    def _mute(self, button):
        t = self._target()
        if t is None:
            return None
        if t.user_id in self.room.muted:
            self.room.muted.discard(t.user_id)
            self.chat.say(self.room, "* %s may talk again" % t.user)
            self.mute_button.set_text("Mute")
        else:
            self.room.muted.add(t.user_id)
            self.chat.say(self.room, "* %s was muted by %s" % (t.user, self.session.user))
            self.mute_button.set_text("Unmute")
            karma.lose(self.chat.server, t.user_id, "muted in chat", by=self.session)
        self.session.log("chat: %s %s in %s" % (
            "muted" if t.user_id in self.room.muted else "unmuted", t.user, self.room.name))
        self.chat.refresh_people(self.room)
        return None

    def _rate(self, step):
        t = self._target()
        if t is None:
            return None
        db = self.chat.db
        if db.karma_given_since(t.user_id, self.session.user_id,
                                karma.day_start()) >= RATES_PER_DAY:
            return self.say("You have rated %s %d times today already." % (t.user,
                                                                          RATES_PER_DAY))
        got = karma.change(self.chat.server, t.user_id, step,
                           "moderator Karma %s" % ("+" if step > 0 else "-"), by=self.session)
        return self.say("%s: Karma Points %s." % (t.user, karma.describe(got[1])))

    def _up(self, button):
        return self._rate(karma.KARMA_STEP)

    def _down(self, button):
        return self._rate(-karma.KARMA_STEP)

    def _topic(self, button):
        if not self._ok(MODERATE):
            return None
        topic = clean_text(self.entry.value).strip()[:60]
        self.room.topic = topic
        if self.room.permanent:
            self.chat.db.set_chat_room_topic(self.room.room_id, topic)
        self.entry.set_text("")
        for w in self.room.windows.values():
            w.topic.set_text(w.topic_text())
        self.chat.say(self.room, "* %s %s" % (self.session.user, "set the topic: " + topic
                                              if topic else "cleared the topic"))
        self.session.log("chat: topic of %s: %r" % (self.room.name, topic))
        return None

    def _unban(self, button):
        if not self._ok(MODERATE):
            return None
        banned = sorted(self.chat.bans.get(self.room.key, ()))
        if not banned:
            return self.say("Nobody is banned from %s." % self.room.name)
        names = [self.chat.db.user(user_id=u)["name"] for u in banned][:DropDown.MAX_ROWS]
        win = Window.centred("Unban", 240, 56, flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_UNBAN)
        win.ids = banned
        win.add(Label(8, 4, 224, 10, "Let back into %s:" % self.room.name[:16]))
        win.who = win.add(DropDown(8, 18, 136, names, 0))
        add_buttons(win, [("Unban", self._unban_ok, GFlag.DEFAULT), ("Cancel", closer, 0)])
        win.show(self.session)
        return None

    def _unban_ok(self, button):
        win = button.window
        win.close()
        if not self._ok(MODERATE) or win.who.selected is None:
            return None
        uid = win.ids[win.who.selected]
        self.chat.bans.get(self.room.key, set()).discard(uid)
        self.chat.refresh_people(self.room)          # (Unban... greys out when none are left)
        name = self.chat.db.user(user_id=uid)["name"]
        self.session.log("chat: unbanned %s from %s" % (name, self.room.name))
        return self.say("%s may come back into %s." % (name, self.room.name))


class RoomList:
    W, H = 400, 160

    def __init__(self, chat, session):
        self.chat = chat
        self.session = session
        self.rooms = []
        self.picked = None               # room key
        self.win = None

    @property
    def mod(self):
        return self.session.can(MODERATE)

    def rows(self):
        mod = self.mod
        self.rooms = [r for r in self.chat.all_rooms() if mod or not r.private]
        out = []
        for r in self.rooms:
            kind = "private" if r.private else "" if r.permanent else "member"   # (one word fits)
            out.append(("%-18s %2d %s" % (r.name[:18], len(r.windows), kind)).rstrip())
        return out

    def show(self, status=None):
        self.chat.lists[self.session] = self
        win = Window.centred(TITLE, self.W, self.H, flags=WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_ROOMS, on_close=self._closed)
        win.add(Label(8, 2, 272, 10, "Room               In"))
        self.list = win.add(ListBox(8, 14, 272, 128, self.rows(), on_select=self._pick))
        self.go_b = win.add(Button(288, 14, 104, 16, "Go", GFlag.DEFAULT, on_click=self._go))
        y = 34
        self.delete_b = None
        if self.mod:                     # (acts on the picked room, like Go)
            self.delete_b = win.add(Button(288, y, 104, 16, "Delete Room",
                                           on_click=self._delete))
            y += 20
        win.add(Group(288, y + 2, 104, 2))                    # a line, then making a room
        win.add(Label(288, y + 8, 104, 10, "Create A Room", GFlag.BOLD | GFlag.CENTRE))
        win.add(Label(288, y + 22, 104, 10, "Room name:"))
        self.name = win.add(TextBox(288, y + 34, 104, 12))
        self.private = win.add(CheckBox(288, y + 50, 104, 12, "Private"))
        # Create Room: makes a member room, or joins the room of that name if there is one
        # (the way into a private room, which isn't listed)
        win.add(Button(288, y + 66, 104, 16, "Create Room", needs=self.name,
                       on_click=self._go_named))
        if self.mod:
            win.add(Button(288, y + 86, 104, 16, "New Room", needs=self.name, on_click=self._new))
        self.status = win.add(Label(8, 146, 272, 10, status or "Pick a room and Go."))
        self.win = win
        self.buttons()
        win.show(self.session)
        return self

    def buttons(self):
        """Go needs a room picked; Delete Room a permanent one other than the Lobby."""
        room = next((r for r in self.rooms if r.key == self.picked), None)
        self.go_b.enable(room is not None)
        if self.delete_b is not None:
            self.delete_b.enable(room is not None and room.permanent
                                 and room.key != room_key(dbmod.LOBBY))

    def refresh(self):
        if self.win is None or not self.win.shown:
            return
        self.list.set_rows(self.rows())
        keys = [r.key for r in self.rooms]
        if self.picked in keys:
            self.list.selected = keys.index(self.picked)
            self.list.set_value(self.list.selected)
        self.buttons()

    def say(self, text):
        self.status.set_text(text)

    def _closed(self, window):
        if self.chat.lists.get(self.session) is self:
            del self.chat.lists[self.session]

    def _ok(self, key=USE):
        if not self.session.can(key):
            refuse(self.session, key)
            return False
        return True

    def _pick(self, listbox, index, double):
        if not self._ok() or listbox.selected is None:
            return None
        self.picked = self.rooms[listbox.selected].key
        self.buttons()
        return self._go(None) if double else None

    def _go(self, button):
        if not self._ok():
            return None
        room = next((r for r in self.rooms if r.key == self.picked), None)
        if room is None:
            return self.say("Pick a room first.")
        return self._join(room.name)

    def _join(self, name, **kw):
        problem = self.chat.join(self.session, name, **kw)
        if problem:
            return self.say(problem)
        self.win.close()
        self._closed(self.win)
        return None

    def _typed(self):
        name = clean_text(self.name.value).strip()
        problem = check_room_name(name)
        if problem:
            self.say(problem)
            return None
        return name

    def _go_named(self, button):
        if not self._ok():
            return None
        name = self._typed()
        if name is None:
            return None
        return self._join(name, private=self.private.checked, create=True)

    def _new(self, button):
        if not self._ok(MODERATE):
            return None
        name = self._typed()
        if name is None:
            return None
        if self.chat.find(name) is not None:
            return self.say("There is already a room called %s." % name)
        room_id = self.chat.db.create_chat_room(name, self.private.checked)
        if room_id is None:
            return self.say("There is already a room called %s." % name)
        self.session.log("chat: new room %s%s" % (name, " (private)" if self.private.checked
                                                  else ""))
        self.picked = room_key(name)
        self.chat.changed()
        return self.say("Made %s." % name)

    def _delete(self, button):
        if not self._ok(MODERATE):
            return None
        room = next((r for r in self.rooms if r.key == self.picked), None)
        if room is None:
            return self.say("Pick a room first.")
        if not room.permanent:
            return self.say("%s goes by itself when everyone leaves." % room.name)
        if room.key == room_key(dbmod.LOBBY):
            return self.say("The %s stays." % dbmod.LOBBY)
        self.chat.db.delete_chat_room(room.room_id)
        for s in list(room.windows):
            self.chat.leave(s, quiet=True)
            s.alert(room.name, "%s closed this room." % self.session.user)
        self.chat.rooms.pop(room.key, None)
        self.chat.bans.pop(room.key, None)
        self.session.log("chat: deleted room %s" % room.name)
        self.chat.changed()
        return self.say("Deleted %s." % room.name)
