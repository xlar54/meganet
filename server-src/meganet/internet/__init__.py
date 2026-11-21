"""Areas > Internet: services from outside MegaNet. Every module in this folder that defines an
Integration subclass with a `name` is found at start-up and listed in the Internet window
(window 56). The first is the text web browser (web.py).

Opening the area needs internet.use (Members and up at first); each service has its own key
too (internet.web for the browser), given out like internet.use the first time it's seen.
"""

import importlib
import logging
import pkgutil

from .. import permissions as perms
from ..ui import AreaWindow
from .base import Integration

log = logging.getLogger("meganet")
INTERNET_USE = perms.INTERNET_USE
WIN_INTERNET = 56
FRAMEWORK_MODULES = {"base", "webtext", "feedparse"}


def discover():
    found = []
    for info in pkgutil.iter_modules(__path__):
        if info.name in FRAMEWORK_MODULES or info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module("%s.%s" % (__name__, info.name))
        except Exception as e:                      # a broken one mustn't stop the server
            log.warning("internet: can't load %s: %s", info.name, e)
            continue
        for obj in vars(module).values():
            if (isinstance(obj, type) and issubclass(obj, Integration) and obj is not Integration
                    and obj.name and obj.__module__ == module.__name__ and obj not in found):
                found.append(obj)
    return sorted(found, key=lambda cls: (cls.order, cls.name.lower()))


class InternetArea:
    def __init__(self, server):
        self.server = server
        self.services = [cls(server) for cls in discover()]
        self.windows = {}                            # session -> its Internet window

    def may_use(self, session, service):
        return session.can(INTERNET_USE) and session.can(service.permission)

    def open(self, session):
        if not session.can(INTERNET_USE):
            session.warn("Internet refused: no %s" % INTERNET_USE)
            return session.alert("Internet", "Your account can't use the Internet area.")
        a = AreaWindow("Internet", WIN_INTERNET,
                       on_close=lambda w: self.windows.pop(session, None))
        win = a.win
        win.services = [s for s in self.services if self.may_use(session, s)]
        n = len(win.services)
        win.head = a.heading("%d service%s from outside MegaNet." % (n, "" if n == 1 else "s"))
        win.list = a.list(self.rows(win.services), self._picked, about=True)
        win.about = a.about_view
        win.open_b = a.command("Open", self._open, default=True)
        win.open_b.enable(False)
        win.status = a.status("Pick a service and Open it." if win.services else
                              "Nothing here for your account yet.")
        self.windows[session] = win
        win.show(session)
        return None

    @staticmethod
    def rows(services):
        return [s.name for s in services]

    def _picked(self, listbox, index, double):
        win = listbox.window
        if listbox.selected is None or listbox.selected >= len(win.services):
            return None
        win.about.set_lines([win.services[listbox.selected].description])
        win.open_b.enable(True)
        if double:
            return self._open(win.open_b)
        return None

    def _open(self, gadget):
        session, win = gadget.session, gadget.window
        i = win.list.selected
        if i is None or i >= len(win.services):
            return session.alert("Internet", "Pick a service first.")
        service = win.services[i]
        if not self.may_use(session, service):
            session.warn("Internet %s refused: no %s" % (service.name, service.permission))
            return session.alert("Internet", "Your account can't use %s." % service.name)
        session.log("internet: opened %s" % service.name)
        return service.open(session)

    def disconnected(self, session):
        self.windows.pop(session, None)
        for s in self.services:
            s.disconnected(session)

    def permissions_changed(self, session):
        win = self.windows.get(session)
        if win is not None and not session.can(INTERNET_USE):
            self.windows.pop(session)
            win.close()
        elif win is not None:
            win.services = [s for s in self.services if self.may_use(session, s)]
            win.list.set_rows(self.rows(win.services))
            win.open_b.enable(False)
        for s in self.services:
            s.permissions_changed(session)
