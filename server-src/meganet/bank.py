"""The Bank (Areas > Bank, bank.use): every user's credits, earned around MegaNet and spent at
the poker table, given to each other, or borrowed.

- A balance is users.credits; every change is a row in the ledger (credit_log) with its
  reason, so the Bank window's statement shows where each credit came from. A balance never
  goes below 0.
- A new account opens with the starting credits (Admin > Bank Settings; accounts from before
  the bank opened got them once too).
- Earning (earn()): EARN below, each reason paying `amount` up to `per day` times a day (both
  set in Bank Settings). Winning pays at most SAME_OPPONENT_WINS times a day against the same
  person, so two accounts can't farm each other. A chat line pays only when it's at least
  CHAT_MIN characters and not the same as the last one. "An hour signed on" counts the
  minutes with some activity in the last ACTIVE_SECS (run()).
- Gifts: any amount up to your balance to another user, with a note; they get a private
  message about it (and a toast if signed on).
- Loans: one at a time, up to the largest loan, at a daily interest rate (compounded,
  charged when the loan is next looked at), due after the loan days. A share of everything
  earned pays it back first (all of it once it's overdue); Repay pays from the balance.
  While a loan is overdue there are no gifts and no poker.
- Admins (admin.bank) change the settings; the User Editor (admin.users) shows and sets a
  user's balance ("set by an admin" in their ledger) and their statement under History.
"""

import asyncio
import logging
import math
import time

from . import db as dbmod
from . import permissions as perms
from .compose import refuse
from .karma import day_start
from .protocol import WFlag, GFlag, clean_text
from .ui import (add_buttons, closer, Window, Label, TextBox, TextView, AreaWindow,
                 MARGIN)

log = logging.getLogger("meganet")

USE, ADMIN = perms.BANK_USE, perms.ADMIN_BANK
TITLE = "Bank"

# (reason, what How to Earn calls it, default credits, default most a day)
EARN = [
    ("game played", "Playing a game", 5, 20),
    ("game won", "Winning a game", 20, 10),
    ("poker hand", "A hand of poker", 1, 50),
    ("board post", "A message board post", 5, 10),
    ("chat", "A line in a chat room", 1, 20),
    ("poll vote", "Voting in a poll", 5, 10),
    ("hour online", "An hour signed on", 10, 8),
]
EARN_REASONS = [r for r, _, _, _ in EARN]
QUIET = {"chat", "poker hand"}           # earned without a toast (they come often)
SAME_OPPONENT_WINS = 3                   # wins a day that pay against the same person
CHAT_MIN = 4
ACTIVE_SECS = 600                        # a minute counts if they did something this recently
CHECK_EVERY = 60

# the other settings: key -> (default, lowest, highest, what Bank Settings calls it)
LIMITS = {
    "start": (dbmod.DEFAULT_START_CREDITS, 0, 100_000, "Starting credits"),
    "loan_max": (1000, 0, 100_000, "Largest loan"),
    "interest": (2, 0, 50, "Interest, % a day"),
    "loan_days": (14, 1, 365, "Loan days"),
    "repay_share": (50, 0, 100, "Earnings to loan, %"),
    "referral": (100, 0, 100_000, "Credits for a referral"),
}
EARN_MAX, PER_DAY_MAX = 1000, 1000


def credits(n):
    """1,250 credits."""
    return "{:,} credit{}".format(n, "" if n == 1 else "s")


def num(n):
    return "{:,}".format(n)


def settings(db):
    """The bank's settings, defaults filled in: start, loan_max, interest, loan_days,
    repay_share, and earn {reason: [credits, most a day]}."""
    got = db.bank_settings()
    out = {}
    for key, (default, lo, hi, _) in LIMITS.items():
        v = got.get(key, default)
        out[key] = v if isinstance(v, (int, float)) and lo <= v <= hi else default
    earn = got.get("earn") if isinstance(got.get("earn"), dict) else {}
    out["earn"] = {}
    for reason, _, amount, per_day in EARN:
        v = earn.get(reason)
        ok = (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) for x in v)
              and 0 <= v[0] <= EARN_MAX and 0 <= v[1] <= PER_DAY_MAX)
        out["earn"][reason] = list(v) if ok else [amount, per_day]
    return out


def parse_amount(text, most=dbmod.CREDITS_MAX):
    """A whole number of credits typed in a box (commas allowed): (n, None) or (None, why)."""
    t = clean_text(text).strip().replace(",", "")
    if not (t.isascii() and t.isdigit()):
        return None, "Type a number of credits."
    n = int(t)
    if n <= 0:
        return None, "Type a number of credits."
    if n > most:
        return None, "That's more than %s." % credits(most)
    return n, None


def compound(owed, rate, days):
    """What's owed after `days` days at `rate` percent a day (rounded up)."""
    return math.ceil(owed * (1 + rate / 100) ** days - 1e-9)


class Bank:
    def __init__(self, server):
        self.server = server
        self.windows = {}                # session -> BankWindow

    @property
    def db(self):
        return self.server.db

    def settings(self):
        return settings(self.db)

    def sessions_of(self, user_id):
        return [s for s in self.server.sessions if s.user_id == user_id and not s.closed]

    # ---- the balance changes: everything goes through here, so the windows follow ----

    def changed(self, user_id):
        """A balance or loan changed: the user's Bank and My Account windows, and the admins'
        User Editors, show it."""
        for s in self.sessions_of(user_id):
            w = self.windows.get(s)
            if w is not None:
                w.refresh()
            self.server.screens.account.credits_changed(s)
        for ed in list(self.server.screens.admin.users_eds.values()):
            if ed.user_id == user_id:
                ed.credits_changed()

    def earn(self, user_id, reason, other_id=None, memo=""):
        """Pay `reason`'s credits (EARN), if today's allowance isn't used up (and for a win,
        not SAME_OPPONENT_WINS against `other_id` today). Part goes to an open loan. Returns
        the credits paid (0: none)."""
        if user_id is None:
            return 0
        amount, per_day = self.settings()["earn"][reason]
        if amount <= 0 or per_day <= 0:
            return 0
        since = day_start()
        if self.db.credit_events_since(user_id, since, reason) >= per_day:
            return 0
        if (reason == "game won" and other_id is not None and self.db.credit_events_since(
                user_id, since, reason, other_id) >= SAME_OPPONENT_WINS):
            return 0
        if self.db.add_credits(user_id, amount, reason, memo, other_id) is None:
            return 0
        loan = self.loan(user_id)
        if loan is not None:
            share = amount if self.overdue(loan) else \
                math.ceil(amount * self.settings()["repay_share"] / 100)
            if share > 0:
                self.db.repay_loan(loan["id"], share, "to your loan")
        if reason not in QUIET:
            what = dict((r, w) for r, w, _, _ in EARN)[reason].lower()
            for s in self.sessions_of(user_id):
                s.toast("+%s: %s" % (credits(amount), what))
        self.changed(user_id)
        return amount

    def referral(self, referrer_id, new_id, new_name):
        """A new member said `referrer_id` sent them (sign-up's "Referred by"): the referrer
        gets the referral credits (Bank Settings), a private message from MegaNet about it,
        and a toast if signed on. Returns the credits paid."""
        amount = self.settings()["referral"]
        paid = 0
        if amount > 0 and self.db.add_credits(referrer_id, amount, "referral", new_name,
                                              new_id) is not None:
            paid = amount
        lines = ["%s has just joined MegaNet and says you referred them." % new_name]
        if paid:
            lines.append("Thank you! %s have been added to your balance." % credits(paid))
        else:
            lines.append("Thank you for spreading the word!")
        self.db.send_private_message(dbmod.SYSTEM_USER, referrer_id,
                                     "You referred %s" % new_name, lines)
        mail = self.server.screens.mail
        mail.arrived(referrer_id)
        mail.changed(referrer_id)
        for s in self.sessions_of(referrer_id):
            s.toast(("+%s: you referred %s" % (credits(paid), new_name)) if paid
                    else "%s joined: you referred them" % new_name)
        if paid:
            self.changed(referrer_id)
        return paid

    def adjust(self, user_id, new_balance, by):
        """An admin sets a balance (the User Editor). True if it changed."""
        old = self.db.credits(user_id)
        if old is None or new_balance == old:
            return False
        if self.db.add_credits(user_id, new_balance - old, "set by an admin",
                               by_user=by.user_id) is None:
            return False
        by.log("bank: set %s's balance %d -> %d" % (
            self.db.user(user_id=user_id)["name"], old, new_balance))
        self.changed(user_id)
        return True

    # ---- loans ----

    def loan(self, user_id):
        """The user's open loan with today's interest charged (None: no loan)."""
        loan = self.db.open_loan(user_id)
        if loan is None:
            return None
        days = int(time.time() - loan["accrued"]) // 86400
        if days > 0:
            owed = compound(loan["owed"], loan["rate"], days)
            self.db.charge_interest(loan["id"], owed, loan["accrued"] + days * 86400,
                                    owed - loan["owed"])
            loan = self.db.open_loan(user_id)
        return loan

    @staticmethod
    def overdue(loan, now=None):
        return loan is not None and (now or time.time()) > loan["due"]

    def blocked(self, user_id):
        """Why the user can't give credits or play poker now (an overdue loan), or None."""
        loan = self.loan(user_id)
        if self.overdue(loan):
            return "Your loan is overdue: repay it first (Areas > Bank)."
        return None

    def take_loan(self, session, amount):
        """A problem, or None (the credits are in their balance)."""
        st = self.settings()
        if self.loan(session.user_id) is not None:
            return "You have a loan already: repay it first."
        if st["loan_max"] <= 0:
            return "The bank isn't lending at the moment."
        if amount > st["loan_max"]:
            return "The bank lends at most %s." % credits(st["loan_max"])
        if self.db.take_loan(session.user_id, amount, float(st["interest"]),
                             st["loan_days"]) is None:
            return "The bank can't lend you that."
        session.log("bank: loan of %d (%g%% a day, %d days)" % (amount, st["interest"],
                                                               st["loan_days"]))
        self.changed(session.user_id)
        return None

    def repay(self, session, amount):
        loan = self.loan(session.user_id)
        if loan is None:
            return "You have no loan."
        amount = min(amount, loan["owed"])
        if amount > self.db.credits(session.user_id):
            return "You have only %s." % credits(self.db.credits(session.user_id))
        got = self.db.repay_loan(loan["id"], amount)
        if got is None:
            return "That didn't work: try again."
        session.log("bank: repaid %d, %d still owed" % got)
        self.changed(session.user_id)
        return None

    # ---- gifts ----

    def gift(self, session, to_name, amount, note=""):
        """Give `amount` to the user called `to_name`: a problem, or None."""
        to = self.db.user(name=clean_text(to_name).strip())
        if to is None:
            return "There's nobody called %s." % clean_text(to_name).strip()[:12]
        if to["id"] == session.user_id:
            return "You can't give credits to yourself."
        problem = self.blocked(session.user_id)
        if problem:
            return problem
        note = clean_text(note).strip()[:40]
        if self.db.transfer_credits(session.user_id, to["id"], amount, note) is None:
            have = self.db.credits(session.user_id)
            return ("You have only %s." % credits(have) if amount > have
                    else "%s can't hold that many credits." % to["name"])
        session.log("bank: gave %d to %s" % (amount, to["name"]))
        lines = ["%s gave you %s." % (session.user, credits(amount))]
        if note:
            lines += ["", "Their note: %s" % note]
        lines += ["", "See Areas > Bank for your balance."]
        self.db.send_private_message(session.user_id, to["id"],
                                     "A gift of %s" % credits(amount), lines)
        self.server.screens.mail.arrived(to["id"])
        self.server.screens.mail.changed(to["id"])
        for s in self.sessions_of(to["id"]):
            s.toast("%s gave you %s!" % (session.user, credits(amount)))
        self.changed(session.user_id)
        self.changed(to["id"])
        return None

    # ---- an hour signed on (and active) ----

    def check_online(self, now=None):
        now = now or time.time()
        for s in list(self.server.screens.online()):
            if now - s.last_active >= ACTIVE_SECS:
                continue
            s.active_minutes += 1
            if s.active_minutes >= 60:
                s.active_minutes = 0
                self.earn(s.user_id, "hour online")

    async def run(self):
        while True:
            await asyncio.sleep(CHECK_EVERY)
            try:
                self.check_online()
            except Exception:
                log.exception("bank: the online check failed")

    # ---- the windows ----

    def open(self, session):
        if not session.can(USE):
            return refuse(session, TITLE, USE)
        w = self.windows.get(session)
        if w is None or not w.win.shown:
            w = BankWindow(self, session)
        return w.show()

    def permissions_changed(self, session):
        w = self.windows.get(session)
        if w is not None:
            if session.can(USE):
                w.show()                 # (Bank Settings... may come or go)
            else:
                w.close()

    def disconnected(self, session):
        self.windows.pop(session, None)

    def how_to_earn(self, session):
        st = self.settings()
        lines = ["Credits are MegaNet's money: play poker with them, give them to friends, "
                 "or keep them.", "", "You earn them by:"]
        for reason, what, _, _ in EARN:
            amount, per_day = st["earn"][reason]
            if amount and per_day:
                lines.append("  %-24s %s, %d times a day" % (what, credits(amount), per_day))
        if st["referral"]:
            lines.append("  %-24s %s, when they sign up" % ("Referring a new member",
                                                           credits(st["referral"])))
        lines += ["", "Winning pays %d times a day at most against the same person. An hour "
                  "counts only the minutes you're doing something." % SAME_OPPONENT_WINS, ""]
        if st["loan_max"]:
            lines.append("The bank lends up to %s at %g%% a day, for %d days. %d%% of what "
                         "you earn pays it back; once it's overdue, all of it does, and you "
                         "can't give credits or play poker until it's repaid."
                         % (credits(st["loan_max"]), st["interest"], st["loan_days"],
                            st["repay_share"]))
        win = Window.centred("How to Earn Credits", 448, 140,
                             flags=WFlag.CLOSE | WFlag.MOVABLE, minimize=False)
        win.add(TextView(MARGIN, 4, 432, 112, lines))
        add_buttons(win, [("OK", closer, GFlag.DEFAULT)], centre=True)
        win.show(session)
        return win

    def open_settings(self, session):
        if not session.can(ADMIN):
            return refuse(session, "Bank Settings", ADMIN)
        return SettingsWindow(self, session).show()


def statement_row(e):
    """A ledger row in the statement: when, the change, the balance after, what."""
    what = e["reason"]
    if e["other_name"]:
        what += {"gift": " from ", "gift sent": " to ", "referral": " of "}.get(
            e["reason"], " v ") + e["other_name"]
    return "%s %8s %9s  %s" % (time.strftime("%m-%d %H:%M", time.localtime(e["at"])),
                               ("%+d" % e["delta"]) if e["delta"] else "",
                               num(e["balance"]), what)


def statement_about(e):
    lines = [statement_row(e)]
    if e["memo"]:
        lines.append(e["memo"])
    if e["by_name"]:
        lines.append("By %s." % e["by_name"])
    return lines


class BankWindow:
    """Areas > Bank: the balance and loan, the statement, and the commands."""

    ROWS = 100

    def __init__(self, bank, session):
        self.bank = bank
        self.session = session
        self.entries = []

    @property
    def db(self):
        return self.bank.db

    def show(self):
        a = AreaWindow(TITLE, None, on_close=self._closed)
        self.win = a.win
        self.head = a.heading("")
        self.list = a.list([], self._pick, columns="When          Change   Balance  What",
                           about=True, about_h=26)
        self.about = a.about_view
        a.command("Gift Credits...", self._gift, default=True)
        self.loan_b = a.command("Take a Loan...", self._loan)
        self.repay_b = a.command("Repay Loan...", self._repay)
        a.command("How to Earn", lambda b: self.bank.how_to_earn(self.session))
        if self.session.can(ADMIN):
            a.section("Admin Tools")
            a.command("Bank Settings...", lambda b: self.bank.open_settings(self.session))
        self.status = a.status("")
        self.fill(send=False)
        self.bank.windows[self.session] = self
        self.win.show(self.session)
        return self.win

    def close(self):
        self.bank.windows.pop(self.session, None)
        self.win.close()

    def _closed(self, window):
        if self.bank.windows.get(self.session) is self:
            del self.bank.windows[self.session]

    def say(self, text):
        self.status.set_text(text)

    def head_text(self):
        uid = self.session.user_id
        text = "Balance: %s." % credits(self.db.credits(uid) or 0)
        loan = self.bank.loan(uid)
        if loan is not None:
            due = time.strftime("%b %d", time.localtime(loan["due"]))
            text += "  Loan: %s owed, %s %s." % (num(loan["owed"]), "OVERDUE since" if
                                                 self.bank.overdue(loan) else "due", due)
        return text, loan

    def fill(self, send=True):
        text, loan = self.head_text()
        self.entries = list(self.db.credit_log(self.session.user_id, self.ROWS))
        rows = [statement_row(e) for e in self.entries]
        for g, t in ((self.head, text),):
            if send:
                g.set_text(t)
            else:
                g.text = t
        if send:
            self.list.set_rows(rows)
            self.about.set_lines([])
        else:
            self.list.rows = rows
        self.loan_b.enable(loan is None and self.bank.settings()["loan_max"] > 0)
        self.repay_b.enable(loan is not None)

    def refresh(self):
        if self.win.shown:
            self.fill()

    def _ok(self):
        if not self.session.can(USE):
            refuse(self.session, TITLE, USE)
            self.close()
            return False
        return self.bank.windows.get(self.session) is self

    def _pick(self, listbox, index, double):
        if self._ok() and listbox.selected is not None and listbox.selected < len(self.entries):
            self.about.set_lines(statement_about(self.entries[listbox.selected]))

    # ---- Gift Credits ----

    def _gift(self, button, to=""):
        if not self._ok():
            return None
        win = Window.centred("Gift Credits", 336, 80, flags=WFlag.MODAL | WFlag.CLOSE |
                             WFlag.MOVABLE)
        rows = [("To:", 96, to), ("Credits:", 80, ""), ("Note:", 256, "")]
        boxes = []
        for i, (text, w, value) in enumerate(rows):
            win.add(Label(MARGIN, 4 + 14 * i, 64, 10, text))
            boxes.append(win.add(TextBox(72, 2 + 14 * i, w, 12, value)))
        win.to, win.amount, win.note = boxes
        win.msg = win.add(Label(MARGIN, 46, 320, 10, "You have %s." % credits(
            self.db.credits(self.session.user_id) or 0)))
        add_buttons(win, [("Give", self._give, GFlag.DEFAULT), ("Cancel", closer, 0)])
        win.show(self.session)
        return win

    def _give(self, button):
        win = button.window
        if not self._ok():
            return win.close()
        amount, problem = parse_amount(win.amount.value)
        if problem is None:
            problem = self.bank.gift(self.session, win.to.value, amount, win.note.value)
        if problem:
            return win.msg.set_text(problem[:40])
        win.close()
        return self.say("You gave %s to %s." % (credits(amount),
                                                 self.db.canonical_name(win.to.value.strip())))

    # ---- loans ----

    def _loan(self, button):
        if not self._ok():
            return None
        st = self.bank.settings()
        win = Window.centred("Take a Loan", 384, 80, flags=WFlag.MODAL | WFlag.CLOSE |
                             WFlag.MOVABLE)
        for i, line in enumerate(("Borrow up to %s at %g%% a day, for %d days."
                                  % (credits(st["loan_max"]), st["interest"], st["loan_days"]),
                                  "%d%% of what you earn pays it back." % st["repay_share"])):
            win.add(Label(MARGIN, 4 + 11 * i, 368, 10, line))
        win.add(Label(MARGIN, 30, 64, 10, "Credits:"))
        win.amount = win.add(TextBox(72, 28, 80, 12, str(st["loan_max"])))
        win.msg = win.add(Label(MARGIN, 46, 368, 10, ""))
        add_buttons(win, [("Borrow", self._borrow, GFlag.DEFAULT), ("Cancel", closer, 0)])
        win.show(self.session)
        return win

    def _borrow(self, button):
        win = button.window
        if not self._ok():
            return win.close()
        amount, problem = parse_amount(win.amount.value)
        problem = problem or self.bank.take_loan(self.session, amount)
        if problem:
            return win.msg.set_text(problem[:46])
        win.close()
        return self.say("The bank lent you %s." % credits(amount))

    def _repay(self, button):
        if not self._ok():
            return None
        loan = self.bank.loan(self.session.user_id)
        if loan is None:
            return self.say("You have no loan.")
        have = self.db.credits(self.session.user_id) or 0
        win = Window.centred("Repay Loan", 336, 70, flags=WFlag.MODAL | WFlag.CLOSE |
                             WFlag.MOVABLE)
        win.add(Label(MARGIN, 4, 320, 10, "You owe %s; you have %s." % (num(loan["owed"]),
                                                                       num(have))))
        win.add(Label(MARGIN, 20, 64, 10, "Credits:"))
        win.amount = win.add(TextBox(72, 18, 80, 12, str(min(have, loan["owed"]))))
        win.msg = win.add(Label(MARGIN, 34, 320, 10, ""))
        add_buttons(win, [("Repay", self._pay, GFlag.DEFAULT), ("Cancel", closer, 0)])
        win.show(self.session)
        return win

    def _pay(self, button):
        win = button.window
        if not self._ok():
            return win.close()
        amount, problem = parse_amount(win.amount.value)
        problem = problem or self.bank.repay(self.session, amount)
        if problem:
            return win.msg.set_text(problem[:40])
        win.close()
        loan = self.bank.loan(self.session.user_id)
        return self.say("Repaid. You owe %s more." % num(loan["owed"]) if loan
                        else "Your loan is paid off.")


class SettingsWindow:
    """Admin > Bank Settings (admin.bank): what each thing earns, the starting credits and
    the loan terms. The top line says how many credits there are."""

    W, H = 560, 171
    RX = 312                     # the right column

    def __init__(self, bank, session):
        self.bank = bank
        self.session = session

    def show(self):
        st = self.bank.settings()
        win = Window.centred("Bank Settings", self.W, self.H,
                             flags=WFlag.CLOSE | WFlag.MOVABLE, minimize=False)
        held, tables, owed = self.bank.db.credits_total()
        win.add(Label(MARGIN, 2, self.W - 16, 10, "Users hold %s; %s on poker tables; %s "
                      "owed on loans." % (num(held), num(tables), num(owed))))
        win.add(Label(MARGIN, 18, 288, 10, "Earning               Credits  A day",
                      flags=GFlag.BOLD))
        win.earn = {}
        for i, (reason, what, _, _) in enumerate(EARN):
            y = 32 + 14 * i
            win.add(Label(MARGIN, y + 2, 176, 10, what))
            amount, per_day = st["earn"][reason]
            win.earn[reason] = (win.add(TextBox(192, y, 48, 12, str(amount))),
                                win.add(TextBox(248, y, 48, 12, str(per_day))))
        win.add(Label(self.RX, 18, 240, 10, "New accounts and loans", flags=GFlag.BOLD))
        win.other = {}
        for i, (key, (_, _, _, what)) in enumerate(LIMITS.items()):
            y = 32 + 14 * i
            win.add(Label(self.RX, y + 2, 176, 10, what + ":"))
            win.other[key] = win.add(TextBox(self.RX + 184, y, 56, 12, "%g" % st[key]))
        win.msg = win.add(Label(MARGIN, 136, self.W - 16, 10, ""))
        add_buttons(win, [("Save", self._save, GFlag.DEFAULT), ("Cancel", closer, 0)])
        win.show(self.session)
        return win

    def _save(self, button):
        win, session = button.window, button.session
        if not session.can(ADMIN):
            win.close()
            return refuse(session, "Bank Settings", ADMIN)
        out = {"earn": {}}

        def number(box, lo, hi, what, real=False):
            t = clean_text(box.value).strip().replace(",", "")
            try:
                v = float(t) if real else int(t)
            except ValueError:
                v = None
            if v is None or not lo <= v <= hi:
                raise ValueError("%s: %s to %s." % (what, num(lo), num(hi)))
            return v
        try:
            for reason, what, _, _ in EARN:
                a, d = win.earn[reason]
                out["earn"][reason] = [number(a, 0, EARN_MAX, what),
                                       number(d, 0, PER_DAY_MAX, what)]
            for key, (_, lo, hi, what) in LIMITS.items():
                v = number(win.other[key], lo, hi, what, real=key == "interest")
                out[key] = int(v) if float(v).is_integer() else v
        except ValueError as e:
            return win.msg.set_text(str(e))
        self.bank.db.set_bank_settings(out)
        session.log("admin: bank settings saved")
        for w in list(self.bank.windows.values()):
            w.refresh()
        return win.close()
