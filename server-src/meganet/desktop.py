"""Desktop icons: a column of Windows 95-style icons at the left of the client's desktop,
each a 32x16 picture (it looks square: the client's pixels are twice as tall as wide) with a
label of one or two lines under it. A click selects one; a double click opens it (C.DESK_OPEN).

The server decides which icons there are and draws them: ICONS below are text pictures, one
character a pixel (PALETTE). An icon is only sent to users who may use what it opens, and
the column follows when their permissions change.
"""

import asyncio

from .protocol import (S, WFlag, Writer, DESK_SLOTS, DESK_ICON_W, DESK_ICON_H, DESK_LABEL_MAX,
                       DESK_CLEAR)
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

# The column, top to bottom: (picture, label, permission or None, Screens action)
DESKTOP = [
    ("chat", "Chat", "chat.use", "open_chat"),
    ("boards", "Message Boards", "boards.read", "open_boards"),
    ("files", "File Library", "files.download", "open_files"),
    ("games", "Games", "games.play", "open_games"),
]


def pixels(name):
    """An icon's DESK_ICON_W x DESK_ICON_H bytes."""
    rows = ICONS[name]
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
        return [d for d in DESKTOP if d[2] is None or session.can(d[2])][:DESK_SLOTS]

    def start(self, session, then=None):
        """At sign-on: a "One moment..." window with a progress bar (modal, no close box)
        while the icons go one at a time; then it closes and `then()` runs (the welcome
        window). Returns the task (None if there are no icons: then() at once)."""
        want = self.icons_for(session)
        if not want:
            self.refresh(session)
            return then() if then else None
        win = Window.centred("One moment...", 240, 34, flags=WFlag.MODAL, win_id=WIN_LOADING,
                             minimize=False)
        win.add(Label(8, 2, 224, 10, "Setting up your desktop..."))
        bar = win.add(Progress(8, 16, 224, 12))
        win.show(session)

        async def run():
            for i in range(len(want)):
                await asyncio.sleep(PACE)
                if session.closed:
                    return
                self._send(session, want[:i + 1])
                bar.set_percent((i + 1) * 100 // len(want))
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
                w.str(one).str(two).bytes(pixels(new[0]))
            session.send(S.DESK_ICON, w)
        session.desk = want

    def open(self, session, slot):
        """C.DESK_OPEN: the icon's action, if this session was sent it and still may use it."""
        icons = getattr(session, "desk", [])
        if not 0 <= slot < len(icons):
            return None
        picture, label, key, action = icons[slot]
        if key is not None and not session.can(key):
            return session.alert(label, "Your account can't use %s." % label)
        return getattr(self.screens, action)(session)
