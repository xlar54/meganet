"""Blackjack's rules (games/blackjack.py plays them at a table): a six-deck shoe, the dealer
stands on all 17s and checks for blackjack with an Ace or a ten up, blackjack pays 3 to 2,
double on any first two cards (after a split too), split a pair once (split Aces take one
card each, and 21 on them isn't a blackjack). No insurance, no surrender.

A Round is one deal: the bets {seat: amount}, then act(seat, action) for the seat whose turn
it is, then dealer_step() until the dealer is done; `results` says what each hand paid.
`moves` lists every card as it's dealt (for the flying cards): (target, index, face_up),
target "dealer" or (seat, hand)."""

import random

from .poker_rules import RulesError, new_deck

DECKS = 6
RESHUFFLE_AT = 0.25           # a new shoe when less than this much of it is left
MIN_BET, MAX_BET = 10, 500


def card_value(c):
    return 11 if c.rank == 14 else min(c.rank, 10)


def value(cards):
    """(total, soft): the best total, and whether an Ace still counts 11 in it."""
    total, aces = 0, 0
    for c in cards:
        total += card_value(c)
        aces += c.rank == 14
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total, aces > 0


def describe(cards):
    total, soft = value(cards)
    return ("Soft %d" % total) if soft and total < 21 else str(total)


class Shoe:
    def __init__(self, rng=None, decks=DECKS):
        self.rng = rng or random.Random()
        self.decks = decks
        self.cards = []
        self.shuffle()

    def shuffle(self):
        self.cards = [c for _ in range(self.decks) for c in new_deck()]
        self.rng.shuffle(self.cards)

    def low(self):
        return len(self.cards) < RESHUFFLE_AT * self.decks * 52

    def draw(self):
        if not self.cards:
            self.shuffle()
        return self.cards.pop()


class Hand:
    def __init__(self, bet, cards=None, split=False):
        self.bet = bet
        self.cards = list(cards or [])
        self.split = split            # made by a split (21 in two isn't a blackjack)
        self.split_aces = False
        self.doubled = False
        self.done = False

    @property
    def total(self):
        return value(self.cards)[0]

    @property
    def bust(self):
        return self.total > 21

    @property
    def blackjack(self):
        return len(self.cards) == 2 and self.total == 21 and not self.split


class Round:
    def __init__(self, bets, shoe):
        """`bets`: {seat: amount} for the seats in this round (dealt in seat order)."""
        if not bets:
            raise RulesError("No bets.")
        self.shoe = shoe
        self.seats = sorted(bets)
        self.hands = {s: [Hand(bets[s])] for s in self.seats}
        self.dealer = []
        self.hole_shown = False
        self.moves = []
        self.events = []
        self.results = {}             # seat -> [(hand, outcome, paid back), ...] when over
        self.turn = None              # (seat, hand index) to act, or None
        self.phase = "play"           # "play", "dealer" (dealer_step() next), "over"
        self._deal()

    # ---- dealing ----

    def _give(self, target, face_up=True):
        c = self.shoe.draw()
        if target == "dealer":
            self.dealer.append(c)
            self.moves.append(("dealer", len(self.dealer) - 1, face_up))
        else:
            seat, k = target
            h = self.hands[seat][k]
            h.cards.append(c)
            self.moves.append(((seat, k), len(h.cards) - 1, True))
        return c

    def _deal(self):
        for _ in range(2):
            for s in self.seats:
                self._give((s, 0))
            self._give("dealer", face_up=not self.dealer)     # the second is the hole card
        up = self.dealer[0]
        if card_value(up) in (10, 11) and value(self.dealer)[0] == 21:
            self.events.append("The dealer has blackjack.")
            self.hole_shown = True
            self.moves.append(("reveal",))
            for s in self.seats:
                self.hands[s][0].done = True
            return self._finish()
        for s in self.seats:
            if self.hands[s][0].blackjack:
                self.hands[s][0].done = True
        self._next_turn()

    @property
    def upcard(self):
        return self.dealer[0] if self.dealer else None

    def dealer_shows(self):
        """What the players see of the dealer's hand: all of it, or the up card's value."""
        if self.hole_shown:
            return describe(self.dealer)
        return str(card_value(self.upcard)) if self.upcard else ""

    # ---- the players' turns ----

    def _next_turn(self):
        for s in self.seats:
            for k, h in enumerate(self.hands[s]):
                if not h.done:
                    self.turn = (s, k)
                    return
        self.turn = None
        self.phase = "dealer"

    def options(self, seat):
        """What `seat` may do now: {"hit", "stand", "double", "split"} -> bool."""
        if self.turn is None or self.turn[0] != seat:
            return dict.fromkeys(("hit", "stand", "double", "split"), False)
        hands = self.hands[seat]
        h = hands[self.turn[1]]
        two = len(h.cards) == 2
        return {"hit": True, "stand": True, "double": two,
                "split": two and len(hands) == 1 and card_value(h.cards[0]) == card_value(
                    h.cards[1])}

    def extra_bet(self, seat, action):
        """The credits a double or split puts in (the hand's bet), else 0."""
        if action in ("double", "split") and self.turn and self.turn[0] == seat:
            return self.hands[seat][self.turn[1]].bet
        return 0

    def act(self, seat, action):
        if self.phase != "play" or self.turn is None or self.turn[0] != seat:
            raise RulesError("It isn't your turn.")
        if not self.options(seat).get(action):
            raise RulesError("You can't %s now." % action)
        k = self.turn[1]
        h = self.hands[seat][k]
        if action == "hit":
            self._give((seat, k))
            if h.total >= 21:
                h.done = True
        elif action == "stand":
            h.done = True
        elif action == "double":
            h.bet *= 2
            h.doubled = True
            self._give((seat, k))
            h.done = True
        elif action == "split":
            second = Hand(h.bet, [h.cards.pop()], split=True)
            h.split = True
            self.hands[seat].append(second)
            aces = h.cards[0].rank == 14
            for j, hh in enumerate(self.hands[seat]):
                self._give((seat, j))
                if aces:
                    hh.split_aces = hh.done = True
                elif hh.total == 21:
                    hh.done = True
        if self.turn is not None and self.hands[seat][self.turn[1]].done:
            self._next_turn()

    def stand_all(self, seat):
        """A player who left: their hands stand as they are."""
        for h in self.hands.get(seat, []):
            h.done = True
        if self.turn is not None and self.turn[0] == seat:
            self._next_turn()

    # ---- the dealer ----

    def dealer_needed(self):
        """Does the dealer draw (any hand still standing that isn't a blackjack)?"""
        return any(not h.bust and not h.blackjack for s in self.seats for h in self.hands[s])

    def dealer_step(self):
        """One dealer move: show the hole card, then draw to 17. False once it's over."""
        if self.phase != "dealer":
            return False
        if not self.hole_shown:
            self.hole_shown = True
            self.moves.append(("reveal",))
            return True
        if self.dealer_needed() and value(self.dealer)[0] < 17:
            self._give("dealer")
            return True
        self._finish()
        return False

    def _finish(self):
        d_total = value(self.dealer)[0]
        d_bj = len(self.dealer) == 2 and d_total == 21
        if d_total > 21:
            self.events.append("The dealer busts with %d." % d_total)
        elif not d_bj:
            self.events.append("The dealer has %d." % d_total)
        for s in self.seats:
            out = []
            for h in self.hands[s]:
                if h.bust:
                    out.append((h, "bust", 0))
                elif h.blackjack and not d_bj:
                    out.append((h, "blackjack", h.bet + h.bet * 3 // 2))
                elif d_bj:
                    out.append((h, "push", h.bet) if h.blackjack else (h, "lose", 0))
                elif d_total > 21 or h.total > d_total:
                    out.append((h, "win", 2 * h.bet))
                elif h.total == d_total:
                    out.append((h, "push", h.bet))
                else:
                    out.append((h, "lose", 0))
            self.results[s] = out
        self.turn = None
        self.phase = "over"

    def paid(self, seat):
        return sum(p for _, _, p in self.results.get(seat, []))

    def staked(self, seat):
        return sum(h.bet for h in self.hands.get(seat, []))
