"""One: the shedding card game for 2-4 (rules in one_rules.py), against people, the computer,
or both.

Games > One > Join asks "Wait for Others" (the queue: it starts when four are waiting, or on
Start Now with two or three) or "vs Computer..." (1-3 computer players, and it starts at
once). A player who leaves is replaced by the computer, so the others can finish; the game
ends when no people are left.

The table (one window a player, a dynamic id; Caps.GRID clients):

    +---------------------------------------------------------------------------------+
    | > bob            5 cards   20 | [back][top]  | the play-by-play and chat       |
    |   Computer 1     7 cards    0 |  Colour: Red |                                 |
    | Your turn: play a card, or click the pile... |                                 |
    | Your score: 0. First to 500 wins.            |                                 |
    | [your hand: 12 x 2 cards, cyan-framed when they can be played]  [<]   |           |
    |                                                                 [>]   | [type ] |
    | [Draw] [Pass] [One!] [Catch!]      [Next Round]                       | [Leave] |
    +---------------------------------------------------------------------------------+

The others are listed in the order they play next (">" the one whose turn it is). Click a
card to play it; a Wild asks for its colour; a Wild Draw Four played at you asks "Challenge
or Draw 4". One! calls your last card (on your turn with two, or just after playing down to
one); Catch! catches someone who forgot. The cards are tiles in resource slot RESOURCE_SLOT,
drawn in one_art.py.
"""

import asyncio
import os
import random
import time
import zlib

from ..protocol import Caps, GFlag, WFlag, GRID_MARK1, clean_text
from ..ui import Button, Grid, Label, TextBox, TextView, Window, add_buttons, MARGIN
from .base import Game
from .one_art import TILES, TILE_W, TILE_H, T_BACK, COLOURS_USED, tile
from .one_rules import (Round, RulesError, COLOURS, COLOUR_NAMES, TARGET, WILD4, sort_key,
                        best_colour, computer_choice)

RESOURCE_SLOT = 8                # (1 is chess's; 2-7 the Art Gallery's)
TILES_KEY = "one %08x" % zlib.crc32(TILES)       # (a new key when the art is edited)
COMPUTER_NAMES = ["Computer 1", "Computer 2", "Computer 3"]
CHAT_MAX = 120

WIN_X, WIN_Y, WIN_W, WIN_H = 4, 18, 624, 134
HAND_X, HAND_Y, HAND_COLS, HAND_ROWS = 8, 60, 12, 2
PAGE = HAND_COLS * HAND_ROWS
PILES_X, PILES_Y = 272, 2
RIGHT_X, RIGHT_W = 416, 200
MARK_PLAY, MARK_OTHER = 15, 9    # cyan: a card you can play
DECK_XY = (PILES_X, PILES_Y)     # where cards fly from and to (client-area pixels)
PILE_XY = (PILES_X + TILE_W, PILES_Y)
FLY_FRAMES = int(os.environ.get("MEGANET_ONE_FLY_FRAMES", 14))  # a card's flight: 0.28 s
                                 # (Caps.SPRITES clients; the variable slows it down for tests)
FLY_GAP = 0.04                   # between one flight and the next (cards drawn one by one)


class Seat:
    """A place at the table: a person (player) or the computer (player None)."""

    def __init__(self, name, player=None):
        self.name = name
        self.player = player
        self.score = 0
        self.page = 0
        self.order = []          # the hand's indexes as shown, sorted
        self.dialog = None       # "colour" / "challenge": the question window up
        self.dialog_win = None
        self.win = None
        # flying cards (Caps.SPRITES): what the table holds back until a card lands
        self.cells_at = {}       # id(card) -> its cell on the page shown
        self.rows_at = {}        # another seat -> its row in the list
        self.pile_tile = 0       # the top card's tile as last shown
        self.hold_pile = None    # the tile to keep showing until a card lands on the pile
        self.pile_flying = 0     # cards on their way to the pile
        self.hidden = set()      # id(card)s on their way to the hand: an empty cell till then
        self.fly_free = 0.0      # when the last flight scheduled ends
        self.fly_n = 1           # the server sprite the last flight used

    def reset_flights(self):
        self.hold_pile, self.pile_flying = None, 0
        self.hidden.clear()

    @property
    def computer(self):
        return self.player is None


class One(Game):
    name = "One"
    description = ("Match the colour or the number, and call One! on your last card. "
                   "2-4 players: wait for others, or play the computer.")
    min_players = 2
    max_players = 4
    computer = True
    needs_caps = Caps.GRID
    tick_interval = 0.25
    BOT_DELAY = 1.5              # seconds the computer waits before it moves
    CATCH_DELAY = 2.5            # ... before it catches someone who didn't call One!
    CATCH_CHANCE = 0.5
    CHALLENGE_CHANCE = 0.25      # how often it challenges a Wild Draw Four

    # ---- setting up ----

    def start(self, players):
        self.rng = random.Random()
        seats = [Seat(p.name, p) for p in players]
        seats += [Seat(n) for n in COMPUTER_NAMES[:max(0, min(self.computers,
                                                                 self.max_players - len(seats)))]]
        self.rng.shuffle(seats)
        self.seats = seats
        self.dealer = self.rng.randrange(len(seats))
        self.round = None
        self.winner = None           # the Seat that won the game (to TARGET)
        for s in self.people():
            s.player.session.send_resource(RESOURCE_SLOT, TILES_KEY, TILES, title=self.name)
            self._window(s)
        self.tell("* %s sit down to play One. First to %d points wins."
                  % (", ".join(s.name for s in seats), TARGET))
        players[0].session.log("one: %s" % ", ".join(s.name for s in seats))
        self.deal()

    def people(self):
        return [s for s in self.seats if s.player is not None]

    def seat_of(self, player):
        return next((s for s in self.seats if s.player is player), None)

    def _window(self, s):
        p = s.player
        win = self.window(p, "One", WIN_X, WIN_Y, WIN_W, WIN_H)
        s.others = [win.add(Label(MARGIN, 2 + 10 * i, 256, 10, "")) for i in range(3)]
        s.piles = win.add(Grid(PILES_X, PILES_Y, 2, 1, TILE_W, TILE_H, RESOURCE_SLOT,
                               marks=(MARK_PLAY, MARK_OTHER)))
        s.colour = win.add(Label(PILES_X, PILES_Y + TILE_H + 4, 136, 10, ""))
        s.status = win.add(Label(MARGIN, 36, 400, 10, "", flags=GFlag.BOLD))
        s.status2 = win.add(Label(MARGIN, 46, 400, 10, ""))
        s.hand = win.add(Grid(HAND_X, HAND_Y, HAND_COLS, HAND_ROWS, TILE_W, TILE_H,
                              RESOURCE_SLOT, marks=(MARK_PLAY, MARK_OTHER)))
        x = HAND_X + HAND_COLS * TILE_W + 2
        s.prev_b = win.add(Button(x, HAND_Y, 14, 20, "<", GFlag.DISABLED,
                                  on_click=lambda b: self.page(s, -1)))
        s.next_b = win.add(Button(x, HAND_Y + 24, 14, 20, ">", GFlag.DISABLED,
                                  on_click=lambda b: self.page(s, 1)))
        y = WIN_H - 20
        s.draw_b = win.add(Button(MARGIN, y, 64, 16, "Draw", on_click=lambda b: self.draw(s)))
        s.pass_b = win.add(Button(80, y, 64, 16, "Pass", on_click=lambda b: self.pass_(s)))
        s.one_b = win.add(Button(152, y, 64, 16, "One!", on_click=lambda b: self.call(s)))
        s.catch_b = win.add(Button(224, y, 72, 16, "Catch!", on_click=lambda b: self.catch(s)))
        s.again_b = win.add(Button(304, y, 104, 16, "Next Round", GFlag.DISABLED,
                                   on_click=lambda b: self.again(s)))
        s.chat = win.add(TextView(RIGHT_X, 2, RIGHT_W, 92))
        s.entry = win.add(TextBox(RIGHT_X, 98, 148, 12))
        win.add(Button(RIGHT_X + 152, 96, 48, 16, "Send", GFlag.DEFAULT,
                       on_click=lambda b: self.say(s)))
        win.add(Button(RIGHT_X + RIGHT_W - 72, y, 72, 16, "Leave",
                       on_click=lambda b: self.quit(s)))
        s.win = win
        self.show(p, win)

    # ---- rounds ----

    def deal(self):
        self.round = Round([s.name for s in self.seats], self.dealer, self.rng)
        self.seen = 0                # round.events already told
        self.scored = False
        self.unsafe_seen = None
        self.unsafe_since = 0.0
        self.catch_tried = False
        self.moves_seen = 0
        for s in self.seats:
            s.page = 0
            s.reset_flights()
        self.tell("* New round: %s deals." % self.seats[self.dealer].name)
        self.sync()

    def sync(self):
        """After any change: the play-by-play, the scores, every table, the questions."""
        r = self.round
        self.last = time.monotonic()
        for line in r.events[self.seen:]:
            self.tell(line)
        self.seen = len(r.events)
        if r.unsafe != self.unsafe_seen:
            self.unsafe_seen = r.unsafe
            self.unsafe_since = self.last
            self.catch_tried = False
        if r.over and not self.scored:
            self.scored = True
            won = self.seats[r.winner]
            won.score += r.points
            for t in self.people():             # (the bank: a round played)
                if t.player in self.players:
                    self.credit(t.player.session, "game played")
            if won.score >= TARGET:
                self.winner = won
                self.tell("* %s wins the game with %d points!" % (won.name, won.score))
                if won.player is not None and won.player in self.players:
                    beaten = [t.player.session for t in self.people() if t is not won]
                    self.credit(won.player.session, "game won",
                                beat=beaten[0] if len(beaten) == 1 else None)
            self.tell("* Scores: " + ", ".join("%s %d" % (s.name, s.score) for s in self.seats))
            if self.people():
                self.people()[0].player.session.log(
                    "one: %s won a round (+%d)%s" % (won.name, r.points,
                                                    ", and the game" if self.winner else ""))
        moves = r.moves[self.moves_seen:]
        self.moves_seen = len(r.moves)
        for i, s in enumerate(self.seats):
            if s.player is not None and s.player in self.players:
                flights = self._flights(i, s, moves)
                self.draw_table(i, s)
                self._schedule(i, s, flights)
                self.ask(i, s)

    # ---- cards flying (Caps.SPRITES clients): the table holds them back until they land ----

    def _flies(self, s):
        return bool(s.player.session.caps & Caps.SPRITES) and s.win is not None and s.win.shown

    def _cell_xy(self, cell):
        if cell is None:                 # (not on the page shown: the hand's far end)
            cell = HAND_COLS - 1
        return (HAND_X + cell % HAND_COLS * TILE_W, HAND_Y + cell // HAND_COLS * TILE_H)

    @staticmethod
    def _row_xy(s, seat):
        return (MARGIN + 104, 10 * s.rows_at.get(seat, 0))

    def _flights(self, i, s, moves):
        """Before the table is drawn: the flights `moves` make for seat i's player, with the
        pile and the hand held back. A hand's target is settled after (None here)."""
        if not moves or not self._flies(s):
            return []
        out = []
        for kind, seat, card in moves:
            if kind == "play":
                src = (self._cell_xy(s.cells_at.get(id(card))) if seat == i
                       else self._row_xy(s, seat))
                if s.hold_pile is None:
                    s.hold_pile = s.pile_tile
                s.pile_flying += 1
                out.append((tile(card), src, PILE_XY, "pile", None))
            elif seat == i:
                s.hidden.add(id(card))
                out.append((tile(card), DECK_XY, None, "hand", card))
            else:
                out.append((T_BACK, DECK_XY, self._row_xy(s, seat), None, None))
        return out

    def _schedule(self, i, s, flights):
        if not flights:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:                     # (no loop: nothing flies, nothing held)
            s.reset_flights()
            return self.draw_table(i, s)
        now = time.monotonic()
        for t, src, dst, what, card in flights:
            if dst is None:                      # into the hand: its cell now
                dst = self._cell_xy(s.cells_at.get(id(card)))
            start = max(now, s.fly_free)
            land = start + FLY_FRAMES / 50
            s.fly_free = land + FLY_GAP
            loop.call_later(start - now, self._send_fly, s, t, src, dst)
            loop.call_later(land - now, self._landed, s, what, card)
        return None

    def _send_fly(self, s, t, src, dst):
        if not self.over and s.player is not None and s.player in self.players:
            s.fly_n ^= 1                 # (the two sprites in turn: one may still be landing)
            s.player.session.fly(s.win, RESOURCE_SLOT, t * TILE_W * TILE_H, TILE_W // 2,
                                 TILE_H, src, dst, FLY_FRAMES, COLOURS_USED, step=2,
                                 n=s.fly_n)

    def _landed(self, s, what, card):
        if what == "pile":
            s.pile_flying = max(0, s.pile_flying - 1)
            if not s.pile_flying:
                s.hold_pile = None
        elif what == "hand":
            s.hidden.discard(id(card))
        else:
            return
        if (not self.over and self.round is not None and s.player is not None
                and s.player in self.players):
            self.draw_table(self.seats.index(s), s)

    def draw_table(self, i, s):
        r = self.round
        hand = r.hands[i]
        n = len(self.seats)
        order = [(i + r.direction * k) % n for k in range(1, n)]
        s.rows_at = {j: row for row, j in enumerate(order)}
        for label, j in zip(s.others, order + [None] * 3):
            if j is None:
                text = ""
            else:
                o = self.seats[j]
                k = len(r.hands[j])
                text = "%s%-12s %2d card%s %4d%s" % (
                    ">" if j == r.turn and not r.over else " ", o.name[:12], k,
                    "s" if k != 1 else " ", o.score, "  One!" if j in r.called and k == 1
                    else "")
            self._put(label, text)
        top = tile(r.top, r.colour if r.top.wild else None)
        s.pile_tile = top if s.hold_pile is None else s.hold_pile
        s.piles.set_cells([T_BACK, s.pile_tile])
        self._put(s.colour, "Colour: %s" % COLOUR_NAMES.get(r.colour, "?"))
        playable = set(r.playable(i))
        s.order = sorted(range(len(hand)), key=lambda k: sort_key(hand[k]))
        pages = max(1, (len(hand) + PAGE - 1) // PAGE)
        s.page = min(s.page, pages - 1)
        shown = s.order[s.page * PAGE:(s.page + 1) * PAGE]
        s.cells_at = {id(hand[k]): n for n, k in enumerate(shown)}
        cells = [0 if id(hand[k]) in s.hidden else
                 tile(hand[k]) | (GRID_MARK1 if k in playable else 0) for k in shown]
        s.hand.set_cells(cells + [0] * (PAGE - len(cells)))
        s.prev_b.enable(s.page > 0)
        s.next_b.enable(s.page < pages - 1)
        mine = i == r.turn and not r.over
        s.draw_b.enable(mine and r.waiting is None)
        s.pass_b.enable(mine and r.waiting == "drawn")
        s.one_b.enable(not r.over and i not in r.called and (
            r.unsafe == i or (mine and len(hand) == 2 and r.waiting in (None, "drawn"))))
        s.catch_b.enable(r.unsafe is not None and r.unsafe != i)
        s.again_b.enable(r.over)
        self._put(s.again_b, "New Game" if self.winner else "Next Round")
        self._put(s.status, self.status_line(i)[:50])
        if self.winner:
            line2 = "Click New Game to play again from 0."
        elif r.over:
            line2 = "Click Next Round to deal again."
        else:
            line2 = "Your score: %d. First to %d wins.%s" % (
                s.score, TARGET, "  (page %d of %d)" % (s.page + 1, pages) if pages > 1
                else "")
        self._put(s.status2, line2[:50])

    def status_line(self, i):
        r = self.round
        if r.over:
            won = self.seats[r.winner]
            who = "You win" if r.winner == i else "%s wins" % won.name
            if self.winner:
                return "%s the game!" % ("You win" if self.winner is self.seats[i]
                                         else "%s wins" % self.winner.name)
            return "%s the round: +%d points." % (who, r.points)
        if r.waiting == "colour":
            return ("Name the colour for your Wild." if r.wild_by == i else
                    "%s is naming a colour." % self.seats[r.wild_by].name)
        turn = self.seats[r.turn].name
        if r.turn != i:
            if r.waiting == "challenge":
                return "%s: challenge or draw 4?" % turn
            return "%s's turn." % turn
        if r.waiting == "challenge":
            return "Challenge the Wild Draw Four, or draw 4."
        if r.waiting == "drawn":
            return "You drew %s: play it, or Pass." % (r.drawn,)
        if not r.playable(i):
            return "Your turn: nothing goes. Draw a card."
        return "Your turn: play a card, or draw."

    @staticmethod
    def _put(gadget, text):
        if gadget.text != text:
            if gadget.shown:
                gadget.set_text(text)
            else:
                gadget.text = text

    def tell(self, line):
        for s in self.people():
            if s.player in self.players:
                s.chat.append(line)

    # ---- questions: the colour for a Wild, a Wild Draw Four's challenge ----

    def ask(self, i, s):
        r = self.round
        want = None
        if not r.over and r.waiting == "colour" and r.wild_by == i:
            want = "colour"
        elif not r.over and r.waiting == "challenge" and r.turn == i:
            want = "challenge"
        if s.dialog == want:
            return
        self._close_dialog(s)
        if want == "colour":
            win = Window.centred("Name a Colour", 320, 40, flags=WFlag.MODAL | WFlag.MOVABLE)
            win.add(Label(MARGIN, 4, 304, 10, "The colour to match next:",
                          flags=GFlag.CENTRE))
            add_buttons(win, [(COLOUR_NAMES[c], (lambda b, c=c: self.colour(s, c)),
                               GFlag.DEFAULT if c == best_colour(r.hands[i], self.rng) else 0)
                              for c in COLOURS], centre=True)
        elif want == "challenge":
            by = self.seats[r.four[0]].name
            win = Window.centred("Wild Draw Four", 320, 52, flags=WFlag.MODAL | WFlag.MOVABLE)
            for k, line in enumerate(("%s played a Wild Draw Four." % by,
                                      "Challenge it, or draw 4?")):
                win.add(Label(MARGIN, 4 + 12 * k, 304, 10, line[:38], flags=GFlag.CENTRE))
            add_buttons(win, [("Challenge", lambda b: self.answer_four(s, True), 0),
                              ("Draw 4", lambda b: self.answer_four(s, False), GFlag.DEFAULT)],
                        centre=True)
        else:
            return
        s.dialog, s.dialog_win = want, win
        s.player.windows.append(win)             # (closed with the game's windows)
        win.show(s.player.session)

    def _close_dialog(self, s):
        win, s.dialog, s.dialog_win = s.dialog_win, None, None
        if win is not None:
            win.close()
            if s.player is not None and win in s.player.windows:
                s.player.windows.remove(win)

    # ---- what people do ----

    def _index(self, s):
        return self.seats.index(s)

    def _ok(self, s):
        return (not self.over and s.player is not None and s.player in self.players
                and self.round is not None)

    def _try(self, s, fn, *args):
        """Run a rules move for seat s; a refusal is shown to them."""
        try:
            fn(self._index(s), *args)
        except RulesError as e:
            s.player.session.toast(str(e))
            return False
        self.sync()
        return True

    def on_select(self, player, window, gadget, index, double):
        s = self.seat_of(player)
        if s is None or not self._ok(s):
            return None
        if gadget is s.piles:
            if index == 0 and self.round.waiting is None and self.round.turn == self._index(s):
                return self.draw(s)
            return None
        if gadget is not s.hand:
            return None
        k = s.page * PAGE + index
        if k >= len(s.order):
            return None
        self._try(s, self.round.play, s.order[k])
        return None

    def draw(self, s):
        if self._ok(s):
            self._try(s, self.round.draw)

    def pass_(self, s):
        if self._ok(s):
            self._try(s, self.round.pass_turn)

    def colour(self, s, c):
        if self._ok(s) and s.dialog == "colour":
            self._close_dialog(s)
            self._try(s, self.round.choose_colour, c)

    def answer_four(self, s, yes):
        """Challenge a Wild Draw Four (yes) or take the 4. (Not `challenge`: that's the
        class flag for a game with a challenge lobby.)"""
        if self._ok(s) and s.dialog == "challenge":
            self._close_dialog(s)
            self._try(s, self.round.challenge, yes)

    def call(self, s):
        if self._ok(s) and self.round.call_one(self._index(s)):
            self.sync()

    def catch(self, s):
        if self._ok(s) and self.round.catch(self._index(s)) is not None:
            self.sync()

    def page(self, s, step):
        if self._ok(s):
            s.page = max(0, s.page + step)
            self.draw_table(self._index(s), s)

    def again(self, s):
        if not self._ok(s) or not self.round.over:
            return None
        if self.winner:
            for t in self.seats:
                t.score = 0
            self.winner = None
            self.tell("* %s starts a new game." % s.name)
        self.dealer = (self.dealer + 1) % len(self.seats)
        self.deal()
        return None

    def say(self, s):
        text = clean_text(s.entry.value).strip()[:CHAT_MAX]
        if not text or not self._ok(s):
            return None
        s.entry.set_text("")
        self.tell("%s: %s" % (s.name, text))
        return None

    def quit(self, s):
        if s.player is None:
            return None
        session = s.player.session
        self.leave(s.player)
        if self._lobby is not None:
            return self._lobby.open(session)
        return None

    # ---- the computer ----

    def tick(self):
        r = self.round
        if self.over or r is None or r.over:
            return
        now = time.monotonic()
        if (r.unsafe is not None and not self.catch_tried and not self.seats[r.unsafe].computer
                and now - self.unsafe_since >= self.CATCH_DELAY):
            self.catch_tried = True
            catchers = [j for j, t in enumerate(self.seats) if t.computer and j != r.unsafe]
            if catchers and self.rng.random() < self.CATCH_CHANCE:
                r.catch(self.rng.choice(catchers))
                return self.sync()
        seat = r.wild_by if r.waiting == "colour" else r.turn
        if not self.seats[seat].computer or now - self.last < self.BOT_DELAY:
            return
        hand = r.hands[seat]
        if r.waiting == "colour":
            r.choose_colour(seat, best_colour(hand, self.rng))
        elif r.waiting == "challenge":
            r.challenge(seat, self.rng.random() < self.CHALLENGE_CHANCE)
        else:
            move = computer_choice(r, seat, self.rng)
            if move[0] == "play":
                if len(hand) == 2:
                    r.call_one(seat)
                r.play(seat, move[1])
            elif move[0] == "pass":
                r.pass_turn(seat)
            else:
                r.draw(seat)
        self.sync()

    # ---- leaving ----

    def on_leave(self, player):
        s = self.seat_of(player)
        if s is None:
            return
        self._close_dialog(s)
        s.player = None
        if not any(t.player in self.players for t in self.seats if t.player is not None):
            return self.end()
        self.tell("* %s left: the computer plays their cards." % s.name)
        if self.round is not None:
            self.sync()
        return None
