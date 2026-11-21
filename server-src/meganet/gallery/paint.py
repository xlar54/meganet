"""Paint: the Art Gallery's paint program, run on the server (gallery.upload).

The server keeps the picture (320x200, up to 32 colours) and does all the painting; the
client shows it as its desktop (S.CANVAS), sends the mouse on it (C.CANVAS), and gets back
the pixels that changed (S.CANVAS_RECT). So the client draws nothing by itself but a stroke
or a shape's outline while the mouse is held (S.CANVAS_PEN), which the server's answer then
covers. See protocol.py and client-src/canvas.asm.

The tool window (a dynamic id, over the picture; it can be dragged, or minimized to see the
whole picture):
    Draw / Line / Box / Oval / Fill / Pick   (radio buttons: the tool)
    Solid (boxes and ovals filled), Size (the brush: a square 1-8 pixels across)
    the palette: 32 colours (a GRID; the picked one framed); a right click on the picture
    picks the colour under it, whatever the tool
    Undo (8 steps), Clear (to colour 0), Save..., Done
Save... asks for a title and a description and writes an ILBM (iff.write_ilbm) into the
gallery: a new picture, or (painting on one of your own) that one again. Done (or the close
box) asks first if there are changes not saved.

Drawing is the same on both sides where it shows: a brush dot is a square `size` across from
(size - 1) // 2 up and left of the point; lines are Bresenham's, from the first point.
"""

import asyncio
import math
import os

from .. import permissions as perms
from ..protocol import (S, Writer, WFlag, GFlag, Caps, clean_text, CanvasPen, CanvasEvent,
                        CANVAS_FIRST, CANVAS_W, CANVAS_H, RESOURCE_CHUNK, GRID_MARK1)
from ..session import resource_messages
from ..ui import (Window, Label, TextBox, TextArea, Radio, CheckBox, DropDown, Button, Grid,
                  Progress, add_buttons, closer, MARGIN)
from .iff import Image, write_ilbm, read_iff, IFFError
from .picture import packbits

UPLOAD = perms.GALLERY_UPLOAD
CANVAS_SLOT = 6                  # the client's resource slots: the picture, the palette tiles
PALETTE_SLOT = 7
COLOURS = 32
TOOLS = ["Draw", "Line", "Box", "Oval", "Fill", "Pick"]
PEN = {"Draw": CanvasPen.FREE, "Line": CanvasPen.LINE, "Box": CanvasPen.BOX,
       "Oval": CanvasPen.BOX, "Fill": CanvasPen.NONE, "Pick": CanvasPen.NONE}
SIZES = [1, 2, 3, 4, 6, 8]
UNDO = 8
TILE_W, TILE_H = 16, 8           # a palette swatch
PACE = 4096
TITLE_MAX = 24
DESC_LINES = 8

# the colours a new picture starts with (colour 0, black, is the background Clear uses)
DEFAULT_PALETTE = [
    (0, 0, 0), (255, 255, 255), (85, 85, 85), (136, 136, 136), (187, 187, 187),
    (204, 0, 0), (119, 0, 0), (255, 136, 0), (136, 68, 0), (255, 238, 0), (170, 170, 0),
    (102, 221, 0), (0, 153, 0), (0, 85, 0), (0, 204, 204), (0, 119, 136), (102, 170, 255),
    (0, 68, 221), (0, 0, 119), (136, 0, 204), (204, 102, 255), (238, 0, 170),
    (255, 153, 187), (255, 204, 153), (204, 153, 102), (85, 51, 17), (153, 204, 255),
    (204, 255, 102), (221, 170, 51), (102, 0, 51), (255, 248, 220), (51, 51, 68)]
assert len(DEFAULT_PALETTE) == COLOURS


def canvas_offset(x, y):
    """Where picture pixel (x, y) is in the client's slot (the lores framebuffer order)."""
    return (y >> 3) * 2560 + (x >> 2) * 32 + (y & 7) * 4 + (x & 3)


def to_slot(pixels):
    """The picture (row by row, colours) as the client keeps it: framebuffer order, palette
    entries."""
    out = bytearray(CANVAS_W * CANVAS_H)
    for y in range(CANVAS_H):
        row = y * CANVAS_W
        for x in range(CANVAS_W):
            out[canvas_offset(x, y)] = pixels[row + x] + CANVAS_FIRST
    return bytes(out)


def paintable(img):
    """None if `img` can be painted on, else why not."""
    if (img.w, img.h) != (CANVAS_W, CANVAS_H):
        return "Paint works on 320 x 200 pictures (this one is %d x %d)." % (img.w, img.h)
    if img.pixels is None or (max(img.pixels) if img.pixels else 0) >= COLOURS:
        return "Paint works on pictures of up to %d colours." % COLOURS
    return None


def line_points(x0, y0, x1, y1):
    """Bresenham's line from (x0, y0) to (x1, y1), as client-src/canvas.asm draws it."""
    dx, sx = abs(x1 - x0), 1 if x1 >= x0 else -1
    dy, sy = -abs(y1 - y0), 1 if y1 >= y0 else -1
    err = dx + dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


class Canvas:
    """The picture: pixels row by row (colour numbers), and what changed since flush()."""

    def __init__(self, pixels=None):
        self.px = bytearray(pixels) if pixels is not None else bytearray(CANVAS_W * CANVAS_H)
        self.dirty = None                # [x0, y0, x1, y1] or None

    def get(self, x, y):
        return self.px[y * CANVAS_W + x]

    def _touch(self, x0, y0, x1, y1):
        if self.dirty is None:
            self.dirty = [x0, y0, x1, y1]
        else:
            d = self.dirty
            d[0], d[1], d[2], d[3] = min(d[0], x0), min(d[1], y0), max(d[2], x1), max(d[3], y1)

    def plot(self, x, y, c):
        if 0 <= x < CANVAS_W and 0 <= y < CANVAS_H:
            self.px[y * CANVAS_W + x] = c
            self._touch(x, y, x, y)

    def span(self, x0, x1, y, c):
        if not 0 <= y < CANVAS_H:
            return
        x0, x1 = max(0, min(x0, x1)), min(CANVAS_W - 1, max(x0, x1))
        if x0 > x1:
            return
        self.px[y * CANVAS_W + x0:y * CANVAS_W + x1 + 1] = bytes((c,)) * (x1 - x0 + 1)
        self._touch(x0, y, x1, y)

    def brush(self, x, y, c, size):
        h = (size - 1) // 2
        for yy in range(y - h, y - h + size):
            self.span(x - h, x - h + size - 1, yy, c)

    def line(self, x0, y0, x1, y1, c, size):
        for x, y in line_points(x0, y0, x1, y1):
            self.brush(x, y, c, size)

    def box(self, x0, y0, x1, y1, c, size, solid):
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if solid:
            for y in range(y0, y1 + 1):
                self.span(x0, x1, y, c)
            return
        for a, b, p, q in ((x0, y0, x1, y0), (x0, y1, x1, y1), (x0, y0, x0, y1),
                           (x1, y0, x1, y1)):
            self.line(a, b, p, q, c, size)

    def oval(self, x0, y0, x1, y1, c, size, solid):
        """The ellipse inside the box (x0, y0)-(x1, y1)."""
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        a, b = (x1 - x0) / 2, (y1 - y0) / 2
        if a < 0.5 or b < 0.5:
            return self.box(x0, y0, x1, y1, c, size, True)
        for y in range(y0, y1 + 1):              # each row: where the edge is
            t = (y - cy) / b
            w = a * math.sqrt(max(0.0, 1 - t * t))
            l, r = round(cx - w), round(cx + w)
            if solid:
                self.span(l, r, y, c)
            else:
                self.brush(l, y, c, size)
                self.brush(r, y, c, size)
        if not solid:                            # each column too (no gaps at the ends)
            for x in range(x0, x1 + 1):
                t = (x - cx) / a
                h = b * math.sqrt(max(0.0, 1 - t * t))
                self.brush(x, round(cy - h), c, size)
                self.brush(x, round(cy + h), c, size)

    def fill(self, x, y, c):
        """Flood fill (4 ways) from (x, y) with colour c."""
        old = self.get(x, y)
        if old == c:
            return
        px, w = self.px, CANVAS_W
        stack = [(x, y)]
        while stack:
            x, y = stack.pop()
            if px[y * w + x] != old:
                continue
            l = x
            while l > 0 and px[y * w + l - 1] == old:
                l -= 1
            r = x
            while r < w - 1 and px[y * w + r + 1] == old:
                r += 1
            self.span(l, r, y, c)
            for ny in (y - 1, y + 1):
                if 0 <= ny < CANVAS_H:
                    i, inside = l, False
                    while i <= r:
                        if px[ny * w + i] == old:
                            if not inside:
                                stack.append((i, ny))
                                inside = True
                        else:
                            inside = False
                        i += 1

    def take_dirty(self):
        d, self.dirty = self.dirty, None
        return d

    def rect_messages(self, d):
        """S.CANVAS_RECT messages for the rectangle d = [x0, y0, x1, y1]: row bands whose
        packed bytes fit in RESOURCE_CHUNK."""
        x0, y0, x1, y1 = d
        w = x1 - x0 + 1
        rows = [packbits(bytes(v + CANVAS_FIRST for v in
                               self.px[y * CANVAS_W + x0:y * CANVAS_W + x1 + 1]))
                for y in range(y0, y1 + 1)]
        out, start, part = [], y0, []
        for i, p in enumerate(rows):
            if part and sum(len(q) for q in part) + len(p) > RESOURCE_CHUNK:
                out.append((start, part))
                start, part = y0 + i, []
            part.append(p)
        if part:
            out.append((start, part))
        # (a row's packed bytes run on into the next row's: one PackBits stream per band, as
        # the client reads it; each row was packed apart, so that's still right)
        return [Writer().u16(x0).u8(sy).u16(w).u8(len(ps)).bytes(b"".join(ps))
                for sy, ps in out]


class Paint:
    """One user painting: session.canvas while it runs."""

    def __init__(self, browser, gallery_id, picture=None, img=None):
        self.b = browser
        self.area = browser.area
        self.session = browser.session
        self.gallery_id = gallery_id
        self.picture_id = picture["id"] if picture else None
        self.title = picture["title"] if picture else ""
        self.description = picture["description"] if picture else ""
        if img is not None:
            pal = list(img.palette[:COLOURS])
            self.palette = pal + DEFAULT_PALETTE[len(pal):]
            self.canvas = Canvas(img.pixels)
        else:
            self.palette = list(DEFAULT_PALETTE)
            self.canvas = Canvas()
        self.tool = "Draw"
        self.colour = 1
        self.size = 1
        self.solid = False
        self.undo = []
        self.changed = False
        self.anchor = None               # a press: (x, y)
        self.last = None                 # freehand: the last point
        self.win = None
        self.over = False
        self.task = None

    # ---- starting and ending ----

    def start(self):
        self.session.canvas = self
        self.session.log("paint %s" % ("picture %d" % self.picture_id if self.picture_id
                                        else "a new picture"))
        self.task = asyncio.get_running_loop().create_task(self._start())

    async def _start(self):
        session = self.session
        msgs = resource_messages(CANVAS_SLOT, to_slot(self.canvas.px), True)
        loading = None
        if len(msgs) > 4:                # (more than a blank page: say what's coming)
            loading = Window.centred("Loading", 260, 40, flags=WFlag.MODAL)
            loading.add(Label(MARGIN, 4, 260 - 2 * MARGIN, 10, "Loading the picture..."))
            bar = loading.add(Progress(MARGIN, 20, 260 - 2 * MARGIN))
            loading.show(session)
        transport = session.writer.transport
        for done, t, w in msgs:
            while transport is not None and not session.closed and \
                    transport.get_write_buffer_size() > PACE:
                await asyncio.sleep(0.02)
            if session.closed or self.over:
                return
            session.send(t, w)
            if loading is not None:
                bar.set_percent(100 * done // len(self.canvas.px))
        session.resources.pop(CANVAS_SLOT, None)
        if loading is not None:
            loading.close()
        tiles = b"".join(bytes((CANVAS_FIRST + i,)) * (TILE_W * TILE_H) for i in range(COLOURS))
        session.send_resource(PALETTE_SLOT, ("paint-palette", COLOURS), tiles)
        self._send_canvas()
        self._open_tools()
        self._send_pen()

    def _send_canvas(self):
        w = Writer().u8(CANVAS_SLOT).u8(len(self.palette))
        for r, g, b in self.palette:
            w.u8(r).u8(g).u8(b)
        self.session.send(S.CANVAS, w)

    def _open_tools(self, status=""):
        win = Window("Paint", 640 - 136 - 8 - 4, 12, 136, 146, on_close=self._closed,
                     minimize=True)
        self.radios = {}
        for i, name in enumerate(TOOLS):
            self.radios[name] = win.add(Radio(4 + 66 * (i % 2), 2 + 12 * (i // 2), 62, 12, name,
                                              checked=name == self.tool,
                                              on_select=self._pick_tool))
        self.solid_box = win.add(CheckBox(4, 40, 62, 12, "Solid", self.solid,
                                          on_select=self._pick_solid))
        win.add(Label(70, 42, 32, 10, "Size"))
        self.size_dd = win.add(DropDown(102, 40, 30, [str(s) for s in SIZES],
                                        selected=SIZES.index(self.size),
                                        on_select=self._pick_size))
        self.grid = win.add(Grid(4, 56, 8, 4, TILE_W, TILE_H, PALETTE_SLOT,
                                 cells=self._cells(), on_select=self._pick_colour))
        win.add(Button(4, 92, 62, 16, "Undo", on_click=self._undo))
        win.add(Button(70, 92, 62, 16, "Clear", on_click=self._clear))
        win.add(Button(4, 112, 62, 16, "Save...", on_click=self._save))
        win.add(Button(70, 112, 62, 16, "Done", GFlag.DEFAULT, on_click=self._done))
        self.status = win.add(Label(4, 132, 128, 10, status))
        self.win = win
        win.show(self.session)

    def _cells(self):
        return [i | (GRID_MARK1 if i == self.colour else 0) for i in range(COLOURS)]

    def _send_pen(self):
        self.session.send(S.CANVAS_PEN, Writer().u8(PEN[self.tool])
                          .u8(CANVAS_FIRST + self.colour).u8(self.size))

    def say(self, text):
        if self.win is not None and self.win.shown:
            self.status.set_text(text[:16])

    def stop(self):
        """Gone without a word (the connection went)."""
        self.over = True
        if self.task is not None:
            self.task.cancel()
        if self.session.canvas is self:
            self.session.canvas = None

    def end(self, text=None):
        if self.over:
            return None
        self.stop()
        if self.win is not None and self.win.shown:
            self.win.close()
        self.session.send(S.CANVAS_END)
        b = self.b
        if b.win is not None and b.win.shown:
            b.refresh()
            if text:
                b.say(text)
        return None

    # ---- the tool window ----

    def _ok(self):
        if self.over:
            return False
        if not self.session.can(UPLOAD):
            self.end("Your account can't paint now.")
            return False
        return True

    def _pick_tool(self, radio, index, double):
        if not self._ok():
            return None
        self.tool = radio.text
        for name, r in self.radios.items():
            if r is not radio and r.checked:
                r.set_checked(False)
        if not radio.checked:
            radio.set_checked(True)
        self._send_pen()
        return self.say("")

    def _pick_solid(self, box, index, double):
        if self._ok():
            self.solid = box.checked

    def _pick_size(self, dd, index, double):
        if self._ok() and 0 <= index < len(SIZES):
            self.size = SIZES[index]
            self._send_pen()

    def _pick_colour(self, grid, index, double):
        if self._ok() and 0 <= index < COLOURS:
            self._set_colour(index)

    def _set_colour(self, c):
        self.colour = c
        self.grid.set_cells(self._cells())
        self._send_pen()

    def _push_undo(self):
        self.undo.append(bytes(self.canvas.px))
        del self.undo[:-UNDO]
        self.changed = True

    def _undo(self, button):
        if not self._ok():
            return None
        if not self.undo:
            return self.say("Nothing to undo.")
        self.canvas.px[:] = self.undo.pop()
        self.canvas.dirty = [0, 0, CANVAS_W - 1, CANVAS_H - 1]
        self.flush()
        return self.say("")

    def _clear(self, button):
        if not self._ok():
            return None
        self._push_undo()
        self.canvas.px[:] = bytes(len(self.canvas.px))
        self.canvas.dirty = [0, 0, CANVAS_W - 1, CANVAS_H - 1]
        self.flush()
        return self.say("Cleared.")

    def _done(self, button):
        if not self.changed:
            return self.end()
        return self._ask_leave()

    def _closed(self, window):
        self.win = None
        if self.over:
            return None
        if not self.changed:
            return self.end()
        return self._ask_leave()

    def _ask_leave(self):
        win = Window.centred("Leave Paint", 300, 50,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE,
                             on_close=self._stay)
        win.add(Label(MARGIN, 4, 284, 10, "Your changes aren't saved."))
        add_buttons(win, [("Leave", self._leave, 0), ("Cancel", self._stay_button,
                                                      GFlag.DEFAULT)], centre=True)
        win.show(self.session)

    def _leave(self, button):
        button.window.close()
        self.end()

    def _stay_button(self, button):
        button.window.close()
        self._stay(None)

    def _stay(self, window):
        if not self.over and (self.win is None or not self.win.shown):
            self._open_tools()

    # ---- the mouse on the picture ----

    def flush(self):
        d = self.canvas.take_dirty()
        if d is not None:
            for w in self.canvas.rect_messages(d):
                self.session.send(S.CANVAS_RECT, w)

    def on_mouse(self, event, x, y):
        if not self._ok():
            return None
        if not (0 <= x < CANVAS_W and 0 <= y < CANVAS_H):
            return None
        cv = self.canvas
        if event == CanvasEvent.RIGHT or (event == CanvasEvent.DOWN and self.tool == "Pick"):
            return self._set_colour(cv.get(x, y))
        tool, c, size = self.tool, self.colour, self.size
        if event == CanvasEvent.DOWN:
            self.anchor = self.last = (x, y)
            if tool == "Draw":
                self._push_undo()
                cv.brush(x, y, c, size)
            elif tool == "Fill":
                self._push_undo()
                cv.fill(x, y, c)
        elif event == CanvasEvent.MOVE:
            if tool == "Draw" and self.last is not None:
                cv.line(*self.last, x, y, c, size)
                self.last = (x, y)
        elif event == CanvasEvent.UP:
            if tool == "Draw" and self.last is not None and self.last != (x, y):
                cv.line(*self.last, x, y, c, size)
            elif tool in ("Line", "Box", "Oval") and self.anchor is not None:
                self._push_undo()
                ax, ay = self.anchor
                if tool == "Line":
                    cv.line(ax, ay, x, y, c, size)
                elif tool == "Box":
                    cv.box(ax, ay, x, y, c, size, self.solid)
                else:
                    cv.oval(ax, ay, x, y, c, size, self.solid)
            self.anchor = self.last = None
        self.flush()
        return None

    # ---- saving ----

    def _save(self, button):
        if not self._ok():
            return None
        return SaveDialog(self).show()

    def save(self, title, description):
        """Write the picture into the gallery: None, or why not."""
        area, db = self.area, self.area.db
        if db.gallery(self.gallery_id) is None:
            return "That gallery is gone."
        img = Image(CANVAS_W, CANVAS_H, palette=self.palette, pixels=bytes(self.canvas.px))
        data = write_ilbm(img)
        colours = img.colours_used()
        pic = db.gallery_picture(self.picture_id) if self.picture_id else None
        if pic is not None and area.may_change(self.session, pic):
            pid, rel = pic["id"], pic["path"]
            db.update_gallery_picture(pid, title, description)
            db.set_gallery_picture_size(pid, CANVAS_W, CANVAS_H, colours)
        else:
            pid = db.add_gallery_picture(self.gallery_id, title, description, CANVAS_W,
                                         CANVAS_H, colours, self.session.user_id)
            rel = "%d/%d.iff" % (self.gallery_id, pid)
        try:
            path = area.full_path(rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        except OSError as e:
            if pic is None:
                db.delete_gallery_picture(pid)
            self.session.warn("painting not saved: %s" % e)
            return "The server couldn't save it."
        db.set_gallery_picture_path(pid, rel)
        area.cache.pop(area.full_path(rel), None)
        self.picture_id, self.title, self.description = pid, title, description
        self.changed = False
        self.b.picture_id = pid
        self.session.log("saved painting %s as galleries/%s" % (title, rel))
        area.changed()
        return None


class SaveDialog:
    W, H = 400, 96

    def __init__(self, paint):
        self.p = paint

    def show(self):
        p = self.p
        win = Window.centred("Save Picture", self.W, self.H,
                             flags=WFlag.MODAL | WFlag.CLOSE | WFlag.MOVABLE)
        win.add(Label(8, 6, 96, 10, "Title:"))
        self.title = win.add(TextBox(104, 4, 6 + 8 * TITLE_MAX, 12, p.title))
        win.add(Label(8, 22, 96, 10, "Description:"))
        self.desc = win.add(TextArea(104, 20, 288, 38, p.description.split("\n")
                                     if p.description else []))
        self.status = win.add(Label(8, 62, self.W - 16, 10,
                                    "Saved over %s." % p.title[:20] if p.picture_id
                                    else "A new picture in the gallery."))
        add_buttons(win, [("Save", self._ok, GFlag.DEFAULT), ("Cancel", closer, 0)])
        self.win = win
        win.show(p.session)
        return None

    def _ok(self, button):
        p = self.p
        if not p._ok():
            return self.win.close()
        title = clean_text(self.title.value).strip()
        if not 1 <= len(title) <= TITLE_MAX:
            return self.status.set_text("Titles are 1-%d characters." % TITLE_MAX)
        lines = [clean_text(s).rstrip() for s in self.desc.lines][:DESC_LINES]
        while lines and not lines[-1]:
            lines.pop()
        problem = p.save(title, "\n".join(lines))
        if problem:
            return self.status.set_text(problem[:48])
        self.win.close()
        return p.say("Saved.")


async def load_for_paint(area, pic):
    """(Image, None) for a picture to paint on, or (None, why not)."""
    try:
        with open(area.full_path(pic["path"]), "rb") as f:
            data = f.read()
        img = await asyncio.to_thread(read_iff, data)
    except (OSError, IFFError) as e:
        return None, "That picture can't be read (%s)." % e
    problem = paintable(img)
    return (None, problem) if problem else (img, None)
