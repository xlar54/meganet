"""MegaNet games. Every module in this folder that defines a Game subclass with a `name` is
found at start-up and listed in the Games window. See README.md here for how to write one."""

import importlib
import logging
import pkgutil

from .base import Game, Player

log = logging.getLogger("meganet")
FRAMEWORK_MODULES = {"base", "lobby", "challenge", "chess_rules", "chess_art"}


def discover():
    """Import every game module in this package; return their Game classes, sorted by name."""
    found = []
    for info in pkgutil.iter_modules(__path__):
        if info.name in FRAMEWORK_MODULES or info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module("%s.%s" % (__name__, info.name))
        except Exception as e:                      # a broken game mustn't stop the server
            log.warning("games: can't load %s: %s", info.name, e)
            continue
        for obj in vars(module).values():
            if (isinstance(obj, type) and issubclass(obj, Game) and obj is not Game
                    and obj.name and obj.__module__.startswith(module.__name__)
                    and obj not in found):
                found.append(obj)
    return sorted(found, key=lambda cls: cls.name.lower())


__all__ = ["Game", "Player", "discover"]
