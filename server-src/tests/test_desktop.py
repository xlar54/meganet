"""Desktop icons (desktop.py): sent at sign-on to those who may use them, opened by a double
click (C.DESK_OPEN), following permission changes."""

from meganet import desktop
from meganet.desktop import WIN_LOADING
from meganet.chat import WIN_ROOM
from meganet.protocol import C, Writer
from tests.test_pages import PagesBase


class DesktopTest(PagesBase):
    async def test_icons_open_and_follow_permissions(self):
        bob = self.bob
        await bob.wait_for(lambda: len(bob.desk) == 7, "icons")
        # "One moment..." (modal, no close box, a progress bar) while they come, then the
        # welcome window
        await bob.wait_window("Welcome, bob")
        ev = [e for e in bob.events if e[0] != "open" or e[1] in ("One moment...", "Welcome, bob")]
        self.assertEqual(ev[:10], [("open", "One moment..."), ("icon", 0), ("icon", 1),
                                  ("icon", 2), ("icon", 8), ("icon", 9), ("icon", 10),
                                  ("icon", 11),
                                  ("close", "One moment..."), ("open", "Welcome, bob")])
        self.assertNotIn(WIN_LOADING, bob.windows)
        # a New User has no files.download: no File Library. On the right (slots 8 up):
        # Who's Online, News, Voting, Bank
        self.assertEqual(bob.desk_labels(), ["Chat", "Message Boards", "Games",
                                             "Who's Online", "News", "Voting", "Bank"])
        self.assertEqual(sorted(bob.desk), [0, 1, 2, 8, 9, 10, 11])
        self.assertEqual(bob.desk[1][:2], ("Message", "Boards"))      # two lines
        bob.desk_open("Who's Online")
        await bob.wait_window("Who's Online")
        bob.desk_open("News")
        await bob.wait_window("News")
        bob.desk_open("Voting")
        await bob.wait_window("Voting")
        bob.desk_open("Bank")
        await bob.wait_window("Bank")
        await bob.enter_room("Lobby", via=lambda: bob.desk_open("Chat"))   # (the list first)
        self.assertIn(WIN_ROOM, bob.windows)
        bob.desk_open("Message Boards")
        await bob.wait_window("Message Boards")
        bob.desk_open("Games")
        await bob.wait_window("Games")
        # no chat.use: the Chat icon goes and Message Boards moves up
        d = self.server.db
        rid = d.user("bob")["role_id"]
        self.assertIsNone(d.set_role_permissions(rid, d.role_permissions(rid) - {"chat.use"}))
        self.server.permissions_changed(role_id=rid)
        await bob.wait_for(lambda: bob.desk_labels() == ["Message Boards", "Games",
                                                         "Who's Online", "News", "Voting",
                                                         "Bank"],
                           "chat gone")
        self.assertEqual(sorted(bob.desk), [0, 1, 8, 9, 10, 11])        # (the right ones stay put)
        # a slot with no icon: ignored (and suspicious)
        before = self.session("bob").suspicious
        bob.send(C.DESK_OPEN, Writer().u8(5))
        await self.roundtrip(bob)
        self.assertEqual(self.session("bob").suspicious, before + 1)

    def test_pictures_and_labels(self):
        for name in desktop.ICONS:
            self.assertEqual(len(desktop.pixels(name)), 32 * 16)
        self.assertEqual(desktop.label_lines("Chat"), ("Chat", ""))
        self.assertEqual(desktop.label_lines("Message Boards"), ("Message", "Boards"))
        self.assertEqual(desktop.label_lines("Supercalifragilistic"), ("Supercalif", "ragilistic"))

    async def test_files_icon_for_members(self):
        alice = self.alice                                  # Sysop: every icon
        await alice.wait_for(lambda: len(alice.desk) == 8, "icons")
        self.assertEqual(alice.desk_labels(), ["Chat", "Message Boards", "File Library", "Games",
                                               "Who's Online", "News", "Voting", "Bank"])
        self.assertEqual(alice.desk[2][:2], ("File", "Library"))
        alice.desk_open("File Library")
        await alice.wait_window("File Library")
