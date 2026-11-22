"""The MegaNet database: one SQLite file (server-src/data/meganet.db by default).

The tables are created on first run. users (with the My Account profile: first_name,
last_name, email, location, birthdate, about, last_login), roles, role_permissions, settings, admin_messages (Help > Page
Admin with no admin signed on), private_messages (Areas > Private Messages) and the message
boards (forums, forum_access, topics, posts: boards.py) and the file libraries (libraries,
library_access, library_files: filelib.py) are in use. (Old databases may still hold the
unused stub tables boards, messages and files.)
An older database (users without role_id or the profile columns) is migrated when it is opened
(USER_COLUMNS, ALTER TABLE).

Roles: each user has one role (users.role_id); a role holds a set of permission keys
(role_permissions, see permissions.py). The first account ever created gets the Sysop role.
The database never lets the last user who can edit roles (admin.roles) lose that right.

Settings (key/value): default_role, first_user_role, and motd (the message of the day, a JSON
list of lines; see motd() / set_motd()).

Passwords are stored as "pbkdf2_sha256$iterations$salt$hash" (hex), never in clear.
"""

import datetime
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import time

from . import permissions as perms
from .protocol import clean_text

PBKDF2_ITERATIONS = 200_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash  TEXT NOT NULL,
    created  INTEGER NOT NULL,
    role_id  INTEGER REFERENCES roles(id),
    first_name TEXT NOT NULL DEFAULT '',
    last_name  TEXT NOT NULL DEFAULT '',
    email      TEXT NOT NULL DEFAULT '',
    location   TEXT NOT NULL DEFAULT '',
    birthdate  TEXT NOT NULL DEFAULT '',
    about      TEXT NOT NULL DEFAULT '',
    last_login INTEGER,
    karma      INTEGER NOT NULL DEFAULT 20,
    tos_agreed INTEGER,                 -- when they agreed to the Terms of Service (sign-up)
    credits    INTEGER NOT NULL DEFAULT 0   -- the bank balance (bank.py; credit_log says why)
);
CREATE TABLE IF NOT EXISTS credit_log (         -- the bank's ledger: every change to a balance
    id       INTEGER PRIMARY KEY,
    user_id  INTEGER NOT NULL REFERENCES users(id),
    delta    INTEGER NOT NULL,                  -- (0: a note, such as loan interest)
    balance  INTEGER NOT NULL,                  -- the balance after it
    reason   TEXT NOT NULL,                     -- bank.EARN's reasons, "gift", "loan", ...
    memo     TEXT NOT NULL DEFAULT '',
    other_id INTEGER,                           -- the other side: a gift's giver or taker,
                                                -- the opponent beaten
    by_user  INTEGER,                           -- an admin's change: who
    at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS credit_log_user ON credit_log (user_id, at);
CREATE TABLE IF NOT EXISTS loans (              -- the bank's loans (one open at a time)
    id        INTEGER PRIMARY KEY,
    user_id   INTEGER NOT NULL REFERENCES users(id),
    principal INTEGER NOT NULL,
    owed      INTEGER NOT NULL,
    rate      REAL NOT NULL,                    -- interest: percent a day
    taken     INTEGER NOT NULL,
    due       INTEGER NOT NULL,
    accrued   INTEGER NOT NULL,                 -- interest is charged up to this time
    closed    INTEGER                           -- paid off then (NULL: still open)
);
CREATE INDEX IF NOT EXISTS loans_user ON loans (user_id);
CREATE TABLE IF NOT EXISTS poker_chips (        -- credits on a poker table (games/poker.py):
    user_id  INTEGER PRIMARY KEY REFERENCES users(id),    -- given back at start-up if the
    chips    INTEGER NOT NULL,                  -- server stopped with them there
    since    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS roles (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    level INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id    INTEGER NOT NULL REFERENCES roles(id),
    permission TEXT NOT NULL,
    PRIMARY KEY (role_id, permission)
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS permissions_seen (
    permission TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS admin_messages (
    id        INTEGER PRIMARY KEY,
    from_user INTEGER NOT NULL REFERENCES users(id),
    sent      INTEGER NOT NULL,
    subject   TEXT NOT NULL DEFAULT '',
    text      TEXT NOT NULL,
    read      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS private_messages (
    id         INTEGER PRIMARY KEY,
    from_user  INTEGER NOT NULL REFERENCES users(id),
    to_user    INTEGER NOT NULL REFERENCES users(id),
    sent       INTEGER NOT NULL,
    subject    TEXT NOT NULL DEFAULT '',
    body       TEXT NOT NULL,
    read       INTEGER NOT NULL DEFAULT 0,
    del_sender INTEGER NOT NULL DEFAULT 0,
    del_recip  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS private_messages_to ON private_messages (to_user);
CREATE INDEX IF NOT EXISTS private_messages_from ON private_messages (from_user);
CREATE TABLE IF NOT EXISTS karma_log (
    id      INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    by_user INTEGER REFERENCES users(id),
    delta   INTEGER NOT NULL,
    karma   INTEGER NOT NULL,
    reason  TEXT NOT NULL,
    at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS karma_log_user ON karma_log (user_id);
CREATE TABLE IF NOT EXISTS chat_rooms (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    topic   TEXT NOT NULL DEFAULT '',
    private INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS forums (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    locked  INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS forum_access (
    forum_id INTEGER NOT NULL REFERENCES forums(id),
    role_id  INTEGER NOT NULL REFERENCES roles(id),
    can_read INTEGER NOT NULL,
    can_post INTEGER NOT NULL,
    PRIMARY KEY (forum_id, role_id)
);
CREATE TABLE IF NOT EXISTS topics (
    id        INTEGER PRIMARY KEY,
    forum_id  INTEGER NOT NULL REFERENCES forums(id),
    subject   TEXT NOT NULL,
    author    INTEGER REFERENCES users(id),
    created   INTEGER NOT NULL,
    last_post INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS topics_forum ON topics (forum_id);
CREATE TABLE IF NOT EXISTS posts (
    id       INTEGER PRIMARY KEY,
    topic_id INTEGER NOT NULL REFERENCES topics(id),
    author   INTEGER REFERENCES users(id),
    posted   INTEGER NOT NULL,
    body     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS posts_topic ON posts (topic_id);
CREATE TABLE IF NOT EXISTS polls (
    id       INTEGER PRIMARY KEY,
    question TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',   -- more background: lines joined with newlines
    author   INTEGER REFERENCES users(id),
    created  INTEGER NOT NULL,
    ends     INTEGER                -- NULL: never; else the time voting stops
);
CREATE TABLE IF NOT EXISTS poll_choices (
    id      INTEGER PRIMARY KEY,
    poll_id INTEGER NOT NULL REFERENCES polls(id),
    idx     INTEGER NOT NULL,
    text    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS poll_choices_poll ON poll_choices (poll_id);
CREATE TABLE IF NOT EXISTS poll_votes (
    poll_id   INTEGER NOT NULL REFERENCES polls(id),
    user_id   INTEGER NOT NULL REFERENCES users(id),
    choice_id INTEGER NOT NULL REFERENCES poll_choices(id),
    at        INTEGER NOT NULL,
    PRIMARY KEY (poll_id, user_id)  -- one vote each
);
CREATE TABLE IF NOT EXISTS news (
    id        INTEGER PRIMARY KEY,
    headline  TEXT NOT NULL,
    body      TEXT NOT NULL,            -- lines joined with newlines
    author    INTEGER REFERENCES users(id),
    posted    INTEGER NOT NULL,
    edited    INTEGER,                  -- NULL: never edited
    editor    INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS feeds (            -- Internet > News Feeds (internet/feeds.py)
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    url       TEXT NOT NULL,
    position  INTEGER NOT NULL           -- the list's order
);
CREATE TABLE IF NOT EXISTS news_reads (       -- who has read which bulletin, and when
    user_id   INTEGER NOT NULL REFERENCES users(id),
    news_id   INTEGER NOT NULL REFERENCES news(id),
    read_at   INTEGER NOT NULL,         -- the version read: the bulletin's COALESCE(edited,
                                        -- posted) then (an edit makes it unread again)
    PRIMARY KEY (user_id, news_id)
);
CREATE TABLE IF NOT EXISTS libraries (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    folder       TEXT NOT NULL UNIQUE,        -- under the server's filelibs/ folder
    description  TEXT NOT NULL DEFAULT '',    -- lines joined with newlines
    auto_approve INTEGER NOT NULL DEFAULT 1,  -- 0: uploads wait for a moderator
    created      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS library_access (
    library_id   INTEGER NOT NULL REFERENCES libraries(id),
    role_id      INTEGER NOT NULL REFERENCES roles(id),
    can_see      INTEGER NOT NULL,
    can_download INTEGER NOT NULL,
    can_upload   INTEGER NOT NULL,
    PRIMARY KEY (library_id, role_id)
);
CREATE TABLE IF NOT EXISTS library_files (
    id          INTEGER PRIMARY KEY,
    library_id  INTEGER NOT NULL REFERENCES libraries(id),
    name        TEXT NOT NULL,                -- what it's called (a CBM name: 16 characters)
    type        TEXT NOT NULL,                -- PRG SEQ USR D64 D81
    description TEXT NOT NULL DEFAULT '',     -- lines joined with newlines
    path        TEXT NOT NULL,                -- relative to the library's folder
    size        INTEGER NOT NULL,
    uploader    INTEGER REFERENCES users(id),
    added       INTEGER NOT NULL,
    approved    INTEGER NOT NULL DEFAULT 1,
    downloads   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS library_files_library ON library_files (library_id);
CREATE TABLE IF NOT EXISTS sid_libraries (       -- SID Music (sidlib.py): as libraries, under
    id           INTEGER PRIMARY KEY,           -- the server's sidlibs/ folder
    title        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    folder       TEXT NOT NULL UNIQUE,
    description  TEXT NOT NULL DEFAULT '',
    auto_approve INTEGER NOT NULL DEFAULT 1,
    created      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sid_access (
    library_id   INTEGER NOT NULL REFERENCES sid_libraries(id),
    role_id      INTEGER NOT NULL REFERENCES roles(id),
    can_see      INTEGER NOT NULL,
    can_download INTEGER NOT NULL,              -- (listen)
    can_upload   INTEGER NOT NULL,
    PRIMARY KEY (library_id, role_id)
);
CREATE TABLE IF NOT EXISTS sid_files (           -- each a checked PSID tune (sidcheck.py)
    id          INTEGER PRIMARY KEY,
    library_id  INTEGER NOT NULL REFERENCES sid_libraries(id),
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,                  -- SID
    description TEXT NOT NULL DEFAULT '',
    path        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    uploader    INTEGER REFERENCES users(id),
    added       INTEGER NOT NULL,
    approved    INTEGER NOT NULL DEFAULT 1,
    downloads   INTEGER NOT NULL DEFAULT 0      -- (plays)
);
CREATE INDEX IF NOT EXISTS sid_files_library ON sid_files (library_id);
CREATE TABLE IF NOT EXISTS galleries (           -- the Art Gallery (gallery/)
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description  TEXT NOT NULL DEFAULT '',       -- lines joined with newlines
    created      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS gallery_pictures (
    id          INTEGER PRIMARY KEY,
    gallery_id  INTEGER NOT NULL REFERENCES galleries(id),
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    path        TEXT NOT NULL,                   -- the IFF, relative to the galleries folder
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    colours     INTEGER NOT NULL,                -- colours used
    artist      INTEGER REFERENCES users(id),
    added       INTEGER NOT NULL,
    views       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS gallery_pictures_gallery ON gallery_pictures (gallery_id);
CREATE TABLE IF NOT EXISTS log (                -- the server log (serverlog.py)
    id       INTEGER PRIMARY KEY,
    at       INTEGER NOT NULL,                  -- Unix time
    level    INTEGER NOT NULL,                  -- 0 info, 1 warning, 2 error
    area     TEXT NOT NULL,                     -- serverlog.AREAS
    conn     INTEGER,                           -- the id of its connection's first row
    session  INTEGER,                           -- the session number (restarts at 1)
    user_id  INTEGER,                           -- (no REFERENCES: rows outlive accounts)
    user     TEXT,                              -- the screen name then
    text     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS log_at ON log (at);
CREATE INDEX IF NOT EXISTS log_conn ON log (conn);
"""

NAME_RE = re.compile(r"[A-Za-z0-9 ]{3,10}")     # (lists show 10)
FORUM_NAME_MAX = 20
FIRST_FORUM = "General"          # the forum a new database starts with
LOBBY = "Lobby"                  # the chat room a new database starts with (never deleted)
ROOM_NAME_MAX = 20
KARMA_MIN, KARMA_MAX = 0, 100
FIRST_USER_KARMA = 100           # the very first account (the Sysop)

# The profile fields of My Account (account.py). Text boxes hold 63 characters; About Me is
# up to ABOUT_LINES lines ("\n"-separated; lines saved before it was a text area were up to 63
# characters, and are kept as they are).
PROFILE_MAX = 63
ABOUT_LINES = 8
# Columns added to users after the first release: (name, SQL type and default)
# a kind of library: its (libraries, access, files) tables
LIBRARY_TABLES = {"files": ("libraries", "library_access", "library_files"),
                  "sid": ("sid_libraries", "sid_access", "sid_files")}

USER_COLUMNS = [("role_id", "INTEGER REFERENCES roles(id)"),
                ("email", "TEXT NOT NULL DEFAULT ''"),
                ("location", "TEXT NOT NULL DEFAULT ''"),
                ("birthdate", "TEXT NOT NULL DEFAULT ''"),
                ("about", "TEXT NOT NULL DEFAULT ''"),
                ("last_login", "INTEGER"),
                ("first_name", "TEXT NOT NULL DEFAULT ''"),
                ("last_name", "TEXT NOT NULL DEFAULT ''"),
                # accounts from before karma points start at OK, not at a new user's Low
                ("karma", "INTEGER NOT NULL DEFAULT 50"),
                ("tos_agreed", "INTEGER"),      # when they agreed to the Terms of Service
                ("credits", "INTEGER NOT NULL DEFAULT 0"),  # (seeded once: credits_seeded)
                # My Account's "Ring when I'm Away" (session.ring): on unless they untick it
                ("ring_away", "INTEGER NOT NULL DEFAULT 1")]
# The bank (bank.py): its settings are one JSON setting; a new account's opening balance is
# its "start" (DEFAULT_START_CREDITS until an admin sets one).
BANK_KEY = "bank"
DEFAULT_START_CREDITS = 500
CREDITS_MAX = 9_999_999          # a balance (and anything typed) stays below this
# First and last names: required (sign-up and My Account), at most REAL_NAME_MAX characters
REAL_NAME_MAX = 20
REAL_NAME_RE = re.compile(r"[A-Za-z][A-Za-z .'-]*")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s.][^@\s]*")
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def check_email(email):
    """None if `email` is empty or looks like an address (something@host.domain)."""
    if email and not EMAIL_RE.fullmatch(email):
        return "That email address doesn't look right."
    return None


def check_birthdate(text, today=None):
    """None if `text` is empty or a real date (YYYY-MM-DD) that isn't in the future."""
    if not text:
        return None
    m = DATE_RE.fullmatch(text)
    if not m:
        return "Birthdate: please use YYYY-MM-DD."
    try:
        day = datetime.date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return "That birthdate isn't a real date."
    if day > (today or datetime.date.today()):
        return "A birthdate can't be in the future."
    if day.year < 1900:
        return "A birthdate from 1900 on, please."
    return None

# Internet > News Feeds starts with these (checked working 2026-11-21); moderators change them.
DEFAULT_FEEDS = [
    ("BBC News", "https://feeds.bbci.co.uk/news/rss.xml"),
    ("NPR News", "https://feeds.npr.org/1001/rss.xml"),
    ("The Guardian: World", "https://www.theguardian.com/world/rss"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("Wired", "https://www.wired.com/feed/rss"),
    ("Engadget", "https://www.engadget.com/rss.xml"),
    ("Hacker News", "https://news.ycombinator.com/rss"),
    ("Slashdot", "https://rss.slashdot.org/Slashdot/slashdotMain"),
    ("BBC Science", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    ("NASA", "https://www.nasa.gov/news-release/feed/"),
    ("ScienceDaily", "https://www.sciencedaily.com/rss/all.xml"),
    ("Hackaday", "https://hackaday.com/blog/feed/"),
    ("Indie Retro News", "https://www.indieretronews.com/feeds/posts/default"),
    ("ESPN", "https://www.espn.com/espn/rss/news"),
]
FEED_NAME_MAX = 19               # (all of it shows in the feeds list)
FEED_URL_MAX = 255


# The Terms of Service new users agree to at the end of sign-up (signup.py), edited by the
# Sysop in Admin > Terms of Service... (admin.py, admin.tos). Kept in the settings table as
# JSON: TOS_PAGES pages of at most TOS_PAGE_LINES lines (the client's text areas hold 32), each
# line at most TOS_COLS characters (the reader's width, so a line typed is a line read). The
# reader shows the pages one after another, a blank line between, and the client keeps
# TOS_VIEW_LINES lines in a view: the whole text must fit (tos_problem).
TOS_KEY = "tos"
TOS_PAGES = 4
TOS_PAGE_LINES = 32
TOS_COLS = 52
TOS_VIEW_LINES = 128
DEFAULT_TOS = [[
    "MEGANET TERMS OF SERVICE",
    "",
    "Welcome to MegaNet. By creating an account or using",
    "the service you agree to these Terms. If you do not",
    "agree, please do not use MegaNet.",
    "",
    "1. YOUR ACCOUNT",
    "You must give true information when you sign up and",
    "keep your password secret. You are responsible for",
    "everything done with your account. One account per",
    "person, please. Tell the Sysop at once if you think",
    "someone else has used your account.",
    "",
    "2. ACCEPTABLE USE",
    "Be courteous. You agree not to post or send",
    "anything that is unlawful, threatening, abusive,",
    "harassing, defamatory, obscene or hateful; that",
    "invades anyone's privacy; or that you have no right",
    "to share, such as pirated software or other",
    "people's copyrighted work.",
    "",
    "You also agree not to impersonate anyone, send spam",
    "or chain letters, upload viruses or harmful files,",
    "try to get into accounts or areas you are not",
    "allowed into, or disrupt the service or its members.",
], [
    "3. YOUR CONTENT",
    "You keep ownership of what you post: messages,",
    "files, pictures and the like. By posting it you",
    "give MegaNet permission to store it, show it and",
    "send it to other members as part of the service.",
    "Don't post anything you wouldn't want others to see.",
    "",
    "4. MODERATION",
    "The Sysop and moderators may edit, move or remove",
    "any content, and may warn, suspend or close any",
    "account that breaks these Terms, at their own",
    "discretion and without notice.",
    "",
    "5. PRIVACY",
    "We keep the information you give us, and records of",
    "your use (such as sign-on times), to run the",
    "service. Your profile is visible to other members.",
    "Private messages are between the members who send",
    "and receive them, but the Sysop may read them to",
    "look into a problem or when the law requires it.",
    "We do not sell your information.",
], [
    "6. FILES AND SOFTWARE",
    "Files in the libraries are shared by members. Use",
    "them at your own risk, and only as their authors",
    "and licences allow. Check what you download.",
    "",
    "7. NO WARRANTY",
    "MegaNet is provided \"as is\", without any warranty.",
    "It may be unavailable or slow, or lose data, at any",
    "time. Keep your own copies of anything important.",
    "",
    "8. LIMITATION OF LIABILITY",
    "As far as the law allows, the operators of MegaNet",
    "are not liable for any loss or damage arising from",
    "your use of the service, or from anything posted by",
    "other members.",
    "",
    "9. CHANGES",
    "These Terms may change. Changes will be announced",
    "in the News, and using MegaNet after a change means",
    "you accept the new Terms.",
    "",
    "10. CONTACT",
    "Questions? Use Help > Page Admin, or send a private",
    "message to the Sysop.",
    "",
    "Thank you, and enjoy MegaNet!",
], []]


def tidy_tos(pages):
    """Pages as stored: TOS_PAGES lists of at most TOS_PAGE_LINES clean lines, trailing
    spaces and trailing blank lines dropped, each line cut at TOS_COLS."""
    out = []
    for page in (list(pages) + [[]] * TOS_PAGES)[:TOS_PAGES]:
        lines = [clean_text(str(line).expandtabs(4).rstrip())[:TOS_COLS] for line in page]
        while lines and not lines[-1]:
            lines.pop()
        out.append(lines[:TOS_PAGE_LINES])
    return out


def tos_text(pages):
    """The lines the reader shows: the pages with text, a blank line between."""
    out = []
    for page in pages:
        if page:
            if out:
                out.append("")
            out.extend(page)
    return out


def tos_problem(pages):
    """None if the Terms fit the reader, else what's wrong."""
    lines = tos_text(tidy_tos(pages))
    if not lines:
        return "The Terms of Service can't be empty."
    if len(lines) > TOS_VIEW_LINES:
        return "That's %d lines; the reader holds %d." % (len(lines), TOS_VIEW_LINES)
    return None


# The message of the day: a list of lines (one paragraph each; the client wraps them), kept in
# the settings table as JSON. Every user sees it in the welcome window at sign-on.
MOTD_KEY = "motd"
MOTD_MAX_LINES = 64          # the client keeps 128 wrapped lines in a view
MOTD_LINE_MAX = 255          # protocol strings stop at 255 bytes
DEFAULT_MOTD = [
    "Welcome to MegaNet, the graphical BBS for the MEGA65!",
    "",
    "Use the menu bar at the top of the screen to find the chat rooms, games and message "
    "boards.",
    "",
    "Sysop: change this message with Admin > Message of the Day, or start the server with "
    "--motd FILE.",
]


def tidy_motd(lines):
    """Lines made safe for the client: ASCII, tabs expanded, trailing spaces and trailing blank
    lines dropped, at most MOTD_MAX_LINES lines of at most MOTD_LINE_MAX characters."""
    out = [clean_text(str(line).expandtabs(4).rstrip())[:MOTD_LINE_MAX] for line in lines]
    while out and not out[-1]:
        out.pop()
    return out[:MOTD_MAX_LINES]


def read_motd_file(path):
    """The lines of a text file (UTF-8; anything not ASCII becomes '?'), tidied."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    if len(lines) > MOTD_MAX_LINES:
        logging.getLogger("meganet").warning("%s: only the first %d lines are used",
                                             path, MOTD_MAX_LINES)
    return tidy_motd(lines)


def check_new_name(name):
    """Return None if `name` is a valid new screen name, else the reason it isn't."""
    if not NAME_RE.fullmatch(name):
        return "Screen names are 3-10 letters, digits or spaces."
    if name != name.strip() or "  " in name:
        return "No leading, trailing or double spaces in screen names."
    return None


def check_real_name(text, which):
    """None if `text` is a good first or last name (`which` = "first" / "last"): required,
    letters, spaces, ' - and ., at most REAL_NAME_MAX characters."""
    if not text:
        return "Please type your %s name." % which
    if len(text) > REAL_NAME_MAX:
        return "Names hold at most %d characters." % REAL_NAME_MAX
    if not REAL_NAME_RE.fullmatch(text):
        return "Names hold letters, spaces, ' - and . only."
    return None


def real_names_problem(first, last):
    return check_real_name(first, "first") or check_real_name(last, "last")


def check_new_password(password):
    if len(password) < 4:
        return "Passwords need at least 4 characters."
    return None


def hash_password(password, salt=None, iterations=None):
    salt = salt or os.urandom(16)
    iterations = iterations or PBKDF2_ITERATIONS
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("latin-1"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, salt.hex(), digest.hex())


def verify_password(password, stored):
    try:
        algo, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    again = hash_password(password, bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(again.split("$")[3], digest)


class _Rollback(Exception):
    """Raised inside `with self.conn:` to undo the transaction."""


def _like_pattern(text):
    """A LIKE pattern (with ESCAPE '!') matching names that contain `text`."""
    return "%" + text.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


class Database:
    def __init__(self, path):
        """`path` is a file name, or ":memory:" for a throwaway database (tests)."""
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.migrate()
        self.seed_roles()
        self.sync_permissions()
        if self.setting(MOTD_KEY) is None:
            self._set_setting(MOTD_KEY, json.dumps(DEFAULT_MOTD))
        if self.setting("forums_seeded") is None:          # a first forum, once
            if not self.forums():
                self.conn.execute("INSERT INTO forums (name, created) VALUES (?, ?)",
                                  (FIRST_FORUM, int(time.time())))
            self._set_setting("forums_seeded", 1)
        if self.setting("news_reads_seeded") is None:       # read tracking began: what
            self.conn.execute(                              # each user saw by the old rule
                "INSERT OR IGNORE INTO news_reads (user_id, news_id, read_at) "   # (changed
                "SELECT u.id, n.id, COALESCE(n.edited, n.posted) FROM users u, news n "           # before
                "WHERE u.last_login IS NOT NULL "                                  # their last
                "AND COALESCE(n.edited, n.posted) <= u.last_login")               # sign-on)
            self._set_setting("news_reads_seeded", 1)
        if self.setting("feeds_seeded") is None:            # common news feeds, once
            if not self.feeds():
                for i, (name, url) in enumerate(DEFAULT_FEEDS):
                    self.conn.execute("INSERT INTO feeds (name, url, position) VALUES (?, ?, ?)",
                                      (name, url, i))
            self._set_setting("feeds_seeded", 1)
        if self.setting("rooms_seeded") is None:            # the Lobby, once
            if not self.chat_rooms():
                self.conn.execute("INSERT INTO chat_rooms (name, created) VALUES (?, ?)",
                                  (LOBBY, int(time.time())))
            self._set_setting("rooms_seeded", 1)
        if self.setting("credits_seeded") is None:          # the bank opened: everyone's
            now = int(time.time())                          # opening balance, once
            start = self.start_credits()
            for (uid,) in self.conn.execute("SELECT id FROM users").fetchall():
                self.conn.execute("UPDATE users SET credits = ? WHERE id = ?", (start, uid))
                self.conn.execute("INSERT INTO credit_log (user_id, delta, balance, reason, at) "
                                  "VALUES (?, ?, ?, 'opening balance', ?)",
                                  (uid, start, start, now))
            self._set_setting("credits_seeded", 1)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ---- start-up: migration, default roles, newly registered permissions ----

    def migrate(self):
        """Bring an older database up to date (the tables themselves exist by now)."""
        cols = [row["name"] for row in self.conn.execute("PRAGMA table_info(users)")]
        with self.conn:
            for name, decl in USER_COLUMNS:
                if name not in cols:
                    self.conn.execute("ALTER TABLE users ADD COLUMN %s %s" % (name, decl))

    def seed_roles(self):
        """Make the default roles on first run, and give every user without a role one: the
        oldest becomes Sysop if nobody can edit roles yet, the others get the default role."""
        with self.conn:
            if self.conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0] == 0:
                for name, level, keys in perms.DEFAULT_ROLES:
                    cur = self.conn.execute("INSERT INTO roles (name, level) VALUES (?, ?)",
                                            (name, level))
                    for key in (perms.keys() if keys is None else keys):
                        self.conn.execute("INSERT INTO role_permissions VALUES (?, ?)",
                                          (cur.lastrowid, key))
                    if name == perms.DEFAULT_ROLE:
                        self._set_setting("default_role", cur.lastrowid)
                    if name == perms.FIRST_USER_ROLE:
                        self._set_setting("first_user_role", cur.lastrowid)
            orphans = [row["id"] for row in self.conn.execute(
                "SELECT id FROM users WHERE role_id IS NULL OR role_id NOT IN "
                "(SELECT id FROM roles) ORDER BY id")]
            if orphans and self.admin_count() == 0:
                self.conn.execute("UPDATE users SET role_id = ? WHERE id = ?",
                                  (self.first_user_role_id(), orphans.pop(0)))
            for uid in orphans:
                self.conn.execute("UPDATE users SET role_id = ? WHERE id = ?",
                                  (self.default_role_id(), uid))

    def sync_permissions(self):
        """Grant the permission keys registered since the last start (permissions.register)
        to every role that holds admin.roles, and to the roles that hold the key's `like`.
        A key is granted only the first time it's seen. Server calls this again after the
        game plugins have registered theirs."""
        seen = {row[0] for row in self.conn.execute("SELECT permission FROM permissions_seen")}
        with self.conn:
            for p in perms.all_permissions():
                if p.key in seen:
                    continue
                grant_from = [perms.ADMIN_ROLES] + ([p.like] if p.like else [])
                for (role_id,) in self.conn.execute(
                        "SELECT DISTINCT role_id FROM role_permissions WHERE permission IN (%s)"
                        % ",".join("?" * len(grant_from)), grant_from).fetchall():
                    self.conn.execute("INSERT OR IGNORE INTO role_permissions VALUES (?, ?)",
                                      (role_id, p.key))
                self.conn.execute("INSERT INTO permissions_seen VALUES (?)", (p.key,))

    # ---- settings ----

    def setting(self, key, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def _set_setting(self, key, value):
        self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                          (key, str(value)))

    def set_setting(self, key, value):
        with self.conn:
            self._set_setting(key, value)

    # ---- the server log (serverlog.py) ----

    def add_log(self, at, level, area, conn, session, user_id, user, text):
        """Add a row; returns its id. Committed at once, unless a transaction is already open
        (then it goes in with that one)."""
        busy = self.conn.in_transaction
        cur = self.conn.execute(
            "INSERT INTO log (at, level, area, conn, session, user_id, user, text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (at, level, area, conn, session, user_id, user,
                                                 text))
        if not busy:
            self.conn.commit()
        return cur.lastrowid

    def set_log_conn(self, row_id, conn):
        busy = self.conn.in_transaction
        self.conn.execute("UPDATE log SET conn = ? WHERE id = ?", (conn, row_id))
        if not busy:
            self.conn.commit()

    def prune_log(self, before):
        """Delete the rows from before Unix time `before`; returns how many went."""
        with self.conn:
            return self.conn.execute("DELETE FROM log WHERE at < ?", (before,)).rowcount

    def last_log_id(self):
        return self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM log").fetchone()[0]

    def log_entries(self, area=None, min_level=0, user="", text="", conn=None, top=None,
                    limit=200, offset=0):
        """(rows newest first, how many match). With `conn`, that connection's rows only and
        the other filters are ignored; `user` and `text` match anywhere, in any case; `top`:
        no rows newer than this id."""
        where, args = [], []
        if top is not None:
            where.append("id <= ?")
            args.append(top)
        if conn is not None:
            where.append("conn = ?")
            args.append(conn)
        else:
            if area:
                where.append("area = ?")
                args.append(area)
            if min_level:
                where.append("level >= ?")
                args.append(min_level)
            if user:
                where.append("user LIKE ? ESCAPE '!'")
                args.append(_like_pattern(user))
            if text:
                where.append("text LIKE ? ESCAPE '!'")
                args.append(_like_pattern(text))
        cond = (" WHERE " + " AND ".join(where)) if where else ""
        total = self.conn.execute("SELECT COUNT(*) FROM log" + cond, args).fetchone()[0]
        rows = self.conn.execute("SELECT * FROM log" + cond + " ORDER BY id DESC LIMIT ? OFFSET ?",
                                 args + [limit, offset]).fetchall()
        return rows, total

    def motd(self):
        """The message of the day, a list of lines (the default if the setting is unreadable)."""
        try:
            lines = json.loads(self.setting(MOTD_KEY, "null"))
        except ValueError:
            lines = None
        if not isinstance(lines, list):
            return list(DEFAULT_MOTD)
        return tidy_motd(lines)

    def set_motd(self, lines):
        """Replace the message of the day; returns the lines as stored (tidied)."""
        lines = tidy_motd(lines)
        with self.conn:
            self._set_setting(MOTD_KEY, json.dumps(lines))
        return lines

    # ---- news feeds (Internet > News Feeds) ----

    def feeds(self):
        return self.conn.execute("SELECT * FROM feeds ORDER BY position, id").fetchall()

    def feed(self, feed_id):
        return self.conn.execute("SELECT * FROM feeds WHERE id = ?", (feed_id,)).fetchone()

    def add_feed(self, name, url):
        with self.conn:
            pos = self.conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM feeds"
                                    ).fetchone()[0]
            cur = self.conn.execute("INSERT INTO feeds (name, url, position) VALUES (?, ?, ?)",
                                    (name, url, pos))
        return cur.lastrowid

    def delete_feed(self, feed_id):
        with self.conn:
            self.conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))

    def tos(self):
        """The Terms of Service: TOS_PAGES lists of lines (the default if none is stored)."""
        try:
            pages = json.loads(self.setting(TOS_KEY, "null"))
        except ValueError:
            pages = None
        if not isinstance(pages, list) or not all(isinstance(p, list) for p in pages):
            pages = DEFAULT_TOS
        return tidy_tos(pages)

    def set_tos(self, pages):
        """Replace the Terms of Service; returns the pages as stored. (Check tos_problem.)"""
        pages = tidy_tos(pages)
        with self.conn:
            self._set_setting(TOS_KEY, json.dumps(pages))
        return pages

    def set_tos_agreed(self, user_id):
        with self.conn:
            self.conn.execute("UPDATE users SET tos_agreed = ? WHERE id = ?",
                              (int(time.time()), user_id))

    def default_role_id(self):
        """The role new accounts get (if that setting is lost: the lowest-level role)."""
        rid = self.setting("default_role")
        if rid is not None and self.role(int(rid)):
            return int(rid)
        row = self.conn.execute("SELECT id FROM roles ORDER BY level, name LIMIT 1").fetchone()
        return row["id"] if row else None

    def set_default_role(self, role_id):
        with self.conn:
            self._set_setting("default_role", role_id)

    def first_user_role_id(self):
        """The role the first account gets: Sysop, or if that role was deleted or lost
        admin.roles, the highest-level role that has admin.roles."""
        rid = self.setting("first_user_role")
        if rid is not None and perms.ADMIN_ROLES in self.role_permissions(int(rid)):
            return int(rid)
        row = self.conn.execute(
            "SELECT r.id FROM roles r JOIN role_permissions p ON p.role_id = r.id "
            "WHERE p.permission = ? ORDER BY r.level DESC LIMIT 1",
            (perms.ADMIN_ROLES,)).fetchone()
        return row["id"] if row else self.default_role_id()

    # ---- users ----

    def create_user(self, name, pw_hash):
        """Add a user with the default role, or Sysop if it's the very first account.
        Returns False if the name (any case) is taken."""
        try:
            with self.conn:
                first = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
                role = self.first_user_role_id() if first else self.default_role_id()
                now = int(time.time())
                start = self.start_credits()
                cur = self.conn.execute(
                    "INSERT INTO users (name, pw_hash, created, role_id, credits) "
                    "VALUES (?, ?, ?, ?, ?)", (name, pw_hash, now, role, start))
                self.conn.execute("INSERT INTO credit_log (user_id, delta, balance, reason, at) "
                                  "VALUES (?, ?, ?, 'opening balance', ?)",
                                  (cur.lastrowid, start, start, now))
                if first:
                    self.conn.execute("UPDATE users SET karma = ? WHERE name = ?",
                                      (FIRST_USER_KARMA, name))
            return True
        except sqlite3.IntegrityError:
            return False

    def user_count(self):
        return self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def password_hash(self, name):
        row = self.conn.execute("SELECT pw_hash FROM users WHERE name = ?", (name,)).fetchone()
        return row["pw_hash"] if row else None

    def canonical_name(self, name):
        """The name as the user first typed it (names are case-insensitive)."""
        row = self.conn.execute("SELECT name FROM users WHERE name = ?", (name,)).fetchone()
        return row["name"] if row else name

    _USER_SQL = ("SELECT u.id, u.name, u.created, u.role_id, r.name AS role, u.first_name, "
                 "u.last_name, u.email, u.location, u.birthdate, u.about, u.last_login, "
                 "u.karma, u.tos_agreed, u.credits, u.ring_away FROM users u "
                 "LEFT JOIN roles r ON r.id = u.role_id ")

    def user(self, name=None, user_id=None):
        """One user (id, name, created, role_id, role), by name (any case) or by id; or None."""
        if user_id is not None:
            return self.conn.execute(self._USER_SQL + "WHERE u.id = ?", (user_id,)).fetchone()
        return self.conn.execute(self._USER_SQL + "WHERE u.name = ?", (name,)).fetchone()

    def users(self, find=""):
        """Every user (id, name, role_id, role) whose name contains `find`, sorted by name."""
        return self.conn.execute(
            self._USER_SQL + "WHERE u.name LIKE ? ESCAPE '!' ORDER BY u.name COLLATE NOCASE",
            (_like_pattern(find),)).fetchall()

    def new_users(self):
        """Users still in the default role (the one new accounts get), oldest first."""
        return self.conn.execute(
            self._USER_SQL + "WHERE u.role_id = ? ORDER BY u.created, u.id",
            (self.default_role_id(),)).fetchall()

    def record_login(self, user_id):
        """A sign-on: store the time, and return the one before it (None the first time)."""
        row = self.conn.execute("SELECT last_login FROM users WHERE id = ?",
                                (user_id,)).fetchone()
        with self.conn:
            self.conn.execute("UPDATE users SET last_login = ? WHERE id = ?",
                              (int(time.time()), user_id))
        return row["last_login"] if row else None

    def set_profile(self, user_id, first_name, last_name, email, location, birthdate,
                    about_lines):
        """Save My Account's fields (checked by the caller; cut to fit here)."""
        about = [clean_text(line).rstrip()[:PROFILE_MAX] for line in about_lines][:ABOUT_LINES]
        while about and not about[-1]:
            about.pop()
        with self.conn:
            self.conn.execute(
                "UPDATE users SET first_name = ?, last_name = ?, email = ?, location = ?, "
                "birthdate = ?, about = ? WHERE id = ?",
                (clean_text(first_name).strip()[:REAL_NAME_MAX],
                 clean_text(last_name).strip()[:REAL_NAME_MAX], clean_text(email)[:PROFILE_MAX], clean_text(location)[:PROFILE_MAX],
                 clean_text(birthdate)[:10], "\n".join(about), user_id))

    def set_ring_away(self, user_id, on):
        with self.conn:
            self.conn.execute("UPDATE users SET ring_away = ? WHERE id = ?",
                              (1 if on else 0, user_id))

    def set_password(self, user_id, pw_hash):
        with self.conn:
            self.conn.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (pw_hash, user_id))

    def user_permissions(self, user_id):
        """The permission keys of the user's role."""
        row = self.conn.execute("SELECT role_id FROM users WHERE id = ?", (user_id,)).fetchone()
        return self.role_permissions(row["role_id"]) if row and row["role_id"] else set()

    def set_user_role(self, user_id, role_id):
        """Move a user to another role. Returns None, or why it can't be done."""
        user, role = self.user(user_id=user_id), self.role(role_id)
        if user is None or role is None:
            return "No such user or role."
        if user["role_id"] == role_id:
            return None
        if self.admin_count(move_user=(user_id, role_id)) == 0:
            return "%s is the last user who can edit roles." % user["name"]
        with self.conn:
            self.conn.execute("UPDATE users SET role_id = ? WHERE id = ?", (role_id, user_id))
        return None

    # ---- messages to the admins (Help > Page Admin when no admin is signed on) ----
    # The text is the message's lines joined with "\n".

    _ADMIN_MSG_SQL = ("SELECT m.id, m.from_user, COALESCE(u.name, '?') AS name, m.sent, "
                      "m.subject, m.text, m.read FROM admin_messages m "
                      "LEFT JOIN users u ON u.id = m.from_user ")

    def add_admin_message(self, from_user, subject, lines):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO admin_messages (from_user, sent, subject, text) VALUES (?, ?, ?, ?)",
                (from_user, int(time.time()), subject, "\n".join(lines)))
        return cur.lastrowid

    def admin_messages(self):
        """Every message to the admins, newest first."""
        return self.conn.execute(self._ADMIN_MSG_SQL + "ORDER BY m.sent DESC, m.id DESC").fetchall()

    def admin_message(self, msg_id):
        return self.conn.execute(self._ADMIN_MSG_SQL + "WHERE m.id = ?", (msg_id,)).fetchone()

    def mark_admin_message_read(self, msg_id, read=True):
        with self.conn:
            self.conn.execute("UPDATE admin_messages SET read = ? WHERE id = ?",
                              (1 if read else 0, msg_id))

    def delete_admin_message(self, msg_id):
        with self.conn:
            self.conn.execute("DELETE FROM admin_messages WHERE id = ?", (msg_id,))

    def admin_unread_count(self):
        return self.conn.execute("SELECT COUNT(*) FROM admin_messages WHERE read = 0").fetchone()[0]

    # ---- private messages (Areas > Private Messages) ----
    # The body is the message's lines joined with "\n". A message stays until both the sender
    # (del_sender: gone from their Sent folder) and the recipient (del_recip) have deleted it.

    _PM_SQL = ("SELECT m.id, m.from_user, m.to_user, COALESCE(f.name, '?') AS from_name, "
               "COALESCE(t.name, '?') AS to_name, m.sent, m.subject, m.body, m.read "
               "FROM private_messages m LEFT JOIN users f ON f.id = m.from_user "
               "LEFT JOIN users t ON t.id = m.to_user ")

    def send_private_message(self, from_user, to_user, subject, lines):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO private_messages (from_user, to_user, sent, subject, body) "
                "VALUES (?, ?, ?, ?, ?)",
                (from_user, to_user, int(time.time()), subject, "\n".join(lines)))
        return cur.lastrowid

    def inbox(self, user_id):
        """The messages to `user_id` they haven't deleted, newest first."""
        return self.conn.execute(self._PM_SQL + "WHERE m.to_user = ? AND m.del_recip = 0 "
                                 "ORDER BY m.sent DESC, m.id DESC", (user_id,)).fetchall()

    def sent_messages(self, user_id):
        """The messages from `user_id` they haven't deleted, newest first."""
        return self.conn.execute(self._PM_SQL + "WHERE m.from_user = ? AND m.del_sender = 0 "
                                 "ORDER BY m.sent DESC, m.id DESC", (user_id,)).fetchall()

    def private_message(self, msg_id):
        return self.conn.execute(self._PM_SQL + "WHERE m.id = ?", (msg_id,)).fetchone()

    def mark_private_read(self, msg_id, read=True):
        with self.conn:
            self.conn.execute("UPDATE private_messages SET read = ? WHERE id = ?",
                              (1 if read else 0, msg_id))

    def unread_private_count(self, user_id):
        return self.conn.execute("SELECT COUNT(*) FROM private_messages WHERE to_user = ? AND "
                                 "del_recip = 0 AND read = 0", (user_id,)).fetchone()[0]

    def delete_private_message(self, msg_id, user_id):
        """`user_id` deletes the message from their inbox or Sent folder (or both, if they sent
        it to themselves). The row goes once both sides have deleted it."""
        with self.conn:
            self.conn.execute("UPDATE private_messages SET del_recip = 1 "
                              "WHERE id = ? AND to_user = ?", (msg_id, user_id))
            self.conn.execute("UPDATE private_messages SET del_sender = 1 "
                              "WHERE id = ? AND from_user = ?", (msg_id, user_id))
            self.conn.execute("DELETE FROM private_messages WHERE id = ? AND del_recip = 1 "
                              "AND del_sender = 1", (msg_id,))

    # ---- roles ----

    def roles(self):
        """Every role (id, name, level, users), sorted by level then name."""
        return self.conn.execute(
            "SELECT r.id, r.name, r.level, "
            "(SELECT COUNT(*) FROM users u WHERE u.role_id = r.id) AS users "
            "FROM roles r ORDER BY r.level, r.name COLLATE NOCASE").fetchall()

    def role(self, role_id):
        return self.conn.execute("SELECT id, name, level FROM roles WHERE id = ?",
                                 (role_id,)).fetchone()

    def role_by_name(self, name):
        return self.conn.execute("SELECT id, name, level FROM roles WHERE name = ?",
                                 (name,)).fetchone()

    def role_permissions(self, role_id):
        return {row[0] for row in self.conn.execute(
            "SELECT permission FROM role_permissions WHERE role_id = ?", (role_id,))}

    def create_role(self, name, level=0, keys=()):
        """Add a role. Returns its id, or None if the name (any case) is taken."""
        try:
            with self.conn:
                cur = self.conn.execute("INSERT INTO roles (name, level) VALUES (?, ?)",
                                        (name, level))
                for key in set(keys):
                    self.conn.execute("INSERT INTO role_permissions VALUES (?, ?)",
                                      (cur.lastrowid, key))
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def rename_role(self, role_id, name):
        """Returns None, or why not."""
        try:
            with self.conn:
                self.conn.execute("UPDATE roles SET name = ? WHERE id = ?", (name, role_id))
            return None
        except sqlite3.IntegrityError:
            return "There is already a role called %s." % name

    def set_role_level(self, role_id, level):
        with self.conn:
            self.conn.execute("UPDATE roles SET level = ? WHERE id = ?", (level, role_id))

    def set_role_permissions(self, role_id, keys):
        """Replace a role's permissions. Returns None, or why not: it would leave no user
        who can edit roles."""
        keys = set(keys)
        if (perms.ADMIN_ROLES not in keys and self.admin_count() > 0
                and self.admin_count(role_perms=(role_id, keys)) == 0):
            return "Nobody else can edit roles, so this role keeps %s." % perms.ADMIN_ROLES
        with self.conn:
            self.conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
            for key in sorted(keys):
                self.conn.execute("INSERT INTO role_permissions VALUES (?, ?)", (role_id, key))
        return None

    def delete_role(self, role_id, move_to=None):
        """Delete a role. Its users move to role `move_to`; without one, a role that still
        has users isn't deleted. The default role can't be deleted. Returns None, or why not."""
        role = self.role(role_id)
        if role is None:
            return "No such role."
        if role_id == self.default_role_id():
            return "%s is the role for new users: make another one the default first." \
                % role["name"]
        n = self.conn.execute("SELECT COUNT(*) FROM users WHERE role_id = ?",
                              (role_id,)).fetchone()[0]
        if n and (move_to is None or move_to == role_id or self.role(move_to) is None):
            return "%s still has %d user%s." % (role["name"], n, "" if n == 1 else "s")
        if n and self.admin_count(move_role=(role_id, move_to)) == 0:
            return "That would leave nobody who can edit roles."
        with self.conn:
            self.conn.execute("UPDATE users SET role_id = ? WHERE role_id = ?", (move_to, role_id))
            self.conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
            self.conn.execute("DELETE FROM forum_access WHERE role_id = ?", (role_id,))
            self.conn.execute("DELETE FROM library_access WHERE role_id = ?", (role_id,))
            self.conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))
        return None

    def admin_count(self, role_perms=None, move_user=None, move_role=None):
        """How many users can edit roles (their role has admin.roles), or how many could after
        a change: role_perms=(role_id, new keys), move_user=(user_id, new role_id),
        move_role=(old role_id, new role_id)."""
        admin_roles = {row[0] for row in self.conn.execute(
            "SELECT role_id FROM role_permissions WHERE permission = ?", (perms.ADMIN_ROLES,))}
        if role_perms:
            rid, keys = role_perms
            if perms.ADMIN_ROLES in keys:
                admin_roles.add(rid)
            else:
                admin_roles.discard(rid)
        n = 0
        for row in self.conn.execute("SELECT id, role_id FROM users"):
            rid = row["role_id"]
            if move_user and row["id"] == move_user[0]:
                rid = move_user[1]
            if move_role and rid == move_role[0]:
                rid = move_role[1]
            n += rid in admin_roles
        return n


    # ---- message boards: forums > topics > posts (boards.py) ----
    # "New" is relative to a time the caller gives (the user's previous login).

    def forums(self, since=0):
        """Every forum (id, name, locked, created, topics, posts, new: posts after `since`),
        sorted by name."""
        return self.conn.execute(
            "SELECT f.id, f.name, f.locked, f.created, "
            "(SELECT COUNT(*) FROM topics t WHERE t.forum_id = f.id) AS topics, "
            "(SELECT COUNT(*) FROM posts p JOIN topics t ON t.id = p.topic_id "
            " WHERE t.forum_id = f.id) AS posts, "
            "(SELECT COUNT(*) FROM posts p JOIN topics t ON t.id = p.topic_id "
            " WHERE t.forum_id = f.id AND p.posted > ?) AS new "
            "FROM forums f ORDER BY f.name COLLATE NOCASE", (since or 0,)).fetchall()

    def forum(self, forum_id):
        return self.conn.execute("SELECT id, name, locked, created FROM forums WHERE id = ?",
                                 (forum_id,)).fetchone()

    def create_forum(self, name):
        """A new forum; its id, or None if the name (any case) is taken."""
        try:
            with self.conn:
                cur = self.conn.execute("INSERT INTO forums (name, created) VALUES (?, ?)",
                                        (name, int(time.time())))
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def rename_forum(self, forum_id, name):
        """Returns None, or why not."""
        try:
            with self.conn:
                self.conn.execute("UPDATE forums SET name = ? WHERE id = ?", (name, forum_id))
            return None
        except sqlite3.IntegrityError:
            return "There is already a forum called %s." % name

    def set_forum_locked(self, forum_id, locked):
        with self.conn:
            self.conn.execute("UPDATE forums SET locked = ? WHERE id = ?",
                              (1 if locked else 0, forum_id))

    def delete_forum(self, forum_id):
        """The forum, with its topics, posts and access rows."""
        with self.conn:
            self.conn.execute("DELETE FROM posts WHERE topic_id IN "
                              "(SELECT id FROM topics WHERE forum_id = ?)", (forum_id,))
            self.conn.execute("DELETE FROM topics WHERE forum_id = ?", (forum_id,))
            self.conn.execute("DELETE FROM forum_access WHERE forum_id = ?", (forum_id,))
            self.conn.execute("DELETE FROM forums WHERE id = ?", (forum_id,))

    def forum_access(self, forum_id):
        """{role_id: (can_read, can_post)} for the roles set for this forum. A role that isn't
        there may read and post (as far as its permissions allow message boards at all)."""
        return {row["role_id"]: (bool(row["can_read"]), bool(row["can_post"]))
                for row in self.conn.execute(
                    "SELECT role_id, can_read, can_post FROM forum_access WHERE forum_id = ?",
                    (forum_id,))}

    def set_forum_access(self, forum_id, access):
        """Replace the forum's rows: {role_id: (can_read, can_post)}; posting implies reading."""
        with self.conn:
            self.conn.execute("DELETE FROM forum_access WHERE forum_id = ?", (forum_id,))
            for role_id, (read, post) in access.items():
                self.conn.execute("INSERT INTO forum_access VALUES (?, ?, ?, ?)",
                                  (forum_id, role_id, 1 if read or post else 0,
                                   1 if post else 0))

    # ---- file libraries (filelib.py) ----

    # File libraries (filelib.py, kind "files") and SID libraries (sidlib.py, kind "sid"):
    # the same three tables each, LIBRARY_TABLES[kind].

    @staticmethod
    def _lib_tables(kind):
        try:
            return LIBRARY_TABLES[kind]
        except KeyError:
            raise ValueError("no library kind %r" % (kind,)) from None

    def _lib_sql(self, kind):
        libs, _, files = self._lib_tables(kind)
        return ("SELECT l.id, l.title, l.folder, l.description, l.auto_approve, l.created, "
                "(SELECT COUNT(*) FROM %s f WHERE f.library_id = l.id AND f.approved) AS files, "
                "(SELECT COUNT(*) FROM %s f WHERE f.library_id = l.id AND NOT f.approved) "
                "AS held FROM %s l " % (files, files, libs))

    def libraries(self, kind="files"):
        """Every library (id, title, folder, description, auto_approve, created, files: approved
        ones, held: waiting for a moderator), sorted by title."""
        return self.conn.execute(self._lib_sql(kind)
                                 + "ORDER BY l.title COLLATE NOCASE").fetchall()

    def library(self, library_id, kind="files"):
        return self.conn.execute(self._lib_sql(kind) + "WHERE l.id = ?",
                                 (library_id,)).fetchone()

    def create_library(self, title, folder, description="", auto_approve=True, kind="files"):
        """A new library; its id, or None if the title (any case) or the folder is taken."""
        libs = self._lib_tables(kind)[0]
        try:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO %s (title, folder, description, auto_approve, created) "
                    "VALUES (?, ?, ?, ?, ?)" % libs,
                    (title, folder, description, 1 if auto_approve else 0, int(time.time())))
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def update_library(self, library_id, title, folder, description, auto_approve, kind="files"):
        """Returns None, or why not."""
        libs = self._lib_tables(kind)[0]
        try:
            with self.conn:
                self.conn.execute("UPDATE %s SET title = ?, folder = ?, description = ?, "
                                  "auto_approve = ? WHERE id = ?" % libs,
                                  (title, folder, description, 1 if auto_approve else 0,
                                   library_id))
            return None
        except sqlite3.IntegrityError:
            return "There is already a library called %s (or using its folder)." % title

    def delete_library(self, library_id, kind="files"):
        """The library's rows: its file entries and access rows (not the files themselves)."""
        libs, access, files = self._lib_tables(kind)
        with self.conn:
            self.conn.execute("DELETE FROM %s WHERE library_id = ?" % files, (library_id,))
            self.conn.execute("DELETE FROM %s WHERE library_id = ?" % access, (library_id,))
            self.conn.execute("DELETE FROM %s WHERE id = ?" % libs, (library_id,))

    def library_access(self, library_id, kind="files"):
        """{role_id: (see, download, upload)} for the roles set for this library. A role that
        isn't there may do all three (as far as its permissions allow)."""
        access = self._lib_tables(kind)[1]
        return {row["role_id"]: (bool(row["can_see"]), bool(row["can_download"]),
                                 bool(row["can_upload"]))
                for row in self.conn.execute(
                    "SELECT role_id, can_see, can_download, can_upload FROM %s "
                    "WHERE library_id = ?" % access, (library_id,))}

    def set_library_access(self, library_id, access, kind="files"):
        """Replace the library's rows: {role_id: (see, download, upload)}; downloading or
        uploading implies seeing it."""
        table = self._lib_tables(kind)[1]
        with self.conn:
            self.conn.execute("DELETE FROM %s WHERE library_id = ?" % table, (library_id,))
            for role_id, (see, down, up) in access.items():
                self.conn.execute("INSERT INTO %s VALUES (?, ?, ?, ?, ?)" % table,
                                  (library_id, role_id, 1 if see or down or up else 0,
                                   1 if down else 0, 1 if up else 0))

    def _file_sql(self, kind):
        return ("SELECT f.id, f.library_id, f.name, f.type, f.description, f.path, f.size, "
                "f.uploader, COALESCE(u.name, '') AS uploader_name, f.added, f.approved, "
                "f.downloads FROM %s f LEFT JOIN users u ON u.id = f.uploader "
                % self._lib_tables(kind)[2])

    def library_files(self, library_id, held=False, kind="files"):
        """A library's files, by name; `held`: those waiting for a moderator too."""
        return self.conn.execute(
            self._file_sql(kind) + "WHERE f.library_id = ? %s ORDER BY f.name COLLATE NOCASE, "
            "f.id" % ("" if held else "AND f.approved"), (library_id,)).fetchall()

    def library_file(self, file_id, kind="files"):
        return self.conn.execute(self._file_sql(kind) + "WHERE f.id = ?", (file_id,)).fetchone()

    def library_file_by_path(self, library_id, path, kind="files"):
        return self.conn.execute(self._file_sql(kind) + "WHERE f.library_id = ? AND f.path = ?",
                                 (library_id, path)).fetchone()

    def add_library_file(self, library_id, name, ftype, description, path, size,
                         uploader=None, approved=True, kind="files"):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO %s (library_id, name, type, description, path, size, "
                "uploader, added, approved) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                % self._lib_tables(kind)[2],
                (library_id, name, ftype, description, path, size, uploader, int(time.time()),
                 1 if approved else 0))
        return cur.lastrowid

    def update_library_file(self, file_id, name, ftype, description, path, size, kind="files"):
        with self.conn:
            self.conn.execute("UPDATE %s SET name = ?, type = ?, description = ?, "
                              "path = ?, size = ? WHERE id = ?" % self._lib_tables(kind)[2],
                              (name, ftype, description, path, size, file_id))

    def approve_library_file(self, file_id, kind="files"):
        with self.conn:
            self.conn.execute("UPDATE %s SET approved = 1 WHERE id = ?"
                              % self._lib_tables(kind)[2], (file_id,))

    def delete_library_file(self, file_id, kind="files"):
        with self.conn:
            self.conn.execute("DELETE FROM %s WHERE id = ?" % self._lib_tables(kind)[2],
                              (file_id,))

    def count_download(self, file_id, kind="files"):
        """(A SID library counts plays here.)"""
        with self.conn:
            self.conn.execute("UPDATE %s SET downloads = downloads + 1 WHERE id = ?"
                              % self._lib_tables(kind)[2], (file_id,))

    # ---- the Art Gallery (gallery/) ----

    _GALLERY_SQL = ("SELECT g.id, g.title, g.description, g.created, (SELECT COUNT(*) FROM "
                    "gallery_pictures p WHERE p.gallery_id = g.id) AS pictures FROM galleries g ")

    def galleries(self):
        """Every gallery (id, title, description, created, pictures), sorted by title."""
        return self.conn.execute(self._GALLERY_SQL + "ORDER BY g.title COLLATE NOCASE").fetchall()

    def gallery(self, gallery_id):
        return self.conn.execute(self._GALLERY_SQL + "WHERE g.id = ?", (gallery_id,)).fetchone()

    def create_gallery(self, title, description=""):
        """A new gallery's id, or None if the title (any case) is taken."""
        try:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO galleries (title, description, created) VALUES (?, ?, ?)",
                    (title, description, int(time.time())))
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def update_gallery(self, gallery_id, title, description):
        """None, or why not."""
        try:
            with self.conn:
                self.conn.execute("UPDATE galleries SET title = ?, description = ? WHERE id = ?",
                                  (title, description, gallery_id))
            return None
        except sqlite3.IntegrityError:
            return "There is already a gallery called %s." % title

    def delete_gallery(self, gallery_id):
        """The gallery and its pictures' rows; the paths of their files (for the caller)."""
        paths = [r["path"] for r in self.conn.execute(
            "SELECT path FROM gallery_pictures WHERE gallery_id = ?", (gallery_id,))]
        with self.conn:
            self.conn.execute("DELETE FROM gallery_pictures WHERE gallery_id = ?", (gallery_id,))
            self.conn.execute("DELETE FROM galleries WHERE id = ?", (gallery_id,))
        return paths

    _PICTURE_SQL = ("SELECT p.id, p.gallery_id, p.title, p.description, p.path, p.width, "
                    "p.height, p.colours, p.artist, COALESCE(u.name, '') AS artist_name, "
                    "p.added, p.views FROM gallery_pictures p LEFT JOIN users u "
                    "ON u.id = p.artist ")

    def gallery_pictures(self, gallery_id):
        """A gallery's pictures, oldest first."""
        return self.conn.execute(self._PICTURE_SQL + "WHERE p.gallery_id = ? ORDER BY p.added, "
                                 "p.id", (gallery_id,)).fetchall()

    def gallery_picture(self, picture_id):
        return self.conn.execute(self._PICTURE_SQL + "WHERE p.id = ?", (picture_id,)).fetchone()

    def add_gallery_picture(self, gallery_id, title, description, width, height, colours,
                            artist=None):
        """A new picture's id; its path is set with set_gallery_picture_path once it's saved."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO gallery_pictures (gallery_id, title, description, path, width, "
                "height, colours, artist, added) VALUES (?, ?, ?, '', ?, ?, ?, ?, ?)",
                (gallery_id, title, description, width, height, colours, artist,
                 int(time.time())))
        return cur.lastrowid

    def set_gallery_picture_path(self, picture_id, path):
        with self.conn:
            self.conn.execute("UPDATE gallery_pictures SET path = ? WHERE id = ?",
                              (path, picture_id))

    def set_gallery_picture_size(self, picture_id, width, height, colours):
        with self.conn:
            self.conn.execute("UPDATE gallery_pictures SET width = ?, height = ?, colours = ? "
                              "WHERE id = ?", (width, height, colours, picture_id))

    def update_gallery_picture(self, picture_id, title, description):
        with self.conn:
            self.conn.execute("UPDATE gallery_pictures SET title = ?, description = ? "
                              "WHERE id = ?", (title, description, picture_id))

    def delete_gallery_picture(self, picture_id):
        with self.conn:
            self.conn.execute("DELETE FROM gallery_pictures WHERE id = ?", (picture_id,))

    def count_view(self, picture_id):
        with self.conn:
            self.conn.execute("UPDATE gallery_pictures SET views = views + 1 WHERE id = ?",
                              (picture_id,))

    _TOPIC_SQL = ("SELECT t.id, t.forum_id, t.subject, t.author, COALESCE(u.name, '?') AS "
                  "author_name, t.created, t.last_post, "
                  "(SELECT COUNT(*) FROM posts p WHERE p.topic_id = t.id) AS posts, "
                  "(SELECT COUNT(*) FROM posts p WHERE p.topic_id = t.id AND p.posted > ?) "
                  "AS new FROM topics t LEFT JOIN users u ON u.id = t.author ")

    def topics(self, forum_id, since=0):
        """The forum's topics (posts, new), the most recently posted in first."""
        return self.conn.execute(self._TOPIC_SQL + "WHERE t.forum_id = ? "
                                 "ORDER BY t.last_post DESC, t.id DESC",
                                 (since or 0, forum_id)).fetchall()

    def topic(self, topic_id, since=0):
        return self.conn.execute(self._TOPIC_SQL + "WHERE t.id = ?",
                                 (since or 0, topic_id)).fetchone()

    def create_topic(self, forum_id, author, subject, lines, now=None):
        """A topic with its first post; returns the topic id."""
        now = int(time.time()) if now is None else now
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO topics (forum_id, subject, author, created, last_post) "
                "VALUES (?, ?, ?, ?, ?)", (forum_id, subject, author, now, now))
            self.conn.execute("INSERT INTO posts (topic_id, author, posted, body) "
                              "VALUES (?, ?, ?, ?)",
                              (cur.lastrowid, author, now, "\n".join(lines)))
        return cur.lastrowid

    def add_post(self, topic_id, author, lines, now=None):
        now = int(time.time()) if now is None else now
        with self.conn:
            cur = self.conn.execute("INSERT INTO posts (topic_id, author, posted, body) "
                                    "VALUES (?, ?, ?, ?)",
                                    (topic_id, author, now, "\n".join(lines)))
            self.conn.execute("UPDATE topics SET last_post = MAX(last_post, ?) WHERE id = ?",
                              (now, topic_id))
        return cur.lastrowid

    _POST_SQL = ("SELECT p.id, p.topic_id, p.author, COALESCE(u.name, '?') AS author_name, "
                 "p.posted, p.body FROM posts p LEFT JOIN users u ON u.id = p.author ")

    def posts(self, topic_id):
        """The topic's posts, oldest first."""
        return self.conn.execute(self._POST_SQL + "WHERE p.topic_id = ? "
                                 "ORDER BY p.posted, p.id", (topic_id,)).fetchall()

    def post(self, post_id):
        return self.conn.execute(self._POST_SQL + "WHERE p.id = ?", (post_id,)).fetchone()

    def delete_topic(self, topic_id):
        with self.conn:
            self.conn.execute("DELETE FROM posts WHERE topic_id = ?", (topic_id,))
            self.conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))

    def delete_post(self, post_id):
        """One post; its topic goes too when it was the last one. True if the topic went."""
        row = self.conn.execute("SELECT topic_id FROM posts WHERE id = ?",
                                (post_id,)).fetchone()
        if row is None:
            return False
        with self.conn:
            self.conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
            last = self.conn.execute("SELECT MAX(posted) FROM posts WHERE topic_id = ?",
                                     (row["topic_id"],)).fetchone()[0]
            if last is None:
                self.conn.execute("DELETE FROM topics WHERE id = ?", (row["topic_id"],))
                return True
            self.conn.execute("UPDATE topics SET last_post = ? WHERE id = ?",
                              (last, row["topic_id"]))
        return False


    # ---- karma points (karma.py) ----

    def change_karma(self, user_id, delta, reason, by_user=None, ceiling=KARMA_MAX):
        """Add `delta` (kept within KARMA_MIN..KARMA_MAX; a gain never goes above `ceiling`)
        and log it. Returns (old, new), or None for no such user. Nothing is logged when the
        value doesn't move."""
        row = self.conn.execute("SELECT karma FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        old = row["karma"]
        new = old + delta
        if delta > 0:
            new = min(new, max(old, ceiling))
        new = max(KARMA_MIN, min(KARMA_MAX, new))
        if new != old:
            with self.conn:
                self.conn.execute("UPDATE users SET karma = ? WHERE id = ?", (new, user_id))
                self.conn.execute("INSERT INTO karma_log (user_id, by_user, delta, karma, reason, "
                                  "at) VALUES (?, ?, ?, ?, ?, ?)",
                                  (user_id, by_user, new - old, new, reason, int(time.time())))
        return old, new

    def karma_log(self, user_id, n=30):
        """The user's latest karma changes, newest first (with who made them, or None)."""
        return self.conn.execute(
            "SELECT k.delta, k.karma, k.reason, k.at, u.name AS by_name FROM karma_log k "
            "LEFT JOIN users u ON u.id = k.by_user WHERE k.user_id = ? "
            "ORDER BY k.at DESC, k.id DESC LIMIT ?", (user_id, n)).fetchall()

    def karma_events_since(self, user_id, since, reason=None, losses=False):
        """How many karma changes since `since`: with this reason (system gains are logged
        with by_user NULL), or (losses=True) any loss."""
        if losses:
            return self.conn.execute("SELECT COUNT(*) FROM karma_log WHERE user_id = ? AND "
                                     "at >= ? AND delta < 0", (user_id, since)).fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM karma_log WHERE user_id = ? AND at >= ? "
                                 "AND reason = ? AND by_user IS NULL",
                                 (user_id, since, reason)).fetchone()[0]

    def karma_given_since(self, user_id, by_user, since):
        """How many karma changes `by_user` gave `user_id` since `since`."""
        return self.conn.execute("SELECT COUNT(*) FROM karma_log WHERE user_id = ? AND "
                                 "by_user = ? AND at >= ?", (user_id, by_user, since)).fetchone()[0]

    def low_karma_users(self, below):
        """Users with karma below `below`, lowest first."""
        return self.conn.execute(self._USER_SQL + "WHERE u.karma < ? ORDER BY u.karma, "
                                 "u.name COLLATE NOCASE", (below,)).fetchall()

    # ---- the bank (bank.py): balances, the ledger, loans, chips on a poker table ----

    def bank_settings(self):
        """The bank's settings as stored (a dict; bank.settings() fills in the defaults)."""
        try:
            got = json.loads(self.setting(BANK_KEY, "{}"))
        except ValueError:
            got = {}
        return got if isinstance(got, dict) else {}

    def set_bank_settings(self, values):
        with self.conn:
            self._set_setting(BANK_KEY, json.dumps(values))

    def start_credits(self):
        start = self.bank_settings().get("start", DEFAULT_START_CREDITS)
        return start if isinstance(start, int) and 0 <= start <= CREDITS_MAX else \
            DEFAULT_START_CREDITS

    def credits(self, user_id):
        row = self.conn.execute("SELECT credits FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["credits"] if row else None

    def _credit(self, user_id, delta, reason, memo, other_id, by_user, at):
        """Inside a transaction: add `delta` unless the balance would go below 0 or above
        CREDITS_MAX; log it. The new balance, or None (nothing changed)."""
        cur = self.conn.execute("UPDATE users SET credits = credits + ? WHERE id = ? AND "
                                "credits + ? BETWEEN 0 AND ?",
                                (delta, user_id, delta, CREDITS_MAX))
        if cur.rowcount != 1:
            return None
        balance = self.credits(user_id)
        self.conn.execute("INSERT INTO credit_log (user_id, delta, balance, reason, memo, "
                          "other_id, by_user, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (user_id, delta, balance, reason, memo[:60], other_id, by_user, at))
        return balance

    def add_credits(self, user_id, delta, reason, memo="", other_id=None, by_user=None):
        """Change a balance and log it: the new balance, or None if it would go below 0 (or
        past CREDITS_MAX), or there's no such user."""
        with self.conn:
            return self._credit(user_id, delta, reason, memo, other_id, by_user,
                                int(time.time()))

    def transfer_credits(self, from_id, to_id, amount, memo=""):
        """A gift: both sides in one transaction. (from's balance, to's) or None if from
        hasn't enough (or to would pass CREDITS_MAX)."""
        now = int(time.time())
        try:
            with self.conn:
                a = self._credit(from_id, -amount, "gift sent", memo, to_id, None, now)
                b = self._credit(to_id, amount, "gift", memo, from_id, None, now) \
                    if a is not None else None
                if b is None:
                    raise _Rollback
                return a, b
        except _Rollback:
            return None

    def credit_log(self, user_id, n=100):
        """The latest ledger rows, newest first, with the other side's and the admin's name."""
        return self.conn.execute(
            "SELECT c.*, o.name AS other_name, b.name AS by_name FROM credit_log c "
            "LEFT JOIN users o ON o.id = c.other_id LEFT JOIN users b ON b.id = c.by_user "
            "WHERE c.user_id = ? ORDER BY c.at DESC, c.id DESC LIMIT ?",
            (user_id, n)).fetchall()

    def credit_events_since(self, user_id, since, reason, other_id=None):
        """How many ledger rows for `reason` since `since` (with that other side, if given)."""
        if other_id is not None:
            return self.conn.execute(
                "SELECT COUNT(*) FROM credit_log WHERE user_id = ? AND at >= ? AND reason = ? "
                "AND other_id = ?", (user_id, since, reason, other_id)).fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM credit_log WHERE user_id = ? AND "
                                 "at >= ? AND reason = ?", (user_id, since, reason)).fetchone()[0]

    def open_loan(self, user_id):
        return self.conn.execute("SELECT * FROM loans WHERE user_id = ? AND closed IS NULL "
                                 "ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()

    def loans_open(self):
        return self.conn.execute("SELECT * FROM loans WHERE closed IS NULL").fetchall()

    def take_loan(self, user_id, amount, rate, days):
        """A new loan: the credits go to the balance. The loan's id, or None (one already
        open, or the balance would pass CREDITS_MAX)."""
        now = int(time.time())
        try:
            with self.conn:
                if self.open_loan(user_id) is not None:
                    raise _Rollback
                if self._credit(user_id, amount, "loan", "%d days at %s%% a day"
                                % (days, ("%g" % rate)), None, None, now) is None:
                    raise _Rollback
                cur = self.conn.execute(
                    "INSERT INTO loans (user_id, principal, owed, rate, taken, due, accrued) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, amount, amount, rate, now, now + days * 86400, now))
                return cur.lastrowid
        except _Rollback:
            return None

    def charge_interest(self, loan_id, owed, accrued, interest):
        """Interest added to a loan (a 0 row in the ledger says how much)."""
        loan = self.conn.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
        with self.conn:
            self.conn.execute("UPDATE loans SET owed = ?, accrued = ? WHERE id = ?",
                              (owed, accrued, loan_id))
            if interest:
                self.conn.execute(
                    "INSERT INTO credit_log (user_id, delta, balance, reason, memo, at) "
                    "VALUES (?, 0, ?, 'loan interest', ?, ?)",
                    (loan["user_id"], self.credits(loan["user_id"]),
                     "+%d: you owe %d" % (interest, owed), int(time.time())))

    def repay_loan(self, loan_id, amount, reason="loan repayment"):
        """Pay `amount` off a loan from the balance (at most what's owed). (paid, still owed)
        or None if the balance hasn't enough."""
        now = int(time.time())
        try:
            with self.conn:
                loan = self.conn.execute("SELECT * FROM loans WHERE id = ? AND closed IS NULL",
                                         (loan_id,)).fetchone()
                if loan is None:
                    raise _Rollback
                amount = min(amount, loan["owed"])
                left = loan["owed"] - amount
                memo = "paid off" if left == 0 else "%d still owed" % left
                if amount <= 0 or self._credit(loan["user_id"], -amount, reason, memo, None,
                                               None, now) is None:
                    raise _Rollback
                self.conn.execute("UPDATE loans SET owed = ?, closed = ? WHERE id = ?",
                                  (left, now if left == 0 else None, loan_id))
                return amount, left
        except _Rollback:
            return None

    def poker_chips(self):
        """{user_id: chips} on poker tables (as of their last hand)."""
        return {r["user_id"]: r["chips"] for r in
                self.conn.execute("SELECT user_id, chips FROM poker_chips")}

    def to_poker_table(self, user_id, amount, reason="poker buy-in"):
        """Buy in (or buy more chips): credits to the table. The balance, or None. (Blackjack
        holds its bets here too: a user is at one table at most.)"""
        now = int(time.time())
        try:
            with self.conn:
                bal = self._credit(user_id, -amount, reason, "", None, None, now)
                if bal is None:
                    raise _Rollback
                self.conn.execute("INSERT INTO poker_chips (user_id, chips, since) VALUES "
                                  "(?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET chips = "
                                  "chips + excluded.chips", (user_id, amount, now))
                return bal
        except _Rollback:
            return None

    def set_poker_chips(self, user_id, chips):
        """After a hand: what a player has on the table now."""
        with self.conn:
            self.conn.execute("UPDATE poker_chips SET chips = ? WHERE user_id = ?",
                              (chips, user_id))

    def from_poker_table(self, user_id, chips=None, memo="", reason="poker cash-out"):
        """Cash out: the chips (None: as stored) go back to the balance. The balance, or None
        if they had nothing on a table."""
        now = int(time.time())
        with self.conn:
            row = self.conn.execute("SELECT chips FROM poker_chips WHERE user_id = ?",
                                    (user_id,)).fetchone()
            if row is None:
                return None
            self.conn.execute("DELETE FROM poker_chips WHERE user_id = ?", (user_id,))
            chips = row["chips"] if chips is None else chips
            room = CREDITS_MAX - self.credits(user_id)
            if min(chips, room) <= 0:
                return self.credits(user_id)
            return self._credit(user_id, min(chips, room), reason, memo, None, None, now)

    def credits_total(self):
        """All the credits there are: (balances, on poker tables, owed on loans)."""
        return (self.conn.execute("SELECT COALESCE(SUM(credits), 0) FROM users").fetchone()[0],
                self.conn.execute("SELECT COALESCE(SUM(chips), 0) FROM poker_chips"
                                  ).fetchone()[0],
                self.conn.execute("SELECT COALESCE(SUM(owed), 0) FROM loans WHERE closed IS "
                                  "NULL").fetchone()[0])

    # ---- chat rooms: the permanent ones (chat.py keeps the members' own in memory) ----

    def chat_rooms(self):
        return self.conn.execute("SELECT id, name, topic, private, created FROM chat_rooms "
                                 "ORDER BY name COLLATE NOCASE").fetchall()

    def create_chat_room(self, name, private=False):
        """Its id, or None if the name (any case) is taken."""
        try:
            with self.conn:
                cur = self.conn.execute("INSERT INTO chat_rooms (name, private, created) "
                                        "VALUES (?, ?, ?)",
                                        (name, 1 if private else 0, int(time.time())))
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def delete_chat_room(self, room_id):
        with self.conn:
            self.conn.execute("DELETE FROM chat_rooms WHERE id = ?", (room_id,))

    def set_chat_room_topic(self, room_id, topic):
        with self.conn:
            self.conn.execute("UPDATE chat_rooms SET topic = ? WHERE id = ?", (topic, room_id))

    # ---- polls (Areas > Voting, polls.py) ----

    _POLL_SQL = ("SELECT p.id, p.question, p.description, p.created, p.ends, u.name AS author_name, "
                 "(SELECT COUNT(*) FROM poll_votes v WHERE v.poll_id = p.id) AS votes "
                 "FROM polls p LEFT JOIN users u ON u.id = p.author ")

    def polls(self):
        """Every poll, newest first, with its vote count."""
        return self.conn.execute(self._POLL_SQL + "ORDER BY p.created DESC, p.id DESC"
                                 ).fetchall()

    def poll(self, poll_id):
        return self.conn.execute(self._POLL_SQL + "WHERE p.id = ?", (poll_id,)).fetchone()

    def poll_choices(self, poll_id):
        """A poll's choices in order: id, text, votes."""
        return self.conn.execute(
            "SELECT c.id, c.text, (SELECT COUNT(*) FROM poll_votes v WHERE v.choice_id = c.id) "
            "AS votes FROM poll_choices c WHERE c.poll_id = ? ORDER BY c.idx",
            (poll_id,)).fetchall()

    def poll_vote_of(self, poll_id, user_id):
        """The choice id `user_id` voted for, or None."""
        row = self.conn.execute("SELECT choice_id FROM poll_votes WHERE poll_id = ? AND "
                                "user_id = ?", (poll_id, user_id)).fetchone()
        return row[0] if row else None

    def create_poll(self, question, choices, ends, author, description=""):
        """A new poll (ends: a time, or None for never). Returns its id."""
        with self.conn:
            cur = self.conn.execute("INSERT INTO polls (question, description, author, "
                                    "created, ends) VALUES (?, ?, ?, ?, ?)",
                                    (question, description, author, int(time.time()), ends))
            for i, text in enumerate(choices):
                self.conn.execute("INSERT INTO poll_choices (poll_id, idx, text) "
                                  "VALUES (?, ?, ?)", (cur.lastrowid, i, text))
        return cur.lastrowid

    def vote(self, poll_id, user_id, choice_id):
        """One vote. False if this user has already voted in the poll (or the choice isn't
        the poll's)."""
        ok = self.conn.execute("SELECT 1 FROM poll_choices WHERE id = ? AND poll_id = ?",
                               (choice_id, poll_id)).fetchone()
        if not ok:
            return False
        try:
            with self.conn:
                self.conn.execute("INSERT INTO poll_votes (poll_id, user_id, choice_id, at) "
                                  "VALUES (?, ?, ?, ?)",
                                  (poll_id, user_id, choice_id, int(time.time())))
            return True
        except sqlite3.IntegrityError:
            return False

    def delete_poll(self, poll_id):
        with self.conn:
            self.conn.execute("DELETE FROM poll_votes WHERE poll_id = ?", (poll_id,))
            self.conn.execute("DELETE FROM poll_choices WHERE poll_id = ?", (poll_id,))
            self.conn.execute("DELETE FROM polls WHERE id = ?", (poll_id,))

    # ---- news bulletins (Areas > News, news.py) ----

    _NEWS_SQL = ("SELECT n.id, n.headline, n.body, n.posted, n.edited, a.name AS author_name, "
                 "e.name AS editor_name FROM news n LEFT JOIN users a ON a.id = n.author "
                 "LEFT JOIN users e ON e.id = n.editor ")

    def news(self):
        """Every bulletin, newest first."""
        return self.conn.execute(self._NEWS_SQL + "ORDER BY n.posted DESC, n.id DESC").fetchall()

    def bulletin(self, news_id):
        return self.conn.execute(self._NEWS_SQL + "WHERE n.id = ?", (news_id,)).fetchone()

    def post_news(self, headline, lines, author):
        """A new bulletin; returns its id."""
        with self.conn:
            cur = self.conn.execute("INSERT INTO news (headline, body, author, posted) "
                                    "VALUES (?, ?, ?, ?)",
                                    (headline, "\n".join(lines), author, int(time.time())))
        return cur.lastrowid

    def edit_news(self, news_id, headline, lines, editor):
        """(`edited` always moves on, even within a second: it is the version news_reads
        compares, so every edit is unread again.)"""
        with self.conn:
            self.conn.execute("UPDATE news SET headline = ?, body = ?, editor = ?, "
                              "edited = MAX(?, COALESCE(edited, posted) + 1) WHERE id = ?",
                              (headline, "\n".join(lines), editor, int(time.time()), news_id))

    def delete_news(self, news_id):
        with self.conn:
            self.conn.execute("DELETE FROM news_reads WHERE news_id = ?", (news_id,))
            self.conn.execute("DELETE FROM news WHERE id = ?", (news_id,))

    def unread_news(self, user_id):
        """The ids of the bulletins `user_id` hasn't read since they were posted or last
        edited, newest first."""
        return [r[0] for r in self.conn.execute(
            "SELECT n.id FROM news n LEFT JOIN news_reads r ON r.news_id = n.id "
            "AND r.user_id = ? WHERE r.read_at IS NULL "
            "OR r.read_at < COALESCE(n.edited, n.posted) "
            "ORDER BY n.posted DESC, n.id DESC", (user_id,))]

    def mark_news_read(self, user_id, news_ids):
        """`user_id` has read these bulletins, as they are now."""
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO news_reads (user_id, news_id, read_at) "
                "SELECT ?, id, COALESCE(edited, posted) FROM news WHERE id = ?",
                [(user_id, i) for i in news_ids])
