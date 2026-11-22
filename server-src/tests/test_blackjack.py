"""Blackjack: the rules on their own (blackjack_rules.py), then the table through the fake
client (games/blackjack.py): joining opens a table at once, bets leave the balance and come
back with the winnings, double, a second player at the same table, the chat, and leaving."""

import unittest
from unittest import mock

from meganet.games import blackjack
from meganet.games import blackjack_rules as rules
from meganet.games.blackjack_art import TABLE
from meganet.games.lobby import WIN_GAMES
from meganet.games.poker_rules import card, new_deck
from meganet.protocol import Caps, Kind
from tests.test_server import ServerTest

GRID = Caps.GRID


def cards(text):
    return [card(t) for t in text.split()]


class FakeShoe:
    """Deals `text`'s cards in order."""

    def __init__(self, text):
        self.cards = cards(text)

    def draw(self):
        return self.cards.pop(0)

    def low(self):
        return False


def rig(shoe, text):
    """The game's shoe deals `text` next (a full shoe's worth after it, so no reshuffle)."""
    shoe.cards = [c for _ in range(6) for c in new_deck()] + list(reversed(cards(text)))


class RulesTest(unittest.TestCase):
    def test_values(self):
        self.assertEqual(rules.value(cards("Ah Kd")), (21, True))
        self.assertEqual(rules.value(cards("Ah Ad 9c")), (21, True))
        self.assertEqual(rules.value(cards("Ah 6d Tc")), (17, False))
        self.assertEqual(rules.describe(cards("Ah 6d")), "Soft 17")
        self.assertEqual(rules.describe(cards("Kh Qd")), "20")

    def test_blackjack_pays_3_to_2(self):
        r = rules.Round({0: 10}, FakeShoe("Ah 9c Kd 7s"))      # me A K, dealer 9 7
        self.assertTrue(r.hands[0][0].blackjack)
        self.assertEqual(r.phase, "dealer", "nothing to do with a blackjack")
        while r.dealer_step():
            pass
        self.assertEqual(r.results[0][0][1:], ("blackjack", 25))

    def test_dealer_checks_for_blackjack(self):
        # (dealt round the table: seat 0, seat 1, the dealer, twice) dealer A up, K in the hole
        r = rules.Round({0: 10, 1: 20}, FakeShoe("Th 9d Ah Kd Qs Kc"))
        self.assertEqual(r.phase, "over", "settled at once")
        self.assertTrue(r.hole_shown)
        self.assertEqual(r.paid(0), 0)
        self.assertEqual(r.paid(1), 0)
        r = rules.Round({0: 10}, FakeShoe("Ah Ac Kh Kc"))     # both blackjack: a push
        self.assertEqual(r.results[0][0][1:], ("push", 10))

    def test_dealer_stands_on_soft_17_and_hits_16(self):
        r = rules.Round({0: 10}, FakeShoe("Th Ac 8d 6c"))      # me 18; dealer A 6
        r.act(0, "stand")
        while r.dealer_step():
            pass
        self.assertEqual(len(r.dealer), 2)
        self.assertEqual(r.results[0][0][1:], ("win", 20))
        r = rules.Round({0: 10}, FakeShoe("Th 9c 8d 7c Kd"))   # dealer 16: hits, busts
        r.act(0, "stand")
        while r.dealer_step():
            pass
        self.assertEqual(rules.value(r.dealer)[0], 26)
        self.assertEqual(r.results[0][0][1:], ("win", 20))

    def test_bust_and_double(self):
        r = rules.Round({0: 10}, FakeShoe("Th 9c 6d 8c Kd"))
        r.act(0, "hit")                                        # 26
        self.assertEqual(r.phase, "dealer")
        self.assertFalse(r.dealer_needed(), "everyone's bust: the dealer just shows")
        while r.dealer_step():
            pass
        self.assertEqual(r.results[0][0][1:], ("bust", 0))
        r = rules.Round({0: 10}, FakeShoe("5h 9c 6d 8c Th"))  # me 11, double: 21
        self.assertEqual(r.extra_bet(0, "double"), 10)
        r.act(0, "double")
        self.assertEqual(r.hands[0][0].bet, 20)
        while r.dealer_step():
            pass
        self.assertEqual(r.results[0][0][1:], ("win", 40))

    def test_split(self):
        r = rules.Round({0: 10}, FakeShoe("8h Tc 8d 7c 3s Kd 2h"))
        self.assertTrue(r.options(0)["split"])
        r.act(0, "split")                       # 8 3 | 8 K
        self.assertEqual([len(h.cards) for h in r.hands[0]], [2, 2])
        self.assertEqual(r.turn, (0, 0))
        self.assertFalse(r.options(0)["split"], "once")
        r.act(0, "hit")                         # 8 3 2 = 13
        r.act(0, "stand")
        self.assertEqual(r.turn, (0, 1))
        r.act(0, "stand")                       # 18
        while r.dealer_step():
            pass                                # dealer 17
        self.assertEqual([o for _, o, _ in r.results[0]], ["lose", "win"])
        self.assertEqual(r.paid(0), 20)
        self.assertEqual(r.staked(0), 20)

    def test_split_aces_take_one_card(self):
        r = rules.Round({0: 10}, FakeShoe("Ah 9c Ad 8c Kh 5s"))
        r.act(0, "split")
        self.assertEqual(r.phase, "dealer", "both hands done")
        self.assertFalse(r.hands[0][0].blackjack, "21 after a split isn't a blackjack")
        while r.dealer_step():
            pass
        self.assertEqual([o for _, o, _ in r.results[0]], ["win", "lose"])  # 21, 16 v 17

    def test_not_your_turn(self):
        r = rules.Round({0: 10, 1: 10}, FakeShoe("Th 9h 8c Tc 9d 8d"))
        with self.assertRaises(rules.RulesError):
            r.act(1, "hit")
        r.stand_all(0)
        self.assertEqual(r.turn, (1, 0))


class BlackjackTest(ServerTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for name, value in (("DEALER_DELAY", 0), ("NEXT_ROUND", 0.2), ("BET_SECS", 3600)):
            patch = mock.patch.object(blackjack, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(blackjack.Blackjack, "tick_interval", 0.02)
        patch.start()
        self.addCleanup(patch.stop)

    async def join(self, c):
        c.windows.pop(WIN_GAMES, None)
        c.pick("Games")
        games = await c.wait_window("Games")
        lb = next(gid for gid, g in games.gadgets.items() if g["kind"] == Kind.LISTBOX)
        await c.wait_for(lambda: games.gadgets[lb]["rows"], "game rows")
        row = next(i for i, r in enumerate(games.gadgets[lb]["rows"])
                   if r.startswith("Blackjack"))
        c.select(WIN_GAMES, lb, row)
        c.click_text(WIN_GAMES, "Join")
        return await c.wait_window("Blackjack")

    async def bet(self, c, table, g, name, amount):
        s = next(t for t in g.seats if t.name == name)
        c.value(table.id, s.view.bet_box.gid, str(amount))
        c.click_text(table.id, "Bet")
        await c.wait_for(lambda: s.bet or g.phase != "betting", "the bet")
        return s

    def uid(self, name):
        return self.server.db.user(name)["id"]

    async def test_needs_credits(self):
        c = await self.signed_on("alice", caps=GRID)
        self.server.db.add_credits(self.uid("alice"), -495, "test")
        c.windows.pop(WIN_GAMES, None)
        c.pick("Games")
        games = await c.wait_window("Games")
        lb = next(gid for gid, g in games.gadgets.items() if g["kind"] == Kind.LISTBOX)
        await c.wait_for(lambda: games.gadgets[lb]["rows"], "game rows")
        row = next(i for i, r in enumerate(games.gadgets[lb]["rows"]) if r.startswith("Black"))
        c.select(WIN_GAMES, lb, row)
        c.click_text(WIN_GAMES, "Join")
        await c.wait_for(lambda: c.alerts, "refused")
        self.assertIn("You need 10 credits to play blackjack", c.alerts[-1][1])

    async def test_a_round_alone(self):
        db = self.server.db
        c = await self.signed_on("alice", caps=GRID)
        table = await self.join(c)                       # a table at once: no waiting
        g = self.server.games.running[-1]
        self.assertEqual(bytes(c.resources[blackjack.RESOURCE_SLOT][:len(TABLE)]), TABLE)
        rig(g.shoe, "Th 9c 9d 7s 5h")                    # me 19; dealer 9 7, hits a 5: 21
        start = db.credits(self.uid("alice"))
        await self.bet(c, table, g, "alice", 50)
        self.assertEqual(db.credits(self.uid("alice")), start - 50)
        await c.wait_for(lambda: g.round is not None, "dealt at once (the only player)")
        self.assertEqual(db.poker_chips(), {self.uid("alice"): 50}, "held on the table")
        await c.wait_for(lambda: c.enabled(table.id, "Stand"), "my turn")
        self.assertFalse(c.enabled(table.id, "Split"))
        c.click_text(table.id, "Stand")
        await c.wait_for(lambda: g.phase in ("over", "betting"), "the dealer played")
        self.assertEqual(g.round.results[0][0][1], "lose")
        self.assertEqual(db.credits(self.uid("alice")), start - 50)
        self.assertEqual(db.poker_chips(), {})
        await c.wait_for(lambda: any("alice loses 50." in l for l in self.chat(table)),
                         "the dealer's line")
        await c.wait_for(lambda: c.enabled(table.id, "Bet"), "the next round's bet")

    async def test_double_and_win(self):
        db = self.server.db
        c = await self.signed_on("alice", caps=GRID)
        table = await self.join(c)
        g = self.server.games.running[-1]
        rig(g.shoe, "5h 9c 6d 8c Th")                   # me 11, double for a 10; dealer 17
        start = db.credits(self.uid("alice"))
        await self.bet(c, table, g, "alice", 20)
        await c.wait_for(lambda: c.enabled(table.id, "Double"), "my turn")
        c.click_text(table.id, "Double")
        await c.wait_for(lambda: g.phase in ("over", "betting"), "settled")
        self.assertEqual(db.credits(self.uid("alice")), start + 40, "won 2 x 40")
        self.assertEqual(db.credit_log(self.uid("alice"))[0]["reason"], "blackjack win")

    async def test_two_players_and_the_chat(self):
        c = await self.signed_on("alice", caps=GRID)
        table = await self.join(c)
        g = self.server.games.running[-1]
        b = await self.signed_on("bob", caps=GRID)
        btable = await self.join(b)
        self.assertIs(self.server.games.running[-1], g, "the same table")
        self.assertEqual([s.name for s in g.seats if not s.empty], ["alice", "bob"])
        # the chat: in both windows, and at alice's seat
        c.value(table.id, g.seats[0].view.entry.gid, "good luck")
        c.click_text(table.id, "Send")
        for w, who in ((table, c), (btable, b)):
            await who.wait_for(lambda: "alice: good luck" in self.chat(w), "the line")
        await b.wait_for(lambda: has(btable, '"good luck"'), "at alice's seat")
        self.assertIn("* bob sits down.", self.chat(table))
        # one bet waits for the other; with both in, the deal
        rig(g.shoe, "Th Tc 9h 9d 8c 8s")                # alice 19, bob 18; dealer 17
        await self.bet(c, table, g, "alice", 10)
        self.assertIsNone(g.round, "waits for bob")
        await self.bet(b, btable, g, "bob", 30)
        await c.wait_for(lambda: g.round is not None, "dealt")
        self.assertEqual(g.round.seats, [0, 1])
        await c.wait_for(lambda: c.enabled(table.id, "Stand"), "alice first")
        self.assertFalse(b.enabled(btable.id, "Stand"), "not bob's turn yet")
        c.click_text(table.id, "Stand")
        await b.wait_for(lambda: b.enabled(btable.id, "Stand"), "bob's turn")
        b.click_text(btable.id, "Stand")
        await c.wait_for(lambda: g.phase in ("over", "betting"), "settled")
        self.assertEqual([o for _, o, _ in g.round.results[0]], ["win"])
        self.assertEqual([o for _, o, _ in g.round.results[1]], ["win"])

    async def test_leaving_gives_back_an_undealt_bet(self):
        db = self.server.db
        c = await self.signed_on("alice", caps=GRID)
        table = await self.join(c)
        g = self.server.games.running[-1]
        b = await self.signed_on("bob", caps=GRID)
        await self.join(b)
        start = db.credits(self.uid("alice"))
        await self.bet(c, table, g, "alice", 40)        # (waits for bob)
        self.assertEqual(db.credits(self.uid("alice")), start - 40)
        c.click_text(table.id, "Leave")
        await c.wait_for(lambda: db.credits(self.uid("alice")) == start, "given back")
        self.assertEqual(db.credit_log(self.uid("alice"))[0]["reason"], "blackjack bet back")
        self.assertEqual([s.name for s in g.seats if not s.empty], ["bob"])

    async def test_leaving_mid_round_is_still_paid(self):
        db = self.server.db
        c = await self.signed_on("alice", caps=GRID)
        table = await self.join(c)
        g = self.server.games.running[-1]
        rig(g.shoe, "Th 9c Kd 7s")                       # me 20 v 16 (+ whatever it draws)
        start = db.credits(self.uid("alice"))
        await self.bet(c, table, g, "alice", 10)
        await c.wait_for(lambda: c.enabled(table.id, "Stand"), "my turn")
        c.click_text(table.id, "Leave")                 # my 20 stands; the round is played out
        await c.wait_for(lambda: g.over, "the table closes")
        self.assertEqual(db.poker_chips(), {})
        paid = g.round.paid(0)
        self.assertEqual(db.credits(self.uid("alice")), start - 10 + paid)

    @staticmethod
    def chat(w):
        return next(g["lines"] for g in w.gadgets.values() if g["kind"] == Kind.TEXTVIEW)


def has(win, text):
    return any(text in (x.get("text") or "") for x in win.gadgets.values())


if __name__ == "__main__":
    unittest.main()
