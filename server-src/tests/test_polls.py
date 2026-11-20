"""Areas > Voting (polls.py): managers set up polls with a question, a description and 2-6
choices (and maybe an end date); everyone votes once; Results shows a bar per choice; after
the end date only the results are shown."""

import time

from meganet import polls
from meganet.polls import WIN_VOTING, WIN_RESULTS, WIN_NEW_POLL, WIN_DELETE_POLL
from meganet.protocol import Kind
from tests.test_pages import PagesBase
from tests.test_roles import gadget_of, status_of


class PollsBase(PagesBase):
    async def open_voting(self, c):
        c.windows.pop(WIN_VOTING, None)
        c.pick("Voting")
        return await c.wait_window("Voting")

    def lists(self, c):
        w = c.windows[WIN_VOTING]
        return (w.gadgets[gadget_of(w, Kind.LISTBOX, 0)]["rows"],
                w.gadgets[gadget_of(w, Kind.LISTBOX, 1)]["rows"])

    def about(self, c):
        w = c.windows[WIN_VOTING]
        return w.gadgets[gadget_of(w, Kind.TEXTVIEW)]["lines"]

    async def new_poll(self, c, question, about, choices, ends=""):
        c.click_text(WIN_VOTING, "New...")
        win = await c.wait_window("New Poll")
        boxes = [g for g in sorted(win.gadgets) if win.gadgets[g]["kind"] == Kind.TEXTBOX]
        c.value(WIN_NEW_POLL, boxes[0], question)
        c.text(WIN_NEW_POLL, gadget_of(win, Kind.EDIT), about)
        for gid, text in zip(boxes[1:7], list(choices) + [""] * 6):
            c.value(WIN_NEW_POLL, gid, text)
        c.value(WIN_NEW_POLL, boxes[7], ends)
        c.click_text(WIN_NEW_POLL, "Create")
        return win

    async def pick(self, c, nth, which=0):
        w = c.windows[WIN_VOTING]
        c.select(WIN_VOTING, gadget_of(w, Kind.LISTBOX, which), nth)
        await self.roundtrip(c)


class VotingTest(PollsBase):
    async def test_set_up_vote_once_results(self):
        alice, bob = self.alice, self.bob                   # alice: Sysop; bob: New User
        self.assertIn("Voting", bob.menu_items("Areas"))
        await self.open_voting(bob)
        self.assertFalse(any(g["text"] == "New..." for g in
                             bob.windows[WIN_VOTING].gadgets.values()), "managers only")
        self.assertEqual(status_of(bob.windows[WIN_VOTING]), "No polls yet.")

        await self.open_voting(alice)
        # mistakes are caught in the dialog
        win = await self.new_poll(alice, "Best SID tune?", [], ["Commando"])
        await alice.wait_for(lambda: status_of(win) == "A poll needs at least 2 choices.", "2")
        alice.click_text(WIN_NEW_POLL, "Cancel")
        await alice.wait_for(lambda: WIN_NEW_POLL not in alice.windows, "cancelled")
        win = await self.new_poll(alice, "Best SID tune?", [], ["A", "B"], ends="soon")
        await alice.wait_for(lambda: status_of(win).startswith("The end date is YYYY"), "date")
        alice.click_text(WIN_NEW_POLL, "Cancel")
        await alice.wait_for(lambda: WIN_NEW_POLL not in alice.windows, "cancelled")
        # the real one
        await self.new_poll(alice, "Best SID tune?",
                            ["Which tune would you play first", "on a brand-new MEGA65?"],
                            ["Commando", "Monty on the Run", "Delta"])
        await alice.wait_for(lambda: WIN_NEW_POLL not in alice.windows, "created")
        await bob.wait_for(lambda: len(self.lists(bob)[0]) == 1, "bob sees it")
        self.assertTrue(self.lists(bob)[0][0].startswith("Best SID tune?"))
        self.assertTrue(self.lists(bob)[0][0].endswith(" open"))

        # bob picks it: its description and choices; Vote waits for a choice
        await self.pick(bob, 0)
        await bob.wait_for(lambda: self.about(bob) == [
            "Which tune would you play first", "on a brand-new MEGA65?"], "description")
        self.assertEqual(self.lists(bob)[1], ["  Commando", "  Monty on the Run", "  Delta"])
        self.assertFalse(bob.enabled(WIN_VOTING, "Vote"))
        self.assertTrue(bob.enabled(WIN_VOTING, "Results"))
        await self.pick(bob, 1, which=1)
        await bob.wait_for(lambda: bob.enabled(WIN_VOTING, "Vote"), "vote enabled")
        bob.click_text(WIN_VOTING, "Vote")
        await bob.wait_for(lambda: status_of(bob.windows[WIN_VOTING]).startswith(
            "Your vote for Monty on the Run is in"), "voted")
        await bob.wait_for(lambda: self.lists(bob)[1][1] == "* Monty on the Run", "marked")
        self.assertTrue(self.lists(bob)[0][0].endswith(" voted"))
        self.assertFalse(bob.enabled(WIN_VOTING, "Vote"))
        # only once, even when the client sends it again
        bob.click_text(WIN_VOTING, "Vote")                   # (greyed: the server ignores it)
        await self.roundtrip(bob)
        pid = self.server.db.polls()[0]["id"]
        self.assertFalse(self.server.db.vote(pid, self.session("bob").user_id,
                                             self.server.db.poll_choices(pid)[0]["id"]))
        self.assertEqual([c["votes"] for c in self.server.db.poll_choices(pid)], [0, 1, 0])

        # Results: a bar per choice, following new votes
        bob.click_text(WIN_VOTING, "Results")
        res = await bob.wait_window("Results")
        bars = lambda: [g.get("value", 0) for g in sorted(
            res.gadgets.values(), key=lambda g: g["box"][1]) if g["kind"] == Kind.PROGRESS]
        self.assertEqual(bars(), [0, 100, 0])
        self.assertIn("1 (100%)", [g["text"] for g in res.gadgets.values()])
        await self.pick(alice, 0)
        await self.pick(alice, 0, which=1)
        alice.click_text(WIN_VOTING, "Vote")
        await bob.wait_for(lambda: bars() == [50, 50, 0], "bob's results follow")

    async def test_end_date_and_delete(self):
        alice, bob = self.alice, self.bob
        db = self.server.db
        pid = db.create_poll("Old question", ["A", "B"], int(time.time()) - 5, None, "")
        db.vote(pid, self.session("alice").user_id, db.poll_choices(pid)[0]["id"])
        await self.open_voting(bob)
        self.assertTrue(self.lists(bob)[0][0].endswith(" ended"))
        await self.pick(bob, 0)
        await bob.wait_for(lambda: status_of(bob.windows[WIN_VOTING]) ==
                           "Voting has ended: these are the results.", "ended")
        self.assertTrue(self.lists(bob)[1][0].endswith("100%"))
        await self.pick(bob, 1, which=1)                     # (picking a choice does nothing)
        self.assertFalse(bob.enabled(WIN_VOTING, "Vote"))
        # end dates: blank is never; one that has passed is refused
        self.assertIsNone(polls.parse_end(""))
        with self.assertRaises(ValueError):
            polls.parse_end("2000-01-01")
        # Delete (managers): a confirmation, then it's gone for everyone
        await self.open_voting(alice)
        await self.pick(alice, 0)
        alice.click_text(WIN_VOTING, "Delete")
        await alice.wait_window("Delete Poll")
        alice.click_text(WIN_DELETE_POLL, "Delete")
        await bob.wait_for(lambda: self.lists(bob)[0] == [], "gone for bob")
        self.assertEqual(db.polls(), [])
