"""The Games window and matchmaking.

The Games window lists every game. A player picks one and clicks Join; they wait in that
game's queue. As soon as max_players are waiting the match starts. If a game allows fewer
(min_players < max_players), any waiting player can click "Start now" once min_players are in.
A game with `computer = True` asks first: "Wait for Others" (the queue) or "vs Computer..."
(how many computer players, then the game starts at once with game.computers set).

Only users whose role holds games.play may open the window, and each game is listed only for
users who also hold its Game.permission (games.play unless the game registers its own).
"""

import asyncio
import logging

from ..protocol import GFlag, WFlag
from ..session import call
from ..ui import (AreaWindow, Window, Label, add_buttons, closer, button_width,
                  MARGIN, BUTTON_W, BUTTON_GAP)
from .base import Player
from .challenge import ChallengeLobby

log = logging.getLogger("meganet")
WIN_GAMES = 3


class GameLobby:
    def __init__(self, game_classes):
        self.classes = list(game_classes)
        self.queues = {cls: [] for cls in self.classes}   # game class -> waiting sessions
        self.windows = {}                                  # session -> its Games window
        self.running = []                                  # Game objects in progress
        self.challenges = {cls: ChallengeLobby(self, cls)  # games with a lobby (challenge.py)
                           for cls in self.classes if getattr(cls, "challenge", False)}

    # ---- the Games window ----

    @staticmethod
    def may_play(session, cls):
        return session.can("games.play") and session.can(cls.permission)

    def open(self, session):
        if not session.can("games.play"):
            return session.alert("Games", "Your account can't play games.")
        a = AreaWindow("Games", WIN_GAMES, on_close=self._closed)
        win = a.win
        win.classes = [cls for cls in self.classes if self.may_play(session, cls)]
        win.head = a.heading("%d game%s to play." % (len(win.classes),
                                                     "" if len(win.classes) == 1 else "s"))
        win.list = a.list(self.rows(win.classes), self._selected, about=True)
        win.about = a.about_view
        win.join_b = a.command("Join", self._join, default=True)
        win.start_b = a.command("Start Now", self._start_now)
        win.leave_b = a.command("Leave Queue", self._unjoin)
        win.status = a.status("Pick a game and Join." if win.classes else
                              "There are no games for your account.")
        self.buttons(session, win)
        win.show(session)
        self.windows[session] = win
        return None

    def buttons(self, session, win):
        """Join needs a game picked; Start Now and Leave Queue a queue you're in (not for a
        game with a lobby: there you pick the opponent)."""
        picked = win.list.selected is not None and win.list.selected < len(win.classes)
        cls = self.waiting_for(session)
        win.join_b.enable(picked)
        win.start_b.enable(cls is not None and cls.min_players < cls.max_players)
        win.leave_b.enable(cls is not None)

    def rows(self, classes):
        rows = []
        for cls in classes:
            players = ("%d" % cls.min_players if cls.min_players == cls.max_players
                       else "%d-%d" % (cls.min_players, cls.max_players))
            waiting = (len(self.challenges[cls].seats) if cls in self.challenges
                       else len(self.queues[cls]))
            rows.append("%-16s %s players, %d waiting" % (cls.name[:16], players, waiting))
        return rows

    def refresh(self):
        for session, win in self.windows.items():
            win.list.set_rows(self.rows(win.classes))
            self.buttons(session, win)

    def permissions_changed(self, session):
        """The user's permissions changed: re-list the games, or close the window."""
        cls = self.waiting_for(session)
        if cls and not self.may_play(session, cls):
            self._dequeue(session)
        for lobby in self.challenges.values():
            lobby.permissions_changed(session)
        win = self.windows.get(session)
        if win is None:
            return
        if not session.can("games.play"):
            self.windows.pop(session)
            win.close()
            return
        win.classes = [c for c in self.classes if self.may_play(session, c)]
        win.list.set_rows(self.rows(win.classes))
        self.buttons(session, win)

    def _selected(self, listbox, index, double):
        win = listbox.window
        if listbox.selected is not None and listbox.selected < len(win.classes):
            win.about.set_lines([win.classes[listbox.selected].description])
        self.buttons(listbox.session, win)
        if double:
            return self._join(listbox)
        return None

    def _closed(self, window):
        self.windows.pop(window.session, None)
        self._dequeue(window.session)

    # ---- matchmaking ----

    def waiting_for(self, session):
        for cls, queue in self.queues.items():
            if session in queue:
                return cls
        return None

    def _dequeue(self, session):
        cls = self.waiting_for(session)
        if cls:
            self.queues[cls].remove(session)
            self.refresh()

    def _join(self, gadget):
        session, win = gadget.session, gadget.window
        if session.game:
            return session.alert("Games", "You are already playing.")
        if win.list.selected is None:
            return session.alert("Games", "Pick a game first.")
        cls = win.classes[win.list.selected]
        if not self.may_play(session, cls):
            return session.alert("Games", "Your account can't play %s." % cls.name)
        if cls in self.challenges:             # a game with a lobby: pick an opponent there
            return self.open_lobby(session, cls)
        caps = getattr(cls, "needs_caps", 0)
        if caps and (session.caps & caps) != caps:
            session.warn("%s refused: client caps $%02X" % (cls.name, session.caps))
            return session.alert("Games", "Your MegaNet client is too old for %s. Start "
                                 "the latest client and try again." % cls.name)
        problem = cls.join_problem(session)
        if problem:
            return session.alert(cls.name, problem)
        if self.waiting_for(session) is cls:
            return None
        if cls.computer:                       # wait for people, or play the computer now
            return self.ask_mode(session, cls)
        return self.queue(session, cls)

    def queue(self, session, cls):
        """Into cls's queue: the match starts when it's full (or on Start Now)."""
        if session.game:
            return session.alert("Games", "You are already playing.")
        self._dequeue(session)
        for game in self.running:              # a game with a free seat takes them now
            if type(game) is cls and not game.over and game.open_seat(session):
                return self.join_running(game, session)
        if getattr(cls, "start_at_once", False):   # (blackjack: a new table, alone for now)
            return self.start(cls, [session], queued=False)
        queue = self.queues[cls]
        queue.append(session)
        win = self.windows.get(session)
        if win is not None:
            win.status.set_text("Waiting for players for %s..." % cls.name)
        if len(queue) >= cls.max_players:
            return self.start(cls, queue[:cls.max_players])
        self.refresh()
        return None

    # ---- a game with computer players: how to play (dynamic window ids) ----

    def ask_mode(self, session, cls):
        """"Wait for Others" (the queue, Start Now with 2 or more) or "vs Computer...": then
        how many computer players, and the game starts at once."""
        def wait(button):
            button.window.close()
            if self.may_play(session, cls) and not session.game:
                return self.queue(session, cls)
            return None
        win = Window.centred("Play %s" % cls.name, 384, 40,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE)
        win.add(Label(MARGIN, 4, 368, 10, "How do you want to play %s?" % cls.name,
                      flags=GFlag.CENTRE))
        add_buttons(win, [("Wait for Others", wait, GFlag.DEFAULT),
                          ("vs Computer...", lambda b: self.ask_computers(b, session, cls), 0),
                          ("Cancel", closer, 0)], centre=True)
        win.show(session)

    def ask_computers(self, button, session, cls):
        button.window.close()
        most = cls.max_players - 1

        def go(b, n):
            b.window.close()
            if session.game:
                return session.alert("Games", "You are already playing.")
            if not self.may_play(session, cls):
                return None
            problem = cls.join_problem(session)
            if problem:
                return session.alert(cls.name, problem)
            self._dequeue(session)
            session.log("games: %s against %d computer player%s"
                        % (cls.name, n, "" if n == 1 else "s"))
            return self.start(cls, [session], queued=False, computers=n)
        specs = [(str(n), (lambda b, n=n: go(b, n)), GFlag.DEFAULT if n == 1 else 0)
                 for n in range(1, most + 1)] + [("Cancel", closer, 0)]
        small = 40 if most > 3 else BUTTON_W             # (1-5 and Cancel fit across)
        w = max(336, small * most + button_width("Cancel") + BUTTON_GAP * most + 2 * MARGIN)
        win = Window.centred("vs Computer", w, 40,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE)
        win.add(Label(MARGIN, 4, w - 2 * MARGIN, 10, "How many computer players?",
                      flags=GFlag.CENTRE))
        buttons = add_buttons(win, specs, centre=True)
        if small != BUTTON_W:                            # narrower number buttons
            x = (w - (small * most + button_width("Cancel") + BUTTON_GAP * most)) // 2
            for b in buttons:
                b.x = x
                if b.text != "Cancel":
                    b.w = small
                x += b.w + BUTTON_GAP
        win.show(session)

    def _start_now(self, gadget):
        session = gadget.session
        cls = self.waiting_for(session)
        if cls is None:
            return session.alert("Games", "Join a game first.")
        if not self.may_play(session, cls):
            self._dequeue(session)
            return session.alert("Games", "Your account can't play %s." % cls.name)
        queue = self.queues[cls]
        if len(queue) < cls.min_players:
            return session.alert("Games", "%s needs at least %d players."
                                 % (cls.name, cls.min_players))
        return self.start(cls, queue[:cls.max_players])

    def _unjoin(self, gadget):
        self._dequeue(gadget.session)
        gadget.window.status.set_text("")

    def open_lobby(self, session, cls):
        """The lobby of a game with `challenge = True` (challenge.py), in place of the Games
        window; out of any queue and any other game's lobby."""
        self._dequeue(session)
        for other_cls, lobby in self.challenges.items():
            if other_cls is not cls:
                lobby.leave(session)
        win = self.windows.pop(session, None)
        if win:
            win.on_close = None
            win.close()
        return self.challenges[cls].open(session)

    def join_running(self, game, session):
        """Into a game that's already running (Game.open_seat said yes)."""
        win = self.windows.pop(session, None)
        if win:
            win.close()
        p = Player(session)
        p.game = game
        session.game = p
        game.players.append(p)
        log.info("games: %s joins %s", session.user, game.name)
        self.refresh()
        return game.sit_down(p)

    async def start(self, cls, sessions, queued=True, computers=0, options=None):
        for s in sessions:
            if queued:
                self.queues[cls].remove(s)
            win = self.windows.pop(s, None)
            if win:
                win.close()
        self.refresh()
        game = cls()
        game._lobby = self
        game.computers = computers
        game.options = dict(options or {})
        game.players = [Player(s) for s in sessions]
        for p in game.players:
            p.game = game
            p.session.game = p
        self.running.append(game)
        log.info("games: %s started: %s", cls.name, ", ".join(p.name for p in game.players))
        await call(game.start(list(game.players)))
        if game.tick_interval and not game.over:
            game._ticker = asyncio.create_task(self._tick(game))

    async def _tick(self, game):
        while not game.over:
            await asyncio.sleep(game.tick_interval)
            if game.over:
                break
            try:
                await call(game.tick())
            except Exception:
                log.exception("games: %s tick failed", game.name)

    def game_ended(self, game):
        if game in self.running:
            self.running.remove(game)
        lobby = self.challenges.get(type(game))
        if lobby:
            lobby.refresh()                    # (its "playing" row goes)

    def disconnected(self, session):
        self.windows.pop(session, None)
        self._dequeue(session)
        for lobby in self.challenges.values():
            lobby.disconnected(session)
        if session.game:
            session.game.game.leave(session.game)
