"""The rules of chess: legal moves (castling, en passant, promotion), check, checkmate,
stalemate and the automatic draws. No engine, no clocks: it only says what's allowed.

Squares are 0-63: a1 = 0, b1 = 1, ... h1 = 7, a2 = 8, ... h8 = 63 (index = rank * 8 + file).
Pieces are letters, upper case white, lower case black: K Q R B N P / k q r b n p; None is an
empty square.

    pos = Position.start()
    move = pos.find_move(12, 28)          # e2-e4 (None if not legal)
    san = pos.san(move)                   # "e4"
    pos = pos.play(move)
    pos.result()                          # None while the game goes on
"""

from collections import namedtuple

WHITE, BLACK = "w", "b"
FILES = "abcdefgh"
PROMOTIONS = "QRBN"

Move = namedtuple("Move", "frm to promo")        # promo: the piece letter (upper case) or None

KNIGHT_STEPS = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
KING_STEPS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
ROOK_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
BISHOP_DIRS = ((1, 1), (1, -1), (-1, 1), (-1, -1))


def name(sq):
    """0 -> "a1"."""
    return FILES[sq % 8] + str(sq // 8 + 1)


def square(text):
    """"e4" -> 28."""
    return "abcdefgh".index(text[0]) + 8 * (int(text[1]) - 1)


def colour(piece):
    return None if piece is None else (WHITE if piece.isupper() else BLACK)


def other(side):
    return BLACK if side == WHITE else WHITE


def _step(sq, df, dr):
    f, r = sq % 8 + df, sq // 8 + dr
    return r * 8 + f if 0 <= f < 8 and 0 <= r < 8 else None


class Position:
    """One position: the board, whose turn, castling rights, the en passant square, the
    move clocks, and the positions so far (for repetitions). Immutable: play() makes a new
    one."""

    def __init__(self, board, turn, castling, ep, halfmoves, fullmove, seen=()):
        self.board = tuple(board)
        self.turn = turn
        self.castling = castling        # a subset of "KQkq"
        self.ep = ep                    # the square a pawn just skipped, or None
        self.halfmoves = halfmoves      # since the last capture or pawn move
        self.fullmove = fullmove
        self.seen = seen + (self.key(),)
        self._legal = None

    @classmethod
    def start(cls):
        board = [None] * 64
        for f, p in enumerate("RNBQKBNR"):
            board[f], board[56 + f] = p, p.lower()
            board[8 + f], board[48 + f] = "P", "p"
        return cls(board, WHITE, "KQkq", None, 0, 1)

    @classmethod
    def from_fen(cls, fen):
        """A position from Forsyth-Edwards Notation (tests, puzzles)."""
        parts = fen.split()
        placement, turn, castling, ep = parts[:4]
        halfmoves, fullmove = (int(parts[4]), int(parts[5])) if len(parts) >= 6 else (0, 1)
        board = [None] * 64
        for r, row in enumerate(placement.split("/")):
            f = 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                else:
                    board[(7 - r) * 8 + f] = ch
                    f += 1
        return cls(board, turn, "" if castling == "-" else castling,
                   None if ep == "-" else square(ep), halfmoves, fullmove)

    def key(self):
        """What makes two positions the same, for repetitions."""
        ep = self.ep if self.ep is not None and self._ep_capturable() else None
        return (self.board, self.turn, self.castling, ep)

    def _ep_capturable(self):
        pawn = "P" if self.turn == WHITE else "p"
        back = -1 if self.turn == WHITE else 1
        return any(s is not None and self.board[s] == pawn and abs(s % 8 - self.ep % 8) == 1
                   for s in (_step(self.ep, -1, back), _step(self.ep, 1, back)))

    def king(self, side):
        k = "K" if side == WHITE else "k"
        return self.board.index(k)

    # ---- attacks ----

    def attacked(self, sq, by):
        """Is square `sq` attacked by side `by`?"""
        b = self.board

        def has(s, letters):
            return s is not None and b[s] is not None and colour(b[s]) == by \
                and b[s].upper() in letters

        fwd = -1 if by == WHITE else 1           # pawns attack from behind the square
        if has(_step(sq, -1, fwd), "P") or has(_step(sq, 1, fwd), "P"):
            return True
        if any(has(_step(sq, df, dr), "N") for df, dr in KNIGHT_STEPS):
            return True
        if any(has(_step(sq, df, dr), "K") for df, dr in KING_STEPS):
            return True
        for dirs, letters in ((ROOK_DIRS, "RQ"), (BISHOP_DIRS, "BQ")):
            for df, dr in dirs:
                s = _step(sq, df, dr)
                while s is not None:
                    if b[s] is not None:
                        if has(s, letters):
                            return True
                        break
                    s = _step(s, df, dr)
        return False

    def in_check(self, side=None):
        side = side or self.turn
        return self.attacked(self.king(side), other(side))

    # ---- moves ----

    def _pseudo(self):
        b, me = self.board, self.turn
        for sq, p in enumerate(b):
            if p is None or colour(p) != me:
                continue
            kind = p.upper()
            if kind == "P":
                yield from self._pawn_moves(sq)
            elif kind in "NK":
                for df, dr in (KNIGHT_STEPS if kind == "N" else KING_STEPS):
                    t = _step(sq, df, dr)
                    if t is not None and colour(b[t]) != me:
                        yield Move(sq, t, None)
                if kind == "K":
                    yield from self._castles(sq)
            else:
                dirs = {"R": ROOK_DIRS, "B": BISHOP_DIRS, "Q": ROOK_DIRS + BISHOP_DIRS}[kind]
                for df, dr in dirs:
                    t = _step(sq, df, dr)
                    while t is not None:
                        if b[t] is None:
                            yield Move(sq, t, None)
                        else:
                            if colour(b[t]) != me:
                                yield Move(sq, t, None)
                            break
                        t = _step(t, df, dr)

    def _pawn_moves(self, sq):
        b, me = self.board, self.turn
        fwd, home, last = (1, 1, 7) if me == WHITE else (-1, 6, 0)

        def add(t):
            if t // 8 == last:
                for p in PROMOTIONS:
                    yield Move(sq, t, p)
            else:
                yield Move(sq, t, None)

        one = _step(sq, 0, fwd)
        if one is not None and b[one] is None:
            yield from add(one)
            two = _step(one, 0, fwd)
            if sq // 8 == home and b[two] is None:
                yield Move(sq, two, None)
        for df in (-1, 1):
            t = _step(sq, df, fwd)
            if t is None:
                continue
            if (b[t] is not None and colour(b[t]) != me) or t == self.ep:
                yield from add(t)

    def _castles(self, sq):
        b, me = self.board, self.turn
        rights, home = ("KQ", 4) if me == WHITE else ("kq", 60)
        if sq != home or self.attacked(home, other(me)):
            return
        if rights[0] in self.castling and b[home + 1] is None and b[home + 2] is None \
                and not self.attacked(home + 1, other(me)):
            yield Move(home, home + 2, None)                  # O-O (the king's end square
        if rights[1] in self.castling and b[home - 1] is None and b[home - 2] is None \
                and b[home - 3] is None and not self.attacked(home - 1, other(me)):
            yield Move(home, home - 2, None)                  # is checked by legal_moves)

    def legal_moves(self):
        if self._legal is None:
            self._legal = [m for m in self._pseudo()
                           if not self._after(m).in_check(self.turn)]
        return self._legal

    def moves_from(self, sq):
        return [m for m in self.legal_moves() if m.frm == sq]

    def find_move(self, frm, to, promo=None):
        """The legal move frm -> to (with promotion piece `promo` if it's a promotion), or
        None. needs_promotion() says whether to ask for the piece."""
        for m in self.legal_moves():
            if m.frm == frm and m.to == to and (m.promo is None or m.promo == (promo or "Q")):
                return m
        return None

    def needs_promotion(self, frm, to):
        return any(m.frm == frm and m.to == to and m.promo for m in self.legal_moves())

    def _after(self, m):
        """The board after move m, without the bookkeeping (for check tests)."""
        b = list(self.board)
        p = b[m.frm]
        b[m.frm] = None
        if p.upper() == "P" and m.to == self.ep:              # en passant: the pawn behind
            b[m.to - 8 if self.turn == WHITE else m.to + 8] = None
        if p.upper() == "K" and abs(m.to - m.frm) == 2:      # castling: the rook too
            rook_from, rook_to = (m.frm + 3, m.frm + 1) if m.to > m.frm else (m.frm - 4, m.frm - 1)
            b[rook_to], b[rook_from] = b[rook_from], None
        if m.promo:
            p = m.promo if self.turn == WHITE else m.promo.lower()
        b[m.to] = p
        return Position.__new__(Position)._init_board(b, self.turn)

    def _init_board(self, board, turn):
        self.board, self.turn = tuple(board), turn
        return self

    def play(self, m):
        """The position after legal move m."""
        b = self._after(m).board
        p, captured = self.board[m.frm], self.board[m.to]
        castling = self.castling
        for sq, right in ((4, "KQ"), (60, "kq"), (0, "Q"), (7, "K"), (56, "q"), (63, "k")):
            if m.frm == sq or m.to == sq:                    # a king or rook moved or taken
                castling = "".join(c for c in castling if c not in right)
        ep = None
        if p.upper() == "P" and abs(m.to - m.frm) == 16:
            ep = (m.frm + m.to) // 2
        reset = p.upper() == "P" or captured is not None
        return Position(b, other(self.turn), castling, ep, 0 if reset else self.halfmoves + 1,
                        self.fullmove + (self.turn == BLACK), self.seen)

    # ---- the end ----

    def insufficient_material(self):
        """Neither side can ever mate: K v K, K + one minor piece v K, or bishops all on one
        colour."""
        rest = [(sq, p.upper()) for sq, p in enumerate(self.board) if p and p.upper() != "K"]
        if any(p in "QRP" for _, p in rest):
            return False
        if len(rest) <= 1:
            return True
        if all(p == "B" for _, p in rest):
            return len({(sq % 8 + sq // 8) % 2 for sq, _ in rest}) == 1
        return False

    def result(self):
        """None while the game goes on; else (score, why): score "1-0", "0-1" or "1/2-1/2"."""
        if not self.legal_moves():
            if self.in_check():
                return ("1-0" if self.turn == BLACK else "0-1"), "checkmate"
            return "1/2-1/2", "stalemate"
        if self.insufficient_material():
            return "1/2-1/2", "insufficient material"
        if self.halfmoves >= 100:
            return "1/2-1/2", "the fifty-move rule"
        if self.seen.count(self.key()) >= 3:
            return "1/2-1/2", "threefold repetition"
        return None

    # ---- notation ----

    def san(self, m):
        """Standard algebraic notation for legal move m: "e4", "Nxf3+", "O-O", "e8=Q#"."""
        p = self.board[m.frm].upper()
        if p == "K" and abs(m.to - m.frm) == 2:
            text = "O-O" if m.to > m.frm else "O-O-O"
        else:
            capture = self.board[m.to] is not None or (p == "P" and m.to == self.ep)
            if p == "P":
                text = (FILES[m.frm % 8] + "x" if capture else "") + name(m.to)
                if m.promo:
                    text += "=" + m.promo
            else:
                rivals = [o for o in self.legal_moves() if o.to == m.to and o.frm != m.frm
                          and self.board[o.frm].upper() == p]
                where = ""
                if rivals:
                    if all(o.frm % 8 != m.frm % 8 for o in rivals):
                        where = FILES[m.frm % 8]
                    elif all(o.frm // 8 != m.frm // 8 for o in rivals):
                        where = str(m.frm // 8 + 1)
                    else:
                        where = name(m.frm)
                text = p + where + ("x" if capture else "") + name(m.to)
        after = self.play(m)
        if after.in_check():
            text += "#" if not after.legal_moves() else "+"
        return text
