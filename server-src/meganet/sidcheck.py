"""SID tunes: reading a PSID file, and checking that the MEGA65 client can play it safely.

The client plays a tune by running its C64 machine code (sidplay.asm): init once, then play
50 times a second (60 for CIA-timed songs), with the tune's own 56 KB mapped in where a C64
would have it: $0000-$BFFF and $E000-$FFFF are the tune's, $C000-$CFFF stays the client's,
and $D000-$DFFF is the I/O. The client's CPU is a 45GS02, not a 6510: the 6502's
undocumented opcodes are other instructions there (MAP, a 16-bit stack...), so a tune that
used one could crash the client, not just sound wrong.

So before a tune goes in a SID library, check() runs it here in a 6502 (legal opcodes only)
for each song, init and then a couple of minutes of play calls, and refuses it if it ever:
  - runs an undocumented opcode, BRK, RTI, CLI, or JMP ($xxFF) (the 65CE02 doesn't wrap);
  - writes outside its own memory and the SIDs ($D400-$D43F, the client's "right" SIDs), the
    CIA timers (the client turns their interrupts off again after each call) and the CIAs'
    time-of-day clocks (some tunes time themselves with it; the client doesn't use it);
  - writes $00 (on the MEGA65, the CPU speed), or touches $C000-$CFFF;
  - writes $D000-$DFFF while its $01 has the I/O switched out (that's RAM then, not a SID).
    ($01 itself it may set, as many tunes do: the client puts it back after each call.)
  - takes too long to return (a stuck loop would freeze the client).
It can't prove a tune safe for ever (a path it didn't take might be taken later in the
song), but a tune that passes behaves like an ordinary PSID.

    psid = parse(data)        -> Psid, or raises TuneError (not a PSID we can play)
    check(psid)               -> None, or raises TuneError (with the reason)
    problem(data)             -> None, or why not (parse and check: what a process pool runs,
                                 so a slow check doesn't hold up the server: sidlib.py)
A check gives up after CHECK_SECS (a tune with many songs, or one made to be slow).
"""

import random
import struct
import time
from collections import namedtuple

SID_LO, SID_HI = 0xD400, 0xD43F          # the client's two right SIDs (a 2SID tune's second)
CIA_OK = set(range(0xDC04, 0xDC0C)) | set(range(0xDD04, 0xDD0C)) | {   # timers, TOD clocks
    0xDC0D, 0xDC0E, 0xDC0F, 0xDD0D, 0xDD0E, 0xDD0F}
SHARED_LO, SHARED_HI = 0xC000, 0xDFFF     # the client's ($C000-$CFFF) and the I/O
MAX_SIZE = 0xC000 - 0x0200 + 0x2000       # what a tune may fill: $0200-$BFFF, $E000-$FFFF
INIT_CYCLES = 3000000                     # init may decrunch: a few seconds on a C64
PLAY_CYCLES = 40000                       # a play call: two C64 frames (a frame is 19,656)
CHECK_PLAYS = 6000                        # play calls checked, shared between the songs
MIN_PLAYS = 200                           # (at least this many a song)
CHECK_SECS = 30.0                         # the most one tune's check may take, all its songs
NAME_MAX = 32


class TuneError(Exception):
    """Why a file isn't a tune the client can play."""


Psid = namedtuple("Psid", "version load init play songs start speeds name author released "
                          "clock model data")
# speeds: one per song, "vbi" (the frame: 50 Hz) or "cia" (a CIA timer: 60 Hz)
# clock: "PAL", "NTSC", "PAL/NTSC" or "?"; model: "6581", "8580", "either" or "?"


def _text(b):
    return b.split(b"\0", 1)[0].decode("latin-1").strip()


def parse(data):
    """A PSID file's header and its C64 data. TuneError if it isn't one we can play."""
    if len(data) < 0x76:
        raise TuneError("Too short to be a SID tune.")
    magic = data[:4]
    if magic == b"RSID":
        raise TuneError("An RSID tune: it needs a whole C64 (its own interrupts), which the "
                        "player can't give it.")
    if magic != b"PSID":
        raise TuneError("Not a SID tune (a PSID file).")
    version, offset, load, init, play, songs, start, speed = struct.unpack(
        ">HHHHHHHI", data[4:22])
    if version not in (1, 2, 3, 4) or offset not in (0x76, 0x7C):
        raise TuneError("A PSID version this player doesn't know (%d)." % version)
    flags = struct.unpack(">H", data[0x76:0x78])[0] if version >= 2 and len(data) >= 0x78 else 0
    if version >= 3 and len(data) >= 0x7C and (data[0x7A] or data[0x7B]):
        second = 0xD000 | data[0x7A] << 4
        if not SID_LO <= second <= SID_HI - 0x1F or data[0x7B]:
            raise TuneError("It needs more SID chips than the player has.")
    if flags & 1:
        raise TuneError("A MUS (Compute's Sidplayer) tune: not a program the player can run.")
    body = data[offset:]
    if load == 0:
        if len(body) < 2:
            raise TuneError("No C64 data in the file.")
        load, body = body[0] | body[1] << 8, body[2:]
    if not body:
        raise TuneError("No C64 data in the file.")
    end = load + len(body) - 1
    if end > 0xFFFF:
        raise TuneError("Its data runs past the end of memory.")
    if load < 0x0200:
        raise TuneError("It loads at $%04X, over the zero page and stack." % load)
    if not (end < SHARED_LO or load > SHARED_HI):
        raise TuneError("It loads at $%04X-$%04X: the player can't give it $C000-$DFFF "
                        "(the MegaNet client and the I/O are there)." % (load, end))
    if init == 0:
        init = load
    if play == 0:
        raise TuneError("It has no play routine (it sets up its own interrupt), which the "
                        "player can't run.")
    for what, a in (("init", init), ("play", play)):
        if SHARED_LO <= a <= SHARED_HI:
            raise TuneError("Its %s routine is at $%04X, where the player can't put it." % (
                what, a))
    if not 1 <= songs <= 256:
        raise TuneError("It says it has %d songs." % songs)
    start = start if 1 <= start <= songs else 1
    speeds = ["cia" if speed >> min(i, 31) & 1 else "vbi" for i in range(songs)]
    clock = ["?", "PAL", "NTSC", "PAL/NTSC"][flags >> 2 & 3]
    model = ["?", "6581", "8580", "either"][flags >> 4 & 3]
    return Psid(version, load, init, play, songs, start, speeds, _text(data[22:54])[:NAME_MAX],
                _text(data[54:86])[:NAME_MAX], _text(data[86:118])[:NAME_MAX], clock, model,
                bytes(body))


def problem(data):
    """None if `data` is a PSID the client can play safely; else why not."""
    try:
        check(parse(data))
    except TuneError as e:
        return str(e)
    return None


def check(psid, plays=CHECK_PLAYS, rng=None, seconds=CHECK_SECS):
    """Run each song (init, then play calls) in the 6502; TuneError if it does anything the
    client couldn't survive, or if checking it takes more than `seconds`."""
    per_song = max(MIN_PLAYS, plays // psid.songs)
    deadline = time.monotonic() + seconds
    for song in range(psid.songs):
        cpu = Cpu(psid, rng or random.Random(song), deadline)
        where = "song %d" % (song + 1) if psid.songs > 1 else "the tune"
        try:
            cpu.call(psid.init, song, INIT_CYCLES, "init")
            for _ in range(per_song):
                cpu.call(psid.play, 0, PLAY_CYCLES, "play")
        except TuneError as e:
            raise TuneError("%s (%s)" % (e, where)) from None


# ---- the 6502 ----

class Cpu:
    """A 6502 with the legal opcodes only, its memory the tune's, and the MEGA65 client's
    rules on what it may touch (see the module's docstring)."""

    RETURN = 0xFFFF            # (call() pushes RETURN-1: a final RTS lands here)
    CLOCK_EVERY = 20000        # instructions between looks at the clock

    def __init__(self, psid, rng, deadline=None):
        self.deadline = deadline
        self.mem = bytearray(0x10000)
        self.mem[psid.load:psid.load + len(psid.data)] = psid.data
        self.rng = rng
        self.a = self.x = self.y = 0
        self.sp = 0xFF
        self.c = self.z = self.i = self.d = self.v = self.n = 0
        self.raster = 0
        self.port = 0x35                    # $01: the client's (I/O in, the ROMs out)

    def io_in(self):
        """$01 shows the I/O at $D000 (CHAREN set, and not all RAM)."""
        return bool(self.port & 4) and bool(self.port & 3)

    # memory, with the rules
    def rd(self, a):
        if SHARED_LO <= a <= SHARED_HI:
            if a < 0xD000:
                raise TuneError("It reads $%04X, which is the MegaNet client's memory." % a)
            return self.io_read(a) if self.io_in() else 0
        if a < 2:
            return self.port if a else 0x2F
        return self.mem[a]

    def io_read(self, a):
        if a in (0xD41B, 0xD41C, 0xD43B, 0xD43C):     # the third oscillator / envelope
            return self.rng.randrange(256)
        if a == 0xD012:
            self.raster = (self.raster + 1) & 0xFF
            return self.raster
        if a in (0xDC04, 0xDC05, 0xDC06, 0xDC07, 0xDD04, 0xDD05, 0xDD06, 0xDD07):
            return self.rng.randrange(256)
        return 0

    def wr(self, a, v):
        if a == 1:                          # (the client restores $01 after each call)
            self.port = v
            return
        if a == 0:
            raise TuneError("It writes $00: on the MEGA65 that sets the CPU speed.")
        if SHARED_LO <= a <= SHARED_HI:
            if a < 0xD000:
                raise TuneError("It writes $%04X, which is the MegaNet client's memory." % a)
            if not self.io_in():
                raise TuneError("It writes $%04X with the I/O switched out by its $01: that's "
                                "RAM the player can't give it." % a)
            if SID_LO <= a <= SID_HI or a in CIA_OK:
                return
            raise TuneError("It writes I/O register $%04X (only the SID is allowed)." % a)
        self.mem[a] = v

    def rd16(self, a):
        return self.rd(a) | self.rd((a + 1) & 0xFFFF) << 8

    def push(self, v):
        self.mem[0x100 | self.sp] = v
        self.sp = (self.sp - 1) & 0xFF

    def pull(self):
        self.sp = (self.sp + 1) & 0xFF
        return self.mem[0x100 | self.sp]

    def flags(self, b=0x20):
        return (self.n << 7 | self.v << 6 | b | self.d << 3 | self.i << 2 | self.z << 1
                | self.c)

    def set_flags(self, p):
        self.n, self.v, self.d = p >> 7 & 1, p >> 6 & 1, p >> 3 & 1
        self.i, self.z, self.c = p >> 2 & 1, p >> 1 & 1, p & 1

    def nz(self, v):
        self.z = int(v == 0)
        self.n = v >> 7
        return v

    def call(self, addr, a, budget, what):
        """JSR addr with A = a (the song, for init); run until it returns. (Interrupts are
        off, and $01 set afresh, as in the client's call: as a PSID player does, so a tune
        may leave $01 anything between calls.)"""
        self.a, self.x, self.y = a, 0, 0
        self.i = 1
        self.port = 0x35
        self.push((self.RETURN - 1) >> 8)
        self.push((self.RETURN - 1) & 0xFF)
        self.pc = addr
        cycles = steps = 0
        while self.pc != self.RETURN:
            cycles += self.step()
            if cycles > budget:
                raise TuneError("Its %s routine didn't return in %d cycles (stuck?)." % (
                    what, budget))
            steps += 1
            if steps % self.CLOCK_EVERY == 0:
                self.time_up()
        self.time_up()

    def time_up(self):
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise TuneError("It takes too long to check (over %d seconds): too many songs, "
                            "or too slow." % CHECK_SECS)

    # one instruction; returns its cycles (roughly: 2 + memory accesses)
    def step(self):
        pc = self.pc
        op = self.mem[pc] if not SHARED_LO <= pc <= SHARED_HI else self.rd(pc)
        entry = OPS.get(op)
        if entry is None:
            raise TuneError("It runs opcode $%02X at $%04X: undocumented on the 6502, and "
                            "another instruction on the MEGA65's CPU." % (op, pc))
        name, mode = entry
        self.pc = (pc + 1 + MODE_LEN[mode]) & 0xFFFF
        addr = self.address(mode, pc)
        getattr(self, "op_" + name)(mode, addr)
        return 2 + MODE_LEN[mode]

    def address(self, mode, pc):
        m = self.mem
        if mode in ("imp", "acc"):
            return None
        b1 = m[(pc + 1) & 0xFFFF]
        if mode == "imm":
            return (pc + 1) & 0xFFFF
        if mode == "zp":
            return b1
        if mode == "zpx":
            return (b1 + self.x) & 0xFF
        if mode == "zpy":
            return (b1 + self.y) & 0xFF
        if mode == "rel":
            return (pc + 2 + (b1 - 256 if b1 > 127 else b1)) & 0xFFFF
        w = b1 | m[(pc + 2) & 0xFFFF] << 8
        if mode == "abs":
            return w
        if mode == "abx":
            return (w + self.x) & 0xFFFF
        if mode == "aby":
            return (w + self.y) & 0xFFFF
        if mode == "ind":
            if w & 0xFF == 0xFF:
                raise TuneError("It jumps through a vector at $%04X: the 6502 and the "
                                "MEGA65's CPU read that one differently." % w)
            return self.rd16(w)
        if mode == "izx":
            p = (b1 + self.x) & 0xFF
            return m[p] | m[(p + 1) & 0xFF] << 8
        if mode == "izy":
            return ((m[b1] | m[(b1 + 1) & 0xFF] << 8) + self.y) & 0xFFFF
        raise AssertionError(mode)

    def val(self, mode, addr):
        return self.a if mode == "acc" else self.rd(addr)

    def put(self, mode, addr, v):
        if mode == "acc":
            self.a = v
        else:
            self.wr(addr, v)

    # loads and stores
    def op_lda(self, m, a): self.a = self.nz(self.rd(a))
    def op_ldx(self, m, a): self.x = self.nz(self.rd(a))
    def op_ldy(self, m, a): self.y = self.nz(self.rd(a))
    def op_sta(self, m, a): self.wr(a, self.a)
    def op_stx(self, m, a): self.wr(a, self.x)
    def op_sty(self, m, a): self.wr(a, self.y)
    def op_tax(self, m, a): self.x = self.nz(self.a)
    def op_tay(self, m, a): self.y = self.nz(self.a)
    def op_txa(self, m, a): self.a = self.nz(self.x)
    def op_tya(self, m, a): self.a = self.nz(self.y)
    def op_tsx(self, m, a): self.x = self.nz(self.sp)
    def op_txs(self, m, a): self.sp = self.x
    def op_pha(self, m, a): self.push(self.a)
    def op_php(self, m, a): self.push(self.flags(0x30))
    def op_pla(self, m, a): self.a = self.nz(self.pull())
    def op_plp(self, m, a):
        i = self.i
        self.set_flags(self.pull())
        if i and not self.i:
            raise TuneError("It turns interrupts on (PLP), which the player can't allow.")

    # arithmetic
    def op_adc(self, m, a):
        v = self.rd(a)
        if self.d:
            lo = (self.a & 15) + (v & 15) + self.c
            hi = (self.a >> 4) + (v >> 4) + (lo > 9)
            lo = lo - 10 if lo > 9 else lo
            self.z = int(((self.a + v + self.c) & 0xFF) == 0)
            self.n = hi >> 3 & 1
            self.v = int(not ((self.a ^ v) & 0x80) and bool((self.a ^ (hi << 4)) & 0x80))
            self.c = int(hi > 9)
            hi = hi - 10 if hi > 9 else hi
            self.a = (hi << 4 | lo) & 0xFF
            return
        r = self.a + v + self.c
        self.v = int(not ((self.a ^ v) & 0x80) and bool((self.a ^ r) & 0x80))
        self.c = int(r > 0xFF)
        self.a = self.nz(r & 0xFF)

    def op_sbc(self, m, a):
        v = self.rd(a)
        r = self.a - v - (1 - self.c)
        self.v = int(bool((self.a ^ v) & 0x80) and bool((self.a ^ r) & 0x80))
        if self.d:
            lo = (self.a & 15) - (v & 15) - (1 - self.c)
            hi = (self.a >> 4) - (v >> 4) - (lo < 0)
            lo = lo + 10 if lo < 0 else lo
            hi = hi + 10 if hi < 0 else hi
            self.c = int(r >= 0)
            self.nz(r & 0xFF)
            self.a = (hi << 4 | lo) & 0xFF
            return
        self.c = int(r >= 0)
        self.a = self.nz(r & 0xFF)

    def compare(self, reg, a):
        r = reg - self.rd(a)
        self.c = int(r >= 0)
        self.nz(r & 0xFF)

    def op_cmp(self, m, a): self.compare(self.a, a)
    def op_cpx(self, m, a): self.compare(self.x, a)
    def op_cpy(self, m, a): self.compare(self.y, a)
    def op_and(self, m, a): self.a = self.nz(self.a & self.rd(a))
    def op_ora(self, m, a): self.a = self.nz(self.a | self.rd(a))
    def op_eor(self, m, a): self.a = self.nz(self.a ^ self.rd(a))

    def op_bit(self, m, a):
        v = self.rd(a)
        self.z = int(self.a & v == 0)
        self.n, self.v = v >> 7, v >> 6 & 1

    def op_inc(self, m, a): self.wr(a, self.nz((self.rd(a) + 1) & 0xFF))
    def op_dec(self, m, a): self.wr(a, self.nz((self.rd(a) - 1) & 0xFF))
    def op_inx(self, m, a): self.x = self.nz((self.x + 1) & 0xFF)
    def op_iny(self, m, a): self.y = self.nz((self.y + 1) & 0xFF)
    def op_dex(self, m, a): self.x = self.nz((self.x - 1) & 0xFF)
    def op_dey(self, m, a): self.y = self.nz((self.y - 1) & 0xFF)

    def op_asl(self, m, a):
        v = self.val(m, a)
        self.c = v >> 7
        self.put(m, a, self.nz(v << 1 & 0xFF))

    def op_lsr(self, m, a):
        v = self.val(m, a)
        self.c = v & 1
        self.put(m, a, self.nz(v >> 1))

    def op_rol(self, m, a):
        v = self.val(m, a)
        r = (v << 1 | self.c) & 0xFF
        self.c = v >> 7
        self.put(m, a, self.nz(r))

    def op_ror(self, m, a):
        v = self.val(m, a)
        r = v >> 1 | self.c << 7
        self.c = v & 1
        self.put(m, a, self.nz(r))

    # flow
    def op_jmp(self, m, a): self.pc = a

    def op_jsr(self, m, a):
        ret = (self.pc - 1) & 0xFFFF
        self.push(ret >> 8)
        self.push(ret & 0xFF)
        self.pc = a

    def op_rts(self, m, a):
        lo = self.pull()
        self.pc = ((self.pull() << 8 | lo) + 1) & 0xFFFF

    def op_rti(self, m, a):
        raise TuneError("It runs RTI: it expects to be called from an interrupt.")

    def op_brk(self, m, a):
        raise TuneError("It runs BRK at $%04X." % ((self.pc - 2) & 0xFFFF))

    def branch(self, cond, a):
        if cond:
            self.pc = a

    def op_bpl(self, m, a): self.branch(not self.n, a)
    def op_bmi(self, m, a): self.branch(self.n, a)
    def op_bvc(self, m, a): self.branch(not self.v, a)
    def op_bvs(self, m, a): self.branch(self.v, a)
    def op_bcc(self, m, a): self.branch(not self.c, a)
    def op_bcs(self, m, a): self.branch(self.c, a)
    def op_bne(self, m, a): self.branch(not self.z, a)
    def op_beq(self, m, a): self.branch(self.z, a)

    # flags
    def op_clc(self, m, a): self.c = 0
    def op_sec(self, m, a): self.c = 1
    def op_cld(self, m, a): self.d = 0
    def op_sed(self, m, a): self.d = 1
    def op_clv(self, m, a): self.v = 0
    def op_sei(self, m, a): self.i = 1
    def op_nop(self, m, a): pass

    def op_cli(self, m, a):
        raise TuneError("It turns interrupts on (CLI), which the player can't allow.")


MODE_LEN = {"imp": 0, "acc": 0, "imm": 1, "zp": 1, "zpx": 1, "zpy": 1, "rel": 1, "izx": 1,
            "izy": 1, "abs": 2, "abx": 2, "aby": 2, "ind": 2}


def _ops():
    """The 151 legal 6502 opcodes: opcode -> (mnemonic, addressing mode)."""
    t = {}
    groups = {
        "ora": (0x01, "izx zp imm abs izy zpx aby abx"),
        "and": (0x21, "izx zp imm abs izy zpx aby abx"),
        "eor": (0x41, "izx zp imm abs izy zpx aby abx"),
        "adc": (0x61, "izx zp imm abs izy zpx aby abx"),
        "sta": (0x81, "izx zp - abs izy zpx aby abx"),
        "lda": (0xA1, "izx zp imm abs izy zpx aby abx"),
        "cmp": (0xC1, "izx zp imm abs izy zpx aby abx"),
        "sbc": (0xE1, "izx zp imm abs izy zpx aby abx"),
    }
    offs = [0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C]
    for name, (base, modes) in groups.items():
        for off, mode in zip(offs, modes.split()):
            if mode != "-":
                t[base + off] = (name, mode)
    shifts = {"asl": 0x02, "rol": 0x22, "lsr": 0x42, "ror": 0x62}
    for name, base in shifts.items():
        t[base + 0x04] = (name, "zp")
        t[base + 0x08] = (name, "acc")
        t[base + 0x0C] = (name, "abs")
        t[base + 0x14] = (name, "zpx")
        t[base + 0x1C] = (name, "abx")
    for name, base in {"inc": 0xE2, "dec": 0xC2}.items():
        t[base + 0x04] = (name, "zp")
        t[base + 0x0C] = (name, "abs")
        t[base + 0x14] = (name, "zpx")
        t[base + 0x1C] = (name, "abx")
    t.update({
        0x86: ("stx", "zp"), 0x8E: ("stx", "abs"), 0x96: ("stx", "zpy"),
        0x84: ("sty", "zp"), 0x8C: ("sty", "abs"), 0x94: ("sty", "zpx"),
        0xA2: ("ldx", "imm"), 0xA6: ("ldx", "zp"), 0xAE: ("ldx", "abs"), 0xB6: ("ldx", "zpy"),
        0xBE: ("ldx", "aby"),
        0xA0: ("ldy", "imm"), 0xA4: ("ldy", "zp"), 0xAC: ("ldy", "abs"), 0xB4: ("ldy", "zpx"),
        0xBC: ("ldy", "abx"),
        0xE0: ("cpx", "imm"), 0xE4: ("cpx", "zp"), 0xEC: ("cpx", "abs"),
        0xC0: ("cpy", "imm"), 0xC4: ("cpy", "zp"), 0xCC: ("cpy", "abs"),
        0x24: ("bit", "zp"), 0x2C: ("bit", "abs"),
        0x4C: ("jmp", "abs"), 0x6C: ("jmp", "ind"), 0x20: ("jsr", "abs"),
        0x60: ("rts", "imp"), 0x40: ("rti", "imp"), 0x00: ("brk", "imp"),
        0x10: ("bpl", "rel"), 0x30: ("bmi", "rel"), 0x50: ("bvc", "rel"), 0x70: ("bvs", "rel"),
        0x90: ("bcc", "rel"), 0xB0: ("bcs", "rel"), 0xD0: ("bne", "rel"), 0xF0: ("beq", "rel"),
        0x18: ("clc", "imp"), 0x38: ("sec", "imp"), 0x58: ("cli", "imp"), 0x78: ("sei", "imp"),
        0xB8: ("clv", "imp"), 0xD8: ("cld", "imp"), 0xF8: ("sed", "imp"),
        0xAA: ("tax", "imp"), 0x8A: ("txa", "imp"), 0xA8: ("tay", "imp"), 0x98: ("tya", "imp"),
        0xBA: ("tsx", "imp"), 0x9A: ("txs", "imp"),
        0x48: ("pha", "imp"), 0x68: ("pla", "imp"), 0x08: ("php", "imp"), 0x28: ("plp", "imp"),
        0xE8: ("inx", "imp"), 0xC8: ("iny", "imp"), 0xCA: ("dex", "imp"), 0x88: ("dey", "imp"),
        0xEA: ("nop", "imp"),
    })
    assert len(t) == 151, len(t)
    return t


OPS = _ops()
