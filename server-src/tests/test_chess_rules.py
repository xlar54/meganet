"""The chess rules (games/chess_rules.py): move counts checked against the published perft
numbers (https://www.chessprogramming.org/Perft_Results), and the special cases."""

import unittest

from meganet.games.chess_rules import Position, square, Move


def perft(pos, depth):
    if depth == 0:
        return 1
    moves = pos.legal_moves()
    if depth == 1:
        return len(moves)
    return sum(perft(pos.play(m), depth - 1) for m in moves)


def play(pos, *moves):
    """Play moves given as "e2e4" or "e7e8q"."""
    for text in moves:
        m = pos.find_move(square(text[:2]), square(text[2:4]),
                          text[4].upper() if len(text) > 4 else None)
        assert m is not None, "%s isn't legal" % text
        pos = pos.play(m)
    return pos


class PerftTest(unittest.TestCase):
    def test_start(self):
        pos = Position.start()
        self.assertEqual([perft(pos, d) for d in (1, 2, 3)], [20, 400, 8902])

    def test_kiwipete(self):                 # castling, en passant, promotions, pins
        pos = Position.from_fen(
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
        self.assertEqual([perft(pos, d) for d in (1, 2)], [48, 2039])

    def test_position3(self):                # en passant out of a pin
        pos = Position.from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1")
        self.assertEqual([perft(pos, d) for d in (1, 2, 3, 4)], [14, 191, 2812, 43238])

    def test_position4(self):                # promotions, castling through check
        pos = Position.from_fen(
            "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1")
        self.assertEqual([perft(pos, d) for d in (1, 2, 3)], [6, 264, 9467])

    def test_position5(self):
        pos = Position.from_fen("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8")
        self.assertEqual([perft(pos, d) for d in (1, 2)], [44, 1486])


class RulesTest(unittest.TestCase):
    def test_fools_mate(self):
        pos = play(Position.start(), "f2f3", "e7e5", "g2g4")
        m = pos.find_move(square("d8"), square("h4"))
        self.assertEqual(pos.san(m), "Qh4#")
        self.assertEqual(pos.play(m).result(), ("0-1", "checkmate"))

    def test_stalemate(self):
        pos = Position.from_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
        self.assertEqual(pos.result(), ("1/2-1/2", "stalemate"))

    def test_castling(self):
        pos = play(Position.start(), "e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6")
        m = pos.find_move(square("e1"), square("g1"))
        self.assertEqual(pos.san(m), "O-O")
        after = pos.play(m)
        self.assertEqual((after.board[square("g1")], after.board[square("f1")]), ("K", "R"))
        self.assertNotIn("K", after.castling)
        self.assertNotIn("Q", after.castling)
        # through an attacked square: not allowed
        pos = Position.from_fen("4k3/8/8/8/8/8/5r2/4K2R w K - 0 1")
        self.assertIsNone(pos.find_move(square("e1"), square("g1")))
        # out of check: not allowed
        pos = Position.from_fen("4k3/8/8/8/8/8/4r3/4K2R w K - 0 1")
        self.assertIsNone(pos.find_move(square("e1"), square("g1")))

    def test_en_passant(self):
        pos = play(Position.start(), "e2e4", "a7a6", "e4e5", "d7d5")
        m = pos.find_move(square("e5"), square("d6"))
        self.assertEqual(pos.san(m), "exd6")
        after = pos.play(m)
        self.assertIsNone(after.board[square("d5")], "the pawn taken")
        # only straight after the double step
        pos = play(Position.start(), "e2e4", "a7a6", "e4e5", "d7d5", "h2h3", "h7h6")
        self.assertIsNone(pos.find_move(square("e5"), square("d6")))

    def test_promotion(self):
        pos = Position.from_fen("8/P6k/8/8/8/8/8/K7 w - - 0 1")
        self.assertTrue(pos.needs_promotion(square("a7"), square("a8")))
        m = pos.find_move(square("a7"), square("a8"), "N")
        self.assertEqual(m, Move(square("a7"), square("a8"), "N"))
        self.assertEqual(pos.play(m).board[square("a8")], "N")
        self.assertEqual(pos.san(pos.find_move(square("a7"), square("a8"), "Q")), "a8=Q")

    def test_pinned_piece_cant_move(self):
        pos = Position.from_fen("4k3/4r3/8/8/8/8/4N3/4K3 w - - 0 1")
        self.assertEqual(pos.moves_from(square("e2")), [])

    def test_draws(self):
        self.assertEqual(Position.from_fen("4k3/8/8/8/8/8/8/4KB2 w - - 0 1").result(),
                         ("1/2-1/2", "insufficient material"))
        self.assertIsNone(Position.from_fen("4k3/8/8/8/8/8/8/3QK3 w - - 0 1").result())
        self.assertEqual(Position.from_fen("4k3/8/8/8/8/8/8/R3K3 w - - 100 80").result(),
                         ("1/2-1/2", "the fifty-move rule"))
        pos = Position.start()
        for _ in range(2):
            pos = play(pos, "g1f3", "g8f6", "f3g1", "f6g8")
        self.assertEqual(pos.result(), ("1/2-1/2", "threefold repetition"))

    def test_disambiguation(self):
        pos = Position.from_fen("4k3/8/8/8/8/8/8/R3K2R w - - 0 1")    # (the king blocks h1)
        self.assertEqual(pos.san(pos.find_move(square("a1"), square("d1"))), "Rd1")
        pos = Position.from_fen("4k3/8/8/8/8/8/4K3/R6R w - - 0 1")
        self.assertEqual(pos.san(pos.find_move(square("a1"), square("d1"))), "Rad1")
        pos = Position.from_fen("4k3/8/8/R7/8/8/8/R3K3 w - - 0 1")
        self.assertEqual(pos.san(pos.find_move(square("a1"), square("a3"))), "R1a3")


if __name__ == "__main__":
    unittest.main()
