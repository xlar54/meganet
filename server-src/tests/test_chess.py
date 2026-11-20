"""Chess (games/chess.py) through the fake client: the lobby and its challenges, the board
(a GRID gadget and its tiles), moves by clicking, the rules, chat, and the ways a game ends."""

from unittest import mock

from meganet.games import chess
from meganet.games.challenge import WIN_GAME_LOBBY, WIN_CHALLENGED
from meganet.games.chess_rules import square
from meganet.games.lobby import WIN_GAMES
from meganet.protocol import Caps, Kind, GRID_MARK1, GRID_MARK2, GRID_TILE_MASK
from tests.test_server import ServerTest

GRID = Caps.GRID


def gid_of(win, kind):
    return next(gid for gid, g in win.gadgets.items() if g["kind"] == kind)


class ChessBase(ServerTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patch = mock.patch.object(chess.random, "randrange", lambda n: 0)   # challenger: White
        patch.start()
        self.addCleanup(patch.stop)

    async def in_lobby(self, c):
        c.windows.pop(WIN_GAMES, None)
        c.pick("Games")
        games = await c.wait_window("Games")
        lb = gid_of(games, Kind.LISTBOX)
        await c.wait_for(lambda: games.gadgets[lb]["rows"], "game rows")
        row = next(i for i, r in enumerate(games.gadgets[lb]["rows"]) if r.startswith("Chess"))
        c.select(WIN_GAMES, lb, row)
        c.click_text(WIN_GAMES, "Join")
        return await c.wait_window("Chess Lobby")

    def lobby_rows(self, c):
        w = c.windows.get(WIN_GAME_LOBBY)
        return w.gadgets[gid_of(w, Kind.LISTBOX)]["rows"] if w else []

    async def challenge(self, a, b):
        """a challenges b (both in the lobby)."""
        await a.wait_for(lambda: any(r.startswith(b.name) for r in self.lobby_rows(a)), b.name)
        w = a.windows[WIN_GAME_LOBBY]
        row = next(i for i, r in enumerate(self.lobby_rows(a)) if r.startswith(b.name))
        a.select(WIN_GAME_LOBBY, gid_of(w, Kind.LISTBOX), row)
        a.click_text(WIN_GAME_LOBBY, "Challenge...")
        return await b.wait_window("Challenge")

    async def game(self):
        """alice (White) and bob (Black), with the boards up."""
        a = await self.signed_on("alice", caps=GRID)
        b = await self.signed_on("bob", caps=GRID)
        await self.in_lobby(a)
        await self.in_lobby(b)
        await self.challenge(a, b)
        b.click_text(WIN_CHALLENGED, "Accept")
        wa = await a.wait_window("Chess:")
        wb = await b.wait_window("Chess:")
        return a, b, wa, wb

    @staticmethod
    def cell(white, text):
        """The cell of square `text` ("e2") on White's board (white=True) or Black's."""
        sq = square(text)
        f, r = sq % 8, sq // 8
        return (7 - r) * 8 + f if white else r * 8 + (7 - f)

    async def move(self, c, w, white, frm, to):
        grid = gid_of(w, Kind.GRID)
        c.select(w.id, grid, self.cell(white, frm))
        c.select(w.id, grid, self.cell(white, to))
        await self.roundtrip(c)

    async def roundtrip(self, c):
        n = len(c.messages)
        c.send_hello()                          # (ignored: a second HELLO) ... any reply will do
        c.pick("Who's Online")
        await c.wait_for(lambda: len(c.messages) > n and "Who's Online" in
                         [x.title for x in c.windows.values() if x.done], "roundtrip")

    def cells(self, w):
        return w.gadgets[gid_of(w, Kind.GRID)]["cells"]

    def piece_at(self, w, white, text):
        return self.cells(w)[self.cell(white, text)] & GRID_TILE_MASK

    def status(self, w):
        labels = [g["text"] for g in w.gadgets.values() if g["kind"] == Kind.LABEL]
        return labels[9], labels[10]             # (8 ranks, the files, then the two lines)

    def chat(self, w):
        return w.gadgets[gid_of(w, Kind.TEXTVIEW)]["lines"]


class LobbyTest(ChessBase):
    async def test_old_client_is_refused(self):
        c = await self.signed_on("carol")                       # no Caps.GRID
        c.pick("Games")
        games = await c.wait_window("Games")
        lb = gid_of(games, Kind.LISTBOX)
        await c.wait_for(lambda: games.gadgets[lb]["rows"], "rows")
        row = next(i for i, r in enumerate(games.gadgets[lb]["rows"]) if r.startswith("Chess"))
        c.select(WIN_GAMES, lb, row)
        c.click_text(WIN_GAMES, "Join")
        await c.wait_for(lambda: c.alerts, "refusal")
        self.assertIn("too old", c.alerts[0][1])
        self.assertNotIn(WIN_GAME_LOBBY, c.windows)

    async def test_challenge_decline_and_accept(self):
        a = await self.signed_on("alice", caps=GRID)
        b = await self.signed_on("bob", caps=GRID)
        c = await self.signed_on("carol", caps=GRID)
        for x in (a, b, c):
            await self.in_lobby(x)
        await a.wait_for(lambda: len(self.lobby_rows(a)) == 3, "three waiting")
        self.assertTrue(self.lobby_rows(a)[0].startswith("alice") and "you" in self.lobby_rows(a)[0])
        ask = await self.challenge(a, b)
        self.assertEqual((ask.text(1), ask.text(2)), ("alice challenges you to",
                                                      "a game of Chess."))
        await a.wait_for(lambda: any(g["text"].startswith("Waiting for bob") for g in
                                     a.windows[WIN_GAME_LOBBY].gadgets.values()), "waiting")
        await b.wait_for(lambda: any("challenging you" in r for r in self.lobby_rows(b)), "row")
        b.click_text(WIN_CHALLENGED, "Decline")
        await a.wait_for(lambda: any("declined" in t for _, _, t in a.toasts), "declined")
        # carol challenges bob; bob accepts: both leave the lobby, alice sees them playing
        await self.challenge(c, b)
        b.click_text(WIN_CHALLENGED, "Accept")
        await c.wait_window("Chess:")
        await b.wait_window("Chess:")
        await a.wait_for(lambda: any("playing" in r for r in self.lobby_rows(a)), "playing row")
        self.assertEqual([r.split()[0] for r in self.lobby_rows(a)], ["alice", "carol"])
        self.assertNotIn(WIN_GAME_LOBBY, b.windows)

    async def test_leaving_the_lobby_drops_challenges(self):
        a = await self.signed_on("alice", caps=GRID)
        b = await self.signed_on("bob", caps=GRID)
        await self.in_lobby(a)
        await self.in_lobby(b)
        await self.challenge(a, b)
        a.close_box(WIN_GAME_LOBBY)
        await b.wait_for(lambda: WIN_CHALLENGED not in b.windows, "the question goes")
        await b.wait_for(lambda: any("alice left" in t for _, _, t in b.toasts), "told")


class GameTest(ChessBase):
    async def test_board_and_moves(self):
        a, b, wa, wb = await self.game()
        self.assertEqual(len(a.resources[chess.RESOURCE_SLOT][:len(chess.TILES)]), len(chess.TILES))
        self.assertEqual(bytes(a.resources[chess.RESOURCE_SLOT][:len(chess.TILES)]), chess.TILES)
        # the progress window came first, went to 100 % with the data, and closed
        opened = a.events.index(("open", "Loading Chess"))
        self.assertIn(("close", "Loading Chess"), a.events[opened:])
        self.assertLess(opened, a.events.index(("open", wa.title)))
        n = len(chess.TILES)
        bar = [v for title, v in a.progress if title == "Loading Chess"]
        self.assertEqual(bar, [100 * min(n, k) // n for k in range(1024, n + 1024, 1024)])
        self.assertEqual(bar[-1], 100)
        await a.wait_for(lambda: self.status(wa)[0] == "Your move (White)", "alice to move")
        self.assertEqual(self.status(wb)[0], "alice's move (White)")
        # each sees their own side at the bottom: White's king on e1, Black's on e8
        self.assertEqual(self.piece_at(wa, True, "e1"), chess.tile(square("e1"), "K"))
        self.assertEqual(self.cells(wa)[60] & GRID_TILE_MASK, chess.tile(square("e1"), "K"))
        self.assertEqual(self.cells(wb)[59] & GRID_TILE_MASK, chess.tile(square("e8"), "k"),
                         "bob's bottom row is rank 8, files h to a")
        grid = gid_of(wa, Kind.GRID)
        # picking e2 marks it and shows e3 / e4 as dots
        a.select(wa.id, grid, self.cell(True, "e2"))
        await a.wait_for(lambda: self.cells(wa)[self.cell(True, "e2")] & GRID_MARK1, "marked")
        self.assertEqual(self.piece_at(wa, True, "e4"), chess.T_DOT + chess.dark(square("e4")))
        # an illegal square: nothing moves; bob can't move White's pieces or out of turn
        a.select(wa.id, grid, self.cell(True, "e5"))
        b.select(wb.id, gid_of(wb, Kind.GRID), self.cell(False, "e7"))
        await self.roundtrip(a)
        self.assertEqual(self.piece_at(wa, True, "e2"), chess.tile(square("e2"), "P"))
        await self.move(a, wa, True, "e2", "e4")
        await b.wait_for(lambda: self.status(wb)[0] == "Your move (Black)", "bob to move")
        self.assertEqual(self.piece_at(wb, False, "e4"), chess.tile(square("e4"), "P"))
        self.assertTrue(self.cells(wb)[self.cell(False, "e4")] & GRID_MARK2, "last move shown")
        self.assertIn("1. e4", self.chat(wb))
        # Scholar's mate
        for c, w, white, frm, to in ((b, wb, False, "e7", "e5"), (a, wa, True, "f1", "c4"),
                                     (b, wb, False, "b8", "c6"), (a, wa, True, "d1", "h5"),
                                     (b, wb, False, "g8", "f6"), (a, wa, True, "h5", "f7")):
            await self.move(c, w, white, frm, to)
        await b.wait_for(lambda: self.status(wb) == ("alice wins.", "Checkmate."), "mate")
        self.assertEqual(self.status(wa)[0], "You win!")
        self.assertIn("4. Qxf7#", self.chat(wa))
        # a rematch swaps the colours
        a.click_text(wa.id, "Rematch")
        b.click_text(wb.id, "Rematch")
        await b.wait_for(lambda: self.status(wb)[0] == "Your move (White)", "bob is White")
        self.assertEqual(self.cells(wb)[60] & GRID_TILE_MASK, chess.tile(square("e1"), "K"))
        self.assertEqual(a.resource_bytes, len(chess.TILES), "the tiles came once")

    async def test_promotion_chat_draw_and_resign(self):
        a, b, wa, wb = await self.game()
        g = self.server.games.running[0]
        from meganet.games.chess_rules import Position
        g.pos = Position.from_fen("4k3/1P5p/8/8/8/8/8/4K3 w - - 0 1")
        g.redraw()
        grid = gid_of(wa, Kind.GRID)
        a.select(wa.id, grid, self.cell(True, "b7"))
        a.select(wa.id, grid, self.cell(True, "b8"))
        promote = await a.wait_window("Promote the Pawn")
        a.click_text(promote.id, "Knight")
        await b.wait_for(lambda: "1. b8=N" in self.chat(wb), "promoted")
        self.assertEqual(self.piece_at(wa, True, "b8"), chess.tile(square("b8"), "N"))
        # chat
        a.value(wa.id, gid_of(wa, Kind.TEXTBOX), "good game")
        a.click_text(wa.id, "Send")
        await b.wait_for(lambda: "alice: good game" in self.chat(wb), "chat")
        # a draw offered and accepted
        a.click_text(wa.id, "Offer Draw")
        await b.wait_for(lambda: b.enabled(wb.id, "Accept Draw"), "accept button")
        b.click_text(wb.id, "Accept Draw")
        await a.wait_for(lambda: self.status(wa) == ("Draw.", "Draw agreed."), "drawn")
        # rematch, then bob (now White) resigns
        a.click_text(wa.id, "Rematch")
        b.click_text(wb.id, "Rematch")
        await b.wait_for(lambda: self.status(wb)[0] == "Your move (White)", "rematch")
        b.click_text(wb.id, "Resign")
        sure = await b.wait_window("Resign")
        b.click_text(sure.id, "Resign")
        await a.wait_for(lambda: self.status(wa) == ("You win!", "bob resigned."), "resigned")

    async def test_leaving_ends_the_game(self):
        a, b, wa, wb = await self.game()
        a.close_box(wa.id)
        await b.wait_for(lambda: self.status(wb) == ("You win!", "alice left the game."), "won")
        self.assertFalse(b.enabled(wb.id, "Rematch"))
        b.click_text(wb.id, "Lobby")
        await b.wait_window("Chess Lobby")
        await b.wait_for(lambda: wb.id not in b.windows, "the board closed")
        self.assertEqual(self.server.games.running, [])
