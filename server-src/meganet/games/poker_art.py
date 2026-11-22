"""The poker table and cards as Grid tiles (games/poker.py): a green felt table with a wooden
rail, COLS x ROWS tiles of 32 x 22 pixels (640x200 pixels are twice as tall as wide, so the
art is drawn in square "fat" pixels, two screen pixels each).

- TABLE_TILES: the table's distinct tiles (the felt repeats, so a few dozen), and TABLE_CELLS,
  which of them each cell shows. These are sent once (resource slot RESOURCE_SLOT).
- Cards, the dealer button and the pot's chips are drawn ON a cell's table tile by
  compose(): the table sends each viewer the tiles it needs as they come (poker.TileCache),
  into the slot's tiles after the table's. So a card can sit anywhere, across two tiles
  (each draws its part), rail and all.

Colours: protocol.GAME_COLOURS and the GUI's (0-15). Edit freely.
"""

import math

TILE_W, TILE_H = 32, 22
COLS, ROWS = 13, 5
W, H = COLS * TILE_W, ROWS * TILE_H           # 416 x 110

GREY = 2                                      # the window's background
FELT = 10                                     # GUI green (0, 128, 0)
FELT_LINE = 249                               # a lighter green: the betting line
WOOD, WOOD_LIGHT, WOOD_DARK, EDGE = 241, 240, 244, 254
WHITE, BLACK, RED, BLUE, GOLD = 242, 254, 251, 252, 253
CARD_COLOURS = [WHITE, BLACK, RED, BLUE, GOLD]   # (a flying card's sprite: no felt)

RADIUS = 54.5                                 # the stadium's ends, in fat pixels
RAIL = 8.0                                    # its width


def _table_pixel(x, y):
    """The colour of table pixel (x, y), x in screen pixels."""
    u = (x + 0.5) / 2.0                        # fat pixels
    v = y + 0.5
    cy = H / 2.0
    left, right = RADIUS, W / 2.0 - RADIUS
    cu = min(max(u, left), right)
    r = math.hypot(u - cu, v - cy)
    if r > RADIUS:
        return GREY
    if r > RADIUS - 1:
        return EDGE
    if r > RADIUS - 2.2:
        return WOOD_LIGHT if v < cy else WOOD
    if r > RADIUS - RAIL + 1:
        return WOOD
    if r > RADIUS - RAIL:
        return WOOD_DARK
    # the felt, with a betting line inside the rail
    line = RADIUS - RAIL - 9
    if line - 0.6 < r <= line + 0.4 and abs(v - cy) > 6:
        return FELT_LINE
    return FELT


def table_pixels():
    return [[_table_pixel(x, y) for x in range(W)] for y in range(H)]


def _tiles():
    px = table_pixels()
    tiles, index, cells = [], {}, []
    for row in range(ROWS):
        for col in range(COLS):
            t = bytes(px[row * TILE_H + y][col * TILE_W + x]
                      for y in range(TILE_H) for x in range(TILE_W))
            if t not in index:
                index[t] = len(tiles)
                tiles.append(t)
            cells.append(index[t])
    return tiles, cells


TABLE_TILES, TABLE_CELLS = _tiles()
TABLE = b"".join(TABLE_TILES)
N_TABLE = len(TABLE_TILES)

# ---- cards: 12 x 20 fat pixels (24 x 20 screen pixels) ----

CARD_W, CARD_H = 12, 20                       # fat pixels

RANK_GLYPHS = {
    14: [".#.", "#.#", "###", "#.#", "#.#"],
    2: ["##.", "..#", ".#.", "#..", "###"],
    3: ["##.", "..#", ".#.", "..#", "##."],
    4: ["#.#", "#.#", "###", "..#", "..#"],
    5: ["###", "#..", "##.", "..#", "##."],
    6: [".##", "#..", "###", "#.#", "###"],
    7: ["###", "..#", ".#.", ".#.", ".#."],
    8: ["###", "#.#", "###", "#.#", "###"],
    9: ["###", "#.#", "###", "..#", "##."],
    10: ["#.###", "#.#.#", "#.#.#", "#.#.#", "#.###"],
    11: ["..#", "..#", "..#", "#.#", ".#."],
    12: [".#.", "#.#", "#.#", ".#.", "..#"],
    13: ["#.#", "#.#", "##.", "#.#", "#.#"],
}
SMALL_SUITS = {
    "h": [".#.#.", "#####", "#####", ".###.", "..#.."],
    "d": ["..#..", ".###.", "#####", ".###.", "..#.."],
    "s": ["..#..", ".###.", "#####", "#####", "..#.."],
    "c": ["..#..", ".###.", "#.#.#", "#####", "..#.."],
}
BIG_SUITS = {
    "h": [".##.##.", "#######", "#######", "#######", ".#####.", "..###..", "...#..."],
    "d": ["...#...", "..###..", ".#####.", "#######", ".#####.", "..###..", "...#..."],
    "s": ["...#...", "..###..", ".#####.", "#######", "#######", "..###..", ".#####."],
    "c": ["..###..", "..###..", "##.#.##", "#######", "##.#.##", "...#...", "..###.."],
}


def _blank_card(body):
    """12 x 20 fat pixels: None (transparent: the corners), or a colour."""
    g = [[body] * CARD_W for _ in range(CARD_H)]
    for y in range(CARD_H):
        for x in range(CARD_W):
            if (x in (0, CARD_W - 1)) or (y in (0, CARD_H - 1)):
                g[y][x] = BLACK
    for x, y in ((0, 0), (CARD_W - 1, 0), (0, CARD_H - 1), (CARD_W - 1, CARD_H - 1)):
        g[y][x] = None
    return g


def _stamp(g, glyph, x0, y0, ink):
    for gy, row in enumerate(glyph):
        for gx, ch in enumerate(row):
            if ch == "#":
                g[y0 + gy][x0 + gx] = ink


def card_face(c):
    """A card (poker_rules.Card) as fat pixels."""
    g = _blank_card(WHITE)
    ink = RED if c.red else BLACK
    _stamp(g, RANK_GLYPHS[c.rank], 1, 2, ink)
    _stamp(g, SMALL_SUITS[c.suit], 6, 2, ink)
    _stamp(g, BIG_SUITS[c.suit], 2, 10, ink)
    return g


def card_back():
    g = _blank_card(BLUE)
    for y in range(1, CARD_H - 1):
        for x in range(1, CARD_W - 1):
            if x in (1, CARD_W - 2) or y in (1, CARD_H - 2):
                g[y][x] = WHITE
            elif (x + y) % 3 == 0 or (x - y) % 3 == 0:
                g[y][x] = WHITE if (x + y) % 2 else BLUE
    return g


def _disc_button():
    """The dealer button: a white disc with a black D."""
    disc = ["..#####..", ".#######.", "#########", "#########", "#########", "#########",
            "#########", ".#######.", "..#####.."]
    d = ["###.", "#..#", "#..#", "#..#", "###."]
    g = [[WHITE if ch == "#" else None for ch in row] for row in disc]
    g[0] = [BLACK if v else None for v in g[0]]
    g[-1] = [BLACK if v else None for v in g[-1]]
    for row in g:
        idx = [i for i, v in enumerate(row) if v is not None]
        row[idx[0]] = row[idx[-1]] = BLACK
    _stamp(g, d, 3, 2, BLACK)
    return g


def chips():
    """Three little stacks of chips (the pot): 13 x 9 fat pixels."""
    w, h = 13, 9
    g = [[None] * w for _ in range(h)]
    for sx, colour, n in ((0, RED, 3), (4, BLUE, 4), (8, GOLD, 2)):
        for k in range(n):
            y = h - 2 - 2 * k
            for x in range(sx + 1, sx + 4):
                g[y][x] = colour
                g[y + 1][x] = BLACK
            g[y][sx] = g[y][sx + 4] = None
            g[y + 1][sx + 1] = g[y + 1][sx + 3] = BLACK
            g[y][sx + 2] = WHITE if k == n - 1 else colour
    return g


def star():
    """A gold star, 9 x 9 fat pixels: the winner's, flashing beside their seat (a sprite:
    STAR_COLOURS show, the felt round it doesn't)."""
    rows = ["....#....", "...###...", "...###...", "#########", ".#######.", "..#####..",
            "..##.##..", ".##...##.", ".#.....#."]
    g = [[GOLD if ch == "#" else None for ch in row] for row in rows]
    for x, y in ((4, 1), (4, 3), (4, 4), (3, 4), (5, 4)):
        g[y][x] = WHITE
    return g


STAR_COLOURS = [GOLD, WHITE]
OVERLAYS = {"button": _disc_button(), "chips": chips(), "back": card_back(), "star": star()}


def overlay_pixels(what):
    """Fat pixels for an overlay: a Card, or "back", "button", "chips"."""
    if isinstance(what, str):
        return OVERLAYS[what]
    return card_face(what)


def overlay_width(what):
    """How wide an overlay is, in screen pixels."""
    return 2 * len(overlay_pixels(what)[0])


def compose(base, items):
    """Table tile `base` (bytes) with each (what, dx) of `items` drawn on it in turn, its left
    edge `dx` screen pixels in (even; it may start left of the tile or run off its right: only
    the part on this tile is drawn), centred top to bottom. The tile's bytes."""
    px = bytearray(base)
    for what, dx in items:
        g = overlay_pixels(what)
        y0 = (TILE_H - len(g)) // 2
        for gy, row in enumerate(g):
            for gx, v in enumerate(row):
                if v is None:
                    continue
                for k in (0, 1):
                    x = dx + 2 * gx + k
                    y = y0 + gy
                    if 0 <= x < TILE_W and 0 <= y < TILE_H:
                        px[y * TILE_W + x] = v
    return bytes(px)


def overlay(base, what, dx):
    """compose() with one item."""
    return compose(base, [(what, dx)])


def interior():
    """The plain felt tile (a flying card is drawn on it: the felt is left out of its
    sprite's colours, so only the card shows)."""
    centre = TABLE_CELLS[(ROWS // 2) * COLS + COLS // 2]
    return TABLE_TILES[centre]


def preview(cells_overlays, path):
    """A PNG of the table with overlays {(col, row): [(what, dx), ...]} (art checks)."""
    from PIL import Image
    from ..protocol import palette_rgb
    img = Image.new("RGB", (W, H * 2))
    for row in range(ROWS):
        for col in range(COLS):
            t = TABLE_TILES[TABLE_CELLS[row * COLS + col]]
            if (col, row) in cells_overlays:
                t = compose(t, cells_overlays[(col, row)])
            for y in range(TILE_H):
                for x in range(TILE_W):
                    rgb = palette_rgb(t[y * TILE_W + x])
                    for k in (0, 1):
                        img.putpixel((col * TILE_W + x, 2 * (row * TILE_H + y) + k), rgb)
    img.save(path)
