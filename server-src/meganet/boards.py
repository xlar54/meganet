"""Areas > Message Boards (boards.read): forums, each a list of topics, each topic a list of
posts. "New" means posted since the user's previous sign-on (session.previous_login; for a
first sign-on everything is new).

    22 = Message Boards: one window that shows one of three views, re-sent as the user moves
         between them:
         - the forums: name, topics, new posts, "locked"; Open. Holders of boards.moderate also
           get a Name box, New Forum, Rename, Delete, Lock / Unlock and Access...
         - a forum's topics ("*" = new posts in it, subject, who started it, replies, the last
           post); Read, New Topic, Back; moderators also Delete Topic
         - a topic's posts on the left ("*" = new), the picked one on the right; Reply, Back;
           moderators also Delete Post (the topic goes with its last post)
    23 = New Topic / Reply (compose.py)
    24 = Forum Access (modal): per role, Read and Post check boxes
    25 = Delete Forum? (modal)

Who may do what:
- Read a forum: boards.read, and the forum's access row for the user's role allows reading (no
  row: allowed). Moderators (boards.moderate) see and read every forum.
- Post (new topics and replies): reading it, boards.post, the row allows posting (no row:
  allowed), and the forum not locked. Moderators may post in a locked forum.
- Everything a moderator does checks boards.moderate again, since a client can send any CLICK.
"""

import time

from . import db as dbmod
from . import karma
from .compose import Composer, refuse, MOD_ONLY
from .protocol import WFlag, GFlag, clean_text
from .ui import (add_buttons, closer, confirm, Window, Button, Label, TextBox, ListBox,
                 TextView, CheckBox, Group)

READ, POST, MODERATE = "boards.read", "boards.post", "boards.moderate"

WIN_BOARDS = 22
WIN_POST = 23
WIN_ACCESS = 24
WIN_DELETE = 25
TITLE = "Message Boards"
W, H = 560, 160
ACCESS_ROLES = 6                 # role rows in the Access window (the client's gadgets)
SUBJECT_COLS = 28


def when(t, fmt="%m-%d %H:%M"):
    return time.strftime(fmt, time.localtime(t))


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def check_forum_name(name):
    if not 1 <= len(name) <= dbmod.FORUM_NAME_MAX:
        return "Forum names are 1-%d characters." % dbmod.FORUM_NAME_MAX
    if not all(" " <= ch <= "~" for ch in name):
        return "Forum names are plain letters, digits and punctuation."
    return None


class Boards:
    def __init__(self, server):
        self.server = server
        self.browsers = {}               # session -> Browser
        self.composers = {}              # session -> Composer

    @property
    def db(self):
        return self.server.db

    # ---- who may do what ----

    @staticmethod
    def moderator(session):
        return session.can(MODERATE)

    def can_read(self, session, forum):
        if forum is None or not session.can(READ):
            return False
        if self.moderator(session):
            return True
        return self.db.forum_access(forum["id"]).get(session.role_id, (True, True))[0]

    def can_post(self, session, forum):
        if not self.can_read(session, forum) or not session.can(POST):
            return False
        if self.moderator(session):
            return True
        if forum["locked"]:
            return False
        return self.db.forum_access(forum["id"]).get(session.role_id, (True, True))[1]

    def forums_for(self, session):
        """The forums this session may read, with new counts since its previous sign-on."""
        return [f for f in self.db.forums(since(session)) if self.can_read(session, f)]

    # ---- opening, and keeping everyone's windows in step ----

    def open(self, session):
        if not session.can(READ):
            return refuse(session, TITLE, READ)
        b = self.browsers.get(session) or Browser(self, session)
        b.view, b.forum_id, b.topic_id, b.post_id = "forums", None, None, None
        return b.show()

    def changed(self):
        """Forums, topics or posts changed: every open Message Boards window follows."""
        for b in list(self.browsers.values()):
            b.refresh()

    def permissions_changed(self, session):
        b = self.browsers.get(session)
        if b is None:
            return
        if not session.can(READ):
            b.close()
            c = self.composers.get(session)
            if c is not None:
                c.close()
        else:
            b.show()                     # (the moderator buttons may come or go)

    def disconnected(self, session):
        self.browsers.pop(session, None)
        self.composers.pop(session, None)

    # ---- writing: new topics and replies ----

    def compose(self, session, forum_id, topic_id=None):
        forum = self.db.forum(forum_id)
        if not self.can_post(session, forum):
            return session.alert(TITLE, "You can't post in this forum." if not forum
                                 or not forum["locked"] else "This forum is locked.")
        if topic_id is None:
            title, subject = "New Topic in %s" % forum["name"], ""
        else:
            topic = self.db.topic(topic_id)
            if topic is None:
                return None
            title, subject = "Reply", reply_subject(topic["subject"])
        c = Composer(session, title, WIN_POST, key=POST, subject=subject,
                     on_send=lambda comp, to, subj, lines: self._send(comp, forum_id, topic_id,
                                                                      subj, lines),
                     on_closed=self._compose_closed,
                     hint="Give it a subject and write it, then Send." if topic_id is None
                     else "Write your reply, then Send.")
        self.composers[session] = c
        return c.show()

    def _compose_closed(self, composer):
        if self.composers.get(composer.session) is composer:
            del self.composers[composer.session]

    def _send(self, composer, forum_id, topic_id, subject, lines):
        session = composer.session
        forum = self.db.forum(forum_id)
        if forum is None:
            return "That forum is gone."
        if not self.can_post(session, forum):
            return "This forum is locked." if forum["locked"] else "You can't post here."
        if topic_id is None:
            if not subject:
                return "Give your topic a subject."
            topic_id = self.db.create_topic(forum_id, session.user_id, clean_text(subject),
                                            lines)
            session.log("new topic %d in %s" % (topic_id, forum["name"]))
        else:
            if self.db.topic(topic_id) is None:
                return "That topic is gone."
            self.db.add_post(topic_id, session.user_id, lines)
            session.log("reply in topic %d" % topic_id)
        composer.close()
        karma.earn(self.server, session.user_id, "board post")
        b = self.browsers.get(session)
        if b is not None:                # show the topic, at the new post
            b.view, b.forum_id, b.topic_id = "topic", forum_id, topic_id
            b.post_id = self.db.posts(topic_id)[-1]["id"]
            b.show("Posted.")
        self.changed()
        return None


def since(session):
    return session.previous_login or 0


def reply_subject(subject):
    return subject if subject.lower().startswith("re:") else ("Re: " + subject)[:63]


class Browser:
    """One user's Message Boards window (WIN_BOARDS), showing the forums, a forum or a topic."""

    def __init__(self, boards, session):
        self.boards = boards
        self.session = session
        self.view = "forums"
        self.forum_id = self.topic_id = self.post_id = None
        self.ids = []                    # list row -> forum, topic or post id
        self.win = None

    @property
    def db(self):
        return self.boards.db

    @property
    def mod(self):
        return self.boards.moderator(self.session)

    def say(self, text):
        self.status.set_text(text)

    def close(self):
        self.boards.browsers.pop(self.session, None)
        for win_id in (WIN_ACCESS, WIN_DELETE, WIN_BOARDS):
            win = self.session.windows.get(win_id)
            if win is not None:
                win.close()

    def _closed(self, window):
        if self.boards.browsers.get(self.session) is self:
            del self.boards.browsers[self.session]

    # ---- the three views ----

    def show(self, status=None):
        """Send the window for the current view (falling back to a view that still exists)."""
        self.boards.browsers[self.session] = self
        forum = self.db.forum(self.forum_id) if self.forum_id is not None else None
        if self.view != "forums" and not self.boards.can_read(self.session, forum):
            self.view, self.forum_id, self.topic_id = "forums", None, None
        if self.view == "topic" and self.db.topic(self.topic_id) is None:
            self.view, self.topic_id = "forum", None
        title = TITLE if self.view == "forums" else "%s: %s" % (TITLE, forum["name"])
        win = Window.centred(title, W, H, flags=WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_BOARDS, on_close=self._closed)
        self.win = win
        getattr(self, "_show_" + self.view)(win, forum, status)
        self.buttons()
        win.show(self.session)
        if self.list.selected is not None:
            self.list.set_value(self.list.selected)
        return self

    def refresh(self):
        """Someone changed something: new rows in place, or another view if ours is gone."""
        if self.win is None or not self.win.shown:
            return
        forum = self.db.forum(self.forum_id) if self.forum_id is not None else None
        if self.view != "forums" and not self.boards.can_read(self.session, forum):
            self.view = "forums"
            return self.show("That forum is gone." if forum is None else
                             "You can't read that forum now.")
        if self.view == "topic" and self.db.topic(self.topic_id) is None:
            self.view = "forum"
            return self.show("That topic was deleted.")
        if self.view == "forum" and bool(forum["locked"]) != self.locked_shown:
            return self.show()           # (New Topic comes or goes, the heading changes)
        rows = getattr(self, "_rows_" + self.view)(forum)
        keep = {"forums": self.forum_id, "forum": self.topic_id, "topic": self.post_id}
        self.list.set_rows(rows)
        self.head.set_text(self._heading(forum))
        if keep[self.view] in self.ids:
            self.list.selected = self.ids.index(keep[self.view])
            self.list.set_value(self.list.selected)
        self.buttons()
        return None

    def picked(self):
        """The id picked in this view's list, if it's still there."""
        pid = {"forums": self.forum_id, "forum": self.topic_id, "topic": self.post_id}[self.view]
        return pid if pid in self.ids else None

    def buttons(self):
        """Grey out the buttons that need something picked in the list."""
        on = self.picked() is not None
        for b in self.need:
            b.enable(on)

    def _heading(self, forum):
        s = since(self.session)
        if self.view == "forums":
            new = sum(f["new"] for f in self.forums)
            if not s:
                return "Welcome to the message boards: everything here is new to you."
            return "Since your last sign-on (%s): %s." % (when(s, "%Y-%m-%d %H:%M"),
                                                          plural(new, "new post"))
        if self.view == "forum":
            new = sum(t["new"] for t in self.topics)
            return "%s, %d new%s" % (plural(len(self.topics), "topic"), new,
                                     "  (locked)" if forum["locked"] else "")
        topic = self.db.topic(self.topic_id, s)
        return ("%s  (%s, %d new)" % (topic["subject"], plural(topic["posts"], "post"),
                                      topic["new"]))[:68]

    # the forums
    def _rows_forums(self, forum=None):
        self.forums = self.boards.forums_for(self.session)
        self.ids = [f["id"] for f in self.forums]
        rows = []
        for f in self.forums:
            access = self.db.forum_access(f["id"])
            flags = (["locked"] if f["locked"] else []) + (
                ["limited"] if self.mod and any(not r or not p for r, p in access.values())
                else [])
            rows.append(("%-20s %3d topic%s %s %s" % (
                f["name"][:20], f["topics"], " " if f["topics"] == 1 else "s",
                "%3d new" % f["new"] if f["new"] else "       ", " ".join(flags))).rstrip())
        return rows

    def _show_forums(self, win, forum, status):
        rows = self._rows_forums()
        self.head = win.add(Label(8, 2, 544, 10, self._heading(None)))
        self.list = win.add(ListBox(8, 14, 400, 112, rows, on_select=self._pick_forum))
        if self.forum_id in self.ids:
            self.list.selected = self.ids.index(self.forum_id)
        self.need = [win.add(Button(416, 14, 136, 16, "Open", GFlag.DEFAULT,
                                    on_click=self._open_forum))]      # (need a forum picked)
        if self.mod:                     # under a line and a heading, set apart from Open
            picked = self.db.forum(self.forum_id) if self.forum_id in self.ids else None
            win.add(Group(416, 36, 136, 2))
            win.add(Label(416, 42, 136, 10, "Admin Tools", GFlag.BOLD | GFlag.CENTRE))
            win.add(Label(416, 56, 136, 10, "Forum name:"))
            self.name = win.add(TextBox(416, 68, 136, 12, picked["name"] if picked else ""))
            win.add(Button(416, 84, 66, 16, "New", on_click=self._new_forum,
                           needs=self.name))                  # (greyed until a name is typed)
            self.need.append(win.add(Button(486, 84, 66, 16, "Rename", on_click=self._rename)))
            self.need.append(win.add(Button(416, 104, 66, 16, "Delete",
                                            on_click=self._delete_forum)))
            self.lock = win.add(Button(486, 104, 66, 16,
                                       "Unlock" if picked and picked["locked"] else "Lock",
                                       on_click=self._lock))
            self.need.append(self.lock)
            self.need.append(win.add(Button(416, 124, 136, 16, "Access...",
                                            on_click=self._access)))
        if status is None:
            status = "Pick a forum and Open it." if rows else "There are no forums yet."
        self.status = win.add(Label(8, 148, 544, 10, status))

    # a forum's topics
    def _rows_forum(self, forum):
        self.topics = self.db.topics(self.forum_id, since(self.session))
        self.ids = [t["id"] for t in self.topics]
        return [("%s %-*s %-10s %3d %s" % (
            "*" if t["new"] else " ", SUBJECT_COLS, t["subject"][:SUBJECT_COLS],
            t["author_name"][:10], t["posts"] - 1, when(t["last_post"])))
            for t in self.topics]

    def _show_forum(self, win, forum, status):
        rows = self._rows_forum(forum)
        self.locked_shown = bool(forum["locked"])
        self.head = win.add(Label(8, 2, 544, 10, self._heading(forum)))
        win.add(Label(8, 14, 544, 10, "  %-*s %-10s %3s %s" % (SUBJECT_COLS, "Subject",
                                                               "Started by", "Re", "Last post")))
        self.list = win.add(ListBox(8, 26, 544, 100, rows, on_select=self._pick_topic))
        if self.topic_id in self.ids:
            self.list.selected = self.ids.index(self.topic_id)
        self.need = [win.add(Button(8, 130, 72, 16, "Read", GFlag.DEFAULT,
                                    on_click=self._read))]           # (need a topic picked)
        x = 88
        if self.boards.can_post(self.session, forum):
            win.add(Button(x, 130, 104, 16, "New Topic...", on_click=self._new_topic))
            x += 112
        win.add(Button(x, 130, 72, 16, "Back", on_click=self._back))
        x += 80
        if self.mod:
            self.need.append(win.add(Button(x, 130, 112, 16, "Delete Topic",
                                            on_click=self._delete_topic)))
        if status is None:
            status = ("Pick a topic and Read it." if rows else "No topics yet.") + (
                "  This forum is locked." if forum["locked"] else "")
        self.status = win.add(Label(8, 148, 544, 10, status))

    # a topic's posts
    def _rows_topic(self, forum):
        s = since(self.session)
        self.posts = self.db.posts(self.topic_id)
        self.ids = [p["id"] for p in self.posts]
        return ["%s %-10s %s" % ("*" if p["posted"] > s else " ", p["author_name"][:10],
                                 when(p["posted"])) for p in self.posts]

    def post_lines(self):
        if self.post_id not in self.ids:
            return []
        p = self.db.post(self.post_id)
        topic = self.db.topic(self.topic_id)
        return (["Subject: %s" % topic["subject"], "From: %s" % p["author_name"],
                 "Date: %s" % when(p["posted"], "%Y-%m-%d %H:%M"), ""] + p["body"].split("\n"))

    def _show_topic(self, win, forum, status):
        rows = self._rows_topic(forum)
        if self.post_id not in self.ids:         # the first new post, or the first
            s = since(self.session)
            self.post_id = next((p["id"] for p in self.posts if p["posted"] > s),
                                self.ids[0] if self.ids else None)
        self.head = win.add(Label(8, 2, 544, 10, self._heading(forum)))
        self.list = win.add(ListBox(8, 14, 216, 112, rows, on_select=self._pick_post))
        if self.post_id in self.ids:
            self.list.selected = self.ids.index(self.post_id)
        self.view_box = win.add(TextView(232, 14, 320, 112, self.post_lines()))
        x = 8
        self.need = []                                               # (need a post picked)
        if self.boards.can_post(self.session, forum):
            win.add(Button(x, 130, 80, 16, "Reply...", GFlag.DEFAULT, on_click=self._reply))
            x += 88
        win.add(Button(x, 130, 72, 16, "Back", on_click=self._back))
        x += 80
        if self.mod:
            self.need.append(win.add(Button(x, 130, 112, 16, "Delete Post",
                                            on_click=self._delete_post)))
        if status is None:
            status = "Pick a post to read it." + (
                "  This forum is locked." if forum["locked"] else "")
        self.status = win.add(Label(8, 148, 544, 10, status))

    # ---- handlers: everyone (each checks boards.read and the forum again) ----

    def _ok(self):
        if not self.session.can(READ):
            refuse(self.session, TITLE, READ)
            self.close()
            return False
        return True

    def _forum(self):
        """The forum in view, if this user may still read it (else back to the forums)."""
        forum = self.db.forum(self.forum_id) if self.forum_id is not None else None
        if not self.boards.can_read(self.session, forum):
            self.view, self.forum_id = "forums", None
            self.show("That forum is gone." if forum is None else "You can't read that forum.")
            return None
        return forum

    def _pick_forum(self, listbox, index, double):
        if not self._ok() or listbox.selected is None or self.view != "forums":
            return None
        self.forum_id = self.ids[listbox.selected]
        self.buttons()
        if double:
            return self._open_forum(None)
        if self.mod:
            f = self.db.forum(self.forum_id)
            self.name.set_text(f["name"])
            self.lock.set_text("Unlock" if f["locked"] else "Lock")
        return self.say("")

    def _open_forum(self, button):
        if not self._ok() or self.view != "forums":
            return None
        if self.forum_id not in self.ids:
            return self.say("Pick a forum first.")
        if self._forum() is None:
            return None
        self.view, self.topic_id = "forum", None
        return self.show()

    def _pick_topic(self, listbox, index, double):
        if not self._ok() or listbox.selected is None or self.view != "forum":
            return None
        self.topic_id = self.ids[listbox.selected]
        self.buttons()
        if double:
            return self._read(None)
        return self.say("")

    def _read(self, button):
        if not self._ok() or self.view != "forum" or self._forum() is None:
            return None
        if self.topic_id not in self.ids:
            return self.say("Pick a topic first.")
        self.view, self.post_id = "topic", None
        return self.show()

    def _pick_post(self, listbox, index, double):
        if not self._ok() or listbox.selected is None or self.view != "topic":
            return None
        if self._forum() is None:
            return None
        self.post_id = self.ids[listbox.selected]
        self.buttons()
        self.view_box.set_lines(self.post_lines())
        return self.say("")

    def _back(self, button):
        if not self._ok():
            return None
        self.view = "forums" if self.view == "forum" else "forum"
        return self.show()

    def _new_topic(self, button):
        if self._ok() and self.view == "forum" and self._forum() is not None:
            self.boards.compose(self.session, self.forum_id)

    def _reply(self, button):
        if self._ok() and self.view == "topic" and self._forum() is not None:
            self.boards.compose(self.session, self.forum_id, self.topic_id)

    # ---- handlers: moderators ----

    def _mod_ok(self):
        if not self.session.can(MODERATE):
            refuse(self.session, TITLE, MODERATE, MOD_ONLY)
            return False
        return self._ok()

    def _picked_forum(self):
        f = self.db.forum(self.forum_id) if self.forum_id in self.ids else None
        if f is None:
            self.say("Pick a forum first.")
        return f

    def _typed_name(self):
        name = clean_text(self.name.value).strip()
        problem = check_forum_name(name)
        if problem:
            self.say(problem)
            return None
        return name

    def _new_forum(self, button):
        if not self._mod_ok() or self.view != "forums":
            return None
        name = self._typed_name()
        if name is None:
            return None
        forum_id = self.db.create_forum(name)
        if forum_id is None:
            return self.say("There is already a forum called %s." % name)
        self.session.log("new forum %s" % name)
        self.forum_id = forum_id
        self.show("Made %s." % name)
        self.boards.changed()
        return None

    def _rename(self, button):
        if not self._mod_ok() or self.view != "forums":
            return None
        f = self._picked_forum()
        name = self._typed_name() if f else None
        if name is None:
            return None
        problem = self.db.rename_forum(f["id"], name)
        if problem:
            return self.say(problem)
        self.session.log("renamed forum %s to %s" % (f["name"], name))
        self.boards.changed()
        return self.say("Renamed %s to %s." % (f["name"], name))

    def _lock(self, button):
        if not self._mod_ok() or self.view != "forums":
            return None
        f = self._picked_forum()
        if f is None:
            return None
        self.db.set_forum_locked(f["id"], not f["locked"])
        self.session.log("%s forum %s" % ("unlocked" if f["locked"] else "locked", f["name"]))
        self.lock.set_text("Lock" if f["locked"] else "Unlock")
        self.boards.changed()
        return self.say(("%s is open again." if f["locked"] else
                         "%s is locked: nobody but moderators can post in it.") % f["name"])

    def _delete_forum(self, button):
        if not self._mod_ok() or self.view != "forums":
            return None
        f = self._picked_forum()
        if f is None:
            return None
        n = next(x["topics"] for x in self.db.forums() if x["id"] == f["id"])
        win = Window.centred("Delete Forum", 320, 50,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_DELETE)
        win.forum_id = f["id"]
        win.add(Label(8, 4, 304, 10, "Delete %s and its %s?" % (f["name"], plural(n, "topic"))))
        win.add(Label(8, 16, 304, 10, "This can't be undone."))
        add_buttons(win, [("Delete", self._confirm_delete, 0),
                          ("Cancel", closer, GFlag.DEFAULT)], centre=True)
        win.show(self.session)
        return None

    def _confirm_delete(self, button):
        win = button.window
        win.close()
        if not self._mod_ok():
            return None
        f = self.db.forum(win.forum_id)
        if f is None:
            return None
        self.db.delete_forum(f["id"])
        self.session.log("deleted forum %s" % f["name"])
        self.forum_id = None
        if self.view == "forums":
            self.show("Deleted %s." % f["name"])
        self.boards.changed()
        return None

    def _delete_topic(self, button):
        """Delete Topic: asks first (as every delete does), then deletes the topic picked
        when it was clicked, whatever the list shows by then."""
        if not self._mod_ok() or self.view != "forum" or self._forum() is None:
            return None
        if self.topic_id not in self.ids:
            return self.say("Pick a topic first.")
        t = self.db.topic(self.topic_id)
        n = len(self.db.posts(t["id"]))
        confirm(self.session, "Delete Topic", ["Delete the topic %s" % t["subject"][:24],
                                               "and its %s?" % plural(n, "post")],
                lambda: self._really_delete_topic(t["id"]), WIN_DELETE)
        return None

    def _really_delete_topic(self, topic_id):
        if not self._mod_ok():
            return None
        t = self.db.topic(topic_id)
        if t is None:
            return self.say("That topic is gone already.")
        self.db.delete_topic(topic_id)
        self.session.log("deleted topic %d (%s)" % (t["id"], t["subject"]))
        if self.topic_id == topic_id:
            self.topic_id = None
        self.boards.changed()
        return self.say("Deleted the topic %s." % t["subject"][:40])

    def _delete_post(self, button):
        if not self._mod_ok() or self.view != "topic" or self._forum() is None:
            return None
        if self.post_id not in self.ids:
            return self.say("Pick a post first.")
        p = self.db.post(self.post_id)
        confirm(self.session, "Delete Post", ["Delete the post by %s?" % p["author_name"],
                                              "This can't be undone."],
                lambda: self._really_delete_post(p["id"]), WIN_DELETE)
        return None

    def _really_delete_post(self, post_id):
        if not self._mod_ok():
            return None
        p = self.db.post(post_id)
        if p is None:
            return self.say("That post is gone already.")
        self.post_id = post_id
        topic_gone = self.db.delete_post(self.post_id)
        self.session.log("deleted post %d by %s" % (p["id"], p["author_name"]))
        self.post_id = None
        if topic_gone:
            self.view, self.topic_id = "forum", None
            self.show("Deleted the post, and the topic with it.")
        else:
            self.show("Deleted the post by %s." % p["author_name"])
        self.boards.changed()
        return None

    # ---- Access: per role, read and post ----

    def _access(self, button):
        if not self._mod_ok() or self.view != "forums":
            return None
        f = self._picked_forum()
        if f is None:
            return None
        roles = self.db.roles()[:ACCESS_ROLES]
        access = self.db.forum_access(f["id"])
        h = 30 + 13 * len(roles) + 34
        win = Window.centred("Forum Access", 360, h,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_ACCESS)
        win.forum_id = f["id"]
        win.add(Label(8, 4, 344, 10, "Who may read and post in %s?" % f["name"][:20]))
        win.add(Label(8, 18, 160, 10, "Role"))
        win.boxes = []
        for i, r in enumerate(roles):
            y = 30 + 13 * i
            read, post = access.get(r["id"], (True, True))
            keys = self.db.role_permissions(r["id"])
            win.add(Label(8, y + 1, 184, 10, (r["name"] + ("" if READ in keys else " *"))[:23]))
            rb = win.add(CheckBox(200, y, 64, 12, "Read", read))
            pb = win.add(CheckBox(272, y, 64, 12, "Post", post))
            win.boxes.append((r["id"], rb, pb))
        y = 30 + 13 * len(roles) + 2
        win.add(Label(8, y + 2, 344, 10, "* no message boards at all (Admin > Roles)"))
        add_buttons(win, [("OK", self._access_ok, GFlag.DEFAULT), ("Cancel", closer, 0)],
                    y=y + 16)
        win.show(self.session)
        return None

    def _access_ok(self, button):
        win = button.window
        win.close()
        if not self._mod_ok():
            return None
        f = self.db.forum(win.forum_id)
        if f is None:
            return None
        access = self.db.forum_access(f["id"])        # (roles beyond the window's kept)
        for role_id, rb, pb in win.boxes:
            access[role_id] = (rb.checked or pb.checked, pb.checked)
        access = {k: v for k, v in access.items() if v != (True, True)}
        self.db.set_forum_access(f["id"], access)
        self.session.log("forum %s access %r" % (f["name"], access))
        self.boards.changed()
        return self.say("Saved who may use %s." % f["name"]) if self.win.shown else None
