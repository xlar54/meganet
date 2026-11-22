"""Build-time asset compiler: client-src/assets -> client-src/gen + target/assets. build.bat
runs it.

It reads:
  client-src/assets/logo.png   the sign-on logo; width and height multiples of 8.
                               Colours equal to a GUI colour (GUI_COLOURS) use that entry;
                               the rest are quantised into entries 16-239.
                               Entries 240-254 are GAME_COLOURS (the server's game art).
and writes:
  client-src/gen/palette.asm   palette_rgb: 3 x 256 bytes (r, g, b), entries 16+ the art's
  client-src/gen/logo.asm      LOGO_CW / LOGO_CH (cells), LOGO_ATTIC
  client-src/gen/manifest.asm  the packed files and their attic addresses (lib/manifest.asm)
  client-src/gen/server.asm    DEFAULT_SERVER, from private/server_address.txt (default_server)
  target/assets/*              the packed files, and files.txt for build.bat
The logo is stored cell by cell, row-major (lib/fcm640.asm's layout), so each row of cells
is one DMA copy into the framebuffer.
"""
import os
import subprocess
import sys

from PIL import Image

import m65assets as m

# entries 0-15: must match the GC_* colours in client-src/lib/gui/gui.asm
GUI_COLOURS = [
    (0, 0, 0), (255, 255, 255), (192, 192, 192), (128, 128, 128),
    (223, 223, 223), (0, 0, 128), (0, 128, 128), (16, 132, 208),
    (255, 255, 225), (192, 0, 0), (0, 128, 0), (64, 64, 64),
    (0, 0, 255), (8, 8, 24), (255, 255, 0), (0, 255, 255),
]
ART_FIRST = 16
GAME_FIRST = 240                   # entries 240-254: fixed colours for the server's game art
# (board squares, pieces): must match server-src/meganet/protocol.py GAME_COLOURS
GAME_COLOURS = [
    (240, 217, 181), (181, 136, 99),             # 240 / 241: light and dark squares
    (250, 248, 240), (190, 184, 172),            # 242 / 243: white pieces, their shade
    (40, 36, 34), (120, 112, 104),               # 244 / 245: black pieces, their highlight
    (205, 210, 106), (170, 162, 58),             # 246 / 247: last-move squares (light, dark)
    (90, 100, 60), (118, 150, 86),               # 248: move dots; 249 green squares
    (238, 238, 210), (200, 40, 40),              # 250 cream squares; 251 red
    (60, 120, 200), (230, 190, 40), (20, 20, 20),    # 252 blue; 253 gold; 254 near black
]
ART_COUNT = GAME_FIRST - ART_FIRST      # entry 255 shows the colour-RAM colour: never used
assert len(GAME_COLOURS) == 255 - GAME_FIRST
LOGO_ATTIC = 0x8000000


def cells(img, lookup):
    w, h = img.size
    assert w % 8 == 0 and h % 8 == 0, 'logo size must be whole 8x8 cells'
    px = img.load()
    out = bytearray()
    for cy in range(h // 8):
        for cx in range(w // 8):
            for y in range(8):
                for x in range(8):
                    out.append(lookup[px[cx * 8 + x, cy * 8 + y]])
    return out


def build():
    img = Image.open(os.path.join(m.SRC_ASSETS, 'logo.png')).convert('RGB')
    w, h = img.size
    pixels = [list(img.getdata())]
    colours, idx = m.quantize([pixels], ART_COUNT, fixed=GUI_COLOURS)
    lookup = {c: ART_FIRST + i for c, i in idx.items()}
    lookup.update({c: i for i, c in enumerate(GUI_COLOURS)})
    m.write_palette(GUI_COLOURS + colours + [(0, 0, 0)] * (ART_COUNT - len(colours))
                    + GAME_COLOURS)
    data = cells(img, lookup)
    m.write_gen('logo.asm', ['LOGO_CW = %d' % (w // 8), 'LOGO_CH = %d' % (h // 8),
                             'LOGO_ATTIC = $%07x' % LOGO_ATTIC], 'sign-on logo size')
    parts = m.write_parts('LOGO', data)
    m.write_manifest([(n, LOGO_ATTIC + off, ln) for n, off, ln in parts])
    default_server()
    extra = [assemble_stack()]
    if '--mock' in sys.argv:            # replay build: the recorded server session
        src = sys.argv[sys.argv.index('--mock') + 1]
        data = open(src, 'rb').read()
        open(os.path.join(m.ASSETS, 'mockrx'), 'wb').write(bytes([0, 0]) + data)
        extra.append('mockrx')
    with open(os.path.join(m.ASSETS, 'files.txt'), 'a') as fh:
        fh.write('\n'.join(extra) + '\n')


SERVER_FILE = os.path.join(m.ROOT, 'private', 'server_address.txt')


def default_server():
    """client-src/gen/server.asm: DEFAULT_SERVER, the address already in the Connect window's
    Server box. It comes from $MEGANET_SERVER, else the first line of
    private/server_address.txt (kept out of git), else nothing (the box starts empty)."""
    addr = os.environ.get('MEGANET_SERVER', '').strip()
    if not addr and os.path.exists(SERVER_FILE):
        addr = (open(SERVER_FILE).read().splitlines() or [''])[0].strip()
    parts = addr.split('.')
    if addr and not (len(parts) == 4 and all(p.isdigit() and int(p) < 256 for p in parts)):
        sys.exit('default server %r: four numbers, like 192.168.1.10' % addr)
    m.write_gen('server.asm', ['DEFAULT_SERVER = "%s"' % addr],
                "the Connect window's server address (private/server_address.txt)")
    print('Default server: %s' % (addr or '(none)'))


def assemble_stack():
    """client-src/mega-ip (weather65's copy of mega-ip) -> target/assets/ethbin: a flat image
    for $2000 in bank 4, with a PRG header for load_file (loaded to $42000)"""
    out = os.path.join(m.ROOT, 'target', 'eth.tmp')
    subprocess.check_call([os.path.join(m.ROOT, '64tass.exe'), '-q', '--nostart',
                           os.path.join(m.ROOT, 'client-src', 'mega-ip', 'eth.asm'), '-o', out])
    data = open(out, 'rb').read()
    os.remove(out)
    assert len(data) < 0x6000, 'the stack overflows the bank 4 window'
    open(os.path.join(m.ASSETS, 'ethbin'), 'wb').write(bytes([0x00, 0x20]) + data)
    return 'ethbin'


if __name__ == '__main__':
    build()
