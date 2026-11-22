# lib/gui: Windows 95-style GUI for the MEGA65

`gui.asm` is a self-contained windowing toolkit for the 640x200, 256-colour Full Colour screen. It has
overlapping windows with title bars, close boxes, dragging and a front-to-back order, plus buttons,
labels, text boxes, password boxes, list boxes and text views, keyboard focus, and a two-sprite
mouse pointer. Nothing in it
is specific to MegaNet, so it can become a separate library later.

## Needs

`lib/fcm640.asm`, `lib/draw640.asm` (+ `lib/font8.asm`), `lib/dma.asm`, `lib/mouse.asm` (with
`MOUSE_MAX_X = 639` defined before it), `lib/hwsprite.asm`, `lib/keyboard.asm`, and `lib/zp.asm`'s
`txt_ptr`, `tmp6` and `ptr1`. It puts its text buffers in `.section bss`: the program needs a
`.dsection bss`.

## Use

```
        jsr gui_init                    ; after f640_init (it writes $D031, which resets sprites)
        #GUI_WIN 1, 100, 40, 300, 100, GWF_CLOSE | GWF_MOVABLE, title
        #GUI_GAD 1, 1, GK_LABEL, 8, 4, 80, 12, 0, 0, s_name
        #GUI_GAD 1, 2, GK_TEXT, 96, 4, 180, 12, 0, 16, 0
        #GUI_GAD 1, 3, GK_BUTTON, 100, 60, 80, 16, GGF_DEFAULT, 0, s_ok
        jsr gui_redraw
loop:   jsr wait_frame
        jsr gui_update                  ; carry set: ge_type, ge_win, ge_gid, ge_key
        bcc loop
        ...
```

The routines and arguments are listed at the top of `gui.asm`. Window coordinates are the outer
size on screen; gadget coordinates are inside the window's client area (`GUI_CLIENT_X/Y` from its top
left corner).

- **Colours:** palette entries 0-15 (`GC_*`). `gui_init` writes them. A program's art uses 16-254;
  entry 255 shows the colour-RAM colour in FCM.
- **Events:**
  - `GE_CLICK`: a button released over itself, or RETURN for the front window's `GGF_DEFAULT` button.
  - `GE_CLOSE`: the close box. The program decides whether to call `gui_win_close`.
  - `GE_KEY`: a key no gadget used, with `ge_gid` = the focused gadget.
  - `GE_SELECT`: a list row clicked. `ge_val` = the row; bit 15 is set for a double click (the
    same row again within half a second).
- **Lists and text views:**
  - Each one gets an 8 KB block at `GUI_BIG_MEM` (default `$8200000`, attic), at most
    `GUI_MAXBIG` (default 8) at a time.
- **Limits** (`.weak`: define them before including `gui.asm` to change them):
  - `GUI_MAXWIN` windows open at once (default 8);
  - `GUI_MAXGAD` gadgets in all of them together (default 48, at most 127);
  - `GUI_MAXBIG` lists, views, text areas and drop-downs (default 8, up to 255).
  - When they run out, a window opens with gadgets missing, or not at all. MegaNet uses
    12 / 80 / 16 (`client-src/main.asm`).
  - A list holds 128 rows of up to 63 characters: set them with `gui_list_total` and
    `gui_list_row`, then `gui_gad_redraw`.
  - A text view keeps its last 64 lines of up to 63 characters. `gui_view_append` word-wraps a
    line to the view's width and redraws it.
- **Drawing waits for `gui_win_show`:** a window isn't drawn at all until `gui_win_show` says
  it's complete. That includes full redraws, so a half-filled window never flashes up. Fill
  its gadgets first, then show it once.
- **Menu bar:** set `gui_menubar` = 1 to show a Windows 95-style bar across the top
  (`GUI_MENU_H` = 11 rows); windows are then kept below it, both when opened and when dragged.
  - Build the menus with `gui_menu_clear` and `gui_menu_add`: `gp_gid` = id, `gp_win` = parent
    (0 for a title on the bar), `gp_text` = label, and `"-"` for a separator line.
  - Click a title for its drop-down. The row under the pointer is lit, and clicking it gives
    `GE_MENU` with `ge_val` = the id. Cursor up/down and RETURN also work; ESC or a click
    elsewhere closes it.
  - With `GUI_WINMENU` = 1 there's also a built-in **Window** menu at the end, listing the open
    windows front first. Picking one brings it to the front; the program never sees that pick.
  - Titles go across in the order they were added, then Window. Set `gui_menu_late` to an id
    and the titles with ids from it to it + 15 go right of Window instead (0, the default:
    none do).
- **Toast:** `gui_toast` (`txt_ptr` = text, A = seconds, X = a notification slot or `$ff`)
  shows a short line in a yellow box at the bottom right of the screen, over everything. It
  takes no keys and doesn't change which window is in front. It goes after the given seconds
  or when clicked; with a slot, the click gives `GE_NOTIFY` for that slot, as if the icon were
  clicked. A new toast replaces the old one.
- **Buttons that need text:** a button with `GGF_NEEDTEXT` and `gg_val` = a text box's id
  (MegaNet: `S.SET_VALUE` on the button) is greyed while that box is empty, and comes back
  as soon as something is typed, with no round trip to the server.
- **Bold labels:** a label with `GGF_BOLD` (64) is drawn twice, one pixel apart, like window
  titles (Message Boards' "Admin Tools" heading). A `GK_GROUP` 2 pixels high is an etched
  separator line.
- **Minimize:** a window with `GWF_MIN` (8) has a minimize box left of its close box.
  - Clicking it shrinks the window to its title bar (156 wide) in a row along the bottom of
    the screen, at y `GUI_MIN_Y` (168), one row above the toast. There are 4 places
    across (`GUI_MIN_COLS`, `.weak`); when a row is full they go on the row above.
  - The bar has a restore box and the close X. Minimized windows stay behind every other
    window (clicking one doesn't bring it forward), so the next window gets the front.
    Their gadgets aren't drawn and take no clicks or keys, but they still take updates.
  - Restore (the box, or the window's name in the Window menu) puts it back where it was,
    in front. A program opening the window again (`gui_win_open`) restores it too while
    `gui_open_restore` is 1 (the default). With 0 it stays minimized and only the place it
    restores to changes. MegaNet sets it to 1 for half a second after the server answers a
    click, so a window the user asked for comes back and a refresh doesn't pop one up.
  - It's all in the GUI: the program isn't told.
- **Desktop icons:** `gui_desk_icon` (A = slot 0-11; `gui_dk_l1` / `gui_dk_l2` = the label's
  two lines, `gui_dk_px` = the picture) puts an icon on the desktop, Windows 95 style.
  - The picture is 32 x 16 bytes (it looks square), colours 0-15, `$ff` see-through. It's
    copied to attic (`GUI_DESK_MEM`, 512 bytes a slot).
  - The labels are up to 10 characters each, white and centred under the picture.
  - Icons go in columns of 4, under every window: slots 0-7 (`GUI_ICON_LEFT`) from the left
    edge, slots 8-11 down the right edge.
  - A click selects one (its label on navy). The same one again within half a second gives
    `GE_DESK` with `ge_val` = the slot. A click elsewhere on the desktop clears the selection.
  - Line 1 empty removes the icon; `gui_desk_clear` removes them all.
- **Text views** take `gui_set_value` too: the wrapped line to show at the top (0 = the
  first; past the end, the last page). A view that is shown and scrolled to the bottom
  follows appended lines down; this puts a page back at its start.
- **Grids** (`GK_GRID`, in `grid.asm`, included after `gui.asm`): a board of picture tiles
  for board games.
  - The gadget's text is 7 bytes, each value + 1: cols, rows, tile w, tile h, resource
    slot, mark colours 1 and 2. Its cells (at most 256, all 0 at first) live in attic
    (`GUI_GRID_MEM` + gadget slot * 256); `gui_grid_cells` sets some and redraws it.
  - A cell is a tile number (bits 0-5), plus a frame in mark colour 2 (bit 6) and/or 1
    (bit 7), drawn two pixels wide at the sides and one at the top and bottom.
  - Tiles are read from a resource slot (`GUI_RES_MEM` + slot * 64 KB: tile t at
    t * w * h, row by row, a palette index a pixel), filled by `gui_resource`. They're drawn
    a pixel at a time, so the grid can be anywhere; clipped to the screen.
  - A click on a cell gives `GE_SELECT` with `ge_val` = row * cols + col.
  - `gui_resource_packed` fills a slot from PackBits (ByteRun1) bytes instead.
- **The desktop as the program's:** `gui_desk_hook` draws it (instead of the plain colour);
  with `gui_desk_input` set, presses on it go to that routine instead of selecting icons
  (A = `GUI_DK_DOWN`, `_MOVE` while held, `_UP`, `_RIGHT` for a right click; `ev_x` /
  `ev_y`), and the icons aren't drawn. `gui_hide_all` hides every open window (not drawn or
  clicked, their gadgets still updated) until `gui_show_all`; windows opened in between show
  as usual. `gui_win_rects` then `gui_covered` (`d6_x` / `d6_y`) tell the program whether a
  window or the bar covers a point, for drawing on the desktop between full redraws. The
  client's Paint (`client-src/canvas.asm`) uses all of these.
- **Holding the screen:** a program that takes the whole screen for a while (the client's
  full-screen pictures) sets `gui_hold` to 1 and stops calling `gui_update`. Changes keep
  arriving and are kept, but nothing is drawn (the menu-bar icons wait too). Afterwards:
  `gui_hold` 0, `gui_palette` (entries 0-15 back), and `gui_redraw_later`.
- **Broadcast:** `gui_banner` (`txt_ptr` = text, up to 79 characters; A = seconds) puts a
  line across the whole bottom row, yellow on red, over everything. It takes no keys and
  goes after the given seconds or when clicked. A toast moves up a row while it's there.
- **Progress bars** (`GK_PROGRESS`): sunken white, filled navy from the left for `gg_val`
  percent (0-100, set with `gui_set_value`).
- **Busy:** `gui_busy` with A = 1 turns the pointer into an hourglass, and `gui_update` then
  ignores clicks and keys; the pointer still moves. A = 0 brings back the arrow. Use it while
  waiting for something such as a server's answer.
- **Notification icons:** `gui_notify` (A = slot 0-7, X = icon) puts a small button at the
  right end of the menu bar. They are packed from the right: the shown icon with the lowest
  slot is rightmost, and empty slots leave no gap. Icon 1 is an alert that flashes red twice
  a second, icon 2 an envelope, icon 3 a Wi-Fi fan (connected), icon 4 the fan greyed with a
  red X (not connected), icon 5 a person (a black pawn), icon 6 a speech bubble, icons
  7-9 a green / yellow / dark grey dot, icon 10 a newspaper, icon 11 two beamed music notes
  and icon 12 the notes greyed (paused), and 0 removes it. There are 8 slots by default
  (`GUI_NSLOTS`, a `.weak` a program can raise: MegaNet has 9), 24 pixels apart. Redrawing
  them clears the bar only as far left as the icons reach (now or last time), so a long menu
  bar's last title isn't wiped under empty slots. A click gives `GE_NOTIFY` with `ge_val` =
  the slot.
- **Scroll bars:** every list and text view has a Windows 95 scroll bar on its right, 11 pixels
  wide.
  - The arrows scroll a row and the track a page. The thumb shows how much is visible
    (dragging it isn't done yet), and the arrows are grey when everything fits.
  - A text view that's scrolled to the bottom stays there as lines arrive. One filled before
    its window is shown opens at the top.
- **Dragging windows:** press on a title bar and move. Four yellow corner brackets, hardware
  sprites `GUI_FRAME_SPR` to `+3` (default 2-5), follow the pointer and show where the window
  will land. They cost no drawing at all. On release the brackets go and the window is drawn
  once at its new place, kept on the screen and below the menu bar. The pointer uses sprites
  `GUI_PTR_SPR` and `+1` (0-1), so a program has sprites 6 and 7 free.
- **Desktop:** `gui_desk_hook` = a routine that draws the backdrop, or 0 for a plain `GUI_DESK` fill.
- **Typing:** the focused text box takes printable keys, DEL, cursor left/right and HOME. TAB moves to
  the window's next text box. Clicking puts the cursor where you clicked.
- **Tests:**
  - Mouse events: write `type, x lo, x hi, y` quads to `gui_dbg_ev` and the count to `gui_dbg_evn`
    (`EV_DOWN` = 2, `EV_UP` = 3).
  - Keys: write them to `keyboard.asm`'s `dbg_keys` / `dbg_klen`. Set `dbg_klen` to 0 before
    rewriting `dbg_keys` and `dbg_kpos`, or the old keys play again.

## Look

The shapes and colours follow Windows 95:
- grey faces and two-layer bevels (white/light grey top-left, black/dark grey bottom-right);
- sunken white text boxes;
- a navy title bar with bold white text (grey when the window isn't in front);
- an extra black border on the default button;
- an etched look for disabled buttons.

The 640x200 pixel is twice as tall as it is wide, so a one-pixel horizontal line is as thick as a
two-pixel vertical one. The pointer is a black outline sprite over a white fill sprite.

## Not yet

These are listed in the project's `TODO.md`:
- dragging a scroll bar's thumb, and holding an arrow to repeat;
- (check boxes, radio buttons and progress bars are done);
- a toolbar of small icon buttons under the menu bar;
- maximize and resize (with gadgets anchored to the edges);
- a dragging outline, focus rectangles and a proportional font.
