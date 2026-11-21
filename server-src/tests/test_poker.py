"""Texas Hold'em (games/poker.py) through the fake client: joining (credits needed), buying
chips from the bank, the table's tiles and cards, playing a hand against the computer,
someone sitting down at a running table, the turn timer, and leaving (the chips go back)."""

from unittest import mock

from meganet.games import poker
from meganet.games.lobby import WIN_GAMES
from meganet.games.poker_art import TABLE, TABLE_TILES, TABLE_CELLS, TILE_W, TILE_H, overlay
from meganet.protocol import Caps, Kind
from tests.test_server import ServerTest

GRID = Caps.GRID


def has(win, text):
    return any(text in (x.get("text") or "") for x in win.gadgets.values())


class PokerBase(ServerTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for name, value in (("BOT_DELAY", 3600), ("NEXT_HAND", 0.2)):
            patch = mock.patch.object(poker, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(poker.Poker, "tick_interval", 0.02)
        patch.start()
        self.addCleanup(patch.stop)

    async def join(self, c):
        c.windows.pop(WIN_GAMES, None)
        c.pick("Games")
        games = await c.wait_window("Games")
        lb = next(gid for gid, g in games.gadgets.items() if g["kind"] == Kind.LISTBOX)
        await c.wait_for(lambda: games.gadgets[lb]["rows"], "game rows")
        row = next(i for i, r in enumerate(games.gadgets[lb]["rows"])
                   if r.startswith("Texas Hold'em"))
        c.select(WIN_GAMES, lb, row)
        c.click_text(WIN_GAMES, "Join")

    async def buy(self, c, amount):
        d = await c.wait_window("Buy Chips")
        box = next(g for g, x in sorted(d.gadgets.items()) if x["kind"] == Kind.TEXTBOX)
        c.value(d.id, box, str(amount))
        c.click_text(d.id, "Buy")
        await c.wait_for(lambda: d.id not in c.windows, "bought")

    async def vs_computer(self, n, name="alice", amount=400, caps=GRID):
        c = await self.signed_on(name, caps=caps)
        await self.join(c)
        ask = await c.wait_window("Play Texas Hold'em")
        c.click_text(ask.id, "vs Computer...")
        many = await c.wait_window("vs Computer")
        c.click_text(many.id, str(n))
        table = await c.wait_window("Texas Hold'em")
        await self.buy(c, amount)
        g = self.server.games.running[-1]
        return c, table, g

    @staticmethod
    def seat(g, name):
        return next(s for s in g.seats if s.name == name)

    @staticmethod
    def grid(w):
        return next(g for g in w.gadgets.values() if g["kind"] == Kind.GRID)

    def tile_at(self, c, w, col, row):
        t = self.grid(w)["cells"][row * 13 + col]
        n = TILE_W * TILE_H
        return bytes(c.resources[poker.RESOURCE_SLOT][t * n:(t + 1) * n])


class PokerTest(PokerBase):
    async def test_needs_credits(self):
        c = await self.signed_on("alice", caps=GRID)
        uid = self.server.db.user("alice")["id"]
        self.server.db.add_credits(uid, -450, "test")
        await self.join(c)
        await c.wait_for(lambda: c.alerts, "refused")
        self.assertIn("You need 100 credits to sit down", c.alerts[-1][1])

    async def test_a_hand_against_the_computer(self):
        c, table, g = await self.vs_computer(1)
        db = self.server.db
        uid = db.user("alice")["id"]
        self.assertEqual(db.credits(uid), 100, "400 of 500 to the table")
        self.assertEqual(db.poker_chips(), {uid: 400})
        self.assertEqual(bytes(c.resources[poker.RESOURCE_SLOT][:len(TABLE)]), TABLE)
        me, cpu = self.seat(g, "alice"), self.seat(g, "Computer 1")
        await c.wait_for(lambda: g.hand is not None, "a hand")
        h = g.hand
        self.assertEqual(sorted(h.hole), sorted([me.index, cpu.index]))
        # my cards are drawn on the felt, face up, for me; the computer's are backs
        place = g.place(me, me)
        for (col, row), dx, card in zip(poker.HOLE_CELLS[place], poker.HOLE_DX,
                                        h.hole[me.index]):
            base = TABLE_TILES[TABLE_CELLS[row * 13 + col]]
            await c.wait_for(lambda: self.tile_at(c, table, col, row) == overlay(base, card, dx),
                             "my card %s" % (card,))
        (col, row) = poker.HOLE_CELLS[g.place(me, cpu)][0]
        base = TABLE_TILES[TABLE_CELLS[row * 13 + col]]
        self.assertEqual(self.tile_at(c, table, col, row), overlay(base, "back", poker.HOLE_DX[0]))
        # play: the computer (when it's its turn) calls; I check or call to the end
        for _ in range(40):
            if g.hand is not h or h.over:
                break
            if h.turn == cpu.index:
                g.act(cpu, "call" if h.to_call(cpu.index) else "check")
                continue
            await c.wait_for(lambda: c.enabled(table.id, "Check") or any(
                c.enabled(table.id, "Call %d" % k) for k in range(1, 401)), "my turn")
            gid, label = next((gid, x["text"]) for gid, x in table.gadgets.items()
                              if x["kind"] == Kind.BUTTON and (x["text"] == "Check"
                                                               or x["text"].startswith("Call")))
            await c.wait_for(lambda: g.seats[me.index].view.call_b.enabled, "enabled")
            c.click(table.id, gid)          # (not click_text: a seat's label says "Check" too)
            await c.wait_for(lambda: h.over or h.turn != me.index,
                             "acted (%s; %s)" % (label, h.events[-3:]))
        self.assertTrue(h.over)
        self.assertEqual(len(h.board), 5)
        await c.wait_for(lambda: db.poker_chips()[uid] == me.chips, "chips saved")
        self.assertEqual(db.credit_log(uid)[0]["reason"], "poker hand", "a credit for playing")
        # Leave: the chips go back to the balance
        chips = me.chips
        c.click_text(table.id, "Leave")
        await c.wait_for(lambda: db.poker_chips() == {}, "cashed out")
        self.assertEqual(db.credits(uid), 100 + 1 + chips)
        self.assertEqual(db.credit_log(uid)[0]["reason"], "poker cash-out")

    async def test_cards_fly(self):
        """Caps.SPRITES: every hole card flies from the dealer on its own, round the table
        twice, then the flop's three cards."""
        with mock.patch.object(poker, "FLY_FRAMES", 1), mock.patch.object(poker, "FLY_GAP", 0):
            c, table, g = await self.vs_computer(2, caps=GRID | Caps.SPRITES)
            await c.wait_for(lambda: g.hand is not None, "a hand")
            await c.wait_for(lambda: len(c.flights) >= 6, "six hole cards")
            me = self.seat(g, "alice")
            h = g.hand
            while h.street == 0 and not h.over:
                t = self.seat(g, g.seats[h.turn].name)
                g.act(t, "call" if h.to_call(t.index) else "check")
            if not h.over:
                await c.wait_for(lambda: len(c.flights) >= 9, "the flop")
            # landed: my cards show
            col, row = poker.HOLE_CELLS[0][1]
            base = TABLE_TILES[TABLE_CELLS[row * 13 + col]]
            if me.index in h.hole and me.index not in h.folded and not h.over:
                await c.wait_for(lambda: self.tile_at(c, table, col, row) == overlay(
                    base, h.hole[me.index][1], poker.HOLE_DX[1]), "my second card")

    async def test_raise_and_fold(self):
        c, table, g = await self.vs_computer(1)
        me, cpu = self.seat(g, "alice"), self.seat(g, "Computer 1")
        await c.wait_for(lambda: g.hand is not None, "a hand")
        h = g.hand
        if h.turn == cpu.index:
            g.act(cpu, "call")
        await c.wait_for(lambda: c.enabled(table.id, "1/2 Pot"), "my turn")
        c.click_text(table.id, "Pot")
        box = next(gid for gid, x in table.gadgets.items() if x["kind"] == Kind.TEXTBOX)
        await c.wait_for(lambda: table.text(box) not in ("", "20"), "the pot size")
        c.value(table.id, box, "60")
        c.click_text(table.id, "Raise")
        await c.wait_for(lambda: h.turn == cpu.index, "raised")
        self.assertEqual(h.current, 60)
        g.act(cpu, "fold")
        self.assertTrue(h.over)
        self.assertEqual(h.results[0][0], me.index)
        await c.wait_for(lambda: g.hand is not h, "the next hand")

    async def test_someone_sits_down(self):
        c, table, g = await self.vs_computer(1)
        b = await self.signed_on("bob", caps=GRID)
        await self.join(b)
        ask = await b.wait_window("Play Texas Hold'em")
        b.click_text(ask.id, "Wait for Others")
        btable = await b.wait_window("Texas Hold'em")
        await self.buy(b, 300)
        self.assertEqual(sorted(s.name for s in g.seats if not s.empty),
                         ["Computer 1", "alice", "bob"])
        await b.wait_for(lambda: g.hand is not None and self.seat(g, "bob").index in g.hand.hole
                         or g.hand is not None and not g.hand.over, "playing")
        # bob sees alice's seat named on his table
        await b.wait_for(lambda: has(btable, "alice"), "alice on bob's table")

    async def test_timeouts_sit_you_out(self):
        with mock.patch.object(poker, "TURN_SECS", 0.1):
            c, table, g = await self.vs_computer(1)
            me, cpu = self.seat(g, "alice"), self.seat(g, "Computer 1")
            for _ in range(200):
                h = g.hand
                if me.sitting_out:
                    break
                if h is not None and not h.over and h.turn == cpu.index:
                    g.act(cpu, "call" if h.to_call(cpu.index) else "check")
                await c.wait_for(lambda: True, "a moment")
                await self.wait_a_bit()
            self.assertTrue(me.sitting_out)
            await c.wait_for(lambda: any("sat out" in t[2] for t in c.toasts), "told")
            await c.wait_for(lambda: c.enabled(table.id, "I'm Back"), "I'm Back")

    async def wait_a_bit(self):
        import asyncio
        await asyncio.sleep(0.03)

    async def test_disconnect_gives_the_chips_back(self):
        c, table, g = await self.vs_computer(1, amount=250)
        db = self.server.db
        uid = db.user("alice")["id"]
        await c.wait_for(lambda: g.hand is not None, "a hand")
        await c.close()
        self.clients.remove(c)
        for _ in range(200):
            if not db.poker_chips():
                break
            await self.wait_a_bit()
        self.assertEqual(db.poker_chips(), {})
        bal = db.credits(uid)
        self.assertGreaterEqual(bal, 250 + 250 - 10 - 1, "back, less a blind at most")
        self.assertTrue(g.over)
