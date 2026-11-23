"""MegaNet > System Stats (stats.py): the menu item under the client's own MegaNet menu, and
the report: counts for today, 7 and 30 days, the most active members, the top lists."""

import time

from meganet import stats
from meganet.protocol import MEGANET_MENU, Kind
from tests.test_server import ServerTest


def lines_of(win):
    return next(g["lines"] for g in win.gadgets.values() if g["kind"] == Kind.TEXTVIEW)


class StatsTest(ServerTest):
    async def test_menu_and_report(self):
        a = await self.signed_on("alice")
        b = await self.signed_on("bob")
        db = self.server.db
        ids = {n: db.user(n)["id"] for n in ("alice", "bob")}
        # some activity: board posts, a file downloaded, a game won, log lines
        forum = db.conn.execute("INSERT INTO forums (name, created) VALUES ('Stats Test', ?)",
                                (int(time.time()),)).lastrowid
        topic = db.conn.execute("INSERT INTO topics (forum_id, subject, author, created, "
                                "last_post) VALUES (?, 'Hi', ?, ?, ?)",
                                (forum, ids["bob"], int(time.time()), int(time.time()))).lastrowid
        for _ in range(3):
            db.conn.execute("INSERT INTO posts (topic_id, author, posted, body) VALUES "
                            "(?, ?, ?, 'x')", (topic, ids["bob"], int(time.time())))
        lib = db.create_library("Games", "games")
        db.conn.execute("INSERT INTO library_files (library_id, name, type, path, size, added, "
                        "downloads) VALUES (?, 'MEGA DEMO', 'PRG', 'd.prg', 10, ?, 7)",
                        (lib, int(time.time())))
        db.add_credits(ids["alice"], 5, "game won")
        db.conn.commit()
        for _ in range(4):
            self.server.sessions and next(s for s in self.server.sessions
                                          if s.user == "bob").log("did something", area="chat")

        self.assertIn("System Stats", a.menu_items("MegaNet"))
        self.assertTrue(any(p == MEGANET_MENU and l == "System Stats" for _, p, l in a.menu))
        a.pick("System Stats")
        win = await a.wait_window("System Stats")
        text = "\n".join(lines_of(win))
        self.assertIn("Members 2, on now 2", text)
        row = next(l for l in lines_of(win) if l.startswith("Sign-ons"))
        self.assertEqual(row.split()[1:], ["2", "2", "2"], row)
        self.assertIn("Board posts", text)
        self.assertIn(next(l for l in lines_of(win) if l.startswith("Board posts")).split()[2],
                      "3")
        self.assertIn("Most active, 7 days: bob", text)
        self.assertIn("Most posts, 30 days: bob 3", text)
        self.assertIn("Most games won, 30 days: alice 1", text)
        self.assertIn("Most downloaded files: MEGA DEMO 7", text)
        self.assertIn("Most played tunes: nobody yet", text)
        self.assertTrue(all(len(l) <= stats.COLS for l in lines_of(win)))

        # A second pick brings the same window up to date (no second window)
        n = sum(1 for w in a.windows.values() if w.title == "System Stats")
        b.pick("System Stats")
        await b.wait_window("System Stats")
        a.pick("System Stats")
        await self.roundtrip(a)
        self.assertEqual(sum(1 for w in a.windows.values() if w.title == "System Stats"), n)

    async def roundtrip(self, c):
        n = len(c.messages)
        c.pick("Who's Online")
        await c.wait_for(lambda: len(c.messages) > n, "roundtrip")
