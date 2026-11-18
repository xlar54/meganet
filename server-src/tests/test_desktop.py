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
        await bob.wait_for(lambda: len(bob.desk) == 3, "icons")
        # "One moment..." (modal, no close box, a progress bar) while they come, then the
        # welcome window
        await bob.wait_window("Welcome, bob")
        ev = [e for e in bob.events if e[0] != "open" or e[1] in ("One moment...", "Welcome, bob")]
        self.assertEqual(ev[:6], [("open", "One moment..."), ("icon", 0), ("icon", 1),
                                  ("icon", 2), ("close", "One moment..."),
                                  ("open", "Welcome, bob")])
        self.assertNotIn(WIN_LOADING, bob.windows)
        # a New User has no files.download: no File Library
        self.assertEqual(bob.desk_labels(), ["Chat", "Message Boards", "Games"])
        self.assertEqual(bob.desk[1][:2], ("Message", "Boards"))      # two lines
        bob.desk_open("Chat")
        await bob.wait_window("Lobby")
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
        await bob.wait_for(lambda: bob.desk_labels() == ["Message Boards", "Games"],
                           "chat gone")
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
        await alice.wait_for(lambda: len(alice.desk) == 4, "icons")
        self.assertEqual(alice.desk_labels(), ["Chat", "Message Boards", "File Library", "Games"])
        self.assertEqual(alice.desk[2][:2], ("File", "Library"))
        alice.alerts.clear()
        alice.desk_open("File Library")
        await alice.wait_for(lambda: alice.alerts, "coming soon")
        self.assertEqual(alice.alerts[-1], ("File Library", "Coming soon."))
