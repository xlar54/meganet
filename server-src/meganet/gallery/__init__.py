"""Areas > Art Gallery (gallery.view): galleries of IFF pictures.

    58 = Art Gallery: one window with two views, re-sent as the user moves between them:
         - the galleries (title, pictures; the picked one's description below); Open. Holders
           of gallery.moderate also get, under "Admin Tools": New..., Edit..., Delete
         - a gallery's pictures (title, artist, added; the picked one's size, colours, views
           and description below);
           View, Slideshow, Upload and Paint (gallery.upload; paint.py), Back; moderators
           also Edit... and Delete (and an artist may edit or delete their own pictures)
    59 = New Gallery / Edit Gallery (modal): Title, Description
    60 = Edit Picture (modal): Title, Description
    61 = Upload Picture (modal): a drive, an IFF file from its directory, Title, Description
    62 = Loading a picture: what, a progress bar, Cancel
    63 = Delete Gallery? / Delete Picture?
    (the upload itself runs in the File Library's transfer window, 45; Paint's windows,
    and its "This One / New" question, take dynamic ids)

Viewing: View shows the picked picture over the whole screen (S.PICTURE); any key or click
goes back. Slideshow starts at the picked picture: Space (or a click) shows the next, Esc
goes back, and after the last one it goes back too. While a picture shows, the next one is
sent in the background, so it's usually there at once; if it isn't, the desktop comes back
with a "Loading" window and a progress bar until it is.

Pictures are kept as the IFF that was uploaded (galleries/<gallery id>/<picture id>.iff on the
server) and converted for the screen when shown (picture.py; cached). The client's resource
slots 2-3 and 4-5 hold two pictures (a hires one needs both of its pair).
"""

import asyncio
import os
import time

from .. import permissions as perms
from ..compose import refuse, MOD_ONLY
from ..protocol import S, Writer, WFlag, GFlag, clean_text, Caps, Local, LocalStatus, \
    LOCAL_DRIVES, UP_CHUNK, PIC_CLICK, PIC_ESC, PIC_HIRES, RESOURCE_SIZE
from ..session import resource_messages
from ..ui import (add_buttons, closer, confirm, Window, Label, TextBox, ListBox, TextArea,
                  DropDown, Progress, AreaWindow, MARGIN)
from ..filelib import Storage, Transfer, status_text, device_name, size_text, TYPE_OF
from .iff import read_iff, IFFError
from .picture import to_screen
from .paint import Paint, load_for_paint

SEE, UPLOAD, MODERATE = perms.GALLERY_VIEW, perms.GALLERY_UPLOAD, perms.GALLERY_MODERATE

WIN_GALLERY, WIN_GALLERY_EDIT, WIN_PICTURE_EDIT, WIN_UPLOAD, WIN_LOADING, WIN_DELETE = \
    range(58, 64)
TITLE = "Art Gallery"

TITLE_MAX = 24                   # a gallery's or a picture's title
DESC_LINES = 8
IFF_MAX = 512 * 1024             # the biggest upload
BUFFERS = (2, 4)                 # the client's resource slots for two pictures (2 slots each)
PACE = 4096                      # bytes left unsent before more of a picture goes out
CACHE = 8                        # pictures kept converted


def when(t, fmt="%y-%m-%d"):
    return time.strftime(fmt, time.localtime(t))


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def check_title(title, what="Titles"):
    if not 1 <= len(title) <= TITLE_MAX:
        return "%s are 1-%d characters." % (what, TITLE_MAX)
    if not all(" " <= ch <= "~" for ch in title):
        return "%s are plain letters, digits and punctuation." % what
    return None


def tidy_lines(lines, n=DESC_LINES):
    out = [clean_text(s).rstrip() for s in lines][:n]
    while out and not out[-1]:
        out.pop()
    return out


def size_line(p):
    return "%d x %d, %s" % (p["width"], p["height"], plural(p["colours"], "colour"))


class Gallery:
    def __init__(self, server):
        self.server = server
        self.root = server.galleries_dir
        os.makedirs(self.root, exist_ok=True)
        self.browsers = {}               # session -> Browser
        self.cache = {}                  # path -> (mtime, Screen), CACHE at most

    @property
    def db(self):
        return self.server.db

    # ---- who may do what ----

    @staticmethod
    def moderator(session):
        return session.can(MODERATE)

    def may_change(self, session, pic):
        """Edit or delete a picture: moderators, and its artist."""
        return pic is not None and (self.moderator(session) or (
            pic["artist"] is not None and pic["artist"] == session.user_id))

    # ---- the pictures on the server ----

    def full_path(self, rel):
        return os.path.join(self.root, rel)

    def load_screen(self, pic):
        """The picture converted for the client's screen (picture.Screen); IFFError or
        OSError if it can't be. Slow: call it in a thread."""
        path = self.full_path(pic["path"])
        mtime = os.path.getmtime(path)
        hit = self.cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        with open(path, "rb") as f:
            scr = to_screen(read_iff(f.read(IFF_MAX + 1)))
        if len(self.cache) >= CACHE:
            self.cache.pop(next(iter(self.cache)))
        self.cache[path] = (mtime, scr)
        return scr

    # ---- opening, and keeping everyone's windows in step ----

    def open(self, session):
        if not session.can(SEE):
            return refuse(session, TITLE, SEE)
        b = self.browsers.get(session) or Browser(self, session)
        b.view, b.gallery_id, b.picture_id = "galleries", None, None
        return b.show()

    def changed(self):
        for b in list(self.browsers.values()):
            b.refresh()

    def permissions_changed(self, session):
        show = session.picture
        if isinstance(show, Show) and not session.can(SEE):
            show.end("You can't use the Art Gallery now.")
        if isinstance(session.canvas, Paint) and not (session.can(SEE) and session.can(UPLOAD)):
            session.canvas.end("Your account can't paint now.")
        st = getattr(session, "storage", None)
        job = st.job if st is not None else None
        if isinstance(job, PictureUpload) and not session.can(UPLOAD):
            job.stop("Stopped: your account can't do that now.")
        b = self.browsers.get(session)
        if b is None:
            return
        if not session.can(SEE):
            b.close()
        else:
            b.show()

    def disconnected(self, session):
        self.browsers.pop(session, None)
        if isinstance(session.picture, Show):
            session.picture.stop()
        if isinstance(session.canvas, Paint):
            session.canvas.stop()


# ---------------------------------------------------------------------------------------------
# One user's Art Gallery window
# ---------------------------------------------------------------------------------------------

class Browser:
    def __init__(self, area, session):
        self.area = area
        self.session = session
        self.view = "galleries"
        self.gallery_id = self.picture_id = None
        self.ids = []
        self.win = None

    @property
    def db(self):
        return self.area.db

    @property
    def mod(self):
        return self.area.moderator(self.session)

    def say(self, text):
        if self.win is not None and self.win.shown:
            self.status.set_text(text[:68])

    def close(self):
        self.area.browsers.pop(self.session, None)
        for win_id in (WIN_GALLERY_EDIT, WIN_PICTURE_EDIT, WIN_UPLOAD, WIN_DELETE, WIN_GALLERY):
            win = self.session.windows.get(win_id)
            if win is not None:
                win.close()

    def _closed(self, window):
        if self.area.browsers.get(self.session) is self:
            del self.area.browsers[self.session]

    def gallery(self):
        return self.db.gallery(self.gallery_id) if self.gallery_id is not None else None

    # ---- the two views ----

    def show(self, status=None):
        self.area.browsers[self.session] = self
        g = self.gallery()
        if self.view == "pictures" and g is None:
            self.view, self.gallery_id = "galleries", None
        title = TITLE if self.view == "galleries" else "%s: %s" % (TITLE, g["title"])
        a = AreaWindow(title, WIN_GALLERY, on_close=self._closed)
        self.win = a.win
        getattr(self, "_show_" + self.view)(a, g, status)
        self.buttons()
        self.win.show(self.session)
        if self.list.selected is not None:
            self.list.set_value(self.list.selected)
        return self

    def refresh(self):
        if self.win is None or not self.win.shown:
            return None
        g = self.gallery()
        if self.view == "pictures" and g is None:
            self.view = "galleries"
            return self.show("That gallery is gone.")
        if self.view == "pictures" and self.session.can(UPLOAD) != self.upload_shown:
            return self.show()
        keep = self.gallery_id if self.view == "galleries" else self.picture_id
        self.list.set_rows(getattr(self, "_rows_" + self.view)(g))
        if keep in self.ids:
            self.list.selected = self.ids.index(keep)
            self.list.set_value(self.list.selected)
        else:
            self.list.selected = None
            if self.view == "galleries":
                self.gallery_id = None
            else:
                self.picture_id = None
        self.head.set_text(self._heading(g))
        self.about.set_lines(self._about())
        self.buttons()
        return None

    def picked(self):
        pid = self.gallery_id if self.view == "galleries" else self.picture_id
        return pid if pid in self.ids else None

    def buttons(self):
        on = self.picked() is not None
        for b in self.need:
            b.enable(on)
        if self.view == "pictures" and self.change_buttons:
            pic = self.db.gallery_picture(self.picture_id) if on else None
            ok = self.area.may_change(self.session, pic)
            for b in self.change_buttons:
                b.enable(ok)

    def _heading(self, g):
        if self.view == "galleries":
            n = len(self.ids)
            if not n:
                return "There are no galleries yet."
            return "%s." % plural(n, "gallery").replace("gallerys", "galleries")
        return "%s: %s" % (g["title"], plural(len(self.ids), "picture"))

    def _about(self):
        if self.view == "galleries":
            g = self.db.gallery(self.gallery_id) if self.gallery_id in self.ids else None
            if g is None:
                return []
            return g["description"].split("\n") if g["description"] else ["(No description.)"]
        p = self.db.gallery_picture(self.picture_id) if self.picture_id in self.ids else None
        if p is None:
            return []
        lines = ["%s, %s%s" % (size_line(p), plural(p["views"], "view"),
                               ", by %s" % p["artist_name"] if p["artist_name"] else "")]
        return lines + (p["description"].split("\n") if p["description"] else [])

    # the galleries
    def _rows_galleries(self, g=None):
        gs = self.db.galleries()
        self.ids = [x["id"] for x in gs]
        return ["%-*s %4d picture%s" % (TITLE_MAX, x["title"], x["pictures"],
                                        "" if x["pictures"] == 1 else "s") for x in gs]

    def _show_galleries(self, a, g, status):
        rows = self._rows_galleries()
        self.head = a.heading(self._heading(None))
        self.list = a.list(rows, self._pick_gallery, about=True, about_lines=self._about())
        if self.gallery_id in self.ids:
            self.list.selected = self.ids.index(self.gallery_id)
        self.about = a.about_view
        self.need = [a.command("Open", self._open_gallery, default=True)]
        self.change_buttons = []
        if self.mod:
            a.section("Admin Tools")
            _new, edit_b = a.pair(("New...", self._new_gallery), ("Edit...", self._edit_gallery))
            self.need += [edit_b, a.pair(("Delete", self._delete_gallery))]
        if status is None:
            status = "Pick a gallery and Open it." if rows else (
                "New... makes one." if self.mod else "There are no galleries yet.")
        self.status = a.status(status)

    # a gallery's pictures
    def _rows_pictures(self, g):
        ps = self.db.gallery_pictures(g["id"])
        self.ids = [p["id"] for p in ps]
        return ["%-*s %-10s %s" % (TITLE_MAX, p["title"][:TITLE_MAX],
                                   (p["artist_name"] or "-")[:10], when(p["added"]))
                for p in ps]               # (the size is in the details under the list)

    def _show_pictures(self, a, g, status):
        rows = self._rows_pictures(g)
        self.head = a.heading(self._heading(g))
        self.list = a.list(rows, self._pick_picture, about=True, about_lines=self._about(),
                           columns="%-*s %-10s %s" % (TITLE_MAX, "Title", "Artist", "Added"))
        if self.picture_id in self.ids:
            self.list.selected = self.ids.index(self.picture_id)
        self.about = a.about_view
        self.need = [a.command("View", self._view, default=True),
                     a.command("Slideshow", self._slideshow)]
        self.upload_shown = self.session.can(UPLOAD)
        if self.upload_shown:                  # (half width: no room for "...")
            a.pair(("Upload", self._upload), ("Paint", self._paint))
        a.command("Back", self._back)
        self.change_buttons = []
        if self.mod or self.upload_shown:      # (moderators: any picture; artists: theirs)
            a.section("Admin Tools" if self.mod else "Your Pictures")
            self.change_buttons = list(a.pair(("Edit...", self._edit_picture),
                                              ("Delete", self._delete_picture)))
        if status is None:
            status = "Pick a picture and View it." if rows else "No pictures here yet."
        self.status = a.status(status)

    # ---- handlers: everyone ----

    def _ok(self):
        if not self.session.can(SEE):
            refuse(self.session, TITLE, SEE)
            self.close()
            return False
        return True

    def _gallery(self):
        g = self.gallery()
        if g is None:
            self.view, self.gallery_id = "galleries", None
            self.show("That gallery is gone.")
        return g

    def _pick_gallery(self, listbox, index, double):
        if not self._ok() or listbox.selected is None or self.view != "galleries":
            return None
        self.gallery_id = self.ids[listbox.selected]
        self.buttons()
        if double:
            return self._open_gallery(None)
        self.about.set_lines(self._about())
        return self.say("")

    def _open_gallery(self, button):
        if not self._ok() or self.view != "galleries":
            return None
        if self.gallery_id not in self.ids:
            return self.say("Pick a gallery first.")
        if self._gallery() is None:
            return None
        self.view, self.picture_id = "pictures", None
        return self.show()

    def _pick_picture(self, listbox, index, double):
        if not self._ok() or listbox.selected is None or self.view != "pictures":
            return None
        self.picture_id = self.ids[listbox.selected]
        self.buttons()
        self.about.set_lines(self._about())
        if double:
            return self._view(None)
        return self.say("")

    def _back(self, button):
        if self._ok():
            self.view = "galleries"
            self.show()

    def _picture(self):
        p = self.db.gallery_picture(self.picture_id) if self.picture_id in self.ids else None
        if p is None:
            self.say("Pick a picture first.")
        return p

    def _can_show(self):
        if not Caps(self.session.caps & 0xFF) & Caps.PICTURE:
            self.session.alert(TITLE, "Your MegaNet client can't show pictures yet.")
            return False
        if isinstance(self.session.picture, Show):
            return False                  # (one is loading)
        return True

    def _view(self, button):
        if not self._ok() or self.view != "pictures":
            return None
        p = self._picture()
        if p is None or not self._can_show():
            return None
        return Show(self, [p["id"]], slideshow=False).start()

    def _slideshow(self, button):
        if not self._ok() or self.view != "pictures":
            return None
        p = self._picture()
        if p is None or not self._can_show():
            return None
        i = self.ids.index(p["id"])
        return Show(self, self.ids[i:] + self.ids[:i], slideshow=True).start()

    def _upload(self, button):
        if not self._ok() or self.view != "pictures":
            return None
        if not self.session.can(UPLOAD):
            return refuse(self.session, TITLE, UPLOAD)
        g = self._gallery()
        if g is None:
            return None
        return UploadDialog(self, g).show()

    def _paint(self, button):
        if not self._ok() or self.view != "pictures":
            return None
        if not self.session.can(UPLOAD):
            return refuse(self.session, TITLE, UPLOAD)
        caps = Caps(self.session.caps & 0xFF)
        if not caps & Caps.CANVAS or not caps & Caps.GRID:
            return self.session.alert(TITLE, "Your MegaNet client can't paint yet.")
        if self.session.canvas is not None or isinstance(self.session.picture, Show):
            return None
        g = self._gallery()
        if g is None:
            return None
        p = self.db.gallery_picture(self.picture_id) if self.picture_id in self.ids else None
        if p is not None and self.area.may_change(self.session, p):
            return PaintChoice(self, g, p).show()
        return Paint(self, g["id"]).start()

    # ---- handlers: changing pictures (moderators, and artists their own) ----

    def _changeable(self):
        if not self._ok() or self.view != "pictures":
            return None
        p = self._picture()
        if p is None:
            return None
        if not self.area.may_change(self.session, p):
            refuse(self.session, TITLE, MODERATE, "Only moderators and its artist can do that.")
            return None
        return p

    def _edit_picture(self, button):
        p = self._changeable()
        if p is not None:
            PictureDialog(self, p).show()

    def _delete_picture(self, button):
        p = self._changeable()
        if p is None:
            return None
        pid = p["id"]

        def go():
            q = self.db.gallery_picture(pid)
            if q is None or not self.area.may_change(self.session, q):
                return None
            self.db.delete_gallery_picture(pid)
            try:
                os.remove(self.area.full_path(q["path"]))
            except OSError:
                pass
            self.session.log("deleted picture %s (%s)" % (q["title"], q["path"]))
            self.picture_id = None
            self.area.changed()
            return self.say("Deleted %s." % q["title"])
        return confirm(self.session, "Delete Picture",
                       ["Delete %s?" % p["title"], "This can't be undone."], go, WIN_DELETE)

    # ---- handlers: moderators ----

    def _mod_ok(self):
        if not self.session.can(MODERATE):
            refuse(self.session, TITLE, MODERATE, MOD_ONLY)
            return False
        return self._ok()

    def _picked_gallery(self):
        g = self.db.gallery(self.gallery_id) if self.gallery_id in self.ids else None
        if g is None:
            self.say("Pick a gallery first.")
        return g

    def _new_gallery(self, button):
        if self._mod_ok() and self.view == "galleries":
            GalleryDialog(self, None).show()

    def _edit_gallery(self, button):
        if self._mod_ok() and self.view == "galleries":
            g = self._picked_gallery()
            if g is not None:
                GalleryDialog(self, g).show()

    def _delete_gallery(self, button):
        if not self._mod_ok() or self.view != "galleries":
            return None
        g = self._picked_gallery()
        if g is None:
            return None
        gid = g["id"]

        def go():
            if not self._mod_ok() or self.db.gallery(gid) is None:
                return None
            for rel in self.db.delete_gallery(gid):
                try:
                    os.remove(self.area.full_path(rel))
                except OSError:
                    pass
            try:
                os.rmdir(self.area.full_path(str(gid)))
            except OSError:
                pass
            self.session.log("deleted gallery %s" % g["title"])
            self.gallery_id = None
            self.area.changed()
            return self.say("Deleted %s." % g["title"])
        return confirm(self.session, "Delete Gallery",
                       ["Delete %s and its %s?" % (g["title"][:16], plural(g["pictures"],
                                                                           "picture")),
                        "This can't be undone."], go, WIN_DELETE)


# ---------------------------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------------------------

class GalleryDialog:
    """New Gallery / Edit Gallery (WIN_GALLERY_EDIT)."""
    W, H = 420, 96

    def __init__(self, browser, g):
        self.b, self.g = browser, g
        self.gallery_id = g["id"] if g else None

    def show(self):
        g = self.g
        win = Window.centred("Edit Gallery" if g else "New Gallery", self.W, self.H,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_GALLERY_EDIT)
        win.add(Label(8, 6, 96, 10, "Title:"))
        self.title = win.add(TextBox(112, 4, 300, 12, g["title"] if g else ""))
        win.add(Label(8, 22, 96, 10, "Description:"))
        self.desc = win.add(TextArea(112, 20, 300, 38, g["description"].split("\n")
                                     if g and g["description"] else []))
        self.status = win.add(Label(8, 62, self.W - 16, 10, ""))
        add_buttons(win, [("OK", self._ok, GFlag.DEFAULT), ("Cancel", closer, 0)])
        self.win = win
        win.show(self.b.session)
        return win

    def _ok(self, button):
        b = self.b
        if not b._mod_ok():
            return self.win.close()
        title = clean_text(self.title.value).strip()
        problem = check_title(title, "Gallery titles")
        if problem:
            return self.status.set_text(problem[:50])
        desc = "\n".join(tidy_lines(self.desc.lines))
        if self.gallery_id is None:
            gid = b.db.create_gallery(title, desc)
            if gid is None:
                return self.status.set_text("There is already a gallery called %s." % title)
            b.session.log("new gallery %s" % title)
            b.gallery_id = gid
            done = "Made %s." % title
        else:
            if b.db.gallery(self.gallery_id) is None:
                self.win.close()
                return b.say("That gallery is gone.")
            problem = b.db.update_gallery(self.gallery_id, title, desc)
            if problem:
                return self.status.set_text(problem[:50])
            b.session.log("edited gallery %s" % title)
            done = "Saved %s." % title
        self.win.close()
        b.area.changed()
        b.say(done)
        return None


class PictureDialog:
    """Edit Picture (WIN_PICTURE_EDIT): its title and description."""
    W, H = 420, 96

    def __init__(self, browser, p):
        self.b, self.picture_id, self.p = browser, p["id"], p

    def show(self):
        p = self.p
        win = Window.centred("Edit Picture", self.W, self.H,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             win_id=WIN_PICTURE_EDIT)
        win.add(Label(8, 6, 96, 10, "Title:"))
        self.title = win.add(TextBox(112, 4, 6 + 8 * TITLE_MAX, 12, p["title"]))
        win.add(Label(8, 22, 96, 10, "Description:"))
        self.desc = win.add(TextArea(112, 20, 300, 38, p["description"].split("\n")
                                     if p["description"] else []))
        self.status = win.add(Label(8, 62, self.W - 16, 10, ""))
        add_buttons(win, [("OK", self._ok, GFlag.DEFAULT), ("Cancel", closer, 0)])
        self.win = win
        win.show(self.b.session)
        return win

    def _ok(self, button):
        b = self.b
        p = b.db.gallery_picture(self.picture_id)
        if p is None or not b.area.may_change(b.session, p):
            self.win.close()
            return b.say("You can't change that picture now.")
        title = clean_text(self.title.value).strip()
        problem = check_title(title)
        if problem:
            return self.status.set_text(problem[:50])
        b.db.update_gallery_picture(p["id"], title, "\n".join(tidy_lines(self.desc.lines)))
        b.session.log("edited picture %s -> %s" % (p["title"], title))
        self.win.close()
        b.area.changed()
        return b.say("Saved %s." % title)


class PaintChoice:
    """Paint (window 63's id is taken: a dynamic one): on the picked picture (one of yours),
    or a new one."""

    def __init__(self, browser, g, p):
        self.b, self.gallery_id, self.p = browser, g["id"], p

    def show(self):
        win = Window.centred("Paint", 320, 50, flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE)
        win.add(Label(8, 4, 304, 10, ("Paint on %s, or a new picture?" % self.p["title"])[:38]))
        add_buttons(win, [("This One", self._this, GFlag.DEFAULT), ("New", self._new, 0),
                          ("Cancel", closer, 0)], centre=True)
        self.win = win
        win.show(self.b.session)

    def _new(self, button):
        self.win.close()
        if self.b._ok():
            Paint(self.b, self.gallery_id).start()

    async def _this(self, button):
        self.win.close()
        b = self.b
        p = b.db.gallery_picture(self.p["id"])
        if not b._ok() or p is None or not b.area.may_change(b.session, p):
            return b.say("You can't paint on that picture now.")
        img, problem = await load_for_paint(b.area, p)
        if problem:
            return b.session.alert("Paint", problem)
        if b.session.canvas is None:
            Paint(b, self.gallery_id, p, img).start()
        return None


class UploadDialog:
    """Upload Picture (WIN_UPLOAD): from drive 8-11, an IFF file from its directory, a
    title and a description."""
    W, H = 440, 171

    def __init__(self, browser, g):
        self.b, self.gallery_id = browser, g["id"]
        self.rows = []
        self.picked = None
        self.req = None

    @property
    def session(self):
        return self.b.session

    def show(self):
        st = Storage.of(self.session)
        if st.job is not None:
            return self.session.alert("Upload", "Wait for the transfer that's running.")
        if not st.caps() & Caps.DRIVES:
            return self.session.alert("Upload", "Your MegaNet client can't read its drives yet.")
        win = Window.centred("Upload Picture", self.W, self.H,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE, win_id=WIN_UPLOAD,
                             on_close=self._closed)
        win.add(Label(8, 4, 48, 10, "From:"))
        self.source = win.add(DropDown(56, 2, 96, ["Drive %d" % d for d in LOCAL_DRIVES], 0,
                                       on_select=self._source))
        self.where = win.add(Label(160, 4, 272, 10, ""))
        self.list = win.add(ListBox(8, 16, 424, 64, [], on_select=self._pick))
        win.add(Label(8, 86, 104, 10, "Title:"))
        self.title = win.add(TextBox(112, 84, 6 + 8 * TITLE_MAX, 12, ""))
        win.add(Label(8, 100, 104, 10, "Description:"))
        self.desc = win.add(TextArea(112, 98, 320, 30, []))
        self.status = win.add(Label(8, 132, 424, 10, ""))
        add_buttons(win, [("Upload", self._go, GFlag.DEFAULT), ("Cancel", self._cancel, 0)])
        self.win = win
        win.show(self.session)
        self._list()
        return win

    @property
    def dev(self):
        return LOCAL_DRIVES[self.source.selected or 0]

    def _source(self, dropdown, index, double):
        self.picked = None
        return self._list()

    def _list(self):
        st = Storage.of(self.session)
        if self.req is not None:
            st.pending.pop(self.req, None)
        self.rows = []
        self.list.set_rows([])
        self.status.set_text("Reading %s..." % device_name(self.dev))
        self.req = st.list_dir(self.dev, "", self._listed)

    def _listed(self, status, text, entries):
        self.req = None
        if not self.win.shown:
            return None
        if status != LocalStatus.OK:
            return self.status.set_text(status_text(status, text))
        head = next((e for e in entries if e[0] == Local.HEADER), None)
        self.where.set_text(("Disk: %s" % (head[2] if head else "?"))[:34])
        self.rows = [e for e in entries if e[0] in (Local.PRG, Local.SEQ, Local.USR)]
        self.list.set_rows(["%-16s %s %4d blocks" % (e[2], TYPE_OF[e[0]], e[1])
                            for e in self.rows])
        return self.status.set_text("Pick the IFF picture to send." if self.rows else
                                    "No PRG, SEQ or USR files on that disk.")

    def _pick(self, listbox, index, double):
        if listbox.selected is None or listbox.selected >= len(self.rows):
            return None
        self.picked = self.rows[listbox.selected]
        name = self.picked[2]
        for ext in (".IFF", ".ILBM", ".LBM", ".PIC"):
            if name.upper().endswith(ext):
                name = name[:-len(ext)]
        if not self.title.value.strip():
            self.title.set_text(name.strip().title()[:TITLE_MAX])
        return self.status.set_text("")

    def _closed(self, window):
        if self.req is not None:
            Storage.of(self.session).pending.pop(self.req, None)
            self.req = None

    def _cancel(self, button):
        self._closed(None)
        button.window.close()

    def _go(self, button):
        b, session = self.b, self.session
        if not b._ok() or not session.can(UPLOAD):
            self.win.close()
            return b.say("You can't upload pictures now.")
        if b.db.gallery(self.gallery_id) is None:
            self.win.close()
            return b.say("That gallery is gone.")
        if self.picked is None:
            return self.status.set_text("Pick a file to send first.")
        title = clean_text(self.title.value).strip()
        problem = check_title(title)
        if problem:
            return self.status.set_text(problem[:53])
        if self.picked[1] * 254 > IFF_MAX + 254:
            return self.status.set_text("That's too big: pictures are up to %d KB."
                                        % (IFF_MAX // 1024))
        desc = "\n".join(tidy_lines(self.desc.lines))
        self._closed(None)
        self.win.close()
        PictureUpload(b, self.gallery_id, self.dev, self.picked[0], self.picked[2], title,
                      desc).start()
        return None


class PictureUpload(Transfer):
    """An IFF from the client's drive (S.LOAD_FILE), checked and converted, then kept."""

    def __init__(self, browser, gallery_id, dev, kind, name, title, desc):
        super().__init__(browser, "Upload", "%s from %s" % (name, device_name(dev)))
        self.gallery_id, self.dev, self.kind, self.name = gallery_id, dev, kind, name
        self.pic_title, self.desc = title, desc
        self.size = None
        self.data = bytearray()

    def start(self):
        self.st.job = self
        req = self.st.start(self)
        self.open_window("Reading it from %s..." % device_name(self.dev))
        self.session.send(S.LOAD_FILE, Writer().u8(req).u8(self.dev).u8(self.kind)
                          .str(self.name))
        self.session.log("picture upload %s" % self.what)

    def fail(self, text):
        self.st.cancel(self)
        self.end(text, False)

    def on_up_begin(self, size):
        if self.over:
            return None
        if size > IFF_MAX:
            return self.fail("That's too big: pictures are up to %d KB." % (IFF_MAX // 1024))
        if size == 0:
            return self.fail("That file is empty.")
        self.size = size
        self.progress(0, size)
        return None

    def on_up_data(self, data):
        if self.over or self.size is None:
            return None
        if len(data) > UP_CHUNK or len(self.data) + len(data) > self.size:
            return self.fail("The client sent more than it said it would.")
        self.data += data
        self.progress(len(self.data), self.size)
        return None

    def on_up_end(self, crc):
        import zlib
        if self.over:
            return None
        if self.size is None or len(self.data) != self.size or zlib.crc32(self.data) != crc:
            self.session.warn("picture upload damaged: %s" % self.what)
            return self.end("It arrived damaged. Try again.", False)
        self.status.set_text("Checking the picture...")
        self.task = asyncio.get_running_loop().create_task(self._store(bytes(self.data)))
        return None

    async def _store(self, data):
        area, db = self.b.area, self.b.db
        try:
            img = await asyncio.to_thread(read_iff, data)
            await asyncio.to_thread(to_screen, img)
        except IFFError as e:
            self.session.warn("picture upload refused: %s: %s" % (self.what, e))
            return self.end(str(e), False)
        except Exception as e:                     # (a picture that breaks the converter)
            self.session.error("picture upload %s: %r" % (self.what, e))
            return self.end("MegaNet couldn't read that picture.", False)
        if db.gallery(self.gallery_id) is None or not self.session.can(UPLOAD):
            return self.end("You can't upload to that gallery now.", False)
        pid = db.add_gallery_picture(self.gallery_id, self.pic_title, self.desc, img.w, img.h,
                                     img.colours_used(), self.session.user_id)
        rel = "%d/%d.iff" % (self.gallery_id, pid)
        try:
            os.makedirs(os.path.dirname(area.full_path(rel)), exist_ok=True)
            with open(area.full_path(rel), "wb") as f:
                f.write(data)
        except OSError as e:
            db.delete_gallery_picture(pid)
            self.session.warn("picture not saved: %s" % e)
            return self.end("The server couldn't save it.", False)
        db.set_gallery_picture_path(pid, rel)
        self.session.log("uploaded picture %s (%dx%d) as galleries/%s" % (self.pic_title, img.w,
                                                                         img.h, rel))
        self.b.picture_id = pid
        self.end("Done: %s is in the gallery." % self.pic_title, True)
        area.changed()
        return None

    def on_done(self, status, text):
        if not self.over:
            self.session.warn("picture upload failed (%d %s): %s" % (status, text, self.what))
            self.end(status_text(status, text), False)


# ---------------------------------------------------------------------------------------------
# Showing pictures: View and Slideshow
# ---------------------------------------------------------------------------------------------

class Loader:
    """Sends one picture into one of the client's picture buffers, paced (PACE bytes ahead
    of the network), in the background. `bar` (a Progress) follows it when set."""

    def __init__(self, show, index, buf):
        self.show = show
        self.session = show.session
        self.index = index
        self.picture_id = show.ids[index]
        self.buf = buf
        self.screen = None
        self.error = None
        self.done_bytes, self.total = 0, 1
        self.bar = None
        self.task = asyncio.get_running_loop().create_task(self._run())

    def key(self):
        return ("picture", self.picture_id, self.version)

    async def _run(self):
        session = self.session
        pic = session.server.db.gallery_picture(self.picture_id)
        if pic is None:
            self.error = "That picture is gone."
            return
        try:
            # (the file's time: a picture painted over again is sent again)
            self.version = os.stat(self.show.area.full_path(pic["path"])).st_mtime_ns
            self.screen = await asyncio.to_thread(self.show.area.load_screen, pic)
        except (OSError, IFFError) as e:
            session.warn("picture %d can't be shown: %s" % (self.picture_id, e))
            self.error = "That picture can't be shown."
            return
        self.title = pic["title"]
        slot = BUFFERS[self.buf]
        key = self.key()
        if session.resources.get(slot) == key:
            return                         # (it's there from before)
        parts = [(slot + i, self.screen.data[i * RESOURCE_SIZE:(i + 1) * RESOURCE_SIZE])
                 for i in range(2 if self.screen.mode == PIC_HIRES else 1)]
        msgs = []
        base = 0
        for s, data in parts:
            session.resources.pop(s, None)       # (half sent: not there)
            msgs += [(base + done, t, w) for done, t, w in resource_messages(s, data, True)]
            base += len(data)
        self.total = base
        transport = session.writer.transport
        for done, t, w in msgs:
            while transport is not None and not session.closed and \
                    transport.get_write_buffer_size() > PACE:
                await asyncio.sleep(0.02)
            if session.closed:
                return
            session.send(t, w)
            self.done_bytes = done
            if self.bar is not None and self.bar.shown:
                self.bar.set_percent(100 * done // self.total)
        session.resources[slot] = key

    def percent(self):
        return 100 * self.done_bytes // max(1, self.total)


class Show:
    """View (one picture) or Slideshow (ids in order): session.picture while it runs."""

    def __init__(self, browser, ids, slideshow):
        self.b = browser
        self.area = browser.area
        self.session = browser.session
        self.ids = ids
        self.slideshow = slideshow
        self.index = 0
        self.showing = None                # the buffer on the client's screen, or None
        self.loaders = {}                  # buffer -> Loader
        self.win = None                    # the Loading window
        self.over = False

    def start(self):
        self.session.picture = self
        self.session.log("%s from picture %d" % ("slideshow" if self.slideshow else "view",
                                                 self.ids[0]))
        self._go(0)

    def _go(self, index):
        """go(index) in the background: the session goes on reading messages meanwhile (a
        Cancel), so nothing here is handed back to it to wait for."""
        self.task = asyncio.get_running_loop().create_task(self.go(index))

    def _loader(self, index):
        """The Loader of picture `index`, started if it isn't (into the buffer not shown)."""
        for l in self.loaders.values():
            if l.index == index:
                return l
        buf = 1 if self.showing == 0 else 0
        old = self.loaders.pop(buf, None)
        if old is not None:
            old.task.cancel()
        l = self.loaders[buf] = Loader(self, index, buf)
        return l

    async def go(self, index):
        self.index = index
        l = self._loader(index)
        if not l.task.done():
            if self.showing is not None:           # the desktop back, while it comes
                self.session.send(S.PICTURE_END)
                self.showing = None
            self._open_loading(l)
            l.bar = self.bar
            self.bar.set_percent(l.percent())
            try:
                await asyncio.shield(l.task)
            except asyncio.CancelledError:
                return None
            if self.win is not None:
                self.win.close()
                self.win = None
        if self.over:
            return None
        if l.error:
            return self.end(l.error)
        scr = l.screen
        w = Writer().u8(BUFFERS[l.buf]).u8(scr.mode).u8(scr.border).u8(len(scr.palette))
        for r, g, b in scr.palette:
            w.u8(r).u8(g).u8(b)
        self.session.send(S.PICTURE, w)
        self.showing = l.buf
        self.session.server.db.count_view(l.picture_id)
        self.b.picture_id = l.picture_id
        if self.slideshow and index + 1 < len(self.ids):
            self._loader(index + 1)                # the next one, while this one shows
        return None

    def _open_loading(self, l):
        if self.win is not None and self.win.shown:
            self.what.set_text(self._what(l))
            return
        win = Window.centred("Loading", 300, 54, win_id=WIN_LOADING,
                             flags=WFlag.MODAL | WFlag.CLOSE, on_close=self._cancelled)
        self.what = win.add(Label(MARGIN, 4, 300 - 2 * MARGIN, 10, self._what(l)))
        self.bar = win.add(Progress(MARGIN, 18, 300 - 2 * MARGIN))
        add_buttons(win, [("Cancel", self._cancel, 0)], centre=True)
        self.win = win
        win.show(self.session)

    def _what(self, l):
        p = self.session.server.db.gallery_picture(l.picture_id)
        name = p["title"] if p else "?"
        if self.slideshow:
            return ("Picture %d of %d: %s" % (l.index + 1, len(self.ids), name))[:35]
        return ("Loading %s..." % name)[:35]

    def _cancel(self, button):
        self.end("Cancelled.")

    def _cancelled(self, window):
        self.win = None
        self.end("Cancelled.")

    def on_key(self, key):
        if self.over or self.showing is None:
            return None
        if not self.slideshow or key == PIC_ESC:
            return self.end()
        if key in (ord(" "), PIC_CLICK, 13):
            if self.index + 1 >= len(self.ids):
                return self.end("That was the last picture.")
            self._go(self.index + 1)
        return None

    def stop(self):
        """Gone without a word (the connection went)."""
        self.over = True
        for l in self.loaders.values():
            l.task.cancel()
        if self.session.picture is self:
            self.session.picture = None

    def end(self, text=None):
        if self.over:
            return None
        self.stop()
        if self.showing is not None:
            self.session.send(S.PICTURE_END)
            self.showing = None
        if self.win is not None:
            win, self.win = self.win, None
            win.close()
        b = self.b
        if text and b.win is not None and b.win.shown:
            b.refresh()
            b.say(text)
        elif b.win is not None and b.win.shown:
            b.refresh()
        return None
