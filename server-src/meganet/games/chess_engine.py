"""The computer's chess (games/chess.py): picks a move for a chess_rules.Position.

A small, plain engine: iterative-deepening negamax with alpha-beta, captures and promotions
tried first (and the last depth's best move), a quiescence search of captures at the leaves
(so it doesn't leave pieces hanging), and an evaluation of material plus the "simplified
evaluation function" piece-square tables (a king table for the middle game and one for the
endgame). Repetitions and the fifty-move rule count as draws.

chess_rules is written to be right, not fast (a few thousand positions a second here), so the
levels look only a few moves ahead:

    Easy    1 move ahead, and a little randomness: it blunders now and then
    Normal  up to 2 moves ahead (it takes what you leave hanging, and sees simple tactics)
    Hard    up to 4, as far as it gets in its time

choose(pos, level) is the search itself (tests call it); think(pos, level) runs it in another
process, one at a time, so the server goes on serving everyone meanwhile.
"""

import asyncio
import multiprocessing
import random
import time
from concurrent.futures import ProcessPoolExecutor

from .chess_rules import WHITE

LEVELS = {"Easy": (1, 1.0, 40), "Normal": (2, 2.5, 0), "Hard": (4, 6.0, 0)}
# level -> (most plies, seconds, random noise in centipawns at the root)
OPENING_MOVES, OPENING_NOISE = 4, 20   # some variety in the first moves, at every level

VALUE = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}
MATE = 100000
INF = 10 ** 9


def _table(rows):
    """8 rows of 8, rank 8 first (as written) -> 64 values indexed a1 = 0 for White."""
    vals = [int(v) for row in rows for v in row.split()]
    return [vals[(7 - sq // 8) * 8 + sq % 8] for sq in range(64)]


PST = {
    "P": _table(["0 0 0 0 0 0 0 0", "50 50 50 50 50 50 50 50", "10 10 20 30 30 20 10 10",
                 "5 5 10 25 25 10 5 5", "0 0 0 20 20 0 0 0", "5 -5 -10 0 0 -10 -5 5",
                 "5 10 10 -20 -20 10 10 5", "0 0 0 0 0 0 0 0"]),
    "N": _table(["-50 -40 -30 -30 -30 -30 -40 -50", "-40 -20 0 0 0 0 -20 -40",
                 "-30 0 10 15 15 10 0 -30", "-30 5 15 20 20 15 5 -30",
                 "-30 0 15 20 20 15 0 -30", "-30 5 10 15 15 10 5 -30",
                 "-40 -20 0 5 5 0 -20 -40", "-50 -40 -30 -30 -30 -30 -40 -50"]),
    "B": _table(["-20 -10 -10 -10 -10 -10 -10 -20", "-10 0 0 0 0 0 0 -10",
                 "-10 0 5 10 10 5 0 -10", "-10 5 5 10 10 5 5 -10",
                 "-10 0 10 10 10 10 0 -10", "-10 10 10 10 10 10 10 -10",
                 "-10 5 0 0 0 0 5 -10", "-20 -10 -10 -10 -10 -10 -10 -20"]),
    "R": _table(["0 0 0 0 0 0 0 0", "5 10 10 10 10 10 10 5", "-5 0 0 0 0 0 0 -5",
                 "-5 0 0 0 0 0 0 -5", "-5 0 0 0 0 0 0 -5", "-5 0 0 0 0 0 0 -5",
                 "-5 0 0 0 0 0 0 -5", "0 0 0 5 5 0 0 0"]),
    "Q": _table(["-20 -10 -10 -5 -5 -10 -10 -20", "-10 0 0 0 0 0 0 -10",
                 "-10 0 5 5 5 5 0 -10", "-5 0 5 5 5 5 0 -5", "0 0 5 5 5 5 0 -5",
                 "-10 5 5 5 5 5 0 -10", "-10 0 5 0 0 0 0 -10",
                 "-20 -10 -10 -5 -5 -10 -10 -20"]),
    "K": _table(["-30 -40 -40 -50 -50 -40 -40 -30", "-30 -40 -40 -50 -50 -40 -40 -30",
                 "-30 -40 -40 -50 -50 -40 -40 -30", "-30 -40 -40 -50 -50 -40 -40 -30",
                 "-20 -30 -30 -40 -40 -30 -30 -20", "-10 -20 -20 -20 -20 -20 -20 -10",
                 "20 20 0 0 0 0 20 20", "20 30 10 0 0 10 30 20"]),
}
KING_END = _table(["-50 -40 -30 -20 -20 -30 -40 -50", "-30 -20 -10 0 0 -10 -20 -30",
                   "-30 -10 20 30 30 20 -10 -30", "-30 -10 30 40 40 30 -10 -30",
                   "-30 -10 30 40 40 30 -10 -30", "-30 -10 20 30 30 20 -10 -30",
                   "-30 -30 0 0 0 0 -30 -30", "-50 -30 -30 -30 -30 -30 -30 -50"])
ENDGAME = 1300       # pieces (not pawns or kings) worth at most this, both sides: an endgame


def evaluate(pos):
    """The position's score for the side to move (centipawns)."""
    b = pos.board
    pieces = sum(VALUE[p.upper()] for p in b if p and p.upper() not in "PK")
    end = pieces <= ENDGAME
    score = 0
    for sq, p in enumerate(b):
        if p is None:
            continue
        kind = p.upper()
        white = p.isupper()
        idx = sq if white else (7 - sq // 8) * 8 + sq % 8        # (mirrored for Black)
        table = KING_END if kind == "K" and end else PST[kind]
        v = VALUE[kind] + table[idx]
        score += v if white else -v
    return score if pos.turn == WHITE else -score


class _Timeout(Exception):
    pass


class Search:
    def __init__(self, deadline):
        self.deadline = deadline
        self.nodes = 0

    def tick(self):
        self.nodes += 1
        if self.nodes & 127 == 0 and time.monotonic() > self.deadline:
            raise _Timeout()

    @staticmethod
    def captures_first(pos, moves, first=None):
        """Moves in order: `first`, then promotions and captures (most valuable victim,
        least valuable attacker first), then the rest."""
        b = pos.board

        def key(m):
            if m == first:
                return -10 ** 6
            victim = b[m.to]
            if m.promo:
                return -9000 - VALUE[m.promo]
            if victim is not None:
                return -10 * VALUE[victim.upper()] + VALUE[b[m.frm].upper()] // 10
            if m.to == pos.ep and b[m.frm].upper() == "P":
                return -1000
            return 0
        return sorted(moves, key=key)

    def negamax(self, pos, depth, alpha, beta, ply):
        self.tick()
        if ply and (pos.halfmoves >= 100 or pos.seen.count(pos.key()) >= 2):
            return 0                                   # a draw (a repetition: drawn already)
        moves = pos.legal_moves()
        if not moves:
            return -MATE + ply if pos.in_check() else 0
        if depth <= 0:
            return self.quiesce(pos, alpha, beta, ply, 0, moves)
        best = -INF
        for m in self.captures_first(pos, moves):
            score = -self.negamax(pos.play(m), depth - 1, -beta, -alpha, ply + 1)
            if score > best:
                best = score
            if score > alpha:
                alpha = score
            if alpha >= beta:
                break
        return best

    def quiesce(self, pos, alpha, beta, ply, qdepth, moves=None):
        """Only captures (and promotions), until the position is quiet."""
        self.tick()
        if moves is None:
            moves = pos.legal_moves()
            if not moves:
                return -MATE + ply if pos.in_check() else 0
        stand = evaluate(pos)
        if stand >= beta:
            return stand
        alpha = max(alpha, stand)
        if qdepth >= 6:
            return stand
        b = pos.board
        loud = [m for m in moves if b[m.to] is not None or m.promo or
                (m.to == pos.ep and b[m.frm].upper() == "P")]
        for m in self.captures_first(pos, loud):
            score = -self.quiesce(pos.play(m), -beta, -alpha, ply + 1, qdepth + 1)
            if score >= beta:
                return score
            alpha = max(alpha, score)
        return alpha


def choose(pos, level="Normal", rng=None, seconds=None):
    """The move the computer plays in `pos` (it has a legal move: the game isn't over)."""
    most, secs, noise = LEVELS.get(level, LEVELS["Normal"])
    if pos.fullmove <= OPENING_MOVES:
        noise = max(noise, OPENING_NOISE)              # (not the same opening every game)
    rng = rng or random.Random()
    deadline = time.monotonic() + (secs if seconds is None else seconds)
    search = Search(deadline)
    moves = Search.captures_first(pos, pos.legal_moves())
    if len(moves) == 1:
        return moves[0]
    best, scores = moves[0], {}
    # Alpha-beta gives exact scores only to moves within the window: the rest come back as
    # bounds ("no better than the best so far"), which may equal it. With noise, the window
    # is wider by twice the noise, so every move the noise might pick has its real score.
    margin = 2 * noise
    for depth in range(1, most + 1):
        done = {}
        try:
            alpha = -INF
            for m in Search.captures_first(pos, moves, best):
                low = alpha - margin if alpha > -INF else -INF
                score = -search.negamax(pos.play(m), depth - 1, -INF, -low, 1)
                done[m] = score
                alpha = max(alpha, score)
        except _Timeout:
            if not done:
                break
            if max(done.values()) <= max(scores.values(), default=-INF):
                break                                  # (half a depth that found nothing better)
        scores = done
        if noise:
            best = max(scores, key=lambda m: scores[m] + rng.randint(-noise, noise))
        else:
            best = max(scores, key=scores.get)
        if scores[best] >= MATE - 100 or time.monotonic() > deadline:
            break
    return best


# ---- in another process ----

_pool = None


def _thinker():
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=1,
                                    mp_context=multiprocessing.get_context("spawn"))
    return _pool


def _reset():
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
    _pool = None


async def think(pos, level="Normal"):
    """choose() in the engine's process; in a thread if that can't run."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(_thinker(), choose, pos, level)
    except Exception:
        _reset()
        return await asyncio.to_thread(choose, pos, level)
