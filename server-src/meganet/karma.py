"""Karma Points: a 0-100 score per user (users.karma) that says how well they behave.

- A new account starts at NEW_KARMA (Low); the first account, the Sysop, at 100; accounts from
  before karma existed at 50.
- It grows slowly by itself while the user does fine (earn()): a message-board post, chatting
  (every CHAT_LINES lines), signing on on another day. Each reason pays at most a few points
  a day, nothing is paid within CLEAN_DAYS of any loss, and these gains stop at AUTO_CEILING
  (Good). Above that only moderators and admins raise it.
- It falls with incidents: a moderator's kick, mute or ban in chat, a moderator's "Karma -",
  and clients that send events the server never offered (forged clicks: suspicious()).
- Moderators (chat.moderate) give KARMA_STEP up or down from a chat room; admins (admin.users)
  see it in the User Editor, set it, read its history, and list the lowest.
- When someone falls to ALERT_AT or below, the admins get a message (Admin > Messages from
  users) so they can act on it: talk to them, or move them to a role with less access.
Every change is logged in karma_log with its reason and who made it.
"""

import logging
import time

from . import db as dbmod

log = logging.getLogger("meganet")

NEW_KARMA = 20
AUTO_CEILING = 70
KARMA_STEP = 5
ALERT_AT = 10
CLEAN_DAYS = 7
CHAT_LINES = 25                  # chat lines for one point
SUSPICIOUS_LIMIT = 5             # forged events in one session before it costs karma

# reason -> (points, most a day) for the automatic gains
GAINS = {"board post": (1, 2), "chat": (1, 2), "signed on": (1, 1)}
# reason -> points lost
LOSSES = {"kicked from chat": 3, "banned from a chat room": 5, "muted in chat": 1,
          "suspicious client activity": 5}

LEVELS = [(10, "Very low"), (30, "Low"), (60, "OK"), (85, "Good"), (101, "Excellent")]


def level(k):
    return next(name for top, name in LEVELS if k < top)


def describe(k):
    return "%d (%s)" % (k, level(k))


def day_start(now=None):
    t = time.localtime(now)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


def change(server, user_id, delta, reason, by=None, ceiling=dbmod.KARMA_MAX):
    """Change a user's karma (by: the session that did it, or None for the system). Admins are
    told when it falls to ALERT_AT or below; open User Editors follow. Returns (old, new)."""
    db = server.db
    got = db.change_karma(user_id, delta, reason, by.user_id if by else None, ceiling)
    if got is None or got[0] == got[1]:
        return got
    old, new = got
    user = db.user(user_id=user_id)
    who = ("by %s" % by.user) if by else "automatically"
    log.info("karma: %s %+d -> %d (%s, %s)" % (user["name"], new - old, new, reason, who))
    if new <= ALERT_AT < old:
        db.add_admin_message(by.user_id if by else user_id, "Karma alert: %s" % user["name"], [
            "%s's Karma Points fell to %s." % (user["name"], describe(new)),
            "Last change: %s (%s)." % (reason, who),
            "", "See Admin > User Editor (History) and decide what to do."])
        server.screens.pages.messages_changed()
    server.screens.admin.changed()
    return got


def earn(server, user_id, reason):
    """An automatic gain for `reason` (GAINS), if today's allowance isn't used up and nothing
    went wrong lately."""
    points, per_day = GAINS[reason]
    db = server.db
    now = time.time()
    if db.karma_events_since(user_id, day_start(now), reason) >= per_day:
        return None
    if db.karma_events_since(user_id, now - CLEAN_DAYS * 86400, losses=True):
        return None
    return change(server, user_id, points, reason, ceiling=AUTO_CEILING)


def lose(server, user_id, reason, by=None):
    return change(server, user_id, -LOSSES[reason], reason, by)


def suspicious(session, what):
    """The client sent something the server never offered it. A few are races (a window closed
    as it was clicked); SUSPICIOUS_LIMIT in one session costs karma, once."""
    session.log("suspicious: %s" % what)
    if session.user_id is None:
        return
    session.suspicious += 1
    if session.suspicious == SUSPICIOUS_LIMIT:
        lose(session.server, session.user_id, "suspicious client activity")
