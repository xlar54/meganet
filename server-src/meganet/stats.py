"""MegaNet > System Stats: how much MegaNet is being used, for everyone signed on.

A window (a dynamic id, one a session: a second pick brings the report up to date) with a
report of text lines and Refresh / OK. Counts for today (since midnight, the server's time),
the last 7 days and the last 30:

    members (new ones), people on now
    sign-ons and how many people; the most active members (their actions in the log), and
    who signed on most
    message-board posts and new topics, and the busiest posters; private messages; news;
    polls open and votes
    the File Library, SID Music and the Art Gallery: how much is there, downloads / plays /
    views, what was added, and the most downloaded files, played tunes and viewed pictures
    games finished and who won most; credits in members' hands

Sign-ons come from the server log, which keeps System Settings' "Keep log" days: a period
longer than that is cut short (the report says so).
"""

import time

from .protocol import GFlag, WFlag
from .ui import TextView, Window, add_buttons, closer

W, H = 464, 150
COLS = (W - 16 - 14) // 8          # characters a line (the view's scroll bar takes some)
DAY = 86400
TOP = 5
# "Most active": a member's lines in the server log (what they did, area by area), not
# counting connecting, signing on, the server's own lines or the automatic karma changes
NOT_ACTIVITY = ("conn", "login", "server", "karma")


def day_start(now):
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def num(n):
    return "{:,}".format(n or 0)


def names_list(title, rows):
    """'title: alice 12, bob 7, ...' wrapped to the view's width (indented after the first)."""
    if not rows:
        return ["%s: nobody yet" % title]
    lines, line = [], title + ":"
    for name, n in rows:
        part = " %s %s," % (name, num(n))
        if len(line) + len(part) > COLS:
            lines.append(line)
            line = "   "
        line += part
    lines.append(line.rstrip(","))
    return lines


def report(server, now=None):
    """The report's lines."""
    now = time.time() if now is None else now
    db = server.db
    q = db.conn.execute
    today, week, month = day_start(now), now - 7 * DAY, now - 30 * DAY

    def count(sql, *args):
        return q(sql, args).fetchone()[0] or 0

    def three(sql):
        """A count for today, 7 days and 30 days: `sql` has one ? for the start."""
        return [count(sql, t) for t in (today, week, month)]

    def row(label, values):
        return "%-14s%9s%10s%10s" % (label, *[num(v) for v in values])

    lines = ["MegaNet, %s" % time.strftime("%a %d %b %Y %H:%M", time.localtime(now)), ""]
    members = count("SELECT COUNT(*) FROM users")
    online = sum(1 for s in server.sessions if s.user)
    lines.append("Members %s, on now %s" % (num(members), num(online)))
    lines.append("")
    lines.append("%-14s%9s%10s%10s" % ("", "Today", "7 days", "30 days"))
    lines.append(row("New members", three("SELECT COUNT(*) FROM users WHERE created >= ?")))
    signon = "FROM log WHERE area = 'login' AND text LIKE 'signed on as %' AND at >= ?"
    lines.append(row("Sign-ons", three("SELECT COUNT(*) " + signon)))
    lines.append(row("  people", three("SELECT COUNT(DISTINCT user_id) " + signon)))
    lines.append(row("Board posts", three("SELECT COUNT(*) FROM posts WHERE posted >= ?")))
    lines.append(row("  new topics", three("SELECT COUNT(*) FROM topics WHERE created >= ?")))
    lines.append(row("Private msgs", three(
        "SELECT COUNT(*) FROM private_messages WHERE sent >= ?")))
    lines.append(row("News", three("SELECT COUNT(*) FROM news WHERE posted >= ?")))
    lines.append(row("Poll votes", three("SELECT COUNT(*) FROM poll_votes WHERE at >= ?")))
    lines.append(row("Games played", three(
        "SELECT COUNT(*) FROM credit_log WHERE reason = 'game played' AND at >= ?")))
    lines.append(row("Poker hands", three(
        "SELECT COUNT(*) FROM credit_log WHERE reason = 'poker hand' AND at >= ?")))
    lines.append(row("Files added", three(
        "SELECT COUNT(*) FROM library_files WHERE added >= ?")))
    lines.append(row("Tunes added", three("SELECT COUNT(*) FROM sid_files WHERE added >= ?")))
    lines.append(row("Pictures added", three(
        "SELECT COUNT(*) FROM gallery_pictures WHERE added >= ?")))

    lines.append("")
    lines += names_list("Most active, 7 days", q(      # (what they did: the log's lines,
        "SELECT user, COUNT(*) AS n FROM log WHERE at >= ? AND user_id IS NOT NULL "
        "AND area NOT IN (%s) GROUP BY user_id ORDER BY n DESC, user LIMIT %d"
        % (",".join("'%s'" % a for a in NOT_ACTIVITY), TOP), (week,)).fetchall())
    lines += names_list("Most sign-ons, 7 days", q(
        "SELECT user, COUNT(*) AS n " + signon + " AND user_id IS NOT NULL GROUP BY user_id "
        "ORDER BY n DESC, user LIMIT %d" % TOP, (week,)).fetchall())
    lines += names_list("Most posts, 30 days", q(
        "SELECT u.name, COUNT(*) AS n FROM posts p JOIN users u ON u.id = p.author "
        "WHERE p.posted >= ? GROUP BY p.author ORDER BY n DESC, u.name LIMIT %d" % TOP,
        (month,)).fetchall())
    lines += names_list("Most games won, 30 days", q(
        "SELECT u.name, COUNT(*) AS n FROM credit_log c JOIN users u ON u.id = c.user_id "
        "WHERE c.reason = 'game won' AND c.at >= ? GROUP BY c.user_id "
        "ORDER BY n DESC, u.name LIMIT %d" % TOP, (month,)).fetchall())

    lines.append("")
    open_polls = count("SELECT COUNT(*) FROM polls WHERE ends IS NULL OR ends > ?", now)
    lines.append("Boards: %s topics, %s posts; polls open: %s" % (
        num(count("SELECT COUNT(*) FROM topics")), num(count("SELECT COUNT(*) FROM posts")),
        num(open_polls)))
    lines.append("Files: %s in %s libraries, %s downloads" % (
        num(count("SELECT COUNT(*) FROM library_files WHERE approved")),
        num(count("SELECT COUNT(*) FROM libraries")),
        num(count("SELECT SUM(downloads) FROM library_files"))))
    lines.append("SID tunes: %s in %s libraries, %s plays" % (
        num(count("SELECT COUNT(*) FROM sid_files WHERE approved")),
        num(count("SELECT COUNT(*) FROM sid_libraries")),
        num(count("SELECT SUM(downloads) FROM sid_files"))))
    lines.append("Pictures: %s in %s galleries, %s views" % (
        num(count("SELECT COUNT(*) FROM gallery_pictures")),
        num(count("SELECT COUNT(*) FROM galleries")),
        num(count("SELECT SUM(views) FROM gallery_pictures"))))
    lines += names_list("Most downloaded files", q(
        "SELECT name, downloads FROM library_files WHERE approved AND downloads > 0 "
        "ORDER BY downloads DESC, name LIMIT 3").fetchall())
    lines += names_list("Most played tunes", q(
        "SELECT name, downloads FROM sid_files WHERE approved AND downloads > 0 "
        "ORDER BY downloads DESC, name LIMIT 3").fetchall())
    lines += names_list("Most viewed pictures", q(
        "SELECT title, views FROM gallery_pictures WHERE views > 0 "
        "ORDER BY views DESC, title LIMIT 3").fetchall())
    balances, on_tables, _owed = db.credits_total()
    lines.append("Credits in members' hands: %s" % num(balances + on_tables))

    kept = server.serverlog.days()
    oldest = count("SELECT MIN(at) FROM log")
    if kept < 30 or (oldest and oldest > month):
        lines.append("")
        lines.append("(Sign-ons go back %s days: the log's start.)" % (
            min(kept, max(0, int((now - oldest) / DAY))) if oldest else 0))
    return [line[:COLS] for line in lines]


class StatsWindow:
    """One session's System Stats window."""

    def __init__(self, server, session):
        self.server = server
        self.session = session
        self.win = None

    def show(self):
        old = getattr(self.session, "stats_win", None)
        if old is not None and old.win is not None and old.win.shown:
            return old.refresh(None)
        self.session.stats_win = self
        win = Window.centred("System Stats", W, H, flags=WFlag.CLOSE | WFlag.MOVABLE)
        self.view = win.add(TextView(8, 4, W - 16, H - 28, report(self.server)))
        add_buttons(win, [("Refresh", self.refresh, 0), ("OK", closer, GFlag.DEFAULT)])
        self.win = win
        win.show(self.session)
        self.session.log("system stats")
        return None

    def refresh(self, button):
        self.view.set_lines(report(self.server), top=True)
        return None
