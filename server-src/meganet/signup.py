"""New User sign-up: a friendly step-by-step wizard.

The client's New User button sends C.LOGIN with flags bit 0 set and an EMPTY screen name and
password; that starts the wizard (a LOGIN with bit 0 and a name still creates the account at
once, as before). The session isn't signed on while it runs, but CLICK / VALUE / SELECT / TEXT /
WIN_CLOSED for the wizard's window are let through (session.py).

One window, WIN_SIGNUP (20), centred, modal, W x H = 448 x 152, sent again for every step:

    1  Screen name   a welcome, the rule, a 10-character text box; First Name and Last Name
                     (required, db.check_real_name)
    2  Password      Password and Confirm, with the rule (db.check_new_password)
    3  About you     Birthdate (Month / Day / Year drop-downs, as My Account), Location, Email
                     (all optional)
    4  About me      a TextArea as wide as My Account's (30-character lines, 8 lines, all shown)
    5  Review        every value on labels; Accept (default), Back, Cancel

Each step: "Step n of 5" at the top left, its text, its fields, a status line, and Back
(not on step 1) / Next (default; Accept on step 5) / Cancel at the bottom right. The values
are kept here between steps, so Back shows them again. Next checks the step; Accept checks
everything again (and shows the first step with a problem).

The name is reserved while the wizard holds it (after a good step 1): another session's
wizard, or an old-style new-user LOGIN, can't take it.

Cancel or the close box: the window closes and the client gets LOGIN_RESULT 0 "Sign-up
cancelled."; the connection stays open for another LOGIN.
Accept: the account is created (default role; the very first account is Sysop) with the
profile, the admins get an admin_messages entry and their envelope icon (not for the first
account: it is the Sysop), then LOGIN_RESULT 1 and the usual sign-on (menu, welcome window...),
and last an ALERT in front: "Welcome to MegaNet!".
"""

import asyncio
import types

from . import db as dbmod
from .account import (Account, MONTHS, NOT_SET, year_rows, tidy_about, length_problem,
                      about_problem, LABEL_X, LABEL_W, FIELD_X, FIELD_W, MONTH_X, MONTH_W,
                      DAY_X, DAY_W, YEAR_X, YEAR_W, BOX_H, BUTTON_W, BUTTON_H)
from .protocol import WFlag, GFlag, clean_text
from .ui import Window, Button, Label, TextBox, Password, DropDown, TextArea

WIN_SIGNUP = 20
WIN_SET_UP = 21                      # "your account is set up": OK, then the welcome window

W, H = 448, 152                      # client area (centred: x 92, y 20)
STEPS = 5
TEXT_W = W - 2 * LABEL_X             # 440: a line of text holds 55 characters
NAME_W = 96                          # room for the 10 characters of a screen name
REAL_W = 6 + 8 * dbmod.REAL_NAME_MAX  # 166: a first or last name shows whole
PW_W = 160
ABOUT_H = 6 + 8 * dbmod.ABOUT_LINES  # 70: all 8 About Me lines show at once
VALUE_W = W - LABEL_X - FIELD_X      # 320: review values show 40 characters
REVIEW_ROW = 11                      # 8 rows (two of About Me) end above the status
STATUS_Y = H - 2 - BUTTON_H - 14     # 120
BUTTON_Y = H - 2 - BUTTON_H          # 134

TITLES = {1: "Screen Name", 2: "Password", 3: "About You", 4: "About Me", 5: "Review"}

CANCELLED = "Sign-up cancelled."
TAKEN = "That name is taken, please try another."
BUSY = "Someone is signing up with that name: try another."
MISMATCH = "The passwords don't match. Please type them again."
NOT_GIVEN = "not given"
WELCOME_TITLE = "Welcome to MegaNet!"
WELCOME_TEXT = "Account set up! An admin has been told and will upgrade your access."
WELCOME_SYSOP = "Account set up! As the first member, you are the Sysop."
ADMIN_SUBJECT = "New user"
ADMIN_TEXT = "%s has just signed up. Please check their access (Admin > User Editor)."


def short(text, n):
    return text if len(text) <= n else text[:n - 3] + "..."


class Signup:
    """The wizard's shared side: starting one, and the names wizards hold."""

    def __init__(self, server):
        self.server = server

    @property
    def db(self):
        return self.server.db

    def start(self, session):
        """C.LOGIN with the new-user flag and no name: step 1 (a wizard already running starts
        over)."""
        if session.signup is not None:
            session.signup.abandon()
        session.signup = Wizard(self, session)
        session.log("sign-up started")
        session.signup.show(1)

    def reserved(self, name, exclude=None):
        """True if another session's wizard holds `name` (any case)."""
        name = name.lower()
        return any(s is not exclude and not s.closed and s.signup is not None
                   and s.signup.name.lower() == name for s in list(self.server.sessions))

    def name_problem(self, name, session):
        problem = dbmod.check_new_name(name)
        if problem:
            return problem
        if self.db.user(name) is not None:
            return TAKEN
        if self.reserved(name, exclude=session):
            return BUSY
        return None


class Wizard:
    """One session's sign-up: the values typed so far and the step on screen."""

    def __init__(self, signup, session):
        self.signup = signup
        self.session = session
        self.step = 1
        self.typed_name = ""         # step 1's box as last seen
        self.name = ""               # the checked name: reserved while set
        self.first = self.last = ""  # first and last name (step 1, required)
        self.password = self.confirm = ""
        self.month = self.day = self.year = 0          # drop-down rows (0 = "--")
        self.years = [NOT_SET] + year_rows()
        self.location = self.email = ""
        self.about = []
        self.win = None

    @property
    def db(self):
        return self.signup.db

    # ---- the window ----

    def show(self, step, status=""):
        self.step = step
        win = Window.centred("New User: %s" % TITLES[step], W, H,
                             flags=WFlag.CLOSE | WFlag.MODAL | WFlag.MOVABLE,
                             win_id=WIN_SIGNUP, on_close=self._closed)
        win.add(Label(LABEL_X, 4, TEXT_W, 10, "Step %d of %d" % (step, STEPS)))
        getattr(self, "_step%d" % step)(win)
        win.status = win.add(Label(LABEL_X, STATUS_Y, TEXT_W, 10, status))
        right = W - LABEL_X
        cancel_x = right - BUTTON_W
        next_x = cancel_x - 16 - BUTTON_W
        if step > 1:
            win.add(Button(next_x - 8 - BUTTON_W, BUTTON_Y, BUTTON_W, BUTTON_H, "Back",
                           on_click=self._back))
        if step < STEPS:
            win.add(Button(next_x, BUTTON_Y, BUTTON_W, BUTTON_H, "Next", GFlag.DEFAULT,
                           on_click=self._next))
        else:
            win.add(Button(next_x, BUTTON_Y, BUTTON_W, BUTTON_H, "Accept", GFlag.DEFAULT,
                           on_click=self._accept))
        win.add(Button(cancel_x, BUTTON_Y, BUTTON_W, BUTTON_H, "Cancel", on_click=self._cancel))
        self.win = win
        win.show(self.session)
        return win

    @staticmethod
    def _text(win, y, *lines):
        for i, line in enumerate(lines):
            win.add(Label(LABEL_X, y + 12 * i, TEXT_W, 10, line))

    @staticmethod
    def _label(win, y, text):
        win.add(Label(LABEL_X, y + 2, LABEL_W, 10, text))

    def _step1(self, win):
        self._text(win, 20, "Welcome to MegaNet! Let's set up your account.",
                   "Choose a screen name: 3-10 letters, digits or spaces.",
                   "Other members will know you by it. Then your real name.")
        self._label(win, 62, "Screen name:")
        win.name_box = win.add(TextBox(FIELD_X, 62, NAME_W, BOX_H, self.typed_name))
        self._label(win, 77, "First Name:")
        win.first = win.add(TextBox(FIELD_X, 77, REAL_W, BOX_H, self.first))
        self._label(win, 92, "Last Name:")
        win.last = win.add(TextBox(FIELD_X, 92, REAL_W, BOX_H, self.last))

    def _step2(self, win):
        self._text(win, 20, "Next, a password, so nobody else can use your name.",
                   dbmod.check_new_password("") + " Type it twice.")
        self._label(win, 50, "Password:")
        win.pw = win.add(Password(FIELD_X, 50, PW_W, BOX_H, self.password))
        self._label(win, 65, "Confirm:")
        win.confirm = win.add(Password(FIELD_X, 65, PW_W, BOX_H, self.confirm))

    def _step3(self, win):
        self._text(win, 20, "Tell us a little about you. All of this is optional,",
                   "and you can change it later in MegaNet > My Account.")
        y = 48
        self._label(win, y, "Birthdate:")
        win.month = win.add(DropDown(FIELD_X + MONTH_X, y, MONTH_W, [NOT_SET] + MONTHS,
                                     self.month))
        win.day = win.add(DropDown(FIELD_X + DAY_X, y, DAY_W,
                                   [NOT_SET] + [str(d) for d in range(1, 32)], self.day))
        win.year = win.add(DropDown(FIELD_X + YEAR_X, y, YEAR_W, self.years, self.year))
        y += 15
        self._label(win, y, "Location:")
        win.location = win.add(TextBox(FIELD_X, y, FIELD_W, BOX_H, self.location))
        y += 15
        self._label(win, y, "Email Address:")
        win.email = win.add(TextBox(FIELD_X, y, FIELD_W, BOX_H, self.email))

    def _step4(self, win):
        self._text(win, 20, "Say hello! A few lines about yourself (optional).",
                   "Up to %d lines; you can change them in My Account." % dbmod.ABOUT_LINES)
        self._label(win, 46, "About Me:")
        win.about = win.add(TextArea(FIELD_X, 46, FIELD_W, ABOUT_H, self.about))

    def _step5(self, win):
        self._text(win, 18, "Please check your details, then click Accept.")
        about = self.about[:2] or [NOT_GIVEN]
        if len(self.about) > 2:
            about[1] += " ..."
        rows = [("Screen name:", self.name), ("Name:", "%s %s" % (self.first, self.last)),
                ("Password:", "*" * len(self.password)),
                ("Birthdate:", self.birthdate_text()),
                ("Location:", self.location or NOT_GIVEN),
                ("Email Address:", self.email or NOT_GIVEN), ("About Me:", about[0])]
        rows += [("", line) for line in about[1:]]
        for i, (label, value) in enumerate(rows):
            y = 30 + REVIEW_ROW * i
            if label:
                win.add(Label(LABEL_X, y, LABEL_W, 10, label))
            win.add(Label(FIELD_X, y, VALUE_W, 10, short(value, VALUE_W // 8)))

    # ---- values ----

    def capture(self):
        """Keep what the client sent for the step on screen."""
        win = self.win
        if self.step == 1:
            self.typed_name = clean_text(win.name_box.value)
            self.first = clean_text(win.first.value).strip()
            self.last = clean_text(win.last.value).strip()
        elif self.step == 2:
            self.password, self.confirm = win.pw.value, win.confirm.value
        elif self.step == 3:
            self.month, self.day, self.year = (win.month.selected or 0, win.day.selected or 0,
                                               win.year.selected or 0)
            self.location = clean_text(win.location.value).strip()
            self.email = clean_text(win.email.value).strip()
        elif self.step == 4:
            self.about = tidy_about(win.about.lines, win.about.columns())

    def birthdate(self):
        """(YYYY-MM-DD or "", None) or (None, problem): My Account's rules."""
        dd = types.SimpleNamespace
        return Account.birthdate(dd(month=dd(selected=self.month), day=dd(selected=self.day),
                                    year=dd(selected=self.year, rows=self.years)))

    def birthdate_text(self):
        if not (self.month and self.day and self.year):
            return NOT_GIVEN
        return "%d %s %s" % (self.day, MONTHS[self.month - 1], self.years[self.year])

    def check(self, step):
        """None if step `step`'s values are good, else the problem."""
        if step == 1:
            name = self.typed_name.strip()
            problem = self.signup.name_problem(name, self.session)
            self.name = "" if problem else name          # (a bad name is not held)
            return problem or dbmod.real_names_problem(self.first, self.last)
        if step == 2:
            problem = dbmod.check_new_password(self.password)
            if problem is None and self.password != self.confirm:
                problem = MISMATCH
            return problem
        if step == 3:
            _date, problem = self.birthdate()
            return (dbmod.check_email(self.email) or problem
                    or length_problem(self.email, self.location))
        if step == 4:
            return about_problem(self.about)
        return None

    # ---- buttons ----

    def _live(self, button):
        return self.session.signup is self and button.window is self.win

    def _next(self, button):
        if not self._live(button):
            return None
        self.capture()
        problem = self.check(self.step)
        if problem:
            return self.win.status.set_text(problem)
        self.show(self.step + 1)
        return None

    def _back(self, button):
        if not self._live(button):
            return None
        self.capture()
        self.show(max(1, self.step - 1))
        return None

    async def _accept(self, button):
        if not self._live(button):
            return None
        for step in range(1, STEPS):
            problem = self.check(step)
            if problem:
                self.show(step, problem)
                return None
        session = self.session
        pw_hash = await asyncio.to_thread(dbmod.hash_password, self.password)
        if session.closed or session.signup is not self:
            return None
        if not self.db.create_user(self.name, pw_hash):      # (taken in the meantime)
            self.name = ""
            self.show(1, TAKEN)
            return None
        user = self.db.user(self.name)
        birthdate, _ = self.birthdate()
        self.db.set_profile(user["id"], self.first, self.last, self.email, self.location,
                            birthdate, self.about)
        first = self.db.user_count() == 1
        if not first:
            self.db.add_admin_message(user["id"], ADMIN_SUBJECT, [ADMIN_TEXT % self.name])
        self.win.close()
        session.signup = None
        session.log("sign-up accepted: %s" % self.name)
        screens = session.server.screens
        session.sign_on(self.name, "Welcome to MegaNet, %s!" % self.name, new=True,
                        welcome=False)
        if not first:
            screens.pages.messages_changed()          # the admins' envelope icons
        set_up_window(session, first)
        return None

    def _cancel(self, button):
        if not self._live(button):
            return None
        self.win.close()
        self.cancelled()
        return None

    def _closed(self, window):
        """The close box: the same as Cancel."""
        if self.session.signup is self and window is self.win:
            self.cancelled()

    def cancelled(self):
        self.session.signup = None
        self.session.log("sign-up cancelled")
        self.session.login_result(False, CANCELLED)

    def abandon(self):
        """Drop the wizard without a LOGIN_RESULT (a new LOGIN replaced it)."""
        if self.win is not None:
            self.win.close()
        if self.session.signup is self:
            self.session.signup = None


SET_UP_W, SET_UP_H = 432, 68


def set_up_lines(name, first):
    if first:
        return ["Your account is set up, %s!" % name,
                "As the very first member, you are the Sysop."]
    return ["Your account is set up, %s!" % name,
            "An admin has been told and will upgrade",
            "your access soon."]


def set_up_window(session, first):
    """After Accept: "your account is set up" on its own, centred, a line per label; OK (or
    the close box) closes it and only then opens the welcome window with the message of the
    day."""
    lines = set_up_lines(session.user, first)
    win = Window.centred(WELCOME_TITLE, SET_UP_W, SET_UP_H,
                         flags=WFlag.CLOSE | WFlag.MODAL | WFlag.MOVABLE, win_id=WIN_SET_UP,
                         on_close=lambda w: session.server.screens.welcome(session))
    for i, line in enumerate(lines):
        win.add(Label(8, 4 + i * 12, SET_UP_W - 16, 10, line, GFlag.CENTRE))

    def ok(button):
        button.window.close()
        session.server.screens.welcome(session)
    win.add(Button((SET_UP_W - BUTTON_W) // 2, SET_UP_H - 20, BUTTON_W, 16, "OK",
                   GFlag.DEFAULT,
                   on_click=ok))
    win.show(session)
    return win
