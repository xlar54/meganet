"""sidcheck.py: reading PSID files, and the 6502 check that keeps tunes the MEGA65 client
couldn't run safely out of the SID libraries. Tunes are assembled here, a rule each; real
tunes are checked too when private/sid/ has some (they aren't ours to publish)."""

import glob
import os
import struct
import unittest

from meganet import sidcheck
from meganet.sidcheck import TuneError, parse, check

HERE = os.path.dirname(os.path.abspath(__file__))
REAL = sorted(glob.glob(os.path.join(HERE, "..", "..", "private", "sid", "*.sid")))


def psid(code, load=0x1000, init=None, play=None, songs=1, magic=b"PSID", speed=0,
         name=b"Test", flags=0x14, version=2):
    """A PSID v2 file: `code` at `load` (init = load, play = load + 3 by default)."""
    head = struct.pack(">4sHHHHHHHI", magic, version, 0x7C, load,
                       load if init is None else init,
                       load + 3 if play is None else play, songs, 1, speed)
    text = b"".join(s.ljust(32, b"\0") for s in (name, b"Someone", b"2026"))
    tail = struct.pack(">HBBBB", flags, 0, 0, 0, 0)
    return head + text + tail + bytes(code)


RTS = [0x60]
# init: rts; play: sta $d418 / rts  (a well-behaved tune)
GOOD = [0x60, 0xEA, 0xEA, 0x8D, 0x18, 0xD4, 0x60]


def play(*body):
    """init: rts; play: `body`, then rts."""
    return [0x60, 0xEA, 0xEA] + list(body) + [0x60]


class ParseTest(unittest.TestCase):
    def test_header(self):
        p = parse(psid(GOOD, songs=3, speed=0b010))
        self.assertEqual((p.load, p.init, p.play, p.songs, p.start), (0x1000, 0x1000, 0x1003,
                                                                       3, 1))
        self.assertEqual(p.speeds, ["vbi", "cia", "vbi"])
        self.assertEqual((p.name, p.author, p.released), ("Test", "Someone", "2026"))
        self.assertEqual((p.clock, p.model), ("PAL", "6581"))
        self.assertEqual(p.data, bytes(GOOD))

    def test_load_address_in_the_data(self):
        p = parse(psid([0x00, 0x20] + GOOD, load=0, init=0x2000, play=0x2003))
        self.assertEqual((p.load, p.data), (0x2000, bytes(GOOD)))

    def test_refused(self):
        for data, why in [
                (psid(GOOD, magic=b"RSID"), "RSID"),
                (b"hello" * 40, "Not a SID tune"),
                (psid(GOOD, play=0), "no play routine"),
                (psid(GOOD, load=0xC000, init=0xC000, play=0xC003), "$C000-$DFFF"),
                (psid(GOOD, load=0xBFFE), "$C000-$DFFF"),         # (runs into it)
                (psid(GOOD, load=0x0100, init=0x100, play=0x103), "zero page and stack"),
                (psid(GOOD, flags=0x15), "MUS")]:
            with self.assertRaises(TuneError, msg=why) as e:
                parse(data)
            self.assertIn(why, str(e.exception))

    def test_high_memory_is_fine(self):
        p = parse(psid(GOOD, load=0xE000))
        check(p, plays=10)


class CheckTest(unittest.TestCase):
    def refused(self, code, why, **kw):
        with self.assertRaises(TuneError) as e:
            check(parse(psid(code, **kw)), plays=20)
        self.assertIn(why, str(e.exception))

    def test_a_good_tune_passes(self):
        check(parse(psid(GOOD)), plays=50)
        # $01 may be set (as tunes do), even left at 0 after a call: it's set afresh for
        # every call, as a PSID player does
        check(parse(psid(play(0x8D, 0x18, 0xD4, 0xA9, 0x00, 0x85, 0x01))), plays=5)

    def test_undocumented_opcodes(self):
        self.refused(play(0xA7, 0x10), "opcode $A7")        # LAX zp
        self.refused(play(0x5C, 0x00, 0x00), "opcode $5C")  # (MAP on the 45GS02)

    def test_interrupts(self):
        self.refused(play(0x58), "CLI")
        self.refused(play(0x08, 0x68, 0x29, 0xFB, 0x48, 0x28), "PLP")   # I cleared by PLP
        self.refused(play(0x00, 0x00), "BRK")

    def test_memory_it_may_not_touch(self):
        self.refused(play(0x8D, 0x00, 0xC8), "$C800, which is the MegaNet client's")
        self.refused(play(0xAD, 0x00, 0xC0), "reads $C000")
        self.refused(play(0x8D, 0x11, 0xD0), "I/O register $D011")
        self.refused(play(0x85, 0x00), "writes $00")
        # with the I/O switched out by $01, $D400 is RAM
        self.refused(play(0xA9, 0x34, 0x85, 0x01, 0x8D, 0x00, 0xD4), "switched out")
        # CIA timers are allowed (the client turns their interrupts off again)
        check(parse(psid(play(0x8D, 0x04, 0xDC, 0x8D, 0x0D, 0xDC))), plays=5)
        # and the time-of-day clocks (a tune timing itself: the client doesn't use them)
        check(parse(psid(play(0x8D, 0x0B, 0xDC, 0x8D, 0x08, 0xDC, 0x8D, 0x0B, 0xDD))),
              plays=5)
        self.refused(play(0x8D, 0x00, 0xDC), "I/O register $DC00")    # (the keyboard's)

    def test_stuck(self):
        self.refused(play(0x4C, 0x03, 0x10), "didn't return")    # jmp to itself
        self.refused([0x4C, 0x00, 0x10] + [0x60] * 4, "init routine didn't return",
                     play=0x1004)

    def test_too_long_to_check(self):
        """A tune that takes longer than the time allowed to check is refused (a 256-song
        tune, or one made to be slow, can't hold the checker for ever)."""
        with self.assertRaises(TuneError) as e:
            check(parse(psid(GOOD, songs=256)), plays=0, seconds=0)
        self.assertIn("too long to check", str(e.exception))
        self.assertIsNone(sidcheck.problem(psid(GOOD)))
        self.assertIn("RSID", sidcheck.problem(psid(GOOD, magic=b"RSID")))

    def test_jmp_indirect_page_wrap(self):
        self.refused(play(0x6C, 0xFF, 0x20), "differently")

    def test_each_song_is_checked(self):
        # song 2's init (A = 1) branches to a CLI
        code = [0xC9, 0x01, 0xD0, 0x01, 0x58, 0x60, 0x60]
        with self.assertRaises(TuneError) as e:
            check(parse(psid(code, songs=2, play=0x1006)), plays=10)
        self.assertIn("song 2", str(e.exception))

    def test_decimal_mode(self):
        cpu = sidcheck.Cpu(parse(psid(GOOD)), None)
        cpu.d, cpu.c, cpu.a = 1, 0, 0x19
        cpu.mem[0x10] = 0x28
        cpu.op_adc("zp", 0x10)
        self.assertEqual((cpu.a, cpu.c), (0x47, 0))
        cpu.c, cpu.a = 1, 0x50
        cpu.op_sbc("zp", 0x10)
        self.assertEqual((cpu.a, cpu.c), (0x22, 1))


@unittest.skipUnless(REAL, "no tunes in private/sid/")
class RealTunesTest(unittest.TestCase):
    def test_they_pass(self):
        for path in REAL:
            with self.subTest(os.path.basename(path)), open(path, "rb") as f:
                check(parse(f.read()), plays=500)


if __name__ == "__main__":
    unittest.main()
