"""News feeds (RSS 2.0, RSS 1.0 / RDF, Atom) -> plain text for feeds.py: the feed's title and
its items (title, link, when, a summary as text paragraphs). Standard library only.

A feed is read with xml.etree (expat); one that declares entities is refused, so a hostile
feed can't blow up in memory. Summaries are often HTML: webtext's converter makes them text.
"""

import datetime
import email.utils
import re
import xml.etree.ElementTree as ET

from .webtext import WebError, ascii_text, html_to_page

MAX_ITEMS = 50                   # items kept from a feed
SUMMARY_MAX = 1500               # characters of an item's summary


class Item:
    def __init__(self, title, link, when, summary):
        self.title = title           # one line of ASCII
        self.link = link             # its web page ("" if none)
        self.when = when             # seconds since the epoch, or None
        self.summary = summary       # text paragraphs ("" = a blank line)


class Feed:
    def __init__(self, title, items):
        self.title = title
        self.items = items


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(el, *names):
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _text(el, *names):
    c = _child(el, *names)
    return "".join(c.itertext()).strip() if c is not None else ""


def one_line(text):
    return ascii_text(re.sub(r"\s+", " ", text)).strip()


def parse_when(text):
    """RFC 822 (RSS) or ISO 8601 (Atom, dc:date) -> seconds since the epoch, or None."""
    text = text.strip()
    if not text:
        return None
    try:
        return email.utils.parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        t = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        return t.timestamp()
    except ValueError:
        return None


def summary_text(markup, link):
    """An item's description or content (HTML or plain) -> paragraphs, cut at SUMMARY_MAX."""
    if not markup.strip():
        return []
    paras = [re.sub(r"\[\d+\]", "", p).rstrip()     # (no [n] link numbers: no links here)
             for p in html_to_page(markup, link or "about:blank").paragraphs]
    out, n = [], 0
    for p in paras:
        if n + len(p) > SUMMARY_MAX:
            out.append(p[:max(0, SUMMARY_MAX - n)].rstrip() + " ...")
            break
        out.append(p)
        n += len(p)
    return out


def parse(data):
    """The bytes of a feed -> Feed. Raises WebError if it isn't one."""
    if re.search(rb"<!ENTITY", data[:20000], re.I):
        raise WebError("That feed declares XML entities: not read.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise WebError("That isn't a news feed (RSS or Atom).") from None
    kind = _local(root.tag)
    if kind == "feed":                               # Atom
        title = one_line(_text(root, "title"))
        items = [_atom_item(e) for e in root if _local(e.tag) == "entry"]
    elif kind in ("rss", "RDF"):                     # RSS 2.0 / RSS 1.0
        channel = _child(root, "channel")
        title = one_line(_text(channel, "title")) if channel is not None else ""
        parent = channel if kind == "rss" and channel is not None else root
        items = [_rss_item(e) for e in parent if _local(e.tag) == "item"]
    else:
        raise WebError("That isn't a news feed (RSS or Atom).")
    return Feed(title or "(untitled feed)", [i for i in items if i.title][:MAX_ITEMS])


def _rss_item(e):
    link = _text(e, "link") or _text(e, "guid")
    markup = _text(e, "encoded") or _text(e, "description")
    return Item(one_line(_text(e, "title")), link.strip(),
                parse_when(_text(e, "pubDate") or _text(e, "date")),
                summary_text(_text(e, "description") or markup, link))


def _atom_item(e):
    link = ""
    for c in e:
        if _local(c.tag) == "link" and c.get("rel", "alternate") == "alternate":
            link = c.get("href", "")
            break
    markup = _text(e, "summary") or _text(e, "content")
    return Item(one_line(_text(e, "title")), link,
                parse_when(_text(e, "published") or _text(e, "updated")),
                summary_text(markup, link))
