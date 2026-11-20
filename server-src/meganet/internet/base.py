"""The Integration base class: one service in Areas > Internet (internet/__init__.py finds
them). Subclass it in a module of this folder:

    class Weather(Integration):
        name = "Weather"
        description = "Today's forecast."
        permission = permissions.register("internet.weather", "Weather", like="internet.use")

        def open(self, session):
            ...  # open its window (ui.Window), as any area does

One object per integration, shared by every session (keep per-user state in a dict by
session, and drop it in disconnected()).
"""


class Integration:
    name = ""                        # shown in the Internet window; required
    description = ""                 # shown when it's picked
    permission = "internet.use"      # who may open it (also needs internet.use)
    order = 50                       # lower first in the list

    def __init__(self, server):
        self.server = server

    def open(self, session):
        """Open its window."""

    def disconnected(self, session):
        """The session signed off."""

    def permissions_changed(self, session):
        """The user's role changed: close what they may no longer use."""
