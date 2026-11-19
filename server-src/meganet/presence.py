"""Presence: each signed-on user's status (the Status menu), and Auto-Away.

    Available   seen by everyone in Who's Online (and the default at sign-on)
    Away        seen by everyone, marked Away; set by the user, or by Auto-Away after
                `away_minutes` (a system setting: Admin > System Settings...) with no activity.
                An automatic Away goes back to Available with the next activity.
    Offline     hidden from everyone but admins (screens.is_admin): Who's Online, User Search
                and instant messages treat them as not signed on; pages don't go to an offline
                admin

Activity is any message from the client except the connectivity check's PINGs and a click
on the status dot.

The menu bar shows the status as a dot just left of the connectivity icon (NOTIFY slot
SLOT_STATUS): green Available, yellow Away, dark grey Offline. Clicking it switches between
Available and Away (Offline goes back to Available); the Status menu has all three.
"""

import asyncio
import logging
import time

from .protocol import Icon, SLOT_STATUS

log = logging.getLogger("meganet")

AVAILABLE, AWAY, OFFLINE = "available", "away", "offline"
STATUSES = (AVAILABLE, AWAY, OFFLINE)
LABELS = {AVAILABLE: "Available", AWAY: "Away", OFFLINE: "Offline"}
ICONS = {AVAILABLE: Icon.AVAILABLE, AWAY: Icon.AWAY, OFFLINE: Icon.OFFLINE}
AWAY_KEY = "away_minutes"        # settings table
DEFAULT_AWAY_MINUTES = 10
AWAY_MINUTES_MAX = 999
CHECK_EVERY = 15                 # seconds between Auto-Away checks


class Presence:
    def __init__(self, server):
        self.server = server

    @property
    def db(self):
        return self.server.db

    def away_minutes(self):
        try:
            return max(0, int(self.db.setting(AWAY_KEY, DEFAULT_AWAY_MINUTES)))
        except ValueError:
            return DEFAULT_AWAY_MINUTES

    def set_away_minutes(self, minutes):
        with self.db.conn:
            self.db._set_setting(AWAY_KEY, int(minutes))

    def set(self, session, status, auto=False):
        """Change `session`'s status (auto: Auto-Away did it); everyone's views follow."""
        if status not in STATUSES:
            raise ValueError(status)
        session.auto_away = auto and status == AWAY
        if session.status == status:
            return
        session.status = status
        session.log("status %s%s" % (status, " (no activity)" if auto else ""))
        self.server.screens.status_changed(session)

    @staticmethod
    def show_icon(session):
        """The status dot on the menu bar (at sign-on and on every change)."""
        session.set_notify(SLOT_STATUS, ICONS[session.status],
                           "Status: %s" % LABELS[session.status])

    def click(self, session):
        """The status dot clicked: Available -> Away; Away or Offline -> Available."""
        self.set(session, AWAY if session.status == AVAILABLE else AVAILABLE)

    def activity(self, session):
        session.last_active = time.time()
        if session.auto_away and session.status == AWAY:
            self.set(session, AVAILABLE)

    def check(self, now=None):
        """Auto-Away: Available users with no activity for away_minutes become Away."""
        minutes = self.away_minutes()
        if not minutes:
            return
        now = time.time() if now is None else now
        for s in self.server.screens.online():
            if s.status == AVAILABLE and now - s.last_active >= minutes * 60:
                self.set(s, AWAY, auto=True)

    async def run(self):
        while True:
            await asyncio.sleep(CHECK_EVERY)
            try:
                self.check()
            except Exception:                    # (a bug here mustn't stop the checks)
                log.exception("auto-away check")

    @staticmethod
    def visible(viewer, target):
        """May `viewer` see that `target` is signed on? (Offline: only admins and themselves.)"""
        from .screens import is_admin
        return target is viewer or target.status != OFFLINE or is_admin(viewer)
