"""Areas > Voting (polls.vote): polls with a question and 2-6 choices. Everyone votes once in
each; Results shows a bar for each choice. A poll can have an end date: after it, nobody
can vote and only the results are shown. Holders of polls.manage (Moderators and up) set up
new polls and delete them.

    32 = Voting: the polls (newest first, with "open", "until 11-30", "voted" or "ended"),
         the picked one's description (more background on the question) and choices, Vote
         and Results; managers also New Poll... and Delete
    33 = Results: the question, then a bar (a Progress gadget) per choice with its votes and
         share, the total, and OK. It follows new votes while it's open.
    34 = New Poll (modal): the question, a description (a few lines), six choice boxes, an
         end date
    35 = Delete Poll? (modal)
"""

import datetime
import time

from . import permissions as perms
from .compose import refuse
from .protocol import WFlag, GFlag, clean_text
from .ui import (add_buttons, closer, Window, Button, Label, TextBox, ListBox, Progress,
                 TextArea, TextView, AreaWindow, AREA_TOP, AREA_LIST_W, AREA_BOTTOM)

VOTE, MANAGE = perms.POLLS_VOTE, perms.POLLS_MANAGE
WIN_VOTING, WIN_RESULTS, WIN_NEW_POLL, WIN_DELETE_POLL = 32, 33, 34, 35
TITLE = "Voting"
QUESTION_MAX = 60
DESCRIPTION_MAX = 600            # characters of background, over a few lines
CHOICE_MAX = 30
CHOICES_MAX = 6
QUESTION_COLS = 35               # of the question in the list (then its state: 11 at most)


def ended(poll, now=None):
    return poll["ends"] is not None and (now or time.time()) >= poll["ends"]


def end_day(poll):
    return time.strftime("%m-%d", time.localtime(poll["ends"] - 1))


def parse_end(text, now=None):
    """A YYYY-MM-DD end date -> the time voting stops (the end of that day, local time),
    None for blank; ValueError with a message for anything else."""
    text = text.strip()
    if not text:
        return None
    try:
        day = datetime.datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValueError("The end date is YYYY-MM-DD, or blank for none.")
    if day.year > datetime.date.today().year + 10:
        raise ValueError("The end date is more than ten years away.")
    try:
        ends = int(time.mktime((day + datetime.timedelta(days=1)).timetuple()))
    except (OverflowError, ValueError):      # (Windows: before 1970)
        raise ValueError("The end date has passed already.")
    if ends <= (now or time.time()):
        raise ValueError("The end date has passed already.")
    return ends


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


class Polls:
    def __init__(self, server):
        self.server = server
        self.windows = {}                # session -> VotingWindow
        self.results = {}                # session -> (poll id, Results window)

    @property
    def db(self):
        return self.server.db

    def open(self, session):
        if not session.can(VOTE):
            return refuse(session, TITLE, VOTE)
        v = self.windows.get(session) or VotingWindow(self, session)
        return v.show()

    def changed(self, poll_id=None):
        """A vote or a poll came or went: every Voting and Results window follows."""
        for v in list(self.windows.values()):
            v.refresh()
        for session, (pid, win) in list(self.results.items()):
            if not win.shown:
                self.results.pop(session, None)
            elif poll_id is None or pid == poll_id:
                self.show_results(session, pid, keep=win)

    def permissions_changed(self, session):
        v = self.windows.get(session)
        if v is None:
            return
        if not session.can(VOTE):
            v.close()
        else:
            v.show()                     # (the manager buttons may come or go)

    def disconnected(self, session):
        self.windows.pop(session, None)
        self.results.pop(session, None)

    # ---- Results: a bar per choice ----

    def show_results(self, session, poll_id, keep=None):
        """The results window for a poll; keep = the open one, updated in place."""
        poll = self.db.poll(poll_id)
        if poll is None:
            if keep is not None:
                keep.close()
            return None
        choices = self.db.poll_choices(poll_id)
        total = sum(c["votes"] for c in choices)
        mine = self.db.poll_vote_of(poll_id, session.user_id)
        rows = []
        for c in choices:
            pct = round(100 * c["votes"] / total) if total else 0
            rows.append((("* " if c["id"] == mine else "") + c["text"], pct,
                         "%d (%d%%)" % (c["votes"], pct)))
        if ended(poll):
            foot = "%s. Voting ended %s." % (plural(total, "vote"), end_day(poll))
        elif poll["ends"] is not None:
            foot = "%s so far; voting is open until %s." % (plural(total, "vote"), end_day(poll))
        else:
            foot = "%s so far." % plural(total, "vote")
        if mine is not None:
            foot += " * = your vote."
        if keep is not None and len(keep.bars) == len(rows):
            for (label, bar, count), (text, pct, n) in zip(keep.bars, rows):
                label.set_text(text)
                bar.set_percent(pct)
                count.set_text(n)
            keep.foot.set_text(foot)
            return keep
        h = 18 + 16 * len(rows) + 34
        win = Window.centred("Results", 440, h, flags=WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_RESULTS, minimize=False)
        win.add(Label(8, 2, 424, 10, poll["question"][:53], GFlag.CENTRE))
        win.bars = []
        for i, (text, pct, n) in enumerate(rows):
            y = 18 + 16 * i
            win.bars.append((win.add(Label(8, y + 1, 176, 10, text[:22])),
                             win.add(Progress(188, y, 160, 12, percent=pct)),
                             win.add(Label(356, y + 1, 76, 10, n))))
        win.foot = win.add(Label(8, 18 + 16 * len(rows) + 2, 424, 10, foot[:53]))
        add_buttons(win, [("OK", closer, GFlag.DEFAULT)], centre=True)
        self.results[session] = (poll_id, win)
        win.show(session)
        return win


class VotingWindow:
    def __init__(self, polls, session):
        self.polls = polls
        self.session = session
        self.win = None
        self.ids = []                    # the listed polls' ids
        self.poll_id = None              # the picked one
        self.choice_ids = []
        self.choice_id = None

    @property
    def db(self):
        return self.polls.db

    @property
    def manager(self):
        return self.session.can(MANAGE)

    # ---- the rows ----

    def state(self, poll, mine):
        if ended(poll):
            return "ended"
        if mine is not None:
            return "voted"
        return "until %s" % end_day(poll) if poll["ends"] is not None else "open"

    def heading(self):
        polls = self.db.polls()
        if not polls:
            return "No polls yet."
        n_open = sum(1 for p in polls if not ended(p))
        return "%d poll%s, %d open for voting." % (len(polls), "" if len(polls) == 1 else "s",
                                                   n_open)

    def poll_rows(self):
        polls = self.db.polls()
        self.ids = [p["id"] for p in polls]
        return ["%-*s %s" % (QUESTION_COLS, p["question"][:QUESTION_COLS],
                             self.state(p, self.db.poll_vote_of(p["id"], self.session.user_id)))
                for p in polls]

    def choice_rows(self):
        poll = self.db.poll(self.poll_id) if self.poll_id in self.ids else None
        if poll is None:
            self.choice_ids = []
            return []
        choices = self.db.poll_choices(poll["id"])
        self.choice_ids = [c["id"] for c in choices]
        mine = self.db.poll_vote_of(poll["id"], self.session.user_id)
        if ended(poll):                  # over: only the results
            total = sum(c["votes"] for c in choices) or 1
            return ["%-*s %3d%%" % (CHOICE_MAX, c["text"], round(100 * c["votes"] / total))
                    for c in choices]
        return [("* " if c["id"] == mine else "  ") + c["text"] for c in choices]

    def description(self):
        """The picked poll's background, as lines for the text view (the client wraps)."""
        poll = self.db.poll(self.poll_id) if self.poll_id in self.ids else None
        if poll is None:
            return []
        return poll["description"].split("\n") if poll["description"] else ["(No description.)"]

    def hint(self):
        poll = self.db.poll(self.poll_id) if self.poll_id in self.ids else None
        if poll is None:
            return "Pick a poll." if self.ids else (
                "No polls yet." + (" New... sets one up." if self.manager else ""))
        if ended(poll):
            return "Voting has ended: these are the results."
        if self.db.poll_vote_of(poll["id"], self.session.user_id) is not None:
            return "You've voted (*). Results shows how it's going."
        return "Pick your choice and Vote. You can vote once."

    # ---- the window ----

    def show(self, status=None):
        self.polls.windows[self.session] = self
        a = AreaWindow(TITLE, WIN_VOTING, on_close=self._closed)
        win = a.win
        rows = self.poll_rows()
        self.head = a.heading(self.heading())
        # the left side: the polls, the picked one's background, its choices
        win.add(Label(8, AREA_TOP, AREA_LIST_W, 10, "%-*s %s" % (QUESTION_COLS, "Poll",
                                                                 "State")))
        self.list = win.add(ListBox(8, AREA_TOP + 12, AREA_LIST_W, 38, rows,
                                    on_select=self._pick))
        self.about = win.add(TextView(8, 68, AREA_LIST_W, 28, self.description()))
        self.choices = win.add(ListBox(8, 100, AREA_LIST_W, AREA_BOTTOM - 100,
                                       self.choice_rows(), on_select=self._pick_choice))
        self.vote_b = a.command("Vote", self._vote, default=True)
        self.results_b = a.command("Results", self._results)
        self.new_b = self.delete_b = None
        if self.manager:
            a.section("Admin Tools")
            self.new_b, self.delete_b = a.pair(("New...", self._new), ("Delete", self._delete))
        self.status = a.status(status or self.hint())
        self.win = win
        self._select()
        self.buttons()
        win.show(self.session)
        return self

    def _select(self):
        """The picked poll and choice highlighted again (before or after it's shown)."""
        if self.poll_id in self.ids:
            self.list.selected = self.ids.index(self.poll_id)
            if self.win.shown:
                self.list.set_value(self.list.selected)
        if self.choice_id in self.choice_ids:
            self.choices.selected = self.choice_ids.index(self.choice_id)
            if self.win.shown:
                self.choices.set_value(self.choices.selected)
        else:
            self.choice_id = None

    def buttons(self):
        poll = self.db.poll(self.poll_id) if self.poll_id in self.ids else None
        can_vote = (poll is not None and not ended(poll) and self.choice_id is not None
                    and self.db.poll_vote_of(poll["id"], self.session.user_id) is None)
        self.vote_b.enable(can_vote)
        self.results_b.enable(poll is not None)
        if self.delete_b is not None:
            self.delete_b.enable(poll is not None)

    def refresh(self, status=None):
        if self.win is None or not self.win.shown:
            return
        self.list.set_rows(self.poll_rows())
        self.head.set_text(self.heading())
        if self.poll_id not in self.ids:
            self.poll_id = self.choice_id = None
        self.choices.set_rows(self.choice_rows())
        self.about.set_lines(self.description())
        self._select()
        self.status.set_text(status or self.hint())
        self.buttons()

    def say(self, text):
        self.status.set_text(text)

    def close(self):
        if self.win is not None:
            self.win.close()
        self._closed(self.win)

    def _closed(self, window):
        if self.polls.windows.get(self.session) is self:
            del self.polls.windows[self.session]

    def _ok(self, key=VOTE):
        if not self.session.can(key):
            refuse(self.session, TITLE, key)
            return False
        return True

    # ---- picking ----

    def _pick(self, listbox, index, double):
        if not self._ok() or listbox.selected is None:
            return None
        pid = self.ids[listbox.selected]
        if pid != self.poll_id:
            self.poll_id, self.choice_id = pid, None
            self.choices.set_rows(self.choice_rows())
            self.about.set_lines(self.description())
            self.say(self.hint())
        self.buttons()
        return self._results(None) if double else None

    def _pick_choice(self, listbox, index, double):
        if not self._ok() or listbox.selected is None or self.poll_id not in self.ids:
            return None
        poll = self.db.poll(self.poll_id)
        if poll is None or ended(poll):
            self.choice_id = None
            return self.buttons()
        self.choice_id = self.choice_ids[listbox.selected]
        self.buttons()
        return self._vote(None) if double else None

    # ---- voting and results ----

    def _vote(self, button):
        if not self._ok():
            return None
        poll = self.db.poll(self.poll_id) if self.poll_id in self.ids else None
        if poll is None or self.choice_id not in self.choice_ids:
            return self.say("Pick a poll and a choice first.")
        if ended(poll):
            self.refresh()
            return self.say("Voting on that poll has ended.")
        if not self.db.vote(poll["id"], self.session.user_id, self.choice_id):
            self.refresh()
            return self.say("You've already voted in that poll.")
        text = next(c["text"] for c in self.db.poll_choices(poll["id"])
                    if c["id"] == self.choice_id)
        self.session.log("voted in poll %d" % poll["id"])
        self.polls.changed(poll["id"])
        return self.say("Your vote for %s is in. Thanks!" % text[:CHOICE_MAX])

    def _results(self, button):
        if not self._ok() or self.poll_id not in self.ids:
            return None
        return self.polls.show_results(self.session, self.poll_id)

    # ---- managers: New Poll..., Delete ----

    def _new(self, button):
        if not self._ok(MANAGE):
            return None
        win = Window.centred("New Poll", 440, 152,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE, win_id=WIN_NEW_POLL)
        win.add(Label(8, 4, 100, 10, "Question:"))
        win.question = win.add(TextBox(112, 2, 320, 12))
        win.add(Label(8, 20, 100, 10, "Description:"))
        win.about = win.add(TextArea(112, 18, 320, 38))
        win.add(Label(8, 62, 100, 10, "Choices:"))
        win.boxes = [win.add(TextBox(112 + 164 * (i % 2), 60 + 16 * (i // 2), 156, 12))
                     for i in range(CHOICES_MAX)]
        win.add(Label(8, 112, 264, 10, "Ends (YYYY-MM-DD, or blank):"))
        win.ends = win.add(TextBox(280, 110, 96, 12))
        win.status = win.add(Label(8, 126, 216, 10, "2 to %d choices." % CHOICES_MAX))
        create, _ = add_buttons(win, [("Create", self._create, GFlag.DEFAULT),
                                      ("Cancel", closer, 0)])
        create.needs = win.question
        win.show(self.session)
        return None

    def _create(self, button):
        win = button.window
        if not self._ok(MANAGE):
            return win.close()
        question = clean_text(win.question.value).strip()
        about = "\n".join(clean_text(line).rstrip() for line in win.about.lines).strip()
        choices = [clean_text(b.value).strip() for b in win.boxes]
        choices = [c for c in choices if c]
        if not 1 <= len(question) <= QUESTION_MAX:
            return win.status.set_text("The question is 1-%d characters." % QUESTION_MAX)
        if len(about) > DESCRIPTION_MAX:
            return win.status.set_text("The description is at most %d characters." % DESCRIPTION_MAX)
        if len(choices) < 2:
            return win.status.set_text("A poll needs at least 2 choices.")
        if any(len(c) > CHOICE_MAX for c in choices):
            return win.status.set_text("Choices are at most %d characters." % CHOICE_MAX)
        if len({c.lower() for c in choices}) != len(choices):
            return win.status.set_text("Two of the choices are the same.")
        try:
            ends = parse_end(win.ends.value)
        except ValueError as e:
            return win.status.set_text(str(e))
        win.close()
        pid = self.db.create_poll(question, choices, ends, self.session.user_id, about)
        self.session.log("set up poll %d: %s" % (pid, question))
        self.poll_id, self.choice_id = pid, None
        self.polls.changed()
        return self.refresh("The poll is up.")

    def _delete(self, button):
        if not self._ok(MANAGE):
            return None
        poll = self.db.poll(self.poll_id) if self.poll_id in self.ids else None
        if poll is None:
            return self.say("Pick a poll first.")
        win = Window.centred("Delete Poll", 360, 50,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_DELETE_POLL)
        win.poll_id = poll["id"]
        win.add(Label(8, 4, 344, 10, "Delete \"%s\" and its %s?" % (
            poll["question"][:20], plural(poll["votes"], "vote"))))
        win.add(Label(8, 16, 344, 10, "This can't be undone."))
        add_buttons(win, [("Delete", self._confirm_delete, 0),
                          ("Cancel", closer, GFlag.DEFAULT)], centre=True)
        win.show(self.session)
        return None

    def _confirm_delete(self, button):
        win = button.window
        win.close()
        if not self._ok(MANAGE):
            return None
        poll = self.db.poll(win.poll_id)
        if poll is None:
            return None
        self.db.delete_poll(poll["id"])
        self.session.log("deleted poll %d: %s" % (poll["id"], poll["question"]))
        self.poll_id = self.choice_id = None
        self.polls.changed()
        return self.refresh("Deleted the poll.")
