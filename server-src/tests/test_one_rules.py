"""One's rules (games/one_rules.py), with no windows: the deck, every card's effect, drawing,
the Wild Draw Four challenge, calling One!, scoring, and whole rounds played by the computer."""

import random
import unittest

from meganet.games.one_rules import (Card, Round, RulesError, deck, computer_choice,
                                     COLOURS, WILD, WILD4, HAND)


def C(text):
    """'R5', 'GS' (Skip), 'BR' (Reverse), 'YD' (Draw Two), 'W', 'F' -> a Card."""
    if text in (WILD, WILD4):
        return Card(None, text)
    return Card(text[0], text[1])


def rigged(n=3, top="R5", hands=(), pile=(), turn=0, colour=None):
    """A round with known cards: hands[i] for seat i, the pile (its last card drawn first)."""
    r = Round(["p%d" % i for i in range(n)], dealer=n - 1, rng=random.Random(1))
    r.hands = [[C(t) for t in h.split()] for h in hands] + [[] for _ in range(n - len(hands))]
    r.pile = [C(t) for t in pile]
    r.discard = [C(top)]
    r.colour = colour or r.top.colour
    r.turn, r.direction, r.waiting = turn, 1, None
    r.opening_wild = False
    r.events = []
    return r


class TopRng(random.Random):
    """A shuffle that puts `card` where the first card turned up comes from."""

    def __init__(self, card, n):
        super().__init__(5)
        self.card, self.n = card, n

    def shuffle(self, x):
        super().shuffle(x)
        if len(x) == 108:
            card = x.pop(x.index(self.card))     # popped just after the deal
            x.insert(len(x) - HAND * self.n, card)


class DeckTest(unittest.TestCase):
    def test_deck(self):
        d = deck()
        self.assertEqual(len(d), 108)
        for c in COLOURS:
            self.assertEqual(d.count(Card(c, "0")), 1)
            for f in "123456789SRD":
                self.assertEqual(d.count(Card(c, f)), 2)
        self.assertEqual(d.count(Card(None, WILD)), 4)
        self.assertEqual(d.count(Card(None, WILD4)), 4)
        self.assertEqual(sum(c.points for c in d), 4 * (2 * 45 + 6 * 20) + 8 * 50)
        self.assertEqual(str(C("YD")), "Yellow Draw Two")

    def test_deal(self):
        r = Round(["a", "b", "c"], dealer=0, rng=random.Random(3))
        self.assertEqual([len(h) for h in r.hands], [7, 7, 7])
        self.assertNotEqual(r.top.face, WILD4)
        self.assertEqual(len(r.pile) + len(r.discard) + 21, 108)

    def test_first_card(self):
        def first(card, n=3):
            return Round(["p%d" % i for i in range(n)], dealer=0, rng=TopRng(C(card), n))
        r = first("R5")
        self.assertEqual((r.top, r.turn, r.colour), (C("R5"), 1, "R"))
        r = first("RS")
        self.assertEqual(r.turn, 2, "the first player is skipped")
        r = first("RR")
        self.assertEqual((r.turn, r.direction), (0, -1), "the dealer starts, the other way")
        r = first("RR", n=2)
        self.assertEqual(r.turn, 0)
        r = first("RD")
        self.assertEqual((r.turn, len(r.hands[1])), (2, 9), "seat 1 draws 2 and is skipped")
        r = first(WILD)
        self.assertEqual((r.turn, r.waiting, r.wild_by), (1, "colour", 1))
        r.choose_colour(1, "G")
        self.assertEqual((r.turn, r.waiting, r.colour), (1, None, "G"), "then seat 1 plays")
        r = first(WILD4)
        self.assertNotEqual(r.top.face, WILD4, "never turned up first")


class PlayTest(unittest.TestCase):
    def test_matching(self):
        r = rigged(hands=["R9 G5 B2 W", "Y1"], top="R5")
        self.assertEqual(r.playable(0), [0, 1, 3])
        self.assertEqual(r.playable(1), [], "not their turn")
        with self.assertRaises(RulesError):
            r.play(0, 2)                          # Blue 2 on Red 5
        with self.assertRaises(RulesError):
            r.play(1, 0)
        r.play(0, 1)                              # Green 5 on Red 5: colour now Green
        self.assertEqual((r.top, r.colour, r.turn), (C("G5"), "G", 1))

    def test_skip_reverse_draw_two(self):
        r = rigged(hands=["RS RR RD R1", "R2 R3", "R4 R6"], top="R5")
        r.play(0, 0)
        self.assertEqual(r.turn, 2, "Skip")
        r.turn = 0
        r.play(0, 0)                              # Reverse with three: back to seat 2
        self.assertEqual((r.direction, r.turn), (-1, 2))
        r.turn, r.direction = 0, 1
        r.pile = [C("B1"), C("B2"), C("B3")]
        r.play(0, 0)                              # Draw Two: seat 1 draws 2, seat 2 plays
        self.assertEqual((r.turn, len(r.hands[1])), (2, 4))
        two = rigged(n=2, hands=["RR R1", "R2"], top="R5")
        two.play(0, 0)
        self.assertEqual(two.turn, 0, "Reverse with two is a Skip")

    def test_wild(self):
        r = rigged(hands=["W R1", "B2"], top="G5")
        r.play(0, 0)
        self.assertEqual((r.waiting, r.turn), ("colour", 0))
        with self.assertRaises(RulesError):
            r.play(0, 0)
        with self.assertRaises(RulesError):
            r.choose_colour(1, "B")
        r.choose_colour(0, "B")
        self.assertEqual((r.colour, r.turn, r.waiting), ("B", 1, None))
        self.assertEqual(r.playable(1), [0])

    def test_wild_draw_four(self):
        pile = ["Y%d" % i for i in range(1, 10)]
        # not challenged: seat 1 draws 4 and is skipped
        r = rigged(hands=["F R1", "B2", "G3"], top="R5", pile=pile)
        r.play(0, 0)
        r.choose_colour(0, "B")
        self.assertEqual((r.turn, r.waiting), (1, "challenge"))
        r.challenge(1, False)
        self.assertEqual((len(r.hands[1]), r.turn), (5, 2))
        # challenged, and guilty (seat 0 held Red): seat 0 draws 4, seat 1 plays
        r = rigged(hands=["F R1", "B2", "G3"], top="R5", pile=pile)
        r.play(0, 0)
        r.choose_colour(0, "B")
        self.assertFalse(r.challenge(1, True))
        self.assertEqual((len(r.hands[0]), len(r.hands[1]), r.turn), (5, 1, 1))
        # challenged, and honest: seat 1 draws 6 and is skipped
        r = rigged(hands=["F B1", "B2", "G3"], top="R5", pile=pile)
        r.play(0, 0)
        r.choose_colour(0, "B")
        self.assertTrue(r.challenge(1, True))
        self.assertEqual((len(r.hands[0]), len(r.hands[1]), r.turn), (1, 7, 2))

    def test_draw(self):
        r = rigged(n=2, hands=["B1", "B2"], top="R5", pile=["G7", "R9"])
        card = r.draw(0)                          # Red 9: it can be played
        self.assertEqual((card, r.waiting, r.turn), (C("R9"), "drawn", 0))
        with self.assertRaises(RulesError):
            r.play(0, 0)                          # only the card drawn
        self.assertEqual(r.playable(0), [1])
        r.pass_turn(0)
        self.assertEqual((r.turn, len(r.hands[0])), (1, 2))
        card = r.draw(1)                          # Green 7 doesn't go: the turn passes
        self.assertEqual((card, r.turn, r.waiting), (C("G7"), 0, None))
        r = rigged(hands=["B1", "B2"], top="R5", pile=["R9"])
        r.draw(0)
        r.play(0, 1)
        self.assertEqual((r.top, r.turn), (C("R9"), 1))

    def test_reshuffle(self):
        r = rigged(hands=["B1", "B2"], top="R5", pile=[])
        r.discard = [C("G1"), C("G2"), C("R5")]
        r.draw(0)
        self.assertEqual(r.discard, [C("R5")])
        self.assertEqual(len(r.pile) + len(r.hands[0]), 3)
        r = rigged(hands=["B1", "B2"], top="R5", pile=[])
        self.assertIsNone(r.draw(0), "nothing to draw: the turn passes")
        self.assertEqual(r.turn, 1)


class CallTest(unittest.TestCase):
    def test_caught(self):
        r = rigged(hands=["R1 R2", "B2 B3", "G1"], top="R5", pile=["Y1", "Y2", "Y3"])
        r.play(0, 0)                              # down to one, not called
        self.assertEqual(r.unsafe, 0)
        self.assertIsNone(r.catch(0), "not yourself")
        self.assertEqual(r.catch(2), 0)
        self.assertEqual((len(r.hands[0]), r.unsafe), (3, None))

    def test_called_before_and_after(self):
        r = rigged(hands=["R1 R2", "B2 B3", "G1"], top="R5")
        self.assertTrue(r.call_one(0))            # two cards, on your turn
        r.play(0, 0)
        self.assertIsNone(r.unsafe)
        r = rigged(hands=["R1 R2", "B2 B3", "G1"], top="R5")
        r.play(0, 0)
        self.assertTrue(r.call_one(0))            # just after: still in time
        self.assertIsNone(r.catch(1))
        self.assertFalse(r.call_one(2), "one card, but never down to it by playing")
        self.assertTrue(r.call_one(1), "two cards, on their turn")

    def test_safe_once_the_next_player_acts(self):
        r = rigged(hands=["R1 R2", "R3 B3 B4", "G1"], top="R5")
        r.play(0, 0)
        r.play(1, 0)
        self.assertIsNone(r.unsafe)
        self.assertIsNone(r.catch(2))


class ScoreTest(unittest.TestCase):
    def test_going_out(self):
        r = rigged(hands=["RD", "B2 W", "GS Y9"], top="R5", pile=["Y1", "Y2"])
        self.assertEqual(r.play(0, 0), 2 + 50 + 1 + 2 + 20 + 9,
                         "the next player draws 2 first, and those count")
        self.assertTrue(r.over)
        self.assertEqual(r.winner, 0)
        with self.assertRaises(RulesError):
            r.draw(1)


class ComputerTest(unittest.TestCase):
    def test_honest_wild_draw_four(self):
        r = rigged(hands=["F R1", "B2"], top="R5")
        self.assertEqual(computer_choice(r, 0, random.Random(1)), ("play", 1))
        r = rigged(hands=["F B1", "B2"], top="R5")
        self.assertEqual(computer_choice(r, 0, random.Random(1)), ("play", 0))

    def test_numbers_first_unless_the_next_is_nearly_out(self):
        r = rigged(hands=["RS R2 R8 W", "B1 B2 B3"], top="R5")
        self.assertEqual(computer_choice(r, 0, random.Random(1)), ("play", 2))
        r = rigged(hands=["RS R2 R8 W", "B1"], top="R5")
        self.assertEqual(computer_choice(r, 0, random.Random(1)), ("play", 0))

    def test_whole_rounds(self):
        """Computers play rounds to the end: cards are never lost or made up."""
        rng = random.Random(7)
        for n in (2, 3, 4):
            for k in range(25):
                r = Round(["c%d" % i for i in range(n)], dealer=k % n, rng=rng)
                moves = 0
                while not r.over:
                    moves += 1
                    self.assertLess(moves, 3000, "a round that never ends")
                    if r.waiting == "colour":
                        r.choose_colour(r.wild_by, rng.choice(COLOURS))
                    elif r.waiting == "challenge":
                        r.challenge(r.turn, rng.random() < 0.5)
                    else:
                        if r.unsafe is not None and rng.random() < 0.3:
                            r.catch((r.unsafe + 1) % n)
                        move = computer_choice(r, r.turn, rng)
                        if move[0] == "play":
                            if len(r.hands[r.turn]) == 2 and rng.random() < 0.7:
                                r.call_one(r.turn)
                            r.play(r.turn, move[1])
                        elif move[0] == "pass":
                            r.pass_turn(r.turn)
                        else:
                            r.draw(r.turn)
                    total = len(r.pile) + len(r.discard) + sum(len(h) for h in r.hands)
                    self.assertEqual(total, 108)
                self.assertEqual(r.hands[r.winner], [])


if __name__ == "__main__":
    unittest.main()
