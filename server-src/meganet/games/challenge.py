"""A game's lobby, for two-player games that set `challenge = True` (chess): instead of
waiting in a queue for whoever comes next, players wait in the lobby and pick an opponent.

    Games > (the game) > Join opens "<Game> Lobby" (window 51): everyone waiting there, and the
    games being played. Pick someone and click Challenge...; they get "<you> challenges you to
    a game of <Game>." with Accept / Decline (window 52). Accept starts the game for the two
    (the challenger first in game.players) and takes both out of the lobby; Decline, or
    either leaving, tells the other. One challenge out at a time; several may come in (shown
    one after another). Cancel withdraws yours.

A game may set `needs_caps` (protocol.Caps) for what its window needs from the client, and
`ranked = True` for a Rankings... button (rankings.py: its players, best first).
"""

from ..protocol import GFlag, WFlag
from ..ui import AreaWindow, Window, Label, add_buttons, MARGIN
from . import rankings

WIN_GAME_LOBBY = 51
WIN_CHALLENGED = 52
COLUMNS = "%-12s%s" % ("Player", "State")          # (the rows: refresh())


class Seat:
    """One person in the lobby."""

    def __init__(self, session):
        self.session = session
        self.win = None
        self.rows = []              # the sessions the list shows, row by row (None: a game)
        self.out = None             # the Seat they've challenged
        self.incoming = []          # Seats challenging them, oldest first
        self.asking = None          # the one window 52 is asking about


class ChallengeLobby:
    def __init__(self, games, cls):
        self.games = games          # the GameLobby (games/lobby.py)
        self.cls = cls
        self.seats = {}             # session -> Seat

    @property
    def title(self):
        return "%s Lobby" % self.cls.name

    @property
    def levels(self):
        """The computer's levels, for a game that can be played against it (Chess)."""
        return tuple(getattr(self.cls, "computer_levels", ()))

    # ---- coming and going ----

    def open(self, session):
        if session.game:
            return session.alert(self.title, "You are already playing.")
        if not self.games.may_play(session, self.cls):
            return session.alert(self.title, "Your account can't play %s." % self.cls.name)
        caps = getattr(self.cls, "needs_caps", 0)
        if caps and (session.caps & caps) != caps:
            session.warn("%s lobby refused: client caps $%02X" % (self.cls.name, session.caps))
            return session.alert(self.title, "Your MegaNet client is too old for %s. Start "
                                 "the latest client and try again." % self.cls.name)
        seat = self.seats.get(session)
        if seat is None:
            seat = self.seats[session] = Seat(session)
            session.log("%s lobby: joined" % self.cls.name)
        self._window(seat)
        self.refresh()
        return None

    def _window(self, seat):
        a = AreaWindow(self.title, WIN_GAME_LOBBY, on_close=lambda w: self.leave(seat.session))
        seat.head = a.heading("Waiting for a game of %s:" % self.cls.name)
        seat.list = a.list([], lambda g, i, d: self._picked(seat, i, d), columns=COLUMNS)
        seat.challenge_b = a.command("Challenge...", lambda b: self.challenge(seat),
                                     default=True)
        seat.cancel_b = a.command("Cancel Challenge", lambda b: self.withdraw(seat))
        if self.levels:
            a.command("Play Computer...", lambda b: self.ask_level(seat))
        if getattr(self.cls, "ranked", False):
            a.command("Rankings...", lambda b: rankings.show(seat.session, self.cls.name))
        seat.status = a.status("")
        seat.win = a.win
        self._buttons(seat)
        a.win.show(seat.session)

    def leave(self, session, why=None):
        """Out of the lobby (its window closed, signed off, or into a game): every
        challenge to or from them is off, and the others are told `why` (default: "X left
        the lobby.")."""
        seat = self.seats.pop(session, None)
        if seat is None:
            return
        why = why or "%s left the lobby." % session.user
        if seat.out is not None:
            target = seat.out
            seat.out = None
            if seat in target.incoming:
                target.incoming.remove(seat)
                if target.asking is seat:
                    self._close_ask(target)
                    self._ask(target)
                target.session.toast(why)
        for other in list(seat.incoming):
            self._drop(other, seat, why)
        if seat.win is not None:
            seat.win.on_close = None
            seat.win.close()
        if seat.asking is not None:
            self._close_ask(seat)
        self.refresh()

    def disconnected(self, session):
        self.leave(session)

    def permissions_changed(self, session):
        if session in self.seats and not self.games.may_play(session, self.cls):
            self.leave(session)
            session.alert(self.title, "Your account can't play %s now." % self.cls.name)

    # ---- the list ----

    def refresh(self):
        playing = [g for g in self.games.running if isinstance(g, self.cls) and not g.over]
        for seat in self.seats.values():
            rows, who = [], []
            for other in sorted(self.seats.values(), key=lambda s: s.session.user.lower()):
                state = "you" if other is seat else (
                    "challenging you" if other in seat.incoming else
                    "you challenged" if seat.out is other else
                    "waiting")
                rows.append("%-12s%s" % (other.session.user, state))
                who.append(other)
            for g in playing:
                bot = getattr(g, "bot", None)
                rows.append("%-12splaying %s" % (
                    g.players[0].name if g.players else "?",
                    " vs ".join([p.name for p in g.players[1:]] + ([bot.name] if bot else []))))
                who.append(None)
            seat.rows = who
            seat.list.set_rows(rows)
            self._buttons(seat)

    def _picked(self, seat, index, double):
        self._buttons(seat)
        if double:
            return self.challenge(seat)
        return None

    def _target(self, seat):
        i = seat.list.selected
        if i is None or i >= len(seat.rows):
            return None
        return seat.rows[i]

    def _buttons(self, seat):
        target = self._target(seat)
        seat.challenge_b.enable(seat.out is None and target is not None and target is not seat)
        seat.cancel_b.enable(seat.out is not None)
        if seat.out is not None:
            seat.status.set_text("Waiting for %s to answer..." % seat.out.session.user)
        elif not seat.status.text or seat.status.text.startswith("Waiting for"):
            seat.status.set_text("Pick an opponent and Challenge them." if len(self.seats) > 1
                                 else "Nobody else is waiting: Play Computer?" if self.levels
                                 else "Nobody else is waiting yet.")

    # ---- playing the computer (a dynamic window id) ----

    def ask_level(self, seat):
        if self.seats.get(seat.session) is not seat or not self.levels:
            return None
        win = Window.centred("Play the Computer", 336, 40,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE)
        win.add(Label(MARGIN, 4, 320, 10, "How well should it play?", flags=GFlag.CENTRE))
        specs = [(lv, (lambda b, lv=lv: self.play_computer(b, seat, lv)),
                  GFlag.DEFAULT if lv == "Normal" else 0) for lv in self.levels]
        add_buttons(win, specs + [("Cancel", lambda b: b.window.close(), 0)], centre=True)
        win.show(seat.session)
        return None

    async def play_computer(self, button, seat, level):
        button.window.close()
        session = seat.session
        if self.seats.get(session) is not seat or session.game:
            return None
        if not self.games.may_play(session, self.cls):
            return session.alert(self.title, "Your account can't play %s." % self.cls.name)
        self.leave(session, "%s started a game." % session.user)
        session.log("%s: game with the computer (%s)" % (self.cls.name, level))
        await self.games.start(self.cls, [session], queued=False, computers=1,
                               options={"level": level})
        self.refresh()
        return None

    # ---- challenges ----

    def challenge(self, seat):
        if self.seats.get(seat.session) is not seat:
            return None
        target = self._target(seat)
        if target is None or target is seat or target not in self.seats.values():
            return seat.session.alert(self.title, "Pick someone who's waiting first.")
        if seat.out is not None:
            return seat.session.alert(self.title, "You have already challenged %s."
                                      % seat.out.session.user)
        if target.out is seat:                 # they challenged you first: that's a yes
            return self.accept(target, seat)
        seat.out = target
        target.incoming.append(seat)
        seat.session.log("%s lobby: challenged %s" % (self.cls.name, target.session.user))
        self._ask(target)
        self.refresh()
        return None

    def withdraw(self, seat):
        if seat.out is not None:
            other = seat.out
            self._drop(seat, other, None)
            other.session.toast("%s withdrew the challenge." % seat.session.user)
            self.refresh()

    def _drop(self, challenger, target, why):
        """challenger's challenge to target is off (why: told to the challenger)."""
        if challenger.out is target:
            challenger.out = None
        if challenger in target.incoming:
            target.incoming.remove(challenger)
            if target.asking is challenger:
                self._close_ask(target)
                self._ask(target)
        if why and challenger.session in self.seats:
            challenger.session.toast(why)
            challenger.status.set_text(why)

    def _ask(self, seat):
        """Window 52: the oldest challenge waiting for an answer, if any."""
        if seat.asking is not None or not seat.incoming:
            return
        challenger = seat.incoming[0]
        seat.asking = challenger
        win = Window.centred("Challenge", 300, 56, win_id=WIN_CHALLENGED,
                             flags=WFlag.CLOSE | WFlag.MOVABLE,
                             on_close=lambda w: self._answer(seat, challenger, False))
        for i, line in enumerate(("%s challenges you to" % challenger.session.user,
                                  "a game of %s." % self.cls.name)):
            win.add(Label(MARGIN, 6 + 12 * i, 300 - 2 * MARGIN, 10, line[:35],
                          flags=GFlag.CENTRE))
        add_buttons(win, [("Accept", lambda b: self._answer(seat, challenger, True),
                           GFlag.DEFAULT),
                          ("Decline", lambda b: self._answer(seat, challenger, False), 0)],
                    centre=True)
        seat.ask_win = win
        win.show(seat.session)
        seat.session.sound(1)

    def _close_ask(self, seat):
        win = getattr(seat, "ask_win", None)
        seat.asking = seat.ask_win = None
        if win is not None:
            win.on_close = None
            win.close()

    def _answer(self, seat, challenger, yes):
        if seat.asking is not challenger:
            return None
        self._close_ask(seat)
        if challenger not in seat.incoming:
            return None
        if yes:
            return self.accept(challenger, seat)
        self._drop(challenger, seat, "%s declined your challenge." % seat.session.user)
        seat.session.log("%s lobby: declined %s" % (self.cls.name, challenger.session.user))
        self._ask(seat)
        self.refresh()
        return None

    async def accept(self, challenger, seat):
        a, b = challenger.session, seat.session
        if a.game or b.game:
            return None
        challenger.out = None                  # (this one's settled: no "left" for them)
        if challenger in seat.incoming:
            seat.incoming.remove(challenger)
        for s in (a, b):
            self.leave(s, "%s started a game." % s.user)
        a.log("%s: game with %s" % (self.cls.name, b.user))
        await self.games.start(self.cls, [a, b], queued=False)
        self.refresh()
        return None
