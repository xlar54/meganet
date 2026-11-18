"""Forced client updates (docs/DESIGN.md, "Forced auto-update").

Put the released client files and a manifest in server-src/updates/:

    updates/manifest.json   {"build": 3, "message": "New version", "files": ["CLIENT", "OVL0"]}
    updates/CLIENT, updates/OVL0 ...   (the files as they go on the D81, sent byte for byte)

A client whose HELLO build is lower than the manifest's gets S.UPDATE and the files instead of
being allowed to sign on. No manifest means updates are off.
"""

import json
import os
import zlib

from .protocol import S, Writer

CHUNK = 1024


class Updates:
    def __init__(self, directory):
        self.dir = directory

    def manifest(self):
        try:
            with open(os.path.join(self.dir, "manifest.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def needs(self, build):
        m = self.manifest()
        return bool(m) and build < m["build"]

    def push(self, session):
        m = self.manifest()
        session.log("forcing update %d -> %d" % (session.build, m["build"]))
        session.send(S.UPDATE, Writer().u16(m["build"]).u8(len(m["files"]))
                     .str(m.get("message", "Updating MegaNet")))
        for name in m["files"]:
            with open(os.path.join(self.dir, name), "rb") as f:
                data = f.read()
            session.send(S.FILE_BEGIN, Writer().u32(len(data)).str(name))
            # TODO: pace by FILE_ACK instead of sending everything at once.
            for offset in range(0, len(data), CHUNK):
                session.send(S.FILE_DATA, Writer().u32(offset).bytes(data[offset:offset + CHUNK]))
            session.send(S.FILE_END, Writer().u32(zlib.crc32(data)))
