"""Pictures for the client's screen (S.PICTURE), and packed resources (S.RESOURCE_PACKED).

    scr = to_screen(img)        # an iff.Image -> a Screen: mode, palette, data
    for offset, packed in packed_chunks(scr.data): ...

The client shows a picture over its whole 640x200 screen (protocol.py S.PICTURE):
- mode PIC_LORES: 320x200, each pixel shown twice across; the data is 64,000 bytes,
- mode PIC_HIRES: 640x200; 128,000 bytes (two resource slots).
The bytes are in the client's framebuffer order (lib/fcm640.asm: rows of 8x8 cells, a cell's
8 rows of 8 pixels), so it copies them straight in: for a hires picture, pixel (x, y) is byte
(y >> 3) * 5120 + (x >> 3) * 64 + (y & 7) * 8 + (x & 7); for a lores one, the byte of screen
pixel (2x, y) divided by 2. Colours are palette indexes 0-254 (on the client, 255 shows the
colour RAM's colour instead), with at most PIC_COLOURS entries.

A picture that doesn't fit is scaled down (nearest pixel) to fit, keeping its shape, and
centred on its darkest colour (the screen's border is that colour too). A picture's pixel shape: a 320x200 Amiga lores pixel is the unit; hires
pixels are half as wide, interlaced ones half as tall (from the size, or BMHD's aspect).
"""

from .iff import Image, CAMG_HIRES, CAMG_LACE
from ..protocol import RESOURCE_CHUNK, PIC_LORES, PIC_HIRES

PIC_COLOURS = 255
SCREEN_H = 200
WIDTHS = {PIC_LORES: 320, PIC_HIRES: 640}


class Screen:
    def __init__(self, mode, palette, data, w, h, border=0):
        self.mode = mode
        self.palette = palette        # [(r, g, b)], at most PIC_COLOURS
        self.data = data              # bytes, in the client's framebuffer order
        self.w, self.h = w, h         # the picture's size on the screen (in its mode's pixels)
        self.border = border          # the colour round it (and the screen's border): its darkest

    def __repr__(self):
        return "<Screen %s %dx%d %d colours>" % ("hires" if self.mode else "lores", self.w,
                                                 self.h, len(self.palette))


def pixel_shape(img):
    """A pixel's width / height, in Amiga lores pixels (1.0 = a 320x200 picture's): from the
    size and CAMG, unless BMHD's aspect says something quite different (many programs write
    1:1 for any picture, which is close enough to a lores 10:11 to ignore)."""
    shape = 1.0
    if img.w > 400 or img.camg & CAMG_HIRES:
        shape /= 2
    if img.h > 300 or img.camg & CAMG_LACE:
        shape *= 2
    if img.aspect:
        x, y = img.aspect
        said = x / y * 1.1                # (a lores pixel's own BMHD aspect is 10:11)
        if 0.2 <= said <= 5 and not 0.67 <= said / shape <= 1.5:
            return said
    return shape


def fit(img):
    """(mode, w, h on screen) for a picture."""
    mode = PIC_HIRES if img.w > 320 else PIC_LORES
    unit = 1.0 if mode == PIC_LORES else 0.5      # the screen pixel's shape in that mode
    tw = WIDTHS[mode]
    dw = img.w * pixel_shape(img) / unit          # its size in screen pixels, unscaled
    dh = img.h
    scale = min(1.0, tw / dw, SCREEN_H / dh)
    return mode, max(1, min(tw, round(dw * scale))), max(1, min(SCREEN_H, round(dh * scale)))


def to_screen(img):
    pixels, palette = img.pixels, img.palette
    if pixels is None:                            # true colour (HAM): 255 colours
        palette, pixels = quantise(img.rgb, PIC_COLOURS)
    elif len(palette) > PIC_COLOURS:
        pixels, palette = drop_255(pixels, palette)
    mode, w, h = fit(img)
    tw = WIDTHS[mode]
    x0, y0 = (tw - w) // 2, (SCREEN_H - h) // 2
    xs = [x * img.w // w for x in range(w)]
    if mode == PIC_HIRES:
        def at(x, y):
            return (y >> 3) * 5120 + (x >> 3) * 64 + (y & 7) * 8 + (x & 7)
    else:
        def at(x, y):
            sx = 2 * x
            return ((y >> 3) * 5120 + (sx >> 3) * 64 + (y & 7) * 8 + (sx & 7)) >> 1
    palette = list(palette[:PIC_COLOURS])
    border = min(range(len(palette)), key=lambda i: sum(palette[i]))
    data = bytearray(bytes((border,)) * (64000 if mode == PIC_LORES else 128000))
    for y in range(h):
        src = (y * img.h // h) * img.w
        sy = y0 + y
        for x in range(w):
            data[at(x0 + x, sy)] = pixels[src + xs[x]]
    return Screen(mode, palette, bytes(data), w, h, border)


def drop_255(pixels, palette):
    """A 256-colour picture: entry 255 can't be shown, so its pixels take the nearest of the
    others."""
    r, g, b = palette[255]
    near = min(range(255), key=lambda i: dist((r, g, b), palette[i]))
    return bytes(near if v == 255 else v for v in pixels), palette[:255]


def dist(a, b):
    return (a[0] - b[0]) ** 2 * 3 + (a[1] - b[1]) ** 2 * 4 + (a[2] - b[2]) ** 2 * 2


def quantise(rgb, n):
    """Median cut: (palette of at most n colours, pixels as indexes)."""
    hist = {}
    for c in rgb:
        k = (c[0] >> 3, c[1] >> 3, c[2] >> 3)
        hist[k] = hist.get(k, 0) + 1
    def measured(box):                # (its widest spread, along which axis, the box)
        if len(box) < 2:
            return (0, 0, box)
        spans = [max(k[a] for k, _ in box) - min(k[a] for k, _ in box) for a in range(3)]
        a = spans.index(max(spans))
        return (spans[a], a, box)

    boxes = [measured(list(hist.items()))]
    while len(boxes) < n:
        best = max(range(len(boxes)), key=lambda i: boxes[i][0])
        span, axis, box = boxes[best]
        if span <= 0:
            break
        boxes.pop(best)
        box = sorted(box, key=lambda kv: kv[0][axis])
        total = sum(c for _, c in box)
        acc, cut = 0, 1
        for i, (_, c) in enumerate(box):
            acc += c
            if acc * 2 >= total:
                cut = max(1, min(len(box) - 1, i + 1))
                break
        boxes += [measured(box[:cut]), measured(box[cut:])]
    palette, index = [], {}
    for _, _, box in boxes:
        total = sum(c for _, c in box) or 1
        palette.append(tuple(min(255, (sum(k[a] * c for k, c in box) * 8 + total * 4) // total)
                             for a in range(3)))
        for k, _ in box:
            index[k] = len(palette) - 1
    pixels = bytes(index[(c[0] >> 3, c[1] >> 3, c[2] >> 3)] for c in rgb)
    return palette, pixels


def packbits(data):
    """PackBits (ByteRun1) of data, as the client's gui_resource_packed unpacks it."""
    from .iff import pack_byterun1
    return pack_byterun1(data)


PACK_BLOCK = 128


def packed_chunks(data, chunk=RESOURCE_CHUNK):
    """[(offset, packed bytes)]: data packed in PACK_BLOCK pieces, gathered into messages of
    at most `chunk` packed bytes; each unpacks to the bytes from its offset on."""
    out = []
    start, parts, size = 0, [], 0
    for off in range(0, len(data), PACK_BLOCK):
        p = packbits(data[off:off + PACK_BLOCK])
        if parts and size + len(p) > chunk:
            out.append((start, b"".join(parts)))
            start, parts, size = off, [], 0
        parts.append(p)
        size += len(p)
    if parts:
        out.append((start, b"".join(parts)))
    return out


def unpackbits(data, n=None):
    """The other way (tests; the fake client)."""
    out = bytearray()
    i = 0
    while i < len(data):
        c = data[i]
        i += 1
        if c < 128:
            out += data[i:i + c + 1]
            i += c + 1
        elif c > 128:
            out += bytes((data[i],)) * (257 - c)
            i += 1
    return bytes(out if n is None else out[:n])


def image_from_screen(scr):
    """The picture back out of a Screen (tests): an Image of the whole screen in its mode."""
    tw = WIDTHS[scr.mode]
    px = bytearray(tw * SCREEN_H)
    for y in range(SCREEN_H):
        for x in range(tw):
            if scr.mode == PIC_HIRES:
                i = (y >> 3) * 5120 + (x >> 3) * 64 + (y & 7) * 8 + (x & 7)
            else:
                sx = 2 * x
                i = ((y >> 3) * 5120 + (sx >> 3) * 64 + (y & 7) * 8 + (sx & 7)) >> 1
            px[y * tw + x] = scr.data[i]
    return Image(tw, SCREEN_H, palette=scr.palette, pixels=bytes(px))
