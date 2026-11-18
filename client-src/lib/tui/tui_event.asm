;=======================================================================================
; lib/tui/tui_event.asm - one event stream for keyboard and mouse, the mouse pointer and the
; text cursor. Needs lib/mouse.asm, lib/hwsprite.asm, lib/system.asm (frame IRQ).
; Define MOUSE_MAX_X = 319 and MOUSE_MAX_Y = 199 (the defaults).
;
;   tui_event_init   after tui_init: sprites, mouse
;   tui_wait_event   wait for an event: A = tui_ev. See below.
;   tui_poll_event   the same without waiting: A = EV_NONE if nothing has happened
;   tui_cursor_on    X = row, Y = col: show the blinking cursor
;   tui_cursor_off
;   tui_cursor_big   0 = underline (insert), 1 = block (overtype)
;   tui_cursor_ink   colour of the cursor
;   tui_pointer_hide hide the mouse pointer, while typing say. A click brings it back, or moving
;                    the mouse TUI_HIDE_SLOP counts from where it was, which a real mouse's jitter
;                    shouldn't reach.
;
; Event:
;   tui_ev           EV_KEY, EV_DOWN, EV_UP, EV_DRAG (moved to another cell, button down),
;                    EV_RDOWN (right button), EV_REPEAT (left held: every few frames)
;   tui_ev_key       EV_KEY: printable ASCII 32-126, a TK_ code, or for CTRL and MEGA
;                    combinations the upper-case letter with KM_CTRL / KM_MEGA set
;   tui_ev_mods      KM_ bits
;   tui_mrow, tui_mcol  the cell under the pointer
;   tui_dbl          EV_DOWN: 1 for the second click of a double click
;
; The MEGA65 keyboard, as this module maps it (book, appendix F):
;   HOME = TK_HOME, SHIFT+HOME = TK_END, CTRL+HOME = TK_BOF, CTRL+SHIFT+HOME = TK_EOF
;   INST/DEL = TK_BKSP, SHIFT+DEL (INST) = TK_INS, ALT+DEL = TK_DEL
;   F9, F11 = TK_PGUP, TK_PGDN (SHIFT = KM_SHIFT), HELP or F1 = TK_F1, RUN/STOP = TK_ESC
;   a tap of ALT alone = TK_ALT. ALT+letter isn't usable: ALT+F, for one, sends nothing.
;
; The cursor left and up keys are cursor right and down with a shift applied: the right
; shift on the MEGA65 (the book), the left in Xemu. $D60F says directly whether those two
; keys are down, on both. So on a left/up code: with $D60F's bit, it is that key, and SHIFT
; was also held only if both shifts show. Without it, it is SHIFT or CTRL + right/down.
;
; Test injection: tui_dbg_q holds 3-byte records, played in order, tui_dbg_len bytes long:
;   1, code, mods    a key as the hardware reports it ($D610, $D611). Mods bit 7 stands for
;                    $D60F showing the cursor left or up key down.
;   2, col, row      move the pointer (hardware mouse reads stop from then on)
;   3, buttons, 0    set the buttons: bit 0 left, bit 1 right
;   4, frames, 0     wait
;   5, 0, 0          a tap of ALT
; Set tui_dbg_pos to 0, then tui_dbg_len last.
;=======================================================================================

EV_NONE         = 0
EV_KEY          = 1
EV_DOWN         = 2
EV_UP           = 3
EV_DRAG         = 4
EV_RDOWN        = 5
EV_REPEAT       = 6

KM_SHIFT        = 1
KM_CTRL         = 2
KM_ALT          = 4
KM_MEGA         = 8

TK_UP           = 1
TK_DOWN         = 2
TK_LEFT         = 3
TK_RIGHT        = 4
TK_HOME         = 5
TK_END          = 6
TK_BOF          = 7
TK_EOF          = 8
TK_PGUP         = 9
TK_PGDN         = 10
TK_INS          = 11
TK_DEL          = 12
TK_BKSP         = 13
TK_ENTER        = 14
TK_TAB          = 15
TK_BTAB         = 16
TK_ESC          = 17
TK_ALT          = 18
TK_F1           = 19
TK_F3           = 20
TK_F5           = 21
TK_F6           = 22
TK_F7           = 23
TK_F8           = 24

MODKEY          = $D611
KEYDIRECT       = $D60F                 ; bit 0 cursor left key, bit 1 cursor up key

TUI_SPR_FILL    = 0                     ; (lower numbers are drawn in front)
TUI_SPR_OUTLINE = 1
TUI_SPR_CURSOR  = 2
TUI_BLINK       = 16                    ; frames per blink phase
TUI_REPEAT1     = 18                    ; frames before EV_REPEAT starts
TUI_REPEAT2     = 4                     ; and between repeats
TUI_DBLCLICK    = 22                    ; frames a double click may take

tui_ev:         .byte 0
tui_ev_key:     .byte 0
tui_ev_mods:    .byte 0
tui_mrow:       .byte 12
tui_mcol:       .byte 40
tui_dbl:        .byte 0
tui_cursor_big: .byte 0
tui_cursor_ink: .byte TUI_WHITE
tui_dbg_pos:    .byte 0
tui_dbg_len:    .byte 0
        .section bss
tui_dbg_q:      .fill 256
        .send

TUI_HIDE_SLOP   = 3                     ; mouse counts that don't bring back a hidden pointer

l_tev_frame:    .byte 0                 ; last frame the mouse was read
l_tev_pend:     .byte 0                 ; events still to report this frame (bits below)
l_tev_lheld:    .byte 0
l_tev_rep:      .byte 0
l_tev_lastclk:  .byte 0                 ; frame of the last click
l_tev_lastrow:  .byte $ff
l_tev_lastcol:  .byte $ff
l_tev_dbgmouse: .byte 0                 ; 1 = the pointer is under test control
l_tev_dbgbtn:   .byte 0
l_tev_dbgold:   .byte 0
l_tev_wait:     .byte 0
l_tev_ptr_on:   .byte 0
l_tev_hidden:   .byte 0                 ; tui_pointer_hide hid it
l_tev_hx:       .word 0                 ; ...with the mouse here
l_tev_hy:       .byte 0
l_tev_altdown:  .byte 0
l_tev_altused:  .byte 0
l_tev_curon:    .byte 0                 ; the application wants a cursor
l_tev_curvis:   .byte 0
l_tev_blink:    .byte 0
l_tev_currow:   .byte 0
l_tev_curcol:   .byte 0
l_tev_oldx:     .word 0
l_tev_oldy:     .byte 0
l_tev_raw:      .byte 0
l_tev_rawm:     .byte 0
l_tev_rawdir:   .byte 0                 ; KEYDIRECT's two bits

L_P_DOWN        = 1
L_P_UP          = 2
L_P_RDOWN       = 4
L_P_DRAG        = 8
L_P_REPEAT      = 16

tui_event_init:
        jsr hws_init
        ldx #TUI_SPR_OUTLINE
        lda #<l_tev_arrow_o
        ldy #>l_tev_arrow_o
        jsr hws_shape
        ldx #TUI_SPR_FILL
        lda #<l_tev_arrow_f
        ldy #>l_tev_arrow_f
        jsr hws_shape
        ldx #TUI_SPR_CURSOR
        lda #<l_tev_cur_line
        ldy #>l_tev_cur_line
        jsr hws_shape
        ldx #TUI_SPR_OUTLINE
        lda #TUI_BLACK
        jsr hws_colour
        ldx #TUI_SPR_FILL
        lda #TUI_WHITE
        jsr hws_colour
        jsr mouse_init
        lda #0
        sta l_tev_pend
        sta l_tev_ptr_on
        sta l_tev_curon
        lda frame_count
        sta l_tev_frame
        lda mouse_x
        sta l_tev_oldx
        lda mouse_x+1
        sta l_tev_oldx+1
        lda mouse_y
        sta l_tev_oldy
        rts

tui_cursor_on:
        stx l_tev_currow
        sty l_tev_curcol
        lda #1
        sta l_tev_curon
        lda #0
        sta l_tev_blink
        jmp l_tev_cur_show
tui_cursor_off:
        lda #0
        sta l_tev_curon
        sta l_tev_curvis
        ldx #TUI_SPR_CURSOR
        jmp hws_off

l_tev_cur_show:
        lda #1
        sta l_tev_curvis
        ldx #TUI_SPR_CURSOR
        lda tui_cursor_big
        beq +
        lda #<l_tev_cur_block
        ldy #>l_tev_cur_block
        bra ++
+       lda #<l_tev_cur_line
        ldy #>l_tev_cur_line
+       jsr hws_shape
        ldx #TUI_SPR_CURSOR
        lda tui_cursor_ink
        jsr hws_colour
        lda l_tev_curcol                ; a cell is 4 sprite pixels wide
        asl
        sta hws_x
        lda #0
        rol
        sta hws_x+1
        asl hws_x
        rol hws_x+1
        lda l_tev_currow
        asl
        asl
        asl
        sta hws_y
        lda #0
        sta hws_y+1
        ldx #TUI_SPR_CURSOR
        jsr hws_place
        ldx #TUI_SPR_CURSOR
        jmp hws_on

l_tev_cur_blink:
        lda l_tev_curon
        beq l_tev_cb_end
        inc l_tev_blink
        lda l_tev_blink
        cmp #TUI_BLINK
        bcc l_tev_cb_end
        lda #0
        sta l_tev_blink
        lda l_tev_curvis
        eor #1
        sta l_tev_curvis
        ldx #TUI_SPR_CURSOR
        lda l_tev_curvis
        beq +
        jmp hws_on
+       jmp hws_off
l_tev_cb_end:
        rts

tui_wait_event:
-       jsr tui_poll_event
        beq -
        rts

tui_poll_event:
        lda l_tev_pend
        bne l_tev_report
        ; test script
        jsr l_tev_script
        bne l_tev_done
        ; a key waiting?
        lda ASCIIKEY
        beq l_tev_frame_work
        sta ASCIIKEY                    ; dequeue
        cmp #$ff
        beq l_tev_frame_work
        sta l_tev_raw
        lda #1
        sta l_tev_altused               ; ALT was part of a combination, not a tap
        lda MODKEY
        sta l_tev_rawm
        lda KEYDIRECT
        and #3
        sta l_tev_rawdir
        jsr l_tev_normalize
        bne l_tev_done
l_tev_frame_work:
        lda frame_count
        cmp l_tev_frame
        beq l_tev_none
        sta l_tev_frame
        lda l_tev_wait
        beq +
        dec l_tev_wait
+       jsr l_tev_cur_blink
        jsr l_tev_alt
        bne l_tev_done
        jsr l_tev_mouse
        lda l_tev_pend
        bne l_tev_report
l_tev_none:
        lda #EV_NONE
        sta tui_ev
l_tev_done:
        lda tui_ev
        rts
l_tev_report:
        lda l_tev_pend
        and #L_P_DOWN
        beq +
        lda #L_P_DOWN
        trb l_tev_pend
        lda #EV_DOWN
        bra l_tev_rep_out
+       lda l_tev_pend
        and #L_P_RDOWN
        beq +
        lda #L_P_RDOWN
        trb l_tev_pend
        lda #EV_RDOWN
        bra l_tev_rep_out
+       lda l_tev_pend
        and #L_P_DRAG
        beq +
        lda #L_P_DRAG
        trb l_tev_pend
        lda #EV_DRAG
        bra l_tev_rep_out
+       lda l_tev_pend
        and #L_P_REPEAT
        beq +
        lda #L_P_REPEAT
        trb l_tev_pend
        lda #EV_REPEAT
        bra l_tev_rep_out
+       lda #L_P_UP
        trb l_tev_pend
        lda #EV_UP
l_tev_rep_out:
        sta tui_ev
        rts

; next test record: A = tui_ev (non-zero if it made an event)
l_tev_script:
        lda l_tev_wait                  ; (counted down in the once-a-frame code)
        bne l_tev_s_no
        ldx tui_dbg_pos
        cpx tui_dbg_len
        bcs l_tev_s_no
        lda tui_dbg_q,x
        sta l_tev_raw
        lda tui_dbg_q+1,x
        pha
        lda tui_dbg_q+2,x
        tay
        pla
        inx
        inx
        inx
        stx tui_dbg_pos
        ldx l_tev_raw
        cpx #1
        bne +
        sta l_tev_raw
        lda #0
        cpy #$80
        bcc l_tev_s_dir
        lda #3
l_tev_s_dir:
        sta l_tev_rawdir
        tya
        and #$7f
        sta l_tev_rawm
        jmp l_tev_normalize
+       cpx #2
        bne +
        sta tui_mcol
        sty tui_mrow
        lda #1
        sta l_tev_dbgmouse
        lda l_tev_dbgold
        sta l_tev_dbgbtn
        jsr l_tev_dbg_moved
        bra l_tev_s_no
+       cpx #3
        bne +
        sta l_tev_dbgbtn
        lda #1
        sta l_tev_dbgmouse
        bra l_tev_s_no
+       cpx #4
        bne +
        sta l_tev_wait
        bra l_tev_s_no
+       cpx #5
        bne l_tev_s_no
        lda #TK_ALT
        sta tui_ev_key
        lda #0
        sta tui_ev_mods
        lda #EV_KEY
        sta tui_ev
        rts
l_tev_s_no:
        lda #EV_NONE
        rts

; a pointer jump by a test: report it like a move
l_tev_dbg_moved:
        lda tui_mcol
        asl
        asl
        clc
        adc #1
        sta mouse_x
        lda #0
        rol
        sta mouse_x+1
        lda tui_mrow
        asl
        asl
        asl
        clc
        adc #1
        sta mouse_y
        lda l_tev_dbgold
        and #1
        beq +
        lda #L_P_DRAG
        tsb l_tev_pend
+       jmp l_tev_place_ptr

; ALT: tapped alone counts as a key
l_tev_alt:
        lda MODKEY
        and #$10
        beq l_tev_alt_up
        lda l_tev_altdown
        bne l_tev_alt_no
        lda #1
        sta l_tev_altdown
        lda #0
        sta l_tev_altused
        bra l_tev_alt_no
l_tev_alt_up:
        lda l_tev_altdown
        beq l_tev_alt_no
        lda #0
        sta l_tev_altdown
        lda l_tev_altused
        bne l_tev_alt_no
        lda #TK_ALT
        sta tui_ev_key
        lda #0
        sta tui_ev_mods
        lda #EV_KEY
        sta tui_ev
        rts
l_tev_alt_no:
        lda #EV_NONE
        rts

l_tev_mouse:
        lda l_tev_dbgmouse
        beq +
        jmp l_tev_dbg_buttons
+       jsr mouse_poll
        ; moved?
        lda mouse_x
        cmp l_tev_oldx
        bne l_tev_mv
        lda mouse_x+1
        cmp l_tev_oldx+1
        bne l_tev_mv
        lda mouse_y
        cmp l_tev_oldy
        beq l_tev_btn
l_tev_mv:
        lda mouse_x
        sta l_tev_oldx
        lda mouse_x+1
        sta l_tev_oldx+1
        lda mouse_y
        sta l_tev_oldy
        jsr l_tev_move_ptr
        ; cell
        lda mouse_x+1                   ; col = x / 4
        lsr
        lda mouse_x
        ror
        lsr
        cmp tui_mcol
        sta tui_mcol
        php
        lda mouse_y                     ; row = y / 8
        lsr
        lsr
        lsr
        cmp tui_mrow
        sta tui_mrow
        beq +
        plp
        bra l_tev_cell
+       plp
        beq l_tev_btn
l_tev_cell:
        lda l_tev_lheld
        beq l_tev_btn
        lda #L_P_DRAG
        tsb l_tev_pend
l_tev_btn:
        lda mouse_left_click
        beq +
        jsr l_tev_clicked
+       lda mouse_left_release
        beq +
        lda #0
        sta l_tev_lheld
        lda #L_P_UP
        tsb l_tev_pend
+       lda mouse_right_click
        beq +
        jsr l_tev_ensure_ptr
        lda #L_P_RDOWN
        tsb l_tev_pend
+       jmp l_tev_repeat

l_tev_dbg_buttons:
        lda l_tev_dbgbtn
        eor l_tev_dbgold
        sta l_tev_raw                   ; changed bits
        lda l_tev_dbgbtn
        sta l_tev_dbgold
        lda l_tev_raw
        and #1
        beq l_tev_db2
        lda l_tev_dbgbtn
        and #1
        beq +
        jsr l_tev_clicked
        bra l_tev_db2
+       lda #0
        sta l_tev_lheld
        lda #L_P_UP
        tsb l_tev_pend
l_tev_db2:
        lda l_tev_raw
        and #2
        beq l_tev_repeat
        lda l_tev_dbgbtn
        and #2
        beq l_tev_repeat
        jsr l_tev_ensure_ptr
        lda #L_P_RDOWN
        tsb l_tev_pend
l_tev_repeat:
        lda l_tev_lheld
        beq l_tev_r_end
        dec l_tev_rep
        bne l_tev_r_end
        lda #TUI_REPEAT2
        sta l_tev_rep
        lda #L_P_REPEAT
        tsb l_tev_pend
l_tev_r_end:
        rts

l_tev_clicked:
        jsr l_tev_ensure_ptr
        lda #1
        sta l_tev_lheld
        lda #TUI_REPEAT1
        sta l_tev_rep
        lda #L_P_DOWN
        tsb l_tev_pend
        lda #0
        sta tui_dbl
        lda tui_mrow
        cmp l_tev_lastrow
        bne l_tev_c1
        lda tui_mcol
        cmp l_tev_lastcol
        bne l_tev_c1
        sec
        lda frame_count
        sbc l_tev_lastclk
        cmp #TUI_DBLCLICK
        bcs l_tev_c1
        lda #1
        sta tui_dbl
        lda #$ff                        ; a third click starts again
        sta l_tev_lastrow
        rts
l_tev_c1:
        lda tui_mrow
        sta l_tev_lastrow
        lda tui_mcol
        sta l_tev_lastcol
        lda frame_count
        sta l_tev_lastclk
        rts

l_tev_ensure_ptr:
        lda l_tev_ptr_on
        beq l_tev_place_ptr
        rts

tui_pointer_hide:
        lda l_tev_ptr_on
        beq l_tev_ph_end
        lda #0
        sta l_tev_ptr_on
        lda #1
        sta l_tev_hidden
        lda mouse_x
        sta l_tev_hx
        lda mouse_x+1
        sta l_tev_hx+1
        lda mouse_y
        sta l_tev_hy
        ldx #TUI_SPR_OUTLINE
        jsr hws_off
        ldx #TUI_SPR_FILL
        jsr hws_off
l_tev_ph_end:
        rts

; the mouse moved. A pointer hidden for typing stays hidden until it's moved more than a jitter.
l_tev_move_ptr:
        lda l_tev_hidden
        beq l_tev_place_ptr
        sec
        lda mouse_x
        sbc l_tev_hx
        tax
        lda mouse_x+1
        sbc l_tev_hx+1
        bpl +
        ; moved left: make the distance positive. More than 255 is far enough.
        cmp #$FF
        bne l_tev_place_ptr
        txa
        eor #$FF
        inc a
        beq l_tev_place_ptr             ; (exactly -256)
        tax
        lda #0
+       bne l_tev_place_ptr
        cpx #TUI_HIDE_SLOP
        bcs l_tev_place_ptr
        sec
        lda mouse_y
        sbc l_tev_hy
        bcs +
        eor #$FF
        inc a
+       cmp #TUI_HIDE_SLOP
        bcs l_tev_place_ptr
        rts

; show the pointer (first movement) and put it where the mouse is
l_tev_place_ptr:
        lda mouse_x
        sta hws_x
        lda mouse_x+1
        sta hws_x+1
        lda mouse_y
        sta hws_y
        lda #0
        sta hws_y+1
        ldx #TUI_SPR_OUTLINE
        jsr hws_place
        lda mouse_x
        sta hws_x
        lda mouse_x+1
        sta hws_x+1
        lda mouse_y
        sta hws_y
        lda #0
        sta hws_y+1
        ldx #TUI_SPR_FILL
        jsr hws_place
        lda l_tev_ptr_on
        bne +
        lda #1
        sta l_tev_ptr_on
        lda #0
        sta l_tev_hidden
        ldx #TUI_SPR_OUTLINE
        jsr hws_on
        ldx #TUI_SPR_FILL
        jsr hws_on
+       rts

; l_tev_raw, l_tev_rawm -> an event, or A = 0 if the key means nothing here
l_tev_normalize:
        ; modifiers
        lda #0
        sta tui_ev_mods
        lda l_tev_rawm
        and #%00000011
        beq +
        lda #KM_SHIFT
        tsb tui_ev_mods
+       lda l_tev_rawm
        and #%00000100
        beq +
        lda #KM_CTRL
        tsb tui_ev_mods
+       lda l_tev_rawm
        and #%00001000
        beq +
        lda #KM_MEGA
        tsb tui_ev_mods
+       lda l_tev_rawm
        and #%00010000
        beq +
        lda #KM_ALT
        tsb tui_ev_mods
+       lda l_tev_raw
        cmp #$9D
        beq l_tev_n_rev
        cmp #$91
        beq l_tev_n_rev
        cmp #$1D
        bne +
        lda #TK_RIGHT
        jmp l_tev_n_key
+       cmp #$11
        bne l_tev_n_notdown
        lda tui_ev_mods                 ; CTRL+Q is the same code as cursor down
        and #KM_CTRL
        beq +
        lda #'Q'
        jmp l_tev_n_key
+       lda #TK_DOWN
        jmp l_tev_n_key
l_tev_n_rev:
        ; a left/up code: see the top of the file
        lda l_tev_raw
        cmp #$9D
        beq +
        lda #2                          ; $91: the up key's bit
        bra ++
+       lda #1                          ; $9D: the left key's bit
+       and l_tev_rawdir
        beq l_tev_n_notkey
        ; that key is down, and brings one shift of its own
        lda l_tev_rawm
        and #%00000011
        cmp #%00000011
        beq l_tev_n_rev_key
        lda #KM_SHIFT
        trb tui_ev_mods
        bra l_tev_n_rev_key
l_tev_n_notkey:
        ; not those keys: SHIFT or CTRL with right or down. (With neither, the key was let go
        ; before we got here, or the code is all there is: believe the code.)
        lda tui_ev_mods
        and #KM_SHIFT | KM_CTRL
        beq l_tev_n_rev_key
        lda l_tev_raw
        cmp #$9D
        bne +
        lda #TK_RIGHT
        jmp l_tev_n_key
+       lda #TK_DOWN
        jmp l_tev_n_key
l_tev_n_rev_key:
        lda l_tev_raw
        cmp #$9D
        bne +
        lda #TK_LEFT
        jmp l_tev_n_key
+       lda #TK_UP
        jmp l_tev_n_key

l_tev_n_notdown:
        ; table of special codes
        ldx #0
-       lda l_tev_codes,x
        beq l_tev_n_other
        cmp l_tev_raw
        beq +
        inx
        inx
        bra -
+       lda l_tev_codes+1,x
        ; those that are also CTRL+letter
        pha
        lda tui_ev_mods
        and #KM_CTRL
        beq l_tev_n_nc
        lda l_tev_raw
        cmp #$1B                        ; below this: a control code from CTRL+letter
        bcs l_tev_n_nc
        cmp #$0D                        ; CTRL+M stays RETURN
        beq l_tev_n_nc
        cmp #$09                        ; CTRL+I stays TAB
        beq l_tev_n_nc
        pla
        bra l_tev_n_letter
l_tev_n_nc:
        pla
        ; the keys that depend on modifiers
        cmp #TK_END
        bne l_tev_n_key
        ; $93: SHIFT = end of line, CTRL = top of file, both = end of file
        lda tui_ev_mods
        and #KM_SHIFT | KM_CTRL
        cmp #KM_SHIFT | KM_CTRL
        bne +
        lda #TK_EOF
        bra l_tev_n_nomod
+       cmp #KM_CTRL
        bne +
        lda #TK_BOF
        bra l_tev_n_nomod
+       lda #TK_END
l_tev_n_nomod:
        pha
        lda #KM_SHIFT | KM_CTRL
        trb tui_ev_mods
        pla
        bra l_tev_n_key
l_tev_n_other:
        lda l_tev_raw
        cmp #$1B
        bcs +
        ; a control code with no table entry: only meaningful with CTRL
l_tev_n_letter:
        lda tui_ev_mods
        and #KM_CTRL
        beq l_tev_n_nothing
        lda l_tev_raw
        clc
        adc #64
        bra l_tev_n_key
+       cmp #$20
        bcc l_tev_n_nothing
        cmp #$7F
        bcc l_tev_n_key                 ; printable
        cmp #$C1
        bcc +
        cmp #$DB
        bcs +
        ; MEGA+letter
        sec
        sbc #$80
        bra l_tev_n_key
+       cmp #$A0                        ; ALT+SPACE
        bne +
        lda #32
        bra l_tev_n_key
+       cmp #$A3                        ; the pound key: its CP437 code
        bne l_tev_n_nothing
        lda #$9C
l_tev_n_key:
        sta tui_ev_key
        lda #EV_KEY
        sta tui_ev
        rts
l_tev_n_nothing:
        lda #EV_NONE
        sta tui_ev
        rts

; raw code, event key
l_tev_codes:
        .byte $0D, TK_ENTER
        .byte $1B, TK_ESC
        .byte $03, TK_ESC               ; RUN/STOP (CTRL+C otherwise)
        .byte $09, TK_TAB
        .byte $0F, TK_BTAB              ; SHIFT+TAB (CTRL+O otherwise)
        .byte $14, TK_BKSP              ; (CTRL+T otherwise)
        .byte $94, TK_INS
        .byte $7F, TK_DEL
        .byte $13, TK_HOME              ; (CTRL+S otherwise)
        .byte $93, TK_END
        .byte $1F, TK_F1                ; HELP
        .byte $F1, TK_F1
        .byte $F3, TK_F3
        .byte $F5, TK_F5
        .byte $F6, TK_F6
        .byte $F7, TK_F7
        .byte $F8, TK_F8
        .byte $F9, TK_PGUP
        .byte $FA, TK_PGUP
        .byte $FB, TK_PGDN
        .byte $FC, TK_PGDN
        .byte 0

; Shapes: 3 bytes a row, 21 rows. Pixels are 2 screen pixels wide.
        .align 64
l_tev_arrow_o:
        .byte %11000000, 0, 0
        .byte %11100000, 0, 0
        .byte %11110000, 0, 0
        .byte %11111000, 0, 0
        .byte %11111100, 0, 0
        .byte %11111110, 0, 0
        .byte %11111111, 0, 0
        .byte %11111111, %10000000, 0
        .byte %11111111, %11000000, 0
        .byte %11111110, 0, 0
        .byte %11101111, 0, 0
        .byte %11000111, 0, 0
        .byte %00000111, %10000000, 0
        .byte %00000011, %10000000, 0
        .fill 21 * 3 - 14 * 3
        .align 64
l_tev_arrow_f:
        .byte %00000000, 0, 0
        .byte %01000000, 0, 0
        .byte %01100000, 0, 0
        .byte %01110000, 0, 0
        .byte %01111000, 0, 0
        .byte %01111100, 0, 0
        .byte %01111110, 0, 0
        .byte %01111111, 0, 0
        .byte %01111100, 0, 0
        .byte %01101100, 0, 0
        .byte %01000110, 0, 0
        .byte %00000110, 0, 0
        .byte %00000011, 0, 0
        .byte %00000000, 0, 0
        .fill 21 * 3 - 14 * 3
        .align 64
l_tev_cur_line:
        .fill 6 * 3
        .byte %11110000, 0, 0
        .byte %11110000, 0, 0
        .fill 13 * 3
        .align 64
l_tev_cur_block:
        .byte %11110000, 0, 0
        .byte %11110000, 0, 0
        .byte %11110000, 0, 0
        .byte %11110000, 0, 0
        .byte %11110000, 0, 0
        .byte %11110000, 0, 0
        .byte %11110000, 0, 0
        .byte %11110000, 0, 0
        .fill 13 * 3
