"""Internet > Web Browser: web pages as text (webtext.py), for MEGA65 screens.

The window (57, 624x166): an address box with Go and Back, the page's title, its text on the
left (wrapped to the view, PAGE_LINES lines a page, Prev Page / Next Page for the rest), and
its links on the right: link n is marked [n] in the text, and a click on it in the list
opens it. Words that aren't an address are a search (webtext.SEARCH_URL).

Pages load in the background: the window says "Loading ...", and the session can still do
anything else; another Go while one loads replaces it. Each URL opened goes in the Server
Log (area "internet"). No JavaScript, no pictures, no forms yet (a search box is the address
box).
"""

import asyncio

from .. import permissions
from ..protocol import GFlag
from ..ui import Window, Label, TextBox, TextView, ListBox, Button, MARGIN
from . import webtext
from .base import Integration

WEB = permissions.register("internet.web", "Browse the web (text)", like="internet.use")
WIN_WEB = 57
WIN_W, WIN_H = 624, 166
TEXT_W = 424                     # the page's text view
PAGE_LINES = 120                 # lines a page (the client's text views keep 128)
HISTORY = 20                     # pages Back remembers (their text is kept: no reload)
HOME = [
    "Type an address and click Go (or press RETURN):",
    "",
    "  example.com",
    "  en.wikipedia.org/wiki/MEGA65",
    "",
    "or some words to search the web for them.",
    "",
    "Pages come as text: no pictures, no JavaScript. Links are",
    "numbered [1], [2]... in the text; click one in the list on the",
    "right to open it.",
]


class Tab:
    """One user's browser window and where it is."""

    def __init__(self, session):
        self.session = session
        self.win = None
        self.page = None             # the webtext.Page shown, None = the start page
        self.lines = HOME
        self.at = 0                  # first line shown
        self.history = []            # pages before this one
        self.loading = None          # the asyncio.Task fetching, if any
        self.full_url = ""           # the address box's whole URL (it shows 63 characters)
        self.generation = 0          # bumped per load: a stale result is dropped


class WebBrowser(Integration):
    name = "Web Browser"
    description = "Web pages as text, with their links."
    permission = WEB
    order = 10

    def __init__(self, server):
        super().__init__(server)
        self.tabs = {}               # session -> Tab
        self.fetch = webtext.fetch   # (tests replace it)

    # ---- the window ----

    def open(self, session):
        tab = self.tabs.get(session)
        if tab is None:
            tab = self.tabs[session] = Tab(session)
        self._window(tab)
        return None

    def _window(self, tab):
        win = Window("Web Browser", 4, 13, WIN_W, WIN_H, win_id=WIN_WEB,
                     on_close=lambda w: self._closed(tab))
        win.add(Label(MARGIN, 4, 64, 10, "Address:"))
        tab.address = win.add(TextBox(72, 2, 392, 12, tab.full_url[:63]))
        win.add(Button(472, 0, 72, 16, "Go", GFlag.DEFAULT, on_click=lambda b: self.go(tab)))
        tab.back_b = win.add(Button(552, 0, 72, 16, "Back", on_click=lambda b: self.back(tab)))
        tab.title = win.add(Label(MARGIN, 20, TEXT_W, 10, "", flags=GFlag.BOLD))
        tab.links_l = win.add(Label(TEXT_W + 16, 20, WIN_W - TEXT_W - 16, 10, "Links:"))
        tab.view = win.add(TextView(MARGIN, 32, TEXT_W, 110))
        tab.links = win.add(ListBox(TEXT_W + 16, 32, WIN_W - TEXT_W - 16, 110,
                                    on_select=lambda g, i, d: self.follow(tab, i)))
        tab.prev_b = win.add(Button(MARGIN, 146, 104, 16, "Prev Page",
                                    on_click=lambda b: self.turn(tab, -1)))
        tab.next_b = win.add(Button(120, 146, 104, 16, "Next Page",
                                    on_click=lambda b: self.turn(tab, 1)))
        tab.page_l = win.add(Label(232, 150, 200, 10, ""))
        tab.win = win
        win.show(tab.session)
        self.show(tab)

    def columns(self, tab):
        return tab.view.columns()

    def show(self, tab, status=None):
        """Put the page (or the start page) in the window, at tab.at."""
        page = tab.page
        if status is not None:
            tab.title.set_text(status[:TEXT_W // 8])
        else:
            tab.title.set_text((page.title if page else "Web Browser")[:TEXT_W // 8])
        part = tab.lines[tab.at:tab.at + PAGE_LINES]
        if page and page.note and tab.at + PAGE_LINES >= len(tab.lines):
            part = part + ["", page.note]
        tab.view.set_lines(part, top=True)
        links = page.links if page else []
        tab.links.set_rows(["%d %s" % (i + 1, text) for i, (text, _) in enumerate(links)])
        tab.links_l.set_text("Links (%d):" % len(links) if links else "Links:")
        pages = max(1, (len(tab.lines) + PAGE_LINES - 1) // PAGE_LINES)
        here = tab.at // PAGE_LINES + 1
        tab.page_l.set_text("Page %d of %d" % (here, pages) if pages > 1 else "")
        tab.prev_b.enable(tab.at > 0)
        tab.next_b.enable(tab.at + PAGE_LINES < len(tab.lines))
        tab.back_b.enable(bool(tab.history))

    # ---- moving about ----

    def go(self, tab, target=None):
        """Load what's in the address box (or `target`, a URL)."""
        text = (target if target is not None else tab.address.value).strip()
        if target is None and tab.full_url and text == tab.full_url[:63]:
            text = tab.full_url                      # (the box only holds 63 characters)
        try:
            url = webtext.to_url(text)
        except webtext.WebError as e:
            return self.show(tab, str(e))
        if target is not None:
            self.set_address(tab, url)
        tab.generation += 1
        if tab.loading is not None:
            tab.loading.cancel()
        tab.title.set_text(("Loading %s..." % url)[:TEXT_W // 8])
        tab.session.log("web: %s" % url)
        tab.loading = asyncio.ensure_future(self._load(tab, url, tab.generation))
        return None

    async def _load(self, tab, url, generation):
        try:
            page = await asyncio.to_thread(self.fetch, url)
        except asyncio.CancelledError:
            return
        except webtext.WebError as e:
            if generation == tab.generation and tab.win is not None:
                tab.loading = None
                tab.session.warn("web: %s: %s" % (url, e))
                self.show(tab, str(e))
            return
        except Exception as e:                       # (a bug in the converter, say)
            if generation == tab.generation and tab.win is not None:
                tab.loading = None
                tab.session.error("web: %s: %r" % (url, e))
                self.show(tab, "That page couldn't be shown.")
            return
        if generation != tab.generation or tab.win is None or tab.session.closed:
            return
        tab.loading = None
        tab.history.append((tab.page, tab.lines, tab.at))
        del tab.history[:-HISTORY]
        tab.page = page
        tab.lines = webtext.wrap(page.paragraphs, self.columns(tab)) or ["(This page is empty.)"]
        tab.at = 0
        self.set_address(tab, page.url)
        self.show(tab)

    @staticmethod
    def set_address(tab, url):
        """The address box shows at most 63 characters: remember the whole URL, so Go on an
        unchanged box opens that, not the cut one."""
        tab.full_url = url
        tab.address.set_text(url[:63])

    def follow(self, tab, index):
        if tab.page is None or not 0 <= index < len(tab.page.links):
            return None
        return self.go(tab, tab.page.links[index][1])

    def back(self, tab):
        if not tab.history:
            return None
        tab.generation += 1                          # (a load in progress is dropped)
        tab.page, tab.lines, tab.at = tab.history.pop()
        self.set_address(tab, tab.page.url if tab.page else "")
        self.show(tab)
        return None

    def turn(self, tab, step):
        at = tab.at + step * PAGE_LINES
        if 0 <= at < len(tab.lines):
            tab.at = at
            self.show(tab)

    # ---- leaving ----

    def _closed(self, tab):
        tab.generation += 1
        tab.win = None
        if tab.loading is not None:
            tab.loading.cancel()
            tab.loading = None
        self.tabs.pop(tab.session, None)

    def disconnected(self, session):
        tab = self.tabs.get(session)
        if tab is not None:
            self._closed(tab)

    def permissions_changed(self, session):
        tab = self.tabs.get(session)
        if tab is not None and not (session.can(permissions.INTERNET_USE)
                                    and session.can(WEB)):
            win = tab.win
            self._closed(tab)
            if win is not None:
                win.on_close = None
                win.close()
