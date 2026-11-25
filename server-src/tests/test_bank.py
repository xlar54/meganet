"""The Bank (bank.py): balances and the ledger, earning and its limits, gifts, loans with
interest, the Bank window, My Account, the User Editor and Bank Settings."""

import os
import tempfile
import time
import unittest

from meganet import bank as bankmod
from meganet import db as dbmod
from meganet.account import WIN_ACCOUNT
from meganet.protocol import Kind
from meganet.server import Server
from tests.test_pages import PagesBase
from tests.test_roles import gadget_of
from meganet.screens import M_ACCOUNT


def has(win, text):
    """A gadget in `win` shows `text` (in part)."""
    return any(text in (x.get("text") or "") for x in win.gadgets.values())


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.db = dbmod.Database(":memory:")
        self.db.create_user("alice", "x")
        self.db.create_user("bob", "x")
        self.a, self.b = self.db.user("alice")["id"], self.db.user("bob")["id"]

    def test_opening_balance_and_transfers(self):
        self.assertEqual(self.db.credits(self.a), dbmod.DEFAULT_START_CREDITS)
        self.assertEqual(self.db.credit_log(self.a)[0]["reason"], "opening balance")
        self.assertEqual(self.db.transfer_credits(self.a, self.b, 200, "hi"), (300, 700))
        self.assertIsNone(self.db.transfer_credits(self.a, self.b, 301), "not enough")
        self.assertEqual((self.db.credits(self.a), self.db.credits(self.b)), (300, 700))
        e = self.db.credit_log(self.b)[0]
        self.assertEqual((e["reason"], e["delta"], e["other_name"], e["memo"]),
                         ("gift", 200, "alice", "hi"))
        self.assertIsNone(self.db.add_credits(self.a, -301, "x"), "never below 0")
        self.assertEqual(bankmod.statement_row(e)[11:], "     +200       700  gift from alice")

    def test_start_setting(self):
        self.db.set_bank_settings({"start": 50})
        self.db.create_user("carol", "x")
        self.assertEqual(self.db.credits(self.db.user("carol")["id"]), 50)

    def test_loans(self):
        lid = self.db.take_loan(self.a, 1000, 2.0, 14)
        self.assertEqual(self.db.credits(self.a), 1500)
        self.assertIsNone(self.db.take_loan(self.a, 10, 2.0, 14), "one at a time")
        self.assertEqual(self.db.repay_loan(lid, 400), (400, 600))
        self.assertEqual(self.db.repay_loan(lid, 5000), (600, 0), "at most what's owed")
        self.assertIsNone(self.db.open_loan(self.a))
        self.assertEqual(self.db.credits(self.a), 500)

    def test_poker_chips(self):
        self.assertEqual(self.db.to_poker_table(self.a, 200), 300)
        self.assertIsNone(self.db.to_poker_table(self.a, 301))
        self.db.set_poker_chips(self.a, 450)
        self.assertEqual(self.db.credits_total(), (800, 450, 0))
        self.assertEqual(self.db.from_poker_table(self.a), 750)
        self.assertIsNone(self.db.from_poker_table(self.a), "nothing left there")

    def test_old_database_gets_opening_balances(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.db")
            d = dbmod.Database(path)
            d.create_user("old", "x")
            d.conn.execute("UPDATE users SET credits = 0")
            d.conn.execute("DELETE FROM credit_log")
            d.conn.execute("DELETE FROM settings WHERE key = 'credits_seeded'")
            d.conn.commit()
            d.close()
            d = dbmod.Database(path)
            self.assertEqual(d.credits(d.user("old")["id"]), dbmod.DEFAULT_START_CREDITS)
            d.close()

    def test_chips_come_back_after_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.db")
            s = Server(path, tmp)
            s.db.create_user("alice", "x")
            uid = s.db.user("alice")["id"]
            s.db.to_poker_table(uid, 100)
            s.db.set_poker_chips(uid, 130)
            s.serverlog.close()
            s.db.close()
            s = Server(path, tmp)
            self.assertEqual(s.db.credits(uid), 530)
            self.assertEqual(s.db.credit_log(uid)[0]["memo"], "the server restarted")
            s.serverlog.close()
            s.db.close()

    def test_helpers(self):
        self.assertEqual(bankmod.compound(1000, 2, 2), 1041)       # 1040.4, rounded up
        self.assertEqual(bankmod.compound(1000, 0, 5), 1000)
        self.assertEqual(bankmod.parse_amount("1,250"), (1250, None))
        self.assertEqual(bankmod.parse_amount("0")[0], None)
        self.assertEqual(bankmod.parse_amount("-5")[0], None)
        self.assertEqual(bankmod.parse_amount("50", most=10)[1], "That's more than 10 credits.")
        st = bankmod.settings(self.db)
        self.assertEqual(st["earn"]["board post"], [5, 10])
        self.db.set_bank_settings({"earn": {"chat": [3, 4], "poll vote": "junk"}, "start": -1})
        st = bankmod.settings(self.db)
        self.assertEqual((st["earn"]["chat"], st["earn"]["poll vote"], st["start"]),
                         ([3, 4], [5, 10], dbmod.DEFAULT_START_CREDITS))


class BankTest(PagesBase):
    """alice (Sysop) and bob (New User) are signed on."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bank = self.server.screens.bank
        db = self.server.db
        self.a, self.b = db.user("alice")["id"], db.user("bob")["id"]

    def bal(self, uid):
        return self.server.db.credits(uid)

    async def test_earning_and_its_limits(self):
        start = self.bal(self.a)
        for _ in range(12):
            self.bank.earn(self.a, "board post")
        self.assertEqual(self.bal(self.a), start + 5 * 10, "10 a day")
        await self.alice.wait_for(lambda: any("+5 credits: a message board post" in t[2]
                                              for t in self.alice.toasts), "toast")
        # a win: at most SAME_OPPONENT_WINS a day against one person
        paid = [self.bank.earn(self.a, "game won", other_id=self.b) for _ in range(5)]
        self.assertEqual(paid, [20] * bankmod.SAME_OPPONENT_WINS + [0] * 2)
        self.assertEqual(self.bank.earn(self.a, "game won"), 20, "the computer: a new day's")
        # set to 0 in Bank Settings: nothing
        st = self.bank.settings()
        st["earn"]["poll vote"] = [0, 10]
        self.server.db.set_bank_settings(st)
        self.assertEqual(self.bank.earn(self.a, "poll vote"), 0)

    async def test_an_hour_online(self):
        s = next(x for x in self.server.sessions if x.user == "bob")
        start = self.bal(self.b)
        s.active_minutes = 58
        self.bank.check_online()
        self.assertEqual((s.active_minutes, self.bal(self.b)), (59, start))
        s.last_active = time.time() - bankmod.ACTIVE_SECS - 1       # idle: doesn't count
        self.bank.check_online()
        self.assertEqual(s.active_minutes, 59)
        s.last_active = time.time()
        self.bank.check_online()
        self.assertEqual((s.active_minutes, self.bal(self.b)), (0, start + 10))

    async def test_chat_lines(self):
        start = self.bal(self.b)
        room = await self.bob.enter_room("Lobby")
        box = gadget_of(room, Kind.TEXTBOX)
        for text in ("hello everyone", "hello everyone", "hi", "how are you all?"):
            self.bob.value(room.id, box, text)
            self.bob.click_text(room.id, "Send")
        await self.bob.wait_for(lambda: self.bal(self.b) == start + 2, "two new lines paid")
        await self.roundtrip(self.bob)
        self.assertEqual(self.bal(self.b), start + 2, "not the repeat, not 'hi'")

    async def test_loans_interest_and_overdue(self):
        db = self.server.db
        s = next(x for x in self.server.sessions if x.user == "alice")
        self.assertIsNone(self.bank.take_loan(s, 1000))
        self.assertEqual(self.bank.take_loan(s, 10), "You have a loan already: repay it first.")
        # half of what's earned goes to the loan
        self.bank.earn(self.a, "board post")
        loan = self.bank.loan(self.a)
        self.assertEqual((loan["owed"], self.bal(self.a)), (997, 1500 + 5 - 3))
        # interest: two days later
        db.conn.execute("UPDATE loans SET accrued = accrued - 2 * 86400")
        db.conn.commit()
        self.assertEqual(self.bank.loan(self.a)["owed"], bankmod.compound(997, 2, 2))
        self.assertEqual(db.credit_log(self.a)[0]["reason"], "loan interest")
        # overdue: no gifts, and everything earned goes to the loan
        db.conn.execute("UPDATE loans SET due = ?", (int(time.time()) - 10,))
        db.conn.commit()
        self.assertEqual(self.bank.gift(s, "bob", 10), "Your loan is overdue: repay it first "
                                                         "(Areas > Bank).")
        before = self.bal(self.a)
        self.bank.earn(self.a, "board post")
        self.assertEqual(self.bal(self.a), before)
        self.assertIsNone(self.bank.repay(s, 5000))
        self.assertIsNone(self.bank.loan(self.a))
        self.assertIsNone(self.bank.gift(s, "bob", 10))

    async def test_bank_window_gift_and_my_account(self):
        a, b = self.alice, self.bob
        b.pick_id(M_ACCOUNT)
        acct = await b.wait_window("My Account")
        self.assertTrue(any(x["text"] == " Credits: 500" for x in acct.gadgets.values()))
        a.pick("Bank")
        w = await a.wait_window("Bank")
        self.assertTrue(has(w, "Balance: 500 credits."))
        a.click_text(w.id, "Gift Credits...")
        d = await a.wait_window("Gift Credits")
        to, amount, note = (gadget_of(d, Kind.TEXTBOX, i) for i in range(3))
        a.value(d.id, to, "bob")
        a.value(d.id, amount, "600")
        a.click_text(d.id, "Give")
        await a.wait_for(lambda: has(d, "You have only 500 credits."), "refused")
        a.value(d.id, amount, "150")
        a.value(d.id, note, "for the coffee")
        a.click_text(d.id, "Give")
        await a.wait_for(lambda: has(w, "You gave 150 credits to bob."), "given")
        await a.wait_for(lambda: has(w, "Balance: 350 credits."), "the balance follows")
        rows = w.gadgets[gadget_of(w, Kind.LISTBOX)]["rows"]
        self.assertTrue(rows[0].endswith("-150       350  gift sent to bob"), rows[0])
        # bob: a toast, a private message, and My Account follows
        await b.wait_for(lambda: any("alice gave you 150 credits!" in t[2] for t in b.toasts),
                         "toast")
        await b.wait_for(lambda: any(x["text"] == " Credits: 650"
                                     for x in acct.gadgets.values()), "My Account follows")
        msg = self.server.db.inbox(self.b)[0]
        self.assertEqual(msg["subject"], "A gift of 150 credits")
        self.assertIn("Their note: for the coffee", msg["body"])

    async def test_take_and_repay_in_the_window(self):
        a = self.alice
        a.pick("Bank")
        w = await a.wait_window("Bank")
        self.assertFalse(a.enabled(w.id, "Repay Loan..."))
        a.click_text(w.id, "Take a Loan...")
        d = await a.wait_window("Take a Loan")
        a.value(d.id, gadget_of(d, Kind.TEXTBOX), "2000")
        a.click_text(d.id, "Borrow")
        await a.wait_for(lambda: has(d, "The bank lends at most 1,000"), "too much")
        a.value(d.id, gadget_of(d, Kind.TEXTBOX), "300")
        a.click_text(d.id, "Borrow")
        await a.wait_for(lambda: has(w, "The bank lent you 300 credits."), "lent")
        await a.wait_for(lambda: has(w, "Loan: 300 owed, due"), "the heading")
        await a.wait_for(lambda: a.enabled(w.id, "Repay Loan..."), "repay now")
        a.click_text(w.id, "Repay Loan...")
        d = await a.wait_window("Repay Loan")
        a.click_text(d.id, "Repay")
        await a.wait_for(lambda: has(w, "Your loan is paid off."), "repaid")

    async def test_admin(self):
        a = self.alice
        a.pick("Bank Settings...")
        w = await a.wait_window("Bank Settings")
        self.assertTrue(has(w, "Users hold 1,000; 0 on poker tables; 0 owed on loans."))
        boxes = [g for g, x in sorted(w.gadgets.items()) if x["kind"] == Kind.TEXTBOX]
        a.value(w.id, boxes[0], "lots")
        a.click_text(w.id, "Save")
        await a.wait_for(lambda: has(w, "Playing a game: 0 to 1,000."), "refused")
        a.value(w.id, boxes[0], "7")
        a.value(w.id, boxes[-6], "250")                      # Starting credits
        a.value(w.id, boxes[-4], "1.5")                      # interest
        a.value(w.id, boxes[-1], "75")                       # credits for a referral
        a.click_text(w.id, "Save")
        await a.wait_for(lambda: w.id not in a.windows, "saved")
        st = self.bank.settings()
        self.assertEqual((st["earn"]["game played"], st["start"], st["interest"],
                          st["referral"]), ([7, 20], 250, 1.5, 75))
        # the User Editor sets a balance, and History has the statement
        a.pick("User Editor...")
        ed = await a.wait_window("User Editor")
        lst = gadget_of(ed, Kind.LISTBOX)
        await a.wait_for(lambda: ed.gadgets[lst].get("rows"), "users")
        a.select(ed.id, lst, [r.split()[0] for r in ed.gadgets[lst]["rows"]].index("bob"))
        box = gadget_of(ed, Kind.TEXTBOX, 6)
        await a.wait_for(lambda: ed.text(box) == "500", "bob's credits")
        a.value(ed.id, box, "1234")
        a.click_text(ed.id, "Save")
        await a.wait_for(lambda: self.bal(self.b) == 1234, "set")
        e = self.server.db.credit_log(self.b)[0]
        self.assertEqual((e["reason"], e["delta"], e["by_name"]), ("set by an admin", 734,
                                                                    "alice"))
        a.click_text(ed.id, "History")
        h = await a.wait_window("History")
        lines = h.gadgets[gadget_of(h, Kind.TEXTVIEW)]["lines"]
        self.assertIn("Bank: 1,234 credits", lines)
        self.assertTrue(any(line.endswith("set by an admin") for line in lines))

    async def test_games_pay(self):
        """Game.credit: a played game and a win (chess, One and Tic-Tac-Toe call it)."""
        from meganet.games.base import Game
        g = Game()
        g.name = "Test"
        sa = next(x for x in self.server.sessions if x.user == "alice")
        sb = next(x for x in self.server.sessions if x.user == "bob")
        self.assertEqual(g.credit(sa, "game played"), 5)
        self.assertEqual(g.credit(sa, "game won", beat=sb), 20)
        e = self.server.db.credit_log(self.a)[0]
        self.assertEqual((e["reason"], e["other_name"], e["memo"]), ("game won", "bob", "Test"))
