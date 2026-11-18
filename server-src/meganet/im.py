"""Instant messages between signed-on users (sending needs im.send; anyone may receive).

- From Who's Online: pick someone, Send Message... opens "IM: name" (a dynamic window id): the
  conversation (TextView), a line to type, Send. The other side's window opens too only when
  they choose: a message to someone without the window open shows them a toast at the bottom
  right of the screen (S.TOAST: no window, nothing takes their keyboard) and the speech-bubble
  icon (NOTIFY slot 4) until they read it. Clicking the toast or the icon opens the
  conversation with the oldest unread message.
- Conversations are kept in memory while both are signed on (the last KEEP lines), so closing
  the window and opening it again shows them.
- Someone Away gets the message, and the sender is told once ("* bob is away"); someone
  Offline counts as not signed on, except to admins (presence.py).
"""

from . import permissions as perms
from .presence import AWAY, Presence
from .protocol import WFlag, GFlag, Icon, SLOT_IM, clean_text
from .ui import Window, Button, TextBox, TextView

TITLE = "Instant Message"
W, H = 360, 120
KEEP = 100
TOAST_SECS = 8
RECEIVE_KEY = "im_new_users_receive"     # settings table: 1 = New Users get IMs (default)

# (short: they also show on Who's Online's top line, 35 characters)
NO_SEND = "Your role can't send messages."
NEW_NO_SEND = "New users can't send messages."
NEW_NO_RECEIVE = "New users can't receive messages."


def is_new(db, session):
    """In the role new accounts get (the one the New User settings are about)."""
    return session.role_id is not None and session.role_id == db.default_role_id()


def new_users_send(db):
    """System Settings' "New users can send": the new-account role has im.send."""
    rid = db.default_role_id()
    return rid is not None and perms.IM_SEND in db.role_permissions(rid)


def set_new_users_send(db, on):
    rid = db.default_role_id()
    if rid is None:
        return None
    keys = db.role_permissions(rid)
    keys = keys | {perms.IM_SEND} if on else keys - {perms.IM_SEND}
    return db.set_role_permissions(rid, keys)


def new_users_receive(db):
    return db.setting(RECEIVE_KEY, "1") != "0"


def set_new_users_receive(db, on):
    with db.conn:
        db._set_setting(RECEIVE_KEY, 1 if on else 0)


class Conversation:
    def __init__(self, partner_id, partner_name):
        self.partner_id = partner_id
        self.partner_name = partner_name
        self.lines = []
        self.unread = 0
        self.win = None
        self.away_noted = False

    def add(self, line):
        self.lines = (self.lines + [line])[-KEEP:]
        if self.win is not None and self.win.shown:
            self.win.view.append(line)
            return True
        return False


class IMs:
    def __init__(self, server):
        self.server = server
        self.convs = {}                  # session -> {partner user id: Conversation}

    def online(self):
        return self.server.screens.online()

    def session_of(self, user_id):
        return next((s for s in self.online() if s.user_id == user_id), None)

    def conv(self, session, partner_id, partner_name):
        c = self.convs.setdefault(session, {}).get(partner_id)
        if c is None:
            c = self.convs[session][partner_id] = Conversation(partner_id, partner_name)
        return c

    # ---- the window ----

    def open(self, session, partner):
        """The conversation window with `partner` (a session); it's read now."""
        c = self.conv(session, partner.user_id, partner.user)
        c.unread = 0
        self.refresh_icon(session)
        win = c.win if c.win is not None and c.win.shown else None
        if win is not None:
            return win
        win = Window.centred("IM: %s" % partner.user, W, H,
                             flags=WFlag.CLOSE | WFlag.MOVABLE, on_close=lambda w: None)
        win.conv = c
        win.view = win.add(TextView(8, 4, 344, 88, list(c.lines)))
        win.entry = win.add(TextBox(8, 98, 280, 12))
        win.send_b = win.add(Button(296, 96, 56, 16, "Send", GFlag.DEFAULT,
                                    on_click=lambda b: self._send(b, c)))
        win.owner, win.partner = session, partner
        win.why = None
        c.win = win
        self._send_button(win)
        win.show(session)
        win.entry.focus()
        return win

    def _send_button(self, win):
        """Send greyed when this pair can't talk (for a rule, not just being away), and
        the reason said once in the conversation."""
        why = self.rule(win.owner, win.partner)
        win.send_b.enable(why is None)
        if why is not None and why != win.why:
            if win.shown:
                win.view.append("* " + why)
            else:
                win.view.lines.append("* " + why)
        win.why = why

    def settings_changed(self):
        """New User IM settings or someone's permissions changed: every IM window's Send
        button follows (Who's Online's are refreshed by the caller)."""
        for session, convs in self.convs.items():
            for c in convs.values():
                if c.win is not None and c.win.shown:
                    self._send_button(c.win)

    # ---- sending ----

    def rule(self, session, partner):
        """A rule that stops `session` messaging `partner` (whoever is signed on), or None."""
        db = self.server.db
        if not session.can(perms.IM_SEND):
            return NEW_NO_SEND if is_new(db, session) else NO_SEND
        if partner is not None and is_new(db, partner) and not new_users_receive(db):
            return NEW_NO_RECEIVE
        return None

    def problem(self, session, partner):
        """Why `session` can't send to `partner` (a session or None), or None."""
        if partner is session:
            return "That's you."
        why = self.rule(session, partner)
        if why:
            return why
        if partner is None or not Presence.visible(session, partner):
            return "That user isn't signed on."
        return None

    def _send(self, button, c):
        session = button.session
        text = clean_text(c.win.entry.value).strip() if c.win else ""
        partner = self.session_of(c.partner_id)
        problem = self.problem(session, partner)
        if problem:
            c.add("* " + problem.replace("That user", c.partner_name))
            return None
        if not text:
            return None
        c.win.entry.set_text("")
        self.send(session, partner, text)
        return None

    def send(self, session, partner, text):
        line = "%s: %s" % (session.user, text)
        mine = self.conv(session, partner.user_id, partner.user)
        mine.add(line)
        if partner.status == AWAY and not mine.away_noted:
            mine.away_noted = True
            mine.add("* %s is away and may not answer for a while." % partner.user)
        elif partner.status != AWAY:
            mine.away_noted = False
        theirs = self.conv(partner, session.user_id, session.user)
        if not theirs.add(line):                 # their window isn't open: a toast + the icon
            theirs.unread += 1
            partner.toast("IM from %s" % line, TOAST_SECS, SLOT_IM)
            self.refresh_icon(partner)
        session.log("IM to %s" % partner.user)

    # ---- the icon ----

    def refresh_icon(self, session):
        convs = self.convs.get(session, {}).values()
        n = sum(c.unread for c in convs)
        if n:
            who = [c.partner_name for c in convs if c.unread]
            session.set_notify(SLOT_IM, Icon.BUBBLE, ("%d new message%s from %s" % (
                n, "" if n == 1 else "s", ", ".join(who)))[:40])
        else:
            session.set_notify(SLOT_IM, Icon.NONE)

    def notify_click(self, session, slot):
        """The icon or the toast: the conversation with unread messages (the first one)."""
        for c in self.convs.get(session, {}).values():
            if c.unread:
                partner = self.session_of(c.partner_id)
                if partner is None:                  # gone: show what they said anyway
                    c.unread = 0
                    self.refresh_icon(session)
                    return session.alert(TITLE, "%s has signed off." % c.partner_name)
                return self.open(session, partner)
        return self.refresh_icon(session)

    # ---- people coming and going ----

    def disconnected(self, session):
        self.convs.pop(session, None)
        for s, convs in self.convs.items():
            c = convs.get(session.user_id)
            if c is not None:
                c.add("* %s signed off." % session.user)
