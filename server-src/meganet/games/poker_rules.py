"""No-limit Texas Hold'em: the cards, ranking hands, and one hand's betting (games/poker.py
draws the table). No windows here, so the tests can play hands directly.

A Hand is played by the seats that have chips (stack > 0): blinds, two hole cards each, four
betting rounds (pre-flop, flop, turn, river) with the board dealt between them, then the
showdown. Standard rules:

- The small blind is left of the button, the big blind left of that; heads-up (two players),
  the button posts the small blind and acts first before the flop, last after it.
- Pre-flop the first to act is left of the big blind, who gets the option to raise when the
  others only call. After the flop it's the first player still in, left of the button.
- No-limit: a raise is at least the last raise (at least the big blind), up to everything you
  have. An all-in raise smaller than that doesn't reopen the betting for those who have
  already acted: they may only call or fold.
- A bet nobody calls goes back to its bettor. Everyone all-in (or all but one): the rest of
  the board is dealt out and it goes to showdown.
- Side pots: each pot is won by the best hand among those who put chips in it. A split pot's
  odd chips go to the winners in order, left of the button.
"""

import random
from collections import Counter, namedtuple

RANKS = "23456789TJQKA"
SUITS = "cdhs"                       # clubs, diamonds, hearts, spades
RANK_NAMES = {2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight",
              9: "Nine", 10: "Ten", 11: "Jack", 12: "Queen", 13: "King", 14: "Ace"}
PLURAL = {6: "Sixes"}
SUIT_NAMES = {"c": "clubs", "d": "diamonds", "h": "hearts", "s": "spades"}

HIGH, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)
CATEGORY = ["High Card", "Pair", "Two Pair", "Three of a Kind", "Straight", "Flush",
            "Full House", "Four of a Kind", "Straight Flush"]

STREETS = ["Pre-flop", "Flop", "Turn", "River"]


class Card(namedtuple("Card", "rank suit")):
    """rank 2-14 (Ace 14), suit one of SUITS."""

    def __str__(self):
        return ("10" if self.rank == 10 else RANKS[self.rank - 2]) + self.suit

    @property
    def red(self):
        return self.suit in "dh"


def card(text):
    """Card("Ah") from text such as "Ah", "Td" or "10d" (tests)."""
    text = text.strip()
    r, s = text[:-1], text[-1].lower()
    rank = 10 if r == "10" else RANKS.index(r.upper()) + 2
    return Card(rank, s)


def cards(text):
    return [card(t) for t in text.split()]


def new_deck():
    return [Card(r, s) for s in SUITS for r in range(2, 15)]


def plural(rank):
    return PLURAL.get(rank, RANK_NAMES[rank] + "s")


def _straight_top(ranks):
    """The top rank of the best straight in a set of ranks (Ace low too), or None."""
    rs = set(ranks)
    if 14 in rs:
        rs.add(1)
    for top in range(14, 4, -1):
        if all(r in rs for r in range(top - 4, top + 1)):
            return top
    return None


def evaluate(hand):
    """The value of the best five of 5-7 cards: a tuple that compares higher for a better
    hand, (category, ranks that break ties...)."""
    ranks = sorted((c.rank for c in hand), reverse=True)
    suits = Counter(c.suit for c in hand)
    suit, n = suits.most_common(1)[0]
    if n >= 5:
        flush = sorted((c.rank for c in hand if c.suit == suit), reverse=True)
        top = _straight_top(flush)
        if top:
            return (STRAIGHT_FLUSH, top)
    counts = Counter(ranks)
    groups = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    if groups[0][1] == 4:
        quad = groups[0][0]
        return (QUADS, quad, max(r for r in ranks if r != quad))
    trips = [r for r, k in groups if k == 3]
    pairs = [r for r, k in groups if k == 2]
    if trips and (len(trips) > 1 or pairs):
        t = trips[0]
        p = max([x for x in trips[1:]] + pairs)
        return (FULL_HOUSE, t, p)
    if n >= 5:
        return (FLUSH,) + tuple(flush[:5])
    top = _straight_top(ranks)
    if top:
        return (STRAIGHT, top)
    if trips:
        t = trips[0]
        return (TRIPS, t) + tuple([r for r in ranks if r != t][:2])
    if len(pairs) >= 2:
        hi, lo = pairs[0], pairs[1]
        return (TWO_PAIR, hi, lo, max(r for r in ranks if r not in (hi, lo)))
    if pairs:
        p = pairs[0]
        return (PAIR, p) + tuple([r for r in ranks if r != p][:3])
    return (HIGH,) + tuple(ranks[:5])


def describe(value):
    """"Two Pair, Kings and Eights" for an evaluate() value."""
    cat = value[0]
    if cat == STRAIGHT_FLUSH:
        return "Royal Flush" if value[1] == 14 else "Straight Flush, %s high" % RANK_NAMES[
            value[1]]
    if cat == QUADS:
        return "Four %s" % plural(value[1])
    if cat == FULL_HOUSE:
        return "Full House, %s over %s" % (plural(value[1]), plural(value[2]))
    if cat == FLUSH:
        return "Flush, %s high" % RANK_NAMES[value[1]]
    if cat == STRAIGHT:
        return "Straight, %s high" % RANK_NAMES[value[1]]
    if cat == TRIPS:
        return "Three %s" % plural(value[1])
    if cat == TWO_PAIR:
        return "Two Pair, %s and %s" % (plural(value[1]), plural(value[2]))
    if cat == PAIR:
        return "Pair of %s" % plural(value[1])
    return "%s high" % RANK_NAMES[value[1]]


def short(value):
    """A short name (a seat's label): "Two Pair", "Flush"..."""
    if value[0] == STRAIGHT_FLUSH and value[1] == 14:
        return "Royal Flush"
    if value[0] == PAIR:
        return "Pair of %s" % plural(value[1])
    return CATEGORY[value[0]]


class RulesError(Exception):
    """A move the rules don't allow (shown to the player)."""


class Hand:
    """One hand. `stacks`: each seat's chips (0 or None: not in this hand); `button`: the
    dealer's seat. After each act() look at `turn` (the seat to act, None when it's over),
    `events` (what happened, as text) and `moves` (for the table: ("deal", seat, which card), ("board",
    first card index, n), ("win", seat, amount))."""

    def __init__(self, stacks, button, small, big, rng=None, deck=None):
        self.rng = rng or random.Random()
        self.n = len(stacks)
        self.stack = [s or 0 for s in stacks]
        self.start_stack = list(self.stack)
        self.seats = [i for i in range(self.n) if self.stack[i] > 0]
        if len(self.seats) < 2:
            raise RulesError("A hand needs two players with chips.")
        self.small, self.big = small, big
        self.deck = list(deck) if deck is not None else new_deck()
        if deck is None:
            self.rng.shuffle(self.deck)
        self.bet = [0] * self.n          # this round
        self.total = [0] * self.n        # this hand
        self.folded = set()
        self.hole = {}
        self.board = []
        self.street = 0
        self.events = []
        self.moves = []
        self.last_action = {}            # seat -> "Call 20" (the table shows it)
        self.results = []                # [(seat, chips won, hand value or None)]
        self.shown = set()               # seats whose cards are shown at the end
        self.over = False
        self.turn = None
        self.button = button if button in self.seats else self.next_seat(button)
        self._deal()

    # ---- seats ----

    def next_seat(self, i, pred=None):
        """The next seat in the hand after i (clockwise) for which pred holds."""
        for k in range(1, self.n + 1):
            j = (i + k) % self.n
            if j in self.seats and (pred is None or pred(j)):
                return j
        return None

    def in_hand(self, i):
        return i in self.seats and i not in self.folded

    def can_act(self, i):
        return self.in_hand(i) and self.stack[i] > 0

    @property
    def live(self):
        return [i for i in self.seats if self.in_hand(i)]

    # ---- dealing and blinds ----

    def _deal(self):
        heads_up = len(self.seats) == 2
        if heads_up:
            self.sb_seat = self.button
            self.bb_seat = self.next_seat(self.button)
        else:
            self.sb_seat = self.next_seat(self.button)
            self.bb_seat = self.next_seat(self.sb_seat)
        for k in range(2):
            i = self.sb_seat
            for _ in self.seats:
                self.hole.setdefault(i, []).append(self.deck.pop())
                self.moves.append(("deal", i, k))
                i = self.next_seat(i)
        self._post(self.sb_seat, self.small, "small blind")
        self._post(self.bb_seat, self.big, "big blind")
        self.current = max(self.bet)
        self.min_raise = self.big
        self.level = 0                   # +1 for each full raise (reopens the betting)
        self.acted = {}                  # seat -> the level when they last acted
        self.turn = self.next_seat(self.bb_seat, self.can_act)
        self._settle()

    def _post(self, i, amount, what):
        amount = min(amount, self.stack[i])
        self._put(i, amount)
        self.events.append("%s posts the %s: %d." % ("{%d}" % i, what, amount))
        self.last_action[i] = "%s %d" % ("SB" if what == "small blind" else "BB", amount)

    def _put(self, i, amount):
        self.stack[i] -= amount
        self.bet[i] += amount
        self.total[i] += amount

    # ---- what the player to act may do ----

    def to_call(self, i):
        return min(self.current - self.bet[i], self.stack[i])

    def can_raise(self, i):
        """May raise: has chips beyond a call, and hasn't acted since the last full raise
        (a short all-in doesn't reopen the betting), and someone else could still call."""
        if self.stack[i] <= self.current - self.bet[i]:
            return False
        if self.acted.get(i) == self.level:
            return False
        return any(self.can_act(j) for j in self.live if j != i)

    def raise_range(self, i):
        """(least, most) to raise TO this round (bet[i] after it), or None."""
        if not self.can_raise(i):
            return None
        most = self.bet[i] + self.stack[i]
        least = min(self.current + self.min_raise, most)
        return least, most

    def options(self, i):
        """{"check": bool, "call": chips to call (0: none), "raise": (least, most) or None}."""
        return {"check": self.bet[i] >= self.current, "call": self.to_call(i),
                "raise": self.raise_range(i)}

    # ---- acting ----

    def act(self, i, action, amount=None):
        """"fold", "check", "call", "raise" (to `amount` this round) or "allin"."""
        if self.over or i != self.turn:
            raise RulesError("It isn't your turn.")
        who = "{%d}" % i
        if action == "fold":
            self.folded.add(i)
            self.events.append("%s folds." % who)
            self.last_action[i] = "Fold"
        elif action == "check":
            if self.bet[i] < self.current:
                raise RulesError("You can't check: %d to call." % self.to_call(i))
            self.events.append("%s checks." % who)
            self.last_action[i] = "Check"
        elif action == "call":
            n = self.to_call(i)
            if n <= 0:
                return self.act(i, "check")
            self._put(i, n)
            allin = self.stack[i] == 0
            self.events.append("%s calls %d%s." % (who, n, " and is all in" if allin else ""))
            self.last_action[i] = "All In" if allin else "Call %d" % n
        elif action in ("raise", "allin"):
            rr = self.raise_range(i)
            if action == "allin":
                if rr is None:                   # (all in to call: that's a call)
                    return self.act(i, "call")
                amount = rr[1]
            if rr is None:
                raise RulesError("You can't raise now.")
            if amount is None or not rr[0] <= amount <= rr[1]:
                raise RulesError("Raise to %d-%d." % rr)
            raise_by = amount - self.current
            opening = self.current == 0
            self._put(i, amount - self.bet[i])
            if raise_by >= self.min_raise:       # a full raise: everyone may act again
                self.min_raise = raise_by
                self.level += 1
            self.current = amount
            allin = self.stack[i] == 0
            verb = "bets" if opening else "raises to"
            self.events.append("%s %s %d%s." % (who, verb, amount,
                                                " (all in)" if allin else ""))
            self.last_action[i] = ("All In %d" % amount if allin else
                                   ("Bet %d" if opening else "Raise %d") % amount)
        else:
            raise RulesError("Unknown move %r." % action)
        self.acted[i] = self.level
        self.turn = self.next_seat(i, self.can_act)
        self._settle()

    def remove(self, i):
        """Seat i leaves mid-hand: their cards are folded, in turn or not."""
        if self.over or not self.in_hand(i):
            return
        if self.turn == i:
            return self.act(i, "fold")
        self.folded.add(i)
        self.events.append("%s folds." % ("{%d}" % i))
        self.last_action[i] = "Fold"
        self._settle()

    def _round_done(self):
        live = self.live
        if len(live) <= 1:
            return True
        need = [j for j in live if self.stack[j] > 0]
        if len(need) <= 1 and all(self.bet[j] >= self.current for j in need):
            return True                          # (nobody left to bet against)
        for j in need:
            if j not in self.acted or self.bet[j] < self.current:
                return False
        return True

    def _settle(self):
        """After a move: is the round over, the hand over? Deal on, or end it."""
        while not self.over:
            if len(self.live) == 1:
                return self._win_uncontested()
            if not self._round_done():
                if self.turn is None or not self.can_act(self.turn):
                    self.turn = self.next_seat(self.turn if self.turn is not None
                                               else self.button, self.can_act)
                return None
            self._return_uncalled()
            for j in self.seats:
                self.bet[j] = 0
            self.current = 0
            self.min_raise = self.big
            self.level = 0
            self.acted = {}
            if self.street == 3:
                return self._showdown()
            self.street += 1
            k = 3 if self.street == 1 else 1
            self.deck.pop()                          # (the burn card)
            first = len(self.board)
            self.board += [self.deck.pop() for _ in range(k)]
            self.moves.append(("board", first, k))
            self.events.append("%s: %s" % (STREETS[self.street],
                                           " ".join(str(c) for c in self.board)))
            for j in self.live:
                if self.last_action.get(j) not in ("Fold",) and self.stack[j] > 0:
                    self.last_action.pop(j, None)
            # nobody (or only one) left who can bet: deal the rest out
            if sum(1 for j in self.live if self.stack[j] > 0) <= 1:
                self.turn = None
                continue
            self.turn = self.next_seat(self.button, self.can_act)

    def _return_uncalled(self):
        """The top bet nobody matched goes back."""
        bets = sorted(((self.bet[j], j) for j in self.seats), reverse=True)
        if len(bets) >= 2 and bets[0][0] > bets[1][0]:
            back = bets[0][0] - bets[1][0]
            j = bets[0][1]
            self.stack[j] += back
            self.bet[j] -= back
            self.total[j] -= back
            self.events.append("%d uncalled goes back to %s." % (back, "{%d}" % j))

    def pot(self):
        return sum(self.total)

    def _win_uncontested(self):
        self._return_uncalled()
        j = self.live[0]
        won = self.pot()
        self.stack[j] += won
        self.results = [(j, won, None)]
        self.moves.append(("win", j, won))
        self.events.append("%s wins %d." % ("{%d}" % j, won))
        self._end()

    def pots(self):
        """[(chips, the seats that can win it)]: the main pot, then the side pots."""
        out = []
        prev = 0
        for level in sorted(set(self.total[j] for j in self.seats if self.total[j] > 0)):
            chips = sum(min(self.total[j], level) - min(self.total[j], prev) for j in self.seats)
            who = [j for j in self.live if self.total[j] >= level]
            if chips:
                if who:
                    out.append([chips, who])
                elif out:                        # (folded chips above the callers: theirs)
                    out[-1][0] += chips
            prev = level
        merged = []                              # one pot for the same set of players
        for chips, who in out:
            if merged and merged[-1][1] == who:
                merged[-1][0] += chips
            else:
                merged.append([chips, who])
        return [(c, w) for c, w in merged]

    def _showdown(self):
        values = {j: evaluate(self.hole[j] + self.board) for j in self.live}
        self.shown = set(self.live)
        won = Counter()
        order = []
        j = self.button
        for _ in range(self.n):                  # odd chips: left of the button first
            j = (j + 1) % self.n
            order.append(j)
        for chips, who in self.pots():
            best = max(values[j] for j in who)
            winners = [j for j in order if j in who and values[j] == best]
            share, odd = divmod(chips, len(winners))
            for k, j in enumerate(winners):
                won[j] += share + (1 if k < odd else 0)
        for j in self.live:
            self.events.append("%s shows %s: %s." % ("{%d}" % j, " ".join(
                str(c) for c in self.hole[j]), describe(values[j])))
        for j in order:
            if won[j]:
                self.stack[j] += won[j]
                self.moves.append(("win", j, won[j]))
                self.events.append("%s wins %d with %s." % ("{%d}" % j, won[j],
                                                           describe(values[j])))
        self.results = [(j, won[j], values[j]) for j in self.live]
        self._end()

    def _end(self):
        self.over = True
        self.turn = None

    # ---- the computer ----

    def strength(self, i, rng, trials=200):
        """How often seat i's hand wins against the others still in (a quick Monte Carlo:
        random cards for them and for the rest of the board)."""
        others = len(self.live) - 1
        if others <= 0:
            return 1.0
        known = set(self.hole[i]) | set(self.board)
        rest = [c for c in new_deck() if c not in known]
        wins = 0.0
        need = 5 - len(self.board)
        for _ in range(trials):
            draw = rng.sample(rest, need + 2 * others)
            board = self.board + draw[:need]
            mine = evaluate(self.hole[i] + board)
            best_other = max(evaluate(draw[need + 2 * k:need + 2 * k + 2] + board)
                             for k in range(others))
            if mine > best_other:
                wins += 1
            elif mine == best_other:
                wins += 0.5
        return wins / trials


def computer_move(hand, i, rng):
    """A reasonable player: bets and raises with strong hands, calls when the price is
    right (pot odds), checks when it's free, folds the rest; now and then a bluff.
    Returns (action, amount)."""
    opts = hand.options(i)
    p = hand.strength(i, rng, 150 if hand.street else 100)
    call = opts["call"]
    pot = hand.pot()
    rr = opts["raise"]
    n = len(hand.live)
    fair = 1.0 / n                               # what an average hand wins
    if rr is not None and (p > fair * 1.9 or (p > fair * 1.4 and rng.random() < 0.35)
                           or rng.random() < 0.04):
        size = int(pot * (0.5 + rng.random() * 0.5)) + hand.current
        amount = max(rr[0], min(rr[1], size))
        if p > 0.85 and rng.random() < 0.3:
            amount = rr[1]
        return "raise", amount
    if call <= 0:
        return "check", None
    odds = call / float(pot + call)
    if p >= odds * 1.1 or (p > fair and call <= hand.big):
        return "call", None
    return "fold", None
