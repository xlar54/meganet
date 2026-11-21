"""Texas Hold'em rules (games/poker_rules.py): ranking hands, blinds and turns, raises,
all-ins and side pots, and the computer."""

import random
import unittest

from meganet.games.poker_rules import (Hand, RulesError, cards, evaluate, describe, new_deck,
                                       computer_move, STRAIGHT, FLUSH, FULL_HOUSE, PAIR,
                                       TWO_PAIR, STRAIGHT_FLUSH, HIGH, QUADS, TRIPS)


def rig(holes, board, n=None):
    """A deck that deals `holes` (one "Ah Kd" string per seat, in dealing order from the
    small blind; first cards first) and then the board (burn cards in between)."""
    holes = [cards(h) for h in holes]
    order = []
    for k in range(2):
        for h in holes:
            order.append(h[k])
    b = cards(board)
    burn = [c for c in new_deck() if c not in order and c not in b]
    seq = order + [burn[0]] + b[:3] + [burn[1]] + b[3:4] + [burn[2]] + b[4:5]
    used = set(seq)
    rest = [c for c in new_deck() if c not in used]
    return rest + list(reversed(seq))                 # (dealt with pop(): from the end)


class EvaluateTest(unittest.TestCase):
    def v(self, text):
        return evaluate(cards(text))

    def test_categories(self):
        self.assertEqual(self.v("Ah Kh Qh Jh Th 2c 3d")[0], STRAIGHT_FLUSH)
        self.assertEqual(describe(self.v("Ah Kh Qh Jh Th 2c 3d")), "Royal Flush")
        self.assertEqual(self.v("5h 4h 3h 2h Ah 9c 9d"), (STRAIGHT_FLUSH, 5), "the steel wheel")
        self.assertEqual(self.v("9c 9d 9h 9s 2c 3d Kc"), (QUADS, 9, 13))
        self.assertEqual(self.v("9c 9d 9h 2s 2c 3d 3c"), (FULL_HOUSE, 9, 3))
        self.assertEqual(self.v("9c 9d 9h 2s 2c 2d Kc"), (FULL_HOUSE, 9, 2), "two trips")
        self.assertEqual(self.v("Ac 9c 7c 4c 2c Kd Kh")[0], FLUSH)
        self.assertEqual(self.v("Ad 2c 3h 4s 5c Kd Kh"), (STRAIGHT, 5), "not the pair")
        self.assertEqual(self.v("Ad 2c 3h 9s 5c Kd Kh"), (PAIR, 13, 14, 9, 5))
        self.assertEqual(self.v("Ad 2c 3h 4s 5c 9d Jh"), (STRAIGHT, 5), "the wheel")
        self.assertEqual(self.v("Td Jc Qh Ks Ac 9d 8h"), (STRAIGHT, 14))
        self.assertEqual(self.v("Td Tc 5h 5s 9c 9d 8h"), (TWO_PAIR, 10, 9, 8), "best two pairs")
        self.assertEqual(self.v("7d 7c 7h Ks 2c 4d 9h"), (TRIPS, 7, 13, 9))
        self.assertEqual(self.v("Ad Jc 9h 7s 5c 3d 2h"), (HIGH, 14, 11, 9, 7, 5))
        self.assertEqual(describe(self.v("6d 6c 6h 2s 2c 4d 9h")), "Full House, Sixes over Twos")
        self.assertEqual(describe(self.v("Kd Kc 8h 8s 2c 4d 9h")), "Two Pair, Kings and Eights")

    def test_order(self):
        hands = ["Ad Jc 9h 7s 5c", "2d 2c 9h 7s 5c", "2d 2c 9h 9s 5c", "2d 2c 2h 9s 5c",
                 "Ad 2c 3h 4s 5c", "Ac 9c 7c 4c 2c", "2d 2c 2h 9s 9c", "2d 2c 2h 2s 9c",
                 "5h 4h 3h 2h Ah"]
        values = [self.v(h) for h in hands]
        self.assertEqual(values, sorted(values))
        self.assertGreater(self.v("Ad Ac 9h 7s 5c"), self.v("Ad Ac 9h 7s 4c"), "kickers")


class HandTest(unittest.TestCase):
    def test_blinds_and_turns_heads_up(self):
        h = Hand([1000, 1000], button=0, small=5, big=10, rng=random.Random(1))
        self.assertEqual((h.sb_seat, h.bb_seat, h.turn), (0, 1, 0), "the button posts SB")
        self.assertEqual(h.options(0), {"check": False, "call": 5, "raise": (20, 1000)})
        h.act(0, "call")
        self.assertEqual(h.turn, 1, "the big blind's option")
        self.assertEqual(h.options(1)["check"], True)
        h.act(1, "check")
        self.assertEqual((h.street, len(h.board), h.turn), (1, 3, 1), "BB first after the flop")
        with self.assertRaises(RulesError):
            h.act(0, "check")

    def test_three_handed_and_a_raise(self):
        h = Hand([1000, 1000, 1000], button=0, small=5, big=10, rng=random.Random(2))
        self.assertEqual((h.sb_seat, h.bb_seat, h.turn), (1, 2, 0))
        h.act(0, "raise", 30)
        self.assertEqual(h.options(1)["raise"], (50, 1000), "at least the last raise again")
        with self.assertRaises(RulesError):
            h.act(1, "raise", 40)
        h.act(1, "fold")
        h.act(2, "call")
        self.assertEqual((h.street, h.pot(), h.turn), (1, 65, 2))

    def test_everyone_folds(self):
        h = Hand([1000, 1000, 1000], button=0, small=5, big=10, rng=random.Random(3))
        h.act(0, "raise", 100)
        h.act(1, "fold")
        h.act(2, "fold")
        self.assertTrue(h.over)
        self.assertEqual(h.stack, [1015, 995, 990], "the uncalled raise came back")
        self.assertEqual(h.results, [(0, 25, None)], "the pot, after the 90 uncalled")
        self.assertEqual(h.shown, set())

    def test_short_allin_does_not_reopen(self):
        h = Hand([1000, 1000, 55], button=0, small=5, big=10, rng=random.Random(4))
        # seat 0 (first to act) raises to 40; SB calls; BB (55) goes all in: 15 more, not a
        # full raise; seat 0 may call or fold but not raise again
        h.act(0, "raise", 40)
        h.act(1, "call")
        h.act(2, "allin")
        self.assertEqual(h.current, 55)
        self.assertEqual(h.turn, 0)
        self.assertIsNone(h.options(0)["raise"])
        h.act(0, "call")
        self.assertIsNone(h.options(1)["raise"])
        h.act(1, "call")
        self.assertEqual((h.street, h.pot()), (1, 165))

    def test_side_pots(self):
        # seats: 0 has 100, 1 has 300, 2 has 1000. Everyone all in pre-flop.
        deck = rig(["Ah Ad", "Kh Kd", "Qh Qd"], "2c 7s 9d 3c 4s")
        h = Hand([100, 300, 1000], button=2, small=5, big=10, deck=deck)
        self.assertEqual((h.sb_seat, h.bb_seat, h.turn), (0, 1, 2))
        self.assertEqual(h.hole, {0: cards("Ah Ad"), 1: cards("Kh Kd"), 2: cards("Qh Qd")})
        h.act(2, "allin")
        h.act(0, "allin")
        h.act(1, "allin")
        self.assertTrue(h.over)
        self.assertEqual(h.board, cards("2c 7s 9d 3c 4s"))
        self.assertEqual(h.pots(), [(300, [0, 1, 2]), (400, [1, 2])])
        self.assertEqual(h.stack, [300, 400, 700], "Aces the main pot, Kings the side pot, "
                                                    "the rest back to the big stack")
        self.assertEqual(h.shown, {0, 1, 2})

    def test_split_pot(self):
        deck = rig(["Ah 2d", "Ac 3d"], "Ks Qs Js Ts 9d")        # both play the board
        h = Hand([500, 500], button=0, small=5, big=10, deck=deck)
        h.act(0, "raise", 25)
        h.act(1, "call")
        for _ in range(3):
            h.act(1, "check")
            h.act(0, "check")
        self.assertTrue(h.over)
        self.assertEqual(h.stack, [500, 500])

    def test_odd_chip(self):
        deck = rig(["Ah 2d", "Ac 3d", "7c 8c"], "Ks Qs Js Ts 2h")
        h = Hand([500, 500, 3], button=2, small=5, big=10, deck=deck)
        # seat 2 is short (3): posted nothing as button; SB seat 0, BB seat 1
        h.act(2, "allin")
        h.act(0, "call")
        h.act(1, "check")
        for _ in range(3):
            h.act(0, "check")
            h.act(1, "check")
        self.assertTrue(h.over)
        self.assertEqual(sum(h.stack), 1003)
        self.assertEqual(h.stack[2], 0)
        self.assertEqual(h.stack[:2], [502, 501], "the odd chip left of the button")

    def test_everyone_all_in_runs_it_out(self):
        h = Hand([200, 200], button=1, small=5, big=10, rng=random.Random(5))
        h.act(1, "allin")
        h.act(0, "call")
        self.assertTrue(h.over)
        self.assertEqual(len(h.board), 5)
        self.assertEqual(sum(h.stack), 400)

    def test_computer_plays(self):
        rng = random.Random(9)
        for k in range(30):
            h = Hand([1000] * 4, button=k % 4, small=5, big=10, rng=rng)
            moves = 0
            while not h.over:
                a, amount = computer_move(h, h.turn, rng)
                h.act(h.turn, a, amount)
                moves += 1
                self.assertLess(moves, 200)
            self.assertEqual(sum(h.stack), 4000)

    def test_strength(self):
        deck = rig(["Ah Ad", "7c 2d"], "Kc 9s 4h 3c 8d")
        h = Hand([500, 500], button=0, small=5, big=10, deck=deck)
        self.assertGreater(h.strength(0, random.Random(1)), 0.75)
        self.assertLess(h.strength(1, random.Random(1)), 0.4, "(against any two cards)")
