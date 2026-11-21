"""Internet > News Feeds (internet/feeds.py) with the fetching stubbed out, and the RSS / Atom
parsing (internet/feedparse.py) offline."""

import unittest

from meganet import db as dbmod
from meganet.internet import WIN_INTERNET, feedparse, webtext
from meganet.internet.feeds import NewsFeeds
from meganet.internet.web import WIN_WEB
from meganet.protocol import Kind
from tests.test_server import ServerTest

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<title>Retro Daily</title>
<item><title>New  MEGA65 game released</title><link>https://retro.example/game</link>
<pubDate>Fri, 21 Nov 2026 14:05:00 GMT</pubDate>
<description>&lt;p&gt;A &lt;b&gt;great&lt;/b&gt; shooter &amp;mdash; out now. &lt;a href="/x"&gt;More&lt;/a&gt;&lt;/p&gt;</description></item>
<item><title>Second story</title><link>https://retro.example/two</link></item>
<item><title></title><link>https://retro.example/none</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom News</title>
<entry><title>Atom story</title><link rel="alternate" href="https://atom.example/1"/>
<updated>2026-11-20T09:30:00Z</updated><summary>Plain summary.</summary></entry>
</feed>"""

RDF = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>Old School</title></channel>
<item><title>RDF story</title><link>https://rdf.example/a</link><dc:date>2026-11-19T08:00:00+00:00</dc:date>
<description>Text.</description></item></rdf:RDF>"""

BOMB = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><rss><channel>
<title>&lol;</title></channel></rss>"""


class ParseTest(unittest.TestCase):
    def test_rss(self):
        f = feedparse.parse(RSS)
        self.assertEqual(f.title, "Retro Daily")
        self.assertEqual([i.title for i in f.items], ["New MEGA65 game released", "Second story"],
                         "an item without a title is dropped")
        i = f.items[0]
        self.assertEqual(i.link, "https://retro.example/game")
        self.assertEqual(i.when, 1795269900.0)
        self.assertEqual(i.summary, ["A great shooter -- out now. More"])
        self.assertEqual(f.items[1].summary, [])

    def test_atom_and_rdf(self):
        f = feedparse.parse(ATOM)
        self.assertEqual((f.title, f.items[0].title, f.items[0].link, f.items[0].summary),
                         ("Atom News", "Atom story", "https://atom.example/1", ["Plain summary."]))
        self.assertEqual(f.items[0].when, 1795167000.0)
        f = feedparse.parse(RDF)
        self.assertEqual((f.title, f.items[0].title, f.items[0].link),
                         ("Old School", "RDF story", "https://rdf.example/a"))

    def test_not_feeds(self):
        for data in (b"<html><body>hi</body></html>", b"not xml at all", BOMB):
            with self.assertRaises(webtext.WebError, msg=data[:20]):
                feedparse.parse(data)

    def test_default_feeds(self):
        self.assertTrue(all(len(n) <= dbmod.FEED_NAME_MAX and u.startswith("https://")
                            for n, u in dbmod.DEFAULT_FEEDS))


def gid(win, kind, nth=0):
    return [g for g, x in sorted(win.gadgets.items()) if x["kind"] == kind][nth]


class FeedsTest(ServerTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.feeds = next(s for s in self.server.screens.internet.services
                          if isinstance(s, NewsFeeds))
        self.fetched = []

        def fake_fetch(url, accept=None):
            self.fetched.append(url)
            if "broken" in url:
                raise webtext.WebError("The site answered 404 Not Found.")
            data = ATOM if "atom" in url else RSS if "retro" in url else b"<html>no</html>"
            return webtext.Fetched(url, "text/xml", "utf-8", data, None)
        self.feeds.fetch = fake_fetch
        db = self.server.db
        for f in db.feeds():
            db.delete_feed(f["id"])
        db.add_feed("Retro Daily", "https://retro.example/rss")
        db.add_feed("Atom News", "https://atom.example/feed")
        db.add_feed("Broken", "https://broken.example/rss")

    async def window(self, c):
        c.pick("Internet")
        w = await c.wait_window("Internet")
        lb = gid(w, Kind.LISTBOX)
        await c.wait_for(lambda: w.gadgets[lb]["rows"], "the services")
        row = w.gadgets[lb]["rows"].index("News Feeds")
        c.select(WIN_INTERNET, lb, row, double=True)
        return await c.wait_window("News Feeds")

    @staticmethod
    def head(w):
        return [x["text"] for x in w.gadgets.values() if x["kind"] == Kind.LABEL][1]

    @staticmethod
    def rows(w, nth):
        return w.gadgets[gid(w, Kind.LISTBOX, nth)]["rows"]

    @staticmethod
    def text(w):
        return w.gadgets[gid(w, Kind.TEXTVIEW)]["lines"]

    async def test_read_and_open_in_browser(self):
        a = await self.signed_on("alice")
        w = await self.window(a)
        self.assertEqual(self.rows(w, 0), ["Retro Daily", "Atom News", "Broken"])
        a.select(w.id, gid(w, Kind.LISTBOX, 0), 0)
        await a.wait_for(lambda: self.head(w).startswith("Retro Daily: 2 stories"), "loaded")
        self.assertTrue(self.rows(w, 1)[0].endswith("New MEGA65 game released"))
        self.assertEqual(self.fetched, ["https://retro.example/rss"])
        a.select(w.id, gid(w, Kind.LISTBOX, 1), 0)
        await a.wait_for(lambda: "A great shooter -- out now. More" in self.text(w), "summary")
        self.assertEqual(self.text(w)[0], "New MEGA65 game released")
        # the cache: picked again, not fetched again
        a.select(w.id, gid(w, Kind.LISTBOX, 0), 1)
        await a.wait_for(lambda: self.head(w).startswith("Atom News: 1 story"), "atom")
        a.select(w.id, gid(w, Kind.LISTBOX, 0), 0)
        await a.wait_for(lambda: self.head(w).startswith("Retro Daily"), "again")
        self.assertEqual(len(self.fetched), 2)
        # Refresh fetches it again
        a.click_text(w.id, "Refresh")
        await a.wait_for(lambda: len(self.fetched) == 3, "refreshed")
        # a broken feed says why
        a.select(w.id, gid(w, Kind.LISTBOX, 0), 2)
        await a.wait_for(lambda: "404" in self.head(w), "the problem")
        # a story opens in the Web Browser (stubbed too)
        browser = next(s for s in self.server.screens.internet.services if s.name == "Web Browser")
        opened = []
        browser.fetch = lambda url: (opened.append(url),
                                     webtext.Page(url, "Story", ["The whole story."], []))[1]
        a.select(w.id, gid(w, Kind.LISTBOX, 0), 0)
        await a.wait_for(lambda: self.head(w).startswith("Retro Daily"), "back")
        a.select(w.id, gid(w, Kind.LISTBOX, 1), 0, double=True)
        await a.wait_for(lambda: opened == ["https://retro.example/game"], "browser")
        await a.wait_for(lambda: WIN_WEB in a.windows, "the browser window")

    async def test_add_and_remove(self):
        a = await self.signed_on("alice")                  # (Sysop: internet.manage)
        w = await self.window(a)
        a.click_text(w.id, "Add Feed...")
        d = await a.wait_window("Add Feed")
        a.value(d.id, gid(d, Kind.TEXTBOX, 0), "Not a feed")
        a.value(d.id, gid(d, Kind.TEXTBOX, 1), "nofeed.example/page")
        a.click_text(d.id, "Add")
        await a.wait_for(lambda: any("isn't a news feed" in x["text"]
                                     for x in d.gadgets.values()), "refused")
        a.value(d.id, gid(d, Kind.TEXTBOX, 0), "More Retro")
        a.value(d.id, gid(d, Kind.TEXTBOX, 1), "retro.example/more")
        a.click_text(d.id, "Add")
        await a.wait_for(lambda: self.rows(w, 0)[-1:] == ["More Retro"], "added")
        self.assertEqual(self.server.db.feeds()[-1]["url"], "https://retro.example/more")
        # Remove (after "are you sure")
        a.select(w.id, gid(w, Kind.LISTBOX, 0), 3)
        a.click_text(w.id, "Remove")
        ask = await a.wait_window("Remove Feed")
        a.click_text(ask.id, "Remove")
        await a.wait_for(lambda: "More Retro" not in self.rows(w, 0), "removed")

    async def test_members_can_read_but_not_manage(self):
        a = await self.signed_on("alice")                  # (the first: Sysop)
        db = self.server.db
        b = await self.signed_on("bob")
        member = db.role_by_name("Member")["id"]
        db.set_user_role(db.user("bob")["id"], member)
        self.server.permissions_changed(user_id=db.user("bob")["id"])
        await b.wait_for(lambda: "Internet" in b.menu_items("Areas"), "Internet for members")
        w = await self.window(b)
        self.assertFalse(any(x["text"] in ("Add Feed...", "Remove") for x in w.gadgets.values()))
        self.feeds.ask_add(self.feeds.readers[next(s for s in self.server.sessions
                                                   if s.user == "bob")])
        await b.wait_for(lambda: b.alerts, "refused")
        self.assertIn("can't change the feeds", b.alerts[-1][1])
