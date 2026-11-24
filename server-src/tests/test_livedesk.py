"""The live desktop (livedesk.py): the ticker, who's online, and the icons' badges."""

import time

from meganet import livedesk
from meganet.account import WIN_ACCOUNT
from meganet.protocol import ONLINE_DOT, BADGE_DOT, TICKER_MAX, MENU_MY_ACCOUNT, Kind
from tests.test_roles import gadget_of
from tests.test_server import ServerTest


class LiveDeskTest(ServerTest):
    def session_of(self, name):
        return next(s for s in self.server.sessions if s.user == name)

    async def test_ticker_line_and_who(self):
        a = await self.signed_on("alice")
        b = await self.signed_on("bob")
        await a.wait_for(lambda: a.ticker and "bob signed on" in a.ticker, "bob in the ticker")
        await a.wait_for(lambda: a.desk_line == "Online now: %salice %sbob" % (ONLINE_DOT,
                                                                                ONLINE_DOT),
                         "the online line")
        await a.wait_for(lambda: a.badge("Who's Online") == "2", "who's online: 2")
        self.assertIn("alice signed on", b.ticker)

        # an event only some may see: only they get it
        live = self.server.screens.live
        live.say("for bob only", can=lambda v: v.user == "bob")
        await b.wait_for(lambda: "for bob only" in b.ticker, "bob's event")
        live.say("for everyone")
        await a.wait_for(lambda: "for everyone" in a.ticker, "everyone's event")
        self.assertNotIn("for bob only", a.ticker)

        # bob goes: the line and the count follow
        await b.close()
        await a.wait_for(lambda: a.desk_line == "Online now: %salice" % ONLINE_DOT, "bob gone")
        await a.wait_for(lambda: a.badge("Who's Online") == "1", "who's online: 1")

    async def test_ticker_keeps_the_newest_that_fit(self):
        a = await self.signed_on("alice")
        live = self.server.screens.live
        for i in range(20):
            live.say("event number %02d %s" % (i, "x" * 30))
        await a.wait_for(lambda: a.ticker and "event number 19" in a.ticker, "the newest")
        self.assertLessEqual(len(a.ticker), TICKER_MAX)
        self.assertNotIn("event number 00", a.ticker)

    async def test_board_badge(self):
        a = await self.signed_on("alice")
        await self.signed_on("bob")
        db = self.server.db
        alice = self.session_of("alice")
        alice.previous_login = int(time.time()) - 3600       # (signed on before)
        forum = db.forums()[0]["id"]
        topic = db.create_topic(forum, db.user("bob")["id"], "Hello", ["hi"])
        live = self.server.screens.live
        live.update_all()
        await a.wait_for(lambda: a.badge("Message Boards") == "1", "1 new post")
        for _ in range(10):
            db.add_post(topic, db.user("bob")["id"], ["more"])
        live.update_all()
        await a.wait_for(lambda: a.badge("Message Boards") == "10+", "over 9: 10+")
        db.add_post(topic, db.user("alice")["id"], ["mine"])   # (her own don't count)
        live.update_all()
        await a.wait_for(lambda: a.badge("Message Boards") == "10+", "still 10+")
        a.desk_open("Message Boards")                         # looking: nothing new now
        await a.wait_window("Message Boards")
        await a.wait_for(lambda: a.badge("Message Boards") == "", "the badge gone")

    async def test_chat_dot(self):
        a = await self.signed_on("alice")
        b = await self.signed_on("bob")
        self.assertEqual(a.badge("Chat"), "")
        await b.enter_room("Lobby")
        self.server.screens.live.update_all()
        await a.wait_for(lambda: a.badge("Chat") == BADGE_DOT, "people chatting")

    async def test_ticker_off_in_my_account(self):
        a = await self.signed_on("alice")
        await a.wait_for(lambda: a.ticker and "alice signed on" in a.ticker, "the ticker")
        a.pick_id(MENU_MY_ACCOUNT)
        acc = await a.wait_window("My Account")
        box = acc.find("Activity ticker")
        self.assertEqual(acc.gadgets[box].get("value"), 1, "on by default")
        a.select(WIN_ACCOUNT, box, 0)
        for i, name in enumerate(("Alice", "Smith")):        # (required to save)
            a.value(WIN_ACCOUNT, gadget_of(acc, Kind.TEXTBOX, i), name)
        a.click_text(WIN_ACCOUNT, "OK")
        await a.wait_for(lambda: a.ticker == "", "the ticker gone")
        self.assertEqual(self.server.db.user("alice")["show_ticker"], 0)
        self.server.screens.live.say("something new")          # (none while it's off)
        await self.signed_on("bob")
        await a.wait_for(lambda: a.badge("Who's Online") == "2", "bob on")
        self.assertEqual(a.ticker, "")
        a.pick_id(MENU_MY_ACCOUNT)                              # on again: it's back
        acc = await a.wait_window("My Account")
        a.select(WIN_ACCOUNT, acc.find("Activity ticker"), 1)
        a.click_text(WIN_ACCOUNT, "OK")
        await a.wait_for(lambda: a.ticker and "something new" in a.ticker, "the ticker back")

    def test_count_text(self):
        self.assertEqual([livedesk.count_text(n) for n in (0, 1, 9, 10, 250)],
                         ["", "1", "9", "10+", "10+"])
