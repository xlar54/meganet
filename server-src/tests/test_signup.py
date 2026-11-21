"""The New User sign-up wizard (signup.py): LOGIN with the new-user flag and no name opens it;
six steps with Back / Next / Cancel, checks on Next and at OK, the review, the Terms of
Service (a box to tick before OK works), the account and
profile saved, the admins told, the welcome alert in front; Cancel and the close box give
LOGIN_RESULT 0 and the connection stays usable; only the wizard's window works before sign-on;
names held by a running wizard."""

import datetime

from meganet import db, ui
from meganet.account import WIN_ACCOUNT
from meganet.pages import WIN_ADMIN_MSGS
from meganet.protocol import S, C, Kind, WFlag, GFlag, Icon, Writer, SLOT_ADMIN_MAIL, \
    MENU_MY_ACCOUNT, window_fits
from meganet.screens import WIN_WELCOME
from meganet.signup import (WIN_SIGNUP, W, H, CANCELLED, TAKEN, BUSY, MISMATCH, WELCOME_TITLE,
                            ADMIN_SUBJECT, NOT_GIVEN, WIN_SET_UP, set_up_lines)
from tests.test_pages import PagesBase
from tests.test_roles import gadget_of, has_text, status_of
from tests.test_server import ServerTest

PARTIAL = "Birthdate: set month, day and year, or all --."
NAME_RULE = "Screen names are 3-10 letters, digits or spaces."


class WizardMixin:
    async def fresh(self, name="newbie"):
        """A connection that has said HELLO, not signed on."""
        c = await self.client(name)
        c.send_hello()
        await c.wait_for(lambda: c.hello, "HELLO")
        return c

    async def start(self, c=None):
        c = c or await self.fresh()
        c.send_login("", "", new=True)
        await self.at(c, 1)
        return c

    async def at(self, c, step):
        await c.wait_for(lambda: has_text(c, WIN_SIGNUP, "Step %d of 6" % step),
                         "step %d" % step)
        return c.windows[WIN_SIGNUP]

    async def press(self, c, label):
        """Click a wizard button. Returns the status text if the same step stays (a problem),
        or None once the next window is drawn."""
        win = c.windows[WIN_SIGNUP]
        win.gadgets[gadget_of(win, Kind.LABEL, -1)]["text"] = "-"
        c.click_text(WIN_SIGNUP, label)

        def done():
            now = c.windows.get(WIN_SIGNUP)
            if now is win:
                return status_of(win) != "-"
            return now is not None and now.done
        await c.wait_for(done, "%s answered" % label)
        return status_of(win) if c.windows.get(WIN_SIGNUP) is win else None

    def fill1(self, c, name, first="Pat", last="Smith"):
        win = c.windows[WIN_SIGNUP]
        for i, text in enumerate((name, first, last)):
            c.value(WIN_SIGNUP, gadget_of(win, Kind.TEXTBOX, i), text)

    def fill2(self, c, pw, confirm=None):
        win = c.windows[WIN_SIGNUP]
        c.value(WIN_SIGNUP, gadget_of(win, Kind.PASSWORD, 0), pw)
        c.value(WIN_SIGNUP, gadget_of(win, Kind.PASSWORD, 1), pw if confirm is None else confirm)

    def fill3(self, c, date=("--", "--", "--"), location="", email=""):
        win = c.windows[WIN_SIGNUP]
        for i, row in enumerate(date):
            gid = gadget_of(win, Kind.DROPDOWN, i)
            c.pick_dropdown(WIN_SIGNUP, gid, win.gadgets[gid]["rows"].index(row))
        c.value(WIN_SIGNUP, gadget_of(win, Kind.TEXTBOX, 0), location)
        c.value(WIN_SIGNUP, gadget_of(win, Kind.TEXTBOX, 1), email)

    def fill4(self, c, lines):
        win = c.windows[WIN_SIGNUP]
        c.text(WIN_SIGNUP, gadget_of(win, Kind.EDIT), lines)

    async def to_review(self, c, name, pw="pass1", date=("--", "--", "--"), location="",
                        email="", about=()):
        self.fill1(c, name)
        self.assertIsNone(await self.press(c, "Next"))
        await self.at(c, 2)
        self.fill2(c, pw)
        self.assertIsNone(await self.press(c, "Next"))
        await self.at(c, 3)
        self.fill3(c, date, location, email)
        self.assertIsNone(await self.press(c, "Next"))
        await self.at(c, 4)
        self.fill4(c, about)
        self.assertIsNone(await self.press(c, "Next"))
        return await self.at(c, 5)

    async def to_terms(self, c):
        """From the review (step 5) to the Terms of Service, the box ticked."""
        self.assertIsNone(await self.press(c, "Next"))
        win = await self.at(c, 6)
        c.select(WIN_SIGNUP, gadget_of(win, Kind.CHECKBOX), 1)
        await c.wait_for(lambda: c.enabled(WIN_SIGNUP, "OK"), "OK enabled")
        return win

    async def accept(self, c):
        """From the review: Next, tick the Terms of Service, OK -> the LOGIN_RESULT."""
        await self.to_terms(c)
        n = len(c.login_results)
        c.click_text(WIN_SIGNUP, "OK")
        await c.wait_for(lambda: len(c.login_results) > n, "LOGIN_RESULT")
        return c.login_results[-1]

    async def cancelled(self, c, n):
        await c.wait_for(lambda: len(c.login_results) > n, "LOGIN_RESULT")
        self.assertEqual(c.login_results[-1], (False, CANCELLED))
        await c.wait_for(lambda: WIN_SIGNUP not in c.windows, "wizard closed")

    def values(self, win):
        """Every label's text, in order."""
        return [g["text"] for _gid, g in sorted(win.gadgets.items()) if g["kind"] == Kind.LABEL]

    def check_layout(self, win, step):
        self.assertEqual(win.size, (W, H))
        self.assertEqual(win.pos, ui.centre(W, H))
        self.assertTrue(window_fits(*win.pos, W, H))
        self.assertTrue(win.flags & WFlag.MODAL and win.flags & WFlag.CLOSE)
        self.assertEqual(self.values(win)[0], "Step %d of 6" % step)
        g = win.gadgets
        labels = [b for b in ("Back", "Next", "OK", "Cancel") if
                  any(x["text"] == b and x["kind"] == Kind.BUTTON for x in g.values())]
        self.assertEqual(labels, (["Back"] if step > 1 else []) +
                         (["OK"] if step == 6 else ["Next"]) + ["Cancel"])
        default = [x["text"] for x in g.values() if x["kind"] == Kind.BUTTON
                   and x["flags"] & GFlag.DEFAULT]
        self.assertEqual(default, ["OK" if step == 6 else "Next"])
        boxes = [g[win.find(b)]["box"] for b in labels]
        self.assertEqual(len({b[1] for b in boxes}), 1, "one row of buttons")
        self.assertEqual(boxes[-1][0] + boxes[-1][2], W - 4, "right-aligned")
        status = g[gadget_of(win, Kind.LABEL, -1)]["box"]
        self.assertLessEqual(status[1] + status[3], boxes[0][1], "status above the buttons")
        for x in g.values():                 # text fits its label
            if x["kind"] == Kind.LABEL:
                self.assertLessEqual(len(x["text"]) * 8, x["box"][2], x["text"])


class SignupTest(WizardMixin, PagesBase):
    """alice (Sysop, an admin) and bob (New User) are signed on."""

    async def test_happy_path(self):
        alice, bob = self.alice, self.bob
        c = await self.fresh("carl")
        c.send_login("", "", new=True)
        win = await self.at(c, 1)
        self.check_layout(win, 1)
        self.assertEqual(win.title, "New User: Screen Name")
        self.assertIn("Choose a screen name: 3-10 letters, digits or spaces.", self.values(win))
        self.assertEqual(c.login_results, [], "no LOGIN_RESULT while the wizard runs")
        self.assertEqual(c.menu, [])
        self.assertEqual([g["box"][1] for g in win.gadgets.values()
                          if g["kind"] == Kind.TEXTBOX], [62, 77, 92], "name, first, last")
        for first, last, problem in (("", "Jones", "Please type your first name."),
                                     ("Carl", "", "Please type your last name."),
                                     ("C4rl", "Jones", "Names hold letters, spaces, ' - and . only."),
                                     ("Carl", "J" * 21, "Names hold at most 20 characters.")):
            self.fill1(c, "Carl", first, last)
            self.assertEqual(await self.press(c, "Next"), problem, (first, last))
        self.fill1(c, "Carl", " Carl ", "O'Brien-Jones")
        self.assertIsNone(await self.press(c, "Next"))

        win = await self.at(c, 2)
        self.check_layout(win, 2)
        self.assertIn("Passwords need at least 4 characters. Type it twice.", self.values(win))
        self.assertEqual(sum(g["kind"] == Kind.PASSWORD for g in win.gadgets.values()), 2)
        self.fill2(c, "pass1")
        self.assertIsNone(await self.press(c, "Next"))

        win = await self.at(c, 3)
        self.check_layout(win, 3)
        self.assertTrue(any("optional" in t for t in self.values(win)))
        self.assertTrue(any("My Account" in t for t in self.values(win)))
        this_year = datetime.date.today().year
        years = win.gadgets[gadget_of(win, Kind.DROPDOWN, 2)]["rows"]
        self.assertEqual(years[:2], ["--", str(this_year)])
        self.fill3(c, ("Jun", "21", "1985"), "Melbourne", "carl@example.com")
        self.assertIsNone(await self.press(c, "Next"))

        win = await self.at(c, 4)
        self.check_layout(win, 4)
        edit = win.gadgets[gadget_of(win, Kind.EDIT)]
        self.assertEqual((edit["box"][2] - 17) // 8, 30, "My Account's line width")
        self.assertGreaterEqual((edit["box"][3] - 6) // 8, db.ABOUT_LINES)
        about = ["Hi, I'm Carl.", "I like SID music", "and demos."]
        self.fill4(c, about)
        self.assertIsNone(await self.press(c, "Next"))

        win = await self.at(c, 5)
        self.check_layout(win, 5)
        shown = self.values(win)
        for text in ("Carl", "Carl O'Brien-Jones", "*****", "21 Jun 1985", "Melbourne", "carl@example.com",
                     "Hi, I'm Carl.", "I like SID music ..."):
            self.assertIn(text, shown)
        self.assertEqual(self.server.db.user("Carl"), None, "nothing saved before Accept")

        self.assertEqual(await self.accept(c), (True, "Welcome to MegaNet, Carl!"))
        # "your account is set up" first, alone: the welcome window only after its OK
        setup = await c.wait_window(WELCOME_TITLE)
        self.assertEqual(setup.id, WIN_SET_UP)
        for line in set_up_lines("Carl", False):
            setup.find(line)
        self.assertNotIn("Welcome, Carl", [w.title for w in c.windows.values()])
        self.assertNotIn(WIN_SIGNUP, c.windows)
        self.assertIn("Areas", c.menu_titles())
        self.assertLess(c.messages.index(S.LOGIN_RESULT), c.messages.index(S.MENU))
        c.click_text(WIN_SET_UP, "OK")
        await c.wait_window("Welcome, Carl")
        self.assertNotIn(WIN_SET_UP, c.windows)
        self.assertEqual(c.alerts, [])

        u = self.server.db.user("carl")
        self.assertEqual((u["name"], u["role"], u["first_name"], u["last_name"], u["email"],
                          u["location"], u["birthdate"], u["about"]),
                         ("Carl", "New User", "Carl", "O'Brien-Jones", "carl@example.com",
                          "Melbourne", "1985-06-21", "\n".join(about)))
        self.assertTrue(db.verify_password("pass1", self.server.db.password_hash("carl")))
        self.assertIsNotNone(self.server.find_user("Carl"))

        # The admins are told: the message, and alice's envelope icon (not bob's).
        msgs = self.server.db.admin_messages()
        self.assertEqual([(x["name"], x["subject"]) for x in msgs], [("Carl", ADMIN_SUBJECT)])
        self.assertEqual(msgs[0]["text"],
                         "Carl has just signed up. Please check their access (Admin > User Editor).")
        await alice.wait_for(lambda: alice.icon(SLOT_ADMIN_MAIL) == Icon.MAIL, "envelope")
        self.assertEqual(alice.hint(SLOT_ADMIN_MAIL), "1 message from users")
        self.assertEqual(bob.icon(SLOT_ADMIN_MAIL), Icon.NONE)
        self.assertEqual(c.icon(SLOT_ADMIN_MAIL), Icon.NONE)
        alice.notify_click(SLOT_ADMIN_MAIL)
        msgs_win = await alice.wait_window("Messages from users")
        rows = msgs_win.gadgets[gadget_of(msgs_win, Kind.LISTBOX)]["rows"]
        self.assertTrue(rows[0].startswith("Carl       New user"), rows)
        self.assertEqual(msgs_win.id, WIN_ADMIN_MSGS)

        # A signed-on wizard user can't start another one.
        n = len(c.login_results)
        c.send_login("", "", new=True)
        await c.wait_for(lambda: len(c.login_results) > n, "refused")
        self.assertEqual(c.login_results[-1], (False, "You are already signed on."))

    async def test_nothing_optional_given(self):
        c = await self.start()
        win = await self.to_review(c, "Dana")
        shown = self.values(win)
        self.assertEqual(shown.count(NOT_GIVEN), 4, shown)          # date, place, email, about
        self.assertEqual((await self.accept(c))[0], True)
        u = self.server.db.user("Dana")
        self.assertEqual((u["email"], u["location"], u["birthdate"], u["about"]), ("",) * 4)

    async def test_bad_and_taken_names(self):
        c = await self.start()
        for name, problem in (("alice", TAKEN), ("ALICE", TAKEN), ("Bob", TAKEN),
                              ("ab", NAME_RULE), ("a!b", NAME_RULE), ("x" * 11, NAME_RULE),
                              ("", NAME_RULE),
                              ("a  b", "No leading, trailing or double spaces in screen names.")):
            self.fill1(c, name)
            self.assertEqual(await self.press(c, "Next"), problem, name)
            self.assertLessEqual(len(problem), 55, "fits the status line")
        self.fill1(c, "  Erin 64 ")                    # (outer spaces are trimmed)
        self.assertIsNone(await self.press(c, "Next"))
        await self.at(c, 2)
        await self.to_review_from_2(c)
        self.assertEqual(await self.accept(c), (True, "Welcome to MegaNet, Erin 64!"))

    async def to_review_from_2(self, c):
        self.fill2(c, "pass1")
        self.assertIsNone(await self.press(c, "Next"))
        await self.at(c, 3)
        self.assertIsNone(await self.press(c, "Next"))
        await self.at(c, 4)
        self.assertIsNone(await self.press(c, "Next"))
        return await self.at(c, 5)

    async def test_passwords(self):
        c = await self.start()
        self.fill1(c, "Fay")
        await self.press(c, "Next")
        await self.at(c, 2)
        for pw, confirm, problem in (("abc", "abc", "Passwords need at least 4 characters."),
                                     ("", "", "Passwords need at least 4 characters."),
                                     ("pass1", "pass2", MISMATCH), ("pass1", "", MISMATCH)):
            self.fill2(c, pw, confirm)
            self.assertEqual(await self.press(c, "Next"), problem)
        self.fill2(c, "good pass")
        self.assertIsNone(await self.press(c, "Next"))
        await self.at(c, 3)

    async def test_invalid_profile(self):
        c = await self.start()
        self.fill1(c, "Gus")
        await self.press(c, "Next")
        await self.at(c, 2)
        self.fill2(c, "pass1")
        await self.press(c, "Next")
        await self.at(c, 3)
        for kw, problem in ((dict(date=("Feb", "30", "1985")), "Birthdate: Feb 1985 has no day 30."),
                            (dict(date=("Jun", "--", "1985")), PARTIAL),
                            (dict(email="gus@"), "That email address doesn't look right."),
                            (dict(location="x" * 64), "Email and Location hold at most 63 characters.")):
            self.fill3(c, **kw)
            self.assertEqual(await self.press(c, "Next"), problem, kw)
        self.fill3(c, ("Feb", "29", "2000"))
        self.assertIsNone(await self.press(c, "Next"))
        await self.at(c, 4)
        self.fill4(c, ["line %d" % i for i in range(9)])
        self.assertEqual(await self.press(c, "Next"), "About Me has 9 lines: it holds at most 8.")
        self.fill4(c, ["line %d" % i for i in range(8)])
        self.assertIsNone(await self.press(c, "Next"))
        win = await self.at(c, 5)
        self.assertIn("29 Feb 2000", self.values(win))
        self.assertIn("line 1 ...", self.values(win))

    async def test_back_keeps_values(self):
        c = await self.start()
        about = ["Hello there.", "Second line."]
        await self.to_review(c, "Hal", "secret1", ("Mar", "4", "1965"), "Perth", "hal@x.org",
                             about)
        self.assertIsNone(await self.press(c, "Back"))
        win = await self.at(c, 4)
        self.assertEqual(win.gadgets[gadget_of(win, Kind.EDIT)]["lines"], about)
        self.assertIsNone(await self.press(c, "Back"))
        win = await self.at(c, 3)
        g = win.gadgets
        self.assertEqual([g[gadget_of(win, Kind.DROPDOWN, i)]["rows"][
            g[gadget_of(win, Kind.DROPDOWN, i)]["value"]] for i in range(3)], ["Mar", "4", "1965"])
        self.assertEqual([win.text(gadget_of(win, Kind.TEXTBOX, i)) for i in range(2)],
                         ["Perth", "hal@x.org"])
        self.assertIsNone(await self.press(c, "Back"))
        win = await self.at(c, 2)
        self.assertEqual([win.text(gadget_of(win, Kind.PASSWORD, i)) for i in range(2)],
                         ["secret1", "secret1"])
        self.assertIsNone(await self.press(c, "Back"))
        win = await self.at(c, 1)
        self.assertEqual([win.text(gadget_of(win, Kind.TEXTBOX, i)) for i in range(3)],
                         ["Hal", "Pat", "Smith"])
        # Back from step 3 without checking: a bad date is kept, and stops Accept.
        for _ in range(2):
            self.assertIsNone(await self.press(c, "Next"))
        await self.at(c, 3)
        self.fill3(c, ("Apr", "31", "1999"), "Perth", "hal@x.org")
        self.assertIsNone(await self.press(c, "Back"))
        await self.at(c, 2)
        self.assertIsNone(await self.press(c, "Next"))
        win = await self.at(c, 3)
        self.assertEqual(self.values(win)[-1], "", "no complaint yet")
        self.assertEqual(await self.press(c, "Next"), "Birthdate: Apr 1999 has no day 31.")
        self.fill3(c, ("Apr", "30", "1999"), "Perth", "hal@x.org")
        self.assertIsNone(await self.press(c, "Next"))
        await self.at(c, 4)
        self.assertIsNone(await self.press(c, "Next"))     # the About Me kept from before
        win = await self.at(c, 5)
        self.assertIn("Second line.", self.values(win))
        self.assertEqual((await self.accept(c))[0], True)
        u = self.server.db.user("Hal")
        self.assertEqual((u["birthdate"], u["about"]), ("1999-04-30", "\n".join(about)))

    async def test_cancel_then_sign_on(self):
        bob = self.bob
        c = await self.start()
        n = len(c.login_results)
        c.click_text(WIN_SIGNUP, "Cancel")
        await self.cancelled(c, n)
        self.assertEqual(c.menu, [])
        # Again on the same connection, cancelled at step 4 this time.
        await self.start(c)
        await self.to_review(c, "Ivy")
        self.assertIsNone(await self.press(c, "Back"))
        await self.at(c, 4)
        n = len(c.login_results)
        c.click_text(WIN_SIGNUP, "Cancel")
        await self.cancelled(c, n)
        self.assertIsNone(self.server.db.user("Ivy"), "no account")
        self.assertIsNone(self.server.find_user("Ivy"))
        self.assertEqual(self.server.db.admin_messages(), [])
        # A normal sign-on on the same connection works.
        await self.sign_off(bob)
        ok, msg = await self.login(c, "bob", "secret")
        self.assertTrue(ok, msg)
        await c.wait_window("Welcome, bob")
        self.assertIn("Areas", c.menu_titles())

    async def test_close_box_cancels(self):
        c = await self.start()
        self.fill1(c, "Jo")
        self.assertEqual(await self.press(c, "Next"), NAME_RULE)
        self.fill1(c, "Joe")
        await self.press(c, "Next")
        await self.at(c, 2)
        n = len(c.login_results)
        c.close_box(WIN_SIGNUP)
        await self.cancelled(c, n)
        # The name is free again, and the old LOGIN still creates accounts at once.
        ok, msg = await self.login(c, "Joe", "pass1", new=True)
        self.assertTrue(ok, msg)
        await c.wait_window("Welcome, Joe")

    async def test_forged_events_before_sign_on(self):
        c = await self.fresh()
        # No wizard yet: nothing is handled, not even for the wizard's id.
        c.click(WIN_WELCOME, 1)
        c.click(WIN_SIGNUP, 1)
        c.send(C.WIN_CLOSED, Writer().u8(WIN_SIGNUP))
        c.pick_id(MENU_MY_ACCOUNT)
        await self.start(c)
        self.assertEqual(list(c.windows), [WIN_SIGNUP])
        # With the wizard open: other windows, menu picks, icons and keys are still refused.
        c.click(WIN_ACCOUNT, 1)
        c.value(WIN_ACCOUNT, 1, "x")
        c.select(WIN_WELCOME, 1, 0)
        c.send(C.WIN_CLOSED, Writer().u8(WIN_WELCOME))
        c.send(C.TEXT, Writer().u8(WIN_ACCOUNT).u8(1).u8(0))
        c.pick_id(MENU_MY_ACCOUNT)
        c.notify_click(SLOT_ADMIN_MAIL)
        c.send(C.KEY, Writer().u8(WIN_SIGNUP).u8(1).u8(65))
        c.send(C.LIST_NEED, Writer().u8(WIN_SIGNUP).u8(1).u16(0).u8(5))
        self.fill1(c, "")
        self.assertEqual(await self.press(c, "Next"), NAME_RULE, "the wizard still works")
        self.assertEqual(list(c.windows), [WIN_SIGNUP])
        self.assertEqual((c.alerts, c.login_results, c.menu), ([], [], []))
        session = next(s for s in self.server.sessions if s.signup is not None)
        self.assertIsNone(session.user)

    async def test_two_sessions_race_for_a_name(self):
        a = await self.start(await self.fresh("a"))
        b = await self.start(await self.fresh("b"))
        self.fill1(a, "Kim")
        self.assertIsNone(await self.press(a, "Next"))
        self.fill1(b, "KIM")
        self.assertEqual(await self.press(b, "Next"), BUSY)
        # An old-style new-user LOGIN can't take it either.
        c = await self.fresh("c")
        ok, msg = await self.login(c, "kim", "pass1", new=True)
        self.assertEqual((ok, msg), (False, "The name kim is taken."))
        # a changes its mind (Back, another name): Kim is free for b.
        await self.at(a, 2)
        self.assertIsNone(await self.press(a, "Back"))
        await self.at(a, 1)
        self.fill1(a, "Lee")
        self.assertIsNone(await self.press(a, "Next"))
        self.fill1(b, "Kim")
        self.assertIsNone(await self.press(b, "Next"))
        await self.at(b, 2)
        await self.to_review_from_2(b)
        self.assertEqual((await self.accept(b))[0], True)
        # If the name went while a was on the Terms (here: forced), OK goes back to step 1.
        await self.at(a, 2)
        await self.to_review_from_2(a)
        await self.to_terms(a)
        session_a = next(s for s in self.server.sessions if s.signup is not None)
        session_a.signup.name = "Kim"
        session_a.signup.typed_name = "Kim"
        a.click_text(WIN_SIGNUP, "OK")
        win = await self.at(a, 1)
        await a.wait_for(lambda: status_of(a.windows[WIN_SIGNUP]) == TAKEN, "taken")
        self.assertEqual(a.login_results, [])
        self.assertEqual(self.server.db.user_count(), 3)

    async def test_wizard_needs_hello(self):
        c = await self.client("nohello")
        ok, msg = await self.login(c, "", "", new=True)
        self.assertEqual((ok, msg), (False, "Say HELLO first."))
        self.assertNotIn(WIN_SIGNUP, c.windows)


class FirstUserTest(WizardMixin, ServerTest):
    async def test_first_account_is_sysop(self):
        c = await self.start()
        await self.to_review(c, "Root")
        self.assertEqual(await self.accept(c), (True, "Welcome to MegaNet, Root!"))
        setup = await c.wait_window(WELCOME_TITLE)
        setup.find("As the very first member, you are the Sysop.")
        setup.done = False                              # the close box works like OK
        c.close_box(WIN_SET_UP)
        await c.wait_window("Welcome, Root")
        self.assertEqual(self.server.db.user("Root")["role"], "Sysop")
        self.assertEqual(self.server.db.admin_messages(), [], "no one else to tell")
        self.assertIn("Admin", c.menu_titles())
        self.assertEqual(c.icon(SLOT_ADMIN_MAIL), Icon.NONE)


if __name__ == "__main__":
    import unittest
    unittest.main()
