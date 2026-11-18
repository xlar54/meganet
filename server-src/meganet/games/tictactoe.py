"""Tic-tac-toe for two players, built only from buttons: a demo of the Game interface.

Each player gets a window with a 3x3 grid of buttons (gadgets 1-9), a status line, and
Rematch / Quit buttons. X always moves first; after each round the players swap marks.
"""

from ..protocol import WFlag
from ..ui import Button, Label
from .base import Game

LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8),       # rows
         (0, 3, 6), (1, 4, 7), (2, 5, 8),       # columns
         (0, 4, 8), (2, 4, 6)]                  # diagonals

STATUS = 10
REMATCH = 11
QUIT = 12


class TicTacToe(Game):
    name = "Tic-Tac-Toe"
    description = "Get three in a row on a 3x3 grid. X moves first."
    min_players = 2
    max_players = 2

    def start(self, players):
        self.mark = {players[0]: "X", players[1]: "O"}
        self.windows = {}
        for i, p in enumerate(players):
            win = self.window(p, "Tic-Tac-Toe", 60 + i * 260, 40, 200, 124, WFlag.CLOSE)
            for cell in range(9):
                row, col = divmod(cell, 3)
                win.add(Button(10 + col * 34, 6 + row * 24, 30, 20, " ", gid=cell + 1))
            win.add(Label(116, 6, 80, 60, "", gid=STATUS))
            win.add(Button(10, 84, 80, 16, "Rematch", gid=REMATCH))
            win.add(Button(100, 84, 80, 16, "Quit", gid=QUIT))
            self.windows[p] = win
            self.show(p, win)
        self.new_round()

    def new_round(self):
        self.board = [" "] * 9
        self.turn = "X"
        self.result = None                 # None while playing, else "X", "O" or "draw"
        self.rematch = set()
        for win in self.windows.values():
            for cell in range(9):
                win[cell + 1].set_text(" ")
        self.update_status()

    def player_with(self, mark):
        return next(p for p, m in self.mark.items() if m == mark)

    def update_status(self):
        for p, win in self.windows.items():
            me = self.mark[p]
            if self.result == "draw":
                text = "Draw!"
            elif self.result:
                text = "You win!" if self.result == me else \
                    "%s wins." % self.player_with(self.result).name
            elif self.turn == me:
                text = "Your turn (%s)" % me
            else:
                text = "%s's turn (%s)" % (self.player_with(self.turn).name, self.turn)
            win[STATUS].set_text(text)

    def on_click(self, player, window, gadget):
        if gadget.gid == QUIT:
            self.leave(player)
        elif gadget.gid == REMATCH:
            self.ask_rematch(player)
        elif 1 <= gadget.gid <= 9:
            self.move(player, gadget.gid - 1)

    def move(self, player, cell):
        me = self.mark[player]
        if self.result or self.turn != me or self.board[cell] != " ":
            return
        self.board[cell] = me
        for win in self.windows.values():
            win[cell + 1].set_text(me)
        if any(all(self.board[i] == me for i in line) for line in LINES):
            self.result = me
        elif " " not in self.board:
            self.result = "draw"
        else:
            self.turn = "O" if me == "X" else "X"
        self.update_status()

    def ask_rematch(self, player):
        if not self.result:
            return
        self.rematch.add(player)
        if len(self.rematch) == len(self.players):
            for p in self.mark:                      # swap marks so the other player starts
                self.mark[p] = "O" if self.mark[p] == "X" else "X"
            self.new_round()
        else:
            for p in self.players:
                if p is not player:
                    self.windows[p][STATUS].set_text("%s wants a rematch." % player.name)
