import unittest

from meganet.protocol import S, Writer, Reader, Deframer, ProtocolError, clean_text
from meganet.ui import Menu


def frames(d, data):
    return [(t, r.rest()) for t, r in d.push(data)]


class WriterReaderTest(unittest.TestCase):
    def test_layout(self):
        f = Writer().u8(5).u16(0x1234).u32(0xDEADBEEF).str("Hi").frame(S.SET_TEXT)
        self.assertEqual(f, bytes([11, 0, 0x13, 5, 0x34, 0x12, 0xEF, 0xBE, 0xAD, 0xDE, 2]) + b"Hi")
        r = Reader(f[3:])
        self.assertEqual((r.u8(), r.u16(), r.u32(), r.str()), (5, 0x1234, 0xDEADBEEF, "Hi"))

    def test_strings_are_clean_ascii(self):
        self.assertEqual(clean_text("café\n\x01ok"), "caf???ok")
        self.assertEqual(len(clean_text("x" * 300)), 255)
        self.assertEqual(Writer().str(None).parts, bytearray([0]))

    def test_short_message_raises(self):
        with self.assertRaises(ProtocolError):
            Reader(b"\x01").u16()


class DeframerTest(unittest.TestCase):
    def setUp(self):
        self.a = Writer().u8(1).str("alpha").frame(S.APPEND)
        self.b = Writer().u8(2).frame(S.WIN_DONE)
        self.c = Writer().bytes(bytes(range(256)) * 4).frame(S.FILE_DATA)   # a long one

    def test_merged(self):
        got = frames(Deframer(), self.a + self.b + self.c)
        self.assertEqual([t for t, _ in got], [S.APPEND, S.WIN_DONE, S.FILE_DATA])
        self.assertEqual(got[0][1], b"\x01\x05alpha")
        self.assertEqual(got[2][1], bytes(range(256)) * 4)

    def test_split_every_byte(self):
        d = Deframer()
        got = []
        for byte in self.a + self.b + self.c:
            got += frames(d, bytes([byte]))
        self.assertEqual([t for t, _ in got], [S.APPEND, S.WIN_DONE, S.FILE_DATA])
        self.assertEqual(d.buf, bytearray())

    def test_split_mid_header_and_merged_tail(self):
        d = Deframer()
        data = self.a + self.b + self.c
        cut1, cut2 = 1, len(self.a) + 1          # inside a's header, inside b's header
        self.assertEqual(frames(d, data[:cut1]), [])
        self.assertEqual([t for t, _ in frames(d, data[cut1:cut2])], [S.APPEND])
        self.assertEqual([t for t, _ in frames(d, data[cut2:-10])], [S.WIN_DONE])
        self.assertEqual([t for t, _ in frames(d, data[-10:])], [S.FILE_DATA])

    def test_empty_frame_is_an_error(self):
        with self.assertRaises(ProtocolError):
            Deframer().push(b"\x00\x00")


class MenuEncodeTest(unittest.TestCase):
    def test_layout(self):
        m = Menu()
        go = m.title(1, "Go")
        m.item(0x10, go, "Hi")
        m.separator(0x11, go)
        self.assertEqual(m.encode().frame(S.MENU),
                         bytes([16, 0, 0x18, 3, 1, 0, 2]) + b"Go" + bytes([0x10, 1, 2]) + b"Hi"
                         + bytes([0x11, 1, 1]) + b"-")
        self.assertEqual(Menu().encode().frame(S.MENU), bytes([2, 0, 0x18, 0]))   # clears it

    def test_rules(self):
        m = Menu()
        m.title(1, "Go")
        m.item(2, 1, "Item")
        for bad in (lambda: m.title(1, "Again"),          # duplicate id
                    lambda: m.title(0xF0, "Client's"),    # client id range
                    lambda: m.title(0, "Zero"),
                    lambda: m.item(3, 9, "No parent"),
                    lambda: m.item(4, 2, "Parent is an item")):
            with self.assertRaises(ValueError):
                bad()
        self.assertIsNone(m.handle_pick(1), "titles are not picked")
        self.assertIsNone(m.handle_pick(99))


if __name__ == "__main__":
    unittest.main()
