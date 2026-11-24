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
import re
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
    extra = [assemble_stack(), client_version()]
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


VERSION_FILE = os.path.join(m.ROOT, 'client-src', 'VERSION')


def read_version(path=VERSION_FILE):
    """client-src/VERSION: {"build": n, "oldest": n, "name": "2.1"} (the name: the build's
    number when it doesn't say)."""
    out = {}
    for line in open(path, encoding='utf-8'):
        line = line.split('#', 1)[0].strip()
        if '=' in line:
            key, value = (s.strip() for s in line.split('=', 1))
            out[key] = value if key == 'name' else int(value)
    if not 1 <= out.get('build', 0) <= 65535 or not 1 <= out.get('oldest', 1) <= out['build']:
        sys.exit('client-src/VERSION: build=1..65535 and oldest=1..build')
    out.setdefault('oldest', 1)
    out.setdefault('name', str(out['build']))
    # always one digit each, major.minor (2.1; after 2.9 comes 3.0): the update's SD card
    # name is MEGANE and the two digits, MEGANE21.D81 (server-src updates.sd_name)
    if not re.fullmatch(r'\d\.\d', out['name']):
        sys.exit('client-src/VERSION: name is one digit, a dot, one digit, like 2.1 '
                 '(after 2.9 comes 3.0)')
    return out


def client_version():
    """client-src/gen/version.asm (CLIENT_BUILD, sent in HELLO) and target/assets/version (the
    file VERSION on the disk, which the server reads: updates.py)."""
    v = read_version()
    m.write_gen('version.asm', ['CLIENT_BUILD = %d' % v['build'],
                                'CLIENT_OLDEST = %d' % v['oldest'],
                                'CLIENT_NAME = "%s"' % v['name']],
                "the client's version (client-src/VERSION)")
    with open(os.path.join(m.ASSETS, 'version'), 'w', newline='\n') as f:
        f.write('build=%d\nname=%s\noldest=%d\n' % (v['build'], v['name'], v['oldest']))
    print('Client version: %s, build %d (oldest %d)' % (v['name'], v['build'], v['oldest']))
    return 'version'


def assemble_stack():
    """client-src/mega-ip (weather65's copy of mega-ip) -> target/assets/ethbin: a flat image
    for $2000 in bank 4, with a PRG header for load_file (loaded to $42000)"""
    out = os.path.join(m.ROOT, 'target', 'eth.tmp')
    lbl = os.path.join(m.ROOT, 'target', 'eth.tmp.lbl')
    subprocess.check_call([os.path.join(m.ROOT, '64tass.exe'), '-q', '--nostart',
                           os.path.join(m.ROOT, 'client-src', 'mega-ip', 'eth.asm'),
                           '-l', lbl, '-o', out])
    data = open(out, 'rb').read()
    os.remove(out)
    assert len(data) < 0x6000, 'the stack overflows the bank 4 window'
    open(os.path.join(m.ASSETS, 'ethbin'), 'wb').write(bytes([0x00, 0x20]) + data)
    stack_labels(lbl)
    os.remove(lbl)
    return 'ethbin'


# mega-ip's variables the debug build (client-src/netlog.asm) copies each frame, as seen with
# bank 4 at $2000: two blocks, LOCAL_IP..LOCAL_ISN and TXQ_HEAD..TCP_PEER_MAC
STACK_VARS = ['LOCAL_IP', 'LOCAL_PORT', 'REMOTE_IP', 'REMOTE_PORT', 'GATEWAY_IP', 'SUBNET_MASK',
              'ETH_STATE', 'TCP_STATE', 'REMOTE_ISN', 'LOCAL_ISN',
              'TXQ_HEAD', 'TXQ_COUNT', 'TXQ_INFLIGHT', 'TX_PEER_WINDOW', 'SEG_WND',
              'TX_UNACK_PENDING', 'TX_UNACK_RETRY_LEFT', 'TX_UNACK_SEQ',
              'TCP_PEER_MAC_VALID', 'TCP_PEER_MAC', 'TCP_TX_MAX_RETRIES']


def stack_labels(lbl):
    """mega-ip's label file -> client-src/gen/mipvars.asm (MIPV_NAME = address)"""
    found = {}
    for line in open(lbl):
        parts = line.split('=')
        if len(parts) == 2 and parts[0].strip() in STACK_VARS:
            found[parts[0].strip()] = int(parts[1].strip().lstrip('$'), 16)
    missing = [n for n in STACK_VARS if n not in found]
    assert not missing, 'mega-ip labels missing: %s' % missing
    assert 0 < found['LOCAL_ISN'] + 4 - found['LOCAL_IP'] <= 64, 'mega-ip block A moved'
    assert 0 < found['TCP_PEER_MAC'] + 6 - found['TXQ_HEAD'] <= 64, 'mega-ip block B moved'
    m.write_gen('mipvars.asm', ['MIPV_%s = $%04x' % (n, found[n]) for n in STACK_VARS],
                "mega-ip's variables (bank 4 view), for the debug build")


if __name__ == '__main__':
    build()
