"""Texas Hold'em: no-limit poker for 2-6 around a green felt table, for real credits (the
bank, bank.py), against people, the computer, or both. Rules: poker_rules.py.

Games > Texas Hold'em > Join: "Wait for Others" sits you at a table that has a free seat (or
waits for one to start: Start Now with two), or "vs Computer..." starts a table with 1-5
computer players. You bring BUY_MIN-BUY_MAX credits to the table (Buy Chips...); what's in
front of you when you leave goes back to your balance. People can sit down at a running
table with a free seat, and play goes on as they come and go; the computer's chips are the
house's.

Each hand you take part in earns the bank's "poker hand" credits (nothing extra for
winning: winning is its own reward). If the server stops, the chips you had at the start of
the hand go back to your balance (db.poker_chips). An overdue loan keeps you from the table.

The table (one window a player, a dynamic id; Caps.GRID clients). You sit at the bottom in
the middle; the others clockwise from there, three along the bottom and three along the top.
Each seat's second line is what they did, or for a few seconds what they said in the chat:

      Computer 2   980   bob        1,250  Computer 3 1,020 | Pot: 120
      Fold               Call 20           "nice hand"      | Blinds 5/10    Hand 12
     +--------------------------------------------------+   | the chat: what people say,
     |     [][]  (D)       [][]              [][]       |   | and the dealer's lines
     |  (chips) [] [] [] [] []                          |   | ("bob wins 120.")
     |     [][]            [][]              [][]       |   | Your turn (25 s): call 20
     +--------------------------------------------------+   | Your hand: Pair of Kings
      Computer 1   1,000   you      1,180  Computer 4   900 | [type here     ] [Send]
      Raise 40             Bet 40          Fold             |
     [Fold][Call 20][Raise][ 60 ][1/2][Pot][All In]          [Sit Out][Chips...][Leave]

RETURN sends the chat line (Send is the default button; Raise needs a click).

The table is a Grid of tiles (poker_art.py); the cards, the dealer button and the pot's chips
are drawn on its tiles for each viewer (TileCache). Cards fly from the dealer to the seats
and the board (Caps.SPRITES clients): each hole card on its own, round the table twice as a
dealer deals, then the flop, turn and river.
"""

import asyncio
import os
import random
import time
import zlib
from collections import OrderedDict

from .. import permissions as perms
from ..protocol import Caps, GFlag, Sound, WFlag, clean_text
from ..ui import (Button, Grid, Label, TextBox, TextView, Window, add_buttons, centre, closer,
                  MARGIN)
from .base import Game
from .poker_art import (TABLE, TABLE_TILES, TABLE_CELLS, N_TABLE, TILE_W, TILE_H, COLS,
                        CARD_COLOURS, STAR_COLOURS, compose, overlay_width)
from .poker_rules import Hand, RulesError, computer_move, evaluate, describe, short

RESOURCE_SLOT = 9                # (1 chess, 2-7 the Art Gallery, 8 One)
TABLE_KEY = "poker %08x" % zlib.crc32(TABLE)
N_TILES = 64                     # a grid's tiles: the table's, then the viewer's own
SEATS = 6
SMALL, BIG = 5, 10
BUY_MIN, BUY_MAX = 100, 1000
COMPUTER_CHIPS = 1000
COMPUTER_NAMES = ["Computer %d" % n for n in range(1, SEATS)]
TURN_SECS = 30                   # then the computer checks or folds for you
TIMEOUTS_OUT = 2                 # timeouts in a row before you're sat out
BOT_DELAY = 1.2
NEXT_HAND = float(os.environ.get("MEGANET_POKER_NEXT_HAND", 4.0))   # seconds between hands
                                                                     # (half without a showdown)
FLY_FRAMES = int(os.environ.get("MEGANET_POKER_FLY_FRAMES", 8))   # 0.16 s a card
FLY_GAP = 0.04
CPU_FOLDS = os.environ.get("MEGANET_POKER_CPU_FOLDS") == "1"   # (tests: you win every hand)
FLASH_SECS = float(os.environ.get("MEGANET_POKER_FLASH_SECS", 2.0))    # the winner's stars:
FLASH_EVERY = float(os.environ.get("MEGANET_POKER_FLASH_EVERY", 0.25))  # on, off, on... (tests:
                                                                        # EVERY = SECS: on)
STAR_FAT = 9                                 # the star: 9 x 9 fat pixels
STAR_PX = 2 * STAR_FAT
STAR_Y = (TILE_H - STAR_FAT) // 2            # its first row in its tile

CHAT_MAX = 120                   # characters a chat line
LOG_KEEP = 60                    # lines of it a newcomer sees
SAY_SECS = 6.0                   # a chat line shows at the seat this long
COMPUTER_CHAT = 0.3              # how often a computer says something when it might
BIG_POT = 200                    # (what's worth a remark)
WIN_LINES = ["Nice.", "I'll take that.", "Thank you!", "Read you like a book.", "Ship it!"]
LOSE_LINES = ["Nice hand.", "Ouch.", "Well played.", "I'll be back.", "Unlucky river..."]
ALL_IN_LINES = ["I'm all in!", "All of it.", "Let's gamble."]

WIN_W, WIN_H = 632, 171
TX, TY = 0, 24                   # the table grid in the window
PANEL_X, PANEL_W = 420, 212      # the right: the pot, the chat and the dealer's lines
# by place round the table (0 = you, then clockwise: three seats along the bottom, three
# along the top): the middle of the seat's two cards (table pixels) and its row of tiles
SEAT_X = [208, 80, 80, 208, 336, 336]
SEAT_ROW = [3, 3, 1, 1, 1, 3]
CARD_W = 24                      # screen pixels
BOARD_ROW = 2
CHIPS_AT = (2, 102)              # (row, x): the pot, left of the board


def hole_x(place, k):
    """Table x of a seat's card k (0 or 1): side by side, 2 pixels apart."""
    return SEAT_X[place] - CARD_W - 2 + k * (CARD_W + 2)


def button_x(place):
    """The dealer button sits beside the cards, on the side towards the table's middle."""
    c = SEAT_X[place]
    return c - CARD_W - 2 - 4 - 18 if c > 208 else c + CARD_W + 6


def board_x(k):
    return 4 * TILE_W + 4 + k * TILE_W


def label_at(place):
    """A seat's two lines (x, y, width): above the table for the top row, below it for the
    bottom row."""
    return SEAT_X[place] - 64 + TX, (2 if SEAT_ROW[place] == 1 else 136), 128


def cells_for(items):
    """{cell: [(what, dx), ...]} for items [(row, x, what), ...]: each drawn on every tile it
    covers."""
    out = {}
    for row, x, what in items:
        w = overlay_width(what)
        for col in range(x // TILE_W, (x + w - 1) // TILE_W + 1):
            if 0 <= col < COLS:
                out.setdefault(row * COLS + col, []).append((what, x - col * TILE_W))
    return out


def num(n):
    return "{:,}".format(n)


class TileCache:
    """One viewer's tiles past the table's: (base tile, ((what, dx), ...)) -> tile number,
    sent the first time it's needed; the least used goes when there's no room (never one on
    show)."""

    def __init__(self, session):
        self.session = session
        self.map = OrderedDict()
        self.free = list(range(N_TABLE, N_TILES))

    def get(self, base, items, keep):
        key = (base, tuple(items))
        if key in self.map:
            self.map.move_to_end(key)
            return self.map[key]
        if self.free:
            t = self.free.pop(0)
        else:
            old = next((k for k, v in self.map.items() if v not in keep), None)
            if old is None:
                old = next(iter(self.map))
            t = self.map.pop(old)
        self.session.send_resource_at(RESOURCE_SLOT, t * TILE_W * TILE_H,
                                      compose(TABLE_TILES[base], key[1]))
        self.map[key] = t
        return t


class Seat:
    """A place at the table: a person (player), the computer (player None, computer True),
    or empty (neither)."""

    def __init__(self, index):
        self.index = index
        self.name = ""
        self.player = None
        self.computer = False
        self.chips = 0
        self.sitting_out = False
        self.timeouts = 0
        self.acted = False            # did something themselves this hand (the bank pays)
        self.view = None              # a person's window and what it shows
        self.said = ""                # their last chat line, shown at the seat until
        self.said_until = 0.0

    @property
    def empty(self):
        return self.player is None and not self.computer

    @property
    def user_id(self):
        return self.player.session.user_id if self.player is not None else None

    def ready(self):
        return not self.empty and self.chips > 0 and not self.sitting_out


class View:
    """What one person's window holds."""

    def __init__(self, seat, session):
        self.seat = seat
        self.session = session
        self.cache = TileCache(session)
        self.hidden = set()           # cards still flying: ("hole", seat, k), ("board", k)
        self.fly_free = 0.0
        self.fly_n = 1
        self.flash = 0                # the winner's stars: which flash is on (see _flash)
        self.win = None
        self.buy_win = None


class Poker(Game):
    name = "Texas Hold'em"
    description = ("No-limit poker for 2-6 at a green felt table, played for your credits. "
                   "Wait for others, or play the computer. Each hand earns a credit or two.")
    min_players = 2
    max_players = SEATS
    computer = True
    needs_caps = Caps.GRID
    tick_interval = 0.25
    permission = perms.register("games.poker", "Play poker (credits)", like="games.play")

    # ---- joining: a seat and the credits for it ----

    @classmethod
    def join_problem(cls, session):
        bank = session.server.screens.bank
        problem = bank.blocked(session.user_id)
        if problem:
            return problem
        have = session.server.db.credits(session.user_id) or 0
        if have < BUY_MIN:
            return ("You need %s to sit down at the poker table; you have %s. See Areas > "
                    "Bank for how to earn more." % (bank_credits(BUY_MIN), bank_credits(have)))
        return None

    def open_seat(self, session):
        return (not self.over and any(s.empty for s in self.seats)
                and self.join_problem(session) is None)

    def start(self, players):
        self.rng = random.Random()
        self.seats = [Seat(i) for i in range(SEATS)]
        self.hand = None
        self.hand_no = 0
        self.button = None
        self.next_at = time.monotonic() + 1.0
        self.log = []                            # the chat so far (for people sitting down)
        self.events_seen = 0
        self.moves_seen = 0
        self.turn_since = 0.0
        self.ended_at = None
        order = list(range(SEATS))
        for p in players:
            self._seat(p, order.pop(0))
        for k in range(max(0, min(self.computers, SEATS - len(players)))):
            s = self.seats[order.pop(0)]
            s.computer, s.name, s.chips = True, COMPUTER_NAMES[k], COMPUTER_CHIPS
        players[0].session.log("poker: %s" % ", ".join(s.name for s in self.seats
                                                          if not s.empty))
        self.redraw()

    def sit_down(self, player):
        s = next(t for t in self.seats if t.empty)
        self._seat(player, s.index)
        self.tell("* %s sits down." % player.name)
        self.redraw()

    def _seat(self, player, i):
        s = self.seats[i]
        s.player, s.name, s.computer, s.chips = player, player.name, False, 0
        s.sitting_out, s.timeouts, s.said = False, 0, ""
        player.session.send_resource(RESOURCE_SLOT, TABLE_KEY, TABLE, title="Poker")
        s.view = View(s, player.session)
        self._window(s)
        self.ask_buy(s)

    def people(self):
        return [s for s in self.seats if s.player is not None]

    def seat_of(self, player):
        return next((s for s in self.seats if s.player is player), None)

    def bank(self):
        return self.people()[0].player.session.server.screens.bank if self.people() else None

    # ---- the window ----

    def _window(self, s):
        p, v = s.player, s.view
        x, y = centre(WIN_W, WIN_H)
        win = self.window(p, "Texas Hold'em", x, y, WIN_W, WIN_H)
        v.win = win
        v.grid = win.add(Grid(TX, TY, COLS, 5, TILE_W, TILE_H, RESOURCE_SLOT,
                              cells=TABLE_CELLS))
        v.labels = []
        for place in range(SEATS):
            lx, ly, lw = label_at(place)
            v.labels.append([win.add(Label(lx, ly + 10 * k, lw, 10, "", flags=GFlag.CENTRE))
                             for k in range(2)])
        # the panel at the right: the pot, the chat (and the dealer's lines), your turn and
        # hand, a line to type in, and the seat's buttons
        px, pw = PANEL_X, PANEL_W
        v.pot = win.add(Label(px, 2, pw, 10, "", flags=GFlag.BOLD))
        v.hand_no = win.add(Label(px, 12, pw, 10, ""))
        v.chat = win.add(TextView(px, 24, pw, 86, list(self.log)))
        v.status = [win.add(Label(px, 112 + 10 * k, pw, 10, "")) for k in range(2)]
        v.entry = win.add(TextBox(px, 138, pw - 60, 12))
        win.add(Button(px + pw - 56, 136, 56, 16, "Send", GFlag.DEFAULT,
                       on_click=lambda b: self.say(s)))
        y = WIN_H - 16
        v.sit_b = win.add(Button(px, y, 76, 16, "Sit Out", on_click=lambda b: self.sit_out(s)))
        v.buy_b = win.add(Button(px + 80, y, 76, 16, "Chips...",
                                 on_click=lambda b: self.ask_buy(s)))
        win.add(Button(px + pw - 52, y, 52, 16, "Leave", on_click=lambda b: self.quit(s)))
        # betting, under the table
        v.fold_b = win.add(Button(0, y, 44, 16, "Fold", on_click=lambda b: self.do(s, "fold")))
        v.call_b = win.add(Button(48, y, 92, 16, "Check", on_click=lambda b: self.do(s, "call")))
        v.raise_b = win.add(Button(144, y, 52, 16, "Raise",
                                   on_click=lambda b: self.do(s, "raise")))
        v.amount = win.add(TextBox(200, y + 2, 48, 12))
        v.half_b = win.add(Button(252, y, 36, 16, "1/2", on_click=lambda b: self.size(s, 2)))
        v.pot_b = win.add(Button(292, y, 36, 16, "Pot", on_click=lambda b: self.size(s, 1)))
        v.allin_b = win.add(Button(332, y, 60, 16, "All In",
                                   on_click=lambda b: self.do(s, "allin")))
        self.show(p, win)
        v.entry.focus()                  # (type to chat straight away)

    @staticmethod
    def _put(gadget, text):
        if gadget.text != text:
            if gadget.shown:
                gadget.set_text(text)
            else:
                gadget.text = text

    def place(self, viewer, seat):
        """Where `seat` sits for `viewer`: 0 at the bottom left, then clockwise."""
        return (seat.index - viewer.index) % SEATS

    def tell(self, line):
        """A line in everyone's chat: the dealer's (placeholders {i} filled), or a person's."""
        line = self.fill(line)
        self.log.append(line)
        del self.log[:-LOG_KEEP]
        for s in self.people():
            if s.player in self.players and s.view is not None and s.view.win is not None:
                s.view.chat.append(line)

    def speak(self, t, text):
        """Seat t says `text`: in the chat, and at the seat for a few seconds."""
        self.tell("%s: %s" % (t.name, text))
        t.said, t.said_until = text, time.monotonic() + SAY_SECS
        self.redraw()

    def say(self, s):
        if s.player is None or s.player not in self.players:
            return None
        text = clean_text(s.view.entry.value).strip()[:CHAT_MAX]
        if not text:
            return None
        s.view.entry.set_text("")
        self.speak(s, text)
        return None

    def computer_says(self, t, lines):
        if t.computer and self.rng.random() < COMPUTER_CHAT:
            self.speak(t, self.rng.choice(lines))

    def name_of(self, i):
        return self.seats[i].name or "?"

    def fill(self, text):
        for i in range(SEATS):
            text = text.replace("{%d}" % i, self.name_of(i))
        return text

    # ---- drawing each person's table ----

    def redraw(self):
        for s in self.people():
            if s.player in self.players and s.view.win is not None and s.view.win.shown:
                self.draw(s)

    def items(self, me):
        """What's on the table for `me`: [(row, x, what), ...] (table pixels): the cards
        (yours face up, the others' backs until a showdown), the board, the pot's chips and
        the dealer button. Cards still flying aren't there yet."""
        v, h = me.view, self.hand
        out = []
        for t in self.seats:
            if h is None or t.index not in h.hole or t.index in h.folded:
                continue
            place = self.place(me, t)
            shown = t is me or t.index in h.shown
            for k, c in enumerate(h.hole[t.index]):
                if ("hole", t.index, k) not in v.hidden:
                    out.append((SEAT_ROW[place], hole_x(place, k), c if shown else "back"))
        if h is not None:
            for k, c in enumerate(h.board):
                if ("board", k) not in v.hidden:
                    out.append((BOARD_ROW, board_x(k), c))
            if h.pot() and not h.over:
                out.append(CHIPS_AT + ("chips",))
        if self.button is not None:
            place = self.place(me, self.seats[self.button])
            out.append((SEAT_ROW[place], button_x(place), "button"))
        return out

    def draw(self, me):
        v, h = me.view, self.hand
        cells = list(TABLE_CELLS)
        keep = set(v.grid.cells)
        for c, items in cells_for(self.items(me)).items():
            t = v.cache.get(TABLE_CELLS[c], items, keep)
            keep.add(t)
            cells[c] = t
        v.grid.set_cells(cells)
        for t in self.seats:
            self.draw_label(v, me, t, self.place(me, t))
        # the panel
        pot = h.pot() if h is not None else 0
        self._put(v.pot, "Pot: %s" % num(pot) if pot else "")
        self._put(v.hand_no, "Blinds %d/%d%s" % (SMALL, BIG, "    Hand %d" % self.hand_no
                                                 if self.hand_no else ""))
        line1, line2 = self.status_lines(me)
        self._put(v.status[0], line1[:PANEL_W // 8])
        self._put(v.status[1], line2[:PANEL_W // 8])
        self.buttons(me)

    def draw_label(self, v, me, t, place):
        for g, text in zip(v.labels[place], self.label_texts(t, place)):
            self._put(g, text)

    def label_texts(self, t, place):
        """A seat's two lines: name and chips, then what they did or said."""
        if t.empty:
            return ["(empty seat)" if place else "", ""]
        h = self.hand
        mark = "> " if h is not None and h.turn == t.index and not h.over else ""   # (line 2)
        chips = h.stack[t.index] if h is not None and t.index in h.hole else t.chips
        act = ""
        if h is not None and t.index in h.hole:
            act = h.last_action.get(t.index, "")
            if h.over:
                won = next((w for j, w, _ in h.results if j == t.index), 0)
                value = next((val for j, _, val in h.results if j == t.index), None)
                act = ("Wins %s" % num(won)) if won else (
                    short(value) if value is not None and t.index in h.shown else
                    "Fold" if t.index in h.folded else "")
        elif t.sitting_out:
            act = "Sitting out"
        elif t.chips <= 0:
            act = "No chips"
        if t.said and time.monotonic() < t.said_until:
            act = '"%s"' % (t.said if len(t.said) <= 13 else t.said[:10].rstrip() + "...")
        # (15 characters at most: the labels are 128 wide and side by side, so there's
        # always a gap between one seat's and the next)
        # (the chips without commas, and the name gives way to them: "Computer 2 1000")
        room = 15 - 1 - len(str(chips))
        return ["%s %d" % (t.name[:min(10, room)].rstrip(), chips), (mark + act)[:15]]

    def status_lines(self, me):
        """Two lines over the chat box: whose turn it is (and the seconds left), and your
        hand."""
        h = self.hand
        mine = ""
        if h is not None and me.index in h.hole and me.index not in h.folded and h.board:
            mine = "Your hand: " + describe(evaluate(h.hole[me.index] + h.board))
        if me.chips <= 0 and (h is None or me.index not in h.hole):
            return "No chips: Chips... or Leave.", ""
        if me.sitting_out:
            return "You're sitting out: I'm Back.", ""
        if h is None or h.over:
            if sum(1 for t in self.seats if t.ready()) < 2:
                return "Waiting for players...", mine
            return "Next hand soon...", mine
        left = max(0, int(TURN_SECS - (time.monotonic() - self.turn_since)))
        if h.turn == me.index:
            call = h.to_call(me.index)
            return ("Your turn (%d s): %s" % (left, "call %s" % num(call) if call
                                               else "check or bet"), mine)
        if self.seats[h.turn].computer:
            return "%s is thinking..." % self.name_of(h.turn), mine
        return "Waiting for %s..." % self.name_of(h.turn)[:12], mine

    def buttons(self, me):
        v, h = me.view, self.hand
        mine = h is not None and not h.over and h.turn == me.index
        opts = h.options(me.index) if mine else None
        v.fold_b.enable(mine and opts["call"] > 0)
        v.call_b.enable(mine)
        self._put(v.call_b, ("Call %s" % num(opts["call"])) if mine and opts["call"]
                  else "Check")
        rr = opts["raise"] if mine else None
        for b in (v.raise_b, v.half_b, v.pot_b, v.allin_b):
            b.enable(rr is not None)
        self._put(v.raise_b, "Bet" if mine and h.current == 0 else "Raise")
        between = h is None or h.over or me.index not in h.hole
        v.buy_b.enable(between and me.chips < BUY_MAX)
        self._put(v.sit_b, "I'm Back" if me.sitting_out else "Sit Out")

    # ---- buying chips ----

    def ask_buy(self, s):
        v = s.view
        if s.player is None or s.player not in self.players:
            return None
        h = self.hand
        if h is not None and not h.over and s.index in h.hole:
            return s.player.session.toast("Buy chips between hands.")
        db = s.player.session.server.db
        have = db.credits(s.user_id) or 0
        room = BUY_MAX - s.chips
        if room <= 0:
            return s.player.session.toast("You have the most chips you can bring.")
        least = max(1, BUY_MIN - s.chips)
        if have < least:
            return s.player.session.alert("Buy Chips", "You need %s; you have %s." % (
                bank_credits(least), bank_credits(have)))
        win = Window.centred("Buy Chips", 320, 70, flags=WFlag.MODAL | WFlag.CLOSE |
                             WFlag.MOVABLE)
        win.add(Label(MARGIN, 4, 304, 10, "Bring %s-%s to the table." % (num(least), num(room))))
        win.add(Label(MARGIN, 16, 304, 10, "You have %s." % bank_credits(have)))
        win.add(Label(MARGIN, 32, 64, 10, "Credits:"))
        win.amount = win.add(TextBox(72, 30, 80, 12, str(min(room, have))))
        win.msg = win.add(Label(160, 32, 152, 10, ""))
        add_buttons(win, [("Buy", lambda b: self._buy(s, b, least, room), GFlag.DEFAULT),
                          ("Cancel", closer, 0)])
        v.buy_win = win
        s.player.windows.append(win)
        win.show(s.player.session)
        return win

    def _buy(self, s, button, least, room):
        win = button.window
        if s.player is None or s.player not in self.players or self.over:
            return win.close()
        from ..bank import parse_amount
        amount, problem = parse_amount(win.amount.value, most=room)
        if problem is None and amount < least:
            problem = "At least %s." % num(least)
        h = self.hand
        if problem is None and h is not None and not h.over and s.index in h.hole:
            problem = "Wait for this hand to end."
        session = s.player.session
        if problem is None:
            problem = session.server.screens.bank.blocked(s.user_id)
        if problem is None and session.server.db.to_poker_table(s.user_id, amount) is None:
            problem = "You haven't that many."
        if problem:
            return win.msg.set_text(problem[:19])
        win.close()
        s.chips += amount
        s.sitting_out = False
        session.log("poker: %s brings %d (now %d)" % (s.name, amount, s.chips))
        session.server.screens.bank.changed(s.user_id)
        self.tell("{%d} brings %s." % (s.index, num(amount)))
        self.redraw()
        return None

    # ---- hands ----

    def tick(self):
        if self.over:
            return
        now = time.monotonic()
        done = [t for t in self.seats if t.said and now >= t.said_until]
        for t in done:                           # (what they said goes from the seat)
            t.said = ""
        if done:
            self.redraw()
        h = self.hand
        if h is None or h.over:
            if now >= self.next_at:
                self.new_hand()
            return
        t = self.seats[h.turn]
        if t.computer:
            if now - self.turn_since >= BOT_DELAY:
                action, amount = (("fold", None) if CPU_FOLDS
                                  else computer_move(h, h.turn, self.rng))
                self.act(t, action, amount)
            return
        left = TURN_SECS - (now - self.turn_since)
        if left <= 0:                            # too slow: check, or fold
            t.timeouts += 1
            self.act(t, "check" if h.options(t.index)["check"] else "fold", auto=True)
            if t.timeouts >= TIMEOUTS_OUT and not t.sitting_out:
                t.sitting_out = True
                if t.player is not None:
                    t.player.session.toast("You were sat out: click I'm Back to play.")
                self.redraw()
        elif int(left) != int(left + self.tick_interval) and t.view is not None:
            self.draw(t)                         # (their countdown, once a second: only
                                                 # theirs changes)

    def new_hand(self):
        for t in self.seats:                     # the house keeps its players in chips
            if t.computer and t.chips <= 0 and not t.sitting_out:
                t.chips = COMPUTER_CHIPS
                self.tell("{%d} buys more chips." % t.index)
        ready = [t for t in self.seats if t.ready()]
        if len(ready) < 2 or not any(t.player is not None for t in ready):
            self.hand = None
            self.next_at = time.monotonic() + 1.0
            return self.redraw()
        stacks = [t.chips if t.ready() else 0 for t in self.seats]
        start = self.button if self.button is not None else self.rng.randrange(SEATS)
        nxt = next((k % SEATS for k in range(start + 1, start + SEATS + 1)
                    if stacks[k % SEATS] > 0), None)
        self.button = nxt
        self.hand_no += 1
        for t in self.seats:
            t.acted = False
        self.hand = Hand(stacks, self.button, SMALL, BIG, self.rng)
        self.events_seen = 0
        self.moves_seen = 0
        self.after_move()

    def act(self, t, action, amount=None, auto=False):
        h = self.hand
        try:
            h.act(t.index, action, amount)
        except RulesError as e:
            if t.player is not None:
                t.player.session.toast(str(e))
            return False
        if not auto:
            t.acted = True
            t.timeouts = 0
        self.after_move()
        if action == "allin":
            self.computer_says(t, ALL_IN_LINES)
        return True

    def after_move(self):
        h = self.hand
        self.turn_since = time.monotonic()
        for e in h.events[self.events_seen:]:
            # (only the hands shown and who won: each line redraws everyone's chat box, and
            # the seat labels already say who called or folded, the table shows the board)
            if " shows " in e or " wins " in e:
                self.tell(e)
        self.events_seen = len(h.events)
        moves = h.moves[self.moves_seen:]
        self.moves_seen = len(h.moves)
        for s in self.people():
            if s.player in self.players:
                self._flights(s, moves)
        if h.over:
            self.hand_over()
        self.redraw()
        if h.turn is not None:
            t = self.seats[h.turn]
            if t.player is not None and t.player in self.players:
                t.player.session.toast("Your turn.", seconds=2)
            if t.view is not None and h.options(t.index)["raise"]:
                rr = h.options(t.index)["raise"]
                self._put(t.view.amount, str(rr[0]))
                t.view.amount.value = str(rr[0])

    def hand_over(self):
        h = self.hand
        for t in self.seats:
            if t.index in h.hole:
                t.chips = h.stack[t.index]
        bank = self.bank()
        for t in self.people():
            if t.player not in self.players or t.index not in h.hole:
                continue
            db = t.player.session.server.db
            db.set_poker_chips(t.user_id, t.chips)
            if t.acted and bank is not None:
                bank.earn(t.user_id, "poker hand")
        showdown = bool(h.shown)
        self.next_at = time.monotonic() + (NEXT_HAND if showdown else NEXT_HAND / 2)
        # now and then a computer has something to say about a big pot
        won = {j: w for j, w, _ in h.results if w}
        if sum(won.values()) >= BIG_POT:
            for t in self.seats:
                if t.computer and t.index in h.hole and t.index in won:
                    self.computer_says(t, WIN_LINES)
                    break
                if t.computer and t.index in h.hole and h.stack[t.index] == 0:
                    self.computer_says(t, LOSE_LINES)
                    break
        self._celebrate(h)
        if self.people():
            self.people()[0].player.session.log("poker: hand %d: %s" % (
                self.hand_no, "; ".join(self.fill(e) for e in h.events if "wins" in e)))

    # ---- the winner: ka-ching, and stars flashing at their seat ----

    def _celebrate(self, h):
        """After the last cards land: each winner hears ka-ching (Sound.KACHING), and everyone
        (Caps.SPRITES) sees two gold stars flash either side of the biggest winner's "Wins N"
        for FLASH_SECS."""
        won = sorted(((w, j) for j, w, _ in h.results if w), reverse=True)
        if not won:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        top, winners = won[0][1], {j for _, j in won}
        now = time.monotonic()
        for s in self.people():
            v = s.view
            if s.player not in self.players or v is None or v.win is None:
                continue
            at = max(now, v.fly_free) - now          # (when the river has landed)
            if s.index in winners:
                loop.call_later(at, self._kaching, s)
            if not s.player.session.caps & Caps.SPRITES:
                continue
            v.flash += 1
            k = 0
            while k * FLASH_EVERY < FLASH_SECS:
                loop.call_later(at + k * FLASH_EVERY, self._flash, s, v.flash, top, k % 2 == 0)
                k += 1
            loop.call_later(at + FLASH_SECS, self._flash, s, v.flash, top, False)

    def _kaching(self, s):
        if s.player is not None and s.player in self.players:
            s.player.session.sound(Sound.KACHING)

    def _flash(self, s, gen, winner, on):
        """The stars on (or off) for viewer s: `gen` is the flash it belongs to (a new deal
        or a newer win ends it)."""
        v = s.view
        if (v is None or v.flash != gen or s.player not in self.players or self.over
                or not v.win.shown):
            return
        session = s.player.session
        if not on:
            session.sprite_off()
            return
        t = self.seats[winner]
        place = self.place(s, t)
        text = self.label_texts(t, place)[1]
        lx, ly, lw = label_at(place)
        cx, half = lx + lw // 2, 4 * len(text)
        tile = v.cache.get(TABLE_CELLS[BOARD_ROW * COLS + COLS // 2], [("star", 0)],
                           set(v.grid.cells))
        offset = tile * TILE_W * TILE_H + STAR_Y * TILE_W
        for n, x in ((0, cx - half - STAR_PX - 4), (1, cx + half + 4)):
            session.sprite_show(n, v.win, RESOURCE_SLOT, offset, STAR_FAT, STAR_FAT,
                                (max(0, x), ly + 9), STAR_COLOURS, stride=TILE_W, step=2)

    # ---- flying cards (Caps.SPRITES) ----

    def _flights(self, s, moves):
        v = s.view
        if not moves or not (s.player.session.caps & Caps.SPRITES) or not v.win.shown:
            return
        h = self.hand
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if any(m[0] == "deal" for m in moves):  # a new hand: the last one's stars are done
            v.flash += 1
            s.player.session.sprite_off()
        bp = self.place(s, self.seats[self.button])
        src = (TX + button_x(bp), TY + SEAT_ROW[bp] * TILE_H)
        now = time.monotonic()
        for m in moves:
            if m[0] == "deal":                   # one card at a time, round the table twice
                place = self.place(s, self.seats[m[1]])
                targets = [(("hole", m[1], m[2]), SEAT_ROW[place], hole_x(place, m[2]),
                            "back")]
            elif m[0] == "board":
                targets = [(("board", k), BOARD_ROW, board_x(k), h.board[k])
                           for k in range(m[1], m[1] + m[2])]
            else:
                continue
            for key, row, x, what in targets:
                v.hidden.add(key)                # (not drawn until it lands)
                start = max(now, v.fly_free)
                land = start + FLY_FRAMES / 50.0
                v.fly_free = land + FLY_GAP
                loop.call_later(start - now, self._send_fly, s, what, src,
                                (TX + x - 4, TY + row * TILE_H))
                loop.call_later(land - now, self._landed, s, [key])

    def _send_fly(self, s, what, src, dst):
        v = s.view
        if self.over or s.player is None or s.player not in self.players or not v.win.shown:
            return
        felt = TABLE_CELLS[BOARD_ROW * COLS + COLS // 2]       # (left out of the sprite)
        t = v.cache.get(felt, [(what, 4)], set(v.grid.cells))
        v.fly_n ^= 1
        s.player.session.fly(v.win, RESOURCE_SLOT, t * TILE_W * TILE_H, TILE_W // 2, TILE_H,
                             src, dst, FLY_FRAMES, CARD_COLOURS, step=2, n=v.fly_n)

    def _landed(self, s, keys):
        v = s.view
        if v is None:
            return
        for k in keys:
            v.hidden.discard(k)
        if not self.over and s.player is not None and s.player in self.players and v.win.shown:
            self.draw(s)

    # ---- what people do ----

    def _turn(self, s):
        h = self.hand
        return (not self.over and s.player in self.players and h is not None and not h.over
                and h.turn == s.index)

    def do(self, s, action):
        if not self._turn(s):
            return None
        amount = None
        if action == "raise":
            text = clean_text(s.view.amount.value).strip().replace(",", "")
            if not (text.isascii() and text.isdigit()):
                return s.player.session.toast("Type how much to raise to.")
            amount = int(text)
        self.act(s, action, amount)
        return None

    def size(self, s, part):
        """1/2 Pot and Pot: the raise box (to that much more than a call; you still click
        Raise)."""
        if not self._turn(s):
            return None
        h = self.hand
        rr = h.options(s.index)["raise"]
        if rr is None:
            return None
        call = h.to_call(s.index)
        to = h.current + (h.pot() + call) // part
        to = max(rr[0], min(rr[1], to))
        s.view.amount.set_text(str(to))
        return None

    def sit_out(self, s):
        if s.player not in self.players:
            return None
        s.sitting_out = not s.sitting_out
        s.timeouts = 0
        self.tell("{%d} %s." % (s.index, "sits out" if s.sitting_out else "is back"))
        self.redraw()
        return None

    def quit(self, s):
        if s.player is None:
            return None
        session = s.player.session
        self.leave(s.player)
        if self._lobby is not None:
            return self._lobby.open(session)
        return None

    def on_leave(self, player):
        s = self.seat_of(player)
        if s is None:
            return
        h = self.hand
        playing = h is not None and not h.over
        if playing and s.index in h.hole:
            h.remove(s.index)
            s.chips = h.stack[s.index]
            h.stack[s.index] = 0                 # (folded: nothing more of theirs is in play)
        session = player.session
        back = session.server.db.from_poker_table(session.user_id, s.chips, "left the table")
        session.log("poker: %s leaves with %d" % (s.name, s.chips))
        session.server.screens.bank.changed(session.user_id)
        if back is not None and s.chips:
            session.toast("%s back to your balance." % bank_credits(s.chips))
        self.tell("{%d} leaves." % s.index)
        s.player, s.view, s.chips = None, None, 0     # (the name stays: the hand's lines)
        if not any(t.player is not None for t in self.seats):
            return self.end()
        if playing:
            self.after_move()
        else:
            self.redraw()
        return None


def bank_credits(n):
    from ..bank import credits
    return credits(n)
