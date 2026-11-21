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

The table (one window a player, a dynamic id; Caps.GRID clients). You sit at the bottom left;
the others clockwise from there, two at each end and two across the top:

          Pot: 120         bob    1,250        Computer 2   980         Hand 12
          Blinds 5/10      Call 20             Fold
               +----------------------------------------------------------+
     Computer 1|  [][]                          [][]                     |Computer 3
     1,000     | [][]   [] [] [] [] []                       [][]        |1,020
     Raise 40  |  [][] (D)                      [][]                     |Check
               +----------------------------------------------------------+
     status         you          1,180           Computer 4    900       Your hand:
                    Bet 40                       Fold                    Pair of Kings
     [Fold] [Call 20] [Raise] [ 60 ] [1/2 Pot] [Pot] [All In]                   [Leave]

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
from ..protocol import Caps, GFlag, WFlag, clean_text
from ..ui import Button, Grid, Label, TextBox, Window, add_buttons, centre, closer, MARGIN
from .base import Game
from .poker_art import (TABLE, TABLE_TILES, TABLE_CELLS, N_TABLE, TILE_W, TILE_H, COLS,
                        CARD_COLOURS, overlay, interior)
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
NEXT_HAND = 4.0                  # seconds between hands (after a showdown; less otherwise)
FLY_FRAMES = int(os.environ.get("MEGANET_POKER_FLY_FRAMES", 8))   # 0.16 s a card
FLY_GAP = 0.04

WIN_W, WIN_H = 624, 171
TX, TY = 104, 24                 # the table grid in the window
# by place round the table (0 = you, then clockwise): the two hole-card cells (col, row)
# and how far in each card is drawn (they sit close together), the dealer button's cell,
# and the seat's label (x, y, width, lines)
HOLE_CELLS = [((3, 3), (4, 3)), ((1, 2), (2, 2)), ((3, 1), (4, 1)), ((8, 1), (9, 1)),
              ((10, 2), (11, 2)), ((8, 3), (9, 3))]
HOLE_DX = (7, 1)
BUTTON_CELLS = [(5, 3), (3, 2), (5, 1), (7, 1), (9, 2), (7, 3)]
LABELS = [(168, 136, 128, 2), (0, 64, 100, 3), (168, 2, 128, 2), (328, 2, 128, 2),
          (524, 64, 100, 3), (328, 136, 128, 2)]
BOARD_CELLS = [(4 + k, 2) for k in range(5)]
BOARD_DX = 4
CHIPS_CELL, CHIPS_DX = (6, 1), 6


def cell(cr):
    return cr[1] * COLS + cr[0]


def cell_xy(cr):
    return TX + cr[0] * TILE_W, TY + cr[1] * TILE_H


def num(n):
    return "{:,}".format(n)


class TileCache:
    """One viewer's tiles past the table's: (base tile, what, dx) -> tile number, sent the
    first time it's needed; the least used goes when there's no room (never one on show)."""

    def __init__(self, session):
        self.session = session
        self.map = OrderedDict()
        self.free = list(range(N_TABLE, N_TILES))

    def get(self, base, what, dx, keep):
        key = (base, what, dx)
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
                                      overlay(TABLE_TILES[base], what, dx))
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
        self.hidden = set()           # cells whose card is still flying there
        self.fly_free = 0.0
        self.fly_n = 1
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
        self.last_event = ""
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
        s.sitting_out, s.timeouts = False, 0
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
        for lx, ly, lw, lines in LABELS:
            v.labels.append([win.add(Label(lx, ly + 10 * k, lw, 10, "",
                                           flags=GFlag.CENTRE if lw == 128 else 0))
                             for k in range(lines)])
        v.pot = win.add(Label(0, 2, 160, 10, "", flags=GFlag.BOLD))
        win.add(Label(0, 12, 160, 10, "Blinds %d/%d" % (SMALL, BIG)))
        v.hand_no = win.add(Label(464, 2, 160, 10, ""))
        v.sit_b = win.add(Button(0, 98, 96, 16, "Sit Out", on_click=lambda b: self.sit_out(s)))
        v.buy_b = win.add(Button(0, 116, 96, 16, "Buy Chips...",
                                 on_click=lambda b: self.ask_buy(s)))
        v.status = [win.add(Label(0, 136 + 10 * k, 160, 10, "")) for k in range(2)]
        v.mine = [win.add(Label(464, 136 + 10 * k, 160, 10, "")) for k in range(2)]
        y = WIN_H - 16
        v.fold_b = win.add(Button(0, y, 56, 16, "Fold", on_click=lambda b: self.do(s, "fold")))
        v.call_b = win.add(Button(62, y, 96, 16, "Check", on_click=lambda b: self.do(s, "call")))
        v.raise_b = win.add(Button(164, y, 64, 16, "Raise", GFlag.DEFAULT,
                                   on_click=lambda b: self.do(s, "raise")))
        v.amount = win.add(TextBox(234, y + 2, 64, 12))
        v.half_b = win.add(Button(304, y, 72, 16, "1/2 Pot", on_click=lambda b: self.size(s, 2)))
        v.pot_b = win.add(Button(382, y, 48, 16, "Pot", on_click=lambda b: self.size(s, 1)))
        v.allin_b = win.add(Button(436, y, 64, 16, "All In",
                                   on_click=lambda b: self.do(s, "allin")))
        win.add(Button(WIN_W - 56, y, 56, 16, "Leave", on_click=lambda b: self.quit(s)))
        self.show(p, win)

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
        self.last_event = line[:40]

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

    def draw(self, me):
        v, h = me.view, self.hand
        cells = list(TABLE_CELLS)
        over = {}                                # cell -> (what, dx)
        mine = None
        for t in self.seats:
            place = self.place(me, t)
            cards = None
            if h is not None and t.index in h.hole and t.index not in h.folded:
                if t is me or t.index in h.shown:
                    cards = h.hole[t.index]
                else:
                    cards = ["back", "back"]
            if cards:
                for cr, dx, c in zip(HOLE_CELLS[place], HOLE_DX, cards):
                    if cell(cr) not in v.hidden:
                        over[cell(cr)] = (c, dx)
            self.draw_label(v, me, t, place)
        if h is not None:
            for k, c in enumerate(h.board):
                cr = BOARD_CELLS[k]
                if cell(cr) not in v.hidden:
                    over[cell(cr)] = (c, BOARD_DX)
            if h.pot() and not h.over:
                over[cell(CHIPS_CELL)] = ("chips", CHIPS_DX)
            if me.index in h.hole and me.index not in h.folded:
                mine = evaluate(h.hole[me.index] + h.board) if h.board else None
        if self.button is not None:
            over[cell(BUTTON_CELLS[self.place(me, self.seats[self.button])])] = ("button", 8)
        keep = set(v.grid.cells)
        for c, (what, dx) in over.items():
            t = v.cache.get(TABLE_CELLS[c], what, dx, keep)
            keep.add(t)
            cells[c] = t
        v.grid.set_cells(cells)
        # the text round the table
        self._put(v.pot, "Pot: %s" % num(h.pot()) if h is not None and h.pot() else "")
        self._put(v.hand_no, "Hand %d" % self.hand_no if self.hand_no else "")
        self._put(v.mine[0], "Your hand:" if mine else "")
        self._put(v.mine[1], describe(mine)[:20] if mine else "")
        line1, line2 = self.status_lines(me)
        self._put(v.status[0], line1[:19])         # (19: clear of your seat's label)
        self._put(v.status[1], line2[:19])
        self.buttons(me)

    def draw_label(self, v, me, t, place):
        lines = v.labels[place]
        if t.empty:
            texts = ["(empty seat)" if place else "", ""]
        else:
            h = self.hand
            mark = "> " if h is not None and h.turn == t.index and not h.over else ""
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
            name = mark + t.name
            if len(lines) == 3:
                texts = [name[:12], num(chips), act[:12]]
            else:
                texts = [("%-10s %5s" % (name[:10], num(chips)))[:16], act[:16]]
        for g, text in zip(lines, texts + [""] * 3):
            self._put(g, text)

    def status_lines(self, me):
        h = self.hand
        if me.chips <= 0 and (h is None or me.index not in h.hole):
            return "No chips: Buy", "Chips... or Leave."
        if me.sitting_out:
            return "You're sitting out.", "Click I'm Back."
        if h is None or h.over:
            if sum(1 for t in self.seats if t.ready()) < 2:
                return "Waiting for players", "to sit down..."
            return self.fill(self.last_event)[:19], "Next hand soon..."
        if h.turn == me.index:
            call = h.to_call(me.index)
            left = max(0, int(TURN_SECS - (time.monotonic() - self.turn_since)))
            return ("Your turn (%d s):" % left,
                    "call %s or raise" % num(call) if call else "check or bet")
        last = self.fill(h.events[-1]) if h.events else ""
        return last[:19], last[19:38]

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
        h = self.hand
        if h is None or h.over:
            if now >= self.next_at:
                self.new_hand()
            return
        t = self.seats[h.turn]
        if t.computer:
            if now - self.turn_since >= BOT_DELAY:
                action, amount = computer_move(h, h.turn, self.rng)
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
            self.draw(t)                         # (the turn's countdown, once a second)

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
        return True

    def after_move(self):
        h = self.hand
        self.turn_since = time.monotonic()
        if h.events[self.events_seen:]:
            self.tell(h.events[-1])
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
        if self.people():
            self.people()[0].player.session.log("poker: hand %d: %s" % (
                self.hand_no, "; ".join(self.fill(e) for e in h.events if "wins" in e)))

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
        src = cell_xy(BUTTON_CELLS[self.place(s, self.seats[self.button])])
        now = time.monotonic()
        for m in moves:
            if m[0] == "deal":                   # one card at a time, round the table twice
                cr = HOLE_CELLS[self.place(s, self.seats[m[1]])][m[2]]
                targets = [(cr, "back", HOLE_DX[m[2]])]
            elif m[0] == "board":
                targets = [(BOARD_CELLS[k], h.board[k], BOARD_DX)
                           for k in range(m[1], m[1] + m[2])]
            else:
                continue
            for cr, what, dx in targets:
                v.hidden.add(cell(cr))           # (the cell stays bare until it lands)
                start = max(now, v.fly_free)
                land = start + FLY_FRAMES / 50.0
                v.fly_free = land + FLY_GAP
                dst = cell_xy(cr)
                loop.call_later(start - now, self._send_fly, s, what, src,
                                (dst[0] + dx - 4, dst[1]))
                loop.call_later(land - now, self._landed, s, [cell(cr)])

    def _send_fly(self, s, what, src, dst):
        v = s.view
        if self.over or s.player is None or s.player not in self.players or not v.win.shown:
            return
        t = v.cache.get(TABLE_CELLS[cell(BOARD_CELLS[2])], what, 4, set(v.grid.cells))
        v.fly_n ^= 1
        s.player.session.fly(v.win, RESOURCE_SLOT, t * TILE_W * TILE_H, TILE_W // 2, TILE_H,
                             src, dst, FLY_FRAMES, CARD_COLOURS, step=2, n=v.fly_n)

    def _landed(self, s, cells):
        v = s.view
        for c in cells:
            v.hidden.discard(c)
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
