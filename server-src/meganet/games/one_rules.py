"""The rules of One (games/one.py), with no windows: a shedding card game for 2-4 players,
played by the usual official rules for this kind of game.

The deck: 108 cards. In each of four colours (Red, Yellow, Green, Blue) one 0, two each of
1-9, two Skips, two Reverses and two Draw Twos; then four Wilds and four Wild Draw Fours.

A round: the dealer deals 7 each and turns up the top card of the rest (a Wild Draw Four goes
back and another is turned). Play starts left of the dealer and goes round; on your turn play
a card that matches the top card's colour, number or symbol, or a Wild; or draw one, and if
that one can be played you may play it (only it) at once, or keep it and pass.

    Skip           the next player misses their turn
    Reverse        play changes direction (with two players it's a Skip)
    Draw Two       the next player draws 2 and misses their turn
    Wild           you name the colour to match next
    Wild Draw Four you name the colour; the next player draws 4 and misses their turn. It's
                   only allowed when you hold nothing of the colour being matched, but you
                   may bluff: the next player may challenge. Guilty: you draw the 4 instead
                   (and they play as usual). Innocent: they draw 6 and miss their turn.

The first card turned up acts on the first player: Skip skips them, Draw Two makes them draw 2
and skips them, Reverse makes the dealer go first the other way, and Wild lets the first
player name the colour before playing.

Down to your last card, call "One!" (before or just after playing your second-to-last). Not
called, and someone catches you before the next player has acted: you draw 2.

The first to play their last card wins the round and scores the cards left in the others'
hands: a number its face value, Skip / Reverse / Draw Two 20, Wild / Wild Draw Four 50 (a
Draw Two or Wild Draw Four that ends a round still makes the next player draw first). The
first to TARGET points wins the game. When the draw pile runs out, the discards (all but the
top card) are shuffled into a new one.
"""

import random

COLOURS = "RYGB"
COLOUR_NAMES = {"R": "Red", "Y": "Yellow", "G": "Green", "B": "Blue"}
FACES = "0123456789SRD"          # numbers, Skip, Reverse, Draw Two (coloured cards)
WILD, WILD4 = "W", "F"           # (no colour)
FACE_NAMES = {"S": "Skip", "R": "Reverse", "D": "Draw Two", WILD: "Wild",
              WILD4: "Wild Draw Four"}
HAND = 7
TARGET = 500


class Card(tuple):
    """(colour, face): colour one of COLOURS, or None for a Wild / Wild Draw Four."""

    def __new__(cls, colour, face):
        return super().__new__(cls, (colour, face))

    colour = property(lambda self: self[0])
    face = property(lambda self: self[1])

    @property
    def wild(self):
        return self.colour is None

    @property
    def points(self):
        if self.wild:
            return 50
        return int(self.face) if self.face.isdigit() else 20

    def __str__(self):
        if self.wild:
            return FACE_NAMES[self.face]
        return "%s %s" % (COLOUR_NAMES[self.colour], FACE_NAMES.get(self.face, self.face))

    def __repr__(self):
        return "Card(%r, %r)" % (self.colour, self.face)


def sort_key(card):
    return (COLOURS.index(card.colour) if not card.wild else 4,
            FACES.index(card.face) if not card.wild else (card.face == WILD4))


def deck():
    cards = []
    for c in COLOURS:
        cards.append(Card(c, "0"))
        for f in FACES[1:]:
            cards += [Card(c, f), Card(c, f)]
    cards += [Card(None, WILD) for _ in range(4)] + [Card(None, WILD4) for _ in range(4)]
    assert len(cards) == 108
    return cards


class RulesError(Exception):
    """A move the rules don't allow (the message says why)."""


class Round:
    """One round. Seats are 0..n-1 in playing order (left = +1). The state between moves:

        turn        whose turn it is
        colour      the colour to match (a Wild's named one)
        waiting     None, or what `turn` must answer first: "colour" (name a colour for the
                    Wild just played: chosen by `turn`), "challenge" (the Wild Draw Four just
                    played at `turn`), "drawn" (`turn` drew a card that can be played: play
                    it or pass)
        unsafe      the seat down to one card that hasn't called One!, while it can still be
                    caught (until the next player acts); None otherwise
        winner      the seat that went out (the round is over)
    Every change is described in `events` (strings, oldest first) for the table to show."""

    def __init__(self, names, dealer, rng=None):
        self.names = list(names)
        self.n = len(self.names)
        if not 2 <= self.n <= 4:
            raise ValueError("2-4 players")
        self.rng = rng or random.Random()
        self.dealer = dealer % self.n
        self.direction = 1
        self.hands = [[] for _ in range(self.n)]
        self.pile = deck()
        self.rng.shuffle(self.pile)
        self.discard = []
        self.events = []
        self.waiting = None
        self.wild_by = None          # who played the Wild waiting for a colour
        self.drawn = None            # the card drawn that may be played
        self.four = None             # the Wild Draw Four challenge: (by, colour before)
        self.called = set()          # seats that have called One! for their last card
        self.unsafe = None
        self.winner = None
        self.points = 0
        for _ in range(HAND):
            for i in range(self.n):
                self.hands[(self.dealer + 1 + i) % self.n].append(self.pile.pop())
        while True:                  # the first card: never a Wild Draw Four
            top = self.pile.pop()
            if top.face != WILD4:
                break
            self.pile.insert(self.rng.randrange(len(self.pile) + 1), top)
        self.discard.append(top)
        self.colour = top.colour
        first = self.next_seat(self.dealer)
        self.say("%s turns up %s." % (self.names[self.dealer], top))
        if top.face == "S":
            self.say("%s is skipped." % self.names[first])
            first = self.next_seat(first)
        elif top.face == "R":        # (two players: the other is skipped; the same thing)
            self.direction = -1
            first = self.dealer
            self.say("%s goes first, the other way." % self.names[first])
        elif top.face == "D":
            self.give(first, 2)
            first = self.next_seat(first)
        self.turn = first
        self.moves = []              # cards moving from now on: ("play" | "draw", seat, card)
        self.opening_wild = top.face == WILD
        if self.opening_wild:
            self.waiting = "colour"
            self.wild_by = first

    # ---- looking ----

    @property
    def top(self):
        return self.discard[-1]

    @property
    def over(self):
        return self.winner is not None

    def next_seat(self, seat, steps=1):
        return (seat + self.direction * steps) % self.n

    def matches(self, card):
        """Could `card` go on the pile now (Wild Draw Four: always, if you risk it)?"""
        return card.wild or card.colour == self.colour or card.face == self.top.face

    def four_allowed(self, seat):
        """A Wild Draw Four from `seat` is honest: nothing of the colour being matched."""
        return not any(c.colour == self.colour for c in self.hands[seat])

    def playable(self, seat):
        """The indexes in seat's hand it may play now."""
        if self.over or seat != self.turn or self.waiting not in (None, "drawn"):
            return []
        hand = self.hands[seat]
        if self.waiting == "drawn":
            return [i for i, c in enumerate(hand) if c is self.drawn]
        return [i for i, c in enumerate(hand) if self.matches(c)]

    def say(self, text):
        self.events.append(text)

    # ---- moves ----

    def _check_turn(self, seat, waiting=None):
        if self.over:
            raise RulesError("The round is over.")
        if seat != self.turn:
            raise RulesError("It isn't your turn.")
        if self.waiting != waiting:
            raise RulesError({"colour": "Name a colour first.",
                              "challenge": "Challenge the Wild Draw Four or draw 4 first.",
                              "drawn": "Play the card you drew or pass."}.get(
                                  self.waiting, "You can't do that now."))

    def _acted(self, seat):
        """`seat` did something: whoever was down to one card uncalled is safe now."""
        if self.unsafe is not None and self.unsafe != seat:
            self.unsafe = None

    def play(self, seat, index):
        """Play hand[index]. A Wild then waits for its colour (choose_colour)."""
        if self.waiting == "drawn" and seat == self.turn and not self.over:
            self.waiting = None
            hand = self.hands[seat]
            if not 0 <= index < len(hand) or hand[index] is not self.drawn:
                self.waiting = "drawn"
                raise RulesError("You may only play the card you drew.")
        else:
            self._check_turn(seat)
        hand = self.hands[seat]
        if not 0 <= index < len(hand):
            raise RulesError("No such card.")
        card = hand[index]
        if not self.matches(card):
            raise RulesError("%s doesn't go on %s." % (card, self.describe_top()))
        self._acted(seat)
        self.drawn = None
        honest = self.four_allowed(seat) if card.face == WILD4 else True
        colour_before = self.colour
        del hand[index]
        self.discard.append(card)
        self.moves.append(("play", seat, card))
        self.say("%s plays %s." % (self.names[seat], card))
        if len(hand) == 1:
            if seat not in self.called:
                self.unsafe = seat
        else:
            self.called.discard(seat)
        if not hand:
            return self._out(seat, card)
        if card.wild:
            self.waiting = "colour"
            self.wild_by = seat
            self.four = (seat, colour_before, honest) if card.face == WILD4 else None
            return None
        self.colour = card.colour
        self._after(seat, card)
        return None

    def _after(self, seat, card):
        """The turn passes on after `seat` played `card` (its colour settled)."""
        nxt = self.next_seat(seat)
        if card.face == "S":
            self.say("%s is skipped." % self.names[nxt])
            nxt = self.next_seat(nxt)
        elif card.face == "R":
            self.direction = -self.direction
            if self.n == 2:
                nxt = seat
            else:
                nxt = self.next_seat(seat)
            self.say("Play goes the other way.")
        elif card.face == "D":
            self.give(nxt, 2)
            nxt = self.next_seat(nxt)
        self.turn = nxt
        self.waiting = None

    def choose_colour(self, seat, colour):
        if self.over or self.waiting != "colour" or seat != self.wild_by:
            raise RulesError("There's no colour to name now.")
        if colour not in COLOURS:
            raise RulesError("Pick Red, Yellow, Green or Blue.")
        self.colour = colour
        self.waiting = None
        self.wild_by = None
        self.say("%s names %s." % (self.names[seat], COLOUR_NAMES[colour]))
        card = self.top
        if self.opening_wild:        # (the first card: the first player names it, then plays)
            self.opening_wild = False
            return
        if card.face == WILD4:
            self.turn = self.next_seat(seat)
            self.waiting = "challenge"
        else:
            self.turn = self.next_seat(seat)

    def challenge(self, seat, yes):
        """The player a Wild Draw Four was played at: challenge it (yes) or take the 4."""
        self._check_turn(seat, "challenge")
        self._acted(seat)
        by, before, honest = self.four
        self.four = None
        self.waiting = None
        if not yes:
            self.give(seat, 4)
            self.turn = self.next_seat(seat)
            return None
        if honest:
            self.say("%s challenges: %s had no %s. %s draws 6." % (
                self.names[seat], self.names[by], COLOUR_NAMES[before], self.names[seat]))
            self.give(seat, 6, quiet=True)
            self.turn = self.next_seat(seat)
        else:
            self.say("%s challenges: %s had %s! %s draws 4." % (
                self.names[seat], self.names[by], COLOUR_NAMES[before], self.names[by]))
            self.give(by, 4, quiet=True)
        return honest

    def draw(self, seat):
        """Draw one. Playable: waiting "drawn" (play it or pass); otherwise the turn passes.
        Returns the card (None if there was nothing left to draw)."""
        self._check_turn(seat)
        self._acted(seat)
        got = self._take(seat, 1)
        self.say("%s draws a card." % self.names[seat])
        if not got:
            self.turn = self.next_seat(seat)
            return None
        card = got[0]
        if self.matches(card):
            self.waiting = "drawn"
            self.drawn = card
        else:
            self.turn = self.next_seat(seat)
        return card

    def pass_turn(self, seat):
        """Keep the card just drawn."""
        self._check_turn(seat, "drawn")
        self.waiting = None
        self.drawn = None
        self.say("%s keeps it." % self.names[seat])
        self.turn = self.next_seat(seat)

    def call_one(self, seat):
        """Call One!: with two cards on your turn (about to play one), or with one while you
        can still be caught. Returns True if it counted."""
        if self.over:
            return False
        hand = self.hands[seat]
        if (len(hand) == 2 and seat == self.turn) or self.unsafe == seat:
            self.called.add(seat)
            if self.unsafe == seat:
                self.unsafe = None
            self.say("%s calls One!" % self.names[seat])
            return True
        return False

    def catch(self, by):
        """`by` catches the player who didn't call One!: they draw 2. Returns the seat caught
        (None: nobody to catch)."""
        if self.over or self.unsafe is None or self.unsafe == by:
            return None
        who = self.unsafe
        self.unsafe = None
        self.say("%s catches %s without One! %s draws 2." % (
            self.names[by], self.names[who], self.names[who]))
        self.give(who, 2, quiet=True)
        return who

    # ---- cards moving ----

    def _take(self, seat, n):
        got = []
        for _ in range(n):
            if not self.pile:
                if len(self.discard) <= 1:
                    break
                top = self.discard.pop()
                self.pile = self.discard
                self.rng.shuffle(self.pile)
                self.discard = [top]
                self.say("The discards are shuffled into a new pile.")
            got.append(self.pile.pop())
        self.hands[seat] += got
        if hasattr(self, "moves"):   # (not the deal)
            self.moves += [("draw", seat, c) for c in got]
        if len(self.hands[seat]) > 1:
            self.called.discard(seat)
        return got

    def give(self, seat, n, quiet=False):
        got = self._take(seat, n)
        if not quiet:
            self.say("%s draws %d." % (self.names[seat], len(got)))
        return got

    def _out(self, seat, card):
        nxt = self.next_seat(seat)
        if card.face == "D":
            self.give(nxt, 2)
        elif card.face == WILD4:
            self.give(nxt, 4)
        self.winner = seat
        self.unsafe = None
        self.waiting = None
        self.points = sum(c.points for i, h in enumerate(self.hands) if i != seat for c in h)
        self.say("%s goes out and scores %d." % (self.names[seat], self.points))
        return self.points

    def describe_top(self):
        if self.top.wild:
            return "%s (%s)" % (self.top, COLOUR_NAMES[self.colour])
        return str(self.top)


# ---- the computer's play ----

def best_colour(hand, rng):
    counts = {c: 0 for c in COLOURS}
    for card in hand:
        if not card.wild:
            counts[card.colour] += 1
    top = max(counts.values())
    return rng.choice([c for c in COLOURS if counts[c] == top])


def computer_choice(rnd, seat, rng):
    """What the computer does on its turn: ("play", index), ("draw",) or ("pass",). It plays
    an honest game: a Wild Draw Four only when it holds nothing of the colour."""
    hand = rnd.hands[seat]
    options = rnd.playable(seat)
    options = [i for i in options
               if hand[i].face != WILD4 or rnd.four_allowed(seat)]
    if rnd.waiting == "drawn":
        return ("play", options[0]) if options else ("pass",)
    if not options:
        return ("draw",)
    nxt = rnd.next_seat(seat)
    danger = len(rnd.hands[nxt]) <= 2          # the next player is nearly out: attack them
    # lower ranks first. Usually: numbers (high first), then actions, keeping the Wilds;
    # against a player nearly out: Draw Four, Draw Two, Skip, Reverse, Wild, then numbers
    attack = {WILD4: 0, "D": 1, "S": 2, "R": 3, WILD: 4}

    def rank(i):
        c = hand[i]
        if danger:
            return (attack.get(c.face, 5), -c.points)
        if c.wild:
            return (2, c.face == WILD4)
        return (1 if c.face in "SRD" else 0, -c.points)
    return ("play", min(options, key=rank))
