"""My Account: the user's profile, opened from the client's own MegaNet menu (MENU_PICK $22,
protocol.MENU_MY_ACCOUNT), and the Reset Password dialog.

    9  = My Account: Username (and the Role beside it), First Name and Last Name (required),
         Email Address, Location (63-character text boxes that scroll), Birthdate (Month / Day /
         Year drop-downs, "--" = not set), About Me (an EDIT text area, up to db.ABOUT_LINES
         lines), Last Login (the sign-on before this one), Karma Points (karma.describe:
         "42 (OK)", shown, not edited) and the Credits beside it (bank.py: it follows the
         balance while the window is open); on the right, Preferences: "Ring when Away" (the
         doorbell for new messages while Away: session.ring) and "Activity ticker" (the
         desktop's ticker: livedesk.py); a status line; Reset Password at the bottom left,
         OK (default) and Cancel at the bottom right
    19 = Reset Password (modal): Current password, New password, Confirm; OK, Cancel

Labels are one column (LABEL_W wide), fields a second column at FIELD_X, rows ROW px apart.
"""

import asyncio
import calendar
import datetime
import textwrap
import time

from . import db as dbmod
from . import karma
from .protocol import WFlag, GFlag, clean_text
from .ui import (add_buttons, closer, Window, Button, CheckBox, Label, TextBox, Password, DropDown,
                 TextArea, Group)

WIN_ACCOUNT = 9
WIN_PASSWORD = 19

LABEL_X, LABEL_W = 4, 112        # "Email Address:" is 14 characters
FIELD_X = 124                    # (an 8 px gap after the longest label)
FIELD_W = 260                    # text boxes show 32 of their 63 characters and scroll;
                                 # About Me lines are (260 - 6 - 11) // 8 = 30 characters
PREF_X = FIELD_X + FIELD_W + 12  # 396: the Preferences column, framed
PREF_W = 160                     # (the box, then up to 17 characters)
W = PREF_X + PREF_W + 4          # 560: client area (the window is centred)
H = 171                          # = protocol.CLIENT_MAX_H
ROW = 14                         # rows are this far apart; a TextBox / DropDown is 12 high
TOP = 2                          # the first row (all of it fits in CLIENT_MAX_H)
BOX_H = 12
ABOUT_H = 30                     # About Me shows (30 - 6) // 8 = 3 lines
BUTTON_W, BUTTON_H = 64, 16
REAL_W = 6 + 8 * dbmod.REAL_NAME_MAX   # 166: first and last names show whole
ROLE_X = 96                      # the Role, beside the (10-character) Username

# Birthdate drop-downs: x offset from FIELD_X and width (room for 3 / 2 / 4 characters)
MONTH_X, MONTH_W = 0, 48
DAY_X, DAY_W = 52, 40
YEAR_X, YEAR_W = 96, 56
NOT_SET = "--"
MONTHS = [calendar.month_abbr[m] for m in range(1, 13)]          # Jan .. Dec
FIRST_YEAR = 1960

PW_TRIES = 3                     # wrong current passwords before the dialog closes
PW_LOCK_SECS = 60                # and Reset Password is refused for this long


def when(t, fmt="%Y-%m-%d %H:%M"):
    return time.strftime(fmt, time.localtime(t))


def year_rows(today=None, stored=None):
    """The Year drop-down's rows after "--": this year down to FIRST_YEAR (newest first). A
    stored year outside that range is kept in the list so it isn't lost."""
    years = list(range((today or datetime.date.today()).year, FIRST_YEAR - 1, -1))
    if stored is not None and stored not in years:
        years.append(stored)
        years.sort(reverse=True)
    return [str(y) for y in years]


KARMA_W = 120                    # "Karma Points:" "42 (Excellent)", then the credits beside it
RING_TEXT = "Ring when Away"
TICKER_TEXT = "Activity ticker"


def credits_text(n):
    """(17 characters at most: millions go without commas)"""
    text = " Credits: {:,}".format(n)
    return text if len(text) <= (FIELD_W - KARMA_W) // 8 else " Credits: %d" % n


def role_text(session):
    return short("Role: %s" % (session.role or "none"), (FIELD_W - ROLE_X) // 8)


def short(text, n):
    return text if len(text) <= n else text[:n - 3] + "..."


def wrap_lines(lines, width):
    """Word-wrap each line to `width` characters (a long word is cut); empty lines stay."""
    out = []
    for line in lines:
        out += textwrap.wrap(line, width, break_on_hyphens=False) or [""]
    return out


def tidy_about(lines, columns):
    """About Me as typed: ASCII, wrapped to `columns` (the client wraps typing too, but may send
    longer lines), trailing spaces and trailing empty lines dropped."""
    about = wrap_lines([clean_text(s).rstrip() for s in lines], columns)
    while about and not about[-1]:
        about.pop()
    return about


def length_problem(email, location):
    if any(len(s) > dbmod.PROFILE_MAX for s in (email, location)):
        return "Email and Location hold at most %d characters." % dbmod.PROFILE_MAX
    return None


def about_problem(about):
    if len(about) > dbmod.ABOUT_LINES:
        return "About Me has %d lines: it holds at most %d." % (len(about), dbmod.ABOUT_LINES)
    return None


class Account:
    def __init__(self, server):
        self.server = server

    @property
    def db(self):
        return self.server.db

    def open(self, session, status=None):
        if session.user is None:
            return None
        user = self.db.user(user_id=session.user_id)
        if user is None:
            return None
        win = Window.centred("My Account", W, H, flags=WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_ACCOUNT)
        y = TOP

        def label(text, y):
            win.add(Label(LABEL_X, y + 2, LABEL_W, 10, text))

        # Preferences, framed, down the right (first: the frame is drawn under them)
        win.add(Group(PREF_X, TOP, PREF_W, 8 * ROW + ABOUT_H - 1))   # (to the Karma row)
        win.add(Label(PREF_X + 8, TOP + 4, PREF_W - 16, 10, "Preferences", flags=GFlag.BOLD))
        # whether new instant and private messages ring the doorbell while they're Away
        # (session.ring); when they're Available it always rings
        win.ring = win.add(CheckBox(PREF_X + 8, TOP + 4 + ROW + 4, PREF_W - 16, BOX_H, RING_TEXT,
                                    bool(user["ring_away"])))
        win.ticker = win.add(CheckBox(PREF_X + 8, TOP + 4 + 2 * ROW + 4, PREF_W - 16, BOX_H,
                                      TICKER_TEXT, bool(user["show_ticker"])))

        label("Username:", y)
        win.add(Label(FIELD_X, y + 2, ROLE_X, 10, user["name"]))
        win.role = win.add(Label(FIELD_X + ROLE_X, y + 2, FIELD_W - ROLE_X, 10,
                                 role_text(session)))
        y += ROW
        label("First Name:", y)
        win.first = win.add(TextBox(FIELD_X, y, REAL_W, BOX_H, user["first_name"]))
        y += ROW
        label("Last Name:", y)
        win.last = win.add(TextBox(FIELD_X, y, REAL_W, BOX_H, user["last_name"]))
        y += ROW
        label("Email Address:", y)
        win.email = win.add(TextBox(FIELD_X, y, FIELD_W, BOX_H, user["email"]))
        y += ROW
        label("Location:", y)
        win.location = win.add(TextBox(FIELD_X, y, FIELD_W, BOX_H, user["location"]))
        y += ROW
        label("Birthdate:", y)
        m = dbmod.DATE_RE.fullmatch(user["birthdate"] or "")
        year, month, day = (int(m[1]), int(m[2]), int(m[3])) if m else (None, 0, 0)
        years = year_rows(stored=year)
        win.month = win.add(DropDown(FIELD_X + MONTH_X, y, MONTH_W, [NOT_SET] + MONTHS,
                                     month if 1 <= month <= 12 else 0))
        win.day = win.add(DropDown(FIELD_X + DAY_X, y, DAY_W,
                                   [NOT_SET] + [str(d) for d in range(1, 32)],
                                   day if 1 <= day <= 31 else 0))
        win.year = win.add(DropDown(FIELD_X + YEAR_X, y, YEAR_W, [NOT_SET] + years,
                                    years.index(str(year)) + 1 if m else 0))
        y += ROW
        label("About Me:", y)
        win.about = win.add(TextArea(FIELD_X, y, FIELD_W, ABOUT_H))
        # Stored lines are kept as they are, but lines saved before About Me was a text area
        # could be 63 characters: wrap them to its width for the client.
        about = user["about"] or ""
        win.about.lines = wrap_lines(about.split("\n"), win.about.columns()) if about else []
        y += ABOUT_H + 1
        label("Last Login:", y)
        last = session.previous_login
        win.add(Label(FIELD_X, y + 2, FIELD_W, 10, when(last) if last else "First sign-on"))
        y += ROW
        label("Karma Points:", y)                # (as the User Editor says it)
        win.karma = win.add(Label(FIELD_X, y + 2, KARMA_W, 10, karma.describe(user["karma"])))
        win.credits = win.add(Label(FIELD_X + KARMA_W, y + 2, FIELD_W - KARMA_W, 10,
                                    credits_text(user["credits"])))
        y += ROW - 2                            # (right under it: the buttons come next)
        win.status = win.add(Label(LABEL_X, y, PREF_X - LABEL_X - 4, 10, status or ""))
        y = H - 2 - BUTTON_H
        win.add(Button(LABEL_X, y, 144, BUTTON_H, "Reset Password...", on_click=self._reset))
        right = PREF_X + PREF_W
        win.add(Button(right - 2 * BUTTON_W - 8, y, BUTTON_W, BUTTON_H, "OK", GFlag.DEFAULT,
                       on_click=self._ok))
        win.add(Button(right - BUTTON_W, y, BUTTON_W, BUTTON_H, "Cancel",
                       on_click=lambda b: b.window.close()))
        win.show(session)
        return win

    def credits_changed(self, session):
        """The bank changed this user's balance: My Account shows it (bank.changed)."""
        win = session.windows.get(WIN_ACCOUNT)
        if win is not None and hasattr(win, "credits"):
            win.credits.set_text(credits_text(self.db.credits(session.user_id) or 0))

    def role_changed(self, session):
        win = session.windows.get(WIN_ACCOUNT)
        if win is not None and hasattr(win, "role"):
            win.role.set_text(role_text(session))

    # ---- handlers ----

    @staticmethod
    def birthdate(win, today=None):
        """From the drop-downs: (YYYY-MM-DD, or "" when all three are "--", None), or
        (None, problem)."""
        month, day, year = (win.month.selected or 0, win.day.selected or 0,
                            win.year.selected or 0)
        if not (month or day or year):
            return "", None
        if not (month and day and year):
            return None, "Birthdate: set month, day and year, or all --."
        year = int(win.year.rows[year])
        if day > calendar.monthrange(year, month)[1]:
            return None, "Birthdate: %s %d has no day %d." % (MONTHS[month - 1], year, day)
        text = "%04d-%02d-%02d" % (year, month, day)
        problem = dbmod.check_birthdate(text, today)
        return (None, problem) if problem else (text, None)

    def _ok(self, button):
        session, win = button.session, button.window
        if session.user is None:
            return None
        first = clean_text(win.first.value).strip()
        last = clean_text(win.last.value).strip()
        email = clean_text(win.email.value).strip()
        location = clean_text(win.location.value).strip()
        about = tidy_about(win.about.lines, win.about.columns())
        birthdate, problem = self.birthdate(win)
        problem = (dbmod.real_names_problem(first, last) or dbmod.check_email(email)
                   or problem or length_problem(email, location) or about_problem(about))
        if problem:
            return win.status.set_text(problem)
        self.db.set_profile(session.user_id, first, last, email, location, birthdate, about)
        session.ring_away = win.ring.checked
        self.db.set_ring_away(session.user_id, session.ring_away)
        if win.ticker.checked != session.show_ticker:
            session.show_ticker = win.ticker.checked
            self.db.set_show_ticker(session.user_id, session.show_ticker)
            self.server.screens.live.update(session)       # (on or off at once)
        session.log("saved My Account")
        return win.close()

    def _reset(self, button):
        session = button.session
        if session.user is None:
            return None
        if time.time() < session.pw_locked_until:
            return button.window.status.set_text("Too many wrong passwords: wait a minute.")
        win = Window.centred("Reset Password", 320, 84,
                             flags=WFlag.CLOSE | WFlag.MODAL | WFlag.MOVABLE,
                             win_id=WIN_PASSWORD)
        rows = [("Current password:", "current"), ("New password:", "new"),
                ("Confirm:", "confirm")]
        for i, (text, attr) in enumerate(rows):
            win.add(Label(8, 4 + i * ROW + 2, 136, 10, text))
            setattr(win, attr, win.add(Password(152, 4 + i * ROW, 160, BOX_H)))
        win.status = win.add(Label(8, 52, 304, 10, "Passwords need at least 4 characters."))
        add_buttons(win, [("OK", self._change, GFlag.DEFAULT), ("Cancel", closer, 0)])
        win.tries = 0
        win.show(session)
        return win

    async def _change(self, button):
        session, win = button.session, button.window
        if session.user is None:
            return None
        current, new, confirm = win.current.value, win.new.value, win.confirm.value
        if not current:
            return win.status.set_text("Type your current password.")
        stored = self.db.password_hash(session.user)
        good = stored is not None and await asyncio.to_thread(
            dbmod.verify_password, current, stored)
        if not win.shown:
            return None
        if not good:
            win.tries += 1
            session.warn("wrong current password (%d)" % win.tries)
            if win.tries >= PW_TRIES:
                session.pw_locked_until = time.time() + PW_LOCK_SECS
                win.close()
                return session.alert("Reset Password", "Too many wrong passwords. Your "
                                     "password was not changed.")
            win.current.set_text("")
            return win.status.set_text("That's not your current password.")
        problem = dbmod.check_new_password(new)
        if problem is None and new != confirm:
            problem = "The new passwords don't match."
        if problem:
            return win.status.set_text(problem)
        pw_hash = await asyncio.to_thread(dbmod.hash_password, new)
        self.db.set_password(session.user_id, pw_hash)
        session.log("changed password")
        for box in (win.current, win.new, win.confirm):
            box.set_text("")
        return win.status.set_text("Your password has been changed.")
