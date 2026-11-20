"""The text browser's insides (internet/web.py): fetching a page safely, and turning HTML into
lines of plain ASCII with numbered links. Standard library only, no JavaScript.

    page = fetch("example.com")           # (blocking: run it in a thread) -> Page
    page.paragraphs, page.links, page.title

Safety: only http and https, and never an address on a private network (the server's own
machine, the LAN, link-local...), redirects included: otherwise anyone could use the server to
reach the router's admin page. At most MAX_BYTES are read, with a TIMEOUT.
"""

import html.parser
import ipaddress
import re
import socket
import ssl
import textwrap
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 15                     # seconds for the whole request
MAX_BYTES = 1_000_000            # read at most this much of a page
USER_AGENT = "MegaNet-TextBrowser/0.1 (MEGA65)"
SEARCH_URL = "https://lite.duckduckgo.com/lite/?q=%s"     # words in the address box


class WebError(Exception):
    """Something the user is told: "Can't find example.invalid." and so on."""


class Page:
    def __init__(self, url, title, paragraphs, links, note=None):
        self.url = url               # where it ended up (after redirects)
        self.title = title
        self.paragraphs = paragraphs # text lines, unwrapped; "" = a blank line
        self.links = links           # [(text, url)], link n shown as [n] (n from 1)
        self.note = note             # e.g. "Only the first 1,000,000 bytes."


# ---- addresses ----

def to_url(text):
    """What the user typed -> a URL: an address as it is (https:// added when there's no
    scheme), anything with spaces or without a dot a search."""
    text = text.strip()
    if not text:
        raise WebError("Type an address or something to search for.")
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        return text
    if " " in text or "." not in text.split("/")[0]:
        return SEARCH_URL % urllib.parse.quote_plus(text)
    return "https://" + text


def check_url(url, resolve=socket.getaddrinfo):
    """Raise WebError unless `url` is http(s) to a host whose every address is public."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise WebError("Only http and https addresses can be opened.")
    host = parts.hostname
    if not host:
        raise WebError("That address has no host name.")
    try:
        infos = resolve(host, parts.port or (443 if parts.scheme == "https" else 80),
                        type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise WebError("Can't find %s." % host) from None
    for info in infos:
        addr = ipaddress.ip_address(info[4][0].split("%")[0])
        if not addr.is_global or addr.is_multicast:
            raise WebError("%s is on a private network: it can't be opened." % host)


_ssl = {"context": None}


def set_cafile(path):
    """Trust the certificates in `path` (a PEM file) for https (the server's --cafile), for
    a Python without a certificate list of its own."""
    _ssl["context"] = ssl.create_default_context(cafile=path)


def ssl_context():
    if _ssl["context"] is None:
        _ssl["context"] = ssl.create_default_context()
    return _ssl["context"]


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)                           # (a redirect to the LAN: refused too)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def unwrap_search_link(url):
    """DuckDuckGo's result links go through /l/?uddg=<the real one>: take the real one."""
    parts = urllib.parse.urlsplit(url)
    if parts.hostname and parts.hostname.endswith("duckduckgo.com") and parts.path == "/l/":
        real = urllib.parse.parse_qs(parts.query).get("uddg")
        if real:
            return real[0]
    return url


def fetch(text_or_url, resolve=socket.getaddrinfo):
    """Fetch and convert a page (blocking). Raises WebError with a message for the user."""
    url = to_url(text_or_url)
    check_url(url, resolve)
    opener = urllib.request.build_opener(_Redirects,
                                         urllib.request.HTTPSHandler(context=ssl_context()))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "text/html, text/plain;q=0.9"})
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            final = resp.geturl()
            ctype = resp.headers.get_content_type()
            charset = resp.headers.get_content_charset()
            data = resp.read(MAX_BYTES + 1)
    except WebError:
        raise
    except urllib.error.HTTPError as e:
        raise WebError("The site answered %d %s." % (e.code, e.reason)) from None
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, WebError):
            raise reason from None
        if isinstance(reason, socket.timeout):
            raise WebError("The site took too long to answer.") from None
        if isinstance(reason, ssl.SSLCertVerificationError):
            if not ssl_context().cert_store_stats().get("x509_ca"):
                raise WebError("The server has no list of trusted certificates: start it "
                               "with --cafile.") from None
            raise WebError("The site's certificate can't be trusted.") from None
        raise WebError("Can't open that page: %s." % reason) from None
    except (socket.timeout, TimeoutError):
        raise WebError("The site took too long to answer.") from None
    except (OSError, ValueError) as e:
        raise WebError("Can't open that page: %s." % e) from None
    note = None
    if len(data) > MAX_BYTES:
        data = data[:MAX_BYTES]
        note = "(Only the first %d KB of this page.)" % (MAX_BYTES // 1000)
    if ctype not in ("text/html", "application/xhtml+xml", "text/plain"):
        raise WebError("That's a %s file: the text browser shows only web pages." % ctype)
    text = data.decode(charset or sniff_charset(data) or "utf-8", errors="replace")
    if ctype == "text/plain":
        lines = [ascii_text(line.rstrip()) for line in text.splitlines()]
        return Page(final, final, lines, [], note)
    return html_to_page(text, final, note)


def sniff_charset(data):
    m = re.search(rb"""<meta[^>]+charset\s*=\s*["']?([a-zA-Z0-9_-]+)""", data[:4096], re.I)
    if m:
        name = m.group(1).decode("ascii")
        try:
            "".encode(name)
            return name
        except LookupError:
            return None
    return None


# ---- text ----

ASCII = {"‘": "'", "’": "'", "‚": ",", "“": '"', "”": '"',
         "„": '"', "–": "-", "—": "--", "―": "--", "…": "...",
         " ": " ", "•": "*", "·": "*", "©": "(c)", "®": "(r)",
         "™": "(tm)", "×": "x", "«": "<<", "»": ">>", "€": "EUR",
         "£": "GBP", "°": " deg", "←": "<-", "→": "->", "½": "1/2",
         "¼": "1/4", "¾": "3/4", "ß": "ss", "æ": "ae", "Æ": "AE",
         "ø": "o", "Ø": "O", "′": "'", "″": '"', "​": ""}


def ascii_text(s):
    """Plain printable ASCII: curly quotes straight, accents off, the rest dropped."""
    out = []
    for ch in s:
        if " " <= ch <= "~":
            out.append(ch)
        elif ch in ASCII:
            out.append(ASCII[ch])
        elif ch == "\n":
            out.append("\n")             # (kept: <pre> needs it; elsewhere it's a space)
        elif ch.isspace():
            out.append(" ")
        else:
            base = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
            out.append(base if base.isprintable() else "")
    return "".join(out)


BLOCK = {"p", "div", "br", "li", "tr", "table", "section", "article", "header", "footer",
         "nav", "ul", "ol", "dl", "dt", "dd", "blockquote", "pre", "hr", "form", "figure",
         "figcaption", "main", "aside", "address", "h1", "h2", "h3", "h4", "h5", "h6",
         "fieldset", "details", "summary", "center", "body", "html"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "source", "track", "wbr"}            # (no end tags)
SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "head", "object",
        "canvas", "select", "button", "textarea", "math", "nav"}


class _Text(html.parser.HTMLParser):
    """only_main: the page has a <main>: everything outside it (menus, sidebars, footers)
    is left out, reader-mode style."""

    def __init__(self, base, only_main=False):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.only_main = only_main
        self.main = 0                # <main> depth
        self.hide = None             # [tag, depth] of a hidden element being skipped
        self.paras = []
        self.cur = []
        self.skip = 0
        self.pre = 0
        self.title = None
        self.in_title = False
        self.links = []
        self.link = None             # [href, text parts] of the <a> being read
        self.lists = []              # "ul" / "ol" counters
        self.heading = None

    # paragraphs
    def flush(self, blank=False):
        line = "".join(self.cur)
        if not self.pre:
            line = re.sub(r"\s+", " ", line).strip()
        if self.heading in ("h1", "h2") and line:
            line = line.upper()
        if re.match(r"^\s*(\*|\d+\.)\s*$", line):    # a bullet with nothing left after it
            line = ""
        if line:
            self.paras.append(line)
        if blank and self.paras and self.paras[-1] != "":
            self.paras.append("")
        self.cur = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.in_title = True
            return
        if tag == "base" and a.get("href"):
            self.base = urllib.parse.urljoin(self.base, a["href"])
        if tag == "main":
            self.main += 1
        if tag in SKIP:
            self.skip += 1
            return
        if self.hide is not None:                    # inside a hidden element: count its
            if tag == self.hide[0]:                  # own tag, to find where it ends
                self.hide[1] += 1
            return
        if tag not in VOID and ("hidden" in a or a.get("aria-hidden") == "true"
                                or a.get("role") in ("navigation", "search")):
            self.hide = [tag, 1]
            return
        if self.skip or (self.only_main and not self.main):
            return
        if tag in BLOCK:
            self.flush(blank=tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "table",
                                     "blockquote", "pre", "ul", "ol", "hr"))
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading = tag
        elif tag == "pre":
            self.pre += 1
        elif tag in ("ul", "ol"):
            self.lists.append(0 if tag == "ol" else None)
        elif tag == "li":
            depth = max(0, len(self.lists) - 1)
            if self.lists and self.lists[-1] is not None:
                self.lists[-1] += 1
                mark = "%d. " % self.lists[-1]
            else:
                mark = "* "
            self.cur.append("  " * depth + mark)
        elif tag == "hr":
            self.paras.append("-" * 20)
        elif tag in ("td", "th"):
            if self.cur and "".join(self.cur).strip():
                self.cur.append("  ")
        elif tag == "img":
            alt = (a.get("alt") or "").strip()
            if alt:
                self.cur.append("[%s] " % alt)
        elif tag == "input":
            kind = (a.get("type") or "text").lower()
            if kind in ("submit", "button") and a.get("value"):
                self.cur.append("[%s]" % a["value"])
            elif kind in ("text", "search", "email", "url", "password"):
                self.cur.append("[______]")
        elif tag == "a":
            href = (a.get("href") or "").strip()
            if href and not href.startswith(("javascript:", "#", "mailto:", "tel:")):
                self.link = [unwrap_search_link(urllib.parse.urljoin(self.base, href)), []]

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
            return
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.hide is not None:
            if tag == self.hide[0]:
                self.hide[1] -= 1
                if self.hide[1] == 0:
                    self.hide = None
            return
        if tag == "main":
            self.flush(blank=True)
            self.main = max(0, self.main - 1)
            return
        if self.skip or (self.only_main and not self.main):
            return
        if tag == "a" and self.link is not None:
            href, parts = self.link
            self.link = None
            text = re.sub(r"\s+", " ", "".join(parts)).strip()
            if text:
                self.links.append((ascii_text(text), href))
                self.cur.append("[%d]" % len(self.links))
            return
        if tag in ("ul", "ol") and self.lists:
            self.lists.pop()
        if tag in BLOCK:
            self.flush(blank=tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "table",
                                     "blockquote", "pre", "ul", "ol"))
            if tag.startswith("h") and len(tag) == 2:
                self.heading = None
        if tag == "pre":                             # (after its last line is flushed)
            self.pre = max(0, self.pre - 1)

    def handle_data(self, data):
        if self.in_title:
            self.title = (self.title or "") + data
            return
        if self.skip or self.hide is not None or (self.only_main and not self.main):
            return
        data = ascii_text(data)
        if self.pre:
            lines = data.split("\n")
            for i, line in enumerate(lines):
                if i:
                    self.flush()
                self.cur.append(line)
            return
        self.cur.append(data)
        if self.link is not None:
            self.link[1].append(data)


def html_to_page(text, url, note=None):
    p = _Text(url, only_main=re.search(r"<main[\s>]", text, re.I) is not None)
    try:
        p.feed(text)
        p.close()
    except Exception:                    # (html.parser is forgiving; a page mustn't crash us)
        pass
    p.flush()
    paras = []
    for line in p.paras:                 # no runs of blank lines, none at the ends
        if line == "" and (not paras or paras[-1] == ""):
            continue
        paras.append(line)
    while paras and paras[-1] == "":
        paras.pop()
    title = ascii_text(re.sub(r"\s+", " ", p.title or "")).strip() or url
    return Page(url, title, paras, p.links, note)


def wrap(paragraphs, width):
    """Paragraphs -> screen lines of at most `width` characters (list items indented under
    their bullet)."""
    out = []
    for para in paragraphs:
        if para == "":
            out.append("")
            continue
        m = re.match(r"^(\s*(?:\* |\d+\. )?)", para)
        indent = " " * len(m.group(1)) if m and m.group(1).strip() else ""
        out.extend(textwrap.wrap(para, width, subsequent_indent=indent,
                                 break_long_words=True, break_on_hyphens=True) or [""])
    return out
