"""One (games/one.py) through the fake client: Join's "Wait for Others" / "vs Computer...",
the table (two GRID gadgets and the card tiles), playing, the colour and challenge questions,
One! and Catch!, the computer's turns, the end of a round, and leaving."""

from unittest import mock

from meganet.games import one
from meganet.games.lobby import WIN_GAMES
from meganet.games.one_art import TILES, tile, T_BACK
from meganet.games.one_rules import Card
from meganet.protocol import Caps, GFlag, Kind, GRID_MARK1, GRID_TILE_MASK
from tests.test_server import ServerTest
from tests.test_one_rules import C

GRID = Caps.GRID


class OneBase(ServerTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        # the computer waits until a test lets it move
        for name, value in (("BOT_DELAY", 3600), ("CATCH_DELAY", 3600), ("tick_interval", 0.02)):
            patch = mock.patch.object(one.One, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    async def join(self, c):
        c.windows.pop(WIN_GAMES, None)
        c.pick("Games")
        games = await c.wait_window("Games")
        lb = next(gid for gid, g in games.gadgets.items() if g["kind"] == Kind.LISTBOX)
        await c.wait_for(lambda: games.gadgets[lb]["rows"], "game rows")
        row = next(i for i, r in enumerate(games.gadgets[lb]["rows"]) if r.startswith("One "))
        c.select(WIN_GAMES, lb, row)
        c.click_text(WIN_GAMES, "Join")
        return await c.wait_window("Play One")

    async def vs_computer(self, n, name="alice", caps=GRID):
        c = await self.signed_on(name, caps=caps)
        ask = await self.join(c)
        c.click_text(ask.id, "vs Computer...")
        many = await c.wait_window("vs Computer")
        c.click_text(many.id, str(n))
        table = await c.wait_window("One")
        await c.wait_for(lambda: self.status(table), "the status line")
        return c, table, self.server.games.running[-1]

    @staticmethod
    def grids(w):
        return [gid for gid, g in w.gadgets.items() if g["kind"] == Kind.GRID]

    def hand(self, w):
        return w.gadgets[self.grids(w)[1]]["cells"]

    def piles(self, w):
        return w.gadgets[self.grids(w)[0]]["cells"]

    @staticmethod
    def status(w):
        return next(g["text"] for g in w.gadgets.values()
                    if g["kind"] == Kind.LABEL and g["flags"] & GFlag.BOLD)

    @staticmethod
    def chat(w):
        return next(g["lines"] for g in w.gadgets.values() if g["kind"] == Kind.TEXTVIEW)

    @staticmethod
    def me(g, name="alice"):
        return next(i for i, s in enumerate(g.seats) if s.name == name)

    def rig(self, g, seat, hand, top="R1", others=None, turn=None):
        """Give `seat` the cards `hand` ("R5 W ...") on top `top`, with its turn."""
        r = g.round
        r.hands[seat] = [C(t) for t in hand.split()]
        if others is not None:
            for i in range(len(g.seats)):
                if i != seat:
                    r.hands[i] = [C(t) for t in others.split()]
        r.discard = [C(top)]
        r.colour = r.top.colour
        r.turn = seat if turn is None else turn
        r.waiting, r.unsafe, r.direction = None, None, 1
        r.opening_wild, r.wild_by, r.four, r.drawn = False, None, None, None
        r.called.clear()
        g.sync()


class JoinTest(OneBase):
    async def test_old_client_is_refused(self):
        c = await self.signed_on("carol")
        c.pick("Games")
        games = await c.wait_window("Games")
        lb = next(gid for gid, g in games.gadgets.items() if g["kind"] == Kind.LISTBOX)
        await c.wait_for(lambda: games.gadgets[lb]["rows"], "rows")
        row = next(i for i, r in enumerate(games.gadgets[lb]["rows"]) if r.startswith("One "))
        c.select(WIN_GAMES, lb, row)
        c.click_text(WIN_GAMES, "Join")
        await c.wait_for(lambda: c.alerts, "refusal")
        self.assertIn("too old", c.alerts[0][1])

    async def test_vs_computer(self):
        c, table, g = await self.vs_computer(2)
        self.assertEqual(sorted(s.name for s in g.seats), ["Computer 1", "Computer 2", "alice"])
        self.assertEqual(bytes(c.resources[one.RESOURCE_SLOT][:len(TILES)]), TILES)
        self.assertIn(("open", "Loading One"), c.events)
        await c.wait_for(lambda: sum(1 for t in self.hand(table) if t) in (7, 9), "seven cards")
        self.assertEqual(self.piles(table)[0], T_BACK)
        others = [g2["text"] for g2 in table.gadgets.values() if g2["kind"] == Kind.LABEL
                  and "cards" in g2["text"]]
        self.assertEqual(len(others), 2)
        self.assertTrue(all("Computer" in t and (" 7 cards" in t or " 9 cards" in t)
                            for t in others), others)   # (9: a Draw Two turned up first)

    async def test_cards_come_packed_to_clients_that_unpack(self):
        c, table, g = await self.vs_computer(1, caps=GRID | Caps.PICTURE)
        self.assertEqual(bytes(c.resources[one.RESOURCE_SLOT][:len(TILES)]), TILES)
        self.assertEqual(c.resource_bytes, len(TILES))
        self.assertLess(c.packed_bytes, len(TILES) // 2, "PackBits: under half the bytes sent")

    async def test_wait_for_others_and_leaving(self):
        a = await self.signed_on("alice", caps=GRID)
        b = await self.signed_on("bob", caps=GRID)
        for c in (a, b):
            ask = await self.join(c)
            c.click_text(ask.id, "Wait for Others")
        await a.wait_for(lambda: a.enabled(WIN_GAMES, "Start Now"), "Start Now")
        a.click_text(WIN_GAMES, "Start Now")
        ta = await a.wait_window("One")
        tb = await b.wait_window("One")
        g = self.server.games.running[-1]
        self.assertEqual(sorted(s.name for s in g.seats), ["alice", "bob"])
        await a.wait_for(lambda: any("bob" in t and "7 cards" in t for t in
                                     (x["text"] for x in ta.gadgets.values())), "bob's row")
        b.click_text(tb.id, "Leave")
        await a.wait_for(lambda: any("bob left" in line for line in self.chat(ta)), "told")
        await b.wait_window("Games")
        self.assertFalse(g.over, "the computer plays bob's cards")
        self.assertTrue(g.seats[self.me(g, "bob")].computer)
        a.click_text(ta.id, "Leave")
        await a.wait_for(lambda: g.over, "no people left: over")


class PlayTest(OneBase):
    async def test_playing_and_the_computer(self):
        c, table, g = await self.vs_computer(1)
        i = self.me(g)
        self.rig(g, i, "R5 B2", top="R1")
        await c.wait_for(lambda: self.hand(table)[:2] == [tile(C("R5")) | GRID_MARK1,
                                                          tile(C("B2"))], "the hand, R5 framed")
        self.assertTrue(self.status(table).startswith("Your turn"))
        grid = self.grids(table)[1]
        c.select(table.id, grid, 1)                    # Blue 2 on Red 1: no
        await c.wait_for(lambda: c.toasts, "refused")
        self.assertIn("doesn't go on Red 1", c.toasts[-1][2])
        c.select(table.id, grid, 0)
        await c.wait_for(lambda: self.piles(table)[1] == tile(C("R5")), "Red 5 on the pile")
        self.assertEqual(self.status(table), "Computer 1's turn.")
        self.assertIn("alice plays Red 5.", self.chat(table))
        g.BOT_DELAY = 0                                # the computer moves
        await c.wait_for(lambda: g.round.turn == i or g.round.over, "back to alice")
        self.assertTrue(any(line.startswith("Computer 1 ") for line in self.chat(table)))

    async def test_drawing_and_passing(self):
        c, table, g = await self.vs_computer(1)
        i = self.me(g)
        self.rig(g, i, "B2", top="R1")
        g.round.pile.append(C("R7"))
        c.click_text(table.id, "Draw")
        await c.wait_for(lambda: self.status(table).startswith("You drew Red 7"), "drawn")
        self.assertTrue(c.enabled(table.id, "Pass"))
        self.assertFalse(c.enabled(table.id, "Draw"))
        c.click_text(table.id, "Pass")
        await c.wait_for(lambda: self.status(table) == "Computer 1's turn.", "passed")
        self.assertEqual(len(g.round.hands[i]), 2)

    async def test_wild_colour_and_one(self):
        c, table, g = await self.vs_computer(1)
        i = self.me(g)
        self.rig(g, i, "W G2", top="R1")
        await c.wait_for(lambda: c.enabled(table.id, "One!"), "One! (two cards, my turn)")
        c.click_text(table.id, "One!")
        await c.wait_for(lambda: "alice calls One!" in self.chat(table), "called")
        c.select(table.id, self.grids(table)[1], 1)    # (sorted: Green 2, then the Wild)
        ask = await c.wait_window("Name a Colour")
        c.click_text(ask.id, "Green")
        await c.wait_for(lambda: g.round.colour == "G" and g.round.turn != i, "Green")
        self.assertEqual(self.piles(table)[1], tile(Card(None, "W"), "G"))
        self.assertIsNone(g.round.unsafe, "called in time: safe")
        self.assertIn("Colour: Green", [x["text"] for x in table.gadgets.values()])

    async def test_caught_without_one(self):
        c, table, g = await self.vs_computer(2)
        i = self.me(g)
        self.rig(g, i, "R2 R3", top="R1")
        c.select(table.id, self.grids(table)[1], 0)
        await c.wait_for(lambda: g.round.unsafe == i, "down to one, not called")
        g.CATCH_DELAY, g.CATCH_CHANCE = 0, 1
        await c.wait_for(lambda: len(g.round.hands[i]) == 3, "caught: draws 2")
        self.assertTrue(any("catches alice" in line for line in self.chat(table)))

    async def test_challenge(self):
        c, table, g = await self.vs_computer(1)
        i = self.me(g)
        k = 1 - i
        self.rig(g, k, "F B1", top="R5", others="R2 R3", turn=k)   # honest: no Red
        g.BOT_DELAY = 0
        ask = await c.wait_window("Wild Draw Four")
        g.BOT_DELAY = 3600
        c.click_text(ask.id, "Challenge")
        await c.wait_for(lambda: any("had no Red" in line for line in self.chat(table)),
                         "the challenge")
        self.assertEqual(len(g.round.hands[i]), 8, "two cards + 6")

    async def test_whole_rounds_against_three(self):
        """alice (played for here by the computer's own choice) and three computers play
        two rounds through the table code: no tick fails, nothing gets stuck."""
        import asyncio
        from meganet.games import lobby
        from meganet.games.one_rules import computer_choice, best_colour
        with mock.patch.object(lobby.log, "exception") as failed:
            c, table, g = await self.vs_computer(3)
            i = self.me(g)
            s = g.seats[i]
            g.BOT_DELAY, g.CATCH_DELAY = 0, 0
            rounds = 0
            for _ in range(4000):
                r = g.round
                if r.over:
                    rounds += 1
                    if rounds == 2:
                        break
                    g.again(s)
                elif r.waiting == "colour" and r.wild_by == i:
                    g.colour(s, best_colour(r.hands[i], g.rng))
                elif r.waiting == "challenge" and r.turn == i:
                    g.answer_four(s, False)
                elif r.turn == i and r.waiting in (None, "drawn"):
                    move = computer_choice(r, i, g.rng)
                    if move[0] == "play":
                        k = s.order.index(move[1])
                        s.page = k // one.PAGE
                        g.on_select(s.player, s.win, s.hand, k % one.PAGE, False)
                    elif move[0] == "pass":
                        g.pass_(s)
                    else:
                        g.draw(s)
                await asyncio.sleep(0.005)
            self.assertEqual(rounds, 2, "two rounds played out")
            failed.assert_not_called()

    async def test_cards_fly(self):
        """Caps.SPRITES: a card played flies from its cell to the pile, which shows it only
        when it lands; a card drawn flies from the deck to its cell, empty till then; the
        computer's cards fly from and to its row."""
        c, table, g = await self.vs_computer(1, caps=GRID | Caps.SPRITES)
        i = self.me(g)
        self.rig(g, i, "B2 R5", top="R1")              # (sorted: R5 in cell 0, B2 in 1)
        await c.wait_for(lambda: self.hand(table)[0] & GRID_TILE_MASK == tile(C("R5")),
                         "dealt")
        with mock.patch.object(one, "FLY_FRAMES", 50):  # (a second: time to look)
            c.select(table.id, self.grids(table)[1], 0)
            await c.wait_for(lambda: c.flights, "the flight")
            f = c.flights[-1]
            card = one.TILE_W * one.TILE_H                 # (a tile's bytes)
            self.assertEqual((f["offset"], f["slot"], f["w"], f["h"], f["step"], f["stride"],
                              f["frames"], f["hide"]),
                             (tile(C("R5")) * card, one.RESOURCE_SLOT, 16, one.TILE_H, 2,
                              one.TILE_W, 50, 1))
            self.assertEqual((f["x"], f["y"]), (one.HAND_X, one.HAND_Y))
            self.assertEqual(f["end"], one.PILE_XY)
            self.assertEqual(f["colours"][0], (254, (20, 20, 20)))
            self.assertEqual(self.piles(table)[1], tile(C("R1")), "the pile waits")
            await c.wait_for(lambda: self.piles(table)[1] == tile(C("R5")), "landed")
            # drawing: the card's cell stays empty until it arrives
            r = g.round
            r.turn, r.pile = i, r.pile + [C("Y9")]
            g.sync()
            c.click_text(table.id, "Draw")
            await c.wait_for(lambda: len(c.flights) == 2, "the draw's flight")
            f = c.flights[-1]
            self.assertEqual((f["offset"], (f["x"], f["y"])), (tile(C("Y9")) * card, one.DECK_XY))
            cell = 0                                    # (sorted R Y G B: Y9, then B2)
            self.assertEqual(f["end"], one.One._cell_xy(g, cell))
            self.assertEqual(self.hand(table)[cell], 0, "not there yet")
            await c.wait_for(lambda: self.hand(table)[cell] & GRID_TILE_MASK == tile(C("Y9")),
                             "arrived")
        # the computer's card flies from its row
        g.BOT_DELAY = 0
        row = (one.MARGIN + 104, 0)                     # (the only other row)
        await c.wait_for(lambda: any((f["x"], f["y"]) == row or f["end"] == row
                                     for f in c.flights[2:]), "the computer's card")

    async def test_no_flights_for_older_clients(self):
        c, table, g = await self.vs_computer(1)
        i = self.me(g)
        self.rig(g, i, "R5 B2", top="R1")
        c.select(table.id, self.grids(table)[1], 0)
        await c.wait_for(lambda: self.piles(table)[1] == tile(C("R5")), "at once")
        self.assertEqual(c.flights, [])

    async def test_end_of_round(self):
        c, table, g = await self.vs_computer(1)
        i = self.me(g)
        self.rig(g, i, "R2", top="R1", others="B5 W")
        c.select(table.id, self.grids(table)[1], 0)
        await c.wait_for(lambda: self.status(table) == "You win the round: +55 points.",
                         "won")
        self.assertEqual(g.seats[i].score, 55)
        self.assertTrue(c.enabled(table.id, "Next Round"))
        c.click_text(table.id, "Next Round")
        await c.wait_for(lambda: not g.round.over and sum(1 for t in self.hand(table) if t) in (7, 9),
                         "dealt again")
        self.assertEqual(g.seats[i].score, 55, "the score stays")
