"""One's cards as tiles for a Grid gadget (games/one.py): 64 tiles of 32 x 22 pixels (640x200
pixels are about twice as tall as wide, so a tile looks like a card standing up).

Every card: a black outline, a white edge, the body in its colour, and a white panel in the
middle with the symbol in black. The glyphs below are 'fat' pixels (each two screen pixels
wide); edit freely.

Tiles:
    0           no card (the window's grey)
    1-52        1 + colour * 13 + face: colours R Y G B, faces 0-9, Skip, Reverse, Draw Two
    53, 54      Wild, Wild Draw Four (black)
    55          a card's back
    56-63       56 + colour * 2 + (0 Wild, 1 Wild Draw Four): one played, in the colour named
"""

from .one_rules import COLOURS, FACES, WILD, WILD4

TILE_W, TILE_H = 32, 22
N_TILES = 64
T_EMPTY, T_WILD, T_WILD4, T_BACK, T_NAMED = 0, 53, 54, 55, 56

GREY, BLACK, WHITE = 2, 254, 242               # GUI face; protocol.GAME_COLOURS
BODY = {"R": 251, "Y": 253, "G": 249, "B": 252}
GOLD, RED = 253, 251

DIGITS = {
    "0": [".####.", "##..##", "##..##", "##..##", "##..##", "##..##", "##..##", "##..##",
          ".####."],
    "1": ["..##..", ".###..", "####..", "..##..", "..##..", "..##..", "..##..", "..##..",
          "######"],
    "2": [".####.", "##..##", "....##", "....##", "...##.", "..##..", ".##...", "##....",
          "######"],
    "3": [".####.", "##..##", "....##", "....##", "..###.", "....##", "....##", "##..##",
          ".####."],
    "4": ["...##.", "..###.", ".####.", "##.##.", "##.##.", "######", "...##.", "...##.",
          "...##."],
    "5": ["######", "##....", "##....", "#####.", "....##", "....##", "....##", "##..##",
          ".####."],
    "6": [".####.", "##..##", "##....", "##....", "#####.", "##..##", "##..##", "##..##",
          ".####."],
    "7": ["######", "....##", "....##", "...##.", "...##.", "..##..", "..##..", ".##...",
          ".##..."],
    "8": [".####.", "##..##", "##..##", "##..##", ".####.", "##..##", "##..##", "##..##",
          ".####."],
    "9": [".####.", "##..##", "##..##", "##..##", ".#####", "....##", "....##", "##..##",
          ".####."],
    "S": ["..###..", ".#...#.", "#...###", "#..###.", "#.###.#", ".###..#", "###...#",
          ".#...#.", "..###.."],                  # Skip: a ring, struck through
    "R": ["..#...", ".##...", "######", ".##...", "..#...", "...#..", "...##.", "######",
          "...##."],                              # Reverse: two arrows
}
_PLUS = ["...", "...", ".#.", "###", ".#.", "...", "..."]
_SMALL = {"2": ["##.", "..#", "..#", ".#.", "#..", "#..", "###"],
          "4": ["#.#", "#.#", "#.#", "###", "..#", "..#", "..#"]}


def _plus(n):
    """'+2' / '+4', 7 fat pixels wide, 9 high."""
    rows = [p + "." + d for p, d in zip(_PLUS, _SMALL[n])]
    return ["......."] + rows + ["......."]


DIGITS["D"] = _plus("2")
GLYPH_WILD4 = _plus("4")
GLYPH_BACK = DIGITS["1"]

for _k, _g in list(DIGITS.items()) + [("+4", GLYPH_WILD4)]:
    assert len(_g) == 9 and all(len(r) == len(_g[0]) <= 7 for r in _g), _k

PANEL_X0, PANEL_X1, PANEL_Y0, PANEL_Y1 = 8, 23, 5, 16       # inclusive


def _card(body, panel=WHITE, glyph=None, ink=BLACK, quarters=False):
    px = [[GREY] * TILE_W for _ in range(TILE_H)]
    for y in range(TILE_H):
        for x in range(TILE_W):
            edge_y = y in (0, TILE_H - 1)
            edge_x = x < 2 or x >= TILE_W - 2
            if edge_y and edge_x:
                continue                                    # (rounded corners: grey)
            if edge_y or edge_x:
                px[y][x] = BLACK
            elif y in (1, TILE_H - 2) or x < 4 or x >= TILE_W - 4:
                px[y][x] = WHITE
            else:
                px[y][x] = body
    for y in range(PANEL_Y0, PANEL_Y1 + 1):
        for x in range(PANEL_X0, PANEL_X1 + 1):
            corner = (y in (PANEL_Y0, PANEL_Y1)
                      and x in (PANEL_X0, PANEL_X0 + 1, PANEL_X1 - 1, PANEL_X1))
            if corner:
                continue
            if quarters:
                right = x >= (PANEL_X0 + PANEL_X1 + 1) // 2
                low = y >= (PANEL_Y0 + PANEL_Y1 + 1) // 2
                px[y][x] = BODY["RBYG"[low * 2 + right]]
            else:
                px[y][x] = panel
    if glyph:
        w = len(glyph[0]) * 2
        x0 = (PANEL_X0 + PANEL_X1 + 1 - w) // 2 & ~1   # (even: a sprite takes every 2nd)
        y0 = PANEL_Y0 + 1
        for gy, row in enumerate(glyph):
            for gx, ch in enumerate(row):
                if ch == "#":
                    px[y0 + gy][x0 + 2 * gx] = px[y0 + gy][x0 + 2 * gx + 1] = ink
    return bytes(v for row in px for v in row)


def make_tiles():
    tiles = [bytes([GREY]) * (TILE_W * TILE_H)]
    for c in COLOURS:
        for f in FACES:
            tiles.append(_card(BODY[c], glyph=DIGITS[f]))
    tiles.append(_card(BLACK, quarters=True))
    tiles.append(_card(BLACK, glyph=GLYPH_WILD4))
    tiles.append(_card(BLACK, panel=RED, glyph=GLYPH_BACK, ink=GOLD))
    for c in COLOURS:
        tiles.append(_card(BODY[c], quarters=True))
        tiles.append(_card(BODY[c], glyph=GLYPH_WILD4))
    assert len(tiles) == N_TILES
    return b"".join(tiles)


COLOURS_USED = [BLACK, WHITE] + [BODY[c] for c in COLOURS]   # (a card sprite's colours)


def tile(card, colour=None):
    """The tile for a card (rules.Card; None: no card). A Wild with `colour` shows it named."""
    if card is None:
        return T_EMPTY
    if card.wild:
        if colour:
            return T_NAMED + COLOURS.index(colour) * 2 + (card.face == WILD4)
        return T_WILD4 if card.face == WILD4 else T_WILD
    return 1 + COLOURS.index(card.colour) * 13 + FACES.index(card.face)


TILES = make_tiles()
# every pixel is doubled across (S.FLY makes a sprite of every second one)
assert all(TILES[i] == TILES[i + 1] for i in range(0, len(TILES), 2))
