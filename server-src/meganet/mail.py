"""Areas > Private Messages (mail.use): an inbox, a Sent folder, and a composer.

    17 = Private Messages: a list of messages ("* " = unread, from or to, subject) and a text
         view with the picked one (From / To, Date, Subject, then the body); New, Reply, Delete,
         Sent / Inbox (switches folders) and Mark as Unread (inbox only); the close box closes it
    18 = New Message: To, Subject, and the body in a text area (compose.py)

The private_messages table keeps each message until both the sender and the recipient have
deleted it. A signed-on recipient gets the envelope icon (NOTIFY slot 2) while they have unread
messages, and at sign-on; clicking it opens the inbox. Every handler checks mail.use again.
"""

import time

from . import permissions as perms
from .compose import Composer, refuse, sent
from .protocol import WFlag, GFlag, Icon, SLOT_MAIL, clean_text
from .ui import Window, Button, Label, ListBox, TextView

WIN_INBOX = 17
WIN_COMPOSE = 18
TITLE = "Private Messages"
INBOX_W, INBOX_H = 632, 160
NAME_COLS = 10                    # list rows: name, subject, date and time, " *" if unread
SUBJECT_COLS = 12                 # (37 characters: the list's width)


def message_row(m, sent_folder):
    unread = not m["read"] and not sent_folder
    name = m["to_name"] if sent_folder else m["from_name"]
    subject = m["subject"] or "(no subject)"
    row = "%-*s %-*s %s%s" % (NAME_COLS, name[:NAME_COLS], SUBJECT_COLS, subject[:SUBJECT_COLS],
                              time.strftime("%m-%d %H:%M", time.localtime(m["sent"])),
                              " *" if unread else "")
    return row[:ListBox.ROW_MAX].rstrip()


def reply_subject(subject):
    subject = subject or ""
    return subject if subject.lower().startswith("re:") else ("Re: " + subject).strip()


class Mail:
    def __init__(self, server):
        self.server = server
        self.inboxes = {}                # session -> Inbox
        self.composers = {}              # session -> Composer

    @property
    def db(self):
        return self.server.db

    def session_of(self, user_id):
        return next((s for s in self.server.screens.online() if s.user_id == user_id), None)

    def allowed(self, session):
        if not session.can(perms.MAIL_USE):
            refuse(session, TITLE, perms.MAIL_USE)
            return False
        return True

    # ---- opening ----

    def open_inbox(self, session, sent=False):
        if not self.allowed(session):
            return None
        box = self.inboxes.get(session) or Inbox(self, session)
        box.sent = sent
        box.msg_id = None
        return box.show()

    def compose(self, session, to="", subject=""):
        if not self.allowed(session):
            return None
        c = Composer(session, "New Message", WIN_COMPOSE, on_send=self._send, to=to,
                     subject=subject, key=perms.MAIL_USE, on_closed=self._compose_closed)
        self.composers[session] = c
        return c.show()

    def _compose_closed(self, composer):
        if self.composers.get(composer.session) is composer:
            del self.composers[composer.session]

    def _send(self, composer, to, subject, lines):
        session = composer.session
        if not to:
            return "Who is it to? Type a screen name."
        user = self.db.user(to)
        if user is None:
            return "There is no user called %s." % to[:20]
        self.db.send_private_message(session.user_id, user["id"], clean_text(subject), lines)
        session.log("private message to %s (%d lines)" % (user["name"], len(lines)))
        composer.close()
        self.changed(user["id"])
        self.changed(session.user_id)
        sent(session, "Your message to %s has been sent." % user["name"])   # (last)
        return None

    # ---- the envelope icon and open inboxes ----

    def refresh_icon(self, session):
        n = self.db.unread_private_count(session.user_id) if session.can(perms.MAIL_USE) else 0
        if n:
            session.set_notify(SLOT_MAIL, Icon.MAIL, "%d unread private message%s" % (
                n, "" if n == 1 else "s"))
        else:
            session.set_notify(SLOT_MAIL, Icon.NONE)

    def changed(self, user_id):
        """`user_id`'s messages changed: their icon and open inbox follow (if signed on)."""
        s = self.session_of(user_id)
        if s is None:
            return
        self.refresh_icon(s)
        box = self.inboxes.get(s)
        if box is not None:
            box.refresh()

    def notify_click(self, session, slot):
        if slot == SLOT_MAIL:
            if not session.can(perms.MAIL_USE):
                session.log("notify click %d refused: no %s" % (slot, perms.MAIL_USE))
                return self.refresh_icon(session)
            return self.open_inbox(session)
        return None

    def signed_on(self, session):
        self.refresh_icon(session)

    def permissions_changed(self, session):
        if not session.can(perms.MAIL_USE):
            box = self.inboxes.get(session)
            if box is not None:
                box.close()
            c = self.composers.get(session)
            if c is not None:
                c.close()
        self.refresh_icon(session)

    def disconnected(self, session):
        self.inboxes.pop(session, None)
        self.composers.pop(session, None)


class Inbox:
    """One user's Private Messages window. The text view only appends, so picking another
    message (or switching folders) sends the window again."""

    def __init__(self, mail, session):
        self.mail = mail
        self.session = session
        self.sent = False                # showing the Sent folder
        self.msg_id = None
        self.ids = []
        self.win = None

    @property
    def db(self):
        return self.mail.db

    def messages(self):
        uid = self.session.user_id
        return self.db.sent_messages(uid) if self.sent else self.db.inbox(uid)

    def rows(self):
        msgs = self.messages()
        self.ids = [m["id"] for m in msgs]
        self.unread = sum(1 for m in msgs if not m["read"])
        return [message_row(m, self.sent) for m in msgs]

    def heading(self):
        n = len(self.ids)
        if self.sent:
            return "Sent: %d message%s" % (n, "" if n == 1 else "s")
        return "Inbox: %d message%s, %d unread" % (n, "" if n == 1 else "s", self.unread)

    def show(self, status=None):
        self.mail.inboxes[self.session] = self
        rows = self.rows()
        if self.msg_id not in self.ids:
            self.msg_id = None
        lines = self.message_lines()
        win = Window.centred(TITLE, INBOX_W, INBOX_H, flags=WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_INBOX, on_close=self._closed)
        self.head = win.add(Label(8, 2, 320, 10, self.heading()))
        self.list = win.add(ListBox(8, 14, 320, 112, rows, on_select=self._pick))
        self.view = win.add(TextView(336, 14, 288, 112, lines))
        win.add(Button(8, 130, 72, 16, "New...", on_click=self._new))
        self.reply_b = win.add(Button(88, 130, 80, 16, "Reply...", on_click=self._reply))
        self.delete_b = win.add(Button(176, 130, 72, 16, "Delete", on_click=self._delete))
        win.add(Button(256, 130, 72, 16, "Inbox" if self.sent else "Sent",
                       on_click=self._folder))
        self.unread_b = None
        if not self.sent:                    # (read or not is the recipient's)
            self.unread_b = win.add(Button(336, 130, 128, 16, "Mark as Unread",
                                           on_click=self._unread))
        self.buttons()
        if status is None:
            status = "Pick a message to read it." if rows else (
                "Nothing sent yet." if self.sent else "No messages.")
        self.status = win.add(Label(8, 148, 616, 10, status))
        self.win = win
        win.show(self.session)
        if self.msg_id is not None:
            self.list.selected = self.ids.index(self.msg_id)
            self.list.set_value(self.list.selected)
        return self

    def buttons(self):
        """Grey out what needs a picked message (Mark as Unread: a read one)."""
        m = self.db.private_message(self.msg_id) if self.msg_id is not None else None
        self.reply_b.enable(m is not None)
        self.delete_b.enable(m is not None)
        if self.unread_b is not None:
            self.unread_b.enable(m is not None and bool(m["read"]))

    def refresh(self):
        """A message came (or went): update the list and heading in place."""
        if self.win is None or not self.win.shown:
            return
        rows = self.rows()
        self.list.set_rows(rows)
        self.head.set_text(self.heading())
        if self.msg_id in self.ids:
            self.list.selected = self.ids.index(self.msg_id)
            self.list.set_value(self.list.selected)
        elif self.msg_id is None:                # (the hint matches the list again)
            self.say("Pick a message to read it." if rows else (
                "Nothing sent yet." if self.sent else "No messages."))
        if self.msg_id not in self.ids:
            self.msg_id = None
        self.buttons()

    def close(self):
        self.mail.inboxes.pop(self.session, None)
        if self.win is not None:
            self.win.close()

    def _closed(self, window):
        if self.mail.inboxes.get(self.session) is self:
            del self.mail.inboxes[self.session]

    def say(self, text):
        self.status.set_text(text)

    def message_lines(self):
        """The reading pane's lines for the picked message (none if nothing is picked)."""
        if self.msg_id is None:
            return []
        m = self.db.private_message(self.msg_id)
        return ["To: %s" % m["to_name"] if self.sent else "From: %s" % m["from_name"],
                "Date: %s" % time.strftime("%Y-%m-%d %H:%M", time.localtime(m["sent"])),
                "Subject: %s" % (m["subject"] or "(no subject)"), ""] + m["body"].split("\n")

    # ---- handlers (each checks mail.use) ----

    def _pick(self, listbox, index, double):
        if not self.mail.allowed(self.session) or listbox.selected is None:
            return
        self.msg_id = self.ids[listbox.selected]
        m = self.db.private_message(self.msg_id)
        if not self.sent and not m["read"]:
            self.db.mark_private_read(self.msg_id)
            self.mail.refresh_icon(self.session)
            self.refresh()                       # (its row loses the unread mark)
        self.view.set_lines(self.message_lines())   # the reading pane, in place
        self.buttons()
        self.say("")

    def _new(self, button):
        if self.mail.allowed(self.session):
            self.mail.compose(self.session)

    def _reply(self, button):
        if not self.mail.allowed(self.session):
            return None
        if self.msg_id is None:
            return self.say("Pick a message first.")
        m = self.db.private_message(self.msg_id)
        to = m["to_name"] if self.sent else m["from_name"]
        return self.mail.compose(self.session, to=to, subject=reply_subject(m["subject"]))

    def _delete(self, button):
        if not self.mail.allowed(self.session):
            return None
        if self.msg_id is None:
            return self.say("Pick a message first.")
        self.db.delete_private_message(self.msg_id, self.session.user_id)
        self.session.log("deleted private message %d" % self.msg_id)
        self.msg_id = None
        self.show("Deleted.")
        self.mail.refresh_icon(self.session)
        return None

    def _unread(self, button):
        """The picked message gets its unread mark (and the envelope icon) back; it stays
        on show until another is picked."""
        if not self.mail.allowed(self.session) or self.sent:
            return None
        if self.msg_id is None:
            return self.say("Pick a message first.")
        self.db.mark_private_read(self.msg_id, False)
        self.session.log("marked private message %d unread" % self.msg_id)
        self.mail.refresh_icon(self.session)
        self.refresh()
        self.buttons()
        return self.say("Marked as unread.")

    def _folder(self, button):
        if not self.mail.allowed(self.session):
            return
        self.sent = not self.sent
        self.msg_id = None
        self.show()

    def _close(self, button):
        self.close()
