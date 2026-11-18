"""A message composer: a centred window with an optional To box, a Subject box, the message in
an editable text area (ui.TextArea: the client lets the user type, wrap, and move around in
it, and sends the lines before any button click), a status line, and Send and Cancel. Used by
Help > Page Admin's "Message to the Admins" (pages.py), private messages (mail.py), the
message boards (boards.py) and the news (news.py: `body` fills the text area for an edit,
`subject_label` and `send_label` rename the Subject box and the Send button).

    Composer(session, "Message to the Admins", WIN_ID, on_send=fn).show()

on_send(composer, to, subject, lines) returns None when it has taken the message (it closes
the composer and confirms with sent()), or a problem to show on the status line. `key` is a
permission every handler checks first (None: anyone signed on).
"""

from .protocol import WFlag, clean_text
from .ui import Window, Button, Label, TextBox, TextArea

MAX_LINES = TextArea.CLIENT_LINES     # what the client's text area holds (32)
LINE_MAX = TextBox.MAX_CHARS


def refuse(session, title, key):
    session.log("refused %s: no %s" % (title, key))
    session.alert(title, "Your account can't use %s." % title)


def sent(session, text="Your message has been sent."):
    """The confirmation after a successful Send (the client draws an OK box)."""
    session.alert("Message Sent", text)


class Composer:
    W = 544
    BODY_H = 102                         # 12 lines show; it scrolls to MAX_LINES

    def __init__(self, session, title, win_id, on_send, to=None, subject="", key=None,
                 on_closed=None, hint="Write your message, then Send.", body=(),
                 subject_label="Subject:", send_label="Send"):
        self.session = session
        self.title = title
        self.win_id = win_id
        self.on_send = on_send
        self.on_closed = on_closed
        self.key = key
        self.has_to = to is not None
        self.to = to or ""
        self.subject = subject
        self.hint = hint
        self.lines = list(body)[:MAX_LINES]       # what the text area starts with (an edit)
        self.subject_label = subject_label
        self.send_label = send_label
        self.win = None

    @property
    def H(self):
        return (16 if self.has_to else 0) + 16 + self.BODY_H + 4 + 12 + 20 - 2

    def show(self, status=None):
        win = Window.centred(self.title, self.W, self.H, flags=WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=self.win_id, on_close=self._closed)
        y = 2
        if self.has_to:
            win.add(Label(8, y + 2, 72, 10, "To:"))
            self.to_box = win.add(TextBox(80, y, 160, 12, self.to))
            y += 16
        bx = max(80, 8 + 8 * len(self.subject_label) + 8)    # (a gap after a long label)
        win.add(Label(8, y + 2, bx - 8, 10, self.subject_label))
        self.subject_box = win.add(TextBox(bx, y, 536 - bx, 12, self.subject))
        y += 16
        self.body = win.add(TextArea(8, y, 528, self.BODY_H, self.lines))
        y += self.BODY_H + 4
        self.status = win.add(Label(8, y + 3, 360, 10, status or self.hint))
        win.add(Button(384, y, 72, 16, self.send_label, on_click=self._send))
        win.add(Button(464, y, 72, 16, "Cancel", on_click=self._cancel))
        self.win = win
        win.show(self.session)
        return self

    def close(self):
        if self.win is not None:
            self.win.close()
        if self.on_closed:
            self.on_closed(self)

    def say(self, text):
        self.status.set_text(text)

    def _allowed(self):
        if self.key is not None and not self.session.can(self.key):
            refuse(self.session, self.title, self.key)
            return False
        return True

    # ---- handlers ----

    def _send(self, button):
        if not self._allowed():
            return None
        if self.has_to:
            self.to = clean_text(self.to_box.value).strip()
        self.subject = clean_text(self.subject_box.value).strip()[:LINE_MAX]
        lines = [clean_text(l).rstrip()[:LINE_MAX] for l in self.body.lines]
        while lines and not lines[-1].strip():
            lines.pop()
        while lines and not lines[0].strip():
            lines.pop(0)
        if not lines:
            return self.say("Write something first.")
        if len(lines) > MAX_LINES:
            return self.say("A message has at most %d lines." % MAX_LINES)
        problem = self.on_send(self, self.to, self.subject, lines)
        if problem:
            self.say(problem)
        return None

    def _cancel(self, button):
        self.close()

    def _closed(self, window):
        if self.on_closed:
            self.on_closed(self)
