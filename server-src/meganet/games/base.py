"""The Game base class that every MegaNet game subclasses. See README.md in this folder."""

from ..protocol import WFlag
from ..ui import Window


class Player:
    """One person in a game. `name` is their screen name; `session` is their connection."""

    def __init__(self, session):
        self.session = session
        self.game = None
        self.windows = []

    @property
    def name(self):
        return self.session.user

    def alert(self, title, text):
        self.session.alert(title, text)

    def __repr__(self):
        return "<Player %s>" % self.name


class Game:
    """Subclass this, set the class attributes, and override the hooks you need.

    One Game object is made for each match. The framework (lobby.py) calls start() with the
    players once enough people have joined, then routes every click and key in the game's
    windows to on_click / on_key.
    """

    name = ""                 # shown in the Games list; a class without a name isn't listed
    description = ""
    min_players = 2
    max_players = 2
    tick_interval = 0         # seconds between tick() calls; 0 = no ticks
    permission = "games.play" # who may play: a key from permissions.py (register your own)
    computer = False          # True: Join offers "vs Computer..." (the game plays the seats)

    @classmethod
    def join_problem(cls, session):
        """Why `session` can't join this game now (shown to them), or None. Poker: not enough
        credits."""
        return None

    def open_seat(self, session):
        """True if `session` may sit down in this game while it's running (lobby.queue puts
        them in at once, then calls sit_down). By default games start with their players."""
        return False

    def sit_down(self, player):
        """`player` joined while the game runs (open_seat said yes); self.players has them."""

    def __init__(self):
        self.players = []     # Player objects still in the game
        self.computers = 0    # computer players asked for (set before start(); computer games)
        self.over = False
        self._lobby = None    # set by the framework

    # ---- hooks: override these ----

    def start(self, players):
        """The match begins. Open a window for each player here."""

    def on_click(self, player, window, gadget):
        """A button (or other gadget) in one of this game's windows was clicked."""

    def on_select(self, player, window, gadget, index, double):
        """A list row or check box in one of this game's windows changed."""

    def on_key(self, player, window, gadget, key):
        """A key was pressed in a RAWKEYS gadget. `key` is the ASCII code."""

    def on_leave(self, player):
        """`player` has left (Quit, closed the window or disconnected); self.players no longer
        holds them. By default the game ends if too few players are left."""
        if not self.over and len(self.players) < self.min_players:
            for p in self.players:
                p.alert(self.name, "%s left the game." % player.name)
            self.end()

    def tick(self):
        """Called every tick_interval seconds while the game runs (if tick_interval > 0)."""

    # ---- helpers for game code ----

    def window(self, player, title, x, y, w, h, flags=WFlag.CLOSE | WFlag.MOVABLE):
        """Make a window for `player` whose gadget events go to this game's hooks. Add gadgets,
        then call self.show(player, window)."""
        win = Window(title, x, y, w, h, flags, on_close=lambda wnd: self.leave(player))
        win.player = player

        def route(gadget, event, *args):
            if self.over or player not in self.players:
                return None
            if event == "click":
                return self.on_click(player, win, gadget)
            if event == "select":
                return self.on_select(player, win, gadget, *args)
            if event == "key":
                return self.on_key(player, win, gadget, *args)
            return None
        win.on_event = route
        return win

    def credit(self, session, reason, beat=None):
        """Pay a player from the bank (bank.py): "game played" (each player, once a game or
        round is done) or "game won" (`beat`: the session of the person beaten, or None for
        the computer or several). Returns the credits paid."""
        if session is None or session.user_id is None:
            return 0
        return session.server.screens.bank.earn(
            session.user_id, reason, beat.user_id if beat is not None else None, self.name)

    def show(self, player, window):
        window.show(player.session)
        if window not in player.windows:
            player.windows.append(window)

    def leave(self, player):
        """Take `player` out of the game (closing their windows), then call on_leave."""
        if player not in self.players:
            return
        self.players.remove(player)
        self._release(player)
        self.on_leave(player)

    def end(self):
        """The match is over: close every player's game windows."""
        if self.over:
            return
        self.over = True
        for p in list(self.players):
            self._release(p)
        if self._lobby:
            self._lobby.game_ended(self)

    def _release(self, player):
        for win in player.windows:
            win.on_close = None
            win.close()
        player.windows.clear()
        if player.session.game is player:
            player.session.game = None
