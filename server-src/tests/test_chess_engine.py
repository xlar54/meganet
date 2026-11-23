"""The computer's chess (games/chess_engine.py) on its own, then a game against it through
the fake client: Play Computer... in the lobby, its moves, a draw offer, a rematch, and the
lobby showing the game."""

import asyncio
import random
import unittest
from unittest import mock

from meganet.games import chess, chess_engine
from meganet.games.challenge import WIN_GAME_LOBBY
from meganet.games.chess_engine import choose, evaluate
from meganet.games.chess_rules import Position, WHITE, BLACK, square
from meganet.protocol import Kind
from tests.test_chess import ChessBase, GRID, gid_of


def best(fen, level="Normal"):
    p = Position.from_fen(fen)
    return p.san(choose(p, level, rng=random.Random(1)))


class EngineTest(unittest.TestCase):
    def test_mate_in_one(self):
        self.assertEqual(best("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 10"), "Ra8#")
        self.assertEqual(best("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 10", "Easy"), "Ra8#")

    def test_takes_a_hanging_queen(self):
        # Black's queen on d4 is free for the knight on f3 (nothing defends it)
        self.assertEqual(best("rnb1kbnr/pppp1ppp/8/8/3q4/5N2/PPPPPPPP/RNBQKB1R w KQkq - 0 4"),
                         "Nxd4")

    def test_doesnt_hang_its_queen(self):
        # Black to move; Qxb2 would lose the queen to Rb1 ... (protected b-pawn: Bc1)
        m = best("rnb1kbnr/pppp1ppp/8/4p3/4P1q1/2N5/PPPP1PPP/R1BQKBNR b KQkq - 0 4")
        p = Position.from_fen("rnb1kbnr/pppp1ppp/8/4p3/4P1q1/2N5/PPPP1PPP/R1BQKBNR b KQkq - "
                              "0 4")
        after = p.play(p.find_move(*self.move_squares(p, m)))
        self.assertGreater(-evaluate(after) + 0, -800, "it keeps its queen")

    @staticmethod
    def move_squares(p, san):
        m = next(m for m in p.legal_moves() if p.san(m) == san)
        return m.frm, m.to, m.promo

    def test_evaluate_is_from_the_movers_side(self):
        p = Position.from_fen("4k3/8/8/8/8/8/8/Q3K3 w - - 0 1")
        self.assertGreater(evaluate(p), 800)
        p = Position.from_fen("4k3/8/8/8/8/8/8/Q3K3 b - - 0 1")
        self.assertLess(evaluate(p), -800)

    def test_plays_only_legal_moves_to_the_end(self):
        rng = random.Random(7)
        p = Position.start()
        for _ in range(40):
            if p.result():
                break
            m = choose(p, "Easy", rng=rng, seconds=0.5)
            self.assertIn(m, p.legal_moves())
            p = p.play(m)

    def test_one_legal_move_is_played_at_once(self):
        p = Position.from_fen("7k/8/8/8/8/8/6q1/7K w - - 0 1")      # Kxg2 is all there is
        self.assertEqual(p.san(choose(p, "Hard")), "Kxg2")

    def test_thinks_in_another_process(self):
        async def run():
            return await chess_engine.think(Position.start(), "Easy")
        m = asyncio.run(run())
        self.assertIn(m, Position.start().legal_moves())


async def quick_think(pos, level):
    """(tests) The engine at its quickest, in this process."""
    return choose(pos, "Easy", rng=random.Random(3), seconds=0.3)


class ComputerGameTest(ChessBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for patch in (mock.patch.object(chess_engine, "think", quick_think),
                      mock.patch.object(chess, "COMPUTER_PAUSE", 0)):
            patch.start()
            self.addCleanup(patch.stop)

    async def vs_computer(self, level="Normal", human_white=True):
        a = await self.signed_on("alice", caps=GRID)
        await self.in_lobby(a)
        await a.wait_for(lambda: a.enabled(WIN_GAME_LOBBY, "Play Computer..."), "the button")
        a.click_text(WIN_GAME_LOBBY, "Play Computer...")
        ask = await a.wait_window("Play the Computer")
        with mock.patch.object(chess.random, "randrange", lambda n: 0 if human_white else 1):
            a.click_text(ask.id, level)
            w = await a.wait_window("Chess:")
        g = next(g for g in self.server.games.running if isinstance(g, chess.Chess))
        return a, w, g

    async def test_play_the_computer(self):
        a, w, g = await self.vs_computer("Hard")
        self.assertEqual(w.title, "Chess: alice v Computer (Hard)")
        self.assertNotIn(WIN_GAME_LOBBY, a.windows, "out of the lobby")
        self.assertEqual(g.views[g.players[0]].side, WHITE)
        await self.move(a, w, True, "e2", "e4")
        await a.wait_for(lambda: g.pos.turn == WHITE and g.pos.fullmove == 2, "it answered")
        await a.wait_for(lambda: any(l.startswith("1... ") for l in self.chat(w)), "its move")
        self.assertEqual(self.status(w)[0], "Your move (White)")

    async def test_computer_moves_first_as_white(self):
        a, w, g = await self.vs_computer("Easy", human_white=False)
        await a.wait_for(lambda: g.pos.turn == BLACK, "White's first move")
        self.assertTrue(any(l.startswith("1. ") for l in self.chat(w)))

    async def test_draw_offer_and_rematch(self):
        a, w, g = await self.vs_computer()
        a.click_text(w.id, "Offer Draw")                 # even: it plays on
        await a.wait_for(lambda: any("declines" in l for l in self.chat(w)), "declined")
        self.assertIsNone(g.result)
        # a position where it's well behind: it takes the draw
        g.pos = Position.from_fen("4k3/8/8/8/8/8/8/QQ2K3 w - - 0 30")
        a.click_text(w.id, "Offer Draw")
        await a.wait_for(lambda: g.result is not None, "accepted")
        self.assertEqual(g.result, ("1/2-1/2", "Draw agreed."))
        await a.wait_for(lambda: a.enabled(w.id, "Rematch"), "rematch")
        a.click_text(w.id, "Rematch")                    # at once, colours swapped
        await a.wait_for(lambda: g.result is None and g.views[g.players[0]].side == BLACK,
                         "a new game")
        await a.wait_for(lambda: g.pos.turn == BLACK, "the computer opens as White")

    async def test_resign_and_leave(self):
        a, w, g = await self.vs_computer()
        a.click_text(w.id, "Resign")
        confirm = await a.wait_window("Resign")
        a.click_text(confirm.id, "Resign")
        await a.wait_for(lambda: g.result is not None, "resigned")
        self.assertEqual(g.result[0], "0-1")
        a.click_text(w.id, "Lobby")
        await a.wait_window("Chess Lobby")
        await a.wait_for(lambda: g.over, "the game ended")

    async def test_the_lobby_shows_the_game(self):
        a, w, g = await self.vs_computer()
        b = await self.signed_on("bob", caps=GRID)
        await self.in_lobby(b)
        await b.wait_for(lambda: any("alice" in r and "Computer" in r
                                     for r in self.lobby_rows(b)), "alice playing Computer")


if __name__ == "__main__":
    unittest.main()
