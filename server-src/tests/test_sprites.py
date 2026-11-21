"""The server's sprites (session.sprite_show / sprite_move / sprite_off / fly; S.SPRITE ...):
what goes to the client, the steps of a move, and older clients getting nothing."""

from meganet.protocol import Caps, SPRITES
from meganet.ui import Window
from tests.test_server import ServerTest

GRID_SPRITES = Caps.GRID | Caps.SPRITES


class SpriteTest(ServerTest):
    async def session_for(self, name, caps):
        c = await self.signed_on(name, caps=caps)
        s = next(x for x in self.server.sessions if x.user == name)
        win = Window("Board", 100, 40, 200, 100)
        win.show(s)
        await c.wait_window("Board")
        return c, s, win

    async def test_show_move_and_off(self):
        c, s, win = await self.session_for("alice", GRID_SPRITES)
        self.assertTrue(s.sprite_show(1, win, 3, 0x1234, 12, 20, (10, 30), [254, 251, 2],
                                      stride=64))
        await c.wait_for(lambda: 1 in c.sprites, "shown")
        sp = c.sprites[1]
        self.assertEqual((sp["slot"], sp["offset"], sp["w"], sp["h"], sp["stride"],
                          sp["step"], sp["x"], sp["y"]), (3, 0x1234, 12, 20, 64, 1, 10, 30))
        self.assertEqual(sp["colours"], [(254, (20, 20, 20)), (251, (200, 40, 40)),
                                         (2, (192, 192, 192))])
        # a move that stays: it ends where asked, to the pixel, and the sprite is still there
        s.sprite_move(1, (10, 30), (210, 3), 7)
        await c.wait_for(lambda: c.flights, "moved")
        self.assertEqual((c.flights[-1]["end"], c.flights[-1]["hide"]), ((210, 3), 0))
        self.assertEqual((c.sprites[1]["x"], c.sprites[1]["y"]), (210, 3))
        s.sprite_off(1)
        await c.wait_for(lambda: 1 not in c.sprites, "gone")
        # fly: shown, moved and gone (every second byte of 32-wide art)
        s.fly(win, 8, 704, 16, 22, (0, 0), (100, 50), 14, [254], step=2)
        await c.wait_for(lambda: len(c.flights) == 2, "flown")
        f = c.flights[-1]
        self.assertEqual((f["w"], f["step"], f["stride"], f["end"], f["hide"]),
                         (16, 2, 32, (100, 50), 1))
        self.assertNotIn(0, c.sprites)

    async def test_limits(self):
        c, s, win = await self.session_for("alice", GRID_SPRITES)
        for bad in (dict(n=SPRITES), dict(w=17), dict(h=65), dict(colours=list(range(16)))):
            args = dict(n=0, w=16, h=22, colours=[254])
            args.update(bad)
            with self.assertRaises(ValueError, msg=bad):
                s.sprite_show(args["n"], win, 8, 0, args["w"], args["h"], (0, 0),
                              args["colours"])

    async def test_older_clients_get_nothing(self):
        c, s, win = await self.session_for("bob", Caps.GRID)
        self.assertFalse(s.sprite_show(0, win, 8, 0, 16, 22, (0, 0), [254]))
        self.assertFalse(s.fly(win, 8, 0, 16, 22, (0, 0), (9, 9), 10, [254]))
        s.sprite_off()
        await c.wait_window("Board")
        self.assertEqual((c.sprites, c.flights), ({}, []))
