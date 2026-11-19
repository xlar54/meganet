"""End-to-end tests: a real server on a random port, fake clients over real TCP."""

import json
import os
import tempfile
import unittest
import zlib

from meganet import db
from meganet.protocol import S
from meganet.server import Server
from meganet.screens import WIN_WELCOME, WIN_LOBBY
from meganet.games.lobby import WIN_GAMES
from tests.fakeclient import FakeClient

db.PBKDF2_ITERATIONS = 1000          # keep the tests quick


class ServerTest(unittest.IsolatedAsyncioTestCase):
    updates_dir = None                   # a folder without manifest.json: updates off

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = Server(":memory:", self.updates_dir or self.tmp.name)
        self.port = await self.server.start("127.0.0.1", 0)
        self.clients = []

    async def asyncTearDown(self):
        for c in self.clients:
            await c.close()
        await self.server.stop()
        self.tmp.cleanup()

    async def client(self, name):
        c = FakeClient(name)
        await c.connect(self.port)
        self.clients.append(c)
        return c

    async def login(self, c, name, password, new=False):
        n = len(c.login_results)
        c.send_login(name, password, new)
        await c.wait_for(lambda: len(c.login_results) > n, "LOGIN_RESULT")
        return c.login_results[-1]

    async def signed_on(self, name, password="secret", build=100, caps=0):
        """A client that has said HELLO, created an account and has the menu bar and the
        welcome window."""
        c = await self.client(name)
        c.send_hello(build, caps)
        await c.wait_for(lambda: c.hello, "HELLO")
        ok, msg = await self.login(c, name, password, new=True)
        self.assertTrue(ok, msg)
        await c.wait_window("Welcome")
        return c


class SignOnTest(ServerTest):
    async def test_ping_pong(self):
        """C.PING gets S.PONG, signed on or not (the client's connectivity check)."""
        from meganet.protocol import S, C
        c = await self.client("pinger")
        c.send(C.PING)
        await c.wait_for(lambda: S.PONG in c.messages, "PONG before HELLO")
        c.send_hello()
        await c.wait_for(lambda: c.hello, "HELLO")
        c.send(C.PING)
        await c.wait_for(lambda: c.messages.count(S.PONG) == 2, "PONG again")

    async def test_hello_then_login(self):
        c = await self.client("alice")
        c.send_hello()
        await c.wait_for(lambda: c.hello, "HELLO")
        self.assertEqual(c.hello[0], 1)
        self.assertEqual(c.windows, {}, "no sign-on window from the server any more")

        ok, msg = await self.login(c, "Alice", "secret", new=True)
        self.assertTrue(ok, msg)
        welcome = await c.wait_window("Welcome, Alice")
        self.assertEqual(welcome.id, WIN_WELCOME)
        self.assertEqual(c.menus_received, 1, "the menu bar came with the sign-on")
        self.assertEqual(c.menu_items("Areas"), ["News", "Message Boards", "Chat Rooms",
                                                 "Private Messages", "Art Gallery", "SID Music",
                                                 "File Library", "Games", "Voting"])
        self.assertLess(c.messages.index(S.MENU), c.messages.index(S.WIN_OPEN))
        await c.close()

        # A second connection: wrong password, then the right one in another case.
        c2 = await self.client("alice2")
        c2.send_hello()
        ok, msg = await self.login(c2, "alice", "wrong")
        self.assertFalse(ok)
        self.assertNotIn(WIN_WELCOME, c2.windows)
        self.assertEqual(c2.menu, [], "no menu before sign-on")
        ok, msg = await self.login(c2, "ALICE", "secret")
        self.assertTrue(ok, msg)
        await c2.wait_window("Welcome, Alice")       # the name as it was first typed

    async def test_new_user_rules(self):
        await self.signed_on("Bob")
        c = await self.client("x")
        c.send_hello()
        self.assertEqual((await self.login(c, "bob", "pass1", new=True))[0], False)  # taken
        self.assertEqual((await self.login(c, "ab", "pass1", new=True))[0], False)   # short
        self.assertEqual((await self.login(c, "a!b", "pass1", new=True))[0], False)  # chars
        self.assertEqual((await self.login(c, "x" * 11, "pass1", new=True))[0], False)
        ok, msg = await self.login(c, "Carol 64", "pass1", new=True)
        self.assertTrue(ok, msg)

    async def test_login_before_hello_fails(self):
        c = await self.client("x")
        ok, _ = await self.login(c, "Dave", "pass1", new=True)
        self.assertFalse(ok)

    async def test_already_signed_on(self):
        await self.signed_on("Erin")
        c = await self.client("x")
        c.send_hello()
        ok, msg = await self.login(c, "erin", "secret")
        self.assertFalse(ok)
        self.assertIn("already", msg)


class ChatTest(ServerTest):
    async def test_two_clients_chat(self):
        a = await self.signed_on("alice")
        b = await self.signed_on("bob")
        for c in (a, b):
            await c.enter_room("Lobby")
        lobby = a.windows[WIN_LOBBY]
        kinds = {g["kind"]: gid for gid, g in lobby.gadgets.items()}
        view, people, entry = kinds[8], kinds[5], kinds[3]       # TEXTVIEW, LISTBOX, TEXTBOX
        await a.wait_for(lambda: a.windows[WIN_LOBBY].gadgets[people]["rows"] == ["alice", "bob"],
                         "both in the user list")

        a.value(WIN_LOBBY, entry, "hello bob")
        a.click_text(WIN_LOBBY, "Send")
        for c in (a, b):
            await c.wait_for(lambda c=c: "alice: hello bob" in c.all_lines(WIN_LOBBY, view),
                             "the chat line")
        self.assertEqual(a.windows[WIN_LOBBY].text(entry), "", "entry cleared for the sender")

        b.close_box(WIN_LOBBY)
        await a.wait_for(lambda: a.windows[WIN_LOBBY].gadgets[people]["rows"] == ["alice"],
                         "bob gone from the list")
        self.assertIn("* bob has left the room", a.all_lines(WIN_LOBBY, view))


class TicTacToeTest(ServerTest):
    async def test_play_to_a_win(self):
        a = await self.signed_on("alice")
        b = await self.signed_on("bob")
        for c in (a, b):
            c.pick("Games")
            games = await c.wait_window("Games")
            listbox = next(gid for gid, g in games.gadgets.items() if g["kind"] == 5)
            await c.wait_for(lambda: games.gadgets[listbox]["rows"], "game rows")
            row = next(i for i, r in enumerate(games.gadgets[listbox]["rows"])
                       if r.startswith("Tic-Tac-Toe"))
            c.select(WIN_GAMES, listbox, row)
            c.click_text(WIN_GAMES, "Join")
        wa = await a.wait_window("Tic-Tac-Toe")
        wb = await b.wait_window("Tic-Tac-Toe")
        self.assertNotIn(WIN_GAMES, a.windows)
        self.assertEqual(wa.text(10), "Your turn (X)")          # alice joined first: X
        self.assertEqual(wb.text(10), "alice's turn (X)")

        # X takes the top row; O plays the middle row. Bob also tries an out-of-turn move.
        b.click(wb.id, 5)
        moves = [(a, wa, 1), (b, wb, 4), (a, wa, 2), (b, wb, 5), (a, wa, 3)]
        for i, (c, w, cell) in enumerate(moves):
            c.click(w.id, cell)
            mark = "XO"[i % 2]
            await a.wait_for(lambda cell=cell, mark=mark: wa.text(cell) == mark,
                             "cell %d = %s" % (cell, mark))
        await a.wait_for(lambda: wa.text(10) == "You win!", "alice wins")
        await b.wait_for(lambda: wb.text(10) == "alice wins.", "bob sees it")
        self.assertEqual([wb.text(g) for g in range(1, 10)],
                         ["X", "X", "X", "O", "O", " ", " ", " ", " "])

        # Rematch: marks swap, so bob is X and starts.
        a.click_text(wa.id, "Rematch")
        await b.wait_for(lambda: wb.text(10) == "alice wants a rematch.", "rematch request")
        b.click_text(wb.id, "Rematch")
        await b.wait_for(lambda: wb.text(10) == "Your turn (X)", "new round")
        self.assertEqual(wa.text(1), " ")

        # Quit: both windows close, the other player is told.
        a.click_text(wa.id, "Quit")
        await b.wait_for(lambda: wb.id not in b.windows, "bob's window closed")
        await b.wait_for(lambda: ("Tic-Tac-Toe", "alice left the game.") in b.alerts, "alert")
        self.assertNotIn(wa.id, a.windows)
        self.assertEqual(self.server.games.running, [])


class UpdateTest(ServerTest):
    async def asyncSetUp(self):
        self.upd = tempfile.TemporaryDirectory()
        self.data = bytes(range(256)) * 9                       # 2304 bytes: three chunks
        with open(os.path.join(self.upd.name, "CLIENT"), "wb") as f:
            f.write(self.data)
        with open(os.path.join(self.upd.name, "manifest.json"), "w") as f:
            json.dump({"build": 200, "message": "New client", "files": ["CLIENT"]}, f)
        self.updates_dir = self.upd.name
        await super().asyncSetUp()

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.upd.cleanup()

    async def test_old_client_is_updated(self):
        c = await self.client("old")
        c.send_hello(build=100)
        await c.wait_for(lambda: c.files and c.files[-1][3] is not None, "the whole file")
        self.assertEqual(c.update, (200, 1, "New client"))
        name, size, data, crc = c.files[0]
        self.assertEqual((name, size, bytes(data), crc),
                         ("CLIENT", len(self.data), self.data, zlib.crc32(self.data)))
        ok, _ = await self.login(c, "Frank", "pass1", new=True)
        self.assertFalse(ok, "no sign-on until updated")

    async def test_new_client_is_not(self):
        c = await self.signed_on("Gina", build=200)
        self.assertIsNone(c.update)


if __name__ == "__main__":
    unittest.main()
