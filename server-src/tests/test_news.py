"""Areas > News (news.py): holders of news.post write, edit and delete bulletins in the
composer; everyone with news.read reads them, newest first, and their windows follow."""

from meganet.news import (WIN_NEWS, WIN_NEWS_EDIT, WIN_NEWS_DELETE, WIN_NEWS_OFFER,
                          WIN_NEWS_READ)
from meganet.protocol import Kind, Icon, SLOT_NEWS
from tests.test_pages import PagesBase
from tests.test_roles import gadget_of, status_of


class NewsTest(PagesBase):
    async def open_news(self, c):
        c.windows.pop(WIN_NEWS, None)
        c.pick("News")
        return await c.wait_window("News")

    def rows(self, c):
        w = c.windows[WIN_NEWS]
        return w.gadgets[gadget_of(w, Kind.LISTBOX)]["rows"]

    def reader(self, c):
        """The reading window's (headline, by-line, text lines)."""
        w = c.windows[WIN_NEWS_READ]
        labels = sorted((g for g in w.gadgets.values() if g["kind"] == Kind.LABEL),
                        key=lambda g: g["box"][1])
        return (labels[0]["text"], labels[1]["text"],
                w.gadgets[gadget_of(w, Kind.TEXTVIEW)]["lines"])

    async def click_row(self, c, nth):
        w = c.windows[WIN_NEWS]
        c.windows.pop(WIN_NEWS_READ, None)
        c.select(WIN_NEWS, gadget_of(w, Kind.LISTBOX), nth)     # (picked: Read opens it)
        c.click_text(WIN_NEWS, "Read")
        return await c.wait_for(lambda: WIN_NEWS_READ in c.windows, "reading window")

    async def write(self, c, button, title, headline, lines, send):
        c.click_text(WIN_NEWS, button)
        comp = await c.wait_window(title)
        c.value(WIN_NEWS_EDIT, gadget_of(comp, Kind.TEXTBOX), headline)
        c.text(WIN_NEWS_EDIT, gadget_of(comp, Kind.EDIT), lines)
        c.click_text(WIN_NEWS_EDIT, send)
        await c.wait_for(lambda: WIN_NEWS_EDIT not in c.windows, "composer closed")
        return comp

    async def test_post_edit_delete(self):
        alice, bob = self.alice, self.bob                   # alice: Sysop; bob: New User
        db = self.server.db
        self.assertIn("News", bob.menu_items("Areas"))
        w = await self.open_news(bob)
        self.assertEqual(status_of(w), "No news yet.")
        self.assertFalse(any(g["text"] == "New..." for g in w.gadgets.values()), "posters only")
        # a forged compose from bob is refused
        self.server.screens.news.compose(self.session("bob"))
        await bob.wait_for(lambda: ("News", "Your account can't use News.") in bob.alerts,
                           "refused")
        self.assertEqual(db.news(), [])

        await self.open_news(alice)
        self.assertFalse(alice.enabled(WIN_NEWS, "Edit..."), "nothing picked yet")
        await self.write(alice, "New...", "New Bulletin", "Server moved",
                         ["We're on a new machine.", "", "Same address."], "Post")
        await bob.wait_for(lambda: len(self.rows(bob)) == 1, "bob sees it")
        self.assertTrue(self.rows(bob)[0].endswith("Server moved"))
        self.assertNotIn(WIN_NEWS_READ, bob.windows, "nothing opens until a click")
        # a click opens it to read, as wide as the composer's text area
        await self.click_row(bob, 0)
        head, by, text = self.reader(bob)
        self.assertEqual(head, "Server moved")
        self.assertTrue(by.startswith("By alice, "))
        self.assertEqual(text, ["We're on a new machine.", "", "Same address."])
        rw = bob.windows[WIN_NEWS_READ]
        self.assertEqual(rw.gadgets[gadget_of(rw, Kind.TEXTVIEW)]["box"][2], 528)
        self.assertFalse(any(g["text"] == "Edit..." for g in rw.gadgets.values()))

        # Edit: the composer starts with the bulletin; Save changes it for everyone
        self.assertTrue(alice.enabled(WIN_NEWS, "Edit..."))
        alice.click_text(WIN_NEWS, "Edit...")
        comp = await alice.wait_window("Edit Bulletin")
        self.assertEqual(comp.gadgets[gadget_of(comp, Kind.EDIT)]["lines"],
                         ["We're on a new machine.", "", "Same address."])
        self.assertEqual(comp.gadgets[gadget_of(comp, Kind.TEXTBOX)]["text"], "Server moved")
        alice.click_text(WIN_NEWS_EDIT, "Cancel")
        await alice.wait_for(lambda: WIN_NEWS_EDIT not in alice.windows, "cancelled")
        await self.write(alice, "Edit...", "Edit Bulletin", "Server moved!",
                         ["New machine, same address."], "Save")
        await bob.wait_for(lambda: self.reader(bob)[0] == "Server moved!",
                           "bob's open reader follows the edit")
        self.assertIn("(edited by alice,", self.reader(bob)[1])
        self.assertEqual(self.reader(bob)[2], ["New machine, same address."])
        self.assertEqual(db.news()[0]["body"], "New machine, same address.")
        bob.click_text(WIN_NEWS_READ, "OK")
        await bob.wait_for(lambda: WIN_NEWS_READ not in bob.windows, "closed")

        # a second one goes on top
        await self.write(alice, "New...", "New Bulletin", "Party", ["Saturday."], "Post")
        await bob.wait_for(lambda: len(self.rows(bob)) == 2, "two")
        self.assertTrue(self.rows(bob)[0].endswith("Party"))

        # Delete: a confirmation, then it's gone for everyone
        alice.click_text(WIN_NEWS, "Delete")
        await alice.wait_window("Delete Bulletin")
        alice.click_text(WIN_NEWS_DELETE, "Delete")
        await bob.wait_for(lambda: len(self.rows(bob)) == 1, "gone for bob")
        self.assertEqual([n["headline"] for n in db.news()], ["Server moved!"])

    async def test_new_news_offered_after_welcome(self):
        db = self.server.db
        db.post_news("Party", ["Saturday."], db.user("alice")["id"])
        db.post_news("Server moved", ["Same address."], db.user("alice")["id"])
        carol = await self.signed_on("carol")               # first sign-on: both are new
        self.assertNotIn(WIN_NEWS_OFFER, carol.windows, "not on top of the welcome")
        carol.click_text(1, "OK")                            # (the welcome window)
        offer = await carol.wait_window("News")
        self.assertIs(carol.windows.get(WIN_NEWS_OFFER), offer)
        offer.find("There are 2 unread news bulletins.")
        carol.click_text(WIN_NEWS_OFFER, "Read Now")
        await carol.wait_for(lambda: WIN_NEWS in carol.windows, "News opened")
        self.assertTrue(self.rows(carol)[0].endswith("Server moved"))

    async def test_no_offer_without_new_news(self):
        bob = self.bob
        bob.click_text(1, "OK")
        await self.roundtrip(bob)
        self.assertNotIn(WIN_NEWS_OFFER, bob.windows)

    async def test_role_can_be_given_news_post(self):
        bob, db = self.bob, self.server.db
        nu = db.default_role_id()
        self.assertIsNone(db.set_role_permissions(nu, db.role_permissions(nu) | {"news.post"}))
        self.server.permissions_changed(role_id=nu)
        w = await self.open_news(bob)
        self.assertTrue(any(g["text"] == "New..." for g in w.gadgets.values()))
        await self.write(bob, "New...", "New Bulletin", "Hi from bob", ["Hello."], "Post")
        self.assertEqual(db.news()[0]["author_name"], "bob")

    def head(self, c):
        w = c.windows[WIN_NEWS]
        return next(g["text"] for g in w.gadgets.values()
                    if g["kind"] == Kind.LABEL and "bulletin" in g["text"])

    async def test_unread_icon_and_marking_read(self):
        alice, bob, db = self.alice, self.bob, self.server.db
        self.assertEqual(bob.icon(SLOT_NEWS), Icon.NONE, "no news: no newspaper")
        await self.open_news(alice)
        await self.write(alice, "New...", "New Bulletin", "Party", ["Saturday."], "Post")
        await self.write(alice, "New...", "New Bulletin", "Moved", ["Same address."], "Post")
        await bob.wait_for(lambda: bob.hint(SLOT_NEWS) == "2 unread news bulletins", "icon")
        self.assertEqual(bob.icon(SLOT_NEWS), Icon.NEWS)
        # the icon opens News: the unread ones starred
        bob.notify_click(SLOT_NEWS)
        await bob.wait_for(lambda: WIN_NEWS in bob.windows and self.rows(bob), "News open")
        self.assertTrue(all(r.startswith("*") for r in self.rows(bob)))
        self.assertEqual(self.head(bob), "2 bulletins, 2 unread (*).")
        # reading one marks it
        await self.click_row(bob, 0)
        await bob.wait_for(lambda: bob.hint(SLOT_NEWS) == "1 unread news bulletin", "one left")
        await bob.wait_for(lambda: self.rows(bob)[0].startswith(" "), "unstarred")
        # an edit makes it unread again (once closed: an open reader shows the edit, read)
        bob.click_text(WIN_NEWS_READ, "OK")
        await bob.wait_for(lambda: WIN_NEWS_READ not in bob.windows, "closed")
        alice.select(WIN_NEWS, gadget_of(alice.windows[WIN_NEWS], Kind.LISTBOX), 0)
        await self.write(alice, "Edit...", "Edit Bulletin", "Moved!", ["New address."], "Save")
        await bob.wait_for(lambda: bob.hint(SLOT_NEWS) == "2 unread news bulletins", "again")
        # Mark All Read: the icon goes
        bob.click_text(WIN_NEWS, "Mark All Read")
        await bob.wait_for(lambda: bob.icon(SLOT_NEWS) == Icon.NONE, "all read")
        self.assertEqual(db.unread_news(db.user("bob")["id"]), [])
        self.assertFalse(bob.enabled(WIN_NEWS, "Mark All Read"))
        # alice's own: she hasn't read them either, but signs on to the icon next time
        carol = await self.signed_on("carol")
        self.assertEqual(carol.hint(SLOT_NEWS), "2 unread news bulletins")

    def test_reading_began_after_old_sign_ons(self):
        """The first start with read tracking: what each user saw by the old rule (posted
        before their last sign-on) counts as read."""
        import os, tempfile
        from meganet.db import Database
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        db = Database(path)
        uid = db.create_user("dave", "x")
        old = db.post_news("Old", ["seen"], uid)
        db.conn.execute("UPDATE news SET posted = 1000 WHERE id = ?", (old,))
        db.conn.execute("UPDATE users SET last_login = 2000 WHERE id = ?", (uid,))
        db.conn.execute("DELETE FROM news_reads")
        db.conn.execute("DELETE FROM settings WHERE key = 'news_reads_seeded'")
        db.conn.commit()
        new = db.post_news("New", ["not seen"], uid)
        db.close()
        db = Database(path)                       # (the start-up that seeds it)
        self.assertEqual(db.unread_news(uid), [new])
        db.close()
