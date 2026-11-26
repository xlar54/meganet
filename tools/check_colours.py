"""Build check for skins (build.bat runs it before assembling).

The GUI toolkit's drawing code must take text, box insides and the other skinned colours
from the skin (gs+GS_INK, gs+GS_PAPER, ...: lib/gui/README.md, "Skins"), not load black,
white or light grey directly: Classic hides the mistake, Dark shows black text on charcoal.

So in client-src/lib/gui/gui.asm, an instruction with #GC_BLACK, #GC_WHITE or #GC_LIGHT
fails the build unless its comment says "(fixed colour)" or "(fixed colour: why)": for colours that
really are the same in every skin (the mouse pointer, the envelope icon, the desktop's
labels, code only the Pinstripe skin runs). Data (.byte tables) isn't checked.

    python tools/check_colours.py          exit 1 and list the lines if any are wrong
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [os.path.join(ROOT, "client-src", "lib", "gui", "gui.asm")]
FIXED = re.compile(r"#\s*GC_(BLACK|WHITE|LIGHT)\b")
MARK = "(fixed colour"                  # "(fixed colour)" or "(fixed colour: why)"


def check(path):
    bad = []
    with open(path, encoding="latin-1") as f:
        for n, line in enumerate(f, 1):
            code, _, comment = line.partition(";")
            if code.strip().startswith(".") or not FIXED.search(code):
                continue
            if MARK not in comment:
                bad.append((n, line.rstrip()))
    return bad


def main():
    problems = 0
    for path in FILES:
        for n, line in check(path):
            problems += 1
            print("%s:%d: a fixed colour in skinned drawing code (use gs+GS_INK / GS_PAPER /"
                  " ..., or mark it \"(fixed colour: why)\"):\n    %s"
                  % (os.path.relpath(path, ROOT), n, line.strip()))
    if problems:
        print("check_colours: %d line(s) to fix" % problems)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
