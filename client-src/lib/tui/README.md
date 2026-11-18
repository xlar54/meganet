MEGA65 TUI library
==================

A DOS-style text user interface for the MEGA65: an 80x25 screen where every cell has its own
foreground and background colour, a mouse pointer, menus, dialogs and a help viewer. Everything is
keyboard and mouse driven. It knows nothing about the application using it.

| File | Gives |
|---|---|
| `tui_zp.asm` | Base-page variables |
| `tui_screen.asm` | Video mode, cell output, boxes, shadows, scroll bars, saving and restoring the screen |
| `tui_font.asm` | The CP437 font, for `TUI_CHARSET = 0` (the default) |
| `tui_font_mixed.asm`, `tui_petscii.asm` | For `TUI_CHARSET = 1`: ASCII and lines in the same style, PETSCII graphics from ROM, and `tui_pet_glyph` to show PETSCII bytes |
| `tui_charmap.asm` | Pick any of 256 characters from a grid |
| `tui_event.asm` | One event stream for keyboard and mouse, the pointer, the text cursor |
| `tui_menu.asm` | Menu bar and drop-down menus |
| `tui_dialog.asm` | Dialogs from a table: labels, text fields, check boxes, radio buttons, buttons, lists, frames; message boxes |
| `tui_dialog.inc` | The dialog table format on its own: the constants and the `DLG` macros. `tui_dialog.asm` includes it; code that only builds tables for a `tui_dialog` elsewhere includes just this |
| `tui_help.asm` | Help viewer: scrolling topics with links, from any chip-RAM bank |
| `tui_help_defs.asm` | The `HLINK` macro, to assemble help text as a file of its own |
| `tui_file.asm` | File dialog for Open and Save As: a list with file types, drives 8-11, subdirectories (`CBM` and `DIR`) and `..`. Needs `lib/kstream.asm` |

Each file documents its routines at the top.

Using it
--------

The library needs `lib/system.asm`, `lib/dma.asm`, `lib/mouse.asm` and `lib/hwsprite.asm`.

```
        .include "platform.asm"
        .include "lib/zp.asm"
        .include "lib/tui/tui_zp.asm"       ; your own base page continues from TUI_ZP_END
        ...
        #TAKEOVER
        jsr irq_install
        cli
        jsr tui_init
        jsr tui_event_init

        lda #$1F                        ; white on blue
        jsr tui_setattr
        ldx #10                         ; row
        ldy #30                         ; column
        jsr tui_goto
        lda #<hello
        ldx #>hello
        jsr tui_puts
loop:
        jsr tui_wait_event              ; A = EV_KEY, EV_DOWN, EV_UP, EV_DRAG, EV_RDOWN, EV_REPEAT
        ...
        jmp loop
        ...
        .include "lib/system.asm"
        .include "lib/dma.asm"
        .include "lib/mouse.asm"
        .include "lib/hwsprite.asm"
        .include "lib/tui/tui_screen.asm"
        .include "lib/tui/tui_event.asm"
        .include "lib/tui/tui_menu.asm"     ; these three only if you use them
        .include "lib/tui/tui_dialog.asm"
        .include "lib/tui/tui_help.asm"
        .include "lib/tui/tui_file.asm"     ; after tui_dialog; needs lib/kstream.asm
        .include "lib/tui/tui_font.asm"
```

A dialog
--------

```
my_dlg:
        #DLG 9, 40, my_title, 0         ; height, width, title, hook
        #DLG_LABEL 2, 2, my_prompt
        #DLG_TEXT 2, 10, 26, my_buffer, 26
        #DLG_CHECK 4, 2, my_option_text, my_option
        #DLG_HLINE 6
        #DLG_BUTTON 7, DLG_AUTO, ok_text, ID_OK, 1      ; 1 = RETURN presses this one
        #DLG_BUTTON 7, DLG_AUTO, cancel_text, 0         ; DLG_AUTO = spaced and centred
        #DLG_END

        lda #<my_dlg
        ldx #>my_dlg
        jsr tui_dialog                  ; A = the id of the button pressed, 0 = cancelled
```

Buttons are solid blocks: blue, or red for a cancelling button (ID 0), with white text on the
focused or default one and grey on the others. `tui_dc_btn`, `tui_dc_btnfoc` and `tui_dc_btncan`
hold the colours. Each has a shadow, so leave the row below a button free, inside the frame.

The file dialog
---------------

```
        ; at boot, first thing, before #TAKEOVER:
        jsr kst_capture
        sei                             ; if you use kstream before #TAKEOVER too
        ...
        ; the name to start with: "*" lists everything
        lda #'*'
        sta tfd_name
        lda #0
        sta tfd_name+1
        lda #TFD_OPEN                   ; or TFD_SAVE
        jsr tui_file_dialog
        cmp #ID_OK
        bne cancelled
        ; tfd_name is the chosen file, in the current directory of drive tfd_unit
        ldy #0
        lda #<tfd_name
        ldx #>tfd_name
        jsr kst_name_put                ; into kst_name; Y = its length
        ...
```

Subdirectories are handled in the dialog. The caller only needs care with `tfd_moved`: see the top of
`tui_file.asm`.

Memory
------

| What | Where | Change it with |
|---|---|---|
| Glyphs | `$40000-$5FFFF`, 128 KB | Fixed |
| Screen RAM | `$12000`, 4000 bytes | `TUI_SCREEN` |
| Colour RAM | `$FF80800`, 4000 bytes: above the 2 KB window the KERNAL uses | `TUI_COLOUR_OFS` |
| Saved screens | Attic `$87F0000`, 8 KB per level, 8 levels | `TUI_LAYER_BASE`, `TUI_LAYERS` |
| File list and path (`tui_file.asm`) | `$13000`, 3.5 KB | `TFD_DIR_BASE`, `TFD_DIR_MAX`, `TFD_PATH_BASE` |
| Help text (`tui_help.asm`) | Wherever you put it: any chip-RAM bank | `tui_help_bank` |
| Sprites | 0 and 1: the pointer. 2: the text cursor | `TUI_SPR_*` in `tui_event.asm` |

The modules keep their buffers in a 64tass section called `bss`, so the program must have a
`.dsection bss` somewhere. At the end of the program is simplest: they're then in the program file,
zero-filled. MSEdit puts the section in uninitialised RAM at `$C401`, inside a `.virtual`, and
clears it at boot.

Menus and dialogs nest, each taking one saved-screen level. `tui_push` and `tui_pop` do the same for
your own overlays.

Character sets
--------------

Define `TUI_CHARSET` before including the TUI, and include the matching font.

| | `0` (default) | `1` |
|---|---|---|
| Font | All of CP437 (`tui_font.asm`, 2 KB) | ASCII and lines (`tui_font_mixed.asm`, 904 bytes), plus PETSCII graphics from the ROM font |
| Good for | PC text, an ANSI terminal | MEGA65 text, PETSCII |
| Extra include | | `tui_petscii.asm` |

Either way, ASCII 32-126 are at their usual codes and `TG_` names the widgets' glyphs, so strings and
widgets work the same.

Attributes
----------

An attribute is `(background << 4) | foreground`, as in VGA text mode: background 0-7, foreground
0-15, with `TUI_BLACK` to `TUI_WHITE` for the EGA colours.

How the colours work
--------------------

The VIC-IV's text modes have one background colour for the whole screen, so the TUI uses Full
Colour Mode. `tui_init` renders the font 8 times, once for each background, with its foreground
pixels set to `$FF`. A cell's character number chooses the glyph and background, and because the
VIC-IV draws pixel value `$FF` in the colour from colour RAM, the foreground costs nothing extra.
Writing a cell is two bytes of screen RAM and two of colour RAM.

Testing
-------

`tui_dbg_q` takes scripted keys and mouse events through the same code paths as real ones: see the
top of `tui_event.asm`.
