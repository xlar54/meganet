"""Reading a file out of a D81 disk image (the 1581's format): the client's own disk, for the
VERSION file build.bat puts on it (updates.py).

A D81 is 80 tracks of 40 sectors of 256 bytes; track t sector s is at ((t - 1) * 40 + s) * 256.
The directory starts at track 40 sector 3: 8 entries of 32 bytes a sector (type, the first
track / sector, a 16-character name padded with $A0), sectors chained by their first two
bytes; a file's sectors likewise (next track 0: the second byte is the last byte used).
"""

D81_SIZES = (819200, 822400)             # (822400: with error bytes)
TRACKS, SECTORS = 80, 40


def _sector(img, t, s):
    if not (1 <= t <= TRACKS and 0 <= s < SECTORS):
        raise ValueError("track %d sector %d isn't on a D81" % (t, s))
    off = ((t - 1) * SECTORS + s) * 256
    return img[off:off + 256]


def _name(raw):
    return bytes(raw).rstrip(b"\xa0").decode("latin-1").upper()


def files(img):
    """[(name, type byte, first track, first sector)] for the directory's files."""
    if len(img) not in D81_SIZES:
        raise ValueError("not a D81 image (%d bytes)" % len(img))
    out, seen = [], set()
    t, s = 40, 3
    while t and (t, s) not in seen:
        seen.add((t, s))
        sec = _sector(img, t, s)
        for i in range(8):
            e = sec[i * 32:i * 32 + 32]
            if e[2] & 0x07:                  # (0: deleted / unused)
                out.append((_name(e[5:21]), e[2], e[3], e[4]))
        t, s = sec[0], sec[1]
    return out


def read(img, name):
    """The bytes of file `name` (any case), or None if the disk has none."""
    entry = next((f for f in files(img) if f[0] == name.upper()), None)
    if entry is None:
        return None
    data, seen = bytearray(), set()
    t, s = entry[2], entry[3]
    while t and (t, s) not in seen:
        seen.add((t, s))
        sec = _sector(img, t, s)
        if sec[0]:
            data += sec[2:]
        else:
            data += sec[2:sec[1] + 1]
        t, s = sec[0], sec[1]
    return bytes(data)
