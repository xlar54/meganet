"""Tank Duel: 2-4 tanks on a random hilly field take turns to fire shells at each other: set the
angle and the power with the - and + buttons, mind the wind, and Fire. People, the computer, or
both (Join: Wait for Others, or vs Computer... with 1-3 computer tanks).

The field is a Grid (Caps.GRID clients) of COLS x ROWS tiles, 32 x 16 screen pixels, drawn
in "fat" pixels (two screen pixels across, one down: about square on the MEGA65's screen),
W x H of them. Its tiles are made here for each picture of the field and sent to each
viewer as they're needed (TileCache: identical tiles are sent once; the sky and the earth
repeat, so a field needs a few dozen).

A turn: the tank's angle (0-180 from the way it faces: 90 is straight up) and power (5-100);
Fire. The shell flies (drawn into the tiles a few times a second, with a short tail), and
where it lands it bursts: a crater, and damage to every tank near enough (a direct hit most).
Tanks fall to the ground left under them. A new wind each turn. The last tank standing wins.
A person has TURN_SECS a turn (then the turn passes).

The computer aims by trying angles and powers against the wind (computer_aim), and misses by
a little: less each time it fires at the same tank.
"""

import asyncio
import math
import os
import random
import time

from ..protocol import Caps, GFlag
from ..ui import Button, Grid, Label, centre
from .base import Game

RESOURCE_SLOT = 12               # (1 chess, 2-7 the Art Gallery, 8 One, 9 poker, 10 SID tunes,
                                 # 11 blackjack)
TILE_W, TILE_H = 32, 16          # screen pixels
FAT_W = TILE_W // 2              # a tile's fat pixels across
COLS, ROWS = 19, 8
W, H = COLS * FAT_W, ROWS * TILE_H      # the field in fat pixels: 304 x 128
N_TILES = 64
TILES_MAX = 52                   # a new field's distinct tiles at most (room left for the
                                 # shell, the blasts and craters)

SKY, DIRT, GRASS, OUTLINE, WRECK = 7, 241, 249, 254, 245
SHELL = 254
TANK_COLOURS = [(251, "red"), (252, "blue"), (253, "gold"), (242, "white")]
BLAST = [14, 253, 251]

GRAVITY = 60.0                   # fat pixels a second, a second
SPEED = 1.45                     # fat pixels a second for each power point
WIND_MAX = 10
WIND_PUSH = 1.6                  # fat pixels a second, a second, for each wind point
DT = 0.02                        # the flight's time step (seconds)
CRATER = 9                       # the crater's radius (fat pixels)
REACH = 15                       # how far the blast hurts
DAMAGE = 70                      # at its middle (a direct hit: at least DIRECT)
DIRECT = 50
HEALTH = 100
TANK_W = 11                      # (odd: the turret is in the middle)
BARREL = 7
ANGLE_MIN, ANGLE_MAX = 0, 180
POWER_MIN, POWER_MAX = 5, 100

STEP = float(os.environ.get("MEGANET_TANKS_STEP", 0.06))       # seconds a picture of a flight
TURN_SECS = 45
COMPUTER_DELAY = float(os.environ.get("MEGANET_TANKS_COMPUTER_DELAY", 1.5))
NEXT_TURN = float(os.environ.get("MEGANET_TANKS_NEXT_TURN", 1.0))
COMPUTER_NAMES = ["Computer %d" % n for n in range(1, 4)]
ERRORS = [7.0, 4.5, 3.0, 2.0, 1.2]    # the computer's spread in power, shot by shot at a tank

WIN_W, WIN_H = 616, 171
GX, GY = 4, 12                   # the field in the window
CY = WIN_H - 16                  # the controls' row


# ---- the field ----

def make_ground(rng):
    """The ground's surface: the first ground row of each fat column (a few gentle waves)."""
    waves = [(rng.uniform(0.5, 1.2), rng.uniform(0, 2 * math.pi), rng.uniform(15, 25)),
             (rng.uniform(1.5, 2.5), rng.uniform(0, 2 * math.pi), rng.uniform(4, 8)),
             (rng.uniform(4.0, 6.0), rng.uniform(0, 2 * math.pi), rng.uniform(1, 2))]
    base = rng.uniform(H * 0.55, H * 0.68)
    out = []
    for x in range(W):
        y = base + sum(a * math.sin(f * 2 * math.pi * x / W + p) for f, p, a in waves)
        out.append(int(min(H - 8, max(H * 0.3, y))))
    return out


class Tank:
    def __init__(self, index, name, player, x):
        self.index = index
        self.name = name
        self.player = player           # a Player, or None (the computer)
        self.colour, self.colour_name = TANK_COLOURS[index]
        self.x = x                     # its middle (fat pixels)
        self.y = 0                     # the ground under it (its bottom row is y - 1)
        self.facing = 1 if x < W // 2 else -1
        self.angle = 45
        self.power = 50
        self.health = HEALTH
        self.shots = {}                # (the computer) target index -> shots at it

    @property
    def alive(self):
        return self.health > 0

    @property
    def computer(self):
        return self.player is None

    def world_angle(self, angle=None):
        a = self.angle if angle is None else angle
        return a if self.facing > 0 else 180 - a

    def muzzle(self, angle=None):
        r = math.radians(self.world_angle(angle))
        return self.x + BARREL * math.cos(r), self.y - 6 - BARREL * math.sin(r)


def place_tanks(n, ground, rng):
    """n tank positions, spread across the field; the ground under each made flat."""
    xs = []
    for i in range(n):
        span = W / n
        xs.append(int(span * (i + 0.5) + rng.uniform(-span / 5, span / 5)))
    for x in xs:
        lo, hi = max(0, x - TANK_W // 2 - 1), min(W, x + TANK_W // 2 + 2)
        level = round(sum(ground[lo:hi]) / (hi - lo))
        for k in range(lo, hi):
            ground[k] = level
    return xs


def flight(x, y, world_angle, power, wind, ground, tanks=(), shooter=None):
    """The shell's path: [(x, y), ...] a DT apart, and how it ends: ("ground", x, y),
    ("tank", tank, x, y) or ("off", None)."""
    r = math.radians(world_angle)
    vx, vy = SPEED * power * math.cos(r), -SPEED * power * math.sin(r)
    ax = WIND_PUSH * wind
    path = []
    t = 0.0
    while t < 20:
        t += DT
        vx += ax * DT
        vy += GRAVITY * DT
        x += vx * DT
        y += vy * DT
        if x < 0 or x >= W or y >= H:
            return path, ("off", None)
        path.append((x, y))
        for tank in tanks:
            if not tank.alive or (tank is shooter and t < 0.15):
                continue
            if abs(x - tank.x) <= TANK_W / 2 and tank.y - 7 <= y <= tank.y:
                return path, ("tank", tank, x, y)
        if y >= ground[int(x)]:
            return path, ("ground", x, y)
    return path, ("off", None)


def computer_aim(tank, target, wind, ground, rng):
    """(angle, power) for the computer: the best try against the wind, then a miss that
    shrinks with each shot at the same target."""
    best = None
    for angle in range(25, 76, 5):
        for power in range(20, POWER_MAX + 1, 2):
            path, end = flight(*tank.muzzle(angle), tank.world_angle(angle), power, wind,
                               ground)
            if end[0] == "off" or not path:
                continue
            miss = abs(end[1] - target.x)
            if best is None or miss < best[0]:
                best = (miss, angle, power)
    if best is None:
        return 45, 60
    n = tank.shots.get(target.index, 0)
    tank.shots[target.index] = n + 1
    spread = ERRORS[min(n, len(ERRORS) - 1)]
    power = round(best[2] + rng.gauss(0, spread))
    angle = round(best[1] + rng.gauss(0, spread / 2))
    return (max(ANGLE_MIN, min(ANGLE_MAX, angle)), max(POWER_MIN, min(POWER_MAX, power)))


class Field:
    """The picture of the field in fat pixels (rows of bytes), and its tiles."""

    def __init__(self, ground, tanks):
        self.ground = ground
        self.tanks = tanks
        self.px = [bytearray(W) for _ in range(H)]
        self.tiles = [b""] * (COLS * ROWS)
        self.paint(0, 0, W, H)

    def paint(self, x0, y0, x1, y1):
        """Draw the field again in a rectangle (fat pixels), and make its tiles again."""
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(W, int(math.ceil(x1))), min(H, int(math.ceil(y1)))
        g = self.ground
        for y in range(y0, y1):
            row = self.px[y]
            for x in range(x0, x1):
                row[x] = SKY if y < g[x] else (GRASS if y < g[x] + 2 else DIRT)
        for t in self.tanks:
            if t.x + TANK_W >= x0 and t.x - TANK_W < x1 and t.y + 1 >= y0 and t.y - 15 < y1:
                self.draw_tank(t)
        for row in range(y0 // TILE_H, (y1 - 1) // TILE_H + 1):
            for col in range(x0 // FAT_W, (x1 - 1) // FAT_W + 1):
                self.tiles[row * COLS + col] = self.tile(col, row)

    def put(self, x, y, c):
        x, y = int(x), int(y)
        if 0 <= x < W and 0 <= y < H:
            self.px[y][x] = c

    def draw_tank(self, t):
        body = t.colour if t.alive else WRECK
        half = TANK_W // 2
        # the tracks, the hull (two rows, narrowing), the turret (two rows), the barrel
        for dy, inset, c in ((0, 0, OUTLINE), (1, 0, OUTLINE), (2, 0, body), (3, 1, body),
                             (4, 3, body), (5, 3, body)):
            for dx in range(-half + inset, half - inset + 1):
                self.put(t.x + dx, t.y - 1 - dy, c)
        if t.alive:
            r = math.radians(t.world_angle())
            for k in range(1, BARREL + 1):
                self.put(t.x + k * math.cos(r), t.y - 6 - k * math.sin(r), OUTLINE)

    def tile(self, col, row):
        out = bytearray(TILE_W * TILE_H)
        for y in range(TILE_H):
            src = self.px[row * TILE_H + y]
            base = col * FAT_W
            for x in range(FAT_W):
                c = src[base + x]
                out[y * TILE_W + 2 * x] = out[y * TILE_W + 2 * x + 1] = c
        return bytes(out)

    def with_dots(self, dots):
        """{cell: tile bytes} of the cells under `dots` [(x, y, colour), ...], drawn on."""
        out = {}
        for x, y, c in dots:
            x, y = int(x), int(y)
            if not (0 <= x < W and 0 <= y < H):
                continue
            cell = (y // TILE_H) * COLS + x // FAT_W
            t = out.get(cell)
            if t is None:
                t = out[cell] = bytearray(self.tiles[cell])
            i = (y % TILE_H) * TILE_W + 2 * (x % FAT_W)
            t[i] = t[i + 1] = c
        return {k: bytes(v) for k, v in out.items()}

    def crater(self, cx, cy):
        """Blow a hole: in each column the blast reaches from the surface down, the ground
        goes to the circle's bottom (where the surface is above the circle, the blast was
        underground: nothing changes there, so no cliffs)."""
        for x in range(max(0, int(cx - CRATER)), min(W, int(cx + CRATER) + 1)):
            d = CRATER * CRATER - (x - cx) ** 2
            if d <= 0:
                continue
            s = math.sqrt(d)
            if self.ground[x] >= cy - s:
                self.ground[x] = min(H - 1, max(self.ground[x], int(cy + s)))


def distinct(tiles):
    return len(set(tiles))


class TileCache:
    """One viewer's tiles: tile bytes -> a tile number, sent the first time; the least used
    goes when there's no room (never one on show)."""

    def __init__(self, session):
        self.session = session
        self.map = {}
        self.order = []
        self.free = list(range(N_TILES))

    def get(self, data, keep):
        t = self.map.get(data)
        if t is not None:
            self.order.remove(data)
            self.order.append(data)
            return t
        if self.free:
            t = self.free.pop(0)
        else:
            old = next((d for d in self.order if self.map[d] not in keep), self.order[0])
            self.order.remove(old)
            t = self.map.pop(old)
        self.session.send_resource_at(RESOURCE_SLOT, t * TILE_W * TILE_H, data)
        self.map[data] = t
        self.order.append(data)
        return t


class View:
    def __init__(self, player):
        self.player = player
        self.cache = TileCache(player.session)
        self.win = None


class TankDuel(Game):
    name = "Tank Duel"
    description = ("Tanks on a hilly field: set the angle and power, mind the wind, and Fire. "
                   "2-4 players, or play the computer. The last tank standing wins.")
    min_players = 2
    max_players = 4
    computer = True
    needs_caps = Caps.GRID
    tick_interval = 0.25

    # ---- setting up ----

    def start(self, players):
        self.rng = random.Random()
        self.views = {}
        for p in players:
            self.views[p] = View(p)
        self.rematch_from = set()
        self.new_round()
        for p in players:
            self._window(self.views[p])
        self.redraw()

    def new_round(self):
        seats = [p for p in self.views if p in self.players]
        names = [(p.name, p) for p in seats] + [
            (COMPUTER_NAMES[k], None) for k in range(max(0, min(self.computers,
                                                                 self.max_players - len(seats))))]
        for _ in range(20):                           # a field that fits in the grid's tiles
            ground = make_ground(self.rng)
            xs = place_tanks(len(names), ground, self.rng)
            order = list(range(len(names)))
            self.rng.shuffle(order)
            tanks = [Tank(i, names[k][0], names[k][1], xs[i]) for i, k in enumerate(order)]
            for t in tanks:
                t.y = ground[t.x]
            field = Field(ground, tanks)
            if distinct(field.tiles) <= TILES_MAX:
                break
        self.ground, self.tanks, self.field = ground, tanks, field
        self.turn = self.rng.randrange(len(tanks))
        self.wind = self.rng.randint(-WIND_MAX // 2, WIND_MAX // 2)
        self.phase = "aim"                            # aim, flight, over
        self.turn_since = time.monotonic()
        self.result = None
        self.rematch_from = set()
        if self.players:
            self.players[0].session.log("tank duel: %s" % ", ".join(t.name for t in tanks))

    def tank_of(self, player):
        return next((t for t in self.tanks if t.player is player), None)

    # ---- the window ----

    def _window(self, v):
        p = v.player
        x, y = centre(WIN_W, WIN_H)
        win = self.window(p, "Tank Duel", x, y, WIN_W, WIN_H)
        v.win = win
        v.status = win.add(Label(4, 1, 400, 10, "", flags=GFlag.BOLD))
        v.wind = win.add(Label(452, 1, 160, 10, ""))
        v.grid = win.add(Grid(GX, GY, COLS, ROWS, TILE_W, TILE_H, RESOURCE_SLOT,
                              cells=self.cells_for(v, self.field.tiles)))
        v.tanks = win.add(Label(4, GY + ROWS * TILE_H + 2, WIN_W - 8, 10, ""))
        v.buttons = []
        x = 4
        for what, label_w in (("angle", 48), ("power", 48)):
            win.add(Label(x, CY + 3, label_w, 10, what.capitalize() + ":"))
            x += label_w
            for step in (-5, -1):
                v.buttons.append(win.add(Button(x, CY, 28, 16, "%d" % step,
                                                on_click=lambda b, w=what, s=step:
                                                self.adjust(v, w, s))))
                x += 30
            label = win.add(Label(x, CY + 3, 28, 10, "", flags=GFlag.CENTRE))
            setattr(v, what, label)
            x += 30
            for step in (1, 5):
                v.buttons.append(win.add(Button(x, CY, 28, 16, "+%d" % step,
                                                on_click=lambda b, w=what, s=step:
                                                self.adjust(v, w, s))))
                x += 30
            x += 8
        v.fire = win.add(Button(x, CY, 56, 16, "Fire", GFlag.DEFAULT,
                                on_click=lambda b: self.fire_button(v)))
        v.rematch = win.add(Button(WIN_W - 4 - 56 - 8 - 72, CY, 72, 16, "Rematch",
                                   GFlag.DISABLED, on_click=lambda b: self.rematch(v)))
        win.add(Button(WIN_W - 4 - 56, CY, 56, 16, "Leave", on_click=lambda b: self.quit(v)))
        self.show(p, win)

    @staticmethod
    def _put(gadget, text):
        if gadget.text != text:
            if gadget.shown:
                gadget.set_text(text)
            else:
                gadget.text = text

    # ---- drawing ----

    def redraw(self, dots=None):
        """Everyone's field (with `dots` drawn on: the shell, a blast) and their lines."""
        extra = self.field.with_dots(dots) if dots else {}
        tiles = list(self.field.tiles)
        for cell, data in extra.items():
            tiles[cell] = data
        for v in self.views.values():
            if v.player not in self.players or v.win is None or not v.win.shown:
                continue
            v.grid.set_cells(self.cells_for(v, tiles, set(v.grid.cells)))
            self.draw_lines(v)

    @staticmethod
    def cells_for(v, tiles, keep=None):
        """The viewer's tile numbers for `tiles` (each sent if it's new to them)."""
        keep = set(keep or ())
        cells = []
        for data in tiles:
            t = v.cache.get(data, keep)
            keep.add(t)
            cells.append(t)
        return cells

    def draw_lines(self, v):
        me = self.tank_of(v.player)
        current = self.tanks[self.turn]
        if self.phase == "over":
            line = self.result
        elif self.phase == "flight":
            line = "%s fires!" % ("You" if current is me else current.name)
        elif current is me:
            left = max(0, int(TURN_SECS - (time.monotonic() - self.turn_since)))
            line = "Your turn (%s): aim and Fire. (%d s)" % (me.colour_name, left)
        elif current.computer:
            line = "%s is aiming..." % current.name
        else:
            line = "%s's turn..." % current.name
        self._put(v.status, line)
        w = self.wind
        arrows = (1 + abs(w) // 4) * ("<" if w < 0 else ">")
        self._put(v.wind, "No wind" if w == 0 else
                  "Wind: %s %d" % (arrows, -w) if w < 0 else "Wind: %d %s" % (w, arrows))
        self._put(v.tanks, "   ".join(
            "%s (%s) %s" % ("you" if t is me else t.name, t.colour_name,
                            t.health if t.alive else "out") for t in self.tanks)[:WIN_W // 8])
        mine = me if me is not None else current
        self._put(v.angle, str(mine.angle))
        self._put(v.power, str(mine.power))
        my_turn = self.phase == "aim" and current is me and me is not None and me.alive
        for b in v.buttons:
            b.enable(my_turn)
        v.fire.enable(my_turn)
        v.rematch.enable(self.phase == "over" and v.player not in self.rematch_from)

    # ---- aiming and firing ----

    def adjust(self, v, what, step):
        me = self.tank_of(v.player)
        if self.over or self.phase != "aim" or me is None or self.tanks[self.turn] is not me:
            return None
        if what == "angle":
            me.angle = max(ANGLE_MIN, min(ANGLE_MAX, me.angle + step))
            self.field.paint(me.x - BARREL - 1, me.y - 15, me.x + BARREL + 2, me.y)
        else:
            me.power = max(POWER_MIN, min(POWER_MAX, me.power + step))
        self.redraw()
        return None

    def fire_button(self, v):
        me = self.tank_of(v.player)
        if self.over or self.phase != "aim" or me is None or self.tanks[self.turn] is not me:
            return None
        return self.fire(me)

    def fire(self, tank):
        self.phase = "flight"
        path, end = flight(*tank.muzzle(), tank.world_angle(), tank.power, self.wind,
                           self.ground, self.tanks, shooter=tank)
        self.redraw()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self.land(end)                    # (no loop: no animation)
        self._flying = loop.create_task(self._fly(path, end))
        return None

    async def _fly(self, path, end):
        per = max(1, round(STEP / DT))
        for k in range(per, len(path) + per, per):
            if self.over:
                return
            head = path[min(k, len(path)) - 1]
            tail = [path[max(0, min(k, len(path)) - 1 - j * per // 2)] for j in (1, 2)]
            dots = [(x, y, SHELL) for x, y in tail] + [
                (head[0] + dx, head[1] + dy, SHELL) for dx in (0, 1) for dy in (0, 1)]
            self.redraw(dots)
            await asyncio.sleep(STEP)
        if end[0] != "off":
            x, y = end[-2], end[-1]
            for r, c in zip((3, 6, CRATER), BLAST):
                if self.over:
                    return
                self.redraw([(x + dx, y + dy, c) for dx in range(-r, r + 1)
                             for dy in range(-r, r + 1) if dx * dx + dy * dy <= r * r])
                await asyncio.sleep(STEP * 1.5)
        if not self.over:
            self.land(end)

    def land(self, end):
        """The shell is down: the crater, the damage, the tanks falling; then the next turn."""
        shooter = self.tanks[self.turn]
        hit_names = []
        if end[0] != "off":
            x, y = end[-2], end[-1]
            direct = end[1] if end[0] == "tank" else None
            self.field.crater(x, y)
            for t in self.tanks:
                if not t.alive:
                    continue
                d = math.hypot(t.x - x, (t.y - 2) - y)
                dmg = int(DAMAGE * (1 - d / REACH)) if d < REACH else 0
                if t is direct:
                    dmg = max(dmg, DIRECT)
                if dmg > 0:
                    t.health = max(0, t.health - dmg)
                    hit_names.append("%s %s" % (t.name, "is out!" if not t.alive
                                                else "-%d" % dmg))
            for t in self.tanks:                    # down to the ground left under them
                t.y = self.ground[t.x]
            self.field.paint(x - CRATER - TANK_W, 0, x + CRATER + TANK_W + 1, H)
            for t in self.tanks:
                self.field.paint(t.x - TANK_W, 0, t.x + TANK_W + 1, H)
        self.log_shot(shooter, end, hit_names)
        alive = [t for t in self.tanks if t.alive]
        if len(alive) <= 1:
            return self.game_over(alive[0] if alive else None)
        self.phase = "aim"
        self.next_tank()
        self.wind = max(-WIND_MAX, min(WIND_MAX, self.wind + self.rng.randint(-3, 3)))
        self.turn_since = time.monotonic() + NEXT_TURN
        self.redraw()
        return None

    def log_shot(self, shooter, end, hits):
        what = ("off the field" if end[0] == "off" else ", ".join(hits) if hits else "a miss")
        for v in self.views.values():
            if v.player in self.players:
                v.player.session.toast("%s: %s" % (shooter.name, what), seconds=3)

    def next_tank(self):
        for k in range(1, len(self.tanks) + 1):
            t = self.tanks[(self.turn + k) % len(self.tanks)]
            if t.alive:
                self.turn = t.index
                return

    def tick(self):
        if self.over or self.phase != "aim":
            return
        t = self.tanks[self.turn]
        now = time.monotonic()
        if now < self.turn_since:
            return
        if t.computer:
            if now - self.turn_since >= COMPUTER_DELAY:
                self.computer_turn(t)
            return
        if t.player not in self.players:
            return self.pass_turn(t)
        left = TURN_SECS - (now - self.turn_since)
        if left <= 0:
            t.player.session.toast("Too slow: your turn passes.")
            return self.pass_turn(t)
        if int(left) != int(left + self.tick_interval):
            v = self.views.get(t.player)
            if v is not None:
                self.draw_lines(v)
        return None

    def pass_turn(self, t):
        self.next_tank()
        self.turn_since = time.monotonic()
        self.redraw()

    def computer_turn(self, t):
        enemies = [o for o in self.tanks if o.alive and o is not t]
        target = min(enemies, key=lambda o: abs(o.x - t.x) + self.rng.uniform(0, W / 3))
        t.facing = 1 if target.x > t.x else -1
        t.angle, t.power = computer_aim(t, target, self.wind, self.ground, self.rng)
        self.field.paint(t.x - BARREL - 1, t.y - 15, t.x + BARREL + 2, t.y)
        self.fire(t)

    # ---- the end ----

    def game_over(self, winner):
        self.phase = "over"
        self.result = ("%s wins!" % winner.name if winner is not None else "Nobody's left: a draw.")
        people = [t for t in self.tanks if t.player is not None and t.player in self.players]
        for t in people:
            self.credit(t.player.session, "game played")
        if winner is not None and winner.player in self.players:
            others = [t for t in self.tanks if t is not winner and t.player is not None]
            self.credit(winner.player.session, "game won",
                        beat=others[0].player.session if len(others) == 1
                        and len(self.tanks) == 2 else None)
            winner.player.session.toast("You win!", seconds=3)
        if self.players:
            self.players[0].session.log("tank duel: %s" % self.result)
        self.redraw()

    def rematch(self, v):
        if self.phase != "over" or v.player not in self.players:
            return None
        self.rematch_from.add(v.player)
        if all(p in self.rematch_from for p in self.players):
            self.new_round()
            self.redraw()
        else:
            self.redraw()
            for p in self.players:
                if p is not v.player:
                    p.session.toast("%s wants a rematch." % v.player.name, seconds=4)
        return None

    def quit(self, v):
        session = v.player.session
        self.leave(v.player)
        if self._lobby is not None:
            return self._lobby.open(session)
        return None

    def on_leave(self, player):
        t = self.tank_of(player)
        if not self.players:
            return self.end()
        if t is not None and t.alive and self.phase != "over":
            t.health = 0
            self.field.paint(t.x - TANK_W, 0, t.x + TANK_W + 1, H)
            alive = [o for o in self.tanks if o.alive]
            if len(alive) <= 1:
                return self.game_over(alive[0] if alive else None)
            if self.tanks[self.turn] is t and self.phase == "aim":
                self.next_tank()
                self.turn_since = time.monotonic()
        self.redraw()
        return None
