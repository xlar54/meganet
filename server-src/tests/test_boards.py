"""Areas > Message Boards: forums > topics > posts, "new" since the previous sign-on,
moderator controls (new, rename, delete, lock, per-role access), and the server enforcing it."""

from meganet.boards import WIN_BOARDS, WIN_POST, WIN_ACCESS, WIN_DELETE
from meganet.protocol import Kind
from tests.test_pages import PagesBase
from tests.test_roles import gadget_of, has_text, status_of


class BoardsTest(PagesBase):
    def win(self, c):
        return c.windows.get(WIN_BOARDS)

    def rows(self, c):
        w = self.win(c)
        return w.gadgets[gadget_of(w, Kind.LISTBOX)]["rows"] if w and w.done else []

    async def shown(self, c, text):
        """Wait for the Message Boards window to be drawn with a gadget showing `text`."""
        await c.wait_for(lambda: has_text(c, WIN_BOARDS, text), "boards showing %r" % text)
        return self.win(c)

    async def open_boards(self, c):
        c.windows.pop(WIN_BOARDS, None)
        c.pick("Message Boards")
        return await self.shown(c, "Open")

    async def pick(self, c, start, double=False):
        await c.wait_for(lambda: any(r.lstrip("* ").startswith(start) for r in self.rows(c)),
                         "a row %r" % start)
        w = self.win(c)
        i = next(i for i, r in enumerate(self.rows(c)) if r.lstrip("* ").startswith(start))
        c.select(WIN_BOARDS, gadget_of(w, Kind.LISTBOX), i, double)

    async def open_forum(self, c, name):
        await self.pick(c, name)
        c.windows[WIN_BOARDS].done = False                # wait for the re-sent window
        c.click_text(WIN_BOARDS, "Open")
        return await self.shown(c, "Back")

    async def post(self, c, button, subject, lines):
        c.click_text(WIN_BOARDS, button + "...")           # (it opens the composer)
        comp = await c.wait_window("New Topic" if button == "New Topic" else "Reply")
        if subject is not None:
            c.value(WIN_POST, gadget_of(comp, Kind.TEXTBOX), subject)
        c.text(WIN_POST, gadget_of(comp, Kind.EDIT), lines)
        c.windows[WIN_BOARDS].done = False
        c.click_text(WIN_POST, "Send")
        await c.wait_for(lambda: WIN_POST not in c.windows, "composer closed")
        return await self.shown(c, "Posted.")

    def make_member(self, name):
        d = self.server.db
        self.assertIsNone(d.set_user_role(d.user(name)["id"], d.role_by_name("Member")["id"]))
        self.server.permissions_changed(user_id=d.user(name)["id"])

    async def test_read_post_reply_new(self):
        alice, bob, d = self.alice, self.bob, self.server.db
        w = await self.open_boards(bob)
        self.assertTrue(self.rows(bob)[0].startswith("General"), self.rows(bob))
        for mod_only in ("New", "Rename", "Delete", "Lock", "Access..."):
            self.assertFalse(any(g["text"] == mod_only for g in w.gadgets.values()), mod_only)
        # bob (New User) may read but not post: no New Topic button, and a forged click fails
        w = await self.open_forum(bob, "General")
        w.find("No topics yet.")
        self.assertFalse(any(g["text"] == "New Topic..." for g in w.gadgets.values()))
        self.server.screens.boards.compose(self.session("bob"), d.forums()[0]["id"])
        await bob.wait_for(lambda: ("Message Boards", "You can't post in this forum.")
                           in bob.alerts, "refused")

        # alice starts a topic; bob's open forum shows it at once
        await self.open_boards(alice)
        await self.open_forum(alice, "General")
        w = await self.post(alice, "New Topic", "Hello all", ["First post!"])
        self.assertIn("First post!", w.gadgets[gadget_of(w, Kind.TEXTVIEW)]["lines"])
        await bob.wait_for(lambda: any("Hello all" in r for r in self.rows(bob)), "bob sees it")
        row = next(r for r in self.rows(bob) if "Hello all" in r)
        self.assertTrue(row.startswith("* "), "new to bob: " + row)   # (first sign-on: all new)

        # bob becomes a Member and replies
        self.make_member("bob")
        await bob.wait_for(lambda: has_text(bob, WIN_BOARDS, "New Topic..."), "New Topic for bob")
        await self.pick(bob, "Hello all")
        bob.windows[WIN_BOARDS].done = False
        bob.click_text(WIN_BOARDS, "Read")
        await self.shown(bob, "Reply...")
        await self.post(bob, "Reply", None, ["Hi alice"])
        posts = d.posts(d.topics(d.forums()[0]["id"])[0]["id"])
        self.assertEqual([(p["author_name"], p["body"]) for p in posts],
                         [("alice", "First post!"), ("bob", "Hi alice")])

        # "new" is since the previous sign-on: after a sign-on later than the posts, none
        await self.sign_off(bob)
        d.conn.execute("UPDATE posts SET posted = posted - 100")
        d.conn.execute("UPDATE topics SET last_post = last_post - 100")
        d.conn.commit()
        bob = await self.sign_in("bob")                 # previous login: the one above
        self.assertGreater(self.session("bob").previous_login, posts[-1]["posted"] - 100)
        await self.open_boards(bob)
        self.assertNotIn("new", self.rows(bob)[0])
        self.assertTrue(any(g["text"].endswith(": 0 new posts.")
                            for g in self.win(bob).gadgets.values()))

    async def test_moderator_controls(self):
        alice, bob, d = self.alice, self.bob, self.server.db
        await self.open_boards(bob)
        w = await self.open_boards(alice)
        name = gadget_of(w, Kind.TEXTBOX)
        # New forum
        alice.value(WIN_BOARDS, name, "Sysops")
        alice.click_text(WIN_BOARDS, "New")
        await self.shown(alice, "Made Sysops.")
        await bob.wait_for(lambda: any(r.startswith("Sysops") for r in self.rows(bob)), "bob")
        alice.value(WIN_BOARDS, gadget_of(self.win(alice), Kind.TEXTBOX), "general")
        alice.click_text(WIN_BOARDS, "New")
        await alice.wait_for(lambda: status_of(self.win(alice)) ==
                             "There is already a forum called general.", "taken")

        # Access: New User may not read Sysops; bob's list loses it
        await self.pick(alice, "Sysops")
        alice.click_text(WIN_BOARDS, "Access...")
        acc = await alice.wait_window("Forum Access")
        boxes = [g for g in sorted(acc.gadgets) if acc.gadgets[g]["kind"] == Kind.CHECKBOX]
        self.assertEqual(len(boxes), 8)                  # 4 roles x Read, Post
        alice.select(WIN_ACCESS, boxes[0], 0)            # New User: Read off
        alice.select(WIN_ACCESS, boxes[1], 0)            #           Post off
        alice.select(WIN_ACCESS, boxes[3], 0)            # Member: Post off
        alice.click_text(WIN_ACCESS, "OK")
        await alice.wait_for(lambda: status_of(self.win(alice)) == "Saved who may use Sysops.",
                             "saved")
        fid = next(f["id"] for f in d.forums() if f["name"] == "Sysops")
        nu, member = d.role_by_name("New User")["id"], d.role_by_name("Member")["id"]
        self.assertEqual(d.forum_access(fid), {nu: (False, False), member: (True, False)})
        await bob.wait_for(lambda: not any(r.startswith("Sysops") for r in self.rows(bob)),
                           "hidden from bob")
        self.assertIn("limited", next(r for r in self.rows(alice) if r.startswith("Sysops")))

        # Rename and Lock
        alice.value(WIN_BOARDS, gadget_of(self.win(alice), Kind.TEXTBOX), "Staff")
        alice.click_text(WIN_BOARDS, "Rename")
        await alice.wait_for(lambda: status_of(self.win(alice)) == "Renamed Sysops to Staff.",
                             "renamed")
        await self.pick(alice, "General")
        alice.click_text(WIN_BOARDS, "Lock")
        await alice.wait_for(lambda: status_of(self.win(alice)).startswith("General is locked"),
                             "locked")
        self.make_member("bob")
        gen = next(f for f in d.forums() if f["name"] == "General")
        self.assertFalse(self.server.screens.boards.can_post(self.session("bob"), gen))
        self.assertTrue(self.server.screens.boards.can_post(self.session("alice"), gen))
        await bob.wait_for(lambda: any(r.startswith("General") and "locked" in r
                                       for r in self.rows(bob)), "locked for bob")

        # Delete, after the confirmation
        await self.pick(alice, "Staff")
        alice.click_text(WIN_BOARDS, "Delete")
        conf = await alice.wait_window("Delete Forum")
        conf.find("Delete Staff and its 0 topics?")
        alice.click_text(WIN_DELETE, "Delete")
        await self.shown(alice, "Deleted Staff.")
        self.assertEqual([f["name"] for f in d.forums()], ["General"])
        self.assertEqual(d.forum_access(fid), {})

    async def test_moderator_actions_are_checked(self):
        """bob (no boards.moderate) clicking moderator buttons he was never sent: refused."""
        bob, d = self.bob, self.server.db
        await self.open_boards(bob)
        await self.pick(bob, "General")
        b = self.server.screens.boards.browsers[self.session("bob")]
        b.name = type("Box", (), {"value": "Hacked"})()       # as if the box were there
        b._rename(None)
        b._delete_forum(None)
        b._lock(None)
        await bob.wait_for(lambda: len(bob.alerts) >= 3, "refusals")
        self.assertEqual([f["name"] for f in d.forums()], ["General"])
        self.assertFalse(d.forums()[0]["locked"])

    async def test_delete_topic_and_last_post(self):
        alice, d = self.alice, self.server.db
        fid = d.forums()[0]["id"]
        t1 = d.create_topic(fid, d.user("alice")["id"], "One", ["a"])
        t2 = d.create_topic(fid, d.user("alice")["id"], "Two", ["b"])
        await self.open_boards(alice)
        await self.open_forum(alice, "General")
        await self.pick(alice, "One")
        alice.windows.pop(WIN_DELETE, None)
        alice.click_text(WIN_BOARDS, "Delete Topic")
        await alice.wait_for(lambda: has_text(alice, WIN_DELETE, "Delete the topic One"), "asked")
        self.assertIsNotNone(d.topic(t1), "not before the answer")
        alice.click_text(WIN_DELETE, "Delete")
        await alice.wait_for(lambda: status_of(self.win(alice)) == "Deleted the topic One.",
                             "deleted")
        self.assertIsNone(d.topic(t1))
        await self.pick(alice, "Two")
        alice.windows[WIN_BOARDS].done = False
        alice.click_text(WIN_BOARDS, "Read")
        await self.shown(alice, "Delete Post")
        alice.windows.pop(WIN_DELETE, None)
        alice.click_text(WIN_BOARDS, "Delete Post")
        await alice.wait_for(lambda: has_text(alice, WIN_DELETE, "Delete"), "asked")
        alice.windows[WIN_BOARDS].done = False
        alice.click_text(WIN_DELETE, "Delete")
        await self.shown(alice, "Deleted the post, and the topic with it.")
        self.assertIsNone(d.topic(t2))


class GreyedOutTest(PagesBase):
    """Buttons that need something picked are greyed out until it is (S.SET_FLAGS), and the
    server ignores clicks on greyed-out buttons."""

    async def test_buttons_follow_the_selection(self):
        from meganet.chat import WIN_ROOM
        from meganet.mail import WIN_INBOX
        from meganet.admin import WIN_USERS
        alice, bob, d = self.alice, self.bob, self.server.db
        # Message Boards: Open, Rename, Delete, Lock, Access... need a forum
        alice.pick("Message Boards")
        w = await alice.wait_window("Message Boards")
        for text in ("Open", "Rename", "Delete", "Lock", "Access..."):
            self.assertFalse(alice.enabled(WIN_BOARDS, text), text)
        self.assertFalse(alice.enabled(WIN_BOARDS, "New"), "New waits for a forum name")
        alice.value(WIN_BOARDS, gadget_of(w, Kind.TEXTBOX), "Sysops")
        self.assertTrue(alice.enabled(WIN_BOARDS, "New"))
        alice.value(WIN_BOARDS, gadget_of(w, Kind.TEXTBOX), "")
        self.assertFalse(alice.enabled(WIN_BOARDS, "New"), "greyed again when cleared")
        alice.click(WIN_BOARDS, w.find("Delete"))            # greyed: ignored
        alice.select(WIN_BOARDS, gadget_of(w, Kind.LISTBOX), 0)
        await alice.wait_for(lambda: alice.enabled(WIN_BOARDS, "Open"), "Open enabled")
        self.assertTrue(alice.enabled(WIN_BOARDS, "Access..."))
        self.assertEqual(len(d.forums()), 1, "the greyed-out Delete did nothing")
        # Private Messages: Reply..., Delete and Mark as Unread need a message
        alice.pick("Private Messages")
        await alice.wait_window("Private Messages")
        for text in ("Reply...", "Delete", "Mark as Unread"):
            self.assertFalse(alice.enabled(WIN_INBOX, text), text)
        self.assertTrue(alice.enabled(WIN_INBOX, "New..."))
        # The User Editor: Save, Set Password..., History need a user
        alice.pick("User Editor...")
        ue = await alice.wait_window("User Editor")
        self.assertFalse(alice.enabled(WIN_USERS, "Save"))
        alice.select(WIN_USERS, gadget_of(ue, Kind.LISTBOX), 0)
        await alice.wait_for(lambda: alice.enabled(WIN_USERS, "History"), "History enabled")
        # A chat room: Kick etc. need someone picked who may be acted on; Unban... a ban
        for c in (bob, alice):
            await c.enter_room("Lobby")
        room = alice.windows[WIN_ROOM]
        self.assertFalse(alice.enabled(WIN_ROOM, "Kick"))
        self.assertFalse(alice.enabled(WIN_ROOM, "Unban..."))
        people = lambda: room.gadgets[gadget_of(room, Kind.LISTBOX)]["rows"]
        await alice.wait_for(lambda: people() == ["alice", "bob"], "both")
        alice.select(WIN_ROOM, gadget_of(room, Kind.LISTBOX), 0)         # herself
        await alice.wait_for(lambda: status_of(room).startswith("alice: Karma"), "picked")
        self.assertFalse(alice.enabled(WIN_ROOM, "Kick"), "not on yourself")
        alice.select(WIN_ROOM, gadget_of(room, Kind.LISTBOX), 1)         # bob
        await alice.wait_for(lambda: alice.enabled(WIN_ROOM, "Kick"), "Kick for bob")
        alice.click_text(WIN_ROOM, "Ban")
        await alice.wait_for(lambda: alice.enabled(WIN_ROOM, "Unban..."), "Unban enabled")
        await alice.wait_for(lambda: not alice.enabled(WIN_ROOM, "Kick"), "bob gone")
