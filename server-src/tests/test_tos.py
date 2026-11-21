"""The Terms of Service: the last step of sign-up (signup.py: read them, tick the box, OK) and
Admin > Terms of Service... (admin.TosEditor: a page at a time, Save, Cancel)."""

from meganet import db
from meganet.admin import TosEditor
from meganet.screens import M_TOS
from meganet.signup import WIN_SIGNUP, TOS_VIEW, NOT_AGREED, CANCELLED
from meganet.protocol import Kind, GFlag
from meganet.ui import TextView, TextArea
from tests.test_pages import PagesBase
from tests.test_roles import gadget_of, status_of
from tests.test_signup import WizardMixin


def view_lines(win):
    return win.gadgets[gadget_of(win, Kind.TEXTVIEW)]["lines"]


class TermsStepTest(WizardMixin, PagesBase):
    """alice (Sysop) and bob (New User) are signed on."""

    async def test_read_tick_and_ok(self):
        c = await self.start()
        await self.to_review(c, "Gus")
        self.assertIsNone(await self.press(c, "Next"))
        win = await self.at(c, 6)
        self.check_layout(win, 6)
        self.assertEqual(win.title, "New User: Terms of Service")
        self.assertEqual(view_lines(win), db.tos_text(db.tidy_tos(db.DEFAULT_TOS)))
        self.assertEqual(TextView(*TOS_VIEW).columns(), db.TOS_COLS, "as wide as the editor")
        await c.wait_for(lambda: win.gadgets[gadget_of(win, Kind.TEXTVIEW)].get("value") == 0,
                         "scrolled to the top")
        box = gadget_of(win, Kind.CHECKBOX)
        self.assertEqual(win.gadgets[box]["text"], "I have read and agree to the Terms of Service.")
        self.assertFalse(c.enabled(WIN_SIGNUP, "OK"), "not until the box is ticked")
        # a forged OK with the box clear: the session drops a click on a greyed-out button,
        # and the wizard checks the box itself too
        signup = next(s.signup for s in self.server.sessions if s.signup is not None)
        c.click_text(WIN_SIGNUP, "OK")
        await signup._accept(signup.win.ok)
        await c.wait_for(lambda: status_of(c.windows[WIN_SIGNUP]) == NOT_AGREED, "refused")
        self.assertIsNone(self.server.db.user("Gus"))
        # tick, untick, tick: OK follows
        c.select(WIN_SIGNUP, box, 1)
        await c.wait_for(lambda: c.enabled(WIN_SIGNUP, "OK"), "enabled")
        c.select(WIN_SIGNUP, box, 0)
        await c.wait_for(lambda: not c.enabled(WIN_SIGNUP, "OK"), "greyed again")
        # Back keeps it; then agree and OK
        self.assertIsNone(await self.press(c, "Back"))
        await self.at(c, 5)
        self.assertEqual(await self.accept(c), (True, "Welcome to MegaNet, Gus!"))
        user = self.server.db.user("Gus")
        self.assertIsNotNone(user["tos_agreed"])

    async def test_cancel_on_the_terms(self):
        c = await self.start()
        await self.to_review(c, "Hal")
        await self.to_terms(c)
        n = len(c.login_results)
        c.click_text(WIN_SIGNUP, "Cancel")
        await self.cancelled(c, n)
        self.assertIsNone(self.server.db.user("Hal"))


class TosEditorTest(WizardMixin, PagesBase):
    async def editor(self, c):
        c.pick("Terms of Service...")
        return await c.wait_window("Terms of Service")

    @staticmethod
    def area(win):
        return gadget_of(win, Kind.EDIT)

    @staticmethod
    def heading(win):
        return next(g["text"] for g in win.gadgets.values()
                    if g["kind"] == Kind.LABEL and g["text"].startswith("Terms of Service:"))

    async def test_pages_save_and_new_users_read_them(self):
        c = self.alice
        self.assertIn("Terms of Service...", c.menu_items("Admin"))
        win = await self.editor(c)
        self.assertEqual(TextArea(*TosEditor.AREA).columns(), db.TOS_COLS)
        self.assertEqual(self.heading(win), "Terms of Service: page 1 of 4")
        self.assertEqual(win.gadgets[self.area(win)]["lines"], db.DEFAULT_TOS[0])
        self.assertFalse(c.enabled(win.id, "<"))
        # page 1 edited, then page 2: the edit is kept while the pages turn
        c.text(win.id, self.area(win), ["OUR RULES", "", "Be nice."])
        c.click_text(win.id, ">")
        await c.wait_for(lambda: self.heading(win) == "Terms of Service: page 2 of 4", "page 2")
        await c.wait_for(lambda: win.gadgets[self.area(win)]["lines"] == db.DEFAULT_TOS[1],
                         "page 2's text")
        c.text(win.id, self.area(win), ["No spam."])
        c.click_text(win.id, "<")
        await c.wait_for(lambda: win.gadgets[self.area(win)]["lines"] == ["OUR RULES", "",
                                                                           "Be nice."], "kept")
        c.click_text(win.id, "Save")
        await c.wait_for(lambda: c.alerts and c.alerts[-1][0] == "Terms of Service", "saved")
        self.assertEqual(c.alerts[-1][1], "Saved. New users agree to them as they join.")
        pages = self.server.db.tos()
        self.assertEqual(pages[:2], [["OUR RULES", "", "Be nice."], ["No spam."]])
        self.assertEqual(pages[2], db.DEFAULT_TOS[2])
        # a new user reads the new text
        n = await self.start()
        await self.to_review(n, "Ivy")
        win6 = await self.to_terms(n)
        self.assertEqual(view_lines(win6)[:5], ["OUR RULES", "", "Be nice.", "", "No spam."])

    async def test_too_long_and_empty_are_refused(self):
        c = self.alice
        win = await self.editor(c)
        full = ["line %d" % i for i in range(db.TOS_PAGE_LINES)]
        for page in range(db.TOS_PAGES):        # 4 x 32 lines + 3 blanks: past 128
            c.text(win.id, self.area(win), full)
            if page < db.TOS_PAGES - 1:
                c.click_text(win.id, ">")
                await c.wait_for(lambda p=page: self.heading(win).endswith(
                    "page %d of 4" % (p + 2)), "next page")
        c.click_text(win.id, "Save")
        await c.wait_for(lambda: c.alerts, "refused")
        self.assertEqual(c.alerts[-1], ("Terms of Service", "That's 131 lines; the reader holds 128."))
        self.assertEqual(self.server.db.tos()[0], db.DEFAULT_TOS[0], "nothing saved")
        self.assertEqual(db.tos_problem([[], [], [], []]), "The Terms of Service can't be empty.")

    async def test_non_admin_is_refused(self):
        bob = self.bob
        self.assertNotIn("Admin", bob.menu_titles())
        bob.pick_id(M_TOS)                      # (forged: never in bob's menu)
        await self.roundtrip(bob)
        self.assertFalse(any(w.title == "Terms of Service" for w in bob.windows.values()))
