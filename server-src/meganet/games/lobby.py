"""The Games window and matchmaking.

The Games window lists every game. A player picks one and clicks Join; they wait in that
game's queue. As soon as max_players are waiting the match starts. If a game allows fewer
(min_players < max_players), any waiting player can click "Start now" once min_players are in.

Only users whose role holds games.play may open the window, and each game is listed only for
users who also hold its Game.permission (games.play unless the game registers its own).
"""

import asyncio
import logging

from ..session import call
from ..ui import Window, Button, Label, ListBox
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
        win = Window("Games", 120, 24, 400, 150, win_id=WIN_GAMES, on_close=self._closed)
        win.add(Label(8, 4, 380, 10, "Pick a game and click Join."))
        win.classes = [cls for cls in self.classes if self.may_play(session, cls)]
        win.list = win.add(ListBox(8, 18, 380, 80, self.rows(win.classes),
                                   on_select=self._selected))
        win.status = win.add(Label(8, 102, 380, 10, ""))
        win.add(Button(8, 118, 80, 16, "Join", on_click=self._join))
        win.add(Button(96, 118, 88, 16, "Start Now", on_click=self._start_now))
        win.add(Button(192, 118, 104, 16, "Leave Queue", on_click=self._unjoin))
        win.show(session)
        self.windows[session] = win
        return None

    def rows(self, classes):
        rows = []
        for cls in classes:
            players = ("%d" % cls.min_players if cls.min_players == cls.max_players
                       else "%d-%d" % (cls.min_players, cls.max_players))
            waiting = (len(self.challenges[cls].seats) if cls in self.challenges
                       else len(self.queues[cls]))
            rows.append("%s (%s players), %d waiting" % (cls.name, players, waiting))
        return rows

    def refresh(self):
        for win in self.windows.values():
            win.list.set_rows(self.rows(win.classes))

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

    def _selected(self, listbox, index, double):
        if listbox.selected is not None:
            listbox.window.status.set_text(listbox.window.classes[listbox.selected].description)
        if double:
            return self._join(listbox)

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
        if self.waiting_for(session) is cls:
            return None
        self._dequeue(session)
        queue = self.queues[cls]
        queue.append(session)
        win.status.set_text("Waiting for players for %s..." % cls.name)
        if len(queue) >= cls.max_players:
            return self.start(cls, queue[:cls.max_players])
        self.refresh()
        return None

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

    async def start(self, cls, sessions, queued=True):
        for s in sessions:
            if queued:
                self.queues[cls].remove(s)
            win = self.windows.pop(s, None)
            if win:
                win.close()
        self.refresh()
        game = cls()
        game._lobby = self
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
