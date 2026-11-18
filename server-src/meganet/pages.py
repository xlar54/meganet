"""Help > Page Admin: a user asks for an admin (anyone whose role has admin.pages).

With an admin signed on (other than the user):
    the user gets the "Page Admin" window ("Paging an admin...", Cancel); every admin gets the
    page icon (NOTIFY slot 0, flashing). The first admin to click it takes the oldest waiting
    page: the icon goes for all admins, the paging window closes, and both get a private chat
    window ("Chat with <other>"). Closing either side ends the chat; the other side can still
    read it. Cancel (or the close box) withdraws the page. If the last admin goes while a page
    waits, the user gets the no-admin dialog instead.
With none:
    "No admin is available right now..." Yes / No. Yes opens "Message to the Admins"
    (compose.py), stored in the admin_messages table. Admins get the mail icon (slot 1) while
    unread ones are waiting; it opens Admin > Messages from users (window 16).

Window ids: 13 = Page Admin (paging), 14 = no admin available, 15 = Message to the Admins,
16 = Messages from users; chats take dynamic ids (session.FIRST_DYNAMIC_WIN up).
"""

import time

from . import permissions as perms
from .compose import Composer, sent
from .protocol import WFlag, GFlag, Icon, SLOT_PAGE, SLOT_ADMIN_MAIL, Sound
from .session import FIRST_DYNAMIC_WIN
from .ui import add_buttons, closer, Window, Button, Label, TextBox, ListBox, TextView, centre

WIN_PAGING = 13
WIN_NO_ADMIN = 14
WIN_TO_ADMINS = 15
WIN_ADMIN_MSGS = 16

CHAT_W, CHAT_H = 360, 140
MSGS_W, MSGS_H = 632, 152


def plural(n, one, many):
    return one if n == 1 else many


class Page:
    def __init__(self, session):
        self.user = session
        self.since = time.time()
        self.win = None


class Pages:
    def __init__(self, server):
        self.server = server
        self.queue = []                  # waiting Pages, oldest first
        self.chats = []                  # open PrivateChats
        self.msg_windows = {}            # admin session -> AdminMessages

    @property
    def db(self):
        return self.server.db

    def online(self):
        return self.server.screens.online()

    def admins(self, exclude=None):
        """The signed-on sessions that may answer pages (not `exclude`)."""
        return [s for s in self.online() if s.can(perms.ADMIN_PAGES) and s is not exclude
                and s.status != "offline"]           # (Offline: not to be paged)

    def page_of(self, session):
        return next((p for p in self.queue if p.user is session), None)

    # ---- the user's side ----

    def page_admin(self, session):
        """Help > Page Admin."""
        page = self.page_of(session)
        if page is not None:                     # already waiting: show the window again
            return self._show_paging(page)
        if not self.admins(exclude=session):
            return self.no_admin(session)
        page = Page(session)
        self.queue.append(page)
        session.log("paging the admins")
        self._show_paging(page)
        self.refresh_icons()
        for admin in self.admins(exclude=session):          # a chime with the flashing icon
            admin.sound(Sound.CHIME)
        return None

    def _show_paging(self, page):
        win = Window.centred("Page Admin", 240, 40, flags=WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_PAGING, on_close=lambda w: self.cancel(page),
                             minimize=False)
        win.add(Label(8, 4, 224, 10, "Paging an admin..."))
        add_buttons(win, [("Cancel", lambda b: self.cancel(page), GFlag.DEFAULT)], centre=True)
        page.win = win
        win.show(page.user)

    def cancel(self, page):
        """The user withdrew the page (Cancel or the close box)."""
        if page not in self.queue:
            return
        self.queue.remove(page)
        page.user.log("page withdrawn")
        if page.win is not None:
            page.win.close()
        self.refresh_icons()

    def no_admin(self, session):
        win = Window.centred("Page Admin", 400, 52, flags=WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_NO_ADMIN, minimize=False)
        win.add(Label(8, 4, 384, 10, "No admin is available right now."))
        win.add(Label(8, 16, 384, 10, "Would you like to leave a message for the admins?"))
        add_buttons(win, [("Yes", self._yes, GFlag.DEFAULT), ("No", closer, 0)], centre=True)
        win.show(session)

    def _yes(self, button):
        session = button.session
        button.window.close()
        Composer(session, "Message to the Admins", WIN_TO_ADMINS,
                 on_send=self._send_message).show()

    def _send_message(self, composer, _to, subject, lines):
        session = composer.session
        self.db.add_admin_message(session.user_id, subject, lines)
        session.log("left a message for the admins (%d lines)" % len(lines))
        composer.close()
        self.messages_changed()
        sent(session, "Your message is waiting for the admins.")     # (last: no redraws after)
        return None

    # ---- the admins' side ----

    def notify_click(self, session, slot):
        if not session.can(perms.ADMIN_PAGES):
            session.log("notify click %d refused: no %s" % (slot, perms.ADMIN_PAGES))
            return self.refresh_icons([session])
        if slot == SLOT_PAGE:
            return self.take(session)
        if slot == SLOT_ADMIN_MAIL:
            return self.open_messages(session)
        return None

    def take(self, admin):
        """The admin clicked the page icon: take the oldest page that isn't their own."""
        page = next((p for p in self.queue if p.user is not admin), None)
        if page is None:
            return self.refresh_icons([admin])
        self.queue.remove(page)
        if page.win is not None:
            page.win.close()
        admin.log("took the page from %s" % page.user.user)
        self.chats.append(PrivateChat(self, page.user, admin))
        self.refresh_icons()
        return None

    def refresh_icons(self, sessions=None):
        """Put the page icon (slot 0) and the admin-mail icon (slot 1) right on every signed-on
        session (or just `sessions`): admins see them, nobody else does."""
        unread = None
        for s in (self.online() if sessions is None else sessions):
            if s.closed or s.user is None:
                continue
            if not s.can(perms.ADMIN_PAGES):
                s.set_notify(SLOT_PAGE, Icon.NONE)
                s.set_notify(SLOT_ADMIN_MAIL, Icon.NONE)
                continue
            waiting = [p for p in self.queue if p.user is not s]
            if len(waiting) == 1:
                s.set_notify(SLOT_PAGE, Icon.PAGE, "%s is paging you" % waiting[0].user.user)
            elif waiting:
                s.set_notify(SLOT_PAGE, Icon.PAGE, "%d users are paging" % len(waiting))
            else:
                s.set_notify(SLOT_PAGE, Icon.NONE)
            if unread is None:
                unread = self.db.admin_unread_count()
            if unread:
                s.set_notify(SLOT_ADMIN_MAIL, Icon.MAIL, "%d %s from users" % (
                    unread, plural(unread, "message", "messages")))
            else:
                s.set_notify(SLOT_ADMIN_MAIL, Icon.NONE)

    def check_waiting(self):
        """Pages nobody can answer any more (the last admin went) turn into the no-admin
        dialog."""
        for page in list(self.queue):
            if not self.admins(exclude=page.user):
                self.queue.remove(page)
                if page.win is not None:
                    page.win.close()
                page.user.log("page dropped: no admin left")
                self.no_admin(page.user)

    # ---- Admin > Messages from users ----

    def open_messages(self, session):
        if not session.can(perms.ADMIN_PAGES):
            session.log("refused admin messages: no %s" % perms.ADMIN_PAGES)
            return session.alert("Administration", "You don't have permission to do that.")
        ed = self.msg_windows.get(session) or AdminMessages(self, session)
        return ed.show()

    def messages_changed(self):
        """A message came, was read or was deleted: the icons and open windows follow."""
        self.refresh_icons()
        for ed in list(self.msg_windows.values()):
            ed.refresh()

    # ---- keeping things in step ----

    def signed_on(self, session):
        self.refresh_icons([session])
        if session.can(perms.ADMIN_PAGES) and self.queue:
            self.refresh_icons()

    def permissions_changed(self, session):
        if not session.can(perms.ADMIN_PAGES) and session in self.msg_windows:
            self.msg_windows[session].close()
        self.refresh_icons([session])
        self.check_waiting()

    def disconnected(self, session):
        page = self.page_of(session)
        if page is not None:
            self.queue.remove(page)
        for chat in list(self.chats):
            chat.gone(session)
        self.msg_windows.pop(session, None)
        self.refresh_icons()
        self.check_waiting()


class ChatSide:
    def __init__(self, chat, session, other_name):
        self.chat = chat
        self.session = session
        self.open = True
        win_id = session.free_window_id()
        k = (win_id - FIRST_DYNAMIC_WIN) % 4             # cascade several chats
        x, y = centre(CHAT_W, CHAT_H)
        win = Window("Chat with %s" % other_name, x + 16 * k, y + 4 * k, CHAT_W, CHAT_H,
                     win_id=win_id, on_close=lambda w: chat.leave(self))
        self.view = win.add(TextView(6, 6, 348, 106))
        self.entry = win.add(TextBox(6, 118, 276, 12))
        win.add(Button(288, 116, 66, 16, "Send", GFlag.DEFAULT,
                       on_click=lambda b: chat.say(self)))
        self.win = win


class PrivateChat:
    """A private chat between a user who paged and the admin who took the page."""

    def __init__(self, pages, user, admin):
        self.pages = pages
        self.ended = False
        self.sides = [ChatSide(self, user, admin.user), ChatSide(self, admin, user.user)]
        for side in self.sides:
            side.win.show(side.session)
        self.sides[0].view.append("* %s has answered your page." % admin.user)
        self.sides[1].view.append("* You took %s's page." % user.user)

    def other(self, side):
        return self.sides[1] if side is self.sides[0] else self.sides[0]

    def say(self, side):
        text = side.entry.value.strip()
        if not text:
            return
        side.entry.set_text("")
        if self.ended:
            return side.view.append("* The chat has ended.")
        line = "%s: %s" % (side.session.user, text)
        for s in self.sides:
            if s.open:
                s.view.append(line)
        return None

    def leave(self, side):
        """One side closed its window (or signed off): the other can read, not send."""
        side.open = False
        other = self.other(side)
        if not self.ended:
            self.ended = True
            if other.open:
                other.view.append("* %s left the chat" % side.session.user)
        if not other.open and self in self.pages.chats:
            self.pages.chats.remove(self)

    def gone(self, session):
        for side in self.sides:
            if side.session is session and side.open:
                self.leave(side)


def admin_msg_row(m):
    """Who, the subject, when, " *" if unread: 37 characters, the list's width."""
    return ("%-10s %-12s %s%s" % (m["name"][:10], (m["subject"] or "(no subject)")[:12],
                                  time.strftime("%m-%d %H:%M", time.localtime(m["sent"])),
                                  "" if m["read"] else " *"))


class AdminMessages:
    """One admin's "Messages from users" window: the list, the picked message, Reply (a private
    message back, through mail.py's composer), Delete, Mark as Unread.
    Picking a message marks it read and shows it in the reading pane, in place."""

    def __init__(self, pages, session):
        self.pages = pages
        self.session = session
        self.msg_id = None
        self.ids = []
        self.win = None

    @property
    def db(self):
        return self.pages.db

    def rows(self):
        msgs = self.db.admin_messages()
        self.ids = [m["id"] for m in msgs]
        return [admin_msg_row(m) for m in msgs]

    def show(self, status=None):
        self.pages.msg_windows[self.session] = self
        rows = self.rows()
        if self.msg_id not in self.ids:
            self.msg_id = None
        lines = self.message_lines()
        win = Window.centred("Messages from users", MSGS_W, MSGS_H, win_id=WIN_ADMIN_MSGS,
                             on_close=self._closed)
        win.add(Label(8, 2, 320, 10, "%d message%s (* = unread)" % (
            len(rows), plural(len(rows), "", "s"))))
        self.list = win.add(ListBox(8, 14, 320, 112, rows, on_select=self._pick))
        self.view = win.add(TextView(336, 14, 288, 112, lines))
        self.reply_b = win.add(Button(8, 130, 80, 16, "Reply...", on_click=self._reply))
        self.delete_b = win.add(Button(96, 130, 72, 16, "Delete", on_click=self._delete))
        self.unread_b = win.add(Button(176, 130, 128, 16, "Mark as Unread",
                                       on_click=self._unread))
        self.buttons()
        self.status = win.add(Label(304, 134, 240, 10, status or (
            "Pick a message to read it." if rows else "No messages.")))
        self.win = win
        win.show(self.session)
        if self.msg_id is not None:
            self.list.selected = self.ids.index(self.msg_id)
            self.list.set_value(self.list.selected)

    def buttons(self):
        """Grey out what needs a picked message (Mark as Unread: a read one)."""
        m = self.db.admin_message(self.msg_id) if self.msg_id is not None else None
        self.reply_b.enable(m is not None)
        self.delete_b.enable(m is not None)
        self.unread_b.enable(m is not None and bool(m["read"]))

    def refresh(self):
        """Another admin (or a user) changed the messages: update the list in place."""
        if self.win is None or not self.win.shown:
            return
        self.list.set_rows(self.rows())
        if self.msg_id in self.ids:
            self.list.selected = self.ids.index(self.msg_id)
            self.list.set_value(self.list.selected)
        else:
            self.msg_id = None
        self.buttons()

    def close(self):
        self.pages.msg_windows.pop(self.session, None)
        if self.win is not None:
            self.win.close()

    def _closed(self, window):
        if self.pages.msg_windows.get(self.session) is self:
            del self.pages.msg_windows[self.session]

    def _allowed(self):
        if not self.session.can(perms.ADMIN_PAGES):
            self.session.log("refused admin messages: no %s" % perms.ADMIN_PAGES)
            self.session.alert("Administration", "You don't have permission to do that.")
            return False
        return True

    def message_lines(self):
        """The reading pane's lines for the picked message (none if nothing is picked)."""
        if self.msg_id is None:
            return []
        m = self.db.admin_message(self.msg_id)
        return ["From: %s" % m["name"],
                "Date: %s" % time.strftime("%Y-%m-%d %H:%M", time.localtime(m["sent"])),
                "Subject: %s" % (m["subject"] or "(none)"), ""] + m["text"].split("\n")

    def _pick(self, listbox, index, double):
        if not self._allowed() or listbox.selected is None:
            return
        self.msg_id = self.ids[listbox.selected]
        self.db.mark_admin_message_read(self.msg_id)
        self.view.set_lines(self.message_lines())     # the reading pane, in place
        self.status.set_text("")
        self.pages.messages_changed()                 # (the list loses the unread mark)

    def _reply(self, button):
        """Answer the picked message with a private message (the same composer as Areas >
        Private Messages), so the reply lands in the user's inbox."""
        if not self._allowed():
            return None
        if self.msg_id is None:
            return self.status.set_text("Pick a message first.")
        m = self.db.admin_message(self.msg_id)
        from .mail import reply_subject
        return self.pages.server.screens.mail.compose(self.session, to=m["name"],
                                                      subject=reply_subject(m["subject"]))

    def _unread(self, button):
        """The picked message is unread again, for every admin (their envelope icons too)."""
        if not self._allowed():
            return None
        if self.msg_id is None:
            return self.status.set_text("Pick a message first.")
        self.db.mark_admin_message_read(self.msg_id, False)
        self.session.log("admin: marked message %d unread" % self.msg_id)
        self.pages.messages_changed()
        return self.status.set_text("Marked as unread.")

    def _delete(self, button):
        if not self._allowed():
            return None
        if self.msg_id is None:
            return self.status.set_text("Pick a message first.")
        self.db.delete_admin_message(self.msg_id)
        self.session.log("admin: deleted message %d from users" % self.msg_id)
        self.msg_id = None
        self.show("Deleted.")
        self.pages.messages_changed()
        return None
