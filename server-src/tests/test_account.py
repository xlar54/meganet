"""My Account: opened by the client's own menu (MENU_PICK $22), the layout, saving and
re-loading each field (text boxes, the birthdate drop-downs, the About Me EDIT area),
validation, OK / Cancel, Last Login, and Reset Password."""

import datetime
import types

from meganet import db, ui
from meganet.account import (Account, WIN_ACCOUNT, WIN_PASSWORD, W, H, FIELD_X, FIELD_W,
                             LABEL_X, FIRST_YEAR, MONTHS, when)
from meganet.protocol import Kind, MENU_MY_ACCOUNT, CLIENT_MAX_H, window_fits
from tests.test_pages import PagesBase
from tests.test_roles import gadget_of, has_text

PARTIAL = "Birthdate: set month, day and year, or all --."


class AccountTest(PagesBase):
    async def open(self, c):
        c.windows.pop(WIN_ACCOUNT, None)
        c.pick_id(MENU_MY_ACCOUNT)
        return await c.wait_window("My Account")

    def boxes(self, win):
        """email, location"""
        return [gadget_of(win, Kind.TEXTBOX, i) for i in (2, 3)]

    def names(self, win):
        """first, last"""
        return [gadget_of(win, Kind.TEXTBOX, i) for i in (0, 1)]

    def dropdowns(self, win):
        """month, day, year"""
        return [gadget_of(win, Kind.DROPDOWN, i) for i in range(3)]

    def status(self, c):
        win = c.windows[WIN_ACCOUNT]
        return win.text(gadget_of(win, Kind.LABEL, -1))

    def shown(self, win):
        """What the window shows: [email, location, (month, day, year), about lines]."""
        g = win.gadgets
        date = tuple(g[i]["rows"][g[i]["value"]] for i in self.dropdowns(win))
        return [win.text(i) for i in self.boxes(win)] + [
            date, g[gadget_of(win, Kind.EDIT)]["lines"]]

    async def ok(self, c, email="", location="", date=("--", "--", "--"), about=(),
                 first="Bob", last="Smith"):
        """Fill in the form and click OK: the status text, or None if the window closed."""
        win = c.windows[WIN_ACCOUNT]
        for gid, text in zip(self.names(win), (first, last)):
            c.value(WIN_ACCOUNT, gid, text)
        for gid, text in zip(self.boxes(win), (email, location)):
            c.value(WIN_ACCOUNT, gid, text)
        for gid, row in zip(self.dropdowns(win), date):
            c.pick_dropdown(WIN_ACCOUNT, gid, win.gadgets[gid]["rows"].index(row))
        c.text(WIN_ACCOUNT, gadget_of(win, Kind.EDIT), about)
        win.gadgets[gadget_of(win, Kind.LABEL, -1)]["text"] = "-"
        c.click_text(WIN_ACCOUNT, "OK")
        await c.wait_for(lambda: WIN_ACCOUNT not in c.windows or self.status(c) != "-",
                         "OK closes the window or sets the status")
        return self.status(c) if WIN_ACCOUNT in c.windows else None

    async def test_opened_by_client_menu_id(self):
        bob = self.bob
        self.assertNotIn(MENU_MY_ACCOUNT, [i for i, _p, _l in bob.menu])
        self.assertNotIn("My Account", bob.menu_items("Members"))
        win = await self.open(bob)
        self.assertEqual(win.id, WIN_ACCOUNT)
        # and also for a role with no permissions at all
        d = self.server.db
        rid = d.create_role("Nobody", 5)
        d.set_user_role(d.user("bob")["id"], rid)
        self.server.permissions_changed(user_id=d.user("bob")["id"])
        await bob.wait_for(lambda: bob.menu_titles() == ["Members", "Help", "Status"], "bare menu")
        await bob.wait_for(lambda: has_text(bob, WIN_ACCOUNT, "Role: Nobody"), "role updated")
        win = await self.open(bob)
        win.find("Role: Nobody")

    async def test_layout(self):
        win = await self.open(self.bob)
        self.assertEqual(win.size, (W, H))
        self.assertLess(W, 632, "narrower than before")
        self.assertLessEqual(H, CLIENT_MAX_H)
        self.assertEqual(win.pos, ui.centre(W, H))
        self.assertTrue(window_fits(*win.pos, W, H))
        g = win.gadgets
        labels = [g[i] for i in sorted(g) if g[i]["kind"] == Kind.LABEL]
        names = ["Username:", "First Name:", "Last Name:", "Email Address:", "Location:",
                 "Birthdate:", "About Me:", "Last Login:", "Karma Points:"]
        col = [lab for lab in labels if lab["text"] in names]
        self.assertEqual([lab["text"] for lab in col], names)
        self.assertEqual({lab["box"][0] for lab in col}, {LABEL_X}, "one label column")
        widest = max(len(n) for n in names) * 8
        self.assertEqual(FIELD_X, LABEL_X + widest + 8, "8 px after the longest label")
        ys = [lab["box"][1] for lab in col]
        gaps = [b - a for a, b in zip(ys, ys[1:])]
        self.assertEqual(gaps[:6], [14] * 6, "even rows")
        self.assertEqual(gaps[6], 30 + 1, "About Me is 30 high, then the gap")
        self.assertEqual(gaps[7], 14, "Karma Points under Last Login")
        karma_box = next(lab for lab in labels if lab["box"][1] == ys[8] and
                         lab["box"][0] == FIELD_X)
        self.assertEqual(karma_box["text"], "%d (Low)" % self.server.db.user("bob")["karma"])
        # The role is beside the username; first and last names are empty boxes to start.
        role = g[win.find("Role: %s" % self.server.db.user("bob")["role"])]["box"]
        self.assertEqual(role[1], ys[0])
        self.assertLessEqual(role[0] + role[2], FIELD_X + FIELD_W)
        self.assertEqual([win.text(i) for i in self.names(win)], ["", ""])
        for i in self.names(win):
            self.assertGreaterEqual((g[i]["box"][2] - 6) // 8, db.REAL_NAME_MAX)
        # Email and Location: half the old 508; still 63 characters (the box scrolls).
        boxes = [g[i]["box"] for i in self.boxes(win)]
        self.assertEqual([b[0] for b in boxes], [FIELD_X] * 2)
        self.assertEqual([(b[2], b[3]) for b in boxes], [(FIELD_W, 12)] * 2)
        self.assertTrue(250 <= FIELD_W <= 262)
        # Birthdate: three drop-downs in a row, wide enough for "Jan", "31" and "2026".
        dd = [g[i] for i in self.dropdowns(win)]
        self.assertEqual(dd[0]["box"][0], FIELD_X)
        self.assertEqual({d["box"][1] for d in dd}, {ys[5] - 2}, "on the Birthdate row")
        for d, chars in zip(dd, (3, 2, 4)):
            self.assertGreaterEqual((d["box"][2] - 17) // 8, chars)
        for a, b in zip(dd, dd[1:]):
            self.assertLess(a["box"][0] + a["box"][2], b["box"][0], "no overlap")
        this_year = datetime.date.today().year
        self.assertEqual(dd[0]["rows"], ["--", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
        self.assertEqual(dd[1]["rows"], ["--"] + [str(i) for i in range(1, 32)])
        self.assertEqual(dd[2]["rows"], ["--"] + [str(y) for y in
                                                  range(this_year, FIRST_YEAR - 1, -1)])
        self.assertEqual([d["value"] for d in dd], [0, 0, 0], "not set")
        # About Me: one EDIT, full field width, 3 lines visible, 30-character lines.
        edits = [g[i] for i in g if g[i]["kind"] == Kind.EDIT]
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["box"], (FIELD_X, ys[6] - 2, FIELD_W, 30))
        self.assertEqual((FIELD_W - 17) // 8, 30)
        self.assertEqual(edits[0]["lines"], [])
        # Buttons: Reset Password bottom left; OK (default) and Cancel bottom right.
        for b in ("Save", "Close"):
            self.assertRaises(KeyError, win.find, b)
        reset, ok, cancel = (g[win.find(b)]["box"] for b in ("Reset Password...", "OK", "Cancel"))
        self.assertEqual(reset[0], LABEL_X)
        self.assertEqual(cancel[0] + cancel[2], FIELD_X + FIELD_W, "right-aligned")
        self.assertLess(reset[0] + reset[2], ok[0])
        self.assertLess(ok[0] + ok[2], cancel[0])
        self.assertEqual({reset[1], ok[1]}, {cancel[1]}, "one row")
        self.assertEqual(g[win.find("OK")]["flags"] & 1, 1, "OK is the default")
        status = g[gadget_of(win, Kind.LABEL, -1)]["box"]
        self.assertLessEqual(status[1] + status[3], cancel[1], "status above the buttons")
        self.assertGreaterEqual(status[1], ys[-1] + 10, "below Karma Points, not over it")
        self.assertGreaterEqual(status[2] // 8, len(PARTIAL), "room for the messages")
        win.find("This is your first sign-on.")

    async def test_save_reload_clear(self):
        bob, d = self.bob, self.server.db
        await self.open(bob)
        about = ["I like chess.", "", "And SID music, demos and", "BBSes."]
        self.assertIsNone(await self.ok(bob, "bob@example.com", "Melbourne",
                                        ("Jun", "21", "1985"), about + ["", ""]),
                          "OK saves and closes")
        u = d.user("bob")
        self.assertEqual((u["first_name"], u["last_name"], u["email"], u["location"],
                          u["birthdate"], u["about"]),
                         ("Bob", "Smith", "bob@example.com", "Melbourne", "1985-06-21",
                          "\n".join(about)))
        win = await self.open(bob)
        self.assertEqual([win.text(i) for i in self.names(win)], ["Bob", "Smith"])
        self.assertEqual(self.shown(win), ["bob@example.com", "Melbourne",
                                           ("Jun", "21", "1985"), about])
        # Eight full-width lines are fine; a long email still holds 63 characters.
        email = "a" * 51 + "@example.com"
        self.assertEqual(len(email), 63)
        eight = ["%d" % i + "x" * 29 for i in range(8)]
        self.assertIsNone(await self.ok(bob, email, "", ("Feb", "29", "2000"), eight))
        self.assertEqual(d.user("bob")["about"].split("\n"), eight)
        self.assertEqual(d.user("bob")["birthdate"], "2000-02-29")
        win = await self.open(bob)
        self.assertEqual(self.shown(win), [email, "", ("Feb", "29", "2000"), eight])
        # All "--" and empty fields clear everything.
        self.assertIsNone(await self.ok(bob))
        u = d.user("bob")
        self.assertEqual((u["email"], u["location"], u["birthdate"], u["about"]), ("",) * 4)
        win = await self.open(bob)
        self.assertEqual(self.shown(win), ["", "", ("--", "--", "--"), []])

    async def test_invalid(self):
        bob, d = self.bob, self.server.db
        await self.open(bob)
        cases = [
            (dict(first=""), "Please type your first name."),
            (dict(last=""), "Please type your last name."),
            (dict(first="B0b"), "Names hold letters, spaces, ' - and . only."),
            (dict(last="x" * 21), "Names hold at most 20 characters."),
            (dict(email="bob@"), "That email address doesn't look right."),
            (dict(email="b" * 52 + "@example.com"),
             "Email and Location hold at most 63 characters."),
            (dict(date=("Feb", "30", "1985")), "Birthdate: Feb 1985 has no day 30."),
            (dict(date=("Feb", "29", "1985")), "Birthdate: Feb 1985 has no day 29."),
            (dict(date=("Apr", "31", "1999")), "Birthdate: Apr 1999 has no day 31."),
            (dict(date=("Jun", "--", "1985")), PARTIAL),
            (dict(date=("--", "--", "1985")), PARTIAL),
            (dict(date=("Jun", "21", "--")), PARTIAL),
            (dict(about=["line %d" % i for i in range(9)]),
             "About Me has 9 lines: it holds at most 8."),
            # a 31-character word doesn't fit a 30-character line: it takes two
            (dict(about=["y" * 31] + ["z"] * 7), "About Me has 9 lines: it holds at most 8."),
        ]
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        if tomorrow.year == datetime.date.today().year:      # (on 31 Dec it isn't in the list)
            cases.append((dict(date=(MONTHS[tomorrow.month - 1], str(tomorrow.day),
                                     str(tomorrow.year))),
                          "A birthdate can't be in the future."))
        win = bob.windows[WIN_ACCOUNT]
        room = win.gadgets[gadget_of(win, Kind.LABEL, -1)]["box"][2] // 8
        for kw, msg in cases:
            self.assertEqual(await self.ok(bob, **kw), msg, kw)
            self.assertLessEqual(len(msg), room, "fits the status line")
        u = d.user("bob")
        self.assertEqual((u["first_name"], u["email"], u["birthdate"], u["about"]),
                         ("", "", "", ""), "nothing saved")
        self.assertIn(WIN_ACCOUNT, bob.windows, "still open")

    def test_birthdate_rules(self):
        """Account.birthdate with a fixed `today` (the future check on any day of the year)."""
        def form(month, day, year_row, years=("2026", "2025")):
            dd = lambda i, rows: types.SimpleNamespace(selected=i, rows=rows)
            return types.SimpleNamespace(month=dd(month, None), day=dd(day, None),
                                         year=dd(year_row, ["--", *years]))
        today = datetime.date(2026, 11, 17)
        bd = Account.birthdate
        self.assertEqual(bd(form(11, 17, 1), today), ("2026-11-17", None))
        self.assertEqual(bd(form(11, 18, 1), today), (None, "A birthdate can't be in the future."))
        self.assertEqual(bd(form(12, 31, 2), today), ("2025-12-31", None))
        self.assertEqual(bd(form(0, 0, 0), today), ("", None))
        self.assertEqual(bd(form(None, None, None), today), ("", None))
        self.assertEqual(bd(form(2, 29, 1, ("2024",)), today), ("2024-02-29", None))
        self.assertEqual(bd(form(0, 5, 1), today), (None, PARTIAL))

    async def test_cancel_discards(self):
        bob, d = self.bob, self.server.db
        win = await self.open(bob)
        g = win.gadgets
        bob.value(WIN_ACCOUNT, self.boxes(win)[0], "bob@example.com")
        month, day, year = self.dropdowns(win)
        bob.pick_dropdown(WIN_ACCOUNT, month, 3)
        bob.pick_dropdown(WIN_ACCOUNT, day, 3)
        bob.pick_dropdown(WIN_ACCOUNT, year, g[year]["rows"].index("1990"))
        bob.text(WIN_ACCOUNT, gadget_of(win, Kind.EDIT), ["Not saved."])
        bob.click_text(WIN_ACCOUNT, "Cancel")
        await bob.wait_for(lambda: WIN_ACCOUNT not in bob.windows, "Cancel closes")
        u = d.user("bob")
        self.assertEqual((u["email"], u["birthdate"], u["about"]), ("", "", ""))
        win = await self.open(bob)
        self.assertEqual(self.shown(win), ["", "", ("--", "--", "--"), []])

    async def test_old_about_and_birthdate(self):
        """About Me saved by the old three-box form (lines up to 63 characters) and a birthdate
        before FIRST_YEAR (the old form allowed 1900 on) still load, and save again."""
        bob, d = self.bob, self.server.db
        old = ["A" * 20 + " " + "b" * 42, "Second line.", "word " * 11 + "end"]
        d.conn.execute("UPDATE users SET about = ?, birthdate = '1950-03-04' "
                       "WHERE name = 'bob'", ("\n".join(old),))
        d.conn.commit()
        win = await self.open(bob)
        shown = self.shown(win)
        self.assertEqual(shown[2], ("Mar", "4", "1950"))
        self.assertIn("1950", win.gadgets[self.dropdowns(win)[2]]["rows"])
        self.assertTrue(all(len(line) <= 30 for line in shown[3]), shown[3])
        self.assertEqual("".join(shown[3]).replace(" ", ""), "".join(old).replace(" ", ""),
                         "nothing lost")
        self.assertEqual(d.user("bob")["about"], "\n".join(old), "stored as is until saved")
        self.assertIsNone(await self.ok(bob, date=("Mar", "4", "1950"), about=shown[3]))
        self.assertEqual(d.user("bob")["birthdate"], "1950-03-04")
        self.assertEqual(d.user("bob")["about"].split("\n"), shown[3])

    async def test_last_login_is_the_previous_one(self):
        d = self.server.db
        first = d.user("bob")["last_login"]
        self.assertIsNotNone(first)
        await self.sign_off(self.bob)
        d.conn.execute("UPDATE users SET last_login = ? WHERE name = 'bob'", (first - 86400,))
        d.conn.commit()
        bob = await self.sign_in("bob")
        win = await self.open(bob)
        win.find(when(first - 86400))
        self.assertGreaterEqual(d.user("bob")["last_login"], first, "this sign-on stored")

    async def test_reset_password(self):
        bob = self.bob
        await self.open(bob)

        async def ok(cur, new, confirm, expect):
            win = bob.windows[WIN_PASSWORD]
            pw = [gadget_of(win, Kind.PASSWORD, i) for i in range(3)]
            for gid, text in zip(pw, (cur, new, confirm)):
                bob.value(WIN_PASSWORD, gid, text)
            win.gadgets[gadget_of(win, Kind.LABEL, -1)]["text"] = "-"
            bob.click_text(WIN_PASSWORD, "OK")
            await bob.wait_for(lambda: WIN_PASSWORD not in bob.windows or
                               win.text(gadget_of(win, Kind.LABEL, -1)) != "-", "status")
            if WIN_PASSWORD in bob.windows:
                self.assertEqual(win.text(gadget_of(win, Kind.LABEL, -1)), expect)

        bob.click_text(WIN_ACCOUNT, "Reset Password...")
        win = await bob.wait_window("Reset Password")
        self.assertEqual(win.pos, ui.centre(320, 84))
        await ok("wrong", "newpass", "newpass", "That's not your current password.")
        await ok("secret", "abc", "abc", "Passwords need at least 4 characters.")
        await ok("secret", "newpass", "newpasz", "The new passwords don't match.")
        await ok("secret", "newpass", "newpass", "Your password has been changed.")
        self.assertTrue(db.verify_password("newpass", self.server.db.password_hash("bob")))
        bob.click_text(WIN_PASSWORD, "Cancel")
        await bob.wait_for(lambda: WIN_PASSWORD not in bob.windows, "closed")
        await self.sign_off(bob)
        bob = await self.sign_in("bob", "newpass")

        # Three wrong current passwords close the dialog, and it stays shut for a while.
        await self.open(bob)
        bob.click_text(WIN_ACCOUNT, "Reset Password...")
        await bob.wait_window("Reset Password")
        for _ in range(3):
            await ok("guess", "x1234", "x1234", "That's not your current password.")
        await bob.wait_for(lambda: bob.alerts, "too many")
        self.assertNotIn(WIN_PASSWORD, bob.windows)
        self.assertTrue(db.verify_password("newpass", self.server.db.password_hash("bob")))
        bob.click_text(WIN_ACCOUNT, "Reset Password...")
        await bob.wait_for(lambda: self.status(bob) == "Too many wrong passwords: wait a "
                           "minute.", "locked")
        self.assertNotIn(WIN_PASSWORD, bob.windows)
