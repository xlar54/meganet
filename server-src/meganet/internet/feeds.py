"""Internet > News Feeds: headlines from RSS and Atom feeds (feedparse.py), read as text.

The window (a dynamic id, 624x166, like the Web Browser's):

    +-----------------------------------------------------------------------------+
    | Feeds              | BBC News: 33 stories (5 minutes ago)                   |
    | [BBC News       ]  | [11-21 Deal with EU not dependent on tuition fees ...] |
    | [NPR News       ]  | [11-21 ...                                            ]|
    | [...            ]  | the picked story: its headline, when, its summary      |
    |                    |                                                        |
    | [Add Feed...][Remove]               [Refresh] [Open in Browser]             |
    +-----------------------------------------------------------------------------+

Pick a feed: its stories load in the background ("Loading BBC News...") and are kept for
CACHE_SECS for everyone (Refresh fetches it again). Pick a story: its summary shows; Open in
Browser (or a double click) opens the whole story in Internet > Web Browser. The feeds are a
list in the database (db.DEFAULT_FEEDS to start with); holders of internet.manage (moderators
at first) get Add Feed... (a name and an address, tried before it's kept) and Remove. Feeds
are fetched as the browser fetches pages (webtext.fetch_raw: never on a private network).
"""

import asyncio
import logging
import time

from .. import db as dbmod
from .. import permissions
from ..protocol import GFlag, WFlag, clean_text
from ..ui import (Window, Label, TextBox, TextView, ListBox, Button, add_buttons, closer,
                  confirm, MARGIN)
from . import feedparse, webtext
from .base import Integration
from .web import WebBrowser

log = logging.getLogger("meganet")
FEEDS = permissions.register("internet.feeds", "Read news feeds", like="internet.use")
MANAGE = permissions.register("internet.manage", "Manage news feeds", like="boards.moderate")
WIN_W, WIN_H = 624, 166
LIST_X, LIST_W = 8, 176          # the feeds
RIGHT_X, RIGHT_W = 192, 424      # the stories and the picked one
CACHE_SECS = 600                 # a feed fetched less than this long ago isn't fetched again
ACCEPT = ("application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, "
          "*/*;q=0.5")
HELLO = ["Pick a feed on the left: its latest stories come up here.",
         "", "Pick a story to read its summary; Open in Browser shows the whole",
         "story in the Web Browser."]


class Reader:
    """One user's News Feeds window."""

    def __init__(self, session):
        self.session = session
        self.win = None
        self.ids = []                # feeds list row -> feed id
        self.feed_id = None          # the feed shown
        self.items = []              # its stories
        self.item = None             # the picked story's index


class NewsFeeds(Integration):
    name = "News Feeds"
    description = ("Headlines from news sites, technology, science and retro computing, "
                   "as text. Open a story in the Web Browser.")
    permission = FEEDS
    order = 20

    def __init__(self, server):
        super().__init__(server)
        self.readers = {}            # session -> Reader
        self.cache = {}              # feed id -> (when fetched, Feed)
        self.loading = {}            # feed id -> the asyncio.Task fetching it
        self.fetch = webtext.fetch_raw   # (tests replace it)

    @property
    def db(self):
        return self.server.db

    # ---- the window ----

    def open(self, session):
        r = self.readers.get(session) or Reader(session)
        self.readers[session] = r
        self._window(r)
        return None

    def _window(self, r):
        s = r.session
        win = Window("News Feeds", 4, 13, WIN_W, WIN_H, on_close=lambda w: self._closed(r))
        win.add(Label(LIST_X, 2, LIST_W, 10, "Feeds"))
        r.list = win.add(ListBox(LIST_X, 14, LIST_W, 124, self._feed_rows(r),
                                 on_select=lambda g, i, d: self._pick_feed(r, i)))
        r.head = win.add(Label(RIGHT_X, 2, RIGHT_W, 10, "Pick a feed."))
        r.stories = win.add(ListBox(RIGHT_X, 14, RIGHT_W, 52, [],
                                    on_select=lambda g, i, d: self._pick_story(r, i, d)))
        r.text = win.add(TextView(RIGHT_X, 70, RIGHT_W, 68, HELLO))
        y = WIN_H - 20
        if s.can(MANAGE):
            win.add(Button(LIST_X, y, 96, 16, "Add Feed...", on_click=lambda b: self.ask_add(r)))
            r.remove_b = win.add(Button(LIST_X + 104, y, 72, 16, "Remove", GFlag.DISABLED,
                                        on_click=lambda b: self.ask_remove(r)))
        else:
            r.remove_b = None
        r.refresh_b = win.add(Button(400, y, 72, 16, "Refresh", GFlag.DISABLED,
                                     on_click=lambda b: self.load(r, force=True)))
        r.browse_b = win.add(Button(480, y, 136, 16, "Open in Browser", GFlag.DISABLED,
                                    on_click=lambda b: self.browse(r)))
        r.win = win
        win.show(s)
        if r.feed_id in r.ids:                       # (opened again: where it was)
            r.list.selected = r.ids.index(r.feed_id)
            r.list.set_value(r.list.selected)
            self.show_feed(r)

    def _feed_rows(self, r):
        feeds = self.db.feeds()
        r.ids = [f["id"] for f in feeds]
        return [f["name"] for f in feeds]

    def _closed(self, r):
        r.win = None

    def say(self, r, text):
        if r.win is not None:
            r.head.set_text(text[:RIGHT_W // 8])

    # ---- feeds and stories ----

    def _pick_feed(self, r, index):
        if index is None or index >= len(r.ids):
            return None
        if r.remove_b is not None:
            r.remove_b.enable(True)
        r.feed_id = r.ids[index]
        return self.load(r)

    def load(self, r, force=False):
        """Show feed r.feed_id: from the cache if it's fresh, else fetched in the background."""
        f = self.db.feed(r.feed_id) if r.feed_id is not None else None
        if f is None:
            return None
        got = self.cache.get(f["id"])
        if got is not None and not force and time.time() - got[0] < CACHE_SECS:
            return self.show_feed(r)
        r.items, r.item = [], None
        r.stories.set_rows([])
        r.browse_b.enable(False)
        r.refresh_b.enable(False)
        self.say(r, "Loading %s..." % f["name"])
        if f["id"] not in self.loading:
            r.session.log("feeds: %s (%s)" % (f["name"], f["url"]))
            self.loading[f["id"]] = asyncio.ensure_future(self._fetch(f))
        return None

    async def _fetch(self, f):
        try:
            feed = await asyncio.to_thread(self._get, f["url"])
            self.cache[f["id"]] = (time.time(), feed)
            problem = None
        except webtext.WebError as e:
            problem = str(e)
        except Exception as e:                       # (a bug: told, logged)
            problem = "That feed couldn't be read."
            log.exception("feeds: %s: %r", f["url"], e)
        finally:
            self.loading.pop(f["id"], None)
        for r in list(self.readers.values()):
            if r.feed_id == f["id"] and r.win is not None and not r.session.closed:
                if problem:
                    r.refresh_b.enable(True)
                    r.session.warn("feeds: %s: %s" % (f["url"], problem))
                    self.say(r, "%s: %s" % (f["name"], problem))
                else:
                    self.show_feed(r)

    def _get(self, url):
        """Fetch and parse a feed (blocking: in a thread)."""
        return feedparse.parse(self.fetch(url, accept=ACCEPT).data)

    def show_feed(self, r):
        f = self.db.feed(r.feed_id)
        got = self.cache.get(r.feed_id)
        if f is None or got is None or r.win is None:
            return None
        when, feed = got
        r.items, r.item = feed.items, None
        r.stories.set_rows([self._story_row(i) for i in feed.items])
        r.refresh_b.enable(True)
        r.browse_b.enable(False)
        ago = int((time.time() - when) // 60)
        self.say(r, "%s: %d stor%s (%s)" % (f["name"], len(feed.items),
                                          "y" if len(feed.items) == 1 else "ies",
                                          "just now" if ago < 1 else "%d min ago" % ago))
        r.text.set_lines(["Pick a story to read it."] if feed.items else
                         ["This feed has no stories just now."], top=True)
        return None

    @staticmethod
    def _story_row(item):
        day = time.strftime("%m-%d", time.localtime(item.when)) if item.when else "     "
        return ("%s %s" % (day, item.title))[:ListBox.ROW_MAX]

    def _pick_story(self, r, index, double):
        if index is None or index >= len(r.items):
            return None
        r.item = index
        item = r.items[index]
        r.browse_b.enable(bool(item.link))
        cols = r.text.columns()
        lines = webtext.wrap([item.title], cols)
        if item.when:
            lines.append(time.strftime("%a %d %b %Y, %H:%M", time.localtime(item.when)))
        lines.append("")
        lines += webtext.wrap(item.summary, cols) or ["(No summary: Open in Browser.)"]
        r.text.set_lines(lines[:TextView.CLIENT_LINES], top=True)
        if double and item.link:
            return self.browse(r)
        return None

    def browse(self, r):
        """The picked story in Internet > Web Browser."""
        if r.item is None or r.item >= len(r.items) or not r.items[r.item].link:
            return None
        s = r.session
        browser = next((x for x in self.server.screens.internet.services
                        if isinstance(x, WebBrowser)), None)
        if browser is None or not (s.can(permissions.INTERNET_USE) and s.can(browser.permission)):
            return s.alert("News Feeds", "Your account can't use the Web Browser.")
        browser.open(s)
        return browser.go(browser.tabs[s], r.items[r.item].link)

    # ---- managing the list (internet.manage) ----

    def ask_add(self, r):
        s = r.session
        if not s.can(MANAGE):
            return s.alert("News Feeds", "Your account can't change the feeds.")
        win = Window.centred("Add Feed", 400, 62, flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE)
        win.add(Label(MARGIN, 4, 72, 10, "Name:"))
        win.name = win.add(TextBox(88, 2, 8 * dbmod.FEED_NAME_MAX + 17, 12))
        win.add(Label(MARGIN, 20, 72, 10, "Address:"))
        win.url = win.add(TextBox(88, 18, 304, 12))
        win.status = win.add(Label(MARGIN, 34, 384, 10, "The feed's RSS or Atom address."))
        add_buttons(win, [("Add", lambda b: self.add(r, win), GFlag.DEFAULT),
                          ("Cancel", closer, 0)])
        win.show(s)
        return None

    async def add(self, r, win):
        s = r.session
        if not s.can(MANAGE):
            return s.alert("News Feeds", "Your account can't change the feeds.")
        name = clean_text(win.name.value).strip()[:dbmod.FEED_NAME_MAX]
        url = win.url.value.strip()
        if not name:
            return win.status.set_text("Give the feed a name.")
        if not url:
            return win.status.set_text("Type the feed's address.")
        try:
            url = webtext.to_url(url)
        except webtext.WebError as e:
            return win.status.set_text(str(e))
        if " " in url or len(url) > dbmod.FEED_URL_MAX or "duckduckgo" in url:
            return win.status.set_text("That doesn't look like a feed's address.")
        win.status.set_text("Trying it...")
        try:
            feed = await asyncio.to_thread(self._get, url)
        except webtext.WebError as e:
            return win.status.set_text(str(e)[:48]) if win.shown else None
        if not win.shown or not s.can(MANAGE):
            return None
        feed_id = self.db.add_feed(name, url)
        self.cache[feed_id] = (time.time(), feed)
        s.log("feeds: added %s (%s)" % (name, url))
        win.close()
        self.changed()
        return None

    def ask_remove(self, r):
        f = self.db.feed(r.feed_id) if r.feed_id is not None else None
        if f is None or not r.session.can(MANAGE):
            return None
        return confirm(r.session, "Remove Feed", ["Remove %s from the feeds?" % f["name"][:20]],
                       lambda: self.remove(r, f["id"]), None, command="Remove")

    def remove(self, r, feed_id):
        f = self.db.feed(feed_id)
        if f is None or not r.session.can(MANAGE):
            return None
        self.db.delete_feed(feed_id)
        self.cache.pop(feed_id, None)
        r.session.log("feeds: removed %s" % f["name"])
        self.changed()
        return None

    def changed(self):
        """The list of feeds changed: every open window follows."""
        for r in list(self.readers.values()):
            if r.win is None:
                continue
            r.list.set_rows(self._feed_rows(r))
            if r.feed_id not in r.ids:
                r.feed_id, r.items, r.item = None, [], None
                r.list.selected = None
                r.stories.set_rows([])
                r.text.set_lines(HELLO, top=True)
                r.browse_b.enable(False)
                r.refresh_b.enable(False)
                if r.remove_b is not None:
                    r.remove_b.enable(False)
                self.say(r, "Pick a feed.")
            else:
                r.list.selected = r.ids.index(r.feed_id)
                r.list.set_value(r.list.selected)

    # ---- sessions ----

    def disconnected(self, session):
        self.readers.pop(session, None)

    def permissions_changed(self, session):
        r = self.readers.get(session)
        if r is None or r.win is None:
            return
        r.win.on_close = None
        r.win.close()
        r.win = None
        if session.can(permissions.INTERNET_USE) and session.can(FEEDS):
            self._window(r)                          # (Add / Remove may come or go)
