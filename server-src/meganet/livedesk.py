"""The live desktop: what's happening on the board, shown on every signed-on member's desktop.

    S.TICKER      a line of recent events (someone signed on, a new topic, a new file, a game
                  won...) scrolling along the bottom, over and over
    S.DESK_LINE   who's online, above it
    S.DESK_BADGE  numbers and dots on the desktop icons: new posts on Message Boards since you
                  last looked, people chatting, games waiting for a player, people online

Each session is sent only what changed for it (what it was last sent is kept on the session).
Events can be seen only by those who may see what they're about (a post in a forum you can't
read never shows). Older clients ignore all three messages.

The badges and the line also follow the board by themselves every REFRESH seconds (run()),
so the places that change them needn't all say so.
"""

import asyncio
import collections
import logging
import time

from .presence import Presence
from .protocol import (S, Writer, clean_text, TICKER_MAX, DESK_LINE_MAX, ONLINE_DOT, BADGE_MAX,
                       BADGE_DOT, DESK_SLOTS)

log = logging.getLogger("meganet")

TICKER_ITEMS = 8             # the newest events kept
SEPARATOR = "   *   "        # between them (the client puts one where the line starts again)
REFRESH = 10                 # seconds between checks of the badges and the online line
ONLINE_TITLE = "Online now:"

Item = collections.namedtuple("Item", "text can at")


class LiveDesk:
    def __init__(self, screens):
        self.screens = screens
        self.server = screens.server
        self.items = collections.deque(maxlen=TICKER_ITEMS)

    # ---- the ticker ----

    def say(self, text, can=None):
        """An event for the ticker: `can(session)` says who may see it (None: everyone)."""
        self.items.append(Item(clean_text(text)[:TICKER_MAX], can, time.time()))
        for s in self.screens.online():
            self.send_ticker(s)

    def tape(self, session):
        """The ticker for this session: the newest events it may see, oldest first, as many as
        fit in TICKER_MAX. "" (no ticker) when they've turned it off in My Account."""
        if not getattr(session, "show_ticker", True):
            return ""
        texts = []
        for item in self.items:
            try:
                if item.can is None or item.can(session):
                    texts.append(item.text)
            except Exception:                    # (a check about something now gone)
                continue
        while texts and len(SEPARATOR.join(texts)) > TICKER_MAX:
            texts.pop(0)
        return SEPARATOR.join(texts)

    def send_ticker(self, session):
        text = self.tape(session)
        if text != getattr(session, "live_tape", None):
            session.send(S.TICKER, Writer().str(text))
            session.live_tape = text

    # ---- who's online ----

    def online_line(self, viewer):
        """"Online now: .fred .xlar54" (ONLINE_DOT before each name): those the viewer may
        see (presence.py hides Offline ones), and "+N" for any that don't fit."""
        names = sorted((s.user for s in self.screens.visible(viewer)), key=str.lower)
        if not names:
            return ""
        line = ONLINE_TITLE
        for i, name in enumerate(names):
            part = " " + ONLINE_DOT + clean_text(name)
            left = len(names) - i - 1            # (room kept for " +N" while more follow)
            reserve = len(" +%d" % left) if left else 0
            if len(line) + len(part) + reserve > DESK_LINE_MAX:
                return line + " +%d" % (len(names) - i)
            line += part
        return line

    def send_line(self, session):
        text = self.online_line(session)
        if text != getattr(session, "live_line", None):
            b = text.encode("latin-1")            # (raw: Writer.str would clean the dots away)
            session.send(S.DESK_LINE, Writer().u8(len(b)).bytes(b))
            session.live_line = text

    # ---- badges on the desktop icons ----

    def badges(self, session):
        """Icon picture name -> badge text ("" none, BADGE_DOT a dot)."""
        out = {}
        chatting = sum(len(r.windows) for r in self.screens.chat.rooms.values())
        out["chat"] = BADGE_DOT if chatting else ""
        out["boards"] = count_text(self.new_posts(session))
        out["games"] = count_text(self.games_waiting(session))
        out["who"] = count_text(len(self.screens.visible(session)))
        return out

    def new_posts(self, session):
        """Posts by others since the session's last look at Message Boards (or its last
        sign-on before this one), in forums it may read."""
        since = max(getattr(session, "boards_seen", 0) or 0, session.previous_login or 0)
        if not since:                            # (the first sign-on: nothing is "new")
            return 0
        boards = self.screens.boards
        n = 0
        for forum_id, count in self.server.db.posts_since(since, session.user_id):
            forum = self.server.db.forum(forum_id)
            if forum is not None and boards.can_read(session, forum):
                n += count
        return n

    def games_waiting(self, session):
        """People waiting for someone to play with, in games this session may play."""
        lobby = self.server.games
        n = 0
        for cls in lobby.classes:
            if not lobby.may_play(session, cls):
                continue
            if cls in lobby.challenges:
                n += sum(1 for s in lobby.challenges[cls].seats if s is not session)
            else:
                n += sum(1 for s in lobby.queues[cls] if s is not session)
        return n

    def send_badges(self, session):
        icons = getattr(session, "desk", None) or []
        have = getattr(session, "live_badges", None)
        if have is None:
            have = session.live_badges = {}
        want = self.badges(session)
        for slot in range(DESK_SLOTS):
            icon = icons[slot] if slot < len(icons) else None
            text = want.get(icon[0], "") if icon is not None else ""
            if have.get(slot) != text:           # (None at first: every slot is sent once)
                session.send(S.DESK_BADGE, Writer().u8(slot).str(text))
                have[slot] = text

    # ---- keeping up ----

    def update(self, session):
        """Everything for one session, if it changed."""
        if session.user is None or session.closed:
            return
        self.send_badges(session)
        self.send_line(session)
        self.send_ticker(session)

    def update_all(self):
        for s in self.screens.online():
            self.update(s)

    def signed_on(self, session, new_member=False):
        if new_member:
            self.say("Welcome to our newest member, %s!" % session.user)
        else:
            self.say("%s signed on" % session.user,
                     can=lambda viewer, who=session: Presence.visible(viewer, who))
        self.update_all()

    def boards_seen(self, session):
        session.boards_seen = time.time()
        self.update(session)

    async def run(self):
        while True:
            await asyncio.sleep(REFRESH)
            try:
                self.update_all()
            except Exception:                    # (a bug here mustn't stop the updates)
                log.exception("live desktop")


BADGE_TOP = 9                # badges show 1-9, then "10+"


def count_text(n):
    """A badge's number: "" for none, 1-9, then "10+"."""
    if n <= 0:
        return ""
    return str(n) if n <= BADGE_TOP else ("%d+" % (BADGE_TOP + 1))[:BADGE_MAX]
