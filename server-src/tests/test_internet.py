"""Areas > Internet and its Web Browser (internet/), with the page fetching stubbed out; and
the HTML to text conversion and the address checks (internet/webtext.py), offline."""

import socket
import unittest

from meganet.internet import WIN_INTERNET, webtext
from meganet.internet.web import WIN_WEB, PAGE_LINES
from meganet.protocol import Kind
from tests.test_server import ServerTest

PAGE = """<html><head><title>A  Test
Page</title><style>p {color: red}</style><script>alert("no")</script></head>
<body><h1>Hello</h1><p>Some <b>bold</b> text with a <a href="/next">link to next</a>
and &ldquo;quotes&rdquo; &amp; caf&eacute;.</p>
<ul><li>one</li><li>two <a href="https://other.example/x">other</a></li></ul>
<a href="javascript:void(0)">nothing</a><a href="#top">top</a>
<pre>  keep
    this</pre><img src="x.png" alt="a cat"></body></html>"""


def gid_of(win, kind):
    return next(gid for gid, g in win.gadgets.items() if g["kind"] == kind)


class WebTextTest(unittest.TestCase):
    def test_html_to_text(self):
        page = webtext.html_to_page(PAGE, "https://site.example/a/b.html")
        self.assertEqual(page.title, "A Test Page")
        self.assertEqual(page.paragraphs, [
            "HELLO", "",
            'Some bold text with a link to next[1] and "quotes" & cafe.', "",
            "* one", "* two other[2]", "",
            "nothingtop",                        # (no numbers: not links to follow)
            "",
            "  keep", "    this", "",
            "[a cat]"])
        self.assertEqual(page.links, [("link to next", "https://site.example/next"),
                                      ("other", "https://other.example/x")])

    def test_wrap(self):
        lines = webtext.wrap(["* a list item that goes on and on", "", "short"], 16)
        self.assertEqual(lines, ["* a list item", "  that goes on", "  and on", "", "short"])

    def test_to_url(self):
        self.assertEqual(webtext.to_url("example.com"), "https://example.com")
        self.assertEqual(webtext.to_url("http://x.org/a"), "http://x.org/a")
        self.assertEqual(webtext.to_url("mega65 games"),
                         webtext.SEARCH_URL % "mega65+games")
        self.assertEqual(webtext.to_url("wikipedia"), webtext.SEARCH_URL % "wikipedia")

    def test_private_addresses_refused(self):
        def resolve(addr):
            return lambda host, port, type=0: [(socket.AF_INET, type, 6, "", (addr, port))]
        for addr in ("127.0.0.1", "10.1.2.3", "192.168.0.1", "172.16.5.5", "169.254.1.1",
                     "0.0.0.0", "::1", "fe80::1", "fc00::5"):
            with self.assertRaises(webtext.WebError, msg=addr):
                webtext.check_url("http://router.example/", resolve(addr))
        webtext.check_url("https://example.com/", resolve("93.184.216.34"))
        with self.assertRaises(webtext.WebError):
            webtext.check_url("file:///etc/passwd")
        with self.assertRaises(webtext.WebError):
            webtext.check_url("ftp://example.com/")

    def test_search_links_unwrapped(self):
        self.assertEqual(webtext.unwrap_search_link(
            "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fmega65.org%2F&rut=x"),
            "https://mega65.org/")


class BrowserTest(ServerTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.browser = next(s for s in self.server.screens.internet.services
                            if s.name == "Web Browser")
        self.fetched = []

        def fake_fetch(url):
            self.fetched.append(url)
            if "private" in url:
                raise webtext.WebError("private.example is on a private network: it can't "
                                       "be opened.")
            if "long" in url:
                return webtext.Page(url, "Long", ["line %d" % i for i in range(300)], [])
            return webtext.html_to_page(PAGE, url)
        self.browser.fetch = fake_fetch

    async def browser_window(self, c):
        c.pick("Internet")
        w = await c.wait_window("Internet")
        lb = gid_of(w, Kind.LISTBOX)
        await c.wait_for(lambda: w.gadgets[lb]["rows"], "the services")
        self.assertTrue(w.gadgets[lb]["rows"][0].startswith("Web Browser"))
        c.select(WIN_INTERNET, lb, 0, double=True)
        return await c.wait_window("Web Browser")

    def labels(self, w):
        return [g["text"] for g in w.gadgets.values() if g["kind"] == Kind.LABEL]

    def text(self, w):
        return w.gadgets[gid_of(w, Kind.TEXTVIEW)]["lines"]

    def links(self, w):
        return w.gadgets[gid_of(w, Kind.LISTBOX)]["rows"]

    async def go(self, c, w, address):
        c.value(w.id, gid_of(w, Kind.TEXTBOX), address)
        c.click_text(w.id, "Go")

    async def test_browse(self):
        a = await self.signed_on("alice")                  # (Sysop: everything)
        self.assertIn("Internet", a.menu_items("Areas"))
        w = await self.browser_window(a)
        self.assertTrue(any("Type an address" in line for line in self.text(w)))
        await self.go(a, w, "site.example/a/b.html")
        await a.wait_for(lambda: self.labels(w)[1] == "A Test Page", "the page")
        self.assertEqual(self.fetched, ["https://site.example/a/b.html"])
        self.assertIn("HELLO", self.text(w))
        self.assertEqual(self.links(w), ["1 link to next", "2 other"])
        self.assertEqual(self.labels(w)[2], "Links (2):")
        # a link: opened; Back: the page before, without fetching it again
        a.select(WIN_WEB, gid_of(w, Kind.LISTBOX), 1)
        await a.wait_for(lambda: len(self.fetched) == 2, "the link")
        self.assertEqual(self.fetched[1], "https://other.example/x")
        await a.wait_for(lambda: w.gadgets[gid_of(w, Kind.TEXTBOX)]["text"]
                         == "https://other.example/x", "its address")
        a.click_text(w.id, "Back")
        await a.wait_for(lambda: w.gadgets[gid_of(w, Kind.TEXTBOX)]["text"]
                         == "https://site.example/a/b.html", "back")
        self.assertEqual(len(self.fetched), 2)
        # words: a search
        await self.go(a, w, "mega65 games")
        await a.wait_for(lambda: len(self.fetched) == 3, "the search")
        self.assertEqual(self.fetched[2], webtext.SEARCH_URL % "mega65+games")
        # a long page: in pages of PAGE_LINES
        await self.go(a, w, "long.example")
        await a.wait_for(lambda: self.labels(w)[-1] == "Page 1 of 3", "pages")
        self.assertEqual(len(self.text(w)), PAGE_LINES)
        self.assertFalse(a.enabled(w.id, "Prev Page"))
        a.click_text(w.id, "Next Page")
        await a.wait_for(lambda: self.labels(w)[-1] == "Page 2 of 3", "page 2")
        self.assertEqual(self.text(w)[0], "line %d" % PAGE_LINES)
        # refused: the message instead of the title; the page stays
        await self.go(a, w, "private.example")
        await a.wait_for(lambda: "private network" in self.labels(w)[1], "refused")
        self.assertEqual(self.text(w)[0], "line %d" % PAGE_LINES)
        rows = self.server.db.log_entries(text="web: https://long.example")[0]
        self.assertTrue(rows, "the URL is in the Server Log")
        self.assertEqual(rows[0]["area"], "internet")

    async def test_new_users_cant(self):
        await self.signed_on("alice")
        b = await self.signed_on("bob")                    # a New User
        self.assertNotIn("Internet", b.menu_items("Areas"))
        self.server.screens.internet.open(self.server.find_user("bob"))
        await b.wait_for(lambda: b.alerts, "refused")
        self.assertNotIn(WIN_INTERNET, b.windows)
