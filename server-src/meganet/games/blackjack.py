"""Blackjack: up to three players at a table against the house's dealer, for real credits (the
bank, bank.py). Rules: blackjack_rules.py (six decks, the dealer stands on all 17s, blackjack
pays 3 to 2, double, split once). The cards are bigger than poker's (blackjack_art.py).

Games > Blackjack > Join sits you at a table with a free seat, or opens a new table at once
(Game.start_at_once): you can play alone. Each round you type a bet (MIN_BET-MAX_BET) and click
Bet; the deal comes when everyone seated has bet, or BET_SECS after the first bet (whoever
hasn't bet sits that round out). Then each player in turn: Hit, Stand, Double, Split; then
the dealer. A bet leaves your balance when you place it (and a double or split's too); what
the round pays comes back when it's over. Until then it's held on the table
(db.to_poker_table: the same table-credits record as poker's, given back if the server
stops). Leaving mid-round: your hands stand as they are and are paid all the same.

The window (one a player, a dynamic id; Caps.GRID clients):

                        Dealer shows 10                     | Blackjack pays 3 to 2
     +----------------------------------------------------+ | Bets 10 to 500
     |                    [A][#]                    (shoe) | | the chat: what people say,
     |                                                     | | and the dealer's lines
     |    [10][6]          [K][A]          [5][5][9]       | | Your turn (25 s): 16
     +----------------------------------------------------+ | Balance: 1,240
        bob 50             you 100          carol 20        | [type here      ] [Send]
        > 16               Blackjack!       "nice"          |
     Bet: [ 100 ] [Bet]                                     |
     [Hit] [Stand] [Double] [Split]                         |                     [Leave]

RETURN sends the chat line. Cards fly from the shoe to the hands (Caps.SPRITES clients).
"""

import asyncio
import os
import time
import zlib
from collections import OrderedDict

from .. import permissions as perms
from ..protocol import Caps, GFlag, Sound, clean_text
from ..ui import Button, Grid, Label, TextBox, TextView, centre
from .base import Game
from .blackjack_art import (TABLE, TABLE_TILES, TABLE_CELLS, N_TABLE, TILE_W, TILE_H, COLS,
                            ROWS, CARD_COLOURS, compose, felt, overlay_width)
from .blackjack_rules import (MIN_BET, MAX_BET, Round, RulesError, Shoe, describe, value)

RESOURCE_SLOT = 11               # (1 chess, 2-7 the Art Gallery, 8 One, 9 poker, 10 SID tunes)
TABLE_KEY = "blackjack %08x" % zlib.crc32(TABLE)
N_TILES = 64
SEATS = 3
SEAT_X = [80, 208, 336]          # the middle of each seat's cards (table pixels)
SEAT_W = 128                     # the room a seat's hands have
DEALER_X, DEALER_W = 208, 200
DEALER_ROW, SEAT_ROW = 0, 2
CARD_PX = 32                     # a card across, screen pixels
FAN = 14                         # pixels between cards in a hand (less if they need it)
SHOE = (376, 0)                  # where the cards fly from (table pixels)

BET_SECS = float(os.environ.get("MEGANET_BJ_BET_SECS", 15))     # after the first bet
TURN_SECS = 30                   # then you stand
DEALER_DELAY = float(os.environ.get("MEGANET_BJ_DEALER_DELAY", 0.8))
NEXT_ROUND = float(os.environ.get("MEGANET_BJ_NEXT_ROUND", 4.0))
FLY_FRAMES = int(os.environ.get("MEGANET_BJ_FLY_FRAMES", 8))
FLY_GAP = 0.04
CHAT_MAX = 120
LOG_KEEP = 60
SAY_SECS = 6.0

WIN_W, WIN_H = 632, 171
TX, TY = 0, 11                   # the table grid in the window
PANEL_X, PANEL_W = 420, 212
LABEL_W = 136
OUTCOME = {"bust": "Bust", "blackjack": "Blackjack!", "win": "Win", "push": "Push",
           "lose": "Lose"}


def num(n):
    return "{:,}".format(n)


def fan(region_x, region_w, n):
    """The x of each of n cards fanned out, centred in a region (even pixels)."""
    if n <= 0:
        return []
    off = FAN if n == 1 else min(FAN, (region_w - CARD_PX) // (n - 1))
    off -= off % 2
    total = CARD_PX + off * (n - 1)
    x0 = region_x + (region_w - total) // 2
    x0 -= x0 % 2
    return [x0 + off * k for k in range(n)]


def hand_regions(seat_index, hands):
    """(x, width) for each of a seat's hands: one in the middle, or two side by side."""
    cx = SEAT_X[seat_index]
    if hands <= 1:
        return [(cx - SEAT_W // 2, SEAT_W)]
    half = SEAT_W // 2 - 2
    return [(cx - SEAT_W // 2, half), (cx + 2, half)]


def cells_for(items):
    """{cell: [(what, dx), ...]} for items [(row, x, what), ...]: each on every tile it
    covers, in order (later cards over earlier ones)."""
    out = {}
    for row, x, what in items:
        w = overlay_width(what)
        for col in range(x // TILE_W, (x + w - 1) // TILE_W + 1):
            if 0 <= col < COLS:
                out.setdefault(row * COLS + col, []).append((what, x - col * TILE_W))
    return out


class TileCache:
    """One viewer's tiles past the table's (as poker.TileCache)."""

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
        base_px = felt() if base is None else TABLE_TILES[base]
        self.session.send_resource_at(RESOURCE_SLOT, t * TILE_W * TILE_H,
                                      compose(base_px, key[1]))
        self.map[key] = t
        return t


class Seat:
    def __init__(self, index):
        self.index = index
        self.name = ""
        self.player = None
        self.bet = 0                  # placed for the next deal (already off their balance)
        self.view = None
        self.said = ""
        self.said_until = 0.0
        self.last_bet = MIN_BET

    @property
    def empty(self):
        return self.player is None

    @property
    def user_id(self):
        return self.player.session.user_id if self.player is not None else None


class View:
    def __init__(self, session):
        self.session = session
        self.cache = TileCache(session)
        self.hidden = set()           # cards still flying: ("dealer", k), ((seat, hand), k)
        self.fly_free = 0.0
        self.fly_n = 1
        self.win = None


class Blackjack(Game):
    name = "Blackjack"
    description = ("Blackjack for 1-3 players against the dealer, with big cards, for your "
                   "credits: bets 10 to 500, blackjack pays 3 to 2. Chat at the table.")
    min_players = 1
    max_players = SEATS
    start_at_once = True          # Join: a table with a free seat, or a new one now
    needs_caps = Caps.GRID
    tick_interval = 0.25
    permission = perms.register("games.blackjack", "Play blackjack (credits)",
                                like="games.play")

    # ---- joining ----

    @classmethod
    def join_problem(cls, session):
        bank = session.server.screens.bank
        problem = bank.blocked(session.user_id)
        if problem:
            return problem
        have = session.server.db.credits(session.user_id) or 0
        if have < MIN_BET:
            return ("You need %s to play blackjack; you have %s. See Areas > Bank for how to "
                    "earn more." % (bank_credits(MIN_BET), bank_credits(have)))
        return None

    def open_seat(self, session):
        return (not self.over and any(s.empty for s in self.seats)
                and self.join_problem(session) is None)

    def start(self, players):
        session = players[0].session
        self.server = session.server
        self.db = session.server.db
        self.shoe = Shoe()
        self.seats = [Seat(i) for i in range(SEATS)]
        self.round = None
        self.round_uids = {}          # seat -> the user whose bets the round holds
        self.round_no = 0
        self.phase = "betting"        # betting, play, dealer, over
        self.bet_until = None
        self.turn_since = 0.0
        self.dealer_at = 0.0
        self.next_at = 0.0
        self.moves_seen = 0
        self.events_seen = 0
        self.log = []
        for p in players:
            self._seat(p, next(s for s in self.seats if s.empty).index)
        session.log("blackjack: %s sit down" % ", ".join(p.name for p in players))
        self.redraw()

    def sit_down(self, player):
        s = next(t for t in self.seats if t.empty)
        self._seat(player, s.index)
        self.tell("* %s sits down." % player.name)
        self.redraw()

    def _seat(self, player, i):
        s = self.seats[i]
        s.player, s.name, s.bet, s.said = player, player.name, 0, ""
        player.session.send_resource(RESOURCE_SLOT, TABLE_KEY, TABLE, title="Blackjack")
        s.view = View(player.session)
        self._window(s)

    def people(self):
        return [s for s in self.seats if s.player is not None and s.player in self.players]

    def seat_of(self, player):
        return next((s for s in self.seats if s.player is player), None)

    @property
    def bank(self):
        return self.server.screens.bank

    # ---- the window ----

    def _window(self, s):
        p, v = s.player, s.view
        x, y = centre(WIN_W, WIN_H)
        win = self.window(p, "Blackjack", x, y, WIN_W, WIN_H)
        v.win = win
        v.dealer = win.add(Label(0, 0, COLS * TILE_W, 10, "", flags=GFlag.CENTRE | GFlag.BOLD))
        v.grid = win.add(Grid(TX, TY, COLS, ROWS, TILE_W, TILE_H, RESOURCE_SLOT,
                              cells=TABLE_CELLS))
        v.labels = []
        ly = TY + ROWS * TILE_H + 2
        for i in range(SEATS):
            lx = SEAT_X[i] - LABEL_W // 2
            v.labels.append([win.add(Label(lx, ly + 10 * k, LABEL_W, 10, "",
                                           flags=GFlag.CENTRE)) for k in range(2)])
        # your bet, and what to do with your hand
        win.add(Label(0, 135, 32, 10, "Bet:"))
        v.bet_box = win.add(TextBox(36, 133, 56, 12, str(s.last_bet)))
        v.bet_b = win.add(Button(96, 131, 52, 16, "Bet", on_click=lambda b: self.place_bet(s)))
        by = WIN_H - 16
        v.hit_b = win.add(Button(0, by, 52, 16, "Hit", on_click=lambda b: self.do(s, "hit")))
        v.stand_b = win.add(Button(56, by, 56, 16, "Stand",
                                   on_click=lambda b: self.do(s, "stand")))
        v.double_b = win.add(Button(116, by, 60, 16, "Double",
                                    on_click=lambda b: self.do(s, "double")))
        v.split_b = win.add(Button(180, by, 52, 16, "Split",
                                   on_click=lambda b: self.do(s, "split")))
        # the panel: the table's rules, the chat, your turn and balance, a line to type in
        px, pw = PANEL_X, PANEL_W
        win.add(Label(px, 2, pw, 10, "Blackjack pays 3 to 2", flags=GFlag.BOLD))
        win.add(Label(px, 12, pw, 10, "Bets %d to %d" % (MIN_BET, MAX_BET)))
        v.chat = win.add(TextView(px, 24, pw, 86, list(self.log)))
        v.status = [win.add(Label(px, 112 + 10 * k, pw, 10, "")) for k in range(2)]
        v.entry = win.add(TextBox(px, 138, pw - 60, 12))
        win.add(Button(px + pw - 56, 136, 56, 16, "Send", GFlag.DEFAULT,
                       on_click=lambda b: self.say(s)))
        win.add(Button(px + pw - 52, by, 52, 16, "Leave", on_click=lambda b: self.quit(s)))
        self.show(p, win)
        v.entry.focus()

    @staticmethod
    def _put(gadget, text):
        if gadget.text != text:
            if gadget.shown:
                gadget.set_text(text)
            else:
                gadget.text = text

    # ---- the chat ----

    def tell(self, line):
        self.log.append(line)
        del self.log[:-LOG_KEEP]
        for s in self.people():
            if s.view is not None and s.view.win is not None:
                s.view.chat.append(line)

    def say(self, s):
        if s.player is None or s.player not in self.players:
            return None
        text = clean_text(s.view.entry.value).strip()[:CHAT_MAX]
        if not text:
            return None
        s.view.entry.set_text("")
        self.tell("%s: %s" % (s.name, text))
        s.said, s.said_until = text, time.monotonic() + SAY_SECS
        self.redraw()
        return None

    # ---- drawing ----

    def redraw(self):
        for s in self.people():
            if s.view.win is not None and s.view.win.shown:
                self.draw(s)

    def items(self, me):
        """[(row, x, what), ...]: the dealer's cards and every hand, in table pixels."""
        v, r = me.view, self.round
        out = []
        if r is None:
            return out
        xs = fan(DEALER_X - DEALER_W // 2, DEALER_W, len(r.dealer))
        for k, c in enumerate(r.dealer):
            if ("dealer", k) not in v.hidden:
                out.append((DEALER_ROW, xs[k], c if (k != 1 or r.hole_shown) else "back"))
        for seat in r.seats:
            hands = r.hands[seat]
            for j, (rx, rw) in enumerate(hand_regions(seat, len(hands))):
                cards = hands[j].cards
                for k, x in enumerate(fan(rx, rw, len(cards))):
                    if ((seat, j), k) not in v.hidden:
                        out.append((SEAT_ROW, x, cards[k]))
        return out

    def draw(self, me):
        v = me.view
        cells = list(TABLE_CELLS)
        keep = set(v.grid.cells)
        for c, items in cells_for(self.items(me)).items():
            t = v.cache.get(TABLE_CELLS[c], items, keep)
            keep.add(t)
            cells[c] = t
        v.grid.set_cells(cells)
        self._put(v.dealer, self.dealer_text())
        for t in self.seats:
            for g, text in zip(v.labels[t.index], self.label_texts(t, me)):
                self._put(g, text)
        for g, text in zip(v.status, self.status_lines(me)):
            self._put(g, text[:PANEL_W // 8])
        self.buttons(me)

    def dealer_text(self):
        r = self.round
        if r is None or not r.dealer:
            return "Dealer"
        if r.phase == "over" and r.hole_shown:
            total = value(r.dealer)[0]
            if total > 21:
                return "Dealer busts with %d" % total
            if total == 21 and len(r.dealer) == 2:
                return "Dealer has blackjack"
            return "Dealer has %d" % total
        if r.hole_shown:
            return "Dealer: %s" % describe(r.dealer)
        return "Dealer shows %s" % r.dealer_shows()

    def label_texts(self, t, me):
        """A seat's two lines (17 characters each): name and bet, then the hand or what they
        said."""
        r = self.round
        if t.empty:
            return ["(empty seat)", ""]
        in_round = r is not None and t.index in r.hands
        # (between rounds the last one stays on the table until a new bet is placed)
        show_round = in_round and (self.phase != "betting" or not t.bet)
        stake = r.staked(t.index) if show_round else t.bet
        name = "you" if t is me else t.name
        line1 = ("%s %d" % (name[:16 - len(str(stake))].rstrip(), stake)) if stake else name[:17]
        line2 = ""
        if show_round:
            hands = r.hands[t.index]
            if r.phase == "over":
                parts = [OUTCOME[o] for _, o, _ in r.results.get(t.index, [])]
                net = r.paid(t.index) - r.staked(t.index)
                line2 = " | ".join(parts)
                if len(parts) == 1 and net > 0:
                    line2 = "%s +%d" % (parts[0], net)
            else:
                line2 = " | ".join("Bust" if h.bust else "BJ!" if h.blackjack else
                                   describe(h.cards) for h in hands)
                if r.turn is not None and r.turn[0] == t.index:
                    line2 = "> " + line2
        elif t.bet:
            line2 = "Ready"
        if t.said and time.monotonic() < t.said_until:
            line2 = '"%s"' % (t.said if len(t.said) <= 15 else t.said[:12].rstrip() + "...")
        return [line1, line2[:17]]

    def status_lines(self, me):
        bal = "Balance: %s" % bank_credits(self.db.credits(me.user_id) or 0)
        r, now = self.round, time.monotonic()
        if self.phase == "betting":
            left = "" if self.bet_until is None else " (%d s)" % max(0, int(self.bet_until - now))
            if me.bet:
                return "Bet %s. Waiting%s..." % (num(me.bet), left), bal
            return "Type a bet, then Bet%s." % left, bal
        if self.phase == "over":
            return "Next round soon...", bal
        if self.phase == "dealer":
            return "The dealer plays...", bal
        if r.turn is not None and r.turn[0] == me.index:
            h = r.hands[me.index][r.turn[1]]
            left = max(0, int(TURN_SECS - (now - self.turn_since)))
            which = (" (hand %d)" % (r.turn[1] + 1)) if len(r.hands[me.index]) > 1 else ""
            return "Your turn (%d s): %s%s" % (left, describe(h.cards), which), bal
        if r.turn is not None:
            return "Waiting for %s..." % self.seats[r.turn[0]].name[:14], bal
        return "", bal

    def buttons(self, me):
        v, r = me.view, self.round
        opts = (r.options(me.index) if r is not None and self.phase == "play"
                else dict.fromkeys(("hit", "stand", "double", "split"), False))
        v.hit_b.enable(opts["hit"])
        v.stand_b.enable(opts["stand"])
        v.double_b.enable(opts["double"])
        v.split_b.enable(opts["split"])
        v.bet_b.enable(self.phase == "betting" and not me.bet)

    # ---- betting ----

    def place_bet(self, s):
        if s.player is None or s.player not in self.players or self.over:
            return None
        session = s.player.session
        if self.phase != "betting":
            return session.toast("Bet when this round is over.")
        if s.bet:
            return None
        from ..bank import parse_amount
        amount, problem = parse_amount(s.view.bet_box.value, most=MAX_BET)
        if problem is None and amount < MIN_BET:
            problem = "Bets are %d to %d." % (MIN_BET, MAX_BET)
        if problem is None:
            problem = self.bank.blocked(s.user_id)
        if problem is None and self.db.to_poker_table(s.user_id, amount,
                                                      reason="blackjack bet") is None:
            problem = "You haven't %s." % bank_credits(amount)
        if problem:
            return session.toast(problem)
        s.bet = s.last_bet = amount
        self.bank.changed(s.user_id)
        session.log("blackjack: %s bets %d" % (s.name, amount))
        if self.bet_until is None:
            self.bet_until = time.monotonic() + BET_SECS
        self.redraw()
        if all(t.bet for t in self.people()):
            self.deal()
        return None

    def deal(self):
        bets = {t.index: t.bet for t in self.people() if t.bet}
        if not bets:
            return
        if self.shoe.low():
            self.shoe.shuffle()
            self.tell("* The dealer shuffles a new shoe.")
        self.round_uids = {t.index: t.user_id for t in self.people() if t.bet}
        for t in self.seats:
            t.bet = 0
        self.bet_until = None
        self.round_no += 1
        self.moves_seen = self.events_seen = 0
        self.round = Round(bets, self.shoe)
        self.phase = "play"
        self.after_move()

    # ---- playing ----

    def do(self, s, action):
        r = self.round
        if (self.over or s.player not in self.players or r is None or self.phase != "play"
                or r.turn is None or r.turn[0] != s.index):
            return None
        if not r.options(s.index).get(action):
            return None
        extra = r.extra_bet(s.index, action)
        if extra:
            if self.db.to_poker_table(s.user_id, extra, reason="blackjack bet") is None:
                return s.player.session.toast("You need %s more to %s." % (
                    bank_credits(extra), action))
            self.bank.changed(s.user_id)
        try:
            r.act(s.index, action)
        except RulesError as e:
            return s.player.session.toast(str(e))
        self.after_move()
        return None

    def after_move(self):
        r = self.round
        self.turn_since = time.monotonic()
        moves = r.moves[self.moves_seen:]
        self.moves_seen = len(r.moves)
        for s in self.people():
            self._flights(s, moves)
        for e in r.events[self.events_seen:]:
            self.tell(e)
        self.events_seen = len(r.events)
        if r.phase == "dealer" and self.phase == "play":
            self.phase = "dealer"
            self.dealer_at = self.landed_at() + DEALER_DELAY
        if r.phase == "over" and self.phase != "over":
            self.settle()
        self.redraw()
        if r.turn is not None and self.phase == "play":
            t = self.seats[r.turn[0]]
            if t.player is not None and t.player in self.players:
                t.player.session.toast("Your turn.", seconds=2)

    def landed_at(self):
        """When every card in the air has landed (for everyone)."""
        return max([time.monotonic()] + [s.view.fly_free for s in self.people()])

    def tick(self):
        if self.over:
            return
        now = time.monotonic()
        done = [t for t in self.seats if t.said and now >= t.said_until]
        for t in done:
            t.said = ""
        r = self.round
        if self.phase == "betting":
            if self.bet_until is not None and now >= self.bet_until:
                return self.deal()
            if self.bet_until is not None and int(self.bet_until - now) != int(
                    self.bet_until - now + self.tick_interval):
                return self.redraw()                 # (the countdown)
        elif self.phase == "play" and r is not None and r.turn is not None:
            t = self.seats[r.turn[0]]
            if t.player is None or t.player not in self.players:
                r.stand_all(t.index)
                return self.after_move()
            left = TURN_SECS - (now - self.turn_since)
            if left <= 0:
                t.player.session.toast("Too slow: you stand.")
                r.act(t.index, "stand")
                return self.after_move()
            if int(left) != int(left + self.tick_interval):
                return self.draw(t)
        elif self.phase == "dealer" and now >= self.dealer_at:
            r.dealer_step()
            self.after_move()
            if self.phase == "dealer":
                self.dealer_at = self.landed_at() + DEALER_DELAY
            return None
        elif self.phase == "over" and now >= self.next_at:
            self.phase = "betting"
            return self.redraw()
        if done:
            self.redraw()
        return None

    def settle(self):
        """The round is over: each seat's winnings back to their balance (gone or not)."""
        r = self.round
        self.phase = "over"
        self.next_at = self.landed_at() + NEXT_ROUND
        words = []
        for seat in r.seats:
            uid = self.round_uids.get(seat)
            paid, staked = r.paid(seat), r.staked(seat)
            name = self.seats[seat].name or "?"
            if uid is not None:
                self.db.from_poker_table(uid, paid, "round %d" % self.round_no,
                                         reason="blackjack win")
                self.bank.changed(uid)
            if paid > staked:
                words.append("%s wins %s." % (name, num(paid - staked)))
            elif paid == staked:
                words.append("%s pushes." % name)
            else:
                words.append("%s loses %s." % (name, num(staked - paid)))
            t = self.seats[seat]
            if paid > staked and t.player is not None and t.player in self.players:
                self._kaching_later(t)
        self.tell(" ".join(words))
        self.server.serverlog.write("blackjack: round %d: %s %s" % (
            self.round_no, self.dealer_text(), " ".join(words)))

    def _kaching_later(self, t):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.call_later(max(0.0, t.view.fly_free - time.monotonic()),
                        lambda: t.player is not None and t.player in self.players
                        and t.player.session.sound(Sound.KACHING))

    # ---- flying cards (Caps.SPRITES) ----

    def _flights(self, s, moves):
        v = s.view
        if not moves or v is None or v.win is None or not v.win.shown:
            return
        if not s.player.session.caps & Caps.SPRITES:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        r = self.round
        now = time.monotonic()
        for m in moves:
            if m[0] == "reveal":
                continue
            target, k, face_up = m
            if target == "dealer":
                xs = fan(DEALER_X - DEALER_W // 2, DEALER_W, k + 1)
                row, key = DEALER_ROW, ("dealer", k)
                what = r.dealer[k] if face_up else "back"
            else:
                seat, j = target
                cards = r.hands[seat][j].cards
                rx, rw = hand_regions(seat, len(r.hands[seat]))[j]
                xs = fan(rx, rw, k + 1)
                row, key, what = SEAT_ROW, (target, k), cards[k]
            v.hidden.add(key)
            start = max(now, v.fly_free)
            land = start + FLY_FRAMES / 50.0
            v.fly_free = land + FLY_GAP
            loop.call_later(start - now, self._send_fly, s, what,
                            (TX + SHOE[0], TY + SHOE[1]), (TX + xs[k], TY + row * TILE_H))
            loop.call_later(land - now, self._landed, s, key)

    def _send_fly(self, s, what, src, dst):
        v = s.view
        if self.over or s.player is None or s.player not in self.players or v is None \
                or not v.win.shown:
            return
        t = v.cache.get(None, [(what, 0)], set(v.grid.cells))
        v.fly_n ^= 1
        s.player.session.fly(v.win, RESOURCE_SLOT, t * TILE_W * TILE_H, TILE_W // 2, TILE_H,
                             src, dst, FLY_FRAMES, CARD_COLOURS, step=2, n=v.fly_n)

    def _landed(self, s, key):
        v = s.view
        if v is None:
            return
        v.hidden.discard(key)
        if not self.over and s.player is not None and s.player in self.players and v.win.shown:
            self.draw(s)

    # ---- leaving ----

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
            return None
        session = player.session
        if s.bet:                                    # a bet not dealt yet: back to them
            self.db.from_poker_table(session.user_id, s.bet, "left the table",
                                     reason="blackjack bet back")
            self.bank.changed(session.user_id)
            s.bet = 0
        session.log("blackjack: %s leaves" % s.name)
        self.tell("* %s leaves." % s.name)
        s.player, s.view = None, None                # (the name stays for the round's lines)
        r = self.round
        if r is not None and self.phase in ("play", "dealer") and s.index in r.hands:
            r.stand_all(s.index)
        if not self.people():
            if r is not None and r.phase != "over":  # no one left to watch: finish it now
                for seat in r.seats:
                    r.stand_all(seat)
                while r.dealer_step():
                    pass
                if self.phase != "over":
                    self.settle()
            return self.end()
        if r is not None and self.phase == "play":
            self.after_move()
        else:
            self.redraw()
        if self.phase == "betting" and self.people() and all(t.bet for t in self.people()):
            self.deal()
        return None


def bank_credits(n):
    from ..bank import credits
    return credits(n)
