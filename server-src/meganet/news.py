"""Areas > News (news.read): bulletins, newest first. Holders of news.post (the Sysop at first;
an admin can give it to any role in Admin > Roles) write new bulletins, edit them and delete
them, in the same composer as the message boards (compose.py): a headline box and the text
area. "Unread" means not opened since it was posted or last edited (db news_reads): marked
"*" in the list, counted by a folded-newspaper icon on the menu bar (NOTIFY slot SLOT_NEWS;
a click opens News), and offered at sign-on.

    36 = News: the list of bulletins ("*" = new, the day, the headline). A click opens one
         to read. Posters also get New..., Edit... and Delete (on the last one clicked).
    40 = a bulletin (modal): the headline, who and when, and the text in a view exactly as
         wide as the composer's text area, so it reads as it was written; OK
    37 = New Bulletin / Edit Bulletin (compose.py)
    38 = Delete Bulletin? (modal)
    39 = "There are N unread news bulletins. Would you like to read them now?" (modal),
         once a sign-on, when the welcome window closes (screens.welcome)

Every handler checks the permission again, since a client can send any CLICK.
"""

import time

from . import permissions as perms
from .compose import Composer, refuse
from .protocol import WFlag, GFlag, Icon, SLOT_NEWS, clean_text
from .ui import add_buttons, closer, Window, Button, Label, ListBox, TextView, AreaWindow

READ, POST = perms.NEWS_READ, perms.NEWS_POST
WIN_NEWS, WIN_NEWS_EDIT, WIN_NEWS_DELETE, WIN_NEWS_OFFER, WIN_NEWS_READ = 36, 37, 38, 39, 40
TITLE = "News"
ROW_COLS = 47                    # characters of a list row the client shows
# The reading window's text is exactly as wide as the composer's text area, so each line
# reads as it was written (as the MOTD view matches its editor).
READ_W = Composer.W
READ_VIEW = (8, 28, Composer.W - 16, 112)


def when(t, fmt="%Y-%m-%d %H:%M"):
    return time.strftime(fmt, time.localtime(t))


def changed_at(item):
    return item["edited"] or item["posted"]


class News:
    def __init__(self, server):
        self.server = server
        self.windows = {}                # session -> NewsWindow
        self.composers = {}              # session -> Composer
        self.readers = {}                # session -> its open reading window

    @property
    def db(self):
        return self.server.db

    def open(self, session):
        if not session.can(READ):
            return refuse(session, TITLE, READ)
        v = self.windows.get(session) or NewsWindow(self, session)
        return v.show()

    def unread(self, session):
        """The ids of the bulletins this user hasn't read (none without news.read)."""
        if not session.user_id or not session.can(READ):
            return []
        return self.db.unread_news(session.user_id)

    def new_count(self, session):
        return len(self.unread(session))

    # ---- the newspaper icon ----

    def refresh_icon(self, session):
        n = self.new_count(session)
        if n:
            session.set_notify(SLOT_NEWS, Icon.NEWS, "%d unread news bulletin%s" % (
                n, "" if n == 1 else "s"))
        else:
            session.set_notify(SLOT_NEWS, Icon.NONE)

    def signed_on(self, session):
        self.refresh_icon(session)

    def notify_click(self, session, slot):
        if slot != SLOT_NEWS:
            return None
        if not session.can(READ):
            session.warn("notify click %d refused: no %s" % (slot, READ))
            return self.refresh_icon(session)
        return self.open(session)

    def unread_changed(self, session):
        """This user's unread bulletins changed: their icon and News window follow."""
        self.refresh_icon(session)
        v = self.windows.get(session)
        if v is not None:
            v.refresh()

    def mark_read(self, session, news_ids):
        if news_ids and session.user_id:
            self.db.mark_news_read(session.user_id, news_ids)
            self.unread_changed(session)

    def offer(self, session):
        """After the welcome window at sign-on: if there are bulletins the user hasn't read,
        ask whether to read them (once a sign-on)."""
        if getattr(session, "news_offered", False) or not session.can(READ) or session.closed:
            return None
        session.news_offered = True
        n = self.new_count(session)
        if not n:
            return None
        win = Window.centred("News", 360, 50, flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_NEWS_OFFER)
        win.add(Label(8, 4, 344, 10, "There %s %d unread news bulletin%s." % (
            "is" if n == 1 else "are", n, "" if n == 1 else "s"), GFlag.CENTRE))
        win.add(Label(8, 16, 344, 10, "Would you like to read %s now?" % (
            "it" if n == 1 else "them"), GFlag.CENTRE))
        add_buttons(win, [("Read Now", self._offer_read, GFlag.DEFAULT),
                          ("Later", closer, 0)], centre=True)
        win.show(session)
        return win

    def _offer_read(self, button):
        button.window.close()
        return self.open(button.session)

    # ---- reading one: a modal window, laid out like the composer ----

    def read(self, session, news_id, keep=None):
        """The bulletin in its own window: the headline, who and when, and the text in a view
        as wide as the composer's text area; OK closes it. keep = the open one, redone."""
        item = self.db.bulletin(news_id)
        if item is None or not session.can(READ):
            if keep is not None:
                keep.close()
            self.readers.pop(session, None)
            return None
        by = "By %s, %s" % (item["author_name"] or "(gone)", when(item["posted"]))
        if item["edited"]:
            by += "  (edited by %s, %s)" % (item["editor_name"] or "(gone)",
                                            when(item["edited"], "%m-%d %H:%M"))
        h = READ_VIEW[1] + READ_VIEW[3] + 4 + 20
        win = Window.centred(TITLE, READ_W, h, flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_NEWS_READ)
        win.news_id = news_id
        win.add(Label(8, 2, READ_W - 16, 10, item["headline"], GFlag.CENTRE))
        win.add(Label(8, 14, READ_W - 16, 10, by, GFlag.CENTRE))
        win.add(TextView(*READ_VIEW, item["body"].split("\n")))
        add_buttons(win, [("OK", closer, GFlag.DEFAULT)], centre=True)
        self.readers[session] = win
        win.show(session)
        self.mark_read(session, [news_id])
        return win

    def changed(self):
        """A bulletin came, changed or went: everyone's newspaper icon and open News window
        follow, and so does anyone reading it."""
        for s in list(self.server.sessions):
            if s.user_id and not s.closed:
                self.refresh_icon(s)
        for v in list(self.windows.values()):
            v.refresh()
        for session, win in list(self.readers.items()):
            if not win.shown:
                self.readers.pop(session, None)
            else:
                self.read(session, win.news_id, keep=win)

    def permissions_changed(self, session):
        self.refresh_icon(session)
        v = self.windows.get(session)
        c = self.composers.get(session)
        if c is not None and not session.can(POST):
            c.close()
        if v is None:
            return
        if not session.can(READ):
            v.close()
        else:
            v.show()                     # (the poster buttons may come or go)

    def disconnected(self, session):
        self.windows.pop(session, None)
        self.composers.pop(session, None)
        self.readers.pop(session, None)

    # ---- writing: new bulletins and edits ----

    def compose(self, session, news_id=None):
        if not session.can(POST):
            return refuse(session, TITLE, POST)
        item = self.db.bulletin(news_id) if news_id is not None else None
        if news_id is not None and item is None:
            return None
        c = Composer(session, "Edit Bulletin" if item else "New Bulletin", WIN_NEWS_EDIT,
                     key=POST, subject=item["headline"] if item else "",
                     body=item["body"].split("\n") if item else (),
                     subject_label="Headline:", send_label="Post" if item is None else "Save",
                     on_send=lambda comp, to, headline, lines: self._send(comp, news_id,
                                                                          headline, lines),
                     on_closed=self._compose_closed,
                     hint="Change it, then Save." if item else
                     "Give it a headline and write it, then Post.")
        self.composers[session] = c
        return c.show()

    def _compose_closed(self, composer):
        if self.composers.get(composer.session) is composer:
            del self.composers[composer.session]

    def _send(self, composer, news_id, headline, lines):
        session = composer.session
        if not headline:
            return "Give it a headline."
        headline = clean_text(headline)
        if news_id is None:
            news_id = self.db.post_news(headline, lines, session.user_id)
            session.log("posted news %d: %s" % (news_id, headline))
            done = "Posted."
        else:
            if self.db.bulletin(news_id) is None:
                return "That bulletin was deleted."
            self.db.edit_news(news_id, headline, lines, session.user_id)
            session.log("edited news %d: %s" % (news_id, headline))
            done = "Saved."
        composer.close()
        v = self.windows.get(session)
        if v is not None:
            v.news_id = news_id
        self.changed()
        if v is not None:
            v.say(done)
        return None


class NewsWindow:
    """One user's News window (WIN_NEWS)."""

    def __init__(self, news, session):
        self.news = news
        self.session = session
        self.win = None
        self.ids = []                    # list row -> bulletin id
        self.news_id = None              # the picked one
        self.need = []                   # buttons that need a bulletin picked

    @property
    def db(self):
        return self.news.db

    @property
    def poster(self):
        return self.session.can(POST)

    # ---- what it shows ----

    def rows(self):
        items = self.db.news()
        self.ids = [n["id"] for n in items]
        unread = set(self.news.unread(self.session))
        return [("%s %s %s" % ("*" if n["id"] in unread else " ", when(n["posted"], "%m-%d"),
                               n["headline"]))[:ROW_COLS] for n in items]

    def heading(self):
        items = self.db.news()
        if not items:
            return "No news yet."
        return "%d bulletin%s, %d unread (*)." % (
            len(items), "" if len(items) == 1 else "s", self.news.new_count(self.session))

    def hint(self):
        if not self.ids:
            return "No news yet." + (" New... writes one." if self.poster else "")
        return "Pick a bulletin and Read it."

    # ---- the list window ----

    def show(self, status=None):
        self.news.windows[self.session] = self
        a = AreaWindow(TITLE, WIN_NEWS, on_close=self._closed)
        win = self.win = a.win
        rows = self.rows()
        if self.news_id not in self.ids:
            self.news_id = None
        self.head = a.heading(self.heading())
        self.list = a.list(rows, self._pick, columns="  %-5s %s" % ("Date", "Headline"))
        if self.news_id in self.ids:
            self.list.selected = self.ids.index(self.news_id)
        self.need = [a.command("Read", self._read, default=True)]
        self.all_b = a.command("Mark All Read", self._all_read)
        if self.poster:
            a.section("Admin Tools")
            new_b, edit_b = a.pair(("New...", self._new), ("Edit...", self._edit))
            self.need += [edit_b, a.pair(("Delete", self._delete))]
        self.status = a.status(status or self.hint())
        self.buttons()
        win.show(self.session)
        if self.list.selected is not None:
            self.list.set_value(self.list.selected)
        return self

    def refresh(self):
        if self.win is None or not self.win.shown:
            return
        self.list.set_rows(self.rows())
        if self.news_id not in self.ids:
            self.news_id = None
        if self.news_id in self.ids:
            self.list.selected = self.ids.index(self.news_id)
            self.list.set_value(self.list.selected)
        self.head.set_text(self.heading())
        self.status.set_text(self.hint())
        self.buttons()

    def buttons(self):
        on = self.news_id in self.ids
        for b in self.need:
            b.enable(on)
        self.all_b.enable(bool(self.news.unread(self.session)))

    def say(self, text):
        self.status.set_text(text)

    def close(self):
        self.news.readers.pop(self.session, None)
        for win_id in (WIN_NEWS_READ, WIN_NEWS_DELETE, WIN_NEWS):
            win = self.session.windows.get(win_id)
            if win is not None:
                win.close()
        self._closed(None)

    def _closed(self, window):
        if self.news.windows.get(self.session) is self:
            del self.news.windows[self.session]

    def _all_read(self, button):
        if self._ok():
            self.news.mark_read(self.session, self.news.unread(self.session))
            self.say("All marked read.")

    def _ok(self, key=READ):
        if not self.session.can(key):
            refuse(self.session, TITLE, key)
            return False
        return True

    # ---- handlers ----

    def _pick(self, listbox, index, double):
        """A click on a bulletin picks it (Read, Edit, Delete); a double click reads it."""
        if not self._ok() or listbox.selected is None:
            return None
        self.news_id = self.ids[listbox.selected]
        self.buttons()
        self.say("")
        if double:
            return self.news.read(self.session, self.news_id)
        return None

    def _read(self, button):
        if not self._ok():
            return None
        if self.news_id not in self.ids:
            return self.say("Pick a bulletin first.")
        return self.news.read(self.session, self.news_id)

    def _new(self, button):
        if self._ok(POST):
            self.news.compose(self.session)

    def _edit(self, button):
        if not self._ok(POST):
            return None
        if self.news_id not in self.ids:
            return self.say("Pick a bulletin first.")
        return self.news.compose(self.session, self.news_id)

    def _delete(self, button):
        if not self._ok(POST):
            return None
        item = self.db.bulletin(self.news_id) if self.news_id in self.ids else None
        if item is None:
            return self.say("Pick a bulletin first.")
        win = Window.centred("Delete Bulletin", 360, 50,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_NEWS_DELETE)
        win.news_id = item["id"]
        win.add(Label(8, 4, 344, 10, ("Delete \"%s\"?" % item["headline"][:32])))
        win.add(Label(8, 16, 344, 10, "This can't be undone."))
        add_buttons(win, [("Delete", self._confirm_delete, 0),
                          ("Cancel", closer, GFlag.DEFAULT)], centre=True)
        win.show(self.session)
        return None

    def _confirm_delete(self, button):
        win = button.window
        win.close()
        if not self._ok(POST):
            return None
        item = self.db.bulletin(win.news_id)
        if item is None:
            return None
        self.db.delete_news(item["id"])
        self.session.log("deleted news %d: %s" % (item["id"], item["headline"]))
        self.news_id = None
        self.news.changed()
        return self.say("Deleted the bulletin.")
