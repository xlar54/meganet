"""Tank Duel (games/tanks.py): the field, the shell's flight, craters and damage, the
computer's aim, and a game against the computer through the fake client (the - and +
buttons, Fire, the turns, the end, a rematch)."""

import random
import unittest
from unittest import mock

from meganet.games import tanks as T
from meganet.games.lobby import WIN_GAMES
from meganet.protocol import Caps, Kind
from tests.test_server import ServerTest

GRID = Caps.GRID


def flat(height=100):
    return [height] * T.W


def tank(i, x, ground, name=None):
    t = T.Tank(i, name or "t%d" % i, None, x)
    t.y = ground[x]
    return t


class RulesTest(unittest.TestCase):
    def test_fields_fit_the_grid(self):
        for seed in range(50):
            rng = random.Random(seed)
            g = T.make_ground(rng)
            xs = T.place_tanks(4, g, rng)
            ts = [tank(i, x, g) for i, x in enumerate(xs)]
            f = T.Field(g, ts)
            self.assertLessEqual(T.distinct(f.tiles), T.TILES_MAX)
            self.assertTrue(all(0 < h < T.H for h in g))
            for t in ts:                                   # level ground under each tank
                self.assertEqual(len({g[k] for k in range(t.x - 5, t.x + 6)}), 1)

    def test_a_shot_goes_up_and_comes_down(self):
        g = flat()
        a = tank(0, 50, g)
        path, end = T.flight(*a.muzzle(45), a.world_angle(45), 40, 0, g)
        self.assertEqual(end[0], "ground")
        self.assertLess(min(y for _, y in path), a.y - 10, "it rose")
        self.assertGreater(end[1], a.x + 20, "it went the way the tank faces")
        # the wind pushes it
        _, with_wind = T.flight(*a.muzzle(45), a.world_angle(45), 40, 8, g)
        self.assertGreater(with_wind[1], end[1])
        # facing left, the same angle goes left
        b = tank(1, 250, g)
        self.assertEqual(b.facing, -1)
        _, left = T.flight(*b.muzzle(45), b.world_angle(45), 40, 0, g)
        self.assertLess(left[1], b.x - 20)

    def test_a_tank_in_the_way_is_hit(self):
        g = flat()
        a, b = tank(0, 50, g), tank(1, 120, g)
        for power in range(10, 101):
            path, end = T.flight(*a.muzzle(45), a.world_angle(45), power, 0, g, [a, b], a)
            if end[0] == "tank":
                self.assertIs(end[1], b)
                return
        self.fail("no power hit the tank")

    def test_crater_and_no_cliffs(self):
        g = flat()
        f = T.Field(g, [])
        f.crater(150, 100)
        self.assertEqual(g[150], 100 + T.CRATER)
        self.assertEqual(g[150 - T.CRATER - 1], 100, "outside the blast")
        # a blast under a high column (the surface above the circle) leaves it
        g2 = flat()
        g2[150] = 60
        T.Field(g2, []).crater(150, 100)
        self.assertEqual(g2[150], 60)

    def test_computer_aim_gets_closer(self):
        g = flat()
        a, b = tank(0, 40, g), tank(1, 260, g)
        rng = random.Random(4)
        misses = []
        for _ in range(5):
            angle, power = T.computer_aim(a, b, 0, g, rng)
            _, end = T.flight(*a.muzzle(angle), a.world_angle(angle), power, 0, g)
            misses.append(abs(end[1] - b.x) if end[0] != "off" else T.W)
        self.assertLess(min(misses[2:]), 20, misses)
        self.assertEqual(a.shots[1], 5)


class GameTest(ServerTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for name, value in (("STEP", 0.001), ("COMPUTER_DELAY", 0.05), ("NEXT_TURN", 0)):
            p = mock.patch.object(T, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(T.TankDuel, "tick_interval", 0.02)
        p.start()
        self.addCleanup(p.stop)

    async def vs_computer(self, n=1):
        c = await self.signed_on("alice", caps=GRID)
        c.windows.pop(WIN_GAMES, None)
        c.pick("Games")
        games = await c.wait_window("Games")
        lb = next(gid for gid, g in games.gadgets.items() if g["kind"] == Kind.LISTBOX)
        await c.wait_for(lambda: games.gadgets[lb]["rows"], "game rows")
        row = next(i for i, r in enumerate(games.gadgets[lb]["rows"])
                   if r.startswith("Tank Duel"))
        c.select(WIN_GAMES, lb, row)
        c.click_text(WIN_GAMES, "Join")
        ask = await c.wait_window("Play Tank Duel")
        c.click_text(ask.id, "vs Computer...")
        many = await c.wait_window("vs Computer")
        c.click_text(many.id, str(n))
        win = await c.wait_window("Tank Duel")
        g = next(g for g in self.server.games.running if isinstance(g, T.TankDuel))
        return c, win, g

    def grid(self, w):
        return next(x for x in w.gadgets.values() if x["kind"] == Kind.GRID)

    async def test_play_the_computer(self):
        c, win, g = await self.vs_computer()
        self.assertEqual([t.name for t in sorted(g.tanks, key=lambda t: t.player is None)],
                         ["alice", "Computer 1"])
        cells = self.grid(win)["cells"]
        self.assertEqual(len(cells), T.COLS * T.ROWS)
        n = T.TILE_W * T.TILE_H
        slot = c.resources[T.RESOURCE_SLOT]
        for cell in (0, len(cells) - 1):                 # the sky, the ground: as drawn
            self.assertEqual(bytes(slot[cells[cell] * n:(cells[cell] + 1) * n]),
                             g.field.tiles[cell])
        me = g.tank_of(g.players[0])
        g.turn, g.phase = me.index, "aim"                # (whoever the draw gave the first go)
        g.redraw()
        await c.wait_for(lambda: c.enabled(win.id, "Fire"), "my turn")
        before = me.angle, me.power
        c.click_text(win.id, "+5")                       # the angle's +5 (the first one)
        await c.wait_for(lambda: me.angle == before[0] + 5, "the angle")
        power_plus = [gid for gid, x in sorted(win.gadgets.items())
                      if x["kind"] == Kind.BUTTON and x["text"] == "+1"][1]
        c.click(win.id, power_plus)
        await c.wait_for(lambda: me.power == before[1] + 1, "the power")
        self.assertTrue(any(x["text"] == str(me.angle) for x in win.gadgets.values()),
                        "the angle shown")
        c.click_text(win.id, "Fire")
        await c.wait_for(lambda: g.phase != "flight" and g.tanks[g.turn] is not me
                         or g.phase == "over", "my shot landed")
        if g.phase != "over":                            # the computer answers
            await c.wait_for(lambda: g.tanks[g.turn] is me or g.phase == "over",
                             "the computer fired")
        self.assertTrue(any("Computer 1:" in t[2] for t in c.toasts) or g.phase == "over")

    async def test_a_direct_hit_wins(self):
        c, win, g = await self.vs_computer()
        me = g.tank_of(g.players[0])
        cpu = next(t for t in g.tanks if t.player is None)
        cpu.health = 10
        g.turn, g.phase = me.index, "aim"
        g.land(("tank", cpu, cpu.x, cpu.y - 2))
        self.assertEqual(g.phase, "over")
        self.assertEqual(cpu.health, 0)
        await c.wait_for(lambda: any(x["text"] == "alice wins!"
                                     for x in win.gadgets.values()), "the result")
        self.assertEqual(self.server.db.credit_log(self.server.db.user("alice")["id"])[0]
                         ["reason"], "game won")
        await c.wait_for(lambda: c.enabled(win.id, "Rematch"), "rematch")
        old = g.field
        c.click_text(win.id, "Rematch")                  # (the only person: a new field at once)
        await c.wait_for(lambda: g.phase == "aim" and g.field is not old, "a new round")
        self.assertTrue(all(t.alive for t in g.tanks))

    async def test_blast_damage_and_falling(self):
        c, win, g = await self.vs_computer()
        me = g.tank_of(g.players[0])
        cpu = next(t for t in g.tanks if t.player is None)
        g.turn = cpu.index
        x, y = me.x + 4, me.y                           # close, not on it
        g.land(("ground", x, y))
        self.assertLess(me.health, T.HEALTH)
        self.assertGreater(me.health, T.HEALTH - T.DAMAGE)
        self.assertEqual(me.y, g.ground[me.x], "it sits on the ground left")
        self.assertGreater(g.ground[x], y, "a crater")

    async def test_a_slow_turn_passes(self):
        with mock.patch.object(T, "TURN_SECS", 0.1):
            c, win, g = await self.vs_computer()
            me = g.tank_of(g.players[0])
            g.turn, g.phase = me.index, "aim"
            g.turn_since = 0                            # (long ago)
            await c.wait_for(lambda: any("Too slow" in t[2] for t in c.toasts), "told")


if __name__ == "__main__":
    unittest.main()
