"""Write AUTOBOOT.C65: a one-line BASIC 65 program, 10 RUN "NAME", that loads and runs
the main program. build.bat writes it as the disk's first file, so Xemu's -autoload (which
runs the first file) and a real MEGA65 (which runs AUTOBOOT.C65 at power-on) both start
the program, and the program itself is on the disk only once.

  python tools/autoboot.py NAME OUT
"""
import sys

RUN = 0x8A                              # BASIC's RUN token


def autoboot(name):
    text = bytes([RUN]) + b' "' + name.upper().encode('ascii') + b'"'
    line = (10).to_bytes(2, 'little') + text + b'\0'
    start = 0x2001
    link = start + 2 + len(line)        # the next line: the end marker
    return start.to_bytes(2, 'little') + link.to_bytes(2, 'little') + line + b'\0\0'


if __name__ == '__main__':
    open(sys.argv[2], 'wb').write(autoboot(sys.argv[1]))
