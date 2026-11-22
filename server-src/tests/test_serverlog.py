"""The server log (serverlog.py): rows kept in the database with their area, level, connection
and screen name; Admin > Server Log... (admin.log) to read them; old rows pruned."""

import time
import unittest

from meganet import permissions, serverlog
from meganet.protocol import Kind
from meganet.serverlog import WIN_LOG, INFO, WARNING, ERROR
from tests.test_roles import RolesBase, gadget_of


class AreasTest(unittest.TestCase):
    def test_areas_and_rows(self):
        self.assertEqual(serverlog.area_of("meganet.filelib"), "files")
        self.assertEqual(serverlog.area_of("meganet.games.tictactoe"), "games")
        self.assertEqual(serverlog.area_of("karma"), "karma")
        self.assertEqual(serverlog.area_of("something_new"), "server")
        row = serverlog.log_row({"at": 0, "level": WARNING, "area": "files", "user": "bob",
                                 "session": 3, "conn": 9, "text": "upload failed\nmore"})
        self.assertEqual(row[11:], "!files  bob        upload failed")
        row = serverlog.log_row({"at": 0, "level": INFO, "area": "conn", "user": None,
                                 "session": 3, "conn": 9, "text": "hello"})
        self.assertIn(" #3 ", row, "before sign-on: the session number")


class ServerLogTest(RolesBase):
    def rows(self, **kw):
        return self.server.db.log_entries(**kw)[0]

    def texts(self, **kw):
        return [e["text"] for e in self.rows(**kw)]

    async def open_log(self, c):
        c.windows.pop(WIN_LOG, None)
        c.pick("Server Log...")
        await c.wait_for(lambda: WIN_LOG in c.windows and c.windows[WIN_LOG].done, "log window")
        return c.windows[WIN_LOG]

    def list_rows(self, c):
        w = c.windows[WIN_LOG]
        return [r for r in w.gadgets[gadget_of(w, Kind.LISTBOX)]["rows"] if r is not None]

    async def test_rows_kept_with_who_and_where(self):
        alice_conn = self.session("alice").conn
        self.assertIsNotNone(alice_conn)
        mine = self.rows(conn=alice_conn)
        self.assertTrue(mine[-1]["text"].startswith("connected from"), "the first row")
        self.assertEqual(mine[-1]["conn"], mine[-1]["id"], "the connection's number")
        self.assertTrue(any(e["text"].startswith("signed on as alice (Sysop")
                            and e["area"] == "login" and e["user"] == "alice" for e in mine))
        self.assertFalse(any(e["conn"] == alice_conn for e in self.rows(user="bob")))

        # A wrong password: a warning, before sign-on (no user, but a connection)
        c = await self.client("x")
        c.send_hello()
        await c.wait_for(lambda: c.hello, "HELLO")
        ok, _ = await self.login(c, "alice", "wrong")
        self.assertFalse(ok)
        e = self.rows(min_level=WARNING, area="login")[0]
        self.assertIn("'alice' refused: Wrong screen name or password.", e["text"])
        self.assertIsNone(e["user"])
        self.assertIsNotNone(e["conn"])

        # Something never offered: a warning (karma.suspicious), filed under bob
        self.bob.pick_id(0x36)                  # Admin > Server Log: not in bob's menu
        await self.roundtrip(self.bob)
        e = self.rows(user="bob", min_level=WARNING)[0]
        self.assertEqual((e["area"], e["level"]), ("karma", WARNING))
        self.assertIn("menu pick 54: never sent", e["text"])

    async def test_a_crash_is_an_error_with_its_traceback(self):
        screens = self.server.screens

        def boom(*args, **kw):
            raise RuntimeError("test crash")
        screens._fill_who = boom
        self.alice.pick("Who's Online")
        await self.roundtrip(self.alice)
        e = self.rows(min_level=ERROR)[0]
        self.assertEqual((e["user"], e["area"]), ("alice", "ui"))
        self.assertIn("error handling message", e["text"])
        self.assertIn("RuntimeError: test crash", e["text"])
        self.assertIn("Traceback", e["text"])

    async def test_viewer(self):
        alice, bob = self.alice, self.bob
        self.assertNotIn("Server Log...", bob.menu_items("Help"))
        self.assertTrue(self.session("alice").can(permissions.ADMIN_LOG), "Sysop has it")
        bob.pick_id(0x36)
        await self.roundtrip(bob)
        self.assertNotIn(WIN_LOG, bob.windows)

        w = await self.open_log(alice)
        rows = self.list_rows(alice)
        self.assertTrue(rows, "the newest rows")
        self.assertTrue(any("signed on as bob" in r for r in rows))

        # Show: warnings and errors only
        alice.pick_dropdown(WIN_LOG, gadget_of(w, Kind.DROPDOWN, 1), 1)
        alice.click_text(WIN_LOG, "Search")
        await alice.wait_for(lambda: all(r[11] in "!#" for r in self.list_rows(alice)),
                             "warnings only")
        self.assertTrue(any("never sent" in r for r in self.list_rows(alice)))

        # User: bob (and everything again)
        alice.pick_dropdown(WIN_LOG, gadget_of(w, Kind.DROPDOWN, 1), 0)
        alice.value(WIN_LOG, gadget_of(w, Kind.TEXTBOX, 0), "BOB")
        alice.click_text(WIN_LOG, "Search")
        await alice.wait_for(lambda: self.list_rows(alice) and all(
            r[19:29].strip() == "bob" for r in self.list_rows(alice)), "bob's rows")

        # Pick one: the details pane; Session: all of that connection, sign-on included
        lb = gadget_of(w, Kind.LISTBOX)
        alice.select(WIN_LOG, lb, 0)
        tv = gadget_of(w, Kind.TEXTVIEW)
        await alice.wait_for(lambda: alice.all_lines(WIN_LOG, tv), "details")
        self.assertIn("bob", alice.all_lines(WIN_LOG, tv)[0])
        self.assertTrue(alice.enabled(WIN_LOG, "Session"))
        alice.click_text(WIN_LOG, "Session")
        await alice.wait_for(lambda: any(g["text"] == "All" for g in w.gadgets.values()),
                             "session mode")
        conn = self.session("bob").conn
        self.assertEqual(len(self.list_rows(alice)), len(self.rows(conn=conn)))
        self.assertTrue(any("connected from" in r for r in self.list_rows(alice)))
        alice.click_text(WIN_LOG, "All")
        await alice.wait_for(lambda: any(g["text"] == "Session" for g in w.gadgets.values()),
                             "back to the filters")

    async def test_pages_and_pruning(self):
        log, d = self.server.serverlog, self.server.db
        now = int(time.time())
        for i in range(serverlog.PAGE + 5):
            d.add_log(now, INFO, "server", None, None, None, None, "filler %d" % i)
        old = d.add_log(now - 100 * 86400, INFO, "server", None, None, None, None, "ancient")
        self.assertIn("ancient", self.texts(text="ancient"))
        w = await self.open_log(self.alice)
        # every row of the page reached the client (it never asks for rows: one it wasn't
        # sent shows whatever its memory held, which looked like a corrupted log on a MEGA65)
        rows = w.gadgets[gadget_of(w, Kind.LISTBOX)]["rows"]
        self.assertEqual(len(rows), serverlog.PAGE)
        self.assertNotIn(None, rows)
        self.assertFalse(self.alice.enabled(WIN_LOG, "Newer"))
        self.assertTrue(self.alice.enabled(WIN_LOG, "Older"))
        self.alice.click_text(WIN_LOG, "Older")
        await self.alice.wait_for(lambda: self.alice.enabled(WIN_LOG, "Newer"), "page 2")
        self.assertFalse(self.alice.enabled(WIN_LOG, "Older"))

        self.assertEqual(log.days(), serverlog.LOG_DAYS)
        log.prune()
        self.assertEqual(self.texts(text="ancient"), [], "older than 90 days: gone")
        self.assertTrue(self.texts(text="filler 3"))
        d.add_log(now - 5 * 86400, INFO, "server", None, None, None, None, "last week")
        log.set_days(3)
        self.assertEqual(self.texts(text="last week"), [])
        self.assertEqual(d.setting("log_days"), "3")
        self.assertNotEqual(old, None)


if __name__ == "__main__":
    unittest.main()
