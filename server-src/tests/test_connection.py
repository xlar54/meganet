"""Client connections: TCP keepalive (dead connections are dropped), and a connection the
network gives up on ("No route to host") ends like any other, without an unhandled exception."""

import asyncio
import socket
import unittest.mock

from meganet import session as sessmod
from tests.test_server import ServerTest


class ConnectionTest(ServerTest):
    def session_of(self, name):
        return next(s for s in self.server.sessions if s.user == name)

    async def test_keepalive_on_client_sockets(self):
        await self.signed_on("bob")
        sock = self.session_of("bob").writer.get_extra_info("socket")
        self.assertEqual(sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE), 1)
        if hasattr(socket, "TCP_KEEPIDLE"):              # (Linux, and Windows' newer Pythons)
            try:
                idle = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE)
            except OSError:
                return
            self.assertEqual(idle, sessmod.KEEPALIVE_IDLE)

    async def test_drained_to_waits_for_the_client(self):
        """unsent() counts what's queued for the client (asyncio's buffer, and on Linux the
        kernel's queue too); drained_to() waits until it's small, or the connection goes."""
        await self.signed_on("bob")
        s = self.session_of("bob")
        self.assertGreaterEqual(s.unsent(), 0)
        with unittest.mock.patch.object(type(s), "unsent", lambda self: 10_000):
            waiting = asyncio.ensure_future(s.drained_to(4096))
            await asyncio.sleep(0.1)
            self.assertFalse(waiting.done(), "too much unsent: it waits")
            s.closed = True
            await asyncio.wait_for(waiting, 1)       # the connection went: it stops waiting
        s.closed = False
        await asyncio.wait_for(s.drained_to(1 << 30), 1)

    async def test_network_error_ends_the_session_quietly(self):
        loop = asyncio.get_running_loop()
        unhandled = []
        loop.set_exception_handler(lambda lp, ctx: unhandled.append(ctx))
        await self.signed_on("bob")
        alice = await self.signed_on("alice")
        s = self.session_of("bob")
        s.reader.set_exception(OSError(113, "No route to host"))
        for _ in range(50):                              # (the read wakes up and fails)
            await asyncio.sleep(0.01)
            if s not in self.server.sessions:
                break
        self.assertNotIn(s, self.server.sessions)        # signed off: bob may sign on again
        self.assertEqual(unhandled, [])
        rows = self.server.db.log_entries(text="connection lost")[0]
        self.assertTrue(any("No route to host" in r["text"] for r in rows))
        self.assertTrue(self.server.db.log_entries(text="disconnected after")[0])
        self.assertIn(self.session_of("alice"), self.server.sessions)    # the others go on

    async def test_signing_on_again_takes_over_the_old_session(self):
        """A MEGA65 switched off without signing off leaves its session open: signing on
        again (the right password) closes that one and goes ahead."""
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda lp, ctx: None)      # (the old socket's reset)
        await self.signed_on("bob")
        old = self.session_of("bob")
        c = await self.client("bob again")
        c.send_hello(100, 0)
        await c.wait_for(lambda: c.hello, "HELLO")
        ok, msg = await self.login(c, "bob", "wrong")          # the wrong password: no
        self.assertFalse(ok)
        self.assertIn(old, self.server.sessions, "the old one is untouched")
        ok, msg = await self.login(c, "bob", "secret")
        self.assertTrue(ok, msg)
        self.assertEqual(msg, "Welcome back, bob.")
        self.assertTrue(old.closed and old.gone.is_set())
        self.assertNotIn(old, self.server.sessions)
        new = self.server.find_user("bob")
        self.assertIsNotNone(new)
        self.assertIsNot(new, old)
        self.assertEqual(sum(1 for s in self.server.sessions if s.user == "bob"), 1)
        await c.wait_window("Welcome")
        rows = self.server.db.log_entries(text="signed on again")[0]
        self.assertTrue(rows, "logged")
