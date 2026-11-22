"""The MegaNet server: accepts MEGA65 clients over TCP and drives their screens.

    python -m meganet [--port 6400] [--db data/meganet.db] [--updates updates] [--motd FILE]
                      [--filelibs filelibs] [--galleries galleries] [--sidlibs sidlibs]
                      [--cafile PEM]
"""

import argparse
import asyncio
import logging
import os
import socket
import time
import traceback

from . import __version__
from . import games
from .db import Database, read_motd_file
from .games.lobby import GameLobby
from .screens import Screens
from .serverlog import ServerLog
from .session import Session, keepalive, quick_ack
from .updates import Updates

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))    # server-src/
DEFAULT_PORT = 6400
DEFAULT_DB = os.path.join(HERE, "data", "meganet.db")
DEFAULT_UPDATES = os.path.join(HERE, "updates")
DEFAULT_FILELIBS = os.path.join(HERE, "filelibs")     # the file libraries' folders (filelib.py)
DEFAULT_GALLERIES = os.path.join(HERE, "galleries")   # the Art Gallery's pictures (gallery/)
DEFAULT_SIDLIBS = os.path.join(HERE, "sidlibs")       # the SID Music libraries (sidlib.py)


class Server:
    """Holds everything shared between sessions: the database, the chat lobby, the games."""

    def __init__(self, db_path=DEFAULT_DB, updates_dir=DEFAULT_UPDATES, motd_file=None,
                 filelibs_dir=None, galleries_dir=None, sidlibs_dir=None):
        """`motd_file`: a text file to load into the message of the day (replacing it).
        `filelibs_dir`: where the file libraries keep their files (default filelibs/; with a
        :memory: database, as the tests use, a folder inside updates_dir instead)."""
        self.db = Database(db_path)
        self.serverlog = ServerLog(self)     # (from here on the log is kept in the database)
        if filelibs_dir is None:
            filelibs_dir = (os.path.join(updates_dir, "filelibs") if db_path == ":memory:"
                            else DEFAULT_FILELIBS)
        self.filelibs_dir = filelibs_dir
        if galleries_dir is None:            # the Art Gallery's pictures (gallery/)
            galleries_dir = (os.path.join(updates_dir, "galleries") if db_path == ":memory:"
                             else DEFAULT_GALLERIES)
        self.galleries_dir = galleries_dir
        if sidlibs_dir is None:              # the SID Music libraries (sidlib.py)
            sidlibs_dir = (os.path.join(updates_dir, "sidlibs") if db_path == ":memory:"
                           else DEFAULT_SIDLIBS)
        self.sidlibs_dir = sidlibs_dir
        if motd_file:
            lines = self.db.set_motd(read_motd_file(motd_file))
            self.serverlog.write("message of the day: %d lines from %s" % (len(lines), motd_file))
        self.screens = Screens(self)
        self.updates = Updates(self)          # (a newer client for older ones)
        self.games = GameLobby(games.discover())
        self.db.sync_permissions()           # the game plugins may have registered keys
        for user_id, chips in self.db.poker_chips().items():   # (left on a poker table when
            self.db.from_poker_table(user_id, memo="the server restarted")   # it stopped)
            self.serverlog.write("bank: %d poker chips back to user %d" % (chips, user_id))
        self.sessions = set()
        self._next_id = 1
        self._server = None

    async def start(self, host="0.0.0.0", port=DEFAULT_PORT):
        """Start listening. Returns the port (useful when `port` is 0: pick a free one)."""
        self._server = await asyncio.start_server(self._connected, host, port)
        self._away = asyncio.create_task(self.screens.presence.run())     # Auto-Away
        self._bank = asyncio.create_task(self.screens.bank.run())         # an hour online
        return self._server.sockets[0].getsockname()[1]

    async def serve_forever(self):
        async with self._server:
            await self._server.serve_forever()

    async def stop(self):
        for task in (getattr(self, "_away", None), getattr(self, "_bank", None)):
            if task:
                task.cancel()
        for s in list(self.sessions):
            if s.game is not None:           # (out of their games now, while the database
                try:                         # is open: poker gives their chips back)
                    self.games.disconnected(s)
                except Exception:
                    s.error("error leaving a game:\n%s" % traceback.format_exc(), area="conn")
            s.disconnect()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.serverlog.close()
        self.db.close()

    async def _connected(self, reader, writer):
        sock = writer.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            quick_ack(sock)
            keepalive(sock)
        session = Session(self, reader, writer, self._next_id)
        self._next_id = self._next_id % 0xFFFF + 1
        self.sessions.add(session)
        peer = writer.get_extra_info("peername")
        session.log("connected from %s" % (("%s port %d" % peer[:2]) if peer else "?"),
                    area="conn")
        started = time.time()
        try:
            await session.run()
        finally:
            self.sessions.discard(session)
            try:
                self.screens.disconnected(session)
                self.games.disconnected(session)
            except Exception:
                session.error("error while disconnecting:\n%s" % traceback.format_exc(),
                              area="conn")
            mins = int(time.time() - started) // 60
            session.log("disconnected after %d:%02d" % (mins // 60, mins % 60)
                        + (" (signed on as %s)" % session.user if session.user else ""),
                        area="conn")

    def permissions_changed(self, role_id=None, user_id=None):
        """An admin changed a role's permissions (role_id) or moved a user to another role
        (user_id); with neither, anything may have changed. Every signed-on user affected
        re-reads their permissions, and their screens follow (menu bar, lobby, admin)."""
        for s in list(self.sessions):
            if s.user is None or s.closed:
                continue
            if role_id is None and user_id is None or s.role_id == role_id                     or s.user_id == user_id:
                old = (s.perms, s.role)
                s.load_permissions()
                self.screens.permissions_changed(s, old)
                self.games.permissions_changed(s)

    def find_user(self, name):
        """The session signed on as `name` (any case), or None."""
        for s in self.sessions:
            if s.user and s.user.lower() == name.lower():
                return s
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="meganet", description="MegaNet BBS server")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port (default 6400)")
    ap.add_argument("--host", default="0.0.0.0", help="address to listen on")
    ap.add_argument("--db", default=DEFAULT_DB, help="SQLite file (default data/meganet.db)")
    ap.add_argument("--updates", default=DEFAULT_UPDATES,
                    help="folder with manifest.json and the client files for forced updates")
    ap.add_argument("--filelibs", default=DEFAULT_FILELIBS,
                    help="folder for the file libraries (default filelibs/)")
    ap.add_argument("--galleries", default=DEFAULT_GALLERIES,
                    help="folder for the Art Gallery's pictures (default galleries/)")
    ap.add_argument("--sidlibs", default=DEFAULT_SIDLIBS,
                    help="folder for the SID Music libraries (default sidlibs/)")
    ap.add_argument("--motd", metavar="FILE",
                    help="text file to load as the message of the day (replaces the saved one)")
    ap.add_argument("--cafile", metavar="PEM",
                    help="trusted certificates for the web browser's https (for a Python "
                         "without its own list)")
    args = ap.parse_args(argv)
    if args.cafile:
        from .internet import webtext
        webtext.set_cafile(args.cafile)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    async def run():
        server = Server(args.db, args.updates, args.motd, args.filelibs, args.galleries,
                        args.sidlibs)
        port = await server.start(args.host, args.port)
        server.serverlog.write("MegaNet server %s listening on port %d (%d games)"
                               % (__version__, port, len(server.games.classes)))
        await server.serve_forever()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
