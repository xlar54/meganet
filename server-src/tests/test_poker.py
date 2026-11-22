"""Texas Hold'em (games/poker.py) through the fake client: joining (credits needed), buying
chips from the bank, the table's tiles and cards, playing a hand against the computer,
someone sitting down at a running table, the turn timer, and leaving (the chips go back)."""

from unittest import mock

from meganet.games import poker
from meganet.games.lobby import WIN_GAMES
from meganet.games.poker_art import (TABLE, TABLE_TILES, TABLE_CELLS, TILE_W, TILE_H, COLS,
                                     compose)
from meganet.games.poker_art import STAR_COLOURS
from meganet.protocol import Caps, Kind, Sound
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

    def tile_at(self, c, w, cell):
        t = self.grid(w)["cells"][cell]
        n = TILE_W * TILE_H
        return bytes(c.resources[poker.RESOURCE_SLOT][t * n:(t + 1) * n])

    async def shows(self, c, w, g, me, place, k, what):
        """Card k of the seat at `place` is `what` (a card, or "back") on `me`'s table: on
        the tile where it starts, drawn with whatever else is there."""
        row, x = poker.SEAT_ROW[place], poker.hole_x(place, k)
        cell = row * COLS + x // TILE_W

        def right():
            items = poker.cells_for(g.items(me)).get(cell, [])
            return ((what, x % TILE_W) in items and self.tile_at(c, w, cell) == compose(
                TABLE_TILES[TABLE_CELLS[cell]], items))
        await c.wait_for(right, "card %d at place %d is %s" % (k, place, (what,)))


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
        for k, card in enumerate(h.hole[me.index]):
            await self.shows(c, table, g, me, g.place(me, me), k, card)
        await self.shows(c, table, g, me, g.place(me, cpu), 0, "back")
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
            seen = len(h.events)
            c.click(table.id, gid)          # (not click_text: a seat's label says "Check" too)
            # (not "the turn moved on": heads-up, the big blind checks, then acts first on
            # the flop)
            await c.wait_for(lambda: h.over or len(h.events) > seen,
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
            if me.index in h.hole and me.index not in h.folded and not h.over:
                await self.shows(c, table, g, me, 0, 1, h.hole[me.index][1])

    async def test_winner_kaching_and_stars(self):
        """I win (the computer folds to my all-in): ka-ching for me, and two gold stars flash
        either side of my seat's "Wins N" line, then go."""
        with mock.patch.object(poker, "FLY_FRAMES", 1), mock.patch.object(poker, "FLY_GAP", 0), \
                mock.patch.object(poker, "FLASH_SECS", 0.4), \
                mock.patch.object(poker, "FLASH_EVERY", 0.1), \
                mock.patch.object(poker, "NEXT_HAND", 60):
            c, table, g = await self.vs_computer(1, caps=GRID | Caps.SPRITES)
            me, cpu = self.seat(g, "alice"), self.seat(g, "Computer 1")
            await c.wait_for(lambda: g.hand is not None, "a hand")
            h = g.hand
            self.assertEqual(c.sounds, [])
            while not h.over:
                if h.turn == cpu.index:
                    g.act(cpu, "fold")
                else:
                    g.act(me, "allin")
            self.assertEqual(h.results[0][0], me.index)
            await c.wait_for(lambda: Sound.KACHING in c.sounds, "ka-ching")
            await c.wait_for(lambda: len(c.sprites) == 2, "two stars")
            lx, ly, lw = poker.label_at(0)
            star = TABLE_TILES[TABLE_CELLS[2 * COLS + COLS // 2]]
            star = compose(star, [("star", 0)])
            for sp in c.sprites.values():
                self.assertEqual(sp["y"], ly + 9)
                self.assertEqual([k for k, _ in sp["colours"]], STAR_COLOURS)
                data = c.resources[poker.RESOURCE_SLOT]
                rows = [bytes(data[sp["offset"] + y * sp["stride"]:][:sp["w"] * 2:2])
                        for y in range(sp["h"])]
                want = [star[(poker.STAR_Y + y) * TILE_W:][:poker.STAR_PX:2]
                        for y in range(poker.STAR_FAT)]
                self.assertEqual(rows, want, "the star's picture")
            xs = sorted(sp["x"] for sp in c.sprites.values())
            self.assertTrue(xs[0] < lx + lw // 2 < xs[1], "one each side: %s" % xs)
            await c.wait_for(lambda: not c.sprites, "the stars go")

    async def test_raise_and_fold(self):
        c, table, g = await self.vs_computer(1)
        me, cpu = self.seat(g, "alice"), self.seat(g, "Computer 1")
        await c.wait_for(lambda: g.hand is not None, "a hand")
        h = g.hand
        if h.turn == cpu.index:
            g.act(cpu, "call")
        await c.wait_for(lambda: c.enabled(table.id, "1/2"), "my turn")
        c.click_text(table.id, "Pot")
        box = me.view.amount.gid
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

    async def test_chat(self):
        """A line typed at the table: in everyone's chat, and at the speaker's seat for a few
        seconds. Some of the dealer's lines are in the chat too (who sat down, who won)."""
        c, table, g = await self.vs_computer(1)
        b = await self.signed_on("bob", caps=GRID)
        await self.join(b)
        ask = await b.wait_window("Play Texas Hold'em")
        b.click_text(ask.id, "Wait for Others")
        btable = await b.wait_window("Texas Hold'em")
        await self.buy(b, 300)
        box = self.seat(g, "alice").view.entry.gid
        c.value(table.id, box, "nice hand")
        c.click_text(table.id, "Send")
        for w, who in ((table, c), (btable, b)):
            await who.wait_for(lambda: "alice: nice hand" in self.chat(w), "the line")
        await b.wait_for(lambda: has(btable, '"nice hand"'), "at alice's seat")
        self.assertEqual(table.text(box), "", "the box empties")
        self.seat(g, "alice").said_until = 0     # (its time is up)
        await b.wait_for(lambda: not has(btable, '"nice hand"'), "gone after a while")
        self.assertIn("* bob sits down.", self.chat(table), "the dealer's lines")
        self.assertFalse(any("posts the" in l or "checks." in l for l in self.chat(table)),
                         "not every action (the seat labels show those)")

    @staticmethod
    def chat(w):
        return next(g["lines"] for g in w.gadgets.values() if g["kind"] == Kind.TEXTVIEW)

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
