"""Cut a 64tass --flat output down to one section: keep the bytes from OFFSET on.

  python tools/cut.py FILE OFFSET

build.bat assembles every overlay at its own physical address ($100000, $110000, ...),
and --flat writes from address 0, so this keeps only the overlay itself.
"""
import sys

path, offset = sys.argv[1], int(sys.argv[2], 0)
data = open(path, 'rb').read()
if len(data) <= offset:
    sys.exit('%s: only %d bytes, nothing after offset $%x' % (path, len(data), offset))
open(path, 'wb').write(data[offset:])
