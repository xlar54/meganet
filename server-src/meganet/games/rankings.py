"""Rankings for player-vs-player games (chess): wins, losses and draws, and an Elo rating that
puts the best players first. Games against the computer don't count.

A game counts once both players have moved; a player who resigns or leaves loses it. Each
player starts at RATING_START; after a game each moves by K * (result - expected), where the
expected result comes from the two ratings (1 / (1 + 10 ** ((theirs - mine) / 400))): beating
a stronger player gains more than beating a weaker one, and losing to one costs less.

The lobby's Rankings... button (challenge.py, for games that set `rankings = True`) opens
window WIN_RANKINGS: everyone with a ranked game, best first, and the viewer's own place.
"""

from ..protocol import GFlag, WFlag
from ..ui import Window, Label, ListBox, add_buttons, closer, MARGIN

RATING_START = 1200
K = 32
WIN_RANKINGS = 58
W, H = 384, 150
COLUMNS = "%4s  %-12s %6s %5s %5s %5s" % ("#", "Player", "Rating", "Won", "Lost", "Drawn")
SHOWN = 128                      # rows (the client's list holds 128)


def expected(mine, theirs):
    """The score a player rated `mine` is expected to make against `theirs` (0..1)."""
    return 1 / (1 + 10 ** ((theirs - mine) / 400))


def new_ratings(a, b, score):
    """(a', b') after a game that a scored `score` in (1 win, 0.5 draw, 0 loss)."""
    ea = expected(a, b)
    return round(a + K * (score - ea)), round(b + K * ((1 - score) - (1 - ea)))


def record(db, game, winner_id, loser_id, draw=False):
    """A ranked game over: winner beat loser (or, `draw`, the two drew). Returns the new
    ratings (winner's, loser's)."""
    a = db.game_rating(game, winner_id)
    b = db.game_rating(game, loser_id)
    ra = a[0] if a else RATING_START
    rb = b[0] if b else RATING_START
    na, nb = new_ratings(ra, rb, 0.5 if draw else 1)
    db.save_game_rating(game, winner_id, na, 0 if draw else 1, 0, 1 if draw else 0)
    db.save_game_rating(game, loser_id, nb, 0, 0 if draw else 1, 1 if draw else 0)
    return na, nb


def rows(db, game):
    """The list's rows, best first, and the rankings they came from."""
    ranks = db.game_rankings(game)[:SHOWN]
    out = ["%4d  %-12s %6d %5d %5d %5d" % (i + 1, name[:12], rating, w, l, d)
           for i, (name, rating, w, l, d, _uid) in enumerate(ranks)]
    return out, ranks


def you_line(db, game, user_id):
    """The viewer's own place."""
    ranks = db.game_rankings(game)
    for i, (_name, rating, _w, _l, _d, uid) in enumerate(ranks):
        if uid == user_id:
            return "You are #%d of %d, rated %d." % (i + 1, len(ranks), rating)
    return "You have no ranked games yet."


def show(session, game):
    """The rankings window for `game` (its name: "Chess")."""
    db = session.server.db
    lines, ranks = rows(db, game)
    win = Window.centred("%s Rankings" % game, W, H, win_id=WIN_RANKINGS,
                         flags=WFlag.CLOSE | WFlag.MOVABLE)
    win.add(Label(MARGIN, 2, W - 2 * MARGIN, 10, COLUMNS))
    win.add(ListBox(MARGIN, 14, W - 2 * MARGIN, 96,
                    lines or ["  No ranked games yet."], on_select=lambda *a: None))
    win.add(Label(MARGIN, 114, W - 2 * MARGIN, 10, you_line(db, game, session.user_id)))
    add_buttons(win, [("Close", closer, GFlag.DEFAULT)])
    win.show(session)
    return win
