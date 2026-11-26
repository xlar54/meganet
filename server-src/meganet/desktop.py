"""Desktop icons: columns of Windows 95-style icons at the left and right of the client's desktop,
each a 32x16 picture (it looks square: the client's pixels are twice as tall as wide) with a
label of one or two lines under it. A click selects one; a double click opens it (C.DESK_OPEN).

The server decides which icons there are and draws them: ICONS below are text pictures, one
character a pixel (PALETTE). An icon is only sent to users who may use what it opens, and
the column follows when their permissions change.
"""

import asyncio

from .protocol import (S, WFlag, Writer, DESK_SLOTS, DESK_LEFT, DESK_ICON_W, DESK_ICON_H,
                       DESK_LABEL_MAX, DESK_CLEAR, Skin)
from .ui import Window, Label, Progress

# text picture character -> the client's GUI colour (lib/gui GC_*); '.' is transparent
PALETTE = {
    ".": DESK_CLEAR, "k": 0, "w": 1, "g": 2, "s": 3, "l": 4, "n": 5, "t": 8, "r": 9,
    "G": 10, "d": 11, "b": 12, "y": 14, "c": 15,
}

ICONS = {
    "chat": [                                    # two speech bubbles, one answering
        ".kkkkkkkkkkkkkkkkkk.............",
        "kwwwwwwwwwwwwwwwwwwk............",
        "kwwssssssssssssswwwk............",
        "kwwwwwwwwwwwwwwwwwwk............",
        "kwwssssssssssswwwwwk............",
        "kwwwwwwwwwwkkkkkkkkkkkkkkkkkkkk.",
        "kwwsssssssskyyyyyyyyyyyyyyyyyyyk",
        "kwwwwwwwwwwkyyddddddddddddddyyyk",
        ".kkkkkkkkkkkyyyyyyyyyyyyyyyyyyyk",
        "...kwwk....kyyddddddddddddyyyyyk",
        "...kwk.....kyyyyyyyyyyyyyyyyyyyk",
        "...kk......kyyddddddddyyyyyyyyyk",
        "...k.......kyyyyyyyyyyyyyyyyyyyk",
        "............kkkkkkkkkkkkkkkkkkk.",
        "........................kyyk....",
        ".........................kyk....",
    ],
    "boards": [                                  # a pin board with notes on it
        ".kkkkkkkkkkkkkkkkkkkkkkkkkkkkkk.",
        ".kssssssssssssssssssssssssssssk.",
        ".ksstttttttttttttssssrrsssstssk.",
        ".ksstssssrrssssttsccccccccstssk.",
        ".ksstswwwwwwwwsttsckkkkkkcstssk.",
        ".ksstswnnnnnnwsttsccccccccstssk.",
        ".ksstswwwwwwwwsttsckkkkkccstssk.",
        ".ksstswnnnnnwwsttsssssssssstssk.",
        ".ksstsssssssssstttttttttttttssk.",
        ".ksstttttttsssssrrssssstttttssk.",
        ".ksstttttttswnnnnnnnnwstttttssk.",
        ".ksstttttttswnnnnnnwwwstttttssk.",
        ".ksstttttttsssssssssssstttttssk.",
        ".kssssssssssssssssssssssssssssk.",
        ".kkkkkkkkkkkkkkkkkkkkkkkkkkkkkk.",
        "....kkk..................kkk....",
    ],
}

ICONS["files"] = [                               # a folder with papers in it
    "................................",
    "...kkkkkkkkkkkkkkkkkkkkkkk......",
    "...kyyykwwwwwwwwwwwwwwwwwwk.....",
    "...kyyykwwssssssssssssswwwk.....",
    "..kkkkkkkkkkkkkkkkkkkkkkkkkkkk..",
    "..kwwwwwwwwwwwwwwwwwwwwwwwwwwk..",
    "..kyyyyyyyyyyyyyyyyyyyyyyyyydk..",
    "..kyyyyyyyyyyyyyyyyyyyyyyyyydk..",
    "..kyyyyyyyyyyyyyyyyyyyyyyyyydk..",
    "..kyyyyyyyyyyyyyyyyyyyyyyyyydk..",
    "..kyyyyyyyyyyyyyyyyyyyyyyyyydk..",
    "..kyyyyyyyyyyyyyyyyyyyyyyyyydk..",
    "..kyyyyyyyyyyyyyyyyyyyyyyyyydk..",
    "..kddddddddddddddddddddddddddk..",
    "..kkkkkkkkkkkkkkkkkkkkkkkkkkkk..",
    "................................",
]
ICONS["games"] = [                               # a joystick: ball, stick, base, fire button
    "..............kkkkkk............",
    ".............krwwrrrk...........",
    ".............krrrrrrk...........",
    ".............krrrrrrk...........",
    "..............kkkkkk............",
    "...............kssk.............",
    "...............kssk.............",
    "....kkkkkk.....kssk.............",
    "....krrrrk.....kssk.............",
    "...kkkkkkkkkkkkkkkkkkkkkkkkkk...",
    "...kddddddddddddddddddddddddk...",
    "...kssssssssssssssssssssssssk...",
    "...kssssssssssssssssssssssssk...",
    "...kssssssssssssssssssssssssk...",
    "...kddddddddddddddddddddddddk...",
    "....kkkkkkkkkkkkkkkkkkkkkkkk....",
]

ICONS["who"] = [                                 # two people, side by side
    "................................",
    "........kkkkk......kkkkk........",
    ".......kyyyyyk....kyyyyyk.......",
    "......kyykyykyk..kyykyykyk......",
    "......kyyyyyyyk..kyyyyyyyk......",
    "......kyykkkyyk..kyykkkyyk......",
    ".......kyyyyyk....kyyyyyk.......",
    "........kkkkk......kkkkk........",
    "......kkkkkkkkk..kkkkkkkkk......",
    ".....kbbbbbbbbbkkrrrrrrrrrk.....",
    "....kbbbbbbbbbbbkrrrrrrrrrrk....",
    "....kbbbbbbbbbbbkrrrrrrrrrrk....",
    "....kbbbbbbbbbbbkrrrrrrrrrrk....",
    "....kbbbbbbbbbbbkrrrrrrrrrrk....",
    "....kkkkkkkkkkkkkkkkkkkkkkkk....",
    "................................",
]
ICONS["news"] = [                                # a newspaper: masthead, a picture, columns
    "..kkkkkkkkkkkkkkkkkkkkkkkkkk....",
    "..kwwwwwwwwwwwwwwwwwwwwwwwwk....",
    "..kwkkkkkkkkkkkkkkkkkkkkkkwk....",
    "..kwkkkkkkkkkkkkkkkkkkkkkkwkk...",
    "..kwwwwwwwwwwwwwwwwwwwwwwwwkdk..",
    "..kwssssssssssssssssssssswwkdk..",
    "..kwwwwwwwwwwwwwwwwwwwwwwwwkdk..",
    "..kwbbbbbbbbwwssssswwssssswkdk..",
    "..kwbbyybbbbwwwwwwwwwwwwwwwkdk..",
    "..kwbbbbbbbbwwssssswwssssswkdk..",
    "..kwbbbbbbbbwwwwwwwwwwwwwwwkdk..",
    "..kwsssssssswwssssswwssssswkdk..",
    "..kwwwwwwwwwwwwwwwwwwwwwwwwkdk..",
    "..kwsssssssswwssssswwssssswkdk..",
    "..kkkkkkkkkkkkkkkkkkkkkkkkkkdk..",
    "....kdddddddddddddddddddddddk...",
]
ICONS["voting"] = [                              # a ballot with a tick going into a box
    "..........kkkkkkkkkkkk..........",
    "..........kwwwwwwwwwwk..........",
    "..........kwwwwwwwwGwk..........",
    "..........kwwwwwwwGGwk..........",
    "..........kwGwwwwGGwwk..........",
    "..........kwGGwwGGwwwk..........",
    "..........kwwGGGGwwwwk..........",
    "....kkkkkkkkkkkkkkkkkkkkkkkk....",
    "....kssssskkkkkkkkkkkksssssk....",
    "....kbbbbbbbbbbbbbbbbbbbbbbk....",
    "....kbbbbbbbbbbbbbbbbbbbbbbk....",
    "....kbbbbbbwwwwwwwwwwbbbbbbk....",
    "....kbbbbbbwkkwkkwkkwbbbbbbk....",
    "....kbbbbbbwwwwwwwwwwbbbbbbk....",
    "....kbbbbbbbbbbbbbbbbbbbbbbk....",
    "....kkkkkkkkkkkkkkkkkkkkkkkk....",
]

ICONS["bank"] = [                                # a bank: gold pediment, white columns
    "...............kk...............",
    ".............kyyyyk.............",
    "..........kyyyyyyyyyyk..........",
    ".......kyyyyyyyyyyyyyyyyk.......",
    "....kyyyyyyyyyyyyyyyyyyyyyyk....",
    "...kkkkkkkkkkkkkkkkkkkkkkkkkk...",
    "...kwwwwwwwwwwwwwwwwwwwwwwwwk...",
    "...kkkkkkkkkkkkkkkkkkkkkkkkkk...",
    "....kwwk.kwwk.kwwk.kwwk.kwwk....",
    "....kwwk.kwwk.kwwk.kwwk.kwwk....",
    "....kwwk.kwwk.kwwk.kwwk.kwwk....",
    "....kwwk.kwwk.kwwk.kwwk.kwwk....",
    "....kwwk.kwwk.kwwk.kwwk.kwwk....",
    "..kkkkkkkkkkkkkkkkkkkkkkkkkkkk..",
    ".kssssssssssssssssssssssssssssk.",
    ".kkkkkkkkkkkkkkkkkkkkkkkkkkkkkk.",
]

# The Pinstripe skin's pictures (protocol.Skin.PINSTRIPE), also Dark's: crisp black outlines,
# flat colours and a grey drop shadow, in the style of a classic colour Mac (originals, not
# copies). Only colours that look the same in every skin: not g, l or t (the window face, the
# light grey and the tooltip colour, which each skin redefines; Dark makes them dark greys).
# s and n stay a mid grey and a blue everywhere. tests/test_skins.py checks this.
SKIN_STABLE = set(".kwrGdbycsn")
ICONS_PIN = {
    "chat": [                                    # a speech balloon, three dots; one behind
        "................................",
        "...........kkkkkkkkkkkkkkkkkk...",
        "..........knnnnnnnnnnnnnnnnnnk..",
        "..kkkkkkkkkkkkkkkkkkkkknnnnnnk..",
        ".kwwwwwwwwwwwwwwwwwwwwwknnnnnk..",
        "kwwwwwwwwwwwwwwwwwwwwwwwknnnnk..",
        "kwwwwkkwwwwwkkwwwwwkkwwwknnnnk..",
        "kwwwwkkwwwwwkkwwwwwkkwwwkkkkk...",
        "kwwwwwwwwwwwwwwwwwwwwwwwksss....",
        ".kwwwwwwwwwwwwwwwwwwwwwks.......",
        "..kkkkkwwkkkkkkkkkkkkkkss.......",
        "......kwwkssssssssssssss........",
        "......kwks......................",
        "......kks.......................",
        "......ks........................",
        "................................",
    ],
    "boards": [                                  # notes pinned to a board, red pins
        "................................",
        ".kkkkkkkkkkkkkkkkkkkkkkkkkkkkkk.",
        ".kddddddddddddddddddddddddddddks",
        ".kdkkkkkkkkkkdddddkkkkkkkkkkddks",
        ".kdkwwwrrwwwkddddkyyyyyrryyykdks",
        ".kdkwwrrrrwwksdddkyyyrrrryyyksks",
        ".kdkwwwwwwwwksdddkyyyyyyyyyyksks",
        ".kdkwkkkkkwwksdddkykkkkkkyyyksks",
        ".kdkwwwwwwwwksdddkyyyyyyyyyyksks",
        ".kdkwkkkkwwwksdddkykkkkkyyyksdks",
        ".kdkwwwwwwwwksdddkkkkkkkkkkkkdks",
        ".kdkkkkkkkkkksddddsssssssssssdks",
        ".kddsssssssssdddddddddddddddddks",
        ".kkkkkkkkkkkkkkkkkkkkkkkkkkkkkks",
        "..sssssssssssssssssssssssssssss.",
        "................................",
    ],
    "files": [                                   # a blue folder, its tab at the top left
        "................................",
        "...kkkkkkkkk....................",
        "..kwwwwwwwwwk...................",
        "..kwnnnnnnnnwkkkkkkkkkkkkkkkk...",
        "..kwnnnnnnnnnnnnnnnnnnnnnnnnnk..",
        "..kwwwwwwwwwwwwwwwwwwwwwwwwwnks.",
        "..kwnnnnnnnnnnnnnnnnnnnnnnnnnks.",
        "..kwnnnnnnnnnnnnnnnnnnnnnnnnnks.",
        "..kwnnnnnnnnnnnnnnnnnnnnnnnnnks.",
        "..kwnnnnnnnnnnnnnnnnnnnnnnnnnks.",
        "..kwnnnnnnnnnnnnnnnnnnnnnnnnnks.",
        "..kwnnnnnnnnnnnnnnnnnnnnnnnnnks.",
        "..kkkkkkkkkkkkkkkkkkkkkkkkkkkks.",
        "...sssssssssssssssssssssssssss..",
        "................................",
        "................................",
    ],
    "games": [                                   # two dice
        "................................",
        "..kkkkkkkkkkkkk.................",
        ".kwwwwwwwwwwwwwk................",
        ".kwkkwwwwwwwwwwk.....kkkkkkkkkk.",
        ".kwkkwwwwwwwwwwk....kwwwwwwwwwwk",
        ".kwwwwwwkkwwwwwks...kwwwwwwrrwwk",
        ".kwwwwwwkkwwwwwks...kwwwwwwrrwwk",
        ".kwwwwwwwwwwkkwks...kwwwwwwwwwwk",
        ".kwwwwwwwwwwkkwks...kwwrrwwwwwwk",
        ".kwwwwwwwwwwwwwks...kwwrrwwwwwwk",
        "..kkkkkkkkkkkkkks...kwwwwwwwwwwk",
        "...ssssssssssssss....kkkkkkkkkks",
        ".....................sssssssssss",
        "................................",
        "................................",
        "................................",
    ],
    "who": [                                     # two people, one in front
        "................................",
        ".........kkkkk..................",
        "........kyyyyyk.....kkkkk.......",
        "........kyyyyyk....kyyyyyk......",
        "........kyyyyyk....kyyyyyk......",
        ".........kkkkk.....kyyyyyk......",
        "......kkkkkkkkkk....kkkkk.......",
        ".....kGGGGGGGGGGkkkkkkkkkkk.....",
        ".....kGGGGGGGGGkrrrrrrrrrrrk....",
        ".....kGGGGGGGGGkrrrrrrrrrrrks...",
        ".....kGGGGGGGGGkrrrrrrrrrrrks...",
        ".....kkkkkkkkkkkrrrrrrrrrrrks...",
        "...............kkkkkkkkkkkkks...",
        "................ssssssssssss....",
        "................................",
        "................................",
    ],
    "news": [                                    # a page with its corner folded down
        "......kkkkkkkkkkkkkkkkkk........",
        "......kwwwwwwwwwwwwwwwwkwk......",
        "......kwkkkkkkkkkkkkkkwkwwk.....",
        "......kwwwwwwwwwwwwwwwwkkkkk....",
        "......kwnnnnnnwwkkkkkkkwwwwks...",
        "......kwnnnnnnwwwwwwwwwwwwwks...",
        "......kwnnnnnnwwkkkkkkkkkwwks...",
        "......kwnnnnnnwwwwwwwwwwwwwks...",
        "......kwwwwwwwwwkkkkkkkkkwwks...",
        "......kwkkkkkkkkkkkkkkkkkwwks...",
        "......kwwwwwwwwwwwwwwwwwwwwks...",
        "......kwkkkkkkkkkkkkkkkwwwwks...",
        "......kwwwwwwwwwwwwwwwwwwwwks...",
        "......kkkkkkkkkkkkkkkkkkkkkks...",
        ".......ssssssssssssssssssssss...",
        "................................",
    ],
    "voting": [                                  # a list of boxes, one ticked
        "........kkkkkkkkkkkkkkkkk.......",
        "........kwwwwwwwwwwwwwwwk.......",
        "........kwkkkkwwwwwwwwwwks......",
        "........kwkwwkwkkkkkkkwwks......",
        "........kwkkkkwwwwwwwwwwks......",
        "........kwwwwwwwwwwwwGwwks......",
        "........kwkkkkwwwwwwGGwwks......",
        "........kwkGwkGkkkkGGkwwks......",
        "........kwkkGGGwwwGGwwwwks......",
        "........kwwwwGGwwGGwwwwwks......",
        "........kwkkkkGGGGwwwwwwks......",
        "........kwkwwkwGGkkkkwwwks......",
        "........kwkkkkwwwwwwwwwwks......",
        "........kkkkkkkkkkkkkkkkks......",
        ".........sssssssssssssssss......",
        "................................",
    ],
    "bank": [                                    # a stack of gold coins and one on its own
        "................................",
        "................................",
        "........kkkkkkkkkkkk............",
        ".......kyyyyyyyyyyyyk...........",
        "......kyyyyyyyyyyyyyyk..........",
        "......kkyyyyyyyyyyyykk..........",
        "......kykkkkkkkkkkkkyk...kkkkkk.",
        "......kkyyyyyyyyyyyykk..kyyyyyyk",
        "......kykkkkkkkkkkkkyk.kyykkkyyk",
        "......kkyyyyyyyyyyyykk.kyykyyyyk",
        "......kykkkkkkkkkkkkyk.kyykkkyyk",
        "......kkyyyyyyyyyyyykks.kyyyyyyk",
        ".......kkkkkkkkkkkkkks...kkkkkk.",
        "........ssssssssssssss.....ssss.",
        "................................",
        "................................",
    ],
}

# The columns, top to bottom: (picture, label, permission or None, Screens action). LEFT
# fills slots 0-7 from the left edge, RIGHT slots 8-11 from the right edge (protocol).
DESKTOP = [
    ("chat", "Chat", "chat.use", "open_chat"),
    ("boards", "Message Boards", "boards.read", "open_boards"),
    ("files", "File Library", "files.download", "open_files"),
    ("games", "Games", "games.play", "open_games"),
]
DESKTOP_RIGHT = [
    ("who", "Who's Online", None, "open_who"),
    ("news", "News", "news.read", "open_news"),
    ("voting", "Voting", "polls.vote", "open_voting"),
    ("bank", "Bank", "bank.use", "open_bank"),
]


def pixels(name, skin=Skin.CLASSIC):
    """An icon's DESK_ICON_W x DESK_ICON_H bytes, in the skin's style (Classic's if it has
    none of its own). Dark uses the flat Pinstripe pictures."""
    flat = skin in (Skin.PINSTRIPE, Skin.DARK)
    rows = (ICONS_PIN if flat else ICONS).get(name) or ICONS[name]
    if len(rows) != DESK_ICON_H or any(len(r) != DESK_ICON_W for r in rows):
        raise ValueError("icon %s isn't %dx%d" % (name, DESK_ICON_W, DESK_ICON_H))
    return bytes(PALETTE[ch] for row in rows for ch in row)


def label_lines(label):
    """One or two lines of at most DESK_LABEL_MAX characters, broken at a space."""
    if len(label) <= DESK_LABEL_MAX:
        return label, ""
    cut = label.rfind(" ", 0, DESK_LABEL_MAX + 1)
    if cut <= 0:
        return label[:DESK_LABEL_MAX], label[DESK_LABEL_MAX:2 * DESK_LABEL_MAX]
    return label[:cut], label[cut + 1:cut + 1 + DESK_LABEL_MAX]


WIN_LOADING = 30            # "One moment...": modal, no close box, while the icons come
PACE = 0.15                 # seconds between icons at sign-on (tests set it to 0)


class Desktop:
    def __init__(self, screens):
        self.screens = screens

    def icons_for(self, session):
        """Slot -> icon (None = empty): the left ones from slot 0, the right from DESK_LEFT."""
        ok = lambda d: d[2] is None or session.can(d[2])
        left = [d for d in DESKTOP if ok(d)][:DESK_LEFT]
        right = [d for d in DESKTOP_RIGHT if ok(d)][:DESK_SLOTS - DESK_LEFT]
        if not right:
            return left
        return left + [None] * (DESK_LEFT - len(left)) + right

    def start(self, session, then=None):
        """At sign-on: a "One moment..." window with a progress bar (modal, no close box)
        while the icons go one at a time; then it closes and `then()` runs (the welcome
        window). Returns the task (None if there are no icons: then() at once)."""
        want = self.icons_for(session)
        if not any(want):
            self.refresh(session)
            return then() if then else None
        win = Window.centred("One moment...", 240, 34, flags=WFlag.MODAL, win_id=WIN_LOADING,
                             minimize=False)
        win.add(Label(8, 2, 224, 10, "Setting up your desktop..."))
        bar = win.add(Progress(8, 16, 224, 12))
        win.show(session)

        steps = [i for i, d in enumerate(want) if d is not None]    # one icon at a time

        async def run():
            for n, i in enumerate(steps):
                await asyncio.sleep(PACE)
                if session.closed:
                    return
                self._send(session, want[:i + 1])
                bar.set_percent((n + 1) * 100 // len(steps))
            await asyncio.sleep(PACE)
            if session.closed:
                return
            win.close()
            self.refresh(session)        # (anything that changed meanwhile)
            if then:
                then()
        return asyncio.get_running_loop().create_task(run())

    def refresh(self, session):
        """Send the icons this session may use; only what changed goes (session.desk)."""
        self._send(session, self.icons_for(session))

    def reskin(self, session):
        """Every icon again, in the session's new skin."""
        session.desk = []
        self.refresh(session)

    def _send(self, session, want):
        have = getattr(session, "desk", [])
        for slot in range(DESK_SLOTS):
            new = want[slot] if slot < len(want) else None
            old = have[slot] if slot < len(have) else None
            if new == old:
                continue
            w = Writer().u8(slot)
            if new is None:
                w.str("").str("")
            else:
                one, two = label_lines(new[1])
                w.str(one).str(two).bytes(pixels(new[0], session.skin if session.skins else 0))
            session.send(S.DESK_ICON, w)
        session.desk = want
        if getattr(session, "live_badges", None) is not None:   # (signed on: the badges
            self.screens.live.send_badges(session)              # follow the icons)

    def open(self, session, slot):
        """C.DESK_OPEN: the icon's action, if this session was sent it and still may use it."""
        icons = getattr(session, "desk", [])
        if not 0 <= slot < len(icons) or icons[slot] is None:
            return None
        picture, label, key, action = icons[slot]
        if key is not None and not session.can(key):
            return session.alert(label, "Your account can't use %s." % label)
        return getattr(self.screens, action)(session)
