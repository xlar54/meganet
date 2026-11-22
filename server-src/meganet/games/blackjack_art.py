"""The blackjack table and its cards as Grid tiles (games/blackjack.py): a green half-moon
table, COLS x ROWS tiles of 32 x 32 pixels, drawn in "fat" pixels (two screen pixels across,
one down: 640x200 pixels are about twice as tall as wide). The dealer's side is the straight
top edge; the players' three seats are along the rounded bottom.

The cards are bigger than poker's (poker_art.py): 16 x 28 fat pixels, 32 x 28 on the screen,
the rank and suit drawn twice as tall. As on the poker table, cards are drawn ON the table's
tiles for each viewer (compose), so a hand fans out across tiles. Edit freely."""

import math

from .poker_art import (GREY, FELT, FELT_LINE, WOOD, WOOD_LIGHT, WOOD_DARK, EDGE, WHITE, BLACK,
                        RED, BLUE, GOLD, RANK_GLYPHS, SMALL_SUITS, BIG_SUITS)

TILE_W, TILE_H = 32, 32
COLS, ROWS = 13, 3
W, H = COLS * TILE_W, ROWS * TILE_H           # 416 x 96 screen pixels
CARD_COLOURS = [WHITE, BLACK, RED, BLUE, GOLD]

CORNER = 36.0                                 # the bottom corners' radius, fat pixels
RAIL = 6.0


def _table_pixel(x, y):
    u, v = (x + 0.5) / 2.0, y + 0.5            # fat pixels
    wf = W / 2.0
    cu = min(max(u, CORNER), wf - CORNER)
    cv = min(v, H - CORNER)                    # (the top edge is straight: no rail there)
    r = math.hypot(u - cu, v - cv)             # 0 in the middle, CORNER at the edge
    if r > CORNER:
        return GREY
    if r > CORNER - 1:
        return EDGE
    if r > CORNER - 2:
        return WOOD_LIGHT
    if r > CORNER - RAIL + 1:
        return WOOD
    if r > CORNER - RAIL:
        return WOOD_DARK
    if v < 1.0:
        return WOOD_DARK                       # the dealer's edge
    line = CORNER - RAIL - 8                   # the line the players' cards sit on
    if line - 0.6 < r <= line + 0.4 and v > H - CORNER:
        return FELT_LINE
    return FELT


def _tiles():
    px = [[_table_pixel(x, y) for x in range(W)] for y in range(H)]
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

# ---- cards: 16 x 28 fat pixels ----

CARD_W, CARD_H = 16, 28


def _blank(body):
    g = [[body] * CARD_W for _ in range(CARD_H)]
    for y in range(CARD_H):
        for x in range(CARD_W):
            if x in (0, CARD_W - 1) or y in (0, CARD_H - 1):
                g[y][x] = BLACK
    for x, y in ((0, 0), (CARD_W - 1, 0), (0, CARD_H - 1), (CARD_W - 1, CARD_H - 1)):
        g[y][x] = None
    return g


def _stamp_tall(g, glyph, x0, y0, ink):
    """A glyph with every row drawn twice (fat pixels are twice as wide as tall)."""
    for gy, row in enumerate(glyph):
        for gx, ch in enumerate(row):
            if ch == "#":
                g[y0 + 2 * gy][x0 + gx] = g[y0 + 2 * gy + 1][x0 + gx] = ink


def card_face(c):
    g = _blank(WHITE)
    ink = RED if c.red else BLACK
    _stamp_tall(g, RANK_GLYPHS[c.rank], 2, 2, ink)              # the corner: rank, then suit
    _stamp_tall(g, SMALL_SUITS[c.suit], 9, 2, ink)
    _stamp_tall(g, BIG_SUITS[c.suit], (CARD_W - 7) // 2, 12, ink)   # the middle
    return g


def card_back():
    g = _blank(BLUE)
    for y in range(1, CARD_H - 1):
        for x in range(1, CARD_W - 1):
            if x in (1, CARD_W - 2) or y in (1, CARD_H - 2):
                g[y][x] = WHITE
            elif (x + y) % 3 == 0 or (x - y) % 3 == 0:
                g[y][x] = WHITE if (x + y) % 2 else BLUE
    return g


BACK = card_back()


def overlay_pixels(what):
    return BACK if what == "back" else card_face(what)


def overlay_width(what):
    return 2 * len(overlay_pixels(what)[0])


def compose(base, items):
    """Table tile `base` with each (card or "back", dx) of `items` drawn on it in turn (dx:
    its left edge in screen pixels, even; only the part on this tile), centred top to
    bottom. The tile's bytes."""
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
                    if 0 <= x < TILE_W:
                        px[(y0 + gy) * TILE_W + x] = v
    return bytes(px)


def felt():
    """A plain felt tile (a flying card is drawn on it; the felt is left out of the sprite)."""
    return TABLE_TILES[TABLE_CELLS[1 * COLS + COLS // 2]]


def preview(items, path):
    """A PNG of the table with cards [(row, x, what), ...] (x in table pixels: art checks)."""
    from PIL import Image
    from ..protocol import palette_rgb
    over = {}
    for row, x, what in items:
        for col in range(x // TILE_W, (x + overlay_width(what) - 1) // TILE_W + 1):
            if 0 <= col < COLS:
                over.setdefault((col, row), []).append((what, x - col * TILE_W))
    img = Image.new("RGB", (W, H * 2))
    for row in range(ROWS):
        for col in range(COLS):
            t = TABLE_TILES[TABLE_CELLS[row * COLS + col]]
            if (col, row) in over:
                t = compose(t, over[(col, row)])
            for y in range(TILE_H):
                for x in range(TILE_W):
                    rgb = palette_rgb(t[y * TILE_W + x])
                    for k in (0, 1):
                        img.putpixel((col * TILE_W + x, 2 * (row * TILE_H + y) + k), rgb)
    img.save(path)
