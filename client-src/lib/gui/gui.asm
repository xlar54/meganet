;=======================================================================================
; lib/gui/gui.asm - a Windows 95-style windowing toolkit for the 640x200, 256-colour
; Full Colour screen (lib/fcm640.asm + lib/draw640.asm). Windows with title bars, close
; boxes, dragging and z-order; buttons, labels, text boxes, password boxes; a mouse
; pointer on two hardware sprites; keyboard focus and editing. See lib/gui/README.md.
;
; Nothing here knows about any particular program: the program creates windows and
; gadgets, calls gui_update once a frame, and acts on the events it returns.
;
;   gui_init        palette entries 0-15 (GC_*), pointer sprites, mouse, empty tables
;   gui_palette     palette entries 0-15 again (after something else used them)
;   gui_desk_input  (word) a routine for presses on the desktop instead of its icons (the
;                   icons aren't drawn then): jumped to with A = GUI_DK_*, ev_x / ev_y;
;                   it returns as gui_update does (carry set = an event in ge_*)
;   gui_hide_all    every open window hidden (not drawn or clicked) until gui_show_all;
;                   windows opened in between show as usual
;   gui_win_rects / gui_covered   the shown windows' rectangles, once; then for a point
;                   (d6_x, d6_y): carry set if a window or the menu bar covers it
;   gui_hold        1 while the program has the whole screen: nothing drawn at once (the
;                   program doesn't call gui_update then); gui_redraw_later when it's back
;   gui_update      once a frame: mouse, keys -> windows and gadgets. Carry set = an
;                   event for the program: ge_type (GE_*), ge_win, ge_gid, ge_key
;   gui_redraw      the desktop (gui_desk_hook, or GC_DESK) and every window
;   gui_redraw_later  the same, once, at the start of the next gui_update (gui_win_show,
;                   gui_win_close and changes behind the front window use this)
;   gui_win_open    gp_win, gp_x/y/w/h (outer size: the client area is GUI_FRAME_W /
;                   GUI_FRAME_H smaller), gp_flags (GWF_*), gp_text = title. Moved up or
;                   left if it would run off the screen. Reopening an open id empties it.
;                   Not drawn until gui_win_show says it's complete. Carry set: no slot
;   gui_win_show    A = window id: draw it (all windows if it isn't the front one)
;   gui_win_close   A = window id: remove it and its gadgets, redraw
;   gui_close_all   every window gone (doesn't draw)
;   gui_gad_add     gp_win, gp_gid, gp_kind (GK_*), gp_x/y/w/h (inside the window's
;                   client area), gp_flags (GGF_*), gp_max (text length, 0 = 63),
;                   gp_text. Carry set: no such window / no free slot. X = slot
;   gui_set_text    gp_win, gp_gid, gp_text: new text, redrawn
;   gui_get_text    A = window, X = gadget: A/X = its text (zero-terminated), Y = length.
;                   Carry set: no such gadget
;   gui_toast       txt_ptr = text, A = seconds, X = slot a click reports ($ff none): a
;                   short message at the bottom right for a while (see below)
;   gui_set_flags   A = window, X = gadget, gp_flags = its flags (GGF_DISABLED: greyed)
;   gui_focus       A = window, X = gadget: keyboard focus to that text box
;   gui_find_win    A = window id -> X = its slot (gw_* tables); carry set if not open
;   gui_find_gad    A = window id, X = gadget id -> X = its slot (gg_* tables); carry set
;                   if none
;   gui_gad_redraw  A = window, X = gadget: draw it again
;   gui_set_value   A = window, X = gadget, gp_x = value: check box / radio state, or a
;                   list's or drop-down's selected row; redrawn
;   gui_edit_count / gui_edit_line   a text area's lines: A = window, X = gadget (and
;                   Y = line): A = how many / txt_ptr = that line
;   gui_busy        A = 1: the pointer becomes an hourglass and clicks and keys are ignored
;                   (the pointer still moves); A = 0: back to normal
;   gui_notify      A = slot 0-6, X = icon (0 none, 1 alert (flashes), 2 envelope, ...): an
;                   icon at the right end of the menu bar; a click on it gives GE_NOTIFY
;   gui_menu_clear / gui_menu_add   the menu bar (gui_menubar = 1 shows it): gp_gid = id,
;                   gp_win = parent (0 = a title), gp_text = label ("-" = a line).
;                   Titles go across in the order added, then the Window menu; set
;                   gui_menu_late to an id and titles with ids from it to it + 15 go
;                   right of Window
;   gui_list_total  gp_win, gp_gid, gp_w = the list's row count now (128 at most)
;   gui_list_row    gp_win, gp_gid, gp_x = row, txt_ptr = its text (63 characters kept)
;   gui_view_append A = window, X = gadget, txt_ptr = a line: word-wrapped onto the text
;                   view (its last 64 lines kept) and redrawn
;   gui_text        txt_ptr = string, gt_x (word) / gt_y, gt_fg, gt_bg ($ff = none),
;                   gt_n (most characters, $ff = all), gt_pw (1 = show '*'): 8x8 text at
;                   any pixel, inside the draw640 clip rectangle (whole characters only)
;   gui_swap        A = 0-255 -> nibble-swapped, for $D100/$D200/$D300
;   #GUI_WIN / #GUI_GAD   the two calls above with constant arguments
;
; Events (ge_type): GE_CLICK (button released over itself, or RETURN = the window's
; GGF_DEFAULT button), GE_CLOSE (close box), GE_KEY (a key no gadget used: ge_key, ge_gid =
; focused gadget or 0). Window ids and gadget ids are the program's (any byte).
;
; Needs fcm640, draw640 (+ font8), dma, mouse, hwsprite, keyboard, and from lib/zp.asm
; txt_ptr, tmp6, ptr1 (d6_p). Define MOUSE_MAX_X = 639 before including lib/mouse.asm.
; Tests inject mouse events through gui_dbg_ev / gui_dbg_evn (type, x lo, x hi, y) and
; keys through keyboard.asm's dbg_keys.
;
; The 640x200 pixel is twice as tall as wide, so horizontal lines are one pixel and
; vertical edges two where Windows 95 uses two of each.
;=======================================================================================

        .weak
GUI_MAXWIN      = 8
GUI_MAXGAD      = 48
GUI_TEXTMAX     = 64                    ; bytes per gadget text, with the 0
GUI_TITLEMAX    = 40
GUI_PTR_SPR     = 0                     ; pointer: this sprite (outline) and the next (fill)
GUI_FRAME_SPR   = 2                     ; dragging: these four (corner brackets)
GUI_DESK        = GC_DESK               ; desktop colour when gui_desk_hook is 0
GUI_MAXBIG      = 8                     ; lists, views, text areas, drop-downs at once
GUI_BIG_MEM     = $8200000              ; their rows: GUI_MAXBIG x 8 KB (attic)
GUI_MAXICON     = 12                    ; desktop icons (columns of GUI_ICON_ROWS): slots
GUI_ICON_LEFT   = 8                     ; 0-7 from the left edge, 8-11 from the right
GUI_DESK_MEM    = $8240000              ; their pictures, 512 bytes each (64 KB aligned)
        .endweak
GUI_ICON_W      = 32                    ; a desktop icon's picture (pixels are twice as tall
GUI_ICON_H      = 16                    ; as wide: it looks square), a label under it
GUI_ICON_LBL    = 11                    ; label line: 10 characters + 0
GUI_ICON_CELLW  = 80                    ; the column's width; icon centred, label too
GUI_ICON_CELLH  = 40
GUI_ICON_ROWS   = 4
GUI_ICON_TOP    = 11 + 4                ; (below the menu bar)
GUI_MAXMENU     = 48                    ; menu entries (titles + items)
GUI_MENULEN     = 24                    ; bytes a label, with the 0
GUI_MAXTITLE    = 12                    ; titles on the bar
GUI_MAXDROP     = 16                    ; items in one drop-down
GUI_MENU_H      = 11                    ; the bar's rows (windows stay below it)
GUI_WINMENU     = 1                     ; 1 = the built-in Window menu
GUI_VIEW_LINES  = 128                   ; a text view keeps 128 lines of up to 63 characters
GUI_SB_W        = 11                    ; lists and text views: the scroll bar's width
GUI_EDIT_LINES  = 32                    ; a text area's lines
GUI_LIST_ROWS   = 128                   ; a list 128 rows of up to 63 (64 bytes each)

; colours: palette entries 0-15 (tools/build_assets.py GUI_COLOURS must match)
GC_BLACK        = 0
GC_WHITE        = 1
GC_FACE         = 2                     ; 3D face, C0C0C0
GC_SHADOW       = 3                     ; 808080
GC_LIGHT        = 4                     ; DFDFDF
GC_TITLE        = 5                     ; active title bar, navy
GC_DESK         = 6                     ; desktop teal
GC_TITLE2       = 7                     ; light blue
GC_TIP          = 8                     ; tooltip yellow
GC_RED          = 9
GC_GREEN        = 10
GC_DKGREY       = 11
GC_BLUE         = 12
GC_NIGHT        = 13                    ; very dark blue
GC_YELLOW       = 14
GC_CYAN         = 15

; gadget kinds (the same numbers as the MegaNet protocol)
GK_LABEL        = 1
GK_BUTTON       = 2
GK_TEXT         = 3
GK_PASSWORD     = 4
GK_LIST         = 5
GK_CHECK        = 6
GK_RADIO        = 7
GK_VIEW         = 8
GK_PROGRESS     = 9
GK_IMAGE        = 10
GK_GROUP        = 11
GK_DROP         = 12                    ; drop-down list (combo box)
GK_EDIT         = 13                    ; editable text area
GK_GRID         = 14                    ; a board of picture tiles (grid.asm)

GWF_CLOSE       = 1                     ; window flags
GWF_MODAL       = 2
GWF_MOVABLE     = 4
GWF_MIN         = 8                     ; a minimize box: the window shrinks to a title bar
                                        ; at the bottom of the screen (restore box, close X)
GGF_DEFAULT     = 1                     ; gadget flags
GGF_DISABLED    = 2
GGF_RAWKEYS     = 4
GGF_MULTILINE   = 8
GGF_CENTRE      = 16                    ; label text centred
GGF_NEEDTEXT    = 32                    ; button greyed while text box gg_val (an id) is empty
GGF_BOLD        = 64                    ; label text bold (drawn twice, one pixel apart)

GE_NONE         = 0
GE_CLICK        = 1
GE_CLOSE        = 2
GE_KEY          = 3
GE_SELECT       = 4                     ; a list row clicked: ge_val (bit 15 = double click)
GE_MENU         = 5                     ; a menu item picked: ge_val = its id
GE_NOTIFY       = 6                     ; a notification icon clicked: ge_val = its slot
GE_DESK         = 7                     ; a desktop icon double-clicked: ge_val = its slot

EV_NONE         = 0                     ; gui_poll's raw events
EV_KEY          = 1
EV_DOWN         = 2
EV_UP           = 3
EV_MOVE         = 4
EV_RDOWN        = 5
GUI_DK_DOWN     = 1                     ; gui_desk_input's A: a press, a move while held,
GUI_DK_MOVE     = 2                     ; the release, a right click (ev_x / ev_y: where)
GUI_DK_UP       = 3
GUI_DK_RIGHT    = 4
GUI_DBG_MAX     = 16

GUI_TITLE_H     = 11                    ; title bar rows
GUI_CLIENT_X    = 4                     ; client area from the window's top left
GUI_CLIENT_Y    = 3 + GUI_TITLE_H + 1
GUI_MIN_W       = 156                   ; a minimized window: just its title bar, in a row
GUI_MIN_H       = 3 + GUI_TITLE_H + 3   ; along the bottom, one row above the toast
GUI_MIN_Y       = 186 - GUI_MIN_H - 1
GUI_MIN_STEP    = 158                   ; 4 places across, then the row above
        .weak
GUI_MIN_COLS    = 4                     ; (a test build can make the rows shorter)
        .endweak
GUI_FRAME_W     = 2 * GUI_CLIENT_X      ; outer size = client area + these
GUI_FRAME_H     = GUI_CLIENT_Y + 3

GUI_WIN .macro id, x, y, w, h, flags, title
        lda #\id
        sta gp_win
        lda #<(\x)
        sta gp_x
        lda #>(\x)
        sta gp_x+1
        lda #\y
        sta gp_y
        lda #<(\w)
        sta gp_w
        lda #>(\w)
        sta gp_w+1
        lda #\h
        sta gp_h
        lda #\flags
        sta gp_flags
        lda #<\title
        sta gp_text
        lda #>\title
        sta gp_text+1
        jsr gui_win_open
.endmacro

GUI_GAD .macro win, gid, kind, x, y, w, h, flags, max, text
        lda #\win
        sta gp_win
        lda #\gid
        sta gp_gid
        lda #\kind
        sta gp_kind
        lda #<(\x)
        sta gp_x
        lda #>(\x)
        sta gp_x+1
        lda #\y
        sta gp_y
        lda #<(\w)
        sta gp_w
        lda #>(\w)
        sta gp_w+1
        lda #\h
        sta gp_h
        lda #\flags
        sta gp_flags
        lda #\max
        sta gp_max
        lda #<\text
        sta gp_text
        lda #>\text
        sta gp_text+1
        jsr gui_gad_add
.endmacro

; ---- arguments and results ----
gp_win:         .byte 0
gp_gid:         .byte 0
gp_kind:        .byte 0
gp_x:           .word 0
gp_y:           .byte 0
gp_w:           .word 0
gp_h:           .byte 0
gp_flags:       .byte 0
gp_max:         .byte 0
gp_text:        .word 0
ge_type:        .byte 0
ge_win:         .byte 0
ge_gid:         .byte 0
ge_key:         .byte 0
ge_val:         .word 0
gui_desk_hook:  .word 0                 ; draws the desktop (0: plain GUI_DESK)
gt_x:           .word 0
gt_y:           .byte 0
gt_fg:          .byte 0
gt_bg:          .byte $ff
gt_n:           .byte $ff
gt_pw:          .byte 0

; ---- windows: one entry per slot; gw_z lists the slots back to front ----
gw_used:        .fill GUI_MAXWIN
gw_id:          .fill GUI_MAXWIN
gw_xl:          .fill GUI_MAXWIN
gw_xh:          .fill GUI_MAXWIN
gw_y:           .fill GUI_MAXWIN
gw_wl:          .fill GUI_MAXWIN
gw_wh:          .fill GUI_MAXWIN
gw_h:           .fill GUI_MAXWIN
gw_flags:       .fill GUI_MAXWIN
gw_focus:       .fill GUI_MAXWIN        ; gadget slot with the keyboard, $ff none
gw_z:           .fill GUI_MAXWIN
gw_shown:       .fill GUI_MAXWIN        ; gui_win_show'n: complete, so it's drawn
gw_min:         .fill GUI_MAXWIN        ; 1 = minimized (gw_s*: its place to restore)
gw_hid:         .fill GUI_MAXWIN        ; 1 = hidden by gui_hide_all (out of gw_z)
l_hz:           .fill GUI_MAXWIN        ; gw_z as gui_hide_all found it
l_hn:           .byte 0
gui_desk_input: .word 0                 ; presses on the desktop go here instead (0: icons)
l_dk_held:      .byte 0                 ; a press on it is held
gw_sxl:         .fill GUI_MAXWIN
gw_sxh:         .fill GUI_MAXWIN
gw_sy:          .fill GUI_MAXWIN
gw_swl:         .fill GUI_MAXWIN
gw_swh:         .fill GUI_MAXWIN
gw_sh:          .fill GUI_MAXWIN
gw_n:           .byte 0

; ---- lists and text views keep their rows in bank 1: one 8 KB block each ----
gg_big:         .fill GUI_MAXGAD        ; the gadget's block, $ff none
l_gb_bank:      .byte 0
gb_used:        .fill GUI_MAXBIG
gb_n:           .fill GUI_MAXBIG        ; rows / lines held
gb_head:        .fill GUI_MAXBIG        ; text view: the ring's next line
gb_top:         .fill GUI_MAXBIG        ; first row / line shown (the scroll position)
gb_sel:         .fill GUI_MAXBIG        ; list: selected row, $ff none
gb_clk:         .fill GUI_MAXBIG        ; list: frame_count at the last click
l_gb_sh:        .byte 0
l_gb_t:         .byte 0
l_gb_line:      .fill 66
l_gb_w:         .byte 0
l_gb_p:         .byte 0
l_gb_e:         .byte 0
l_gb_k:         .byte 0
l_gb_vl:        .byte 0

; ---- gadgets ----
gg_win:         .fill GUI_MAXGAD        ; window slot, $ff = free
gg_id:          .fill GUI_MAXGAD
gg_kind:        .fill GUI_MAXGAD
gg_xl:          .fill GUI_MAXGAD
gg_xh:          .fill GUI_MAXGAD
gg_y:           .fill GUI_MAXGAD
gg_wl:          .fill GUI_MAXGAD
gg_wh:          .fill GUI_MAXGAD
gg_h:           .fill GUI_MAXGAD
gg_flags:       .fill GUI_MAXGAD
gg_max:         .fill GUI_MAXGAD
gg_len:         .fill GUI_MAXGAD
gg_cur:         .fill GUI_MAXGAD
gg_scr:         .fill GUI_MAXGAD
gg_val:         .fill GUI_MAXGAD
gg_dirty:       .fill GUI_MAXGAD        ; to draw again at the next gui_update
l_gg_any:       .byte 0

l_gtb_lo:       .byte <(l_gui_tbuf + range(GUI_MAXGAD) * GUI_TEXTMAX)
l_gtb_hi:       .byte >(l_gui_tbuf + range(GUI_MAXGAD) * GUI_TEXTMAX)
l_gwt_lo:       .byte <(l_gui_wbuf + range(GUI_MAXWIN) * GUI_TITLEMAX)
l_gwt_hi:       .byte >(l_gui_wbuf + range(GUI_MAXWIN) * GUI_TITLEMAX)

; ---- the menu bar ----
gui_menubar:    .byte 0                 ; 1 = shown: windows stay below it
gui_hold:       .byte 0                 ; 1 = the program has the whole screen (a picture):
                                        ; the GUI draws nothing at once (gui_update isn't
                                        ; called then either); gui_redraw_later afterwards
gui_menu_late:  .byte 0                 ; titles with ids from this to this + 15 go right
                                        ; of the Window menu (0: none do)
l_mn_pass:      .byte 0
mn_n:           .byte 0
mn_id:          .fill GUI_MAXMENU
mn_par:         .fill GUI_MAXMENU
l_mnt_lo:       .byte <(l_gui_mbuf + range(GUI_MAXMENU) * GUI_MENULEN)
l_mnt_hi:       .byte >(l_gui_mbuf + range(GUI_MAXMENU) * GUI_MENULEN)
mt_n:           .byte 0                 ; titles laid out on the bar
mt_idx:         .fill GUI_MAXTITLE      ; their entry ($ff: the Window menu)
mt_x0l:         .fill GUI_MAXTITLE
mt_x0h:         .fill GUI_MAXTITLE
mt_x1l:         .fill GUI_MAXTITLE
mt_x1h:         .fill GUI_MAXTITLE
l_mn_open:      .byte $ff               ; the open title, $ff none
l_md_hov:       .byte $ff               ; the lit row
l_md_r:         .byte 0
md_n:           .byte 0
md_item:        .fill GUI_MAXDROP       ; entry, or $80 + window slot
md_w:           .byte 0
md_x0:          .word 0
md_x1:          .word 0
md_y1:          .byte 0

        .weak
GUI_TBUF        = 0                     ; nonzero: the gadget texts live there instead
        .endweak                        ; (GUI_MAXGAD * GUI_TEXTMAX bytes, bank 0)
        .section bss
l_gui_mbuf:     .fill GUI_MAXMENU * GUI_MENULEN
        .if GUI_TBUF == 0
l_gui_tbuf:     .fill GUI_MAXGAD * GUI_TEXTMAX
        .endif
l_gui_wbuf:     .fill GUI_MAXWIN * GUI_TITLEMAX
        .send
        .if GUI_TBUF != 0
l_gui_tbuf      = GUI_TBUF
        .endif

; ---- working state ----
gr_x0:          .word 0                 ; the rectangle being drawn / tested (same
gr_y0:          .word 0                 ; order as d6_x, d6_y, d6_x1, d6_y1)
gr_x1:          .word 0
gr_y1:          .word 0
l_gd_ws:        .byte 0                 ; window slot being drawn
l_gd_gs:        .byte 0                 ; gadget slot being drawn
l_gd_tl:        .byte 0
l_gd_br:        .byte 0
l_go_x:         .word 0                 ; client-area origin of l_gd_ws
l_go_y:         .byte 0
l_gc_split:     .byte 0
l_gc_row:       .byte 0
l_gc_bits:      .byte 0
l_gu_ws:        .byte 0
l_gu_press:     .byte $ff               ; button held down (gadget slot)
l_gu_drag:      .byte $ff               ; window being dragged (slot)
l_gu_offx:      .word 0
l_gu_offy:      .byte 0
l_gu_t:         .word 0
l_gu_t2:        .word 0
ev_type:        .byte 0
ev_x:           .word 0
ev_y:           .byte 0
ev_key:         .byte 0
l_ev_held:      .byte 0
l_ev_lx:        .word 0
l_ev_ly:        .byte 0
gui_dbg_ev:     .fill GUI_DBG_MAX * 4   ; injected events (tests): type, x lo, x hi, y
gui_dbg_evn:    .byte 0
gui_dbg_evp:    .byte 0

;=======================================================================================
; set-up
;=======================================================================================
gui_init:
        jsr gui_palette
        jmp l_gui_init2

; palette entries 0-15: the GUI's colours (again after a full-screen picture used them)
gui_palette:
        ldx #0
-       lda l_gui_pal_r,x
        jsr gui_swap
        sta $d100,x
        lda l_gui_pal_g,x
        jsr gui_swap
        sta $d200,x
        lda l_gui_pal_b,x
        jsr gui_swap
        sta $d300,x
        inx
        cpx #16
        bne -
        rts

l_gui_init2:
        jsr gui_close_all
        lda #0
        sta mn_n
        sta gui_hold
        sta gui_dbg_evn
        sta gui_dbg_evp
        sta l_ev_held
        lda #$ff
        sta l_gu_press
        sta l_gu_drag
        jsr hws_init
        ldx #GUI_PTR_SPR
        lda #<l_gui_arrow_o
        ldy #>l_gui_arrow_o
        jsr hws_shape
        ldx #GUI_PTR_SPR + 1
        lda #<l_gui_arrow_f
        ldy #>l_gui_arrow_f
        jsr hws_shape
        ldx #GUI_PTR_SPR
        lda #GC_BLACK
        jsr hws_colour
        ldx #GUI_PTR_SPR + 1
        lda #GC_WHITE
        jsr hws_colour
        jsr mouse_init
        ldx #0                          ; the drag brackets
-       phx
        lda l_dg_shape_lo,x
        ldy l_dg_shape_hi,x
        pha
        txa
        clc
        adc #GUI_FRAME_SPR
        tax
        pla
        jsr hws_shape
        lda #GC_YELLOW
        jsr hws_colour
        jsr hws_off
        plx
        inx
        cpx #4
        bne -
        ldx #GUI_PTR_SPR
        jsr hws_on
        ldx #GUI_PTR_SPR + 1
        jsr hws_on
        jmp l_gui_pointer

gui_swap:
        asl
        adc #$80
        rol
        asl
        adc #$80
        rol
        rts

; A = 1: busy, the hourglass pointer, input ignored; 0: the arrow again
gui_busy:
        cmp l_busy
        beq _same
        sta l_busy
        tay
        ldx #GUI_PTR_SPR
        lda l_ptr_o_lo,y
        pha
        lda l_ptr_o_hi,y
        tay
        pla
        jsr hws_shape
        ldy l_busy
        ldx #GUI_PTR_SPR + 1
        lda l_ptr_f_lo,y
        pha
        lda l_ptr_f_hi,y
        tay
        pla
        jsr hws_shape
_same:  rts
l_busy:         .byte 0
gui_open_restore: .byte 1               ; 1: gui_win_open of a minimized window restores it;
                                        ; 0: it stays minimized (the program sets it)
l_ptr_o_lo:     .byte <l_gui_arrow_o, <l_gui_glass_o
l_ptr_o_hi:     .byte >l_gui_arrow_o, >l_gui_glass_o
l_ptr_f_lo:     .byte <l_gui_arrow_f, <l_gui_glass_f
l_ptr_f_hi:     .byte >l_gui_arrow_f, >l_gui_glass_f

; the pointer where the mouse is (sprites are placed in 320-wide units)
l_gui_pointer:
        lda mouse_x+1
        lsr
        sta hws_x+1
        lda mouse_x
        ror
        sta hws_x
        lda mouse_y
        sta hws_y
        lda #0
        sta hws_y+1
        ldx #GUI_PTR_SPR
        jsr hws_place
        ldx #GUI_PTR_SPR + 1
        jmp hws_place

;=======================================================================================
; raw input -> ev_type (EV_*), ev_x / ev_y, ev_key (from renderer65's gui.asm)
;=======================================================================================
l_gui_poll:
        lda #EV_NONE
        sta ev_type
        lda gui_dbg_evp                 ; an injected event?
        cmp gui_dbg_evn
        bcs _real
        asl
        asl
        tax
        inc gui_dbg_evp
        lda gui_dbg_ev,x
        sta ev_type
        lda gui_dbg_ev+1,x
        sta ev_x
        sta mouse_x
        lda gui_dbg_ev+2,x
        sta ev_x+1
        sta mouse_x+1
        lda gui_dbg_ev+3,x
        sta ev_y
        sta mouse_y
        lda ev_type
        cmp #EV_KEY
        bne +
        jsr key_get
        sta ev_key
+       jmp l_gui_pointer
_real:
        jsr mouse_poll
        jsr l_gui_pointer
        lda mouse_x
        sta ev_x
        lda mouse_x+1
        sta ev_x+1
        lda mouse_y
        sta ev_y
        jsr key_get
        beq +
        sta ev_key
        lda #EV_KEY
        sta ev_type
        rts
+       lda mouse_left_click
        beq +
        lda #1
        sta l_ev_held
        lda #EV_DOWN
        sta ev_type
        bra _moved
+       lda mouse_left_release
        beq +
        lda #0
        sta l_ev_held
        lda #EV_UP
        sta ev_type
        bra _moved
+       lda mouse_right_click
        beq +
        lda #EV_RDOWN
        sta ev_type
        rts
+       lda l_ev_held
        beq _moved
        lda ev_x
        cmp l_ev_lx
        bne +
        lda ev_x+1
        cmp l_ev_lx+1
        bne +
        lda ev_y
        cmp l_ev_ly
        beq _moved
+       lda #EV_MOVE
        sta ev_type
_moved:
        lda ev_x
        sta l_ev_lx
        lda ev_x+1
        sta l_ev_lx+1
        lda ev_y
        sta l_ev_ly
        rts

;=======================================================================================
; drawing primitives on the rectangle gr_x0..gr_y1
;=======================================================================================
; copy gr_* to d6_x, d6_y, d6_x1, d6_y1
l_gd_cp:
        ldx #7
-       lda gr_x0,x
        sta d6_x,x
        dex
        bpl -
        rts

; fill gr in colour A
l_gd_fill:
        sta d6_col
        jsr l_gd_cp
        jmp d6_fill

; one-pixel edges of gr: A = top and left, X = bottom and right
l_gd_edges:
        sta l_gd_tl
        stx l_gd_br
        jsr l_gd_cp                     ; top: x0 .. x1 - 1, y0
        lda d6_y
        sta d6_y1
        lda d6_y+1
        sta d6_y1+1
        lda d6_x1
        bne +
        dec d6_x1+1
+       dec d6_x1
        lda l_gd_tl
        sta d6_col
        jsr d6_fill
        jsr l_gd_cp                     ; left: x0, y0 .. y1 - 1
        lda d6_x
        sta d6_x1
        lda d6_x+1
        sta d6_x1+1
        lda d6_y1
        bne +
        dec d6_y1+1
+       dec d6_y1
        jsr d6_fill
        jsr l_gd_cp                     ; bottom: x0 .. x1, y1
        lda d6_y1
        sta d6_y
        lda d6_y1+1
        sta d6_y+1
        lda l_gd_br
        sta d6_col
        jsr d6_fill
        jsr l_gd_cp                     ; right: x1, y0 .. y1
        lda d6_x1
        sta d6_x
        lda d6_x1+1
        sta d6_x+1
        jmp d6_fill

; gr one pixel smaller on every side
l_gd_shrink:
        inc gr_x0
        bne +
        inc gr_x0+1
+       inc gr_y0
        bne +
        inc gr_y0+1
+       lda gr_x1
        bne +
        dec gr_x1+1
+       dec gr_x1
        lda gr_y1
        bne +
        dec gr_y1+1
+       dec gr_y1
        rts

; two-layer bevels; gr ends up inside them
l_gd_bevel2:                            ; A/X outer, Y = inner top-left, l_gd_ib = inner
        sty l_gd_it                     ; bottom-right
        jsr l_gd_edges
        jsr l_gd_shrink
        lda l_gd_it
        ldx l_gd_ib
        jsr l_gd_edges
        jmp l_gd_shrink
l_gd_ib:        .byte 0
l_gd_it:        .byte 0
l_gd_raised:                            ; a button
        lda #GC_SHADOW
        sta l_gd_ib
        lda #GC_WHITE
        ldx #GC_BLACK
        ldy #GC_LIGHT
        jmp l_gd_bevel2
l_gd_frame:                             ; a window
        lda #GC_SHADOW
        sta l_gd_ib
        lda #GC_LIGHT
        ldx #GC_BLACK
        ldy #GC_WHITE
        jmp l_gd_bevel2
l_gd_sunken:                            ; a text box
        lda #GC_LIGHT
        sta l_gd_ib
        lda #GC_SHADOW
        ldx #GC_WHITE
        ldy #GC_BLACK
        jmp l_gd_bevel2
l_gd_pressed:                           ; a button held down
        lda #GC_FACE
        sta l_gd_ib
        lda #GC_BLACK
        ldx #GC_WHITE
        ldy #GC_SHADOW
        jmp l_gd_bevel2

; clip draw640 to gr
l_gd_clip:
        lda gr_x0
        sta d6_cx0
        lda gr_x0+1
        sta d6_cx0+1
        lda gr_x1
        sta d6_cx1
        lda gr_x1+1
        sta d6_cx1+1
        lda gr_y0
        sta d6_cy0
        lda gr_y0+1
        sta d6_cy0+1
        lda gr_y1
        sta d6_cy1
        lda gr_y1+1
        sta d6_cy1+1
        rts

; A = length of the string at txt_ptr
l_gd_strlen:
        ldy #0
-       lda (txt_ptr),y
        beq +
        iny
        bne -
+       tya
        rts

;=======================================================================================
; text at any pixel (whole characters inside the clip rectangle)
;=======================================================================================
gui_text:
        ldy #0
_c:     cpy gt_n
        beq _done
        lda (txt_ptr),y
        beq _done
        ldx gt_pw
        beq +
        lda #'*'
+       phy
        jsr l_gd_char
        ply
        iny
        bra _c
_done:  rts

; character A at (gt_x, gt_y); gt_x moves on 8
l_gd_char:
        sec
        sbc #32
        bcs +
        lda #0
+       cmp #96
        bcc +
        lda #0
+       sta tmp6
        lda #0
        sta tmp6+1
        asl tmp6
        rol tmp6+1
        asl tmp6
        rol tmp6+1
        asl tmp6
        rol tmp6+1
        clc
        lda tmp6
        adc #<D6_FONT
        sta tmp6
        lda tmp6+1
        adc #>D6_FONT
        sta tmp6+1
        ; whole character inside the clip columns?
        lda gt_x
        cmp d6_cx0
        lda gt_x+1
        sbc d6_cx0+1
        bcc _skip                       ; x < cx0
        clc
        lda gt_x
        adc #7
        sta l_gu_t
        lda gt_x+1
        adc #0
        sta l_gu_t+1
        lda d6_cx1
        cmp l_gu_t
        lda d6_cx1+1
        sbc l_gu_t+1
        bcc _skip                       ; cx1 < x + 7
        lda gt_x                        ; pixels before the next cell
        and #7
        sta l_gc_split
        lda #8
        sec
        sbc l_gc_split
        sta l_gc_split
        lda #0
        sta l_gc_row
_r:     clc
        lda gt_y
        adc l_gc_row
        sta d6_y
        lda #0
        sta d6_y+1
        lda d6_y
        cmp d6_cy0
        bcc _next
        lda d6_cy1
        cmp d6_y
        bcc _next
        lda gt_x
        sta d6_x
        lda gt_x+1
        sta d6_x+1
        jsr d6_addr
        ldy l_gc_row
        lda (tmp6),y
        sta l_gc_bits
        ldz #0
        ldx #8
_px:    asl l_gc_bits
        bcc _bg
        lda gt_fg
        bra _st
_bg:    lda gt_bg
        cmp #$ff
        beq _sk
_st:    sta [d6_p],z
_sk:    inz
        cpz l_gc_split
        bne +
        tza
        clc
        adc #56                         ; on into the next cell
        taz
+       dex
        bne _px
_next:  inc l_gc_row
        lda l_gc_row
        cmp #8
        bne _r
_skip:  clc
        lda gt_x
        adc #8
        sta gt_x
        bcc +
        inc gt_x+1
+       rts

;=======================================================================================
; geometry
;=======================================================================================
; gr = window X's outer rectangle
l_gw_rect:
        lda gw_xl,x
        sta gr_x0
        lda gw_xh,x
        sta gr_x0+1
        lda gw_y,x
        sta gr_y0
        lda #0
        sta gr_y0+1
        sta gr_y1+1
        clc
        lda gr_x0
        adc gw_wl,x
        sta gr_x1
        lda gr_x0+1
        adc gw_wh,x
        sta gr_x1+1
        lda gr_x1
        bne +
        dec gr_x1+1
+       dec gr_x1
        clc
        lda gr_y0
        adc gw_h,x
        sta gr_y1
        bcc +
        inc gr_y1+1
+       lda gr_y1
        bne +
        dec gr_y1+1
+       dec gr_y1
        rts

; l_go_x / l_go_y = client-area origin of window X
l_gw_origin:
        clc
        lda gw_xl,x
        adc #GUI_CLIENT_X
        sta l_go_x
        lda gw_xh,x
        adc #0
        sta l_go_x+1
        clc
        lda gw_y,x
        adc #GUI_CLIENT_Y
        sta l_go_y
        rts

; gr = gadget X's rectangle (on screen); l_gd_ws = its window. X kept
l_gg_rect:
        phx
        lda gg_win,x
        sta l_gd_ws
        tax
        jsr l_gw_origin
        plx
        clc
        lda l_go_x
        adc gg_xl,x
        sta gr_x0
        lda l_go_x+1
        adc gg_xh,x
        sta gr_x0+1
        clc
        lda l_go_y
        adc gg_y,x
        sta gr_y0
        lda #0
        adc #0
        sta gr_y0+1
        clc
        lda gr_x0
        adc gg_wl,x
        sta gr_x1
        lda gr_x0+1
        adc gg_wh,x
        sta gr_x1+1
        lda gr_x1
        bne +
        dec gr_x1+1
+       dec gr_x1
        clc
        lda gr_y0
        adc gg_h,x
        sta gr_y1
        lda gr_y0+1
        adc #0
        sta gr_y1+1
        lda gr_y1
        bne +
        dec gr_y1+1
+       dec gr_y1
        rts

; carry set if (ev_x, ev_y) is inside gr
l_pt_in:
        lda ev_x
        cmp gr_x0
        lda ev_x+1
        sbc gr_x0+1
        bcc _no
        lda gr_x1
        cmp ev_x
        lda gr_x1+1
        sbc ev_x+1
        bcc _no
        lda ev_y
        cmp gr_y0
        lda #0
        sbc gr_y0+1
        bcc _no
        lda gr_y1
        cmp ev_y
        lda gr_y1+1
        sbc #0
        bcc _no
        sec
        rts
_no:    clc
        rts

; the front window's slot in A (Z set if there is none: then A = $ff)
l_gw_front:
        ldy gw_n
        beq _none
        dey
        lda gw_z,y
        rts
_none:  lda #$ff
        rts

;=======================================================================================
; lookups
;=======================================================================================
; A = window id -> X = slot, carry clear; carry set if not open
gui_find_win:
l_gw_find:
        ldx #0
-       ldy gw_used,x
        beq +
        cmp gw_id,x
        beq _yes
+       inx
        cpx #GUI_MAXWIN
        bne -
        sec
        rts
_yes:   clc
        rts

; A = window id, X = gadget id -> X = gadget slot, carry clear; carry set if none
gui_find_gad:
l_gg_find:
        stx l_gu_t
        jsr l_gw_find
        bcs _no
        stx l_gu_t+1                    ; window slot
        ldx #0
-       lda gg_win,x
        cmp l_gu_t+1
        bne +
        lda gg_id,x
        cmp l_gu_t
        beq _yes
+       inx
        cpx #GUI_MAXGAD
        bne -
_no:    sec
        rts
_yes:   clc
        rts

; X = window slot: move it to the front of gw_z
l_gw_raise:
        stx l_gu_t
        ldy #0                          ; find it
-       lda gw_z,y
        cmp l_gu_t
        beq +
        iny
        cpy gw_n
        bne -
        rts
+       iny                             ; close the gap
_sh:    cpy gw_n
        beq _put
        lda gw_z,y
        dey
        sta gw_z,y
        iny
        iny
        bra _sh
_put:   ldy gw_n
        dey
        lda l_gu_t
        sta gw_z,y
        rts

;=======================================================================================
; windows
;=======================================================================================
gui_win_open:
        ; keep it on the screen: at most 640 x 200, moved up / left if it runs off
        lda gp_w+1
        cmp #>640
        bcc +
        bne _wbig
        lda gp_w
        cmp #<640 + 1
        bcc +
_wbig:  lda #<640
        sta gp_w
        lda #>640
        sta gp_w+1
+       clc                             ; x + w > 640: x = 640 - w
        lda gp_x
        adc gp_w
        sta l_gu_t
        lda gp_x+1
        adc gp_w+1
        sta l_gu_t+1
        lda #<640
        cmp l_gu_t
        lda #>640
        sbc l_gu_t+1
        bcs +
        sec
        lda #<640
        sbc gp_w
        sta gp_x
        lda #>640
        sbc gp_w+1
        sta gp_x+1
+       lda gp_h
        cmp #201
        bcc +
        lda #200
        sta gp_h
+       clc                             ; y + h > 200: y = 200 - h
        lda gp_y
        adc gp_h
        bcs _ymove
        cmp #201
        bcc +
_ymove: lda #200
        sec
        sbc gp_h
        sta gp_y
+       lda gui_menubar                 ; and below the menu bar
        beq +
        lda gp_y
        cmp #GUI_MENU_H
        bcs +
        lda #GUI_MENU_H
        sta gp_y
        clc
        adc gp_h
        bcs _hcut
        cmp #201
        bcc +
_hcut:  lda #200 - GUI_MENU_H
        sta gp_h
+       lda gp_win
        jsr l_gw_find
        bcs _new
        stx l_gd_ws
        lda #1                          ; (open already: it stays drawn until refilled)
        sta l_reopen
        jsr l_gg_free                   ; empty it
        ldx l_gd_ws
        jsr l_gw_raise
        ldx l_gd_ws
        bra _set
_new:   lda #0
        sta l_reopen
        ldx #0
-       lda gw_used,x
        beq +
        inx
        cpx #GUI_MAXWIN
        bne -
        sec
        rts
+       lda #0
        sta gw_hid,x
        lda #1
        sta gw_used,x
        ldy gw_n
        txa
        sta gw_z,y
        inc gw_n
_set:   lda gp_win
        sta gw_id,x
        lda l_reopen                    ; minimized, sent again without being asked for
        beq _geo                        ; (gui_open_restore = 0): it stays minimized, and
        lda gw_min,x                    ; the new place is where it restores to
        beq _geo
        lda gui_open_restore
        bne _geo
        lda gp_x
        sta gw_sxl,x
        lda gp_x+1
        sta gw_sxh,x
        lda gp_y
        sta gw_sy,x
        lda gp_w
        sta gw_swl,x
        lda gp_w+1
        sta gw_swh,x
        lda gp_h
        sta gw_sh,x
        jsr l_gw_lower                  ; (back behind the others)
        ldx l_mm_ws
        bra _flags
_geo:   lda #0
        sta gw_min,x
        lda gp_x
        sta gw_xl,x
        lda gp_x+1
        sta gw_xh,x
        lda gp_y
        sta gw_y,x
        lda gp_w
        sta gw_wl,x
        lda gp_w+1
        sta gw_wh,x
        lda gp_h
        sta gw_h,x
_flags: lda gp_flags
        sta gw_flags,x
        lda #$ff
        sta gw_focus,x
        lda l_reopen                    ; a new window isn't drawn until gui_win_show; one
        bne +                           ; opened again keeps showing (the next step of a
        sta gw_shown,x                  ; wizard appears in place, nothing behind it shows)
+
        lda l_gwt_lo,x                  ; the title
        sta tmp6
        lda l_gwt_hi,x
        sta tmp6+1
        lda gp_text
        sta txt_ptr
        lda gp_text+1
        sta txt_ptr+1
        ldy #0
-       lda (txt_ptr),y
        cpy #GUI_TITLEMAX - 1
        bcc +
        lda #0
+       sta (tmp6),y
        beq +
        iny
        bra -
+       clc
        rts

; free window slot l_gd_ws's gadgets
l_gg_free:
        ldx #0
-       lda gg_win,x
        cmp l_gd_ws
        bne +
        jsr l_gg_release
+       inx
        cpx #GUI_MAXGAD
        bne -
        rts

; gadget slot X free, with its list / view block. X kept
l_gg_release:
        lda #$ff
        sta gg_win,x
        ldy gg_big,x
        cpy #$ff
        beq +
        lda #0
        sta gb_used,y
        lda #$ff
        sta gg_big,x
+       rts

; (the whole screen: the window that was in front has to lose its title colour)
gui_win_show:
        jsr l_gw_find
        bcs _no
        lda #1                          ; complete: drawn from now on
        sta gw_shown,x
        jmp gui_redraw_later
_no:    rts

gui_win_close:
        jsr l_gw_find
        bcs _no
        stx l_gd_ws
        jsr l_gg_free
        ldx l_gd_ws
        lda gw_hid,x                    ; (hidden: it isn't in gw_z)
        bne _gone
        jsr l_gw_raise                  ; to the front, then off the end of gw_z
        dec gw_n
_gone:  ldx l_gd_ws
        lda #0
        sta gw_hid,x
        sta gw_used,x
        lda #$ff
        sta l_gu_press
        sta l_gu_drag
        jmp gui_redraw_later
_no:    rts

; every window and gadget gone (doesn't draw)
gui_close_all:
        ldx #0
        lda #$ff
-       sta gg_win,x
        sta gg_big,x
        inx
        cpx #GUI_MAXGAD
        bne -
        ldx #0
        lda #0
-       sta gw_used,x
        sta gw_hid,x
        inx
        cpx #GUI_MAXWIN
        bne -
        sta gw_n
        sta l_hn
        sta l_dk_held
        ldx #0
-       sta gb_used,x
        inx
        cpx #GUI_MAXBIG
        bne -
        lda #$ff
        sta l_mn_open
        sta l_dd_gs
        jsr l_drag_hide                 ; (a drag in progress: its brackets go)
        lda #$ff
        ldx #GUI_NSLOTS - 1             ; no notification icons
        lda #0
-       sta nt_icon,x
        dex
        bpl -
        lda #$ff
        sta l_gu_press
        sta l_gu_drag
        rts

; every window open now hidden: not drawn, not clicked, its gadgets not drawn (they still
; change); windows opened afterwards show as usual. gui_show_all brings them back
gui_hide_all:
        ldy #0
-       cpy gw_n
        beq +
        ldx gw_z,y
        txa
        sta l_hz,y
        lda #1
        sta gw_hid,x
        iny
        bra -
+       sty l_hn
        lda #0
        sta gw_n
        lda #$ff
        sta l_gu_press
        sta l_gu_drag
        jsr l_drag_hide
        jmp gui_redraw_later

; the hidden windows back, behind the ones opened since, in their old order
gui_show_all:
        ldy gw_n                        ; the new ones up by however many come back
        ldx #0
-       cpx l_hn
        beq +
        phx
        lda l_hz,x
        tax
        lda gw_used,x
        and gw_hid,x
        plx                             ; (plx sets the flags from X: test A again)
        cmp #0
        beq _skip
        iny
_skip:  inx
        bra -
+       sty l_gu_t                      ; (the new count)
        ldx gw_n                        ; move the new ones up
        ldy l_gu_t
-       cpx #0
        beq +
        dex
        dey
        lda gw_z,x
        sta gw_z,y
        bra -
+       ldx #0                          ; the hidden ones into the gap, in order
        ldy #0
-       cpx l_hn
        beq _done
        stx l_gu_t+1
        lda l_hz,x
        tax
        lda gw_used,x
        and gw_hid,x
        beq +
        lda #0
        sta gw_hid,x
        txa
        sta gw_z,y
        iny
+       ldx l_gu_t+1
        inx
        bra -
_done:  lda l_gu_t
        sta gw_n
        lda #0
        sta l_hn
        ldx #GUI_MAXWIN - 1             ; (anything else still marked: not any more)
-       sta gw_hid,x
        dex
        bpl -
        jmp gui_redraw_later

; d6_x / d6_y (a screen point): carry set if a window (shown, not hidden) or the menu
; bar covers it. gui_win_rects first, once, for the windows as they are
gui_win_rects:
        ldy #0
        sty gui_wr_n
-       cpy gw_n
        beq _out
        phy
        ldx gw_z,y
        lda gw_shown,x
        beq _nx
        jsr l_gw_rect
        ldx gui_wr_n
        cpx #GUI_MAXWIN
        bcs _nx
        lda gr_x0
        sta l_wr_x0l,x
        lda gr_x0+1
        sta l_wr_x0h,x
        lda gr_x1
        sta l_wr_x1l,x
        lda gr_x1+1
        sta l_wr_x1h,x
        lda gr_y0
        sta l_wr_y0,x
        lda gr_y1
        sta l_wr_y1,x
        inc gui_wr_n
_nx:    ply
        iny
        bra -
_out:   rts

gui_covered:
        lda gui_menubar
        beq +
        lda d6_y
        cmp #GUI_MENU_H
        bcc _yes
+       ldx gui_wr_n
-       dex
        bmi _no
        lda d6_y
        cmp l_wr_y0,x
        bcc -
        lda l_wr_y1,x
        cmp d6_y
        bcc -
        lda d6_x
        cmp l_wr_x0l,x
        lda d6_x+1
        sbc l_wr_x0h,x
        bcc -
        lda l_wr_x1l,x
        cmp d6_x
        lda l_wr_x1h,x
        sbc d6_x+1
        bcc -
_yes:   sec
        rts
_no:    clc
        rts
gui_wr_n:       .byte 0
l_wr_x0l:       .fill GUI_MAXWIN
l_wr_x0h:       .fill GUI_MAXWIN
l_wr_x1l:       .fill GUI_MAXWIN
l_wr_x1h:       .fill GUI_MAXWIN
l_wr_y0:        .fill GUI_MAXWIN
l_wr_y1:        .fill GUI_MAXWIN

; the whole screen again, at the start of the next gui_update: many changes in one frame
; (a server sending a window, its rows, an alert...) cost one redraw, with no flicker
gui_redraw_later:
        lda #1
        sta l_gui_later
        rts
l_gui_later:    .byte 0
l_reopen:       .byte 0
gui_redraws:    .word 0                 ; full redraws so far

gui_redraw:
        lda #0                          ; (it draws every gadget)
        sta l_gg_any
        ldx #GUI_MAXGAD - 1
-       sta gg_dirty,x
        dex
        bpl -
        inc gui_redraws                 ; (tests count these)
        bne +
        inc gui_redraws+1
+       lda #0
        sta l_gui_later
        jsr d6_clip_all
        lda gui_desk_hook+1
        beq _plain
        jsr _call
        bra _wins
_plain: lda #0
        sta gr_x0
        sta gr_x0+1
        sta gr_y0
        sta gr_y0+1
        sta gr_y1+1
        lda #<639
        sta gr_x1
        lda #>639
        sta gr_x1+1
        lda #199
        sta gr_y1
        lda #GUI_DESK
        jsr l_gd_fill
_wins:  lda gui_desk_input+1             ; the desktop icons (unless the program has the
        bne +                           ; desktop: its input hook)
        jsr l_dk_draw
+
        jsr l_gw_draw_mins                ; minimized windows: behind every other one
        ldy #0
-       cpy gw_n
        beq +
        ldx gw_z,y
        lda gw_shown,x                  ; (still being filled: not yet)
        beq _skip
        lda gw_min,x                    ; (minimized: done)
        bne _skip
        phy
        jsr l_gui_draw_win
        ply
_skip:  iny
        bra -
+       jsr l_mn_draw                  ; the menu bar on top
        jmp l_ts_draw                   ; and a toast over everything
_call:  jmp (gui_desk_hook)

; draw window slot X: frame, title bar, close box, gadgets
l_gui_draw_win:
        stx l_gd_ws
        jsr d6_clip_all
        jsr l_gw_rect
        jsr l_gd_frame
        lda #GC_FACE
        jsr l_gd_fill
        ; title bar
        ldx l_gd_ws
        jsr l_gw_rect
        clc
        lda gr_x0
        adc #3
        sta gr_x0
        bcc +
        inc gr_x0+1
+       sec
        lda gr_x1
        sbc #3
        sta gr_x1
        bcs +
        dec gr_x1+1
+       clc
        lda gr_y0
        adc #3
        sta gr_y0
        adc #GUI_TITLE_H - 1
        sta gr_y1
        lda #0
        sta gr_y1+1
        jsr l_gw_front
        ldy #GC_SHADOW
        cmp l_gd_ws
        bne +
        ldy #GC_TITLE
+       tya
        jsr l_gd_fill
        ; the title, bold (twice, one pixel apart), clipped short of the close box
        ldx l_gd_ws
        lda gw_flags,x
        and #GWF_CLOSE
        beq +
        sec
        lda gr_x1
        sbc #16
        sta gr_x1
        bcs +
        dec gr_x1+1
+       lda gw_flags,x                  ; and of the minimize box
        and #GWF_MIN
        beq +
        sec
        lda gr_x1
        sbc #16
        sta gr_x1
        bcs +
        dec gr_x1+1
+       jsr l_gd_clip
        lda l_gwt_lo,x
        sta txt_ptr
        lda l_gwt_hi,x
        sta txt_ptr+1
        jsr l_gw_front
        ldy #GC_LIGHT
        cmp l_gd_ws
        bne +
        ldy #GC_WHITE
+       sty gt_fg
        lda #$ff
        sta gt_bg
        sta gt_n
        lda #0
        sta gt_pw
        ldx l_gd_ws
        clc
        lda gr_y0
        adc #(GUI_TITLE_H - 8) / 2
        sta gt_y
        ldy #0
-       phy
        clc
        lda gr_x0
        adc #3
        sta gt_x
        lda gr_x0+1
        adc #0
        sta gt_x+1
        tya
        clc
        adc gt_x
        sta gt_x
        bcc +
        inc gt_x+1
+       jsr gui_text
        ply
        iny
        cpy #2
        bne -
        jsr d6_clip_all
        ; close box
        ldx l_gd_ws
        lda gw_flags,x
        and #GWF_CLOSE
        beq _minb
        jsr l_gw_rect
        sec                             ; x: right - 19 .. right - 5, y: top + 4 .. + 12
        lda gr_x1
        sbc #5
        sta gr_x1
        bcs +
        dec gr_x1+1
+       sec
        lda gr_x1
        sbc #14
        sta gr_x0
        lda gr_x1+1
        sbc #0
        sta gr_x0+1
        clc
        lda gr_y0
        adc #4
        sta gr_y0
        adc #GUI_TITLE_H - 3
        sta gr_y1
        jsr l_gd_raised
        lda #GC_FACE
        jsr l_gd_fill
        jsr l_gd_cross
_minb:  ldx l_gd_ws                     ; minimize (or restore) box: right - 35 .. right - 21
        lda gw_flags,x
        and #GWF_MIN
        beq _gads
        lda #21
        jsr l_tb_rect
        jsr l_gd_raised
        lda #GC_FACE
        jsr l_gd_fill
        ldy #l_tb_minimize - l_tb_icons
        ldx l_gd_ws
        lda gw_min,x
        beq +
        ldy #l_tb_restore - l_tb_icons
+       jsr l_tb_icon
_gads:  ldx l_gd_ws                     ; (minimized: no gadgets)
        lda gw_min,x
        bne _end
        ldx #0
-       lda gg_win,x
        cmp l_gd_ws
        bne +
        phx
        jsr l_gui_draw_gad0
        plx
+       inx
        cpx #GUI_MAXGAD
        bne -
_end:   jmp d6_clip_all

; X = window slot, A = from the window's right edge to the box's: gr = a title-bar box,
; 15 x 9 (the close box: A = 5; minimize: 21). X kept
l_tb_rect:
        sta l_tb_d
        jsr l_gw_rect
        sec
        lda gr_x1
        sbc l_tb_d
        sta gr_x1
        bcs +
        dec gr_x1+1
+       sec
        lda gr_x1
        sbc #14
        sta gr_x0
        lda gr_x1+1
        sbc #0
        sta gr_x0+1
        clc
        lda gr_y0
        adc #4
        sta gr_y0
        adc #GUI_TITLE_H - 3
        sta gr_y1
        rts

; Y = an icon's offset in l_tb_icons: its rectangles filled, relative to gr's top left
l_tb_icon:
        lda gr_x0
        sta l_tb_bx
        lda gr_x0+1
        sta l_tb_bx+1
        lda gr_y0
        sta l_tb_by
_lp:    lda l_tb_icons,y
        cmp #$ff
        beq _end
        clc
        adc l_tb_bx
        sta gr_x0
        lda l_tb_bx+1
        adc #0
        sta gr_x0+1
        clc
        lda l_tb_icons+2,y
        adc l_tb_bx
        sta gr_x1
        lda l_tb_bx+1
        adc #0
        sta gr_x1+1
        clc
        lda l_tb_icons+1,y
        adc l_tb_by
        sta gr_y0
        clc
        lda l_tb_icons+3,y
        adc l_tb_by
        sta gr_y1
        lda #0
        sta gr_y0+1
        sta gr_y1+1
        lda l_tb_icons+4,y
        phy
        jsr l_gd_fill
        ply
        tya
        clc
        adc #5
        tay
        bra _lp
_end:   rts
l_tb_d:         .byte 0
l_tb_bx:        .word 0
l_tb_by:        .byte 0
l_tb_icons:                             ; x0, y0, x1, y1, colour inside the box's bevel
l_tb_minimize:                          ; _ : a bar along the bottom
        .byte 3, 3, 8, 3, GC_BLACK
        .byte $ff
l_tb_restore:                           ; two windows, one in front of the other
        .byte 4, 0, 9, 0, GC_BLACK      ; behind: top, right, bottom right
        .byte 9, 0, 9, 2, GC_BLACK
        .byte 7, 2, 9, 2, GC_BLACK
        .byte 1, 1, 6, 4, GC_FACE       ; in front: cleared, then its edges
        .byte 1, 1, 6, 1, GC_BLACK
        .byte 1, 4, 6, 4, GC_BLACK
        .byte 1, 1, 1, 4, GC_BLACK
        .byte 6, 1, 6, 4, GC_BLACK
        .byte $ff

; the minimized windows, back to front, behind everything else. l_gd_ws kept
l_gw_draw_mins:
        lda l_gd_ws
        pha
        ldy #0
-       cpy gw_n
        beq _end
        ldx gw_z,y
        lda gw_shown,x
        beq _n
        lda gw_min,x
        beq _n
        phy
        jsr l_gui_draw_win
        ply
_n:     iny
        bra -
_end:   pla
        sta l_gd_ws
        rts

; X = window slot: minimize it (a title bar in the first free place along the bottom,
; behind the other windows in the order) or restore it (to the front). Doesn't draw
l_gw_minmax:
        lda gw_min,x
        beq _min
        lda gw_sxl,x                    ; restore
        sta gw_xl,x
        lda gw_sxh,x
        sta gw_xh,x
        lda gw_sy,x
        sta gw_y,x
        lda gw_swl,x
        sta gw_wl,x
        lda gw_swh,x
        sta gw_wh,x
        lda gw_sh,x
        sta gw_h,x
        lda #0
        sta gw_min,x
        jmp l_gw_raise
_min:   lda gw_xl,x
        sta gw_sxl,x
        lda gw_xh,x
        sta gw_sxh,x
        lda gw_y,x
        sta gw_sy,x
        lda gw_wl,x
        sta gw_swl,x
        lda gw_wh,x
        sta gw_swh,x
        lda gw_h,x
        sta gw_sh,x
        stx l_mm_ws
        ldy #0                          ; the first place no other minimized window has:
_k:     sty l_mm_k                      ; along the bottom row, then the rows above it
        cpy #GUI_MAXWIN - 1
        beq _got                        ; (one for each window: never all taken)
        ldx #0
_w:     cpx l_mm_ws
        beq _wn
        lda gw_used,x
        beq _wn
        lda gw_min,x
        beq _wn
        lda gw_xl,x
        cmp l_mm_xl,y
        bne _wn
        lda gw_y,x
        cmp l_mm_y,y
        bne _wn
        lda gw_xh,x
        cmp l_mm_xh,y
        beq _used
_wn:    inx
        cpx #GUI_MAXWIN
        bne _w
        bra _got
_used:  iny
        bra _k
_got:   ldx l_mm_ws
        ldy l_mm_k
        lda l_mm_xl,y
        sta gw_xl,x
        lda l_mm_xh,y
        sta gw_xh,x
        lda l_mm_y,y
        sta gw_y,x
        lda #<GUI_MIN_W
        sta gw_wl,x
        lda #>GUI_MIN_W
        sta gw_wh,x
        lda #GUI_MIN_H
        sta gw_h,x
        lda #1
        sta gw_min,x
; X = window slot: to the back of gw_z (the window under it gets the front)
l_gw_lower:
        stx l_mm_ws
        ldy #0
-       lda gw_z,y
        cmp l_mm_ws
        beq _sh
        iny
        cpy gw_n
        bne -
        rts
_sh:    cpy #0
        beq _put
        lda gw_z-1,y
        sta gw_z,y
        dey
        bra _sh
_put:   lda l_mm_ws
        sta gw_z
        rts
l_mm_ws:        .byte 0
l_mm_k:         .byte 0
l_mm_xl:                                ; place k: column k % 4, row k / 4 (0 = the bottom)
.for k in range(GUI_MAXWIN)
        .byte <(4 + (k % GUI_MIN_COLS) * GUI_MIN_STEP)
.endfor
l_mm_xh:
.for k in range(GUI_MAXWIN)
        .byte >(4 + (k % GUI_MIN_COLS) * GUI_MIN_STEP)
.endfor
l_mm_y:
.for k in range(GUI_MAXWIN)
        .byte GUI_MIN_Y - (k / GUI_MIN_COLS) * GUI_MIN_H >= GUI_MENU_H ? GUI_MIN_Y - (k / GUI_MIN_COLS) * GUI_MIN_H : GUI_MENU_H
.endfor

;=======================================================================================
; desktop icons: a picture (GUI_ICON_W x GUI_ICON_H) with one or two label lines under it,
; in columns down the left of the desktop (slots 0-7) and the right (8-11), under every window
;=======================================================================================
gui_dk_l1:      .word 0                 ; gui_desk_icon: label line 1 ("" removes the icon),
gui_dk_l2:      .word 0                 ; line 2 ("" none), the picture's bytes (colour
gui_dk_px:      .word 0                 ; $ff = see-through)
dk_used:        .fill GUI_MAXICON
dk_l1:          .fill GUI_MAXICON * GUI_ICON_LBL
dk_l2:          .fill GUI_MAXICON * GUI_ICON_LBL
l_dk_sel:       .byte $ff               ; the selected one, $ff none
l_dk_clk:       .byte 0                 ; frame_count at the last click on it
l_dk_k:         .byte 0
l_dk_r:         .byte 0
l_dk_c:         .byte 0
l_dk_t:         .byte 0
l_dk_off:                               ; icon k: its label's offset, cell centre x, top y
.for k in range(GUI_MAXICON)
        .byte k * GUI_ICON_LBL
.endfor
l_dk_cx         .function k             ; icon k's cell centre x: left columns, then right
                .endf k < GUI_ICON_LEFT ? (k / GUI_ICON_ROWS) * GUI_ICON_CELLW + GUI_ICON_CELLW / 2 : 640 - GUI_ICON_CELLW / 2 - ((k - GUI_ICON_LEFT) / GUI_ICON_ROWS) * GUI_ICON_CELLW
l_dk_mx:
.for k in range(GUI_MAXICON)
        .byte <l_dk_cx(k)
.endfor
l_dk_mxh:
.for k in range(GUI_MAXICON)
        .byte >l_dk_cx(k)
.endfor
l_dk_y:
.for k in range(GUI_MAXICON)
        .byte GUI_ICON_TOP + ((k < GUI_ICON_LEFT ? k : k - GUI_ICON_LEFT) % GUI_ICON_ROWS) * GUI_ICON_CELLH
.endfor

; A = slot: set it from gui_dk_l1 / l2 / px, or remove it. Drawn at the next frame
gui_desk_icon:
        cmp #GUI_MAXICON
        bcc +
        rts
+       sta l_dk_k
        tax
        lda #0
        sta dk_used,x
        cpx l_dk_sel
        bne +
        lda #$ff
        sta l_dk_sel
+       clc                             ; the labels
        lda #<dk_l1
        adc l_dk_off,x
        sta tmp7
        lda #>dk_l1
        adc #0
        sta tmp7+1
        lda gui_dk_l1
        sta tmp6
        lda gui_dk_l1+1
        sta tmp6+1
        jsr l_dk_copy
        ldx l_dk_k
        clc
        lda #<dk_l2
        adc l_dk_off,x
        sta tmp7
        lda #>dk_l2
        adc #0
        sta tmp7+1
        lda gui_dk_l2
        sta tmp6
        lda gui_dk_l2+1
        sta tmp6+1
        jsr l_dk_copy
        ldy #0                          ; no line 1: removed
        lda gui_dk_l1
        sta tmp6
        lda gui_dk_l1+1
        sta tmp6+1
        lda (tmp6),y
        beq _done
        lda gui_dk_px                   ; the picture to GUI_DESK_MEM + k * 512
        sta tmp6
        lda gui_dk_px+1
        sta tmp6+1
        lda #<GUI_DESK_MEM
        sta ptr0
        lda l_dk_k
        asl
        clc
        adc #>GUI_DESK_MEM
        sta ptr0+1
        lda #`GUI_DESK_MEM
        sta ptr0+2
        lda #GUI_DESK_MEM >> 24
        sta ptr0+3
        ldx #GUI_ICON_W * GUI_ICON_H / 256
_pg:    ldy #0
        ldz #0
-       lda (tmp6),y
        sta [ptr0],z
        iny
        inz
        bne -
        inc tmp6+1
        inc ptr0+1
        dex
        bne _pg
        ldz #0
        ldx l_dk_k
        lda #1
        sta dk_used,x
_done:  jmp gui_redraw_later

; tmp6 -> tmp7: a label line, at most GUI_ICON_LBL - 1 characters and the 0
l_dk_copy:
        ldy #0
-       lda (tmp6),y
        beq +
        sta (tmp7),y
        iny
        cpy #GUI_ICON_LBL - 1
        bne -
        lda #0
+       sta (tmp7),y
        rts

; every icon gone (signing off)
gui_desk_clear:
        lda #0
        ldx #GUI_MAXICON - 1
-       sta dk_used,x
        dex
        bpl -
        lda #$ff
        sta l_dk_sel
        rts

l_dk_draw:
        ldx #0
_lp:    stx l_dk_k
        lda dk_used,x
        beq _nx
        jsr l_dk_one
_nx:    ldx l_dk_k
        inx
        cpx #GUI_MAXICON
        bne _lp
        ldz #0
        rts

; icon l_dk_k: its picture, 8 pixels at a time (one cell row each), then its labels
l_dk_one:
        lda #0
        sta l_dk_r
_row:   lda #0
        sta l_dk_c
_chk:   ldx l_dk_k
        lda l_dk_c                      ; x = centre - 16 + c * 8 (a multiple of 8)
        asl
        asl
        asl
        clc
        adc l_dk_mx,x
        sta d6_x
        lda l_dk_mxh,x
        adc #0
        sta d6_x+1
        sec
        lda d6_x
        sbc #GUI_ICON_W / 2
        sta d6_x
        lda d6_x+1
        sbc #0
        sta d6_x+1
        lda #0
        sta d6_y+1
        clc
        lda l_dk_y,x
        adc l_dk_r
        sta d6_y
        jsr d6_addr                     ; d6_p: the screen
        lda l_dk_r                      ; ptr0: the picture, + r * 32 + c * 8
        and #7
        lsr
        ror
        ror
        ror
        sta l_dk_t
        lda l_dk_c
        asl
        asl
        asl
        ora l_dk_t
        sta ptr0
        lda l_dk_r
        lsr
        lsr
        lsr
        sta l_dk_t
        lda l_dk_k
        asl
        clc
        adc l_dk_t
        adc #>GUI_DESK_MEM
        sta ptr0+1
        lda #`GUI_DESK_MEM
        sta ptr0+2
        lda #GUI_DESK_MEM >> 24
        sta ptr0+3
        ldz #7
-       lda [ptr0],z
        cmp #$ff
        beq +
        sta [d6_p],z
+       dez
        bpl -
        inc l_dk_c
        lda l_dk_c
        cmp #GUI_ICON_W / 8
        bne _chk
        inc l_dk_r
        lda l_dk_r
        cmp #GUI_ICON_H
        bne _row
        ldz #0
        ldx l_dk_k                      ; the labels: white, on navy when it's selected
        clc
        lda #<dk_l1
        adc l_dk_off,x
        sta txt_ptr
        lda #>dk_l1
        adc #0
        sta txt_ptr+1
        lda #GUI_ICON_H + 2
        jsr l_dk_label
        ldx l_dk_k
        clc
        lda #<dk_l2
        adc l_dk_off,x
        sta txt_ptr
        lda #>dk_l2
        adc #0
        sta txt_ptr+1
        lda #GUI_ICON_H + 11
        ; (fall through)
; txt_ptr = a label line, A = its y below the icon's top: centred under it
l_dk_label:
        ldx l_dk_k
        clc
        adc l_dk_y,x
        sta gt_y
        ldy #0
-       lda (txt_ptr),y
        beq +
        iny
        bra -
+       cpy #0
        beq _none
        tya                             ; x = centre - n * 4
        asl
        asl
        sta l_dk_t
        sec
        lda l_dk_mx,x
        sbc l_dk_t
        sta gt_x
        lda l_dk_mxh,x
        sbc #0
        sta gt_x+1
        lda #0
        sta gt_pw
        lda #$ff
        sta gt_n
        sta gt_bg
        lda #GC_WHITE
        sta gt_fg
        cpx l_dk_sel
        bne +
        lda #GC_TITLE
        sta gt_bg
+       jsr gui_text
        lda #$ff
        sta gt_bg
_none:  rts

; a click on the desktop (no window there): an icon is selected; the same one again
; within half a second is a double click -> GE_DESK. Elsewhere: none selected
l_gu_desk:
        jsr l_gw_front                  ; (a modal window in front: nothing)
        cmp #$ff
        beq +
        tax
        lda gw_flags,x
        and #GWF_MODAL
        beq +
        clc
        rts
+       ldx #0
_lp:    lda dk_used,x
        beq _nx
        stx l_dk_k
        lda l_dk_mx,x                   ; the icon and its labels: centre - 32 .. + 31,
        sec                             ; top .. top + 35
        sbc #32
        sta gr_x0
        lda l_dk_mxh,x
        sbc #0
        sta gr_x0+1
        clc
        lda gr_x0
        adc #63
        sta gr_x1
        lda gr_x0+1
        adc #0
        sta gr_x1+1
        lda l_dk_y,x
        sta gr_y0
        clc
        adc #GUI_ICON_H + 19
        sta gr_y1
        lda #0
        sta gr_y0+1
        sta gr_y1+1
        jsr l_pt_in
        ldx l_dk_k
        bcs _hit
_nx:    inx
        cpx #GUI_MAXICON
        bne _lp
        lda l_dk_sel                    ; nothing there: none selected
        cmp #$ff
        beq _out
        lda #$ff
        sta l_dk_sel
        jsr gui_redraw_later
_out:   clc
        rts
_hit:   cpx l_dk_sel
        bne _sel
        lda frame_count
        sec
        sbc l_dk_clk
        cmp #25
        bcs _clk
        stx ge_val                      ; double click
        lda #0
        sta ge_val+1
        sta ge_win
        sta ge_gid
        lda frame_count                 ; (a third click isn't another double)
        sec
        sbc #100
        sta l_dk_clk
        lda #GE_DESK
        sta ge_type
        sec
        rts
_sel:   stx l_dk_sel
        jsr gui_redraw_later
_clk:   lda frame_count
        sta l_dk_clk
        clc
        rts

; an X in the middle of gr (the close box's inside)
l_gd_cross:                             ; corner to corner of gr, two pixels thick
        lda #GC_BLACK
        sta d6_col
        lda #0
        sta d6_y+1
        sta d6_y1+1
        ldy #0
_l:     sty l_cx_i
        clc                             ; \ from (x0 + i, y0) to (x1 - 1 + i, y1)
        lda gr_x0
        adc l_cx_i
        sta d6_x
        lda gr_x0+1
        adc #0
        sta d6_x+1
        sec
        lda gr_x1
        sbc #1
        sta d6_x1
        lda gr_x1+1
        sbc #0
        sta d6_x1+1
        clc
        lda d6_x1
        adc l_cx_i
        sta d6_x1
        lda d6_x1+1
        adc #0
        sta d6_x1+1
        lda gr_y0
        sta d6_y
        lda gr_y1
        sta d6_y1
        jsr d6_line
        sec                             ; / from (x1 - i, y0) to (x0 + 1 - i, y1)
        lda gr_x1
        sbc l_cx_i
        sta d6_x
        lda gr_x1+1
        sbc #0
        sta d6_x+1
        clc
        lda gr_x0
        adc #1
        sta d6_x1
        lda gr_x0+1
        adc #0
        sta d6_x1+1
        sec
        lda d6_x1
        sbc l_cx_i
        sta d6_x1
        lda d6_x1+1
        sbc #0
        sta d6_x1+1
        lda gr_y0
        sta d6_y
        lda gr_y1
        sta d6_y1
        jsr d6_line
        ldy l_cx_i
        iny
        cpy #2
        bne _l
        rts
l_cx_i:         .byte 0

;=======================================================================================
; gadgets
;=======================================================================================
gui_gad_add:
        lda gp_win
        jsr l_gw_find
        bcc +
        rts
+       stx l_gd_ws
        lda gp_win
        ldx gp_gid
        jsr l_gg_find                   ; the same id again: replace it
        bcc _slot
        ldx #0
-       lda gg_win,x
        cmp #$ff
        beq _slot
        inx
        cpx #GUI_MAXGAD
        bne -
        sec
        rts
_slot:  jsr l_gg_release                 ; (a replaced gadget's block goes back)
        lda l_gd_ws
        sta gg_win,x
        lda gp_gid
        sta gg_id,x
        lda gp_kind
        sta gg_kind,x
        lda gp_x
        sta gg_xl,x
        lda gp_x+1
        sta gg_xh,x
        lda gp_y
        sta gg_y,x
        lda gp_w
        sta gg_wl,x
        lda gp_w+1
        sta gg_wh,x
        lda gp_h
        sta gg_h,x
        lda gp_flags
        sta gg_flags,x
        lda gp_max
        beq +
        cmp #GUI_TEXTMAX
        bcc ++
+       lda #GUI_TEXTMAX - 1
+       sta gg_max,x
        lda #0
        sta gg_val,x
        jsr l_gg_copy
        lda gg_kind,x                   ; a grid: its cells all 0
        cmp #GK_GRID
        bne +
        jsr l_gr_clear
+       lda gg_kind,x                   ; a list, view, text area or drop-down: a block
        cmp #GK_LIST
        beq +
        cmp #GK_EDIT
        beq +
        cmp #GK_DROP
        beq +
        cmp #GK_VIEW
        bne _nobig
+       ldy #0
-       lda gb_used,y
        beq +
        iny
        cpy #GUI_MAXBIG
        bne -
        bra _nobig                      ; none free: it stays empty
+       lda #1
        sta gb_used,y
        tya
        sta gg_big,x
        lda #0
        sta gb_n,y
        sta gb_head,y
        sta gb_top,y
        sta gb_row,y
        sta gb_col,y
        lda #$ff
        sta gb_sel,y
_nobig: lda gg_kind,x                   ; the window's first text box gets the keyboard
        cmp #GK_TEXT
        beq +
        cmp #GK_EDIT
        beq +
        cmp #GK_PASSWORD
        bne _done
+       ldy l_gd_ws
        lda gw_focus,y
        cmp #$ff
        bne _done
        txa
        sta gw_focus,y
_done:  clc
        rts

; gp_text -> gadget X's buffer (up to gg_max), length, cursor at the end. X kept
l_gg_copy:
        lda l_gtb_lo,x
        sta tmp6
        lda l_gtb_hi,x
        sta tmp6+1
        lda gp_text
        sta txt_ptr
        lda gp_text+1
        sta txt_ptr+1
        ldy #0
        lda txt_ptr+1
        beq _end                        ; no text
-       tya
        cmp gg_max,x
        bcs _end
        lda (txt_ptr),y
        beq _end
        sta (tmp6),y
        iny
        bra -
_end:   lda #0
        sta (tmp6),y
        tya
        sta gg_len,x
        sta gg_cur,x
        lda #0
        sta gg_scr,x
        rts

gui_set_text:
        lda gp_win
        ldx gp_gid
        jsr l_gg_find
        bcs _no
        lda gg_kind,x                   ; a text area or text view: emptied
        cmp #GK_EDIT
        beq _empty
        cmp #GK_VIEW
        bne +
_empty: ldy gg_big,x
        cpy #$ff
        beq _no
        lda #0
        sta gb_n,y
        sta gb_head,y
        sta gb_top,y
        sta gb_row,y
        sta gb_col,y
        jmp l_gg_later
+
        jsr l_gg_copy
        phx
        jsr l_gg_redraw
        plx
        jmp l_gg_needs
_no:    rts

; the window of gadget slot X: each GGF_NEEDTEXT button there greyed while its text box
; (gg_val = the box's id) is empty, and back when it isn't; redrawn when that changes
l_gg_needs:
        ldy gg_win,x
        sty l_gn_ws
        ldx #0
_lp:    lda gg_win,x
        cmp l_gn_ws
        bne _nx
        lda gg_flags,x
        and #GGF_NEEDTEXT
        beq _nx
        stx l_gn_i
        lda gg_val,x                    ; find the box: same window, that id
        sta l_gn_id
        ldy #0
        lda #0
        sta l_gn_len
_f:     lda gg_win,y
        cmp l_gn_ws
        bne _fn
        lda gg_id,y
        cmp l_gn_id
        bne _fn
        lda gg_kind,y
        cmp #GK_BUTTON
        beq _fn
        lda gg_len,y
        sta l_gn_len
        bra _got
_fn:    iny
        cpy #GUI_MAXGAD
        bne _f
_got:   lda gg_flags,x
        and #$ff - GGF_DISABLED
        ldy l_gn_len
        bne +
        ora #GGF_DISABLED
+       cmp gg_flags,x
        beq _nx
        sta gg_flags,x
        jsr l_gg_redraw
        ldx l_gn_i
_nx:    inx
        cpx #GUI_MAXGAD
        bne _lp
        rts
l_gn_ws:  .byte 0
l_gn_i:   .byte 0
l_gn_id:  .byte 0
l_gn_len: .byte 0

gui_get_text:
        jsr l_gg_find
        bcs _no
        ldy gg_len,x
        lda l_gtb_hi,x
        pha
        lda l_gtb_lo,x
        plx
        clc
_no:    rts

; A = window, X = gadget, gp_flags = its new flags (GGF_*): e.g. GGF_DISABLED greys a
; button out and its clicks are ignored; redrawn
gui_set_flags:
        jsr l_gg_find
        bcs +
        lda gp_flags
        sta gg_flags,x
        phx
        jsr l_gg_redraw
        plx
        jmp l_gg_needs                  ; (a NEEDTEXT button keeps following its box)
+       rts

gui_focus:
        jsr l_gg_find
        bcs _no
        phx
        ldy gg_win,x
        lda gw_focus,y                  ; the old one loses its caret
        pha
        txa
        sta gw_focus,y
        plx
        cpx #$ff
        beq +
        jsr l_gg_redraw
+       plx
        jmp l_gg_redraw
_no:    rts

; redraw gadget X: in place if its window is in front, else everything
l_gg_redraw:
        lda l_gui_later                 ; a whole redraw is coming anyway
        bne _skip
        ldy gg_win,x                    ; not drawn yet: it waits for gui_win_show
        lda gw_hid,y                    ; (hidden: not drawn at all)
        bne _skip
        lda gw_shown,y
        bne +
_skip:  rts
+       phx
        jsr l_gw_front
        plx
        cmp gg_win,x
        beq l_gui_draw_gad
        jmp gui_redraw_later            ; (behind another window: once, at the next frame)

; A = window, X = gadget: draw it again (after gui_list_row etc.)
gui_gad_redraw:
        jsr l_gg_find
        bcc l_gg_later
        rts

; gadget X drawn again at the start of the next gui_update: many changes in a frame (a
; server sending lines one at a time) cost one redraw
l_gg_later:
        lda #1
        sta gg_dirty,x
        sta l_gg_any
        rts

; the gadgets marked by l_gg_later
l_gg_flush:
        lda #0
        sta l_gg_any
        ldx #0
-       lda gg_dirty,x
        beq +
        lda #0
        sta gg_dirty,x
        lda gg_win,x
        cmp #$ff
        beq +
        phx
        jsr l_gg_redraw
        plx
+       inx
        cpx #GUI_MAXGAD
        bne -
        rts

; draw gadget slot X
; draw gadget X in place, unless its window is minimized
l_gui_draw_gad:
        ldy gg_win,x
        lda gw_min,y
        ora gw_hid,y
        bne _r
        jmp l_gui_draw_gad0
_r:     rts

l_gui_draw_gad0:
        stx l_gd_gs
        jsr d6_clip_all
        jsr l_gg_rect
        lda #$ff
        sta gt_bg
        sta gt_n
        lda #0
        sta gt_pw
        lda #GC_BLACK
        sta gt_fg
        lda gg_flags,x
        and #GGF_DISABLED
        beq +
        lda #GC_SHADOW
        sta gt_fg
+       lda l_gtb_lo,x
        sta txt_ptr
        lda l_gtb_hi,x
        sta txt_ptr+1
        lda gg_kind,x
        cmp #GK_BUTTON
        bne +
        jmp l_gd_button
+       cmp #GK_TEXT
        beq _tb
        cmp #GK_PASSWORD
        beq _tb
        cmp #GK_LIST
        beq _box
        cmp #GK_VIEW
        beq _box
        cmp #GK_EDIT
        beq _box
        cmp #GK_DROP
        bne +
        jmp l_gd_drop
+       cmp #GK_GRID
        bne +
        jmp l_gd_grid
+       cmp #GK_GROUP
        bne +
        jmp l_gd_group
+       cmp #GK_PROGRESS
        bne +
        jmp l_gd_progress
+       cmp #GK_CHECK
        beq _chk
        cmp #GK_RADIO
        beq _chk
        jmp l_gd_label
_chk:   jmp l_gd_check
_tb:    jmp l_gd_textbox
_box:   jmp l_gd_rows

; a progress bar: sunken, white, navy from the left for gg_val percent (0-100)
l_gd_progress:
        jsr l_gd_sunken                 ; (gr: inside the bevel)
        lda #GC_WHITE
        jsr l_gd_fill
        ldx l_gd_gs
        lda gg_val,x
        beq _done
        cmp #100
        bcc +
        lda #100
+       sta l_pg_v
        sec                             ; the inside's width
        lda gr_x1
        sbc gr_x0
        sta l_pg_w
        lda gr_x1+1
        sbc gr_x0+1
        sta l_pg_w+1
        inc l_pg_w
        bne +
        inc l_pg_w+1
+       lda l_pg_w                      ; filled = width * v / 100: (width * v) * 656 >> 16
        sta $d770                       ; (the hardware multiplier)
        lda l_pg_w+1
        sta $d771
        lda #0
        sta $d772
        sta $d773
        sta $d775
        sta $d776
        sta $d777
        lda l_pg_v
        sta $d774
        lda $d778
        ldx $d779
        sta $d770
        stx $d771
        lda #<656
        sta $d774
        lda #>656
        sta $d775
        lda $d77a
        sta l_pg_w
        lda $d77b
        sta l_pg_w+1
        ora l_pg_w
        beq _done
        clc
        lda gr_x0
        adc l_pg_w
        sta gr_x1
        lda gr_x0+1
        adc l_pg_w+1
        sta gr_x1+1
        lda gr_x1
        bne +
        dec gr_x1+1
+       dec gr_x1
        lda #GC_TITLE
        jsr l_gd_fill
_done:  rts
l_pg_v:         .byte 0
l_pg_w:         .word 0

l_gd_label:
        lda #GC_FACE
        jsr l_gd_fill
        jsr l_gd_clip
        jsr l_gd_vmid
        lda gr_x0
        sta gt_x
        lda gr_x0+1
        sta gt_x+1
        ldx l_gd_gs
        lda gg_flags,x
        and #GGF_CENTRE
        beq +
        jsr l_gd_hmid
+       lda gt_x                        ; (bold: drawn again one pixel right, as titles are)
        sta l_gd_bx
        lda gt_x+1
        sta l_gd_bx+1
        jsr gui_text
        ldx l_gd_gs
        lda gg_flags,x
        and #GGF_BOLD
        beq +
        clc
        lda l_gd_bx
        adc #1
        sta gt_x
        lda l_gd_bx+1
        adc #0
        sta gt_x+1
        jsr gui_text
+       jmp d6_clip_all
l_gd_bx:        .word 0

; gt_y = text centred in gr's height
l_gd_vmid:
        sec
        lda gr_y1
        sbc gr_y0
        sec
        sbc #7                          ; height - 8 (height = y1 - y0 + 1)
        bcs +
        lda #0
+       lsr
        clc
        adc gr_y0
        sta gt_y
        rts

; gt_x = text (txt_ptr) centred in gr's width
l_gd_hmid:
        jsr l_gd_strlen
        sta l_gu_t                      ; width in pixels: n * 8
        lda #0
        sta l_gu_t+1
        asl l_gu_t
        rol l_gu_t+1
        asl l_gu_t
        rol l_gu_t+1
        asl l_gu_t
        rol l_gu_t+1
        sec                             ; room = x1 - x0 + 1 - width
        lda gr_x1
        sbc gr_x0
        sta l_gu_t2
        lda gr_x1+1
        sbc gr_x0+1
        sta l_gu_t2+1
        inc l_gu_t2
        bne +
        inc l_gu_t2+1
+       sec
        lda l_gu_t2
        sbc l_gu_t
        sta l_gu_t2
        lda l_gu_t2+1
        sbc l_gu_t+1
        sta l_gu_t2+1
        bcs +
        lda #0                          ; too wide: from the left
        sta l_gu_t2
        sta l_gu_t2+1
+       lsr l_gu_t2+1
        ror l_gu_t2
        clc
        lda gr_x0
        adc l_gu_t2
        sta gt_x
        lda gr_x0+1
        adc l_gu_t2+1
        sta gt_x+1
        rts

l_gd_button:
        lda gg_flags,x
        and #GGF_DEFAULT
        beq +
        lda #GC_BLACK                   ; the default button's extra black border
        tax
        jsr l_gd_edges
        jsr l_gd_shrink
+       lda l_gu_press
        cmp l_gd_gs
        bne _up
        jsr l_gd_pressed
        bra _face
_up:    jsr l_gd_raised
_face:  lda #GC_FACE
        jsr l_gd_fill
        jsr l_gd_clip
        jsr l_gd_hmid
        jsr l_gd_vmid
        lda l_gu_press
        cmp l_gd_gs
        bne +
        inc gt_y                        ; pressed: the text moves down and right
        inc gt_x
        bne +
        inc gt_x+1
+       ldx l_gd_gs
        lda gg_flags,x
        and #GGF_DISABLED
        beq _txt
        lda #GC_WHITE                   ; disabled: etched (white, then grey on top)
        sta gt_fg
        lda gt_x
        pha
        lda gt_x+1
        pha
        inc gt_x
        inc gt_y
        jsr gui_text
        dec gt_y
        pla
        sta gt_x+1
        pla
        sta gt_x
        lda #GC_SHADOW
        sta gt_fg
_txt:   jsr gui_text
        jmp d6_clip_all

; a check box or radio button: a small sunken box, ticked (or a dot) when gg_val is set,
; the text to its right
l_gd_check:
        lda #GC_FACE
        jsr l_gd_fill
        jsr l_gd_vmid                   ; text row; the box sits on it
        lda gr_x0                       ; the text: 14 pixels in
        clc
        adc #14
        sta gt_x
        lda gr_x0+1
        adc #0
        sta gt_x+1
        jsr l_gd_clip
        jsr gui_text
        jsr d6_clip_all
        ldx l_gd_gs                     ; the box: 10 x 9 at the text's left
        lda gr_x0
        clc
        adc #9
        sta gr_x1
        lda gr_x0+1
        adc #0
        sta gr_x1+1
        lda gt_y
        sta gr_y0
        clc
        adc #8
        sta gr_y1
        lda #0
        sta gr_y0+1
        sta gr_y1+1
        jsr l_gd_sunken
        lda #GC_WHITE
        jsr l_gd_fill
        ldx l_gd_gs
        lda gg_val,x
        beq _out
        lda gg_kind,x
        cmp #GK_RADIO
        beq _dot
        lda #GC_BLACK                   ; a tick: \ then /, two pixels thick
        sta d6_col
        ldy #0
_t:     phy
        tya
        clc
        adc gr_x0
        sta d6_x
        lda gr_x0+1
        adc #0
        sta d6_x+1
        clc
        lda d6_x
        adc #2
        sta d6_x1
        lda d6_x+1
        adc #0
        sta d6_x1+1
        lda gr_y0
        inc a
        inc a
        sta d6_y
        clc
        adc #2
        sta d6_y1
        lda #0
        sta d6_y+1
        sta d6_y1+1
        jsr d6_line
        clc                             ; / from the bottom of the \ up to the top right
        lda d6_x1
        sta d6_x
        lda d6_x1+1
        sta d6_x+1
        lda d6_y1
        sta d6_y
        lda gr_y0
        sta d6_y1
        clc
        lda d6_x
        adc #3
        sta d6_x1
        lda d6_x+1
        adc #0
        sta d6_x1+1
        jsr d6_line
        ply
        iny
        cpy #2
        bne _t
_out:   rts
_dot:   jsr l_gd_shrink                 ; radio: a black dot in the middle
        lda #GC_BLACK
        jmp l_gd_fill

; A = window, X = gadget, gp_x = value: a check box's state or a list's selected row
; ($ffff / $ff = none). Redrawn
gui_set_value:
        jsr l_gg_find
        bcs _no
        lda gg_kind,x
        cmp #GK_VIEW                    ; a text view: scrolled to wrapped line gp_x (0 = the
        bne +                           ; top; past the end: the last page)
        ldy gg_big,x
        cpy #$ff
        beq _no
        jsr l_gb_vlgad
        jsr l_gb_maxtop
        sta l_gb_t
        lda gp_x+1
        bne _vmax
        lda gp_x
        cmp l_gb_t
        bcc _vset
_vmax:  lda l_gb_t
_vset:  sta gb_top,y
        jmp l_gg_later
+       cmp #GK_LIST
        beq +
        cmp #GK_DROP
        bne _val
+
        ldy gg_big,x
        cpy #$ff
        beq _no
        lda gp_x+1
        bne _none
        lda gp_x
        cmp gb_n,y
        bcc +
_none:  lda #$ff
+       sta gb_sel,y
        cmp #$ff                        ; keep it in view
        beq _draw
        phx
        jsr l_gb_vlgad
        plx
        lda gb_sel,y
        cmp gb_top,y
        bcs +
        sta gb_top,y
        bra _draw
+       sec
        sbc gb_top,y
        cmp l_gb_vl
        bcc _draw
        lda gb_sel,y
        sec
        sbc l_gb_vl
        inc a
        sta gb_top,y
_draw:  jmp l_gg_redraw
_val:   lda gp_x
        sta gg_val,x
        phx
        jsr l_gg_redraw
        plx
        jmp l_gg_needs                  ; (a NEEDTEXT button: its box's id just came)
_no:    rts

l_gd_group:
        lda #GC_SHADOW
        ldx #GC_WHITE
        jsr l_gd_edges
        jsr l_gd_shrink
        lda #GC_WHITE
        ldx #GC_SHADOW
        jsr l_gd_edges
        jmp d6_clip_all

l_gd_textbox:
        jsr l_gd_sunken                 ; (no white fill first: that flashes when typing)
        ldx l_gd_gs
        lda gg_kind,x
        cmp #GK_PASSWORD
        bne +
        lda #1
        sta gt_pw
+       ; visible characters: (inside width - 2) / 8
        sec
        lda gr_x1
        sbc gr_x0
        sta l_gu_t
        lda gr_x1+1
        sbc gr_x0+1
        lsr
        ror l_gu_t
        lsr
        ror l_gu_t
        lsr
        ror l_gu_t
        lda l_gu_t
        bne +
        lda #1
+       sta gt_n
        ; keep the cursor in view: scr <= cur < scr + n
        lda gg_cur,x
        cmp gg_scr,x
        bcs +
        sta gg_scr,x
+       sec
        lda gg_cur,x
        sbc gg_scr,x
        cmp gt_n
        bcc +
        lda gg_cur,x
        sec
        sbc gt_n
        inc a
        sta gg_scr,x
+       clc
        lda l_gtb_lo,x
        adc gg_scr,x
        sta txt_ptr
        lda l_gtb_hi,x
        adc #0
        sta txt_ptr+1
        jsr l_gd_clip
        jsr l_gd_vmid
        clc
        lda gr_x0
        adc #1
        sta gt_x
        lda gr_x0+1
        adc #0
        sta gt_x+1
        lda #GC_WHITE                   ; each character on white, over the old one
        sta gt_bg
        jsr gui_text
        jsr l_gd_spare                  ; and white around it
        ; the caret, if this box has the keyboard and its window is in front
        ldx l_gd_gs
        ldy gg_win,x
        lda gw_focus,y
        cmp l_gd_gs
        bne _out
        jsr l_gw_front
        ldx l_gd_gs
        cmp gg_win,x
        bne _out
        sec
        lda gg_cur,x
        sbc gg_scr,x
        sta l_gu_t
        lda #0
        sta l_gu_t+1
        asl l_gu_t
        rol l_gu_t+1
        asl l_gu_t
        rol l_gu_t+1
        asl l_gu_t
        rol l_gu_t+1
        sec                             ; (+ 1: where the character starts)
        lda gr_x0
        adc l_gu_t
        sta d6_x
        lda gr_x0+1
        adc l_gu_t+1
        sta d6_x+1
        lda d6_x
        sta d6_x1
        lda d6_x+1
        sta d6_x1+1
        lda gt_y
        sta d6_y
        clc
        adc #7
        sta d6_y1
        lda #0
        sta d6_y+1
        sta d6_y1+1
        lda #GC_BLACK
        sta d6_col
        jsr d6_fill
_out:   jmp d6_clip_all

;=======================================================================================
; gui_update: one frame of input
;=======================================================================================
gui_update:
        lda l_gui_later                 ; a redraw waiting from the last frame's changes
        beq +
        jsr gui_redraw
+       lda l_gg_any                    ; gadgets waiting
        beq +
        jsr l_gg_flush
        jsr l_ts_draw                   ; (they may have drawn over the toast)
+       jsr l_ts_tick
        jsr l_gui_poll
        lda l_gu_drag                   ; dragging: the brackets follow the pointer
        cmp #$ff
        beq +
        jsr l_drag_show
+       jsr l_nt_flash
        lda l_busy                      ; busy (the hourglass): no clicks or keys
        beq +
        clc
        rts
+       lda l_dd_gs                     ; a drop-down list's pop-up open: it has the input
        cmp #$ff
        beq +
        jmp l_dd_update
+       lda l_mn_open                   ; a menu open: it has the input
        cmp #$ff
        beq +
        jmp l_mn_update
+       lda l_dk_held                   ; a press held on the desktop's input hook: its
        beq _nodk                       ; moves and its release go there too
        lda ev_type
        cmp #EV_MOVE
        beq _dkmv
        cmp #EV_UP
        bne _nodk
        lda #0
        sta l_dk_held
        lda #GUI_DK_UP
        jmp (gui_desk_input)
_dkmv:  lda #GUI_DK_MOVE
        jmp (gui_desk_input)
_nodk:  lda ev_type
        cmp #EV_RDOWN                   ; a right click on the desktop: the hook's
        bne +
        lda gui_desk_input+1
        beq _none
        jsr l_gw_at
        bcs _none
        lda #GUI_DK_RIGHT
        jmp (gui_desk_input)
+       lda ev_type
        cmp #EV_DOWN
        bne _notdown
        jsr l_ts_click                  ; a click on the toast: it goes (and may report)
        bcc +
        rts
+       lda gui_menubar                 ; a click on the bar: a notification icon,
        beq _down                       ; or open that menu
        jsr l_nt_at
        cmp #$ff
        beq _title
        sta ge_val
        lda #0
        sta ge_val+1
        lda #GE_NOTIFY
        sta ge_type
        sec
        rts
_title: jsr l_mn_at
        cmp #$ff
        beq _down
        jsr l_md_open
        jsr l_mn_draw
        clc
        rts
_down:  jmp l_gu_down
_notdown:
        cmp #EV_UP
        bne _notup
        jmp l_gu_up
_notup: cmp #EV_KEY
        bne _none
        jmp l_gu_key
_none:  clc
        rts

l_gu_none:
        clc
        rts

; the topmost window under the pointer -> X, carry set (clear: the desktop)
l_gw_at:
        ldy gw_n                        ; the windows, front first
-       dey
        bmi _mins
        ldx gw_z,y
        lda gw_min,x
        bne -
        phy
        jsr l_gw_rect
        jsr l_pt_in
        ply
        bcc -
        ldx gw_z,y
        sec
        rts
_mins:  ldx #0                          ; then the minimized ones, behind them all
_m:     lda gw_used,x
        beq _mn
        lda gw_min,x
        beq _mn
        lda gw_shown,x
        beq _mn
        lda gw_hid,x
        bne _mn
        phx
        jsr l_gw_rect
        jsr l_pt_in
        plx
        bcc _mn
        rts                             ; (carry set)
_mn:    inx
        cpx #GUI_MAXWIN
        bne _m
        clc
        rts

; the topmost gadget of window l_gd_ws under the pointer -> X, carry set
l_gg_at:
        ldx #GUI_MAXGAD
-       dex
        bmi _no
        lda gg_win,x
        cmp l_gd_ws
        bne -
        jsr l_gg_rect
        jsr l_pt_in
        bcc -
        rts
_no:    clc
        rts

l_gu_down:
        jsr l_gw_at
        bcs +
        lda gui_desk_input+1            ; the desktop: the program's hook, or its icons
        beq _icons
        jsr l_gw_front                  ; (a modal window in front: nothing)
        cmp #$ff
        beq _hook
        tax
        lda gw_flags,x
        and #GWF_MODAL
        bne l_gu_none
_hook:  lda #1
        sta l_dk_held
        lda #GUI_DK_DOWN
        jmp (gui_desk_input)
_icons: jmp l_gu_desk
+
        stx l_gu_ws
        jsr l_gw_front
        cmp l_gu_ws
        beq _front
        tax                             ; a modal window in front blocks the rest
        lda gw_flags,x
        and #GWF_MODAL
        bne l_gu_none
        ldx l_gu_ws                     ; (a minimized one stays at the back: only its
        lda gw_min,x                    ; boxes and dragging it do anything)
        bne _front
        jsr l_gw_raise
        jsr gui_redraw
_front: ldx l_gu_ws
        clc                             ; in the title bar? (y < top + client offset)
        lda gw_y,x
        adc #GUI_CLIENT_Y - 1
        cmp ev_y
        bcc _client
        ; the close box: x >= right - 19
        lda gw_flags,x
        and #GWF_CLOSE
        beq _minbox
        jsr l_gw_rect
        sec
        lda gr_x1
        sbc #19
        sta gr_x0
        lda gr_x1+1
        sbc #0
        sta gr_x0+1
        jsr l_pt_in
        bcc _minbox
        lda #GE_CLOSE
        ldx l_gu_ws
        lda gw_id,x
        sta ge_win
        lda #0
        sta ge_gid
        lda #GE_CLOSE
        sta ge_type
        sec
        rts
_minbox:                                ; minimize / restore: x right - 35 .. right - 20
        ldx l_gu_ws
        lda gw_flags,x
        and #GWF_MIN
        beq _move
        jsr l_gw_rect
        sec
        lda gr_x1
        sbc #20
        sta gr_x1
        bcs +
        dec gr_x1+1
+       sec
        lda gr_x1
        sbc #15
        sta gr_x0
        lda gr_x1+1
        sbc #0
        sta gr_x0+1
        jsr l_pt_in
        bcc _move
        ldx l_gu_ws
        jsr l_gw_minmax
        jsr gui_redraw
        clc
        rts
_move:  ldx l_gu_ws
        lda gw_flags,x
        and #GWF_MOVABLE
        beq l_gu_none
        stx l_gu_drag
        sec
        lda ev_x
        sbc gw_xl,x
        sta l_gu_offx
        lda ev_x+1
        sbc gw_xh,x
        sta l_gu_offx+1
        sec
        lda ev_y
        sbc gw_y,x
        sta l_gu_offy
        jsr l_drag_on                   ; the corner brackets, where it is now
        clc
        rts
_client:
        ldx l_gu_ws                     ; (minimized: its bottom edge, nothing there)
        lda gw_min,x
        beq +
        clc
        rts
+       lda l_gu_ws
        sta l_gd_ws
        jsr l_gg_at
        bcc _nog
        lda gg_flags,x
        and #GGF_DISABLED
        bne _nog
        lda gg_kind,x
        cmp #GK_BUTTON
        bne +
        stx l_gu_press
        jsr l_gui_draw_gad
        clc
        rts
+       cmp #GK_GRID
        bne +
        jsr l_gg_rect
        jmp l_gu_grid
+       cmp #GK_TEXT
        beq _text
        cmp #GK_PASSWORD
        beq _text
        cmp #GK_LIST
        beq _rows
        cmp #GK_EDIT
        beq _rows
        cmp #GK_DROP
        bne +
        jmp l_dd_open
+       cmp #GK_VIEW
        bne +
_rows:  jmp l_gu_rows
+       cmp #GK_CHECK
        beq _chk
        cmp #GK_RADIO
        bne _nog
        lda #1                          ; radio: on (the program turns the others off)
        bra _set
_chk:   lda gg_val,x                    ; check box: flips
        eor #1
_set:   sta gg_val,x
        sta ge_val
        lda #0
        sta ge_val+1
        phx
        jsr l_gui_draw_gad
        plx
        lda gg_id,x
        sta ge_gid
        ldy gg_win,x
        lda gw_id,y
        sta ge_win
        lda #GE_SELECT
        sta ge_type
        sec
        rts
_nog:   clc
        rts
_text:  ; the keyboard to this box, the cursor where it was clicked
        phx
        jsr l_gg_rect                   ; (x - x0 - 1) / 8 + scr, at most the length
        sec
        lda ev_x
        sbc gr_x0
        sta l_gu_t
        lda ev_x+1
        sbc gr_x0+1
        sta l_gu_t+1
        lsr l_gu_t+1
        ror l_gu_t
        lsr l_gu_t+1
        ror l_gu_t
        lsr l_gu_t+1
        ror l_gu_t
        plx
        clc
        lda l_gu_t
        adc gg_scr,x
        cmp gg_len,x
        bcc +
        lda gg_len,x
+       sta gg_cur,x
        ldy gg_win,x
        lda gw_id,y
        pha
        lda gg_id,x
        tax
        pla
        jsr gui_focus
        clc
        rts

l_gu_click:                             ; X = gadget slot: report a click on it
        lda gg_id,x
        sta ge_gid
        ldy gg_win,x
        lda gw_id,y
        sta ge_win
        lda #GE_CLICK
        sta ge_type
        sec
        rts

l_gu_up:
        ldx l_gu_press
        cpx #$ff
        beq _drag
        lda #$ff
        sta l_gu_press
        phx
        jsr l_gui_draw_gad
        plx
        jsr l_gg_rect
        jsr l_pt_in
        bcc _none
        jmp l_gu_click
_none:  clc
        rts
_drag:  ldx l_gu_drag
        cpx #$ff
        beq _none
        lda #$ff
        sta l_gu_drag
        phx
        jsr l_drag_hide                 ; the corner brackets go
        plx
        jsr l_drag_pos                  ; where it lands (as the brackets showed)
        lda l_gu_t                      ; moved at all?
        cmp gw_xl,x
        bne _mv
        lda l_gu_t+1
        cmp gw_xh,x
        bne _mv
        lda l_gu_t2
        cmp gw_y,x
        beq _none
_mv:    lda l_gu_t
        sta gw_xl,x
        lda l_gu_t+1
        sta gw_xh,x
        lda l_gu_t2
        sta gw_y,x
        jsr gui_redraw
        clc
        rts

;---------------------------------------------------------------------------------------
; dragging a window: four yellow corner brackets (hardware sprites GUI_FRAME_SPR .. +3)
; show where it will land; the window itself is drawn once, when it's dropped
;---------------------------------------------------------------------------------------
; window X dragged to the pointer: l_gu_t (word) / l_gu_t2 = its new x / y, kept on the
; screen and below the menu bar. X kept
l_drag_pos:
        sec                             ; x = pointer - offset, kept on the screen
        lda ev_x
        sbc l_gu_offx
        sta l_gu_t
        lda ev_x+1
        sbc l_gu_offx+1
        sta l_gu_t+1
        bpl +
        lda #0
        sta l_gu_t
        sta l_gu_t+1
+       sec                             ; most = 640 - width
        lda #<640
        sbc gw_wl,x
        sta l_gu_t2
        lda #>640
        sbc gw_wh,x
        sta l_gu_t2+1
        lda l_gu_t2
        cmp l_gu_t
        lda l_gu_t2+1
        sbc l_gu_t+1
        bcs +
        lda l_gu_t2
        sta l_gu_t
        lda l_gu_t2+1
        sta l_gu_t+1
+       sec                             ; y = pointer - offset, 0 .. 200 - height
        lda ev_y
        sbc l_gu_offy
        bcs +
        lda #0
+       sta l_gu_t2
        lda #200
        sec
        sbc gw_h,x
        cmp l_gu_t2
        bcs +
        sta l_gu_t2
+       lda gui_menubar                 ; not over the menu bar
        beq +
        lda l_gu_t2
        cmp #GUI_MENU_H
        bcs +
        lda #GUI_MENU_H
        sta l_gu_t2
+       rts

; the brackets at where window l_gu_drag would land now (once a frame while dragging)
l_drag_show:
        ldx l_gu_drag
        jsr l_drag_pos
        lda l_gu_t                      ; left = x / 2 (sprites are placed in 320 units)
        sta l_dg_l
        lda l_gu_t+1
        lsr
        ror l_dg_l
        clc                             ; right = (x + w - 1) / 2 - 15
        lda l_gu_t
        adc gw_wl,x
        sta l_dg_r
        lda l_gu_t+1
        adc gw_wh,x
        sta l_dg_r+1
        lda l_dg_r
        bne +
        dec l_dg_r+1
+       dec l_dg_r
        lsr l_dg_r+1
        ror l_dg_r
        sec
        lda l_dg_r
        sbc #15
        sta l_dg_r
        lda l_dg_r+1
        sbc #0
        sta l_dg_r+1
        lda l_gu_t2                     ; bottom = y + h - 12
        clc
        adc gw_h,x
        sec
        sbc #12
        sta l_dg_b
        ldx #0                          ; place the four
_s:     stx l_dg_i
        lda l_dg_xs,x                   ; left or right
        beq +
        lda l_dg_r
        ldy l_dg_r+1
        bra ++
+       lda l_dg_l
        ldy #0
+       sta hws_x
        sty hws_x+1
        lda l_dg_ys,x                   ; top or bottom
        beq +
        lda l_dg_b
        bra ++
+       lda l_gu_t2
+       sta hws_y
        lda #0
        sta hws_y+1
        txa
        clc
        adc #GUI_FRAME_SPR
        tax
        jsr hws_place
        ldx l_dg_i
        inx
        cpx #4
        bne _s
        rts
l_dg_xs:        .byte 0, 1, 0, 1        ; top left, top right, bottom left, bottom right
l_dg_ys:        .byte 0, 0, 1, 1

l_drag_on:
        jsr l_drag_show
        ldx #GUI_FRAME_SPR
-       phx
        jsr hws_on
        plx
        inx
        cpx #GUI_FRAME_SPR + 4
        bne -
        rts
l_drag_hide:
        ldx #GUI_FRAME_SPR
-       phx
        jsr hws_off
        plx
        inx
        cpx #GUI_FRAME_SPR + 4
        bne -
        rts
l_dg_l:         .word 0
l_dg_r:         .word 0
l_dg_b:         .byte 0
l_dg_i:         .byte 0

l_gu_key:
        lda ev_key
        sta ge_key
        jsr l_gw_front
        cmp #$ff
        beq _raw
        sta l_gu_ws
        tax
        lda gw_min,x                    ; minimized in front: its gadgets get no keys
        beq +
        jmp _raw
+       lda ev_key
        cmp #K_TAB
        bne +
        jmp l_gu_tab
+       ldy l_gu_ws                     ; a text area with the keyboard takes it all
        lda gw_focus,y
        cmp #$ff
        beq _nfe
        tax
        lda gg_kind,x
        cmp #GK_EDIT
        bne _nfe
        lda ev_key
        jsr l_ed_key
        bcc _used
        jmp _raw
_used:  rts
_nfe:   lda ev_key
        cmp #K_RETURN
        bne +
        jsr l_gu_default
        bcc +
        rts
+       ldy l_gu_ws
        lda gw_focus,y
        cmp #$ff
        beq _raw
        tax
        lda gg_kind,x
        cmp #GK_TEXT
        beq _edit
        cmp #GK_PASSWORD
        bne _raw
_edit:  jsr l_gu_edit
        bcs _raw
        rts                             ; (carry clear: used)
_raw:   lda #0                          ; not used here: the program's
        sta ge_win
        sta ge_gid
        jsr l_gw_front
        cmp #$ff
        beq _ev
        tax
        lda gw_id,x
        sta ge_win
        lda gw_focus,x
        cmp #$ff
        beq _ev
        tax
        lda gg_id,x
        sta ge_gid
_ev:    lda #GE_KEY
        sta ge_type
        sec
        rts

; RETURN: the front window's default button -> carry set and a GE_CLICK
l_gu_default:
        ldx #0
-       lda gg_win,x
        cmp l_gu_ws
        bne +
        lda gg_kind,x
        cmp #GK_BUTTON
        bne +
        lda gg_flags,x
        and #GGF_DEFAULT
        beq +
        lda gg_flags,x
        and #GGF_DISABLED
        bne +
        jmp l_gu_click
+       inx
        cpx #GUI_MAXGAD
        bne -
        clc
        rts

; TAB: the keyboard to the window's next text box
l_gu_tab:
        ldy l_gu_ws
        lda gw_focus,y
        tax
        ldy #GUI_MAXGAD
_n:     inx
        cpx #GUI_MAXGAD
        bcc +
        ldx #0
+       lda gg_win,x
        cmp l_gu_ws
        bne _skip
        lda gg_flags,x                  ; (not a greyed-out one)
        and #GGF_DISABLED
        bne _skip
        lda gg_kind,x
        cmp #GK_TEXT
        beq _got
        cmp #GK_EDIT
        beq _got
        cmp #GK_PASSWORD
        beq _got
_skip:  dey
        bne _n
        clc
        rts
_got:   ldy l_gu_ws
        lda gw_id,y
        pha
        lda gg_id,x
        tax
        pla
        jsr gui_focus
        clc
        rts

; edit text box X with ev_key. Carry set: not an editing key
l_gu_edit:
        lda l_gtb_lo,x
        sta txt_ptr
        lda l_gtb_hi,x
        sta txt_ptr+1
        lda ev_key
        cmp #K_DEL
        beq _bs
        cmp #K_LEFT
        beq _left
        cmp #K_RIGHT
        beq _right
        cmp #K_HOME
        beq _home
        cmp #32
        bcc _not
        cmp #127
        bcs _not
        lda gg_len,x                    ; insert at the cursor
        cmp gg_max,x
        bcs _done
        tay
-       lda (txt_ptr),y                 ; move cur .. len (with the 0) up one
        iny
        sta (txt_ptr),y
        dey
        tya
        cmp gg_cur,x
        beq +
        dey
        bra -
+       lda ev_key
        sta (txt_ptr),y
        inc gg_len,x
        inc gg_cur,x
        bra _done
_bs:    lda gg_cur,x
        beq _done
        tay
        dey
-       iny                             ; move cur .. len down one
        lda (txt_ptr),y
        dey
        sta (txt_ptr),y
        iny
        tya
        cmp gg_len,x
        bne -
        dec gg_len,x
        dec gg_cur,x
        bra _done
_left:  lda gg_cur,x
        beq _done
        dec gg_cur,x
        bra _done
_right: lda gg_cur,x
        cmp gg_len,x
        bcs _done
        inc gg_cur,x
        bra _done
_home:  lda #0
        sta gg_cur,x
_done:  phx
        jsr l_gg_redraw
        plx
        jsr l_gg_needs
        clc
        rts
_not:   sec
        rts

;=======================================================================================
; lists and text views: rows in bank 1 (GUI_BIG_MEM + block * 8 KB)
;=======================================================================================
; A = row, Y = block, l_gb_sh = 6 (view: 64-byte lines) lists and drop-downs too -> ptr2. Y kept
l_gb_row:
        sta ptr2
        lda #0
        sta ptr2+1
        ldx l_gb_sh
-       asl ptr2
        rol ptr2+1
        dex
        bne -
        tya                             ; + block * 8 KB: (block & 7) * $2000 into the
        lsr                             ; middle byte, block >> 3 into the bank byte
        lsr                             ; (more than 8 blocks: GUI_MAXBIG up to 255)
        lsr
        sta l_gb_bank
        tya
        and #7
        asl
        asl
        asl
        asl
        asl
        clc
        adc ptr2+1                      ; (row * 64 < $2000: no carry out)
        sta ptr2+1
        clc
        lda ptr2
        adc #<GUI_BIG_MEM
        sta ptr2
        lda ptr2+1
        adc #>GUI_BIG_MEM
        sta ptr2+1
        lda #(GUI_BIG_MEM >> 16) & $ff
        adc l_gb_bank
        sta ptr2+2
        lda #GUI_BIG_MEM >> 24
        sta ptr2+3
        rts

; row A of block Y -> l_gb_line (zero-terminated)
l_gb_get:
        jsr l_gb_row
        ldx #0
        ldz #0
-       lda [ptr2],z
        sta l_gb_line,x
        beq +
        inx
        inz
        cpx #63
        bne -
        lda #0
        sta l_gb_line,x
+       rts

; l_gb_e characters of txt_ptr from index l_gb_p -> row A of block Y
l_gb_store:
        jsr l_gb_row
        ldy l_gb_p
        ldz #0
        ldx l_gb_e
        beq +
-       lda (txt_ptr),y
        sta [ptr2],z
        iny
        inz
        dex
        bne -
+       lda #0
        sta [ptr2],z
        rts

; l_gb_line on screen row l_gb_e of gr (gt_fg / gt_bg set)
l_gb_text:
        jsr l_gb_rowy
        clc
        lda gr_x0
        adc #1
        sta gt_x
        lda gr_x0+1
        adc #0
        sta gt_x+1
        lda #<l_gb_line
        sta txt_ptr
        lda #>l_gb_line
        sta txt_ptr+1
        lda #$ff
        sta gt_n
        lda #0
        sta gt_pw
        jmp gui_text
; gt_y = gr_y0 + 1 + l_gb_e * 8
l_gb_rowy:
        lda l_gb_e
        asl
        asl
        asl
        sec
        adc gr_y0
        sta gt_y
        rts

; draw a list or text view (gadget l_gd_gs, gr = its rectangle): a scroll bar on the
; right, the rows from gb_top
l_gd_rows:
        jsr l_gd_sunken
        lda #GC_WHITE
        jsr l_gd_fill
        ldx l_gd_gs
        ldy gg_big,x
        cpy #$ff
        bne +
        rts
+       sty l_gb_t
        jsr l_gb_vlcalc
        jsr l_sb_draw
        sec                             ; the rows: left of the scroll bar
        lda gr_x1
        sbc #GUI_SB_W
        sta gr_x1
        bcs +
        dec gr_x1+1
+       jsr l_gd_clip
        lda #0
        sta l_gb_e
        ldy l_gb_t
        lda gb_top,y
        sta l_gb_k
        ldx l_gd_gs
        lda gg_kind,x
        cmp #GK_LIST
        bne +
        jmp _list
+       cmp #GK_EDIT
        bne +
        jmp _edit
+       lda #6
        sta l_gb_sh
_vl:    ldy l_gb_t
        lda l_gb_e
        cmp l_gb_vl
        bcs _done
        lda l_gb_k
        cmp gb_n,y
        bcs _done
        lda gb_head,y                   ; ring row = (head - n + k) & 127
        sec
        sbc gb_n,y
        clc
        adc l_gb_k
        and #GUI_VIEW_LINES - 1
        jsr l_gb_get
        lda #GC_BLACK
        sta gt_fg
        lda #$ff
        sta gt_bg
        jsr l_gb_text
        inc l_gb_k
        inc l_gb_e
        bra _vl
_done:  jmp d6_clip_all
_edit:  lda #6                          ; a text area: lines from the scroll position
        sta l_gb_sh
_er:    ldy l_gb_t
        lda l_gb_e
        cmp l_gb_vl
        bcs _caret
        lda l_gb_k
        cmp gb_n,y
        bcs _caret
        jsr l_gb_get
        lda #GC_BLACK
        sta gt_fg
        lda #$ff
        sta gt_bg
        jsr l_gb_text
        inc l_gb_k
        inc l_gb_e
        bra _er
_caret: ldx l_gd_gs                     ; the cursor, if it has the keyboard
        ldy gg_win,x
        lda gw_focus,y
        cmp l_gd_gs
        bne _cdone
        jsr l_gw_front
        ldx l_gd_gs
        cmp gg_win,x
        bne _cdone
        ldy l_gb_t
        lda gb_row,y
        sec
        sbc gb_top,y
        bcc _cdone
        cmp l_gb_vl
        bcs _cdone
        sta l_gb_e
        jsr l_gb_rowy
        lda gb_col,y
        sta l_gu_t
        lda #0
        sta l_gu_t+1
        asl l_gu_t
        rol l_gu_t+1
        asl l_gu_t
        rol l_gu_t+1
        asl l_gu_t
        rol l_gu_t+1
        sec                             ; x0 + 1 + column * 8
        lda gr_x0
        adc l_gu_t
        sta d6_x
        sta d6_x1
        lda gr_x0+1
        adc l_gu_t+1
        sta d6_x+1
        sta d6_x1+1
        lda gt_y
        sta d6_y
        clc
        adc #7
        sta d6_y1
        lda #0
        sta d6_y+1
        sta d6_y1+1
        lda #GC_BLACK
        sta d6_col
        jsr d6_fill
_cdone: jmp d6_clip_all
_list:  lda #6
        sta l_gb_sh
_lr:    ldy l_gb_t
        lda l_gb_e
        cmp l_gb_vl
        bcs _done
        lda l_gb_k
        cmp gb_n,y
        bcs _done
        jsr l_gb_get
        ldy l_gb_t
        lda #GC_BLACK
        sta gt_fg
        lda #$ff
        sta gt_bg
        lda l_gb_k
        cmp gb_sel,y
        bne _ln
        jsr l_gb_rowy                   ; the selection: white on navy
        lda gr_x0
        sta d6_x
        lda gr_x0+1
        sta d6_x+1
        lda gr_x1
        sta d6_x1
        lda gr_x1+1
        sta d6_x1+1
        lda gt_y
        sta d6_y
        clc
        adc #7
        sta d6_y1
        lda #0
        sta d6_y+1
        sta d6_y1+1
        lda #GC_TITLE
        sta d6_col
        jsr d6_fill
        lda #GC_WHITE
        sta gt_fg
_ln:    jsr l_gb_text
        inc l_gb_k
        inc l_gb_e
        bra _lr

; l_gb_vl = rows that fit in gr (the inside of a list / view): (height - 2) / 8
l_gb_vlcalc:
        sec
        lda gr_y1
        sbc gr_y0
        sec
        sbc #1
        bcs +
        lda #0
+       lsr
        lsr
        lsr
        bne +
        lda #1
+       sta l_gb_vl
        rts
; l_gb_vl for gadget X from its height (no gr needed): (h - 6) / 8
l_gb_vlgad:
        lda gg_h,x
        sec
        sbc #6
        bcs +
        lda #0
+       lsr
        lsr
        lsr
        bne +
        lda #1
+       sta l_gb_vl
        rts
; A = the furthest block Y can scroll: n - vl, or 0
l_gb_maxtop:
        lda gb_n,y
        sec
        sbc l_gb_vl
        bcs +
        lda #0
+       rts

; A * X / Y (8 bits each, Y > 0) -> A, on the hardware multiplier and divider
l_muldiv:
        sta MULTINA
        stx MULTINB
        lda #0
        sta MULTINA+1
        sta MULTINA+2
        sta MULTINA+3
        sta MULTINB+1
        sta MULTINB+2
        sta MULTINB+3
        lda MULTOUT                     ; (the product, before the inputs change)
        ldx MULTOUT+1
        sta MULTINA
        stx MULTINA+1
        sty MULTINB
-       bit DIVBUSY
        bmi -
        lda DIVOUT+4
        rts

; the scroll bar's geometry, for block Y in gr (the inside) with l_gb_vl rows:
; sb_x0, the track sb_ty0..sb_ty1, the thumb sb_t0..sb_t1 (sb_has = 0: everything fits).
; Y = l_gb_t afterwards
l_sb_geom:
        sec
        lda gr_x1
        sbc #GUI_SB_W - 1
        sta sb_x0
        lda gr_x1+1
        sbc #0
        sta sb_x0+1
        clc
        lda gr_y0
        adc #9
        sta sb_ty0
        sec
        lda gr_y1
        sbc #9
        sta sb_ty1
        lda #0
        sta sb_has
        lda l_gb_vl
        cmp gb_n,y
        bcs _out                        ; vl >= n: it all fits
        sec                             ; the track's height
        lda sb_ty1
        sbc sb_ty0
        bcc _out
        inc a
        sta sb_th
        lda gb_n,y                      ; the thumb: th * vl / n, 6 .. th
        sta l_sb_n
        tay
        lda sb_th
        ldx l_gb_vl
        jsr l_muldiv
        cmp #6
        bcs +
        lda #6
+       cmp sb_th
        bcc +
        lda sb_th
+       sta sb_thh
        ldy l_gb_t                      ; where: (th - thh) * top / (n - vl)
        lda l_sb_n
        sec
        sbc l_gb_vl
        sta l_sb_rng
        lda sb_th
        sec
        sbc sb_thh
        sta l_sb_room
        ldx gb_top,y
        ldy l_sb_rng
        jsr l_muldiv
        cmp l_sb_room
        bcc +
        lda l_sb_room
+       clc
        adc sb_ty0
        sta sb_t0
        clc
        adc sb_thh
        sta sb_t1
        dec sb_t1
        lda #1
        sta sb_has
_out:   ldy l_gb_t
        rts

; draw the scroll bar of block l_gb_t at the right of gr (gr kept)
l_sb_draw:
        ldx #7
-       lda gr_x0,x
        sta l_sb_save,x
        dex
        bpl -
        ldy l_gb_t
        jsr l_sb_geom
        lda sb_x0                       ; the track
        sta gr_x0
        lda sb_x0+1
        sta gr_x0+1
        lda #GC_LIGHT
        jsr l_gd_fill
        lda l_sb_save+2                 ; the up button: top 9 rows
        sta gr_y0
        clc
        adc #8
        sta gr_y1
        jsr l_sb_button
        lda l_sb_save+2
        ldx #0
        jsr l_sb_arrow
        lda l_sb_save+6                 ; the down button: bottom 9 rows
        sta gr_y1
        sec
        sbc #8
        sta gr_y0
        jsr l_sb_button
        lda l_sb_save+6
        sec
        sbc #8
        ldx #1
        jsr l_sb_arrow
        lda sb_has                      ; the thumb
        beq +
        lda sb_t0
        sta gr_y0
        lda sb_t1
        sta gr_y1
        jsr l_sb_button
+       ldx #7
-       lda l_sb_save,x
        sta gr_x0,x
        dex
        bpl -
        rts
; a raised square on gr's rows (x from sb_x0 to the saved x1)
l_sb_button:
        lda sb_x0
        sta gr_x0
        lda sb_x0+1
        sta gr_x0+1
        lda l_sb_save+4
        sta gr_x1
        lda l_sb_save+5
        sta gr_x1+1
        lda #0
        sta gr_y0+1
        sta gr_y1+1
        jsr l_gd_raised
        lda #GC_FACE
        jmp l_gd_fill
; a small triangle in the button whose top row is A: X = 0 up, 1 down (grey when there's
; nothing to scroll)
l_sb_arrow:
        clc
        adc #3
        sta l_sb_ay
        stx l_sb_dir
        ldy #GC_BLACK
        lda sb_has
        bne +
        ldy #GC_SHADOW
+       sty d6_col
        ldx #0
_r:     phx
        stx l_sb_i
        clc                             ; x: centre - i .. centre + i
        lda sb_x0
        adc #5
        sta l_sb_cx
        lda sb_x0+1
        adc #0
        sta l_sb_cx+1
        sec
        lda l_sb_cx
        sbc l_sb_i
        sta d6_x
        lda l_sb_cx+1
        sbc #0
        sta d6_x+1
        clc
        lda l_sb_cx
        adc l_sb_i
        sta d6_x1
        lda l_sb_cx+1
        adc #0
        sta d6_x1+1
        lda l_sb_dir                    ; y: row i (up) or 2 - i (down)
        beq _upr
        lda #2
        sec
        sbc l_sb_i
        bra _y
_upr:   lda l_sb_i
_y:     clc
        adc l_sb_ay
        sta d6_y
        sta d6_y1
        lda #0
        sta d6_y+1
        sta d6_y1+1
        jsr d6_fill
        plx
        inx
        cpx #3
        bne _r
        rts

; a click in list or text view X (gr = its rectangle): the scroll bar scrolls it; a list
; row is selected
l_gu_rows:
        ldy gg_big,x
        cpy #$ff
        beq _none
        stx l_gu_t2
        sty l_gb_t
        jsr l_gd_shrink
        jsr l_gd_shrink
        jsr l_gb_vlcalc
        sec                             ; left of the scroll bar: the rows
        lda gr_x1
        sbc #GUI_SB_W - 1
        sta l_gu_t
        lda gr_x1+1
        sbc #0
        sta l_gu_t+1
        lda ev_x
        cmp l_gu_t
        lda ev_x+1
        sbc l_gu_t+1
        bcc _rows
        ldy l_gb_t
        jsr l_sb_geom
        lda gr_y0                       ; the up button
        clc
        adc #8
        cmp ev_y
        bcs _up
        lda gr_y1                       ; the down button
        sec
        sbc #8
        cmp ev_y
        bcc _down
        beq _down
        lda sb_has                      ; the track: a page at a time
        beq _none
        lda ev_y
        cmp sb_t0
        bcc _pgup
        lda sb_t1
        cmp ev_y
        bcc _pgdn
_none:  clc                             ; (the thumb: dragging it isn't done yet)
        rts
_rows:  ldx l_gu_t2
        lda gg_kind,x
        cmp #GK_EDIT
        bne +
        jmp l_ed_click
+       cmp #GK_LIST
        bne _none
        jsr l_gg_rect
        jmp l_gu_list
_up:    lda #1
        bra _dec
_pgup:  lda l_gb_vl
_dec:   sta l_sb_i
        ldy l_gb_t
        lda gb_top,y
        sec
        sbc l_sb_i
        bcs _set
        lda #0
        bra _set
_down:  lda #1
        bra _inc
_pgdn:  lda l_gb_vl
_inc:   ldy l_gb_t
        clc
        adc gb_top,y
        sta l_sb_i
        jsr l_gb_maxtop
        cmp l_sb_i
        bcc _set
        lda l_sb_i
_set:   ldy l_gb_t
        cmp gb_top,y
        beq _none
        sta gb_top,y
        ldx l_gu_t2
        jsr l_gui_draw_gad
        clc
        rts

sb_x0:          .word 0
sb_ty0:         .byte 0
sb_ty1:         .byte 0
sb_th:          .byte 0
sb_thh:         .byte 0
sb_t0:          .byte 0
sb_t1:          .byte 0
sb_has:         .byte 0
l_sb_n:         .byte 0
l_sb_rng:       .byte 0
l_sb_room:      .byte 0
l_sb_save:      .fill 8
l_sb_ay:        .byte 0
l_sb_dir:       .byte 0
l_sb_i:         .byte 0
l_sb_cx:        .word 0

; gp_win, gp_gid, gp_w = how many rows the list has now (rows past it go)
gui_list_total:
        lda gp_win
        ldx gp_gid
        jsr l_gg_find
        bcs _out
        ldy gg_big,x
        cpy #$ff
        beq _out
        lda gp_w+1
        bne _max
        lda gp_w
        cmp #GUI_LIST_ROWS
        bcc +
_max:   lda #GUI_LIST_ROWS
+       sta gb_n,y
        lda gb_sel,y                    ; a selection past the end goes
        cmp gb_n,y
        bcc +
        lda #$ff
        sta gb_sel,y
+       jsr l_gb_vlgad                  ; the scroll no further than the end
        jsr l_gb_maxtop
        cmp gb_top,y
        bcs _out
        sta gb_top,y
_out:   rts

; gp_win, gp_gid, gp_x = row, txt_ptr = its text (up to 63 characters). Doesn't draw
gui_list_row:
        lda gp_x+1
        bne _out
        lda gp_x
        cmp #GUI_LIST_ROWS
        bcs _out
        lda gp_win
        ldx gp_gid
        jsr l_gg_find
        bcs _out
        ldy gg_big,x
        cpy #$ff
        beq _out
        sty l_gb_t
        lda gb_n,y                      ; the list reaches at least this row
        cmp gp_x
        beq +
        bcs ++
+       lda gp_x
        inc a
        sta gb_n,y
+       ldy #0                          ; length, at most 63
-       lda (txt_ptr),y
        beq +
        iny
        cpy #63
        bne -
+       sty l_gb_e
        lda #0
        sta l_gb_p
        lda #6
        sta l_gb_sh
        ldy l_gb_t
        lda gp_x
        jmp l_gb_store
_out:   rts

; A = window, X = gadget, txt_ptr = a line for the text view: word-wrapped to its width,
; the oldest lines dropped past 128. Redrawn; if it was scrolled to the bottom it stays there
gui_view_append:
        jsr l_gg_find
        bcc +
        rts
+       ldy gg_big,x
        cpy #$ff
        bne +
        rts
+       lda gg_kind,x                   ; a text area: a line at its end
        cmp #GK_EDIT
        bne +
        jmp l_ed_append
+       sty l_gb_t
        stx l_gu_t2
        jsr l_gb_vlgad                  ; at the bottom now? then it follows the new lines
        lda #0
        sta l_gb_fol
        lda gb_n,y
        sec
        sbc gb_top,y
        cmp l_gb_vl
        beq +
        bcs ++
+       inc l_gb_fol
+       ldy gg_win,x                    ; (not on screen yet, as when a window is filled
        lda gw_shown,y                  ; before it's shown: it opens at the top)
        bne +
        lda #0
        sta l_gb_fol
+       ldy l_gb_t
        sec                             ; width: (w - 6 - scroll bar) / 8, 1 .. 63
        lda gg_wl,x
        sbc #6 + GUI_SB_W
        sta l_gu_t
        lda gg_wh,x
        sbc #0
        lsr
        ror l_gu_t
        lsr
        ror l_gu_t
        lsr
        ror l_gu_t
        lda l_gu_t
        cmp #63
        bcc +
        lda #63
+       cmp #1
        bcs +
        lda #1
+       sta l_gb_w
        lda #6
        sta l_gb_sh
        lda #0
        sta l_gb_p
_line:  ldy l_gb_p                      ; up to a width of characters
        ldx #0
-       lda (txt_ptr),y
        beq _short
        inx
        iny
        cpx l_gb_w
        bne -
        lda (txt_ptr),y                 ; exactly a width left: the last line
        beq _short
-       dey                             ; break at the last space
        cpy l_gb_p
        beq _hard
        lda (txt_ptr),y
        cmp #' '
        bne -
        tya
        sec
        sbc l_gb_p
        sta l_gb_e
        iny
        sty l_gb_k
        bra _store
_hard:  lda l_gb_w                      ; no space: cut it
        sta l_gb_e
        clc
        lda l_gb_p
        adc l_gb_w
        sta l_gb_k
        bra _store
_short: stx l_gb_e
        lda #$ff
        sta l_gb_k
        cpx #0                          ; nothing left after a wrap: done
        bne _store
        lda l_gb_p
        bne _drawit
_store: ldy l_gb_t
        lda gb_head,y
        jsr l_gb_store
        ldy l_gb_t
        lda gb_head,y
        inc a
        and #GUI_VIEW_LINES - 1
        sta gb_head,y
        lda gb_n,y
        cmp #GUI_VIEW_LINES
        bcs _drop
        inc a
        sta gb_n,y
        bra +
_drop:  lda gb_top,y                    ; full: the oldest line went, so did a row of scroll
        beq +
        dec a
        sta gb_top,y
+       lda l_gb_k
        cmp #$ff
        beq _drawit
        sta l_gb_p
        bra _line
_drawit:
        lda l_gb_fol                    ; following: show the newest lines
        beq +
        ldy l_gb_t
        jsr l_gb_maxtop
        sta gb_top,y
+       ldx l_gu_t2
        jmp l_gg_later
l_gb_fol:       .byte 0

; a click in list X (gr = its rectangle): select the row -> GE_SELECT
l_gu_list:
        ldy gg_big,x
        cpy #$ff
        beq _none
        sty l_gb_t
        stx l_gu_t2
        sec                             ; row = (y - y0 - 3) / 8 + top
        lda ev_y
        sbc gr_y0
        sec
        sbc #3
        bcs +
        lda #0
+       lsr
        lsr
        lsr
        clc
        adc gb_top,y
        cmp gb_n,y
        bcs _none
        sta l_gb_k
        lda #0
        sta ge_val+1
        lda l_gb_k                      ; the same row again within half a second: double
        cmp gb_sel,y
        bne _one
        lda frame_count
        sec
        sbc gb_clk,y
        cmp #25
        bcs _one
        lda #$80
        sta ge_val+1
_one:   lda frame_count
        sta gb_clk,y
        lda l_gb_k
        sta gb_sel,y
        sta ge_val
        ldx l_gu_t2
        jsr l_gui_draw_gad
        ldx l_gu_t2
        lda gg_id,x
        sta ge_gid
        ldy gg_win,x
        lda gw_id,y
        sta ge_win
        lda #GE_SELECT
        sta ge_type
        sec
        rts
_none:  clc
        rts

;=======================================================================================
; the menu bar (Windows 95 style): titles across the top, a drop-down under each, and
; the built-in Window menu (the open windows, front first: picking one brings it forward)
;=======================================================================================
gui_menu_clear:
        lda #0
        sta mn_n
        rts

; gp_gid = id, gp_win = parent (0: a title on the bar), gp_text = label ("-" = a line)
gui_menu_add:
        ldx mn_n
        cpx #GUI_MAXMENU
        bcs _full
        lda gp_gid
        sta mn_id,x
        lda gp_win
        sta mn_par,x
        lda l_mnt_lo,x
        sta tmp6
        lda l_mnt_hi,x
        sta tmp6+1
        lda gp_text
        sta txt_ptr
        lda gp_text+1
        sta txt_ptr+1
        ldy #0
-       lda (txt_ptr),y
        cpy #GUI_MENULEN - 1
        bcc +
        lda #0
+       sta (tmp6),y
        beq +
        iny
        bra -
+       inc mn_n
_full:  rts

; txt_ptr = menu entry X's label
l_mn_text:
        lda l_mnt_lo,x
        sta txt_ptr
        lda l_mnt_hi,x
        sta txt_ptr+1
        rts

; lay out the titles: mt_* (the titles below gui_menu_late, Window, then the late ones)
l_mn_layout:
        lda #0
        sta mt_n
        sta l_mn_pass
        lda #8
        sta l_gu_t
        lda #0
        sta l_gu_t+1
_pass:  ldx #0
_e:     cpx mn_n
        beq _end
        lda mn_par,x
        bne _ne
        lda gui_menu_late               ; late: late != 0 and id - late < 16
        beq _early
        lda mn_id,x
        sec
        sbc gui_menu_late
        cmp #16
        bcs _early
        lda #1
        bra _cmp
_early: lda #0
_cmp:   cmp l_mn_pass
        bne _ne
        phx
        jsr l_mn_text
        ldy mt_n
        txa
        sta mt_idx,y
        jsr l_mn_place
        plx
_ne:    inx
        bra _e
_end:   lda l_mn_pass
        bne _done
        inc l_mn_pass
        lda #GUI_WINMENU
        beq _pass
        lda #<s_gui_window
        sta txt_ptr
        lda #>s_gui_window
        sta txt_ptr+1
        ldy mt_n
        lda #$ff
        sta mt_idx,y
        jsr l_mn_place
        bra _pass
_done:  rts
; title Y (txt_ptr = its text) at l_gu_t: width = length * 8 + 16
l_mn_place:
        cpy #GUI_MAXTITLE
        bcc +
        rts
+       lda l_gu_t
        sta mt_x0l,y
        lda l_gu_t+1
        sta mt_x0h,y
        phy
        jsr l_gd_strlen
        ply
        asl
        asl
        asl
        clc
        adc #16
        clc
        adc l_gu_t
        sta l_gu_t
        bcc +
        inc l_gu_t+1
+       sec
        lda l_gu_t
        sbc #1
        sta mt_x1l,y
        lda l_gu_t+1
        sbc #0
        sta mt_x1h,y
        inc mt_n
        rts

; draw the bar (and the open drop-down)
l_mn_draw:
        lda gui_menubar
        bne +
        rts
+       jsr l_mn_layout
        jsr d6_clip_all
        lda #0
        sta gr_x0
        sta gr_x0+1
        sta gr_y0
        sta gr_y0+1
        sta gr_y1+1
        lda #<639
        sta gr_x1
        lda #>639
        sta gr_x1+1
        lda #GUI_MENU_H - 2
        sta gr_y1
        lda #GC_FACE
        jsr l_gd_fill
        lda #GUI_MENU_H - 1             ; a line under it
        sta gr_y0
        sta gr_y1
        lda #GC_SHADOW
        jsr l_gd_fill
        ldy #0
_t:     cpy mt_n
        beq _drop
        phy
        jsr l_mn_title
        ply
        iny
        bra _t
_drop:  jsr l_nt_all                     ; the notification icons at the right
        lda l_mn_open
        cmp #$ff
        beq +
        jmp l_md_draw
+       rts

; draw title Y (highlighted if it's the open one)
l_mn_title:
        lda mt_x0l,y
        sta gr_x0
        lda mt_x0h,y
        sta gr_x0+1
        lda mt_x1l,y
        sta gr_x1
        lda mt_x1h,y
        sta gr_x1+1
        lda #0
        sta gr_y0
        sta gr_y0+1
        sta gr_y1+1
        lda #GUI_MENU_H - 2
        sta gr_y1
        ldx #GC_BLACK
        tya
        cmp l_mn_open
        bne +
        phy
        lda #GC_TITLE
        jsr l_gd_fill
        ply
        ldx #GC_WHITE
+       stx gt_fg
        lda #$ff
        sta gt_bg
        sta gt_n
        lda #0
        sta gt_pw
        lda #1
        sta gt_y
        clc
        lda gr_x0
        adc #8
        sta gt_x
        lda gr_x0+1
        adc #0
        sta gt_x+1
        lda mt_idx,y
        cmp #$ff
        bne +
        lda #<s_gui_window
        sta txt_ptr
        lda #>s_gui_window
        sta txt_ptr+1
        jmp gui_text
+       tax
        jsr l_mn_text
        jmp gui_text

; open title A: collect its items, size the drop-down
l_md_open:
        sta l_mn_open
        lda #$ff
        sta l_md_hov
        lda #0
        sta md_n
        lda #80                         ; the widest label (in pixels), at least 80
        sta md_w
        ldy l_mn_open
        lda mt_idx,y
        cmp #$ff
        beq _wins
        tax
        lda mn_id,x                     ; the title's items, in order
        sta l_gu_t2
        ldx #0
-       cpx mn_n
        beq _size
        lda mn_par,x
        cmp l_gu_t2
        bne +
        txa
        jsr l_md_item
+       inx
        bra -
_wins:  ldy gw_n                        ; the open windows, front first
-       dey
        bmi _size
        lda gw_z,y
        ora #$80
        phy
        jsr l_md_item
        ply
        bra -
_size:  lda md_n                        ; nothing in it (Window with no windows open):
        bne +                           ; it doesn't open
        lda #$ff
        sta l_mn_open
        rts
+       ldy l_mn_open                   ; x from the title, kept on the screen
        lda mt_x0l,y
        sta md_x0
        lda mt_x0h,y
        sta md_x0+1
        clc
        lda md_w
        adc #24
        sta md_w
        clc
        lda md_x0
        adc md_w
        sta md_x1
        lda md_x0+1
        adc #0
        sta md_x1+1
        lda md_x1+1                     ; past 639: move it left
        cmp #>640
        bcc +
        lda md_x1
        cmp #<640
        bcc +
        sec
        lda #<639
        sta md_x1
        sbc md_w
        sta md_x0
        lda #>639
        sta md_x1+1
        sbc #0
        sta md_x0+1
+       lda md_n                        ; height: 10 a row + 4
        asl
        sta md_y1
        asl
        asl
        clc
        adc md_y1
        adc #GUI_MENU_H + 3
        sta md_y1
        rts

; add item A (a menu entry, or $80 + window slot) to the drop-down; md_w widens to fit
l_md_item:
        ldy md_n
        cpy #GUI_MAXDROP
        bcs _out
        sta md_item,y
        inc md_n
        phx
        jsr l_md_label
        jsr l_gd_strlen
        plx
        asl
        asl
        asl
        bcs _wide
        cmp md_w
        bcc _out
        sta md_w
_out:   rts
_wide:  lda #255
        sta md_w
        rts
; txt_ptr = the label of drop-down item A
l_md_label:
        ora #0                          ; (the flags from A, whatever the caller did last)
        bpl +
        and #$7f
        tax
        lda l_gwt_lo,x
        sta txt_ptr
        lda l_gwt_hi,x
        sta txt_ptr+1
        rts
+       tax
        jmp l_mn_text

; draw the open drop-down
l_md_draw:
        jsr d6_clip_all
        jsr l_md_rect
        jsr l_gd_raised
        lda #GC_FACE
        jsr l_gd_fill
        lda #0
        sta l_gu_t2
_i:     lda l_gu_t2
        cmp md_n
        beq _done
        jsr l_md_row
        inc l_gu_t2
        bra _i
_done:  rts
; gr = the drop-down's rectangle
l_md_rect:
        lda md_x0
        sta gr_x0
        lda md_x0+1
        sta gr_x0+1
        lda md_x1
        sta gr_x1
        lda md_x1+1
        sta gr_x1+1
        lda #GUI_MENU_H
        sta gr_y0
        lda md_y1
        sta gr_y1
        lda #0
        sta gr_y0+1
        sta gr_y1+1
        rts
; draw row A of the drop-down
l_md_row:
        sta l_md_r
        clc                             ; gr = the row: x0 + 3 .. x1 - 3, y = top + 2 + 10 row
        lda md_x0
        adc #3
        sta gr_x0
        lda md_x0+1
        adc #0
        sta gr_x0+1
        sec
        lda md_x1
        sbc #3
        sta gr_x1
        lda md_x1+1
        sbc #0
        sta gr_x1+1
        lda l_md_r
        asl
        sta gr_y0
        asl
        asl
        clc
        adc gr_y0
        adc #GUI_MENU_H + 2
        sta gr_y0
        clc
        adc #9
        sta gr_y1
        lda #0
        sta gr_y0+1
        sta gr_y1+1
        ldy l_md_r
        lda md_item,y
        jsr l_md_label
        ldy #0                          ; "-": a separator
        lda (txt_ptr),y
        cmp #'-'
        bne _text
        iny
        lda (txt_ptr),y
        bne _text
        lda #GC_FACE
        jsr l_gd_fill
        lda gr_y0
        clc
        adc #4
        sta gr_y0
        sta gr_y1
        lda #GC_SHADOW
        jmp l_gd_fill
_text:  ldx #GC_BLACK
        lda #GC_FACE
        ldy l_md_r
        cpy l_md_hov
        bne +
        ldx #GC_WHITE
        lda #GC_TITLE
+       stx gt_fg
        jsr l_gd_fill                   ; (fills don't touch txt_ptr)
        lda #$ff
        sta gt_bg
        sta gt_n
        lda #0
        sta gt_pw
        clc
        lda gr_x0
        adc #9
        sta gt_x
        lda gr_x0+1
        adc #0
        sta gt_x+1
        lda gr_y0
        inc a
        sta gt_y
        jmp gui_text

; the drop-down row under the pointer -> A ($ff none)
l_md_at:
        jsr l_md_rect
        jsr l_pt_in
        bcc _no
        sec
        lda ev_y
        sbc #GUI_MENU_H + 2
        bcc _no
        ldx #0
-       cmp #10
        bcc +
        sbc #10
        inx
        bra -
+       cpx md_n
        bcs _no
        txa
        rts
_no:    lda #$ff
        rts

; the bar title under the pointer -> A ($ff none)
l_mn_at:
        lda ev_y
        cmp #GUI_MENU_H
        bcs _no
        ldy #0
-       cpy mt_n
        beq _no
        lda ev_x
        cmp mt_x0l,y
        lda ev_x+1
        sbc mt_x0h,y
        bcc +
        lda mt_x1l,y
        cmp ev_x
        lda mt_x1h,y
        sbc ev_x+1
        bcc +
        tya
        rts
+       iny
        bra -
_no:    lda #$ff
        rts

; gui_update while a drop-down is open. Carry set = an event (GE_MENU)
l_mn_update:
        jsr l_md_at                     ; the row under the pointer, lit
        ldx ev_type
        cpx #EV_KEY
        bne +
        lda l_md_hov                    ; (keys move it instead)
+       cmp l_md_hov
        beq +
        sta l_md_hov
        jsr l_md_draw
+       lda ev_type
        cmp #EV_DOWN
        beq _down
        cmp #EV_UP
        beq _up
        cmp #EV_KEY
        beq _key
        clc
        rts
_down:  jsr l_mn_at                     ; another title: that menu instead
        cmp #$ff
        beq +
        cmp l_mn_open
        beq _close                      ; the same title: shut it
        jsr l_md_open
        jsr gui_redraw
        clc
        rts
+       jsr l_md_at                     ; inside: wait for the release
        cmp #$ff
        bne _none
_close: lda #$ff                        ; anywhere else: shut (the click goes nowhere)
        sta l_mn_open
        jsr gui_redraw
_none:  clc
        rts
_up:    lda l_md_hov
        cmp #$ff
        beq _none
_pick:  tay                             ; a separator does nothing
        lda md_item,y
        pha
        jsr l_md_label
        ldy #0
        lda (txt_ptr),y
        cmp #'-'
        bne +
        iny
        lda (txt_ptr),y
        bne +
        pla
        clc
        rts
+       lda #$ff
        sta l_mn_open
        pla
        bpl _ev
        and #$7f                        ; the Window menu: that window to the front
        tax                             ; (restored if it was minimized)
        lda gw_min,x
        beq +
        jsr l_gw_minmax
        bra ++
+       jsr l_gw_raise
+
        jsr gui_redraw
        clc
        rts
_ev:    tax
        lda mn_id,x
        sta ge_val
        lda #0
        sta ge_val+1
        lda #GE_MENU
        sta ge_type
        jsr gui_redraw
        sec
        rts
_key:   lda ev_key
        cmp #K_ESC
        beq _close
        cmp #K_STOP
        beq _close
        cmp #K_RETURN
        bne +
        lda l_md_hov
        cmp #$ff
        beq _none
        bra _pick
+       cmp #K_DOWN
        bne +
        lda l_md_hov
        inc a
        cmp md_n
        bcc _hov
        lda #0
        bra _hov
+       cmp #K_UP
        bne _none
        lda l_md_hov
        dec a
        bpl +
        lda md_n
        dec a
+       cmp #$ff
        beq _none
_hov:   sta l_md_hov
        jsr l_md_draw
        clc
        rts

s_gui_window:   .null "Window"

;---------------------------------------------------------------------------------------
; a toast: a short line in a yellow box at the bottom right of the screen, for a few
; seconds, over everything, taking no input from the window you're in (an instant message
; arriving, say). A click on it removes it early and, with a slot, gives GE_NOTIFY as if
; that notification icon were clicked. A new toast replaces the old one.
;   gui_toast   txt_ptr = text (GUI_TOAST_MAX characters kept), A = seconds, X = the slot
;               a click reports ($ff: none)
;---------------------------------------------------------------------------------------
GUI_TOAST_MAX   = 72
L_TS_Y0         = 186
L_TS_Y1         = 199

gui_toast:
        stx l_ts_slot
        tax                             ; frames = seconds * 50
        lda #0
        sta l_ts_t
        sta l_ts_t+1
_sec:   cpx #0
        beq _text
        clc
        lda l_ts_t
        adc #50
        sta l_ts_t
        bcc _nc
        inc l_ts_t+1
_nc:    dex
        bra _sec
_text:  ldy #0                          ; the text, and its width: 8 a character + 16
-       lda (txt_ptr),y
        cpy #GUI_TOAST_MAX
        bcc +
        lda #0
+       sta l_ts_buf,y
        cmp #0                          ; (the end: flags from the byte, not the cpy)
        beq +
        iny
        bra -
+       tya
        sta l_ts_len
        lda l_ts_t                      ; (0 seconds: nothing)
        ora l_ts_t+1
        beq _out
        lda l_ts_len                    ; x0 = 636 - (len * 8 + 16)
        asl
        sta l_ts_x0
        lda #0
        rol
        sta l_ts_x0+1
        asl l_ts_x0
        rol l_ts_x0+1
        asl l_ts_x0
        rol l_ts_x0+1
        clc
        lda l_ts_x0
        adc #16
        sta l_ts_x0
        bcc +
        inc l_ts_x0+1
+       sec
        lda #<636
        sbc l_ts_x0
        sta l_ts_x0
        lda #>636
        sbc l_ts_x0+1
        sta l_ts_x0+1
        jmp gui_redraw_later            ; (it removes the old one; the toast is drawn last)
_out:   rts

; A = the toast's top row: one row higher while a broadcast has the bottom one
l_ts_top:
        lda l_bc_t
        ora l_bc_t+1
        beq +
        lda #L_TS_Y0 - (L_TS_Y1 - L_TS_Y0 + 1)
        rts
+       lda #L_TS_Y0
        rts

; gr = the toast's box
l_ts_rect:
        lda l_ts_x0
        sta gr_x0
        lda l_ts_x0+1
        sta gr_x0+1
        lda #<636
        sta gr_x1
        lda #>636
        sta gr_x1+1
        jsr l_ts_top
        sta gr_y0
        clc
        adc #L_TS_Y1 - L_TS_Y0
        sta gr_y1
        lda #0
        sta gr_y0+1
        sta gr_y1+1
        rts

l_ts_draw:
        jsr l_bc_draw                   ; a broadcast first (the toast goes above it)
        lda l_ts_t
        ora l_ts_t+1
        bne +
        rts
+       jsr d6_clip_all
        jsr l_ts_rect
        lda #GC_TIP
        jsr l_gd_fill
        lda #GC_BLACK
        tax
        jsr l_gd_edges
        lda #<l_ts_buf
        sta txt_ptr
        lda #>l_ts_buf
        sta txt_ptr+1
        lda #GC_BLACK
        sta gt_fg
        lda #$ff
        sta gt_bg
        sta gt_n
        lda #0
        sta gt_pw
        jsr l_ts_top
        clc
        adc #3
        sta gt_y
        clc
        lda l_ts_x0
        adc #8
        sta gt_x
        lda l_ts_x0+1
        adc #0
        sta gt_x+1
        jmp gui_text

; once a frame: count down; at 0 the screen is drawn again without it
l_ts_tick:
        jsr l_bc_tick
        lda l_ts_t
        ora l_ts_t+1
        beq _out
        lda l_ts_t
        bne +
        dec l_ts_t+1
+       dec l_ts_t
        lda l_ts_t
        ora l_ts_t+1
        bne _out
        jmp gui_redraw_later
_out:   rts

; a press: on the toast? carry set: ge_* is a GE_NOTIFY to report, or ge_type = GE_NONE
l_ts_click:
        lda l_ts_t
        ora l_ts_t+1
        beq _bc
        jsr l_ts_rect
        jsr l_pt_in
        bcc _bc
        lda #0
        sta l_ts_t
        sta l_ts_t+1
        jsr gui_redraw_later
        lda l_ts_slot
        cmp #$ff
        beq _none
        sta ge_val
        lda #0
        sta ge_val+1
        lda #GE_NOTIFY
        sta ge_type
        sec
        rts
_none:  lda #GE_NONE                     ; nothing to report, but the press is used up:
        sta ge_type                     ; drop our return address so gui_update itself
        pla                             ; returns, carry clear (no event)
        pla
        clc
        rts
_bc:    lda l_bc_t                      ; on the broadcast: it goes, nothing to report
        ora l_bc_t+1
        beq _no
        jsr l_bc_rect
        jsr l_pt_in
        bcc _no
        lda #0
        sta l_bc_t
        sta l_bc_t+1
        jsr gui_redraw_later
        bra _none
_no:    clc
        rts

;---------------------------------------------------------------------------------------
; a broadcast: a message to everyone, across the whole bottom row, yellow on red, over
; everything (a toast goes one row up meanwhile). It takes no input; a click removes it.
;   gui_banner  txt_ptr = text (GUI_BANNER_MAX characters kept), A = seconds
;---------------------------------------------------------------------------------------
GUI_BANNER_MAX  = 79

gui_banner:
        tax                             ; frames = seconds * 50
        lda #0
        sta l_bc_t
        sta l_bc_t+1
_sec:   cpx #0
        beq _text
        clc
        lda l_bc_t
        adc #50
        sta l_bc_t
        bcc +
        inc l_bc_t+1
+       dex
        bra _sec
_text:  ldy #0
-       lda (txt_ptr),y
        cpy #GUI_BANNER_MAX
        bcc +
        lda #0
+       sta l_bc_buf,y
        cmp #0
        beq +
        iny
        bra -
+       jmp gui_redraw_later

; gr = the bottom row
l_bc_rect:
        lda #0
        sta gr_x0
        sta gr_x0+1
        sta gr_y0+1
        sta gr_y1+1
        lda #<639
        sta gr_x1
        lda #>639
        sta gr_x1+1
        lda #L_TS_Y0
        sta gr_y0
        lda #L_TS_Y1
        sta gr_y1
        rts

l_bc_draw:
        lda l_bc_t
        ora l_bc_t+1
        bne +
        rts
+       jsr d6_clip_all
        jsr l_bc_rect
        lda #GC_RED
        jsr l_gd_fill
        lda #<l_bc_buf
        sta txt_ptr
        lda #>l_bc_buf
        sta txt_ptr+1
        lda #GC_YELLOW
        sta gt_fg
        lda #$ff
        sta gt_bg
        sta gt_n
        lda #0
        sta gt_pw
        sta gt_x+1
        lda #4
        sta gt_x
        lda #L_TS_Y0 + 3
        sta gt_y
        jmp gui_text

l_bc_tick:
        lda l_bc_t
        ora l_bc_t+1
        beq _out
        lda l_bc_t
        bne +
        dec l_bc_t+1
+       dec l_bc_t
        lda l_bc_t
        ora l_bc_t+1
        bne _out
        jmp gui_redraw_later
_out:   rts

gui_banner_t:                           ; (public, read-only: a broadcast is showing)
l_bc_t:         .word 0                 ; frames left, 0 = none
l_bc_buf:       .fill GUI_BANNER_MAX + 1

gui_toast_t:                            ; (public, read-only: a toast is showing)
l_ts_t:         .word 0                 ; frames left, 0 = no toast
l_ts_x0:        .word 0
l_ts_len:       .byte 0
l_ts_slot:      .byte $ff
l_ts_buf:       .fill GUI_TOAST_MAX + 1

;---------------------------------------------------------------------------------------
; notification icons at the right end of the menu bar, packed from the right: the shown
; icon with the lowest slot is rightmost, and empty slots leave no gap. Icon 1 = an alert
; (flashes), 2 = an envelope, 3 = a Wi-Fi fan (connected), 4 = the fan greyed with a red X
; (not connected), 5 = a person (a black board-game pawn), 6 = a speech bubble, 7 / 8 / 9 =
; a green / yellow / dark grey dot with a black edge (a status), 10 = a newspaper, 11 = two
; beamed music notes (black: playing), 12 = the notes greyed (paused). A click gives
; GE_NOTIFY, ge_val = the slot
;---------------------------------------------------------------------------------------
        .weak
GUI_NSLOTS      = 8                     ; (a program may want more: each takes GUI_NSPACE
        .endweak                        ; more of the bar when they all show at once)
GUI_NICON_W     = 22                    ; an icon's width
GUI_NSPACE      = 24                    ; and the step from one slot to the next (8 of them
                                        ; stay right of a 7-title menu bar)

; A = slot, X = icon (0 = none): set it and draw it
gui_notify:
        cmp #GUI_NSLOTS
        bcs _out
        tay
        txa
        sta nt_icon,y
        lda gui_menubar
        beq _out
        lda gui_hold                    ; (something else has the screen: drawn later)
        bne _out
        jmp l_nt_all                    ; (the others may move along)
_out:   rts

; gr = slot A's square on the bar: x1 = 635 - n * GUI_NSPACE, n = the icons shown in the
; slots below A
l_nt_rect:
        sta l_nt_t                      ; (slot)
        ldx #0
        lda #0
_cnt:   cpx l_nt_t
        beq _got
        ldy nt_icon,x
        beq +
        clc
        adc #GUI_NSPACE
+       inx
        bra _cnt
_got:   sta l_nt_t
        sec
        lda #<635
        sbc l_nt_t
        sta gr_x1
        lda #>635
        sbc #0
        sta gr_x1+1
        sec
        lda gr_x1
        sbc #GUI_NICON_W - 1
        sta gr_x0
        lda gr_x1+1
        sbc #0
        sta gr_x0+1
        lda #0
        sta gr_y0
        sta gr_y0+1
        sta gr_y1+1
        lda #GUI_MENU_H - 2
        sta gr_y1
        rts

; draw slot A's icon (or the bar's face where there's none)
l_nt_draw:
        sta l_nt_s
        jsr d6_clip_all
        lda l_nt_s
        jsr l_nt_rect
        ldy l_nt_s
        lda nt_icon,y
        bne +
        rts                             ; none (l_nt_all clears the row first)
+       cmp #3
        bcc +
        jmp l_nt_wifi                   ; 3-10
+       cmp #1
        bne _env
        jsr l_gd_raised                 ; 1: an alert button
        jmp _alert
_env:   lda #GC_FACE                    ; 2: a plain white envelope on the bar, a black
        jsr l_gd_fill                   ; outline and an X corner to corner (the folds)
        jsr l_gd_shrink
        lda #GC_WHITE
        jsr l_gd_fill
        lda #GC_BLACK
        tax
        jsr l_gd_edges
        lda #GC_BLACK
        sta d6_col
        lda #0
        sta d6_y+1
        sta d6_y1+1
        lda gr_x0                       ; \ top left to bottom right
        sta d6_x
        lda gr_x0+1
        sta d6_x+1
        lda gr_y0
        sta d6_y
        lda gr_x1
        sta d6_x1
        lda gr_x1+1
        sta d6_x1+1
        lda gr_y1
        sta d6_y1
        jsr d6_line
        lda gr_x1                       ; / top right to bottom left
        sta d6_x
        lda gr_x1+1
        sta d6_x+1
        lda gr_y0
        sta d6_y
        lda gr_x0
        sta d6_x1
        lda gr_x0+1
        sta d6_x1+1
        lda gr_y1
        sta d6_y1
        jmp d6_line
_alert: ldx #GC_BLACK                   ; 1: "!" - red on the flash, grey between
        lda #GC_FACE
        ldy l_nt_phase
        beq +
        ldx #GC_WHITE
        lda #GC_RED
+       stx gt_fg
        jsr l_gd_fill
        lda #<s_nt_bang
        sta txt_ptr
        lda #>s_nt_bang
        sta txt_ptr+1
        lda #$ff
        sta gt_bg
        sta gt_n
        lda #0
        sta gt_pw
        lda #1
        sta gt_y
        clc
        lda gr_x0
        adc #3
        sta gt_x
        lda gr_x0+1
        adc #0
        sta gt_x+1
        jmp gui_text
s_nt_bang:      .null "!"

; icon 3 (A = 3) to 10 in gr: a 21x9 bitmap, "#" in the icon's colour (black; 4 grey; the
; dots theirs; 10 white), "+" black: the fan (l_nw_bm), for 4 with a red X; 5 the pawn
; (l_np_bm); 6 the bubble (l_nb_bm); 7-9 the dot (l_nd_bm); 10 the newspaper (l_nn_bm)
l_nt_wifi:
        sta l_nw_i
        lda #<l_nw_bm
        ldx #>l_nw_bm
        ldy l_nw_i
        cpy #5
        bne +
        lda #<l_np_bm
        ldx #>l_np_bm
+       cpy #6
        bne +
        lda #<l_nb_bm
        ldx #>l_nb_bm
+       cpy #7
        bcc +
        lda #<l_nd_bm
        ldx #>l_nd_bm
+       cpy #10
        bne +
        lda #<l_nn_bm
        ldx #>l_nn_bm
+       cpy #11                         ; 11, 12: the music notes
        bcc +
        lda #<l_nm_bm
        ldx #>l_nm_bm
+       sta _px+1
        stx _px+2
        lda #GC_FACE
        jsr l_gd_fill
        ldx l_nw_i
        lda l_nw_cols-3,x
        sta l_nw_k
        lda #0
        sta d6_y+1
        sta l_nw_c
        lda #1
        sta l_nw_r
        ldx #0
_px:    lda l_nw_bm,x
        ldy l_nw_k
        cmp #"#"
        beq _pl
        ldy #GC_BLACK
        cmp #"+"
        bne _nx
_pl:    sty d6_col
        phx
        clc
        lda gr_x0
        adc l_nw_c
        sta d6_x
        lda gr_x0+1
        adc #0
        sta d6_x+1
        clc
        lda gr_y0
        adc l_nw_r
        sta d6_y
        jsr d6_plot
        plx
_nx:    inx
        inc l_nw_c
        lda l_nw_c
        cmp #L_NW_W
        bne +
        lda #0
        sta l_nw_c
        inc l_nw_r
+       cpx #L_NW_W * L_NW_H
        bne _px
        lda l_nw_i
        cmp #4
        bne _out
        lda #GC_RED                     ; the X: two pixels wide, corner to corner
        sta d6_col
        lda #0
        sta l_nw_c
_x:     lda #0
        sta d6_y+1
        sta d6_y1+1
        clc                             ; \
        lda gr_x0
        adc l_nw_c
        sta d6_x
        lda gr_x0+1
        adc #0
        sta d6_x+1
        lda gr_y0
        sta d6_y
        sec
        lda gr_x1
        sbc #1
        clc
        adc l_nw_c
        sta d6_x1
        lda gr_x1+1
        adc #0
        sta d6_x1+1
        lda gr_y1
        sta d6_y1
        jsr d6_line
        lda #0                          ; /
        sta d6_y+1
        sta d6_y1+1
        sec
        lda gr_x1
        sbc #1
        clc
        adc l_nw_c
        sta d6_x
        lda gr_x1+1
        adc #0
        sta d6_x+1
        lda gr_y0
        sta d6_y
        clc
        lda gr_x0
        adc l_nw_c
        sta d6_x1
        lda gr_x0+1
        adc #0
        sta d6_x1+1
        lda gr_y1
        sta d6_y1
        jsr d6_line
        inc l_nw_c
        lda l_nw_c
        cmp #2
        bne _x
_out:   rts
L_NW_W = 21
L_NW_H = 9
l_nw_bm:
        .text "........#####........"
        .text "....####.....####...."
        .text ".###.............###."
        .text "#.....#########.....#"
        .text "....##.........##...."
        .text "...#.....###.....#..."
        .text "........#...#........"
        .text "....................."
        .text ".........###........."
l_np_bm:                                ; a Sorry-style pawn: round head, neck, cone (pixels are
        .text "........#####........"   ; twice as tall as wide)
        .text ".......#######......."
        .text "........#####........"
        .text "..........#.........."
        .text ".........###........."
        .text "........#####........"
        .text ".......#######......."
        .text "......#########......"
        .text ".....###########....."
l_nb_bm:                                ; 6: a speech bubble (instant messages)
        .text "...###############..."
        .text "..#...............#.."
        .text "..#..###.####.##..#.."
        .text "..#...............#.."
        .text "..#..#####.###....#.."
        .text "..#...............#.."
        .text "...####.##########..."
        .text ".......#.#..........."
        .text ".......##............"
l_nd_bm:                                ; 7-9: a dot (twice as wide as tall, as pixels are)
        .text "....................."
        .text ".......+++++++......."
        .text ".....++#######++....."
        .text "....+###########+...."
        .text "...+#############+..."
        .text "....+###########+...."
        .text ".....++#######++....."
        .text ".......+++++++......."
        .text "....................."
l_nn_bm:                                ; 10: a newspaper (unread news): a white page, the
        .text "..+++++++++++++++++.."   ; masthead, two rows of columns
        .text "..+###############+.."
        .text "..+#+++++++++#####+.."
        .text "..+###############+.."
        .text "..+#+++#+++#+++++#+.."
        .text "..+###############+.."
        .text "..+#+++#+++#+++++#+.."
        .text "..+###############+.."
        .text "..+++++++++++++++++.."
l_nm_bm:                                ; 11 / 12: two beamed quavers (music playing / paused)
        .text "......##########....."
        .text "......##########....."
        .text "......#........#....."
        .text "......#........#....."
        .text "......#........#....."
        .text "......#........#....."
        .text "...####.....####....."
        .text "..#####....#####....."
        .text "...###......###......"
l_nw_cols:      .byte GC_BLACK, GC_SHADOW, GC_BLACK, GC_BLACK      ; icons 3-6's "#"
                .byte GC_GREEN, GC_YELLOW, GC_DKGREY               ; 7-9
                .byte GC_WHITE                                     ; 10
                .byte GC_BLACK, GC_SHADOW                          ; 11, 12
l_nw_i:         .byte 0
l_nw_k:         .byte 0
l_nw_c:         .byte 0
l_nw_r:         .byte 0

; all the slots: the icons' strip cleared to the bar's face, then each icon. Only as far left
; as the icons reach now, or reached last time (a long menu bar's last title may be under
; slots that are empty)
l_nt_all:
        jsr d6_clip_all
        ldx #0                          ; the icons shown
        ldy #0
-       lda nt_icon,y
        beq +
        inx
+       iny
        cpy #GUI_NSLOTS
        bne -
        txa
        cmp l_nt_was
        bcs +
        lda l_nt_was                    ; (more last time: clear where they were)
+       stx l_nt_was
        cmp #0
        bne +
        jmp _icons                      ; none now or before: nothing to clear
+       sec
        sbc #1
        tay                             ; (the strip: 635 - (n - 1) * GUI_NSPACE - 21 .. 635)
        lda #<(635 - (GUI_NICON_W - 1))
        sta gr_x0
        lda #>(635 - (GUI_NICON_W - 1))
        sta gr_x0+1
-       cpy #0
        beq +
        sec
        lda gr_x0
        sbc #GUI_NSPACE
        sta gr_x0
        lda gr_x0+1
        sbc #0
        sta gr_x0+1
        dey
        bra -
+       lda #<635
        sta gr_x1
        lda #>635
        sta gr_x1+1
        lda #0
        sta gr_y0
        sta gr_y0+1
        sta gr_y1+1
        lda #GUI_MENU_H - 2
        sta gr_y1
        lda #GC_FACE
        jsr l_gd_fill
_icons: lda #0
        sta l_nt_k
-       lda l_nt_k
        jsr l_nt_draw
        inc l_nt_k
        lda l_nt_k
        cmp #GUI_NSLOTS
        bne -
        rts

; the slot under the pointer -> A ($ff none)
l_nt_at:
        lda #0
        sta l_nt_k
-       ldy l_nt_k
        lda nt_icon,y
        beq +
        tya
        jsr l_nt_rect
        jsr l_pt_in
        bcc +
        lda l_nt_k
        rts
+       inc l_nt_k
        lda l_nt_k
        cmp #GUI_NSLOTS
        bne -
        lda #$ff
        rts

; once a frame: flash the alerts, twice a second
l_nt_flash:
        lda gui_menubar
        beq _out
        lda frame_count
        and #15
        bne _out
        lda l_nt_phase
        eor #1
        sta l_nt_phase
        ldy #0
-       lda nt_icon,y
        cmp #1
        bne +
        phy
        tya
        jsr l_nt_draw
        ply
+       iny
        cpy #GUI_NSLOTS
        bne -
_out:   rts

nt_icon:        .fill GUI_NSLOTS
l_nt_was:       .byte 0                 ; icons shown at the last l_nt_all
l_nt_s:         .byte 0
l_nt_k:         .byte 0
l_nt_t:         .byte 0
l_nt_phase:     .byte 0

;=======================================================================================
; GK_EDIT: an editable text area. Its lines (up to GUI_EDIT_LINES, each up to the box's
; width in characters) are rows 0 .. n-1 of its 8 KB block, 64 bytes each. The cursor is
; gb_row / gb_col. Typing past the end of a line carries on on a new line below.
;=======================================================================================
; l_gb_w = the characters a line of gadget X holds: (w - 6 - scroll bar) / 8, 1 .. 63
l_ed_width:
        sec
        lda gg_wl,x
        sbc #6 + GUI_SB_W
        sta l_gu_t
        lda gg_wh,x
        sbc #0
        lsr
        ror l_gu_t
        lsr
        ror l_gu_t
        lsr
        ror l_gu_t
        lda l_gu_t
        cmp #63
        bcc +
        lda #63
+       cmp #1
        bcs +
        lda #1
+       sta l_gb_w
        rts

; line A of block l_gb_t -> l_gb_line, l_ed_len = its length
l_ed_load:
        ldy #6
        sty l_gb_sh
        ldy l_gb_t
        jsr l_gb_get
        ldx #0
-       lda l_gb_line,x
        beq +
        inx
        bra -
+       stx l_ed_len
        ldy l_gb_t
        rts
; l_gb_line (l_ed_len characters) -> line A of block l_gb_t
l_ed_save:
        pha
        lda #<l_gb_line
        sta txt_ptr
        lda #>l_gb_line
        sta txt_ptr+1
        lda #0
        sta l_gb_p
        lda l_ed_len
        sta l_gb_e
        lda #6
        sta l_gb_sh
        pla
        ldy l_gb_t
        jsr l_gb_store
        ldy l_gb_t
        rts
; an empty line in at row A (the ones below move down). Carry set: no room
l_ed_insline:
        sta l_ed_r
        ldy l_gb_t
        lda gb_n,y
        cmp #GUI_EDIT_LINES
        bcs _full
        sta l_ed_k
_mv:    lda l_ed_k                      ; k = n .. r + 1: line k - 1 -> k
        cmp l_ed_r
        beq _new
        bcc _new
        dec a
        jsr l_ed_load
        lda l_ed_k
        jsr l_ed_save
        dec l_ed_k
        bra _mv
_new:   lda #0
        sta l_ed_len
        lda l_ed_r
        jsr l_ed_save
        lda gb_n,y
        inc a
        sta gb_n,y
        clc
        rts
_full:  sec
        rts
; line A out (the ones below move up)
l_ed_delline:
        sta l_ed_k
_mv:    ldy l_gb_t                      ; k = r .. n - 2: line k + 1 -> k
        lda l_ed_k
        inc a
        cmp gb_n,y
        bcs _done
        jsr l_ed_load
        lda l_ed_k
        jsr l_ed_save
        inc l_ed_k
        bra _mv
_done:  lda gb_n,y
        beq +
        dec a
        sta gb_n,y
+       rts
; at least one (empty) line, so there's somewhere to type
l_ed_one:
        ldy l_gb_t
        lda gb_n,y
        bne +
        lda #0
        sta l_ed_len
        jsr l_ed_save
        lda #1
        sta gb_n,y
+       rts
; the cursor no further right than its line
l_ed_clamp:
        lda gb_row,y
        jsr l_ed_load
        lda gb_col,y
        cmp l_ed_len
        bcc +
        lda l_ed_len
        sta gb_col,y
+       rts


; after one line of text on white at (gr_x0 + 1, gt_y) .. gt_x: the rest of gr white - the
; left margin column, the space after the text, and any rows above and below it
l_gd_spare:
        lda gt_x                        ; after the text: gt_x .. x1, the text's rows
        sta d6_x
        lda gt_x+1
        sta d6_x+1
        lda gr_x1
        sta d6_x1
        lda gr_x1+1
        sta d6_x1+1
        lda gt_y
        sta d6_y
        clc
        adc #7
        sta d6_y1
        jsr l_white
        lda gr_x0                       ; the margin column: x0, all rows
        sta d6_x
        sta d6_x1
        lda gr_x0+1
        sta d6_x+1
        sta d6_x1+1
        lda gr_y0
        sta d6_y
        lda gr_y1
        sta d6_y1
        jsr l_white
        lda gr_x0                       ; above the text: x0 .. x1, y0 .. gt_y - 1
        sta d6_x
        lda gr_x0+1
        sta d6_x+1
        lda gr_x1
        sta d6_x1
        lda gr_x1+1
        sta d6_x1+1
        lda gr_y0
        sta d6_y
        lda gt_y
        beq +
        dec a
        sta d6_y1
        jsr l_white
+       lda gt_y                        ; below it: gt_y + 8 .. y1
        clc
        adc #8
        sta d6_y
        lda gr_y1
        sta d6_y1
        ; (fall through)
; fill d6_x .. d6_x1 (words), d6_y .. d6_y1 (bytes) white, if it isn't empty
l_white:
        lda #0
        sta d6_y+1
        sta d6_y1+1
        lda d6_y1
        cmp d6_y
        bcc _no
        lda d6_x1
        cmp d6_x
        lda d6_x1+1
        sbc d6_x+1
        bcc _no
        lda #GC_WHITE
        sta d6_col
        jmp d6_fill
_no:    rts

; text area: draw line A of gadget X alone (typing changes only it): the line on white,
; the rest of its row white, the caret if it's the cursor's. Nothing if it's scrolled out
l_ed_drawrow:
        sta l_ed_dr
        stx l_gd_gs
        jsr l_gg_rect
        jsr l_gd_shrink
        jsr l_gd_shrink
        ldx l_gd_gs
        ldy gg_big,x
        sty l_gb_t
        jsr l_gb_vlcalc
        lda l_ed_dr                     ; its row on screen
        sec
        sbc gb_top,y
        bcc _out
        cmp l_gb_vl
        bcs _out
        sta l_gb_e
        sec                             ; the text part: left of the scroll bar
        lda gr_x1
        sbc #GUI_SB_W
        sta gr_x1
        bcs +
        dec gr_x1+1
+       jsr l_gd_clip
        lda l_ed_dr
        cmp gb_n,y
        bcc +
        lda #0                          ; (past the last line: empty)
        sta l_gb_line
        bra ++
+       ldx #6
        stx l_gb_sh
        jsr l_gb_get
+       lda #GC_BLACK
        sta gt_fg
        lda #GC_WHITE
        sta gt_bg
        jsr l_gb_text
        lda gt_x                        ; the rest of the row white
        sta d6_x
        lda gt_x+1
        sta d6_x+1
        lda gr_x1
        sta d6_x1
        lda gr_x1+1
        sta d6_x1+1
        lda gt_y
        sta d6_y
        clc
        adc #7
        sta d6_y1
        jsr l_white
        ldy l_gb_t                      ; the caret
        lda gb_row,y
        cmp l_ed_dr
        bne _out
        ldx l_gd_gs
        ldy gg_win,x
        lda gw_focus,y
        cmp l_gd_gs
        bne _out
        ldy l_gb_t
        lda gb_col,y
        sta l_gu_t
        lda #0
        sta l_gu_t+1
        asl l_gu_t
        rol l_gu_t+1
        asl l_gu_t
        rol l_gu_t+1
        asl l_gu_t
        rol l_gu_t+1
        sec                             ; x0 + 1 + column * 8
        lda gr_x0
        adc l_gu_t
        sta d6_x
        sta d6_x1
        lda gr_x0+1
        adc l_gu_t+1
        sta d6_x+1
        sta d6_x1+1
        lda gt_y
        sta d6_y
        clc
        adc #7
        sta d6_y1
        lda #0
        sta d6_y+1
        sta d6_y1+1
        lda #GC_BLACK
        sta d6_col
        jsr d6_fill
_out:   jmp d6_clip_all
l_ed_dr:        .byte 0
l_ed_or:        .byte 0
l_ed_ot:        .byte 0
l_ed_on:        .byte 0

; A = a key for text area X. Carry set: not one it uses
l_ed_key:
        sta l_ed_kv
        stx l_ed_gs
        ldy gg_big,x
        cpy #$ff
        bne +
        sec
        rts
+       sty l_gb_t
        jsr l_ed_width
        jsr l_ed_one
        lda gb_row,y                    ; (to see what changed)
        sta l_ed_or
        lda gb_top,y
        sta l_ed_ot
        lda gb_n,y
        sta l_ed_on
        lda l_ed_kv
        cmp #K_RETURN
        bne +
        jmp _ret
+       cmp #K_DEL
        bne +
        jmp _bs
+       cmp #K_LEFT
        bne +
        jmp _left
+       cmp #K_RIGHT
        bne +
        jmp _right
+       cmp #K_UP
        bne +
        jmp _up
+       cmp #K_DOWN
        bne +
        jmp _down
+       cmp #K_HOME
        bne +
        lda #0
        sta gb_col,y
        jmp _done
+       cmp #32
        bcc _not
        cmp #127
        bcc _ins
_not:   sec
        rts
_ins:   lda gb_row,y
        jsr l_ed_load
        lda l_ed_len
        cmp l_gb_w
        bcc _room
        lda gb_row,y                    ; full: carry on on a new line below
        inc a
        jsr l_ed_insline
        bcc +
        jmp _done
+       lda gb_row,y
        inc a
        sta gb_row,y
        lda #0
        sta gb_col,y
        lda gb_row,y
        jsr l_ed_load
_room:  ldx l_ed_len                    ; make room at the cursor
-       lda l_gb_line,x
        sta l_gb_line+1,x
        txa
        cmp gb_col,y
        beq +
        dex
        bra -
+       lda l_ed_kv
        sta l_gb_line,x
        inc l_ed_len
        lda gb_row,y
        jsr l_ed_save
        lda gb_col,y
        inc a
        sta gb_col,y
        jmp _done
_ret:   lda gb_n,y                      ; split the line at the cursor
        cmp #GUI_EDIT_LINES
        bcc +
        jmp _done
+       lda gb_row,y
        jsr l_ed_load
        lda gb_col,y                    ; the tail -> l_ed_tail
        tay
        ldx #0
-       lda l_gb_line,y
        sta l_ed_tail,x
        beq +
        iny
        inx
        bra -
+       ldy l_gb_t
        ldx gb_col,y                    ; this line ends at the cursor
        lda #0
        sta l_gb_line,x
        stx l_ed_len
        lda gb_row,y
        jsr l_ed_save
        lda gb_row,y
        inc a
        jsr l_ed_insline
        ldx #0                          ; the tail on the new line
-       lda l_ed_tail,x
        sta l_gb_line,x
        beq +
        inx
        bra -
+       stx l_ed_len
        lda gb_row,y
        inc a
        jsr l_ed_save
        lda gb_row,y
        inc a
        sta gb_row,y
        lda #0
        sta gb_col,y
        jmp _done
_bs:    lda gb_col,y
        beq _join
        lda gb_row,y                    ; the character before the cursor goes
        jsr l_ed_load
        ldx gb_col,y
        dex
-       lda l_gb_line+1,x
        sta l_gb_line,x
        beq +
        inx
        bra -
+       dec l_ed_len
        lda gb_row,y
        jsr l_ed_save
        lda gb_col,y
        dec a
        sta gb_col,y
        jmp _done
_join:  lda gb_row,y                    ; at the start: onto the end of the line above
        bne +
        jmp _done
+       jsr l_ed_load                   ; this line -> l_ed_tail
        ldx #0
-       lda l_gb_line,x
        sta l_ed_tail,x
        beq +
        inx
        bra -
+       stx l_ed_tl
        lda gb_row,y
        dec a
        jsr l_ed_load                   ; the line above
        lda l_ed_len
        sta l_ed_p
        clc
        adc l_ed_tl
        cmp l_gb_w
        beq +
        bcc +
        jmp _done                       ; they don't fit on one line
+       ldx l_ed_len
        lda #0
        sta l_ed_i
-       phx
        ldx l_ed_i
        lda l_ed_tail,x
        plx
        sta l_gb_line,x
        cmp #0                          ; (plx set Z from X, and sta sets nothing: test A)
        beq +
        inx
        inc l_ed_i
        bra -
+       stx l_ed_len
        lda gb_row,y
        dec a
        jsr l_ed_save
        lda gb_row,y
        jsr l_ed_delline
        ldy l_gb_t
        lda gb_row,y
        dec a
        sta gb_row,y
        lda l_ed_p
        sta gb_col,y
        jmp _done
_left:  lda gb_col,y
        beq +
        dec a
        sta gb_col,y
        jmp _done
+       lda gb_row,y                    ; to the end of the line above
        beq _done
        dec a
        sta gb_row,y
        lda #63
        sta gb_col,y
        jsr l_ed_clamp
        bra _done
_right: lda gb_row,y
        jsr l_ed_load
        lda gb_col,y
        cmp l_ed_len
        bcs +
        inc a
        sta gb_col,y
        bra _done
+       lda gb_row,y                    ; to the start of the line below
        inc a
        cmp gb_n,y
        bcs _done
        sta gb_row,y
        lda #0
        sta gb_col,y
        bra _done
_up:    lda gb_row,y
        beq _done
        dec a
        sta gb_row,y
        jsr l_ed_clamp
        bra _done
_down:  lda gb_row,y
        inc a
        cmp gb_n,y
        bcs _done
        sta gb_row,y
        jsr l_ed_clamp
_done:  ldx l_ed_gs                     ; keep the cursor's line in view
        jsr l_gb_vlgad
        ldy l_gb_t
        lda gb_row,y
        cmp gb_top,y
        bcs +
        sta gb_top,y
        bra _draw
+       sec
        sbc gb_top,y
        cmp l_gb_vl
        bcc _draw
        lda gb_row,y
        sec
        sbc l_gb_vl
        inc a
        sta gb_top,y
_draw:  ldx l_ed_gs                     ; the same lines, the same scroll: just the line(s)
        ldy l_gb_t                      ; typed on, else the whole area
        lda gb_top,y
        cmp l_ed_ot
        bne _all
        lda gb_n,y
        cmp l_ed_on
        bne _all
        lda l_gui_later                 ; (a whole redraw is coming anyway)
        bne _all
        jsr l_gw_front                  ; in front, so nothing covers it
        ldx l_ed_gs
        cmp gg_win,x
        bne _all
        lda l_ed_or
        jsr l_ed_drawrow
        ldy l_gb_t
        lda gb_row,y
        cmp l_ed_or
        beq _ok
        ldx l_ed_gs
        jsr l_ed_drawrow
_ok:    clc
        rts
_all:   ldx l_ed_gs
        jsr l_gg_redraw
        clc
        rts

; a click in text area X (gr = its inside, l_gb_t its block): the keyboard, and the
; cursor where it was clicked
l_ed_click:
        stx l_ed_gs
        jsr l_ed_width
        sec                             ; row = (y - y0 - 1) / 8 + top
        lda ev_y
        sbc gr_y0
        sec
        sbc #1
        bcs +
        lda #0
+       lsr
        lsr
        lsr
        clc
        ldy l_gb_t
        adc gb_top,y
        sta l_ed_r
        jsr l_ed_one
        lda l_ed_r                      ; no further than the last line
        cmp gb_n,y
        bcc +
        lda gb_n,y
        dec a
+       sta gb_row,y
        sec                             ; column = (x - x0 - 1) / 8
        lda ev_x
        sbc gr_x0
        sta l_gu_t
        lda ev_x+1
        sbc gr_x0+1
        lsr
        ror l_gu_t
        lsr
        ror l_gu_t
        lsr
        ror l_gu_t
        lda l_gu_t
        sta gb_col,y
        jsr l_ed_clamp
        ldx l_ed_gs
        ldy gg_win,x
        lda gw_id,y
        pha
        lda gg_id,x
        tax
        pla
        jsr gui_focus
        clc
        rts

; a line from the server (APPEND) at the end of text area X (cut to its width)
l_ed_append:
        sty l_gb_t
        stx l_ed_gs
        jsr l_ed_width
        ldy l_gb_t
        lda gb_n,y
        cmp #GUI_EDIT_LINES
        bcs _out
        ldy #0                          ; its length, at most the width
-       lda (txt_ptr),y
        beq +
        iny
        cpy l_gb_w
        bne -
+       sty l_gb_e
        lda #0
        sta l_gb_p
        lda #6
        sta l_gb_sh
        ldy l_gb_t
        lda gb_n,y
        jsr l_gb_store
        ldy l_gb_t
        lda gb_n,y
        inc a
        sta gb_n,y
        ldx l_ed_gs
        jmp l_gg_later
_out:   rts

; A = window, X = gadget (a text area): A = its line count; carry set if no such gadget
gui_edit_count:
        jsr l_gg_find
        bcs _no
        ldy gg_big,x
        cpy #$ff
        beq _no
        lda gb_n,y
        clc
        rts
_no:    sec
        rts
; A = window, X = gadget, Y = line: txt_ptr = that line (zero-terminated, in l_gb_line)
gui_edit_line:
        sty l_ed_r
        jsr l_gg_find
        bcs _no
        ldy gg_big,x
        cpy #$ff
        beq _no
        sty l_gb_t
        lda l_ed_r
        jsr l_ed_load
        lda #<l_gb_line
        sta txt_ptr
        lda #>l_gb_line
        sta txt_ptr+1
        clc
        rts
_no:    sec
        rts

;=======================================================================================
; GK_DROP: a drop-down list. Rows as a list's (gui_list_total / gui_list_row, 64 bytes
; each), the choice in gb_sel. A click opens a pop-up list under it; picking a row gives
; GE_SELECT.
;=======================================================================================
GUI_DROP_ROWS   = 8                     ; rows the pop-up shows at once

; draw drop-down l_gd_gs (gr = its rectangle)
l_gd_drop:
        jsr l_gd_sunken
        lda #GC_WHITE
        jsr l_gd_fill
        ldx l_gd_gs
        ldy gg_big,x
        cpy #$ff
        bne +
        rts
+       sty l_gb_t
        ldx #7                          ; (the inside, for the button)
-       lda gr_x0,x
        sta l_sb_save,x
        dex
        bpl -
        sec                             ; the button: the right 11 pixels
        lda gr_x1
        sbc #GUI_SB_W - 1
        sta sb_x0
        lda gr_x1+1
        sbc #0
        sta sb_x0+1
        lda gr_y0
        sta gr_y0
        lda gr_y1
        sta gr_y1
        jsr l_sb_button
        lda #1
        sta sb_has
        lda l_sb_save+2                 ; its arrow, one row higher than a scroll bar's
        dec a
        ldx #1
        jsr l_sb_arrow
        ldx #7
-       lda l_sb_save,x
        sta gr_x0,x
        dex
        bpl -
        sec                             ; the choice, left of the button
        lda gr_x1
        sbc #GUI_SB_W
        sta gr_x1
        bcs +
        dec gr_x1+1
+       jsr l_gd_clip
        ldy l_gb_t
        lda gb_sel,y
        cmp #$ff
        beq _out
        cmp gb_n,y
        bcs _out
        ldx #6
        stx l_gb_sh
        jsr l_gb_get
        lda #GC_BLACK
        sta gt_fg
        lda #$ff
        sta gt_bg
        lda #0
        sta l_gb_e
        jsr l_gd_vmid
        lda gt_y
        dec a
        sta l_dd_y                      ; (l_gb_text adds 1 + row * 8 to gr_y0)
        lda gr_y0
        pha
        lda l_dd_y
        sta gr_y0
        jsr l_gb_text
        pla
        sta gr_y0
_out:   jmp d6_clip_all

; open drop-down X's pop-up (gr = its rectangle)
l_dd_open:
        ldy gg_big,x
        cpy #$ff
        bne +
        clc
        rts
+       stx l_dd_gs
        sty l_gb_t
        lda gb_n,y                      ; rows shown: n, at most GUI_DROP_ROWS
        beq _none
        cmp #GUI_DROP_ROWS
        bcc +
        lda #GUI_DROP_ROWS
+       sta l_dd_vis
        lda gr_x0
        sta dd_x0
        lda gr_x0+1
        sta dd_x0+1
        lda gr_x1
        sta dd_x1
        lda gr_x1+1
        sta dd_x1+1
        lda l_dd_vis                    ; height: rows * 8 + 4
        asl
        asl
        asl
        clc
        adc #3
        sta l_dd_h
        lda gr_y1                       ; under it, or above it if it won't fit
        clc
        adc #1
        sta dd_y0
        clc
        adc l_dd_h
        bcs _above
        cmp #200
        bcc +
_above: lda gr_y0
        sec
        sbc #1
        sbc l_dd_h
        sta dd_y0
+       lda dd_y0
        clc
        adc l_dd_h
        sta dd_y1
        ldy l_gb_t                      ; the choice lit and in view
        lda gb_sel,y
        cmp gb_n,y
        bcc +
        lda #0
+       sta l_dd_hov
        lda l_dd_vis
        sta l_gb_vl
        lda l_dd_hov
        cmp gb_top,y
        bcc _top
        sec
        sbc gb_top,y
        cmp l_dd_vis
        bcc +
        lda l_dd_hov
        sec
        sbc l_dd_vis
        inc a
_top:   sta gb_top,y
+       jsr l_gb_maxtop
        cmp gb_top,y
        bcs +
        sta gb_top,y
+       jsr l_dd_draw
_none:  clc
        rts

; gr = the pop-up's inside (inside its black frame and white margin)
l_dd_inner:
        lda dd_x0
        sta gr_x0
        lda dd_x0+1
        sta gr_x0+1
        lda dd_x1
        sta gr_x1
        lda dd_x1+1
        sta gr_x1+1
        lda dd_y0
        sta gr_y0
        lda dd_y1
        sta gr_y1
        lda #0
        sta gr_y0+1
        sta gr_y1+1
        rts

l_dd_draw:
        jsr d6_clip_all
        jsr l_dd_inner
        lda #GC_BLACK
        tax
        jsr l_gd_edges
        jsr l_gd_shrink
        lda #GC_WHITE
        jsr l_gd_fill
        ldy l_gb_t
        lda l_dd_vis
        sta l_gb_vl
        lda gb_n,y                      ; a scroll bar if they don't all fit
        cmp l_dd_vis
        beq +
        bcc +
        jsr l_sb_draw
        sec
        lda gr_x1
        sbc #GUI_SB_W
        sta gr_x1
        bcs +
        dec gr_x1+1
+       jsr l_gd_clip
        lda #6
        sta l_gb_sh
        lda #0
        sta l_gb_e
        ldy l_gb_t
        lda gb_top,y
        sta l_gb_k
_r:     ldy l_gb_t
        lda l_gb_e
        cmp l_dd_vis
        bcs _done
        lda l_gb_k
        cmp gb_n,y
        bcs _done
        jsr l_gb_get
        lda #GC_BLACK
        sta gt_fg
        lda #$ff
        sta gt_bg
        lda l_gb_k
        cmp l_dd_hov
        bne _t
        jsr l_gb_rowy                   ; the lit row: white on navy
        lda gr_x0
        sta d6_x
        lda gr_x0+1
        sta d6_x+1
        lda gr_x1
        sta d6_x1
        lda gr_x1+1
        sta d6_x1+1
        lda gt_y
        sta d6_y
        clc
        adc #7
        sta d6_y1
        lda #0
        sta d6_y+1
        sta d6_y1+1
        lda #GC_TITLE
        sta d6_col
        jsr d6_fill
        lda #GC_WHITE
        sta gt_fg
_t:     jsr l_gb_text
        inc l_gb_k
        inc l_gb_e
        bra _r
_done:  jmp d6_clip_all

; the pop-up's row under the pointer -> A ($ff none); carry set if over its scroll bar
l_dd_at:
        jsr l_dd_inner
        jsr l_pt_in
        bcc _no
        jsr l_gd_shrink
        ldy l_gb_t
        lda gb_n,y                      ; on the scroll bar?
        cmp l_dd_vis
        beq _rows
        bcc _rows
        sec
        lda gr_x1
        sbc #GUI_SB_W - 1
        sta l_gu_t
        lda gr_x1+1
        sbc #0
        sta l_gu_t+1
        lda ev_x
        cmp l_gu_t
        lda ev_x+1
        sbc l_gu_t+1
        bcc _rows
        lda #$ff
        sec
        rts
_rows:  sec
        lda ev_y
        sbc gr_y0
        sec
        sbc #1
        bcs +
        lda #0
+       lsr
        lsr
        lsr
        cmp l_dd_vis
        bcs _no
        clc
        adc gb_top,y
        cmp gb_n,y
        bcs _no
        clc
        rts
_no:    lda #$ff
        clc
        rts

; gui_update while a pop-up is open. Carry set = an event (GE_SELECT)
l_dd_update:
        lda ev_type
        cmp #EV_KEY
        beq _key
        jsr l_dd_at                     ; the row under the pointer, lit
        bcs +
        cmp #$ff
        beq +
        cmp l_dd_hov
        beq +
        sta l_dd_hov
        jsr l_dd_draw
+       lda ev_type
        cmp #EV_DOWN
        bne _no
        jsr l_dd_at
        bcs _bar
        cmp #$ff
        beq _close                      ; outside: shut it (the click goes nowhere)
        bra _pick
_bar:   ldy l_gb_t                      ; the scroll bar: top half up, bottom half down
        lda dd_y0
        clc
        adc dd_y1
        ror
        cmp ev_y
        bcc _dn
        lda gb_top,y
        sec
        sbc l_dd_vis
        bcs +
        lda #0
+       bra _st
_dn:    lda gb_top,y
        clc
        adc l_dd_vis
        sta l_gu_t
        jsr l_gb_maxtop
        cmp l_gu_t
        bcc _st
        lda l_gu_t
_st:    sta gb_top,y
        jsr l_dd_draw
_no:    clc
        rts
_key:   lda ev_key
        cmp #K_ESC
        beq _close
        cmp #K_STOP
        beq _close
        cmp #K_RETURN
        bne +
        lda l_dd_hov
        bra _pick
+       ldy l_gb_t
        cmp #K_DOWN
        bne +
        lda l_dd_hov
        inc a
        cmp gb_n,y
        bcs _no
        bra _hov
+       cmp #K_UP
        bne _no
        lda l_dd_hov
        beq _no
        dec a
_hov:   sta l_dd_hov                    ; (and scrolled into view)
        cmp gb_top,y
        bcs +
        sta gb_top,y
+       sec
        sbc gb_top,y
        cmp l_dd_vis
        bcc +
        lda l_dd_hov
        sec
        sbc l_dd_vis
        inc a
        sta gb_top,y
+       jsr l_dd_draw
        clc
        rts
_pick:  ldy l_gb_t
        sta gb_sel,y
        sta ge_val
        lda #0
        sta ge_val+1
        ldx l_dd_gs
        lda gg_id,x
        sta ge_gid
        ldy gg_win,x
        lda gw_id,y
        sta ge_win
        lda #$ff
        sta l_dd_gs
        jsr gui_redraw
        lda #GE_SELECT
        sta ge_type
        sec
        rts
_close: lda #$ff
        sta l_dd_gs
        jsr gui_redraw
        clc
        rts

gb_row:         .fill GUI_MAXBIG        ; text area: the cursor's line
gb_col:         .fill GUI_MAXBIG        ;            and column
l_ed_len:       .byte 0
l_ed_kv:        .byte 0
l_ed_gs:        .byte 0
l_ed_r:         .byte 0
l_ed_k:         .byte 0
l_ed_i:         .byte 0
l_ed_p:         .byte 0
l_ed_tl:        .byte 0
l_ed_tail:      .fill 66
l_dd_gs:        .byte $ff               ; the drop-down whose pop-up is open, $ff none
l_dd_vis:       .byte 0
l_dd_h:         .byte 0
l_dd_hov:       .byte 0
l_dd_y:         .byte 0
dd_x0:          .word 0
dd_x1:          .word 0
dd_y0:          .byte 0
dd_y1:          .byte 0

;=======================================================================================
; data
;=======================================================================================
GUIPAL_R = [0, 255, 192, 128, 223, 0, 0, 16, 255, 192, 0, 64, 0, 8, 255, 0]
GUIPAL_G = [0, 255, 192, 128, 223, 0, 128, 132, 255, 0, 128, 64, 0, 8, 255, 255]
GUIPAL_B = [0, 255, 192, 128, 223, 128, 128, 208, 225, 0, 0, 64, 255, 24, 0, 255]
l_gui_pal_r:    .byte GUIPAL_R
l_gui_pal_g:    .byte GUIPAL_G
l_gui_pal_b:    .byte GUIPAL_B

; the pointer: a Windows-style arrow, black outline (sprite GUI_PTR_SPR) over a white
; fill (the next sprite). Sprite pixels are 2 x 1 of the 640x200 screen.
        .align 64
l_gui_arrow_o:
        .byte %10000000, 0, 0
        .byte %11000000, 0, 0
        .byte %10100000, 0, 0
        .byte %10010000, 0, 0
        .byte %10001000, 0, 0
        .byte %10000100, 0, 0
        .byte %10000010, 0, 0
        .byte %10001110, 0, 0
        .byte %10101000, 0, 0
        .byte %11010100, 0, 0
        .byte %10010100, 0, 0
        .byte %00001010, 0, 0
        .byte %00000110, 0, 0
        .fill 8 * 3
        .byte 0
; the busy pointer: an hourglass, black outline over a white fill
        .align 64
l_gui_glass_o:
        .byte $fe, 0, 0
        .byte $82, 0, 0
        .byte $44, 0, 0
        .byte $28, 0, 0
        .byte $10, 0, 0
        .byte $28, 0, 0
        .byte $44, 0, 0
        .byte $82, 0, 0
        .byte $fe, 0, 0
        .fill 64 - 9 * 3
l_gui_glass_f:
        .byte 0, 0, 0
        .byte $7c, 0, 0
        .byte $38, 0, 0
        .byte $10, 0, 0
        .byte 0, 0, 0
        .byte $10, 0, 0
        .byte $38, 0, 0
        .byte $7c, 0, 0
        .byte 0, 0, 0
        .fill 64 - 9 * 3
l_dg_shape_lo:  .byte <l_dg_tl, <l_dg_tr, <l_dg_bl, <l_dg_br
l_dg_shape_hi:  .byte >l_dg_tl, >l_dg_tr, >l_dg_bl, >l_dg_br
; the corner brackets: arms 16 sprite pixels across (32 screen pixels) and 12 rows down
        .align 64
l_dg_tl:
        .byte $ff, $ff, 0
        .fill 11 * 3, [$80, 0, 0]
        .fill 64 - 12 * 3
l_dg_tr:
        .byte $ff, $ff, 0
        .fill 11 * 3, [0, 1, 0]
        .fill 64 - 12 * 3
l_dg_bl:
        .fill 11 * 3, [$80, 0, 0]
        .byte $ff, $ff, 0
        .fill 64 - 12 * 3
l_dg_br:
        .fill 11 * 3, [0, 1, 0]
        .byte $ff, $ff, 0
        .fill 64 - 12 * 3
        .align 64
l_gui_arrow_f:
        .byte %00000000, 0, 0
        .byte %00000000, 0, 0
        .byte %01000000, 0, 0
        .byte %01100000, 0, 0
        .byte %01110000, 0, 0
        .byte %01111000, 0, 0
        .byte %01111100, 0, 0
        .byte %01110000, 0, 0
        .byte %01010000, 0, 0
        .byte %00001000, 0, 0
        .byte %00001000, 0, 0
        .byte %00000100, 0, 0
        .byte %00000000, 0, 0
        .fill 8 * 3
        .byte 0
