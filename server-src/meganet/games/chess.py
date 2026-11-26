"""Chess for two, with the rules enforced (chess_rules.py) and a chat beside the board.

Players meet in the Chess Lobby (challenge.py): one challenges, the other accepts. Colours
are drawn at random; a rematch swaps them. Each player sees the board from their own side.
Or Play Computer... in the lobby: a game against chess_engine.py at Easy, Normal or Hard. The
computer's seat (Computer) has no window; it moves after a short pause (thinking in its own
process), takes a draw only when it's behind, and always takes a rematch. Beating it pays
the bank's "game won" (as for any computer).

The board is a Grid gadget (Caps.GRID clients): 8 x 8 tiles of 32 x 16 pixels, made here
from chess_art.py and sent once a connection into resource slot RESOURCE_SLOT. Click one of
your pieces: it's framed (mark 1) and its moves show, a dot on an empty square and a frame
on a capture. Click one of them to move; a pawn reaching the last rank asks for its piece.
The last move's squares are framed in mark 2.

The window (a dynamic id): the board with its ranks and files, two status lines, the chat
and the moves ("12. Nf3"), a line to type, and Offer Draw / Resign / Rematch / Lobby. The
game ends with checkmate, stalemate, the automatic draws (insufficient material, the
fifty-move rule, threefold repetition), a draw agreed, resigning, or a player leaving. No
clocks yet. Games between two people are ranked once both have moved (rankings.py: wins,
losses, draws and an Elo rating; the lobby's Rankings... shows them).
"""

import asyncio
import logging
import os
import random
import time
import zlib

from ..protocol import Caps, GFlag, WFlag, GRID_MARK1, GRID_MARK2, clean_text
from ..ui import Button, Grid, Label, TextBox, TextView, Window, confirm, add_buttons, MARGIN
from . import chess_engine, rankings
from .base import Game
from .chess_art import PIECES
from .chess_rules import Position, WHITE, BLACK, colour, name

log = logging.getLogger("meganet")

RESOURCE_SLOT = 1                # (slot 0 is left for the next thing that wants one)
TILE_W, TILE_H = 32, 16
KINDS = "KQRBNP"
LIGHT, DARK = 240, 241           # protocol.GAME_COLOURS
WHITE_BODY, WHITE_EDGE = 242, 254
BLACK_BODY, BLACK_EDGE, BLACK_DETAIL = 244, 254, 245
DOT = 248
MARK_SELECT, MARK_LAST = 251, 253     # red: the piece picked and what it can take; gold: last
# tiles: 0 / 1 empty light / dark; 2-25 a piece (2 + dark * 12 + black * 6 + kind); 26 / 27
# a move dot on light / dark
T_DOT = 26
N_TILES = 28
CHAT_MAX = 120                   # characters a chat line
PAID_MOVES = 5                   # a game this long (or longer) earns credits (games.base.credit)

WIN_W, WIN_H = 624, 156
BOARD_X, BOARD_Y = 12, 4
RIGHT_X, RIGHT_W = 280, 336
WIN_RESIGN = 53
WIN_PROMOTE = 54
COMPUTER_PAUSE = float(os.environ.get("MEGANET_CHESS_PAUSE", 0.8))  # its move shows no sooner
DRAW_WHEN_BEHIND = -100          # the computer takes a draw when it's this far behind (or more)


class Computer:
    """The computer's seat (Play Computer in the lobby): not a Player, no session, no window."""
    session = None

    def __init__(self, level):
        self.level = level
        self.name = "Computer" if level == "Normal" else "Computer (%s)" % level


def make_tiles():
    """The 28 tiles, 32 x 16 bytes each, row by row (palette indices)."""
    out = bytearray()

    def square(bg, art=None, side=None):
        for y in range(TILE_H):
            for x in range(TILE_W):
                c = art[y][x // 2] if art else "."
                if c == ".":
                    out.append(bg)
                elif side == WHITE:
                    out.append(WHITE_BODY if c == "#" else WHITE_EDGE)
                else:
                    out.append({"#": BLACK_BODY, "o": BLACK_EDGE}.get(c, BLACK_DETAIL))

    square(LIGHT)
    square(DARK)
    for bg in (LIGHT, DARK):
        for side in (WHITE, BLACK):
            for k in KINDS:
                square(bg, PIECES[k], side)
    for bg in (LIGHT, DARK):                       # the move dots
        start = len(out)
        square(bg)
        for y, (x0, x1) in ((6, (14, 18)), (7, (12, 20)), (8, (12, 20)), (9, (14, 18))):
            for x in range(x0, x1):
                out[start + y * TILE_W + x] = DOT
    assert len(out) == N_TILES * TILE_W * TILE_H
    return bytes(out)


TILES = make_tiles()
TILES_KEY = "chess %08x" % zlib.crc32(TILES)     # (a new key when the art is edited)


def dark(sq):
    return (sq % 8 + sq // 8) % 2 == 0           # a1 is dark


def tile(sq, piece):
    if piece is None:
        return 1 if dark(sq) else 0
    return 2 + dark(sq) * 12 + (piece.islower()) * 6 + KINDS.index(piece.upper())


class View:
    """One player's window and what they've picked."""

    def __init__(self, player, side):
        self.player = player
        self.side = side
        self.selected = None


class Chess(Game):
    name = "Chess"
    description = ("Classic chess for two. Pick your opponent in the lobby, or play the "
                   "computer (Easy, Normal or Hard) when nobody else is on.")
    min_players = 2
    max_players = 2
    challenge = True             # a lobby to pick an opponent in (challenge.py)
    ranked = True                # games between people are ranked (rankings.py; the lobby's
                                 # Rankings... button)
    computer_levels = tuple(chess_engine.LEVELS)    # the lobby's Play Computer... (challenge.py)
    needs_caps = Caps.GRID

    # ---- setting up ----

    def start(self, players):
        level = self.options.get("level") if self.computers else None
        self.bot = Computer(level) if level else None
        self.bot_view = None
        seats = list(players) + ([self.bot] if self.bot else [])
        white = random.randrange(2)
        self.views = {p: View(p, WHITE if i == white else BLACK) for i, p in enumerate(seats)}
        if self.bot:
            self.bot_view = self.views[self.bot]
        for p, v in self.views.items():
            if p is self.bot:
                continue
            p.session.send_resource(RESOURCE_SLOT, TILES_KEY, TILES, title=self.name)
            self._window(v)
        self.new_game()

    def people(self):
        """The views of the people still playing (not the computer's)."""
        return [v for v in self.views.values() if v.player in self.players]

    def _window(self, v):
        p = v.player
        other = self.opponent(p)
        win = self.window(p, "Chess: %s v %s" % (p.name, other.name if other else "?"),
                          4, 18, WIN_W, WIN_H)
        v.grid = win.add(Grid(BOARD_X, BOARD_Y, 8, 8, TILE_W, TILE_H, RESOURCE_SLOT,
                              marks=(MARK_SELECT, MARK_LAST)))
        v.ranks = [win.add(Label(2, BOARD_Y + 16 * r + 4, 8, 8, "")) for r in range(8)]
        v.files = win.add(Label(BOARD_X - 4, BOARD_Y + 130, 264, 8, ""))
        v.status = win.add(Label(RIGHT_X, 4, RIGHT_W, 10, "", flags=GFlag.BOLD))
        v.status2 = win.add(Label(RIGHT_X, 16, RIGHT_W, 10, ""))
        v.chat = win.add(TextView(RIGHT_X, 30, RIGHT_W, 86))
        v.entry = win.add(TextBox(RIGHT_X, 120, 256, 12))
        win.add(Button(544, 118, 72, 16, "Send", GFlag.DEFAULT,
                       on_click=lambda b: self.say(v)))
        v.draw_b = win.add(Button(RIGHT_X, 136, 96, 16, "Offer Draw",
                                  on_click=lambda b: self.draw_button(v)))
        v.resign_b = win.add(Button(384, 136, 72, 16, "Resign",
                                    on_click=lambda b: self.resign_button(v)))
        v.rematch_b = win.add(Button(464, 136, 72, 16, "Rematch", GFlag.DISABLED,
                                     on_click=lambda b: self.rematch(v)))
        win.add(Button(544, 136, 72, 16, "Lobby", on_click=lambda b: self.to_lobby(v)))
        v.win = win
        self._labels(v)
        self.show(p, win)

    def _labels(self, v):
        def put(label, text):
            if label.shown:
                label.set_text(text)
            else:                                # (not shown yet: GADGET carries it)
                label.text = text
        for r, label in enumerate(v.ranks):
            put(label, str(8 - r) if v.side == WHITE else str(r + 1))
        files = "abcdefgh" if v.side == WHITE else "hgfedcba"
        put(v.files, "  " + "   ".join(files))

    def opponent(self, player):
        return next((p for p in self.views if p is not player), None)

    def new_game(self):
        self.pos = Position.start()
        self.last = None             # (from, to) of the last move
        self.result = None           # (score, text) once it's over
        self.draw_offer = None       # the View that offered one
        self.rematch_from = set()
        for v in self.people():
            v.selected = None
            v.draw_b.set_text("Offer Draw")
            v.draw_b.enable(True)
            v.resign_b.enable(True)
            v.rematch_b.enable(False)
        white = self.side_view(WHITE)
        black = self.side_view(BLACK)
        self.tell("* New game: %s has White, %s Black." % (white.player.name,
                                                          black.player.name))
        if self.players:
            self.players[0].session.log("chess: %s (White) v %s (Black)"
                                        % (white.player.name, black.player.name))
        self.redraw()
        self._computer_turn()

    def side_view(self, side):
        return next(v for v in self.views.values() if v.side == side)

    # ---- showing it ----

    def to_square(self, v, cell):
        """A cell of v's board (0 = top left) -> the square on it."""
        row, col = divmod(cell, 8)
        return (7 - row) * 8 + col if v.side == WHITE else row * 8 + (7 - col)

    def redraw(self):
        for v in self.views.values():
            if v.player in self.players:
                self.draw_board(v)
                self.draw_status(v)

    def draw_board(self, v):
        targets = {m.to for m in self.pos.moves_from(v.selected)} if v.selected is not None \
            else set()
        cells = []
        for cell in range(64):
            sq = self.to_square(v, cell)
            piece = self.pos.board[sq]
            t = tile(sq, piece)
            if sq in targets:
                if piece is None and not self.is_en_passant(v.selected, sq):
                    t = T_DOT + dark(sq)
                else:
                    t |= GRID_MARK1
            if sq == v.selected:
                t |= GRID_MARK1
            elif self.last and sq in self.last:
                t |= GRID_MARK2
            cells.append(t)
        v.grid.set_cells(cells)

    def is_en_passant(self, frm, to):
        return self.pos.ep == to and (self.pos.board[frm] or "").upper() == "P"

    def draw_status(self, v):
        mover = self.side_view(self.pos.turn)
        if self.result:
            score, text = self.result
            if score == "1/2-1/2":
                line = "Draw."
            else:
                winner = self.side_view(WHITE if score == "1-0" else BLACK)
                line = "You win!" if winner is v else "%s wins." % winner.player.name
            line2 = text
        else:
            side = "White" if self.pos.turn == WHITE else "Black"
            line = ("Your move (%s)" % side if mover is v
                    else "%s's move (%s)" % (mover.player.name, side))
            line2 = "Check!" if self.pos.in_check() else "Move %d" % self.pos.fullmove
            if self.draw_offer is not None and self.draw_offer is not v:
                line2 += ("  " if line2 else "") + "%s offers a draw." \
                    % self.draw_offer.player.name
        v.status.set_text(line)
        v.status2.set_text(line2[:42])

    def tell(self, line):
        for v in self.views.values():
            if v.player in self.players:
                v.chat.append(line)

    # ---- playing ----

    def on_select(self, player, window, gadget, index, double):
        v = self.views.get(player)
        if v is None or gadget is not v.grid or self.result:
            return None
        if self.pos.turn != v.side:
            return None
        sq = self.to_square(v, index)
        piece = self.pos.board[sq]
        if v.selected is not None and any(m.to == sq for m in self.pos.moves_from(v.selected)):
            frm = v.selected
            if self.pos.needs_promotion(frm, sq):
                return self.ask_promotion(v, frm, sq)
            return self.move(v, self.pos.find_move(frm, sq))
        if piece is not None and colour(piece) == v.side and v.selected != sq:
            v.selected = sq
        else:
            v.selected = None
        self.draw_board(v)
        return None

    def ask_promotion(self, v, frm, to):
        p = v.player
        win = Window.centred("Promote the Pawn", 312, 40, win_id=WIN_PROMOTE,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             on_close=lambda w: self._promoted(v, frm, to, None))
        win.add(Label(MARGIN, 4, 296, 10, "Make it a:", flags=GFlag.CENTRE))
        add_buttons(win, [(label, (lambda b, k=k: self._promoted(v, frm, to, k)),
                           GFlag.DEFAULT if k == "Q" else 0)
                          for label, k in (("Queen", "Q"), ("Rook", "R"),
                                           ("Bishop", "B"), ("Knight", "N"))], centre=True)
        p.windows.append(win)                    # (closed with the game's windows)
        win.show(p.session)

    def _promoted(self, v, frm, to, kind):
        p = v.player
        win = p.session.windows.get(WIN_PROMOTE)
        if win is not None:
            win.on_close = None
            win.close()
            if win in p.windows:
                p.windows.remove(win)
        if kind is None or self.result or self.pos.turn != v.side or p not in self.players:
            v.selected = None
            return self.draw_board(v)
        m = self.pos.find_move(frm, to, kind)
        return self.move(v, m) if m else self.draw_board(v)

    def move(self, v, m):
        pos = self.pos
        san = pos.san(m)
        number = "%d." % pos.fullmove if pos.turn == WHITE else "%d..." % pos.fullmove
        self.pos = pos.play(m)
        self.last = (m.frm, m.to)
        for w in self.views.values():
            w.selected = None
        if self.draw_offer is not None and self.draw_offer is not v:
            self.tell("* (%s's draw offer lapses.)" % self.draw_offer.player.name)
            self.draw_offer = None
        self._draw_buttons()
        self.tell("%s %s" % (number, san))
        result = self.pos.result()
        if result:
            score, why = result
            text = {"checkmate": "Checkmate.", "stalemate": "Stalemate.",
                    "insufficient material": "Draw: neither side can mate.",
                    "the fifty-move rule": "Draw by the fifty-move rule.",
                    "threefold repetition": "Draw by threefold repetition."}[why]
            return self.finish(score, text)
        self.redraw()
        self._computer_turn()
        return None

    # ---- the computer's moves ----

    def _computer_turn(self):
        """If it's the computer's move: think (chess_engine, in its own process), then play
        it, no sooner than COMPUTER_PAUSE after the person's move."""
        if self.bot is None or self.result or self.over or self.pos.turn != self.bot_view.side:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        pos, since = self.pos, time.monotonic()

        async def go():
            try:
                m = await chess_engine.think(pos, self.bot.level)
            except Exception:
                log.exception("chess: the computer couldn't move")
                return
            await asyncio.sleep(max(0.0, COMPUTER_PAUSE - (time.monotonic() - since)))
            if not self.over and not self.result and self.pos is pos and self.players:
                self.move(self.bot_view, m)
        self._thinking = loop.create_task(go())

    def computer_takes_draw(self):
        """Will the computer agree to a draw now? When it's behind (by its own reckoning)."""
        score = chess_engine.evaluate(self.pos)
        if self.pos.turn != self.bot_view.side:
            score = -score
        return score <= DRAW_WHEN_BEHIND

    def finish(self, score, text):
        self.result = (score, text)
        self.draw_offer = None
        for v in self.people():
            v.selected = None
            v.draw_b.enable(False)
            v.resign_b.enable(False)
            v.rematch_b.enable(len(self.players) == 2 or self.bot is not None)
        self.tell("* %s %s" % (score, text))
        if self.players:
            white, black = self.side_view(WHITE), self.side_view(BLACK)
            self.players[0].session.log("chess: %s v %s, %s %s after %d moves" % (
                white.player.name, black.player.name, score, text, self.pos.fullmove))
        self.pay(score)
        self.rank(score)
        self.redraw()

    def rank(self, score):
        """The rankings (rankings.py): a game between two people, once both have moved
        (fullmove 2: black has moved). The computer's games don't count."""
        if self.bot is not None or self.pos.fullmove < 2:
            return
        white, black = self.side_view(WHITE), self.side_view(BLACK)
        w, b = white.player.session, black.player.session
        if w is None or b is None or w.user_id is None or b.user_id is None:
            return
        db = w.server.db
        if score == "1-0":
            rankings.record(db, self.name, w.user_id, b.user_id)
        elif score == "0-1":
            rankings.record(db, self.name, b.user_id, w.user_id)
        else:
            rankings.record(db, self.name, w.user_id, b.user_id, draw=True)
        w.log("chess rankings: %s (white) and %s (black), %s" % (w.user, b.user, score))

    def pay(self, score):
        """The bank: both play (a game of at least PAID_MOVES moves); the winner wins."""
        if self.pos.fullmove < PAID_MOVES:
            return
        white, black = self.side_view(WHITE), self.side_view(BLACK)
        w, b = white.player.session, black.player.session
        for s in (w, b):
            self.credit(s, "game played")
        if score == "1-0":
            self.credit(w, "game won", beat=b)
        elif score == "0-1":
            self.credit(b, "game won", beat=w)

    # ---- the buttons ----

    def _draw_buttons(self):
        for v in self.people():
            offered = self.draw_offer is not None and self.draw_offer is not v
            v.draw_b.set_text("Accept Draw" if offered else "Offer Draw")
            v.draw_b.enable(not self.result and self.draw_offer is not v)

    def draw_button(self, v):
        if self.result:
            return None
        if self.draw_offer is not None and self.draw_offer is not v:
            self.tell("* %s accepts the draw." % v.player.name)
            return self.finish("1/2-1/2", "Draw agreed.")
        if self.bot is not None:                 # the computer answers at once
            self.tell("* %s offers a draw." % v.player.name)
            if self.computer_takes_draw():
                self.tell("* %s accepts the draw." % self.bot.name)
                return self.finish("1/2-1/2", "Draw agreed.")
            self.tell("* %s declines: play on." % self.bot.name)
            return None
        if self.draw_offer is None:
            self.draw_offer = v
            self.tell("* %s offers a draw." % v.player.name)
            self._draw_buttons()
            self.redraw()
        return None

    def resign_button(self, v):
        if self.result:
            return None

        def resign():
            if self.result or v.player not in self.players:
                return None
            return self.finish("0-1" if v.side == WHITE else "1-0",
                               "%s resigned." % v.player.name)
        confirm(v.player.session, "Resign", ["Resign this game?"], resign, WIN_RESIGN,
                command="Resign")
        return None

    def rematch(self, v):
        if not self.result or (len(self.players) < 2 and self.bot is None):
            return None
        self.rematch_from.add(v)
        if self.bot is not None:
            self.rematch_from.add(self.bot_view)     # (the computer always wants another)
        if len(self.rematch_from) == 2:
            for w in self.views.values():
                w.side = BLACK if w.side == WHITE else WHITE
                if w.player is not self.bot:
                    self._labels(w)
            self.new_game()
        else:
            self.tell("* %s wants a rematch." % v.player.name)
            v.rematch_b.enable(False)
        return None

    def to_lobby(self, v):
        session = v.player.session
        self.leave(v.player)
        lobby = self._lobby
        if lobby is not None:
            return lobby.open_lobby(session, type(self))
        return None

    def say(self, v):
        text = clean_text(v.entry.value).strip()[:CHAT_MAX]
        if not text:
            return None
        v.entry.set_text("")
        self.tell("%s: %s" % (v.player.name, text))
        return None

    # ---- leaving ----

    def on_leave(self, player):
        v = self.views.get(player)
        other = self.opponent(player)
        if v is not None and not self.result and other in self.players:
            self.tell("* %s left the game." % player.name)
            self.finish("0-1" if v.side == WHITE else "1-0", "%s left the game." % player.name)
        elif other in self.players:
            self.tell("* %s left." % player.name)
            self.views[other].rematch_b.enable(False)
        if not self.players:
            self.end()
