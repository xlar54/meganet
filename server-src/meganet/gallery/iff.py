"""IFF pictures (Deluxe Paint's format): reading ILBM and PBM, writing ILBM. Standard library
only.

    img = read_iff(data)        # an Image, or IFFError saying why not
    data = write_ilbm(img)      # back to an ILBM (ByteRun1), the planes the colours need

What's read:
- FORM ILBM (planar: 1-8 bitplanes, a mask plane is skipped) and FORM PBM (chunky, 8 bits);
- compression 0 (none) or 1 (ByteRun1);
- BMHD, CMAP, CAMG: EHB (64 colours: the second 32 are the first at half brightness) and
  HAM6 / HAM8 (decoded to true colour, then cut down to 255 colours: picture.quantise);
- an old CMAP of 4-bit values (every low nibble 0) is spread to 8 bits (v | v >> 4).
Other chunks are skipped. A FORM inside a LIST / CAT (an animation) isn't read.
"""

import struct

MAX_W, MAX_H = 1024, 1024         # bigger than any MEGA65 or Amiga screen
CAMG_HAM, CAMG_EHB, CAMG_HIRES, CAMG_LACE = 0x800, 0x80, 0x8000, 0x4


class IFFError(Exception):
    """Not an IFF picture this module can read (the message says why, for the user)."""


class Image:
    """A picture: w x h pixels. Either `palette` ([(r, g, b)], 0-255 each) and `pixels`
    (bytes, a palette index a pixel, row by row), or `rgb` ([(r, g, b)] a pixel, row by
    row) for true-colour pictures (HAM)."""

    def __init__(self, w, h, palette=None, pixels=None, rgb=None, aspect=None, camg=0):
        self.w, self.h = w, h
        self.palette = palette
        self.pixels = pixels
        self.rgb = rgb
        self.aspect = aspect          # (x, y) from BMHD, or None
        self.camg = camg

    def colours_used(self):
        if self.pixels is None:
            return len(set(self.rgb))
        return len(set(self.pixels))

    def __repr__(self):
        return "<Image %dx%d %s>" % (self.w, self.h, "%d colours" % len(self.palette)
                                     if self.palette is not None else "true colour")


# ---- reading ----

def chunks(data, start, end):
    """(id, body) for each chunk from `start` to `end` (odd lengths are padded)."""
    p = start
    while p + 8 <= end:
        cid = data[p:p + 4]
        size = struct.unpack(">I", data[p + 4:p + 8])[0]
        body = data[p + 8:p + 8 + size]
        if len(body) < size:
            raise IFFError("The file is cut short.")
        yield cid, body
        p += 8 + size + (size & 1)


def unpack_byterun1(data, pos, n):
    """n bytes unpacked from data[pos:], and where the packed bytes ended."""
    out = bytearray()
    end = len(data)
    while len(out) < n:
        if pos >= end:
            raise IFFError("The picture's data is cut short.")
        c = data[pos]
        pos += 1
        if c < 128:                       # c + 1 bytes as they are
            out += data[pos:pos + c + 1]
            pos += c + 1
        elif c > 128:                     # the next byte 257 - c times
            if pos >= end:
                raise IFFError("The picture's data is cut short.")
            out += bytes((data[pos],)) * (257 - c)
            pos += 1
        # (128: nothing)
    if len(out) > n:                      # a run across the row's end: the rest is junk
        out = out[:n]
    return bytes(out), pos


# a byte -> its 8 bits, left pixel first
_BITS = [tuple((b >> (7 - i)) & 1 for i in range(8)) for b in range(256)]


def read_iff(data):
    data = bytes(data)
    if len(data) < 12 or data[:4] != b"FORM":
        raise IFFError("That isn't an IFF file.")
    form = data[8:12]
    if form not in (b"ILBM", b"PBM "):
        raise IFFError("That IFF file isn't a picture (it's %s)."
                       % form.decode("latin-1").strip())
    size = struct.unpack(">I", data[4:8])[0]
    end = min(len(data), 8 + size)
    bmhd = cmap = body = None
    camg = 0
    for cid, b in chunks(data, 12, end):
        if cid == b"BMHD":
            bmhd = b
        elif cid == b"CMAP":
            cmap = b
        elif cid == b"CAMG" and len(b) >= 4:
            camg = struct.unpack(">I", b[:4])[0]
        elif cid == b"BODY":
            body = b
    if bmhd is None or len(bmhd) < 20:
        raise IFFError("The picture has no header (BMHD).")
    if body is None:
        raise IFFError("The picture has no pixels (BODY).")
    (w, h, _x, _y, planes, masking, compression, _pad, _transparent, xasp, yasp,
     _pw, _ph) = struct.unpack(">HHhhBBBBHBBhh", bmhd[:20])
    if not (1 <= w <= MAX_W and 1 <= h <= MAX_H):
        raise IFFError("The picture is %dx%d: at most %dx%d, please." % (w, h, MAX_W, MAX_H))
    if compression not in (0, 1):
        raise IFFError("The picture is packed in a way MegaNet can't read (%d)." % compression)
    chunky = form == b"PBM "
    if chunky and planes != 8:
        raise IFFError("A PBM picture with %d bit planes can't be read." % planes)
    if not chunky and not 1 <= planes <= 8:
        raise IFFError("The picture has %d bit planes: 1-8, please." % planes)
    palette = _palette(cmap)
    rows = _rows(body, w, h, planes, masking == 1, compression == 1, chunky)
    aspect = (xasp, yasp) if xasp and yasp else None
    ham = not chunky and camg & CAMG_HAM and planes in (6, 8)
    if ham:
        return Image(w, h, rgb=_ham(rows, planes, palette), aspect=aspect, camg=camg)
    ncol = 1 << planes
    if not chunky and planes == 6 and (camg & CAMG_EHB or len(palette) <= 32):
        base = (palette + [(0, 0, 0)] * 32)[:32]
        palette = base + [(r // 2, g // 2, b // 2) for r, g, b in base]
    if len(palette) < ncol:
        palette = palette + _grey(ncol)[len(palette):] if not palette else \
            palette + [(0, 0, 0)] * (ncol - len(palette))
    pixels = bytes(v for row in rows for v in row)
    return Image(w, h, palette=palette[:ncol], pixels=pixels, aspect=aspect, camg=camg)


def _palette(cmap):
    if not cmap:
        return []
    n = len(cmap) // 3
    pal = [(cmap[3 * i], cmap[3 * i + 1], cmap[3 * i + 2]) for i in range(n)]
    if pal and all((c & 0x0F) == 0 for rgb in pal for c in rgb):
        pal = [tuple(c | c >> 4 for c in rgb) for rgb in pal]      # 4-bit OCS colours
    return pal


def _grey(n):
    return [(v, v, v) for v in (255 * i // max(1, n - 1) for i in range(n))]


def _rows(body, w, h, planes, mask, packed, chunky):
    """The pixel rows: lists of w values."""
    if chunky:
        row_bytes = w + (w & 1)
        parts = 1
    else:
        row_bytes = ((w + 15) // 16) * 2
        parts = planes + (1 if mask else 0)
    pos = 0
    rows = []
    for _ in range(h):
        if chunky:
            if packed:
                line, pos = unpack_byterun1(body, pos, row_bytes)
            else:
                line = body[pos:pos + row_bytes]
                pos += row_bytes
                if len(line) < row_bytes:
                    raise IFFError("The picture's data is cut short.")
            rows.append(list(line[:w]))
            continue
        row = [0] * (row_bytes * 8)
        for p in range(parts):
            if packed:
                line, pos = unpack_byterun1(body, pos, row_bytes)
            else:
                line = body[pos:pos + row_bytes]
                pos += row_bytes
                if len(line) < row_bytes:
                    raise IFFError("The picture's data is cut short.")
            if p >= planes:
                continue                  # the mask plane
            bit = 1 << p
            x = 0
            for byte in line:
                if byte:
                    for i, v in enumerate(_BITS[byte]):
                        if v:
                            row[x + i] |= bit
                x += 8
        rows.append(row[:w])
    return rows


def _ham(rows, planes, palette):
    """HAM6 / HAM8 rows -> true-colour pixels."""
    pal = (palette + [(0, 0, 0)] * 64)[:64]
    out = []
    if planes == 6:
        shift, mask = 4, 15
        scale = lambda v: v * 17
    else:
        shift, mask = 6, 63
        scale = None
    for row in rows:
        r, g, b = pal[0]
        for v in row:
            mode, val = v >> shift, v & mask
            if mode == 0:
                r, g, b = pal[val]
            elif scale is not None:
                if mode == 1:
                    b = scale(val)
                elif mode == 2:
                    r = scale(val)
                else:
                    g = scale(val)
            else:                         # HAM8: the top 6 bits, the low 2 kept
                if mode == 1:
                    b = (val << 2) | (b & 3)
                elif mode == 2:
                    r = (val << 2) | (r & 3)
                else:
                    g = (val << 2) | (g & 3)
            out.append((r, g, b))
    return out


# ---- writing ----

def pack_byterun1(row):
    """One row packed with ByteRun1."""
    out = bytearray()
    i, n = 0, len(row)
    while i < n:
        j = i
        while j + 1 < n and row[j + 1] == row[i] and j - i < 127:
            j += 1
        if j > i:                         # a run of 2 or more
            out += bytes((257 - (j - i + 1), row[i]))
            i = j + 1
            continue
        j = i                             # literals until a run of 3 starts
        while j < n and j - i < 128:
            if j + 2 < n and row[j] == row[j + 1] == row[j + 2]:
                break
            j += 1
        if j == i:
            j = i + 1
        out.append(j - i - 1)
        out += bytes(row[i:j])
        i = j
    return bytes(out)


def _chunk(cid, body):
    body = bytes(body)
    return cid + struct.pack(">I", len(body)) + body + (b"\0" if len(body) & 1 else b"")


def write_ilbm(img, camg=None):
    """An ILBM of a palette Image, ByteRun1-packed, with as few planes as its colours need."""
    if img.palette is None:
        raise ValueError("write_ilbm needs a palette picture")
    ncol = max(2, len(img.palette), (max(img.pixels) + 1) if img.pixels else 2)
    planes = max(1, (ncol - 1).bit_length())
    w, h = img.w, img.h
    row_bytes = ((w + 15) // 16) * 2
    # a pixel's shape as Deluxe Paint gives it: lores 10:11, hires half as wide, interlaced
    # half as tall
    if img.aspect:
        xasp, yasp = img.aspect
    else:
        xasp, yasp = (5 if w > 400 else 10), 11
        if h > 300:
            xasp *= 2
    bmhd = struct.pack(">HHhhBBBBHBBhh", w, h, 0, 0, planes, 0, 1, 0, 0, xasp, yasp,
                       max(w, 320), max(h, 200))
    pal = list(img.palette) + [(0, 0, 0)] * ((1 << planes) - len(img.palette))
    cmap = bytes(c for rgb in pal[:1 << planes] for c in rgb)
    body = bytearray()
    for y in range(h):
        row = img.pixels[y * w:(y + 1) * w]
        for p in range(planes):
            bit = 1 << p
            line = bytearray(row_bytes)
            for x, v in enumerate(row):
                if v & bit:
                    line[x >> 3] |= 0x80 >> (x & 7)
            body += pack_byterun1(line)
    parts = _chunk(b"BMHD", bmhd) + _chunk(b"CMAP", cmap)
    if camg is None:
        camg = CAMG_HIRES if w > 400 else 0
    parts += _chunk(b"CAMG", struct.pack(">I", camg)) + _chunk(b"BODY", body)
    return b"FORM" + struct.pack(">I", 4 + len(parts)) + b"ILBM" + parts
