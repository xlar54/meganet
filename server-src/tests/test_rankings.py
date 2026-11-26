"""Rankings (games/rankings.py): chess games between people are recorded once both have moved
(a resignation or a player leaving is a loss), with an Elo rating; the Chess Lobby's
Rankings... lists everyone best first and says where the viewer stands."""

import unittest

from meganet import db as dbmod
from meganet.games import rankings
from meganet.games.challenge import WIN_GAME_LOBBY
from meganet.protocol import Kind
from tests.test_chess import ChessBase, gid_of


class RatingTest(unittest.TestCase):
    def test_elo(self):
        self.assertEqual(rankings.new_ratings(1200, 1200, 1), (1216, 1184))
        self.assertEqual(rankings.new_ratings(1200, 1200, 0.5), (1200, 1200))
        up, down = rankings.new_ratings(1100, 1300, 1)        # beating a stronger player
        self.assertGreater(up - 1100, 16)
        self.assertEqual(up - 1100, 1300 - down)

    def test_record_and_order(self):
        d = dbmod.Database(":memory:")
        for n in ("ann", "ben", "cat"):
            d.create_user(n, "x")
        ids = {n: d.user(n)["id"] for n in ("ann", "ben", "cat")}
        rankings.record(d, "Chess", ids["ann"], ids["ben"])
        rankings.record(d, "Chess", ids["ann"], ids["cat"])
        rankings.record(d, "Chess", ids["cat"], ids["ben"], draw=True)
        rows = d.game_rankings("Chess")
        self.assertEqual([r[0] for r in rows], ["ann", "cat", "ben"])
        self.assertEqual(rows[0][2:5], (2, 0, 0))
        self.assertEqual(rows[1][2:5], (0, 1, 1))
        self.assertEqual(d.game_rankings("Checkers"), [])
        lines, _ = rankings.rows(d, "Chess")
        self.assertTrue(lines[0].startswith("   1  ann"), lines[0])
        for line in lines + [rankings.COLUMNS]:
            self.assertLessEqual(len(line), (rankings.W - 2 * 6 - 17) // 8, line)
        self.assertEqual(rankings.you_line(d, "Chess", ids["cat"]), "You are #2 of 3, rated 1185.")
        d.close()


class RankedGameTest(ChessBase):
    async def rankings_window(self, c):
        """Back in the lobby, Rankings...: (rows, the line about the viewer)."""
        if WIN_GAME_LOBBY not in c.windows:
            await self.in_lobby(c)
        c.windows.pop(rankings.WIN_RANKINGS, None)
        c.click_text(WIN_GAME_LOBBY, "Rankings...")
        w = await c.wait_window("Chess Rankings")
        labels = [g["text"] for g in w.gadgets.values() if g["kind"] == Kind.LABEL]
        return w.gadgets[gid_of(w, Kind.LISTBOX)]["rows"], labels[-1]

    async def test_a_resignation_is_ranked(self):
        a, b, wa, wb = await self.game()
        await self.move(a, wa, True, "e2", "e4")
        await self.move(b, wb, False, "e7", "e5")
        b.click_text(wb.id, "Resign")
        sure = await b.wait_window("Resign")
        b.click_text(sure.id, "Resign")
        await a.wait_for(lambda: self.status(wa) == ("You win!", "bob resigned."), "resigned")
        rows = self.server.db.game_rankings("Chess")
        self.assertEqual([(r[0], r[1], r[2], r[3]) for r in rows],
                         [("alice", 1216, 1, 0), ("bob", 1184, 0, 1)])
        b.click_text(wb.id, "Lobby")
        await b.wait_window("Chess Lobby")
        lines, you = await self.rankings_window(b)
        self.assertTrue(lines[0].startswith("   1  alice") and "1216" in lines[0], lines)
        self.assertTrue(lines[1].startswith("   2  bob"), lines)
        self.assertEqual(you, "You are #2 of 2, rated 1184.")

    async def test_unranked_before_both_have_moved(self):
        a, b, wa, wb = await self.game()
        await self.move(a, wa, True, "e2", "e4")
        a.close_box(wa.id)                                   # (alice leaves: she loses)
        await b.wait_for(lambda: self.status(wb) == ("You win!", "alice left the game."), "won")
        self.assertEqual(self.server.db.game_rankings("Chess"), [])
        b.click_text(wb.id, "Lobby")
        await b.wait_window("Chess Lobby")
        lines, you = await self.rankings_window(b)
        self.assertEqual(lines, ["  No ranked games yet."])
        self.assertEqual(you, "You have no ranked games yet.")
