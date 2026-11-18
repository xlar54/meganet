# Writing a MegaNet game

A game is one Python file in this folder. The server finds it at start-up (any module here that
defines a `Game` subclass with a `name`), lists it in the Games window, and starts a match as
soon as enough players have joined. No other file needs changing.

The game never draws anything itself. It builds windows out of gadgets (buttons, labels, list
boxes...: see `meganet/ui.py`), and the MEGA65 client draws them. When a player clicks, the
client tells the server, and the server calls your game's hooks.

## The smallest game

```python
# meganet/games/coinflip.py
import random
from ..ui import Button, Label
from .base import Game

class CoinFlip(Game):
    name = "Coin Flip"
    description = "Click Flip. Heads wins."
    min_players = 2
    max_players = 2

    def start(self, players):
        for p in players:
            win = self.window(p, "Coin Flip", 200, 60, 200, 60)
            win.add(Label(8, 6, 180, 10, "Click Flip!", gid=1))
            win.add(Button(8, 24, 60, 16, "Flip", gid=2))
            self.show(p, win)

    def on_click(self, player, window, gadget):
        if gadget.gid == 2:
            side = random.choice(["heads", "tails"])
            for p in self.players:
                p.alert("Coin Flip", "%s flipped %s." % (player.name, side))
            self.end()
```

## The Game class (`base.py`)

Class attributes:

| Attribute | Meaning |
|---|---|
| `name` | Shown in the Games list. Required. |
| `description` | Shown when the game is selected in the list. |
| `min_players`, `max_players` | The match starts when `max_players` are waiting, or when a waiting player clicks "Start now" and at least `min_players` are waiting. |
| `tick_interval` | Seconds between `tick()` calls; 0 (the default) means no ticks. |
| `permission` | The permission key needed to see and join the game: `"games.play"` (the default), or your own (below). Everyone also needs `games.play` to open the Games window. |

Hooks (override what you need; any of them may be `async def`):

| Hook | When |
|---|---|
| `start(players)` | The match begins. Open each player's window here. |
| `on_click(player, window, gadget)` | A gadget in one of the game's windows was clicked. |
| `on_select(player, window, gadget, index, double)` | A list row or check box changed. |
| `on_key(player, window, gadget, key)` | A key in a gadget with the `GFlag.RAWKEYS` flag (ASCII code). For real-time games. |
| `on_leave(player)` | A player quit, closed the window or disconnected. `self.players` no longer holds them. The default ends the game, with an alert to the others, when fewer than `min_players` are left. |
| `tick()` | Every `tick_interval` seconds while the game runs. |

Helpers:

| Helper | Does |
|---|---|
| `self.window(player, title, x, y, w, h, flags)` | Makes a window whose gadget events go to the hooks above. Closing it means "leave the game". |
| `self.show(player, window)` | Sends it to that player. |
| `self.leave(player)` | Takes a player out (for a Quit button). |
| `self.end()` | Ends the match and closes every game window. |
| `self.players` | The `Player`s still in: `.name`, `.alert(title, text)`, `.session`. |

Once a window is shown, change it with the gadget methods: `gadget.set_text(...)`,
`set_value(...)`, `ListBox.set_rows(...)`, `TextView.append(...)`. Each sends one small message;
the client redraws just that gadget. Get gadgets back with `window[gid]`.

## Who may play

By default anyone whose role has `games.play` can play. To let admins choose who plays your
game, register a permission of its own in the module and name it on the class:

```python
from .. import permissions

class Chess(Game):
    name = "Chess"
    permission = permissions.register("games.chess", "Play chess", like="games.play")
```

`like="games.play"` means that when the server first sees the key, every role that can play
games gets it (and so do the admin roles), so nothing changes until an admin unticks it in the
Roles window. The game is then listed, and can be joined, only by users who hold the key. See
"Roles and permissions" in [../../README.md](../../README.md).

## Things to know

- The screen is 640x200 and the font is 8x8, so keep windows small. Gadget coordinates are
  relative to the window's inside.
- Give gadgets fixed ids (`gid=`) when you want to recognise them in `on_click`.
- Strings are plain ASCII, at most 255 characters.
- Keep each message small; the client runs on a 40 MHz 8-bit CPU over a slow TCP stack.
  Change the gadgets that changed instead of re-sending whole windows.
- An exception in a hook is logged with its traceback and the event is dropped; the players
  stay connected. Test your game with fake clients, as `tests/test_server.py` does.

`tictactoe.py` is a complete example: turns, win and draw detection, rematch and quit.
