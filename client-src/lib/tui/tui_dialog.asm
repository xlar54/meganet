;=======================================================================================
; lib/tui/tui_dialog.asm - modal dialogs built from a table, for keyboard and mouse.
; Needs tui_screen.asm and tui_event.asm.
;
;   tui_dialog       A/X = dialog: runs it. A = the id of the button pressed, 0 = cancelled
;                    (Esc). The screen is put back as it was.
;   tui_msgbox       A/X = one line of text, Y = MB_OK, MB_YESNOCANCEL, MB_OKCANCEL: A =
;                    ID_OK / ID_YES, ID_NO, or 0
;   tui_dlg_redraw   X = control number: draw it again (after a hook changes its data)
;   tui_strlen       A/X = string: A = its length, tui_str = its address
;   tui_dlg_refield  after a hook changes the focused text field's contents: tidy its cursor
;
; Dialogs nest: a hook may call tui_dialog or tui_msgbox, and its own dialog carries on after.
;   tui_dlg_focus    the control number to start on: set it just before tui_dialog, it is
;                    used once ($ff = the first one that takes focus)
;   tui_dc_*         the colours
;
; A dialog is a header and controls, ended by DLG_END. Rows and columns count from the
; dialog's own top-left corner; the dialog is centred on the screen.
;   DLG h, w, title, hook     hook = 0, or a routine: A = reason, X = control number.
;       DH_LIST    the list's selection moved
;       DH_BUTTON  a button was pressed (tui_dlg_result = its id). Carry set stays open.
;       DH_TOGGLE  a check box or radio button changed
;       DH_INIT    the dialog has just been drawn (X = 0): paint anything extra
;   DLG_LABEL row, col, text                      col DLG_AUTO: centred in the dialog
;   DLG_TEXT row, col, width, buffer, maxlen, upper   a framed one-line field. Buffer is
;                    zero-terminated; upper = 1 forces upper case.
;   DLG_CHECK row, col, text, var                 var = 0 or 1
;   DLG_RADIO row, col, text, var, value          on when var = value
;   DLG_BUTTON row, col, text, id, default        default = 1: what RETURN presses.
;                                                 Its shadow needs the row below it free.
;                    col DLG_AUTO: the DLG_AUTO buttons on a row are spaced and centred
;   DLG_LIST row, col, width, height, provider, state     framed, with a scroll bar.
;       state = .word count, top, selected. provider: A/X = item number -> A/X = string.
;   DLG_FRAME row, col, height, width, title      a labelled group
;   DLG_HLINE row                                 a line across the dialog
;=======================================================================================

        .include "tui_dialog.inc"       ; (next to this file)

L_DC_TYPE       = 0
L_DC_ROW        = 1
L_DC_COL        = 2
L_DC_W          = 3
L_DC_P1         = 4
L_DC_P2         = 6
L_DC_ID         = 8
L_DC_SIZE       = 9
L_DLG_HDR       = 6

tui_dc_box:     .byte $70
tui_dc_hot:     .byte $7F
tui_dc_edit:    .byte $70
tui_dc_editsel: .byte $07
tui_dc_listsel: .byte $07
tui_dc_btn:     .byte $17               ; a button: grey on blue
tui_dc_btnfoc:  .byte $1F               ; the focused or default one: white on blue
tui_dc_btncan:  .byte $40               ; the background of a cancelling button (ID 0): red

tui_dlg_result: .byte 0
tui_dlg_focus:  .byte $ff

l_dl_def:       .word 0
l_dl_top:       .byte 0
l_dl_left:      .byte 0
l_dl_h:         .byte 0
l_dl_w:         .byte 0
l_dl_n:         .byte 0
l_dl_foc:       .byte 0
l_dl_hook:      .word 0
l_dl_press:     .byte $ff               ; the button being held
l_dl_i:         .byte 0
l_dl_t:         .byte 0
l_dl_t2:        .byte 0
l_dl_row:       .byte 0                 ; screen row and column of the current control
l_dl_col:       .byte 0
; text field being edited
l_dt_pos:       .byte 0
l_dt_sel:       .byte 0
l_dt_off:       .byte 0
l_dt_len:       .byte 0
; list being handled
l_dl_state:     .word 0
l_dl_lcount:    .word 0
l_dl_ltop:      .word 0
l_dl_lsel:      .word 0
l_dl_lh:        .byte 0
l_dl_vec:       .word 0
l_dl_state_len = * - l_dl_def

; tui_dp = control X
l_dl_ctl:
        stx l_dl_t
        lda l_dl_def
        clc
        adc #L_DLG_HDR
        sta tui_dp
        lda l_dl_def+1
        adc #0
        sta tui_dp+1
        cpx #0
        beq +
-       clc
        lda tui_dp
        adc #L_DC_SIZE
        sta tui_dp
        bcc *+4
        inc tui_dp+1
        dex
        bne -
+       ldx l_dl_t
        ; screen position
        ldy #L_DC_ROW
        lda (tui_dp),y
        clc
        adc l_dl_top
        sta l_dl_row
        ldy #L_DC_COL
        lda (tui_dp),y
        clc
        adc l_dl_left
        sta l_dl_col
        rts

; length of the string at A/X -> A. tui_str points at it.
tui_strlen:
l_dl_slen:
        sta tui_str
        stx tui_str+1
        ldy #0
-       lda (tui_str),y
        beq +
        iny
        bne -
+       tya
        rts

; A/X = the control's P1 word
l_dl_p1:
        ldy #L_DC_P1
        lda (tui_dp),y
        pha
        iny
        lda (tui_dp),y
        tax
        pla
        rts

tui_dialog:
        ; the outer dialog's state goes on the stack, in case this was called from a hook
        sta l_dl_ax
        stx l_dl_ax+1
        ldx #0
-       lda l_dl_def,x
        pha
        inx
        cpx #l_dl_state_len
        bne -
        lda l_dl_ax
        ldx l_dl_ax+1
        jsr l_dl_run
        sta l_dl_ax
        ldx #l_dl_state_len - 1
-       pla
        sta l_dl_def,x
        dex
        bpl -
        lda l_dl_ax
        rts
l_dl_ax:        .word 0

tui_dlg_refield:
        ldx l_dl_foc
        jsr l_dl_got_focus
        ldx l_dl_foc
        jmp tui_dlg_redraw

l_dl_run:
        sta l_dl_def
        sta tui_dp
        stx l_dl_def+1
        stx tui_dp+1
        ldy #0
        lda (tui_dp),y
        sta l_dl_h
        iny
        lda (tui_dp),y
        sta l_dl_w
        ldy #4
        lda (tui_dp),y
        sta l_dl_hook
        iny
        lda (tui_dp),y
        sta l_dl_hook+1
        sec
        lda #TUI_ROWS
        sbc l_dl_h
        lsr
        sta l_dl_top
        sec
        lda #TUI_COLS
        sbc l_dl_w
        lsr
        sta l_dl_left
        ; count the controls
        ldx #0
-       jsr l_dl_ctl
        ldy #0
        lda (tui_dp),y
        beq +
        inx
        bra -
+       stx l_dl_n
        jsr l_dl_layout
        lda #$ff
        sta l_dl_press
        jsr tui_cursor_off
        jsr tui_push
        ; the box
        lda tui_dc_hot
        sta tui_hotattr
        lda tui_dc_box
        jsr tui_setattr
        lda l_dl_top
        sta tui_r
        lda l_dl_left
        sta tui_c
        lda l_dl_h
        sta tui_h
        lda l_dl_w
        sta tui_w
        lda l_dl_def
        sta tui_dp
        lda l_dl_def+1
        sta tui_dp+1
        ldy #2
        lda (tui_dp),y
        pha
        iny
        lda (tui_dp),y
        tax
        pla
        jsr tui_box
        jsr tui_shadow
        ; focus
        lda tui_dlg_focus
        sta l_dl_foc
        lda #$ff
        sta tui_dlg_focus
        lda l_dl_foc
        cmp #$ff
        bne +
        lda #0
        sta l_dl_foc
        ldx l_dl_foc
        jsr l_dl_takes
        bcc +
        jsr l_dl_next_focus
+       ldx l_dl_foc
        jsr l_dl_got_focus
        jsr l_dl_draw_all
        lda #DH_INIT
        ldx #0
        jsr l_dl_call_hook
        jsr l_dl_place
l_dl_loop:
        jsr tui_wait_event
        cmp #EV_KEY
        bne +
        jmp l_dl_key
+       cmp #EV_DOWN
        bne +
        jmp l_dl_down
+       cmp #EV_UP
        bne +
        jmp l_dl_up
+       cmp #EV_REPEAT
        bne l_dl_loop
        jmp l_dl_repeat

; give every DLG_AUTO control its column. (Once only: the table keeps the result.)
l_dl_layout:
        lda #0
        sta l_la_i
l_la_loop:
        ldx l_la_i
        cpx l_dl_n
        bcc +
        rts
+       jsr l_dl_ctl
        ldy #L_DC_COL
        lda (tui_dp),y
        cmp #DLG_AUTO
        bne l_la_next
        ldy #L_DC_TYPE
        lda (tui_dp),y
        cmp #DC_BUTTON
        beq l_la_buttons
        cmp #DC_LABEL
        bne l_la_next
        jsr l_dl_p1
        jsr l_dl_slen
        sta l_la_t
        sec
        lda l_dl_w
        sbc l_la_t
        lsr
        ldy #L_DC_COL
        sta (tui_dp),y
l_la_next:
        inc l_la_i
        bra l_la_loop

l_la_buttons:
        ldy #L_DC_ROW
        lda (tui_dp),y
        sta l_la_row
        ; their total width, and how many
        lda #0
        sta l_la_total
        sta l_la_n
        lda l_la_i
        sta l_la_j
l_la_measure:
        jsr l_la_this
        bcs +
        clc
        adc l_la_total
        sta l_la_total
        inc l_la_n
+       inc l_la_j
        lda l_la_j
        cmp l_dl_n
        bcc l_la_measure
        ; three cells between them, or one if that wouldn't fit
        lda #3
        sta l_la_gap
        jsr l_la_span
        clc
        adc #4                          ; the frame and a cell inside it, each side
        cmp l_dl_w
        bcc +
        beq +
        lda #1
        sta l_la_gap
        jsr l_la_span
+       jsr l_la_span
        sta l_la_t
        sec
        lda l_dl_w
        sbc l_la_t
        lsr
        sta l_la_pos
        ; place them
        lda l_la_i
        sta l_la_j
l_la_place:
        jsr l_la_this
        bcs +
        clc
        adc l_la_gap
        pha
        lda l_la_pos
        ldy #L_DC_COL
        sta (tui_dp),y
        pla
        clc
        adc l_la_pos
        sta l_la_pos
+       inc l_la_j
        lda l_la_j
        cmp l_dl_n
        bcc l_la_place
        jmp l_la_next

; control l_la_j: carry clear and A = its width, if it's a DLG_AUTO button on this row
l_la_this:
        ldx l_la_j
        jsr l_dl_ctl
        ldy #L_DC_TYPE
        lda (tui_dp),y
        cmp #DC_BUTTON
        bne l_la_no
        ldy #L_DC_COL
        lda (tui_dp),y
        cmp #DLG_AUTO
        bne l_la_no
        ldy #L_DC_ROW
        lda (tui_dp),y
        cmp l_la_row
        bne l_la_no
        jsr l_dl_p1
        jsr l_dl_slen
        clc
        adc #4                          ; "< " and " >"
        clc
        rts
l_la_no:
        sec
        rts

; A = total width + the gaps between l_la_n buttons
l_la_span:
        lda l_la_total
        ldx l_la_n
-       dex
        beq +
        clc
        adc l_la_gap
        bra -
+       rts

l_la_i:         .byte 0
l_la_j:         .byte 0
l_la_t:         .byte 0
l_la_row:       .byte 0
l_la_total:     .byte 0
l_la_n:         .byte 0
l_la_gap:       .byte 0
l_la_pos:       .byte 0

l_dl_exit:
        sta tui_dlg_result
        jsr tui_cursor_off
        jsr tui_pop
        lda tui_dlg_result
        rts

l_dl_draw_all:
        lda #0
        sta l_dl_i
-       lda l_dl_i
        cmp l_dl_n
        beq +
        tax
        jsr tui_dlg_redraw
        inc l_dl_i
        bra -
+       rts

tui_dlg_redraw:
        stx l_dl_rd
        jsr l_dl_ctl
        lda tui_dc_box
        jsr tui_setattr
        ldy #L_DC_TYPE
        lda (tui_dp),y
        cmp #DC_LABEL
        bne +
        ldx l_dl_row
        ldy l_dl_col
        jsr tui_goto
        jsr l_dl_p1
        jmp tui_puts
+       cmp #DC_TEXT
        bne +
        jmp l_dl_draw_text
+       cmp #DC_CHECK
        bne +
        jmp l_dl_draw_check
+       cmp #DC_RADIO
        bne +
        jmp l_dl_draw_radio
+       cmp #DC_BUTTON
        bne +
        jmp l_dl_draw_button
+       cmp #DC_LIST
        bne +
        jmp l_dl_draw_list
+       cmp #DC_FRAME
        bne +
        jmp l_dl_draw_frame
+       ; DC_HLINE
        ldx l_dl_row
        ldy l_dl_left
        jsr tui_goto
        lda #TG_LTEE
        jsr tui_putc
        lda #TG_HLINE
        ldx l_dl_w
        dex
        dex
        jsr tui_rep
        lda #TG_RTEE
        jmp tui_putc
l_dl_rd:        .byte 0

l_dl_draw_frame:
        lda l_dl_row
        sta tui_r
        lda l_dl_col
        sta tui_c
        ldy #L_DC_P2
        lda (tui_dp),y
        sta tui_h
        ldy #L_DC_W
        lda (tui_dp),y
        sta tui_w
        jsr l_dl_p1
        sta l_tui_title
        stx l_tui_title+1
        jsr tui_frame
        jmp tui_title

l_dl_draw_check:
        ldx l_dl_row
        ldy l_dl_col
        jsr tui_goto
        lda #'['
        jsr tui_putc
        ldy #L_DC_P2
        lda (tui_dp),y
        sta tui_str
        iny
        lda (tui_dp),y
        sta tui_str+1
        ldy #0
        lda (tui_str),y
        beq +
        lda #'X'
        bra ++
+       lda #32
+       jsr tui_putc
        lda #']'
        bra l_dl_mark_text

l_dl_draw_radio:
        ldx l_dl_row
        ldy l_dl_col
        jsr tui_goto
        lda #'('
        jsr tui_putc
        ldy #L_DC_P2
        lda (tui_dp),y
        sta tui_str
        iny
        lda (tui_dp),y
        sta tui_str+1
        ldy #0
        lda (tui_str),y
        ldy #L_DC_ID
        cmp (tui_dp),y
        bne +
        lda #TG_BULLET
        bra ++
+       lda #32
+       jsr tui_putc
        lda #')'
l_dl_mark_text:
        jsr tui_putc
        lda #32
        jsr tui_putc
        jsr l_dl_p1
        jmp tui_puts

l_dl_draw_button:
        ldx l_dl_row
        ldy l_dl_col
        jsr tui_goto
        ; a solid block. Bright for the focused button, or the default one when no button has focus
        lda tui_dc_btn
        sta l_dl_t2
        ldx l_dl_foc
        cpx l_dl_rd
        beq l_dl_b_hi
        ldy #L_DC_P2
        lda (tui_dp),y
        beq l_dl_b_put
        ; default button: bright unless another button has focus
        phy
        ldx l_dl_foc
        jsr l_dl_type_of
        ply
        cmp #DC_BUTTON
        beq l_dl_b_put
l_dl_b_hi:
        lda tui_dc_btnfoc
        sta l_dl_t2
l_dl_b_put:
        ldx l_dl_rd
        jsr l_dl_ctl
        ldy #L_DC_ID
        lda (tui_dp),y
        bne +
        lda l_dl_t2
        and #$0F
        ora tui_dc_btncan
        sta l_dl_t2
+       lda l_dl_t2
        jsr tui_setattr
        lda #32
        ldx #2
        jsr tui_rep
        jsr l_dl_p1
        jsr tui_puts
        lda #32
        ldx #2
        jsr tui_rep
        ; its shadow: half a cell to the right, half a cell below. Keep the row under a button free.
        lda tui_dc_box
        and #$F0
        jsr tui_setattr
        lda #TG_LOWER
        jsr tui_putc
        ldx l_dl_row
        inx
        ldy l_dl_col
        iny
        jsr tui_goto
        jsr l_dl_p1
        jsr l_dl_slen
        clc
        adc #4
        tax
        lda #TG_UPPER
        jmp tui_rep

; X = control: A = its type (tui_dp moves)
l_dl_type_of:
        jsr l_dl_ctl
        ldy #L_DC_TYPE
        lda (tui_dp),y
        rts

l_dl_draw_text:
        ; frame
        sec
        lda l_dl_row
        sbc #1
        sta tui_r
        sec
        lda l_dl_col
        sbc #1
        sta tui_c
        lda #3
        sta tui_h
        ldy #L_DC_W
        lda (tui_dp),y
        clc
        adc #2
        sta tui_w
        jsr tui_frame
        ldx l_dl_rd
        jsr l_dl_ctl
        ; the visible part
        jsr l_dl_p1
        sta l_dl_vec
        stx l_dl_vec+1
        ldx l_dl_row
        ldy l_dl_col
        jsr tui_goto
        lda tui_dc_edit
        ldx l_dl_rd
        cpx l_dl_foc
        bne +
        ldx l_dt_sel
        beq +
        lda tui_dc_editsel
+       jsr tui_setattr
        ldy #L_DC_W
        lda (tui_dp),y
        sta l_dl_t2                     ; cells to fill
        lda l_dl_vec
        sta tui_str
        lda l_dl_vec+1
        sta tui_str+1
        ldy #0
        ldx l_dl_rd
        cpx l_dl_foc
        bne +
        ldy l_dt_off
+
-       lda l_dl_t2
        beq l_dl_dt_end
        lda (tui_str),y
        beq l_dl_dt_pad
        jsr tui_putc
        iny
        dec l_dl_t2
        bra -
l_dl_dt_pad:
        lda tui_dc_edit
        jsr tui_setattr
        lda #32
        ldx l_dl_t2
        jsr tui_rep
l_dl_dt_end:
        rts

l_dl_draw_list:
        jsr l_dl_load_list
        ; frame
        sec
        lda l_dl_row
        sbc #1
        sta tui_r
        sec
        lda l_dl_col
        sbc #1
        sta tui_c
        clc
        lda l_dl_lh
        adc #2
        sta tui_h
        ldy #L_DC_W
        lda (tui_dp),y
        clc
        adc #2
        sta tui_w
        jsr tui_frame
        ldx l_dl_rd
        jsr l_dl_ctl
        lda #0
        sta l_dl_li
l_dl_dl_row:
        ldx l_dl_rd
        jsr l_dl_ctl
        clc
        lda l_dl_row
        adc l_dl_li
        tax
        ldy l_dl_col
        jsr tui_goto
        ; item number = top + row
        clc
        lda l_dl_ltop
        adc l_dl_li
        sta l_dl_item
        lda l_dl_ltop+1
        adc #0
        sta l_dl_item+1
        lda tui_dc_box
        sta l_dl_t2
        lda l_dl_item
        cmp l_dl_lsel
        bne +
        lda l_dl_item+1
        cmp l_dl_lsel+1
        bne +
        lda tui_dc_listsel
        sta l_dl_t2
+       lda l_dl_item+1
        cmp l_dl_lcount+1
        bcc l_dl_dl_item
        bne l_dl_dl_blank
        lda l_dl_item
        cmp l_dl_lcount
        bcc l_dl_dl_item
l_dl_dl_blank:
        lda tui_dc_box
        jsr tui_setattr
        ldy #L_DC_W
        lda (tui_dp),y
        tax
        lda #32
        jsr tui_rep
        bra l_dl_dl_next
l_dl_dl_item:
        lda l_dl_t2
        jsr tui_setattr
        lda #32
        jsr tui_putc
        lda tui_col
        sta l_dl_cstart
        lda l_dl_item
        ldx l_dl_item+1
        jsr l_dl_provider
        jsr tui_puts
        ; pad the rest of the row
        ldx l_dl_rd
        jsr l_dl_ctl_keep
        ldy #L_DC_W
        lda (tui_dp),y
        sec
        sbc #1
        sec
        sbc l_dl_used
        tax
        lda #32
        jsr tui_rep
l_dl_dl_next:
        inc l_dl_li
        lda l_dl_li
        cmp l_dl_lh
        beq +
        jmp l_dl_dl_row
+       ; scroll bar in the frame's right edge, when needed
        ldx l_dl_rd
        jsr l_dl_ctl
        lda l_dl_lcount+1
        bne l_dl_sb
        lda l_dl_lcount
        cmp l_dl_lh
        beq l_dl_sb_end
        bcc l_dl_sb_end
l_dl_sb:
        lda tui_dc_box
        jsr tui_setattr
        lda l_dl_row
        sta tui_r
        ldy #L_DC_W
        lda (tui_dp),y
        clc
        adc l_dl_col
        sta tui_c
        lda l_dl_lh
        sta tui_h
        lda l_dl_ltop
        sta tui_sb_pos
        lda l_dl_ltop+1
        sta tui_sb_pos+1
        sec
        lda l_dl_lcount
        sbc l_dl_lh
        sta tui_sb_range
        lda l_dl_lcount+1
        sbc #0
        sta tui_sb_range+1
        jsr tui_vscroll
l_dl_sb_end:
        rts
l_dl_li:        .byte 0
l_dl_item:      .word 0
l_dl_cstart:    .byte 0
l_dl_used:      .byte 0

; like l_dl_ctl, and measures how many cells the item used
l_dl_ctl_keep:
        sec
        lda tui_col
        sbc l_dl_cstart
        sta l_dl_used
        jmp l_dl_ctl

l_dl_provider:
        jmp (l_dl_vec)

; tui_dp = the list control: load its state
l_dl_load_list:
        ldy #L_DC_ID
        lda (tui_dp),y
        sta l_dl_lh
        ldy #L_DC_P1
        lda (tui_dp),y
        sta l_dl_vec
        iny
        lda (tui_dp),y
        sta l_dl_vec+1
        iny
        lda (tui_dp),y
        sta l_dl_state
        sta tui_str
        iny
        lda (tui_dp),y
        sta l_dl_state+1
        sta tui_str+1
        ldy #5
-       lda (tui_str),y
        sta l_dl_lcount,y
        dey
        bpl -
        rts

; l_dl_lcount.. -> the list's state
l_dl_save_list:
        lda l_dl_state
        sta tui_str
        lda l_dl_state+1
        sta tui_str+1
        ldy #5
-       lda l_dl_lcount,y
        sta (tui_str),y
        dey
        bpl -
        rts

; carry clear if control X takes focus
l_dl_takes:
        jsr l_dl_type_of
        cmp #DC_LABEL
        beq l_dl_tk_no
        cmp #DC_FRAME
        beq l_dl_tk_no
        cmp #DC_HLINE
        beq l_dl_tk_no
        clc
        rts
l_dl_tk_no:
        sec
        rts

l_dl_next_focus:
-       inc l_dl_foc
        lda l_dl_foc
        cmp l_dl_n
        bcc +
        lda #0
        sta l_dl_foc
+       ldx l_dl_foc
        jsr l_dl_takes
        bcs -
        rts
l_dl_prev_focus:
-       lda l_dl_foc
        bne +
        lda l_dl_n
        sta l_dl_foc
+       dec l_dl_foc
        ldx l_dl_foc
        jsr l_dl_takes
        bcs -
        rts

; prepare control X for typing
l_dl_got_focus:
        jsr l_dl_type_of
        cmp #DC_TEXT
        bne +
        jsr l_dl_p1
        jsr l_dl_slen
        sta l_dt_len
        sta l_dt_pos
        lda #1
        sta l_dt_sel
        lda #0
        sta l_dt_off
        jsr l_dt_scrollfix
+       rts

; change focus to A
l_dl_set_focus:
        cmp l_dl_foc
        beq l_dl_sf_end
        ldx l_dl_foc
        stx l_dl_oldf
        sta l_dl_foc
        tax
        jsr l_dl_got_focus
        ldx l_dl_oldf
        jsr tui_dlg_redraw
        jsr l_dl_redraw_buttons
        ldx l_dl_foc
        jsr tui_dlg_redraw
l_dl_sf_end:
        rts
l_dl_oldf:      .byte 0

; the default button's brightness depends on where focus is
l_dl_redraw_buttons:
        lda #0
        sta l_dl_i
-       lda l_dl_i
        cmp l_dl_n
        beq +
        tax
        jsr l_dl_type_of
        cmp #DC_BUTTON
        bne l_dl_rb_n
        ldx l_dl_i
        jsr tui_dlg_redraw
l_dl_rb_n:
        inc l_dl_i
        bra -
+       rts

; put the cursor on the focused control
l_dl_place:
        ldx l_dl_foc
        jsr l_dl_type_of
        sta l_dl_t2
        lda #TUI_BLACK
        sta tui_cursor_ink
        lda #0
        sta tui_cursor_big
        lda l_dl_t2
        cmp #DC_TEXT
        bne +
        sec
        lda l_dt_pos
        sbc l_dt_off
        clc
        adc l_dl_col
        tay
        ldx l_dl_row
        jmp tui_cursor_on
+       cmp #DC_BUTTON
        bne +
        lda #TUI_WHITE                  ; (on a coloured block)
        sta tui_cursor_ink
        ldy l_dl_col
        iny
        iny
        ldx l_dl_row
        jmp tui_cursor_on
+       cmp #DC_LIST
        bne +
        ldy #L_DC_ID
        jsr l_dl_load_list
        sec
        lda l_dl_lsel
        sbc l_dl_ltop
        clc
        adc l_dl_row
        tax
        ldy l_dl_col
        iny
        jmp tui_cursor_on
+       ldy l_dl_col                    ; check box or radio button
        iny
        ldx l_dl_row
        jmp tui_cursor_on

;---------------------------------------------------------------------------------------
; keys
;---------------------------------------------------------------------------------------
l_dl_key:
        lda tui_ev_key
        cmp #TK_ESC
        bne +
        lda #0
        jmp l_dl_exit
+       cmp #TK_TAB
        bne +
        lda l_dl_foc
        pha
        jsr l_dl_next_focus
        lda l_dl_foc
        jmp l_dl_focus_from_stack
+       cmp #TK_BTAB
        bne +
        lda l_dl_foc
        pha
        jsr l_dl_prev_focus
        lda l_dl_foc
l_dl_focus_from_stack:
        sta l_dl_t2
        pla
        sta l_dl_foc
        lda l_dl_t2
        jsr l_dl_set_focus
        jsr l_dl_place
        jmp l_dl_loop
+       cmp #TK_ENTER
        bne l_dl_k_type
        jsr l_dl_commit_text
        ; a focused button, else the default one
        ldx l_dl_foc
        jsr l_dl_type_of
        cmp #DC_BUTTON
        bne +
        ldx l_dl_foc
        jmp l_dl_press_x
+       jsr l_dl_press_default
        jmp l_dl_loop
l_dl_k_type:
        ldx l_dl_foc
        jsr l_dl_type_of
        cmp #DC_TEXT
        bne +
        jsr l_dt_key
        jsr l_dl_place
        jmp l_dl_loop
+       cmp #DC_LIST
        bne +
        jsr l_dl_list_key
        jsr l_dl_place
        jmp l_dl_loop
+       cmp #DC_BUTTON
        bne +
        lda tui_ev_key
        cmp #32
        bne l_dl_k_end
        ldx l_dl_foc
        jmp l_dl_press_x
+       ; check box or radio button
        lda tui_ev_key
        cmp #32
        bne +
        ldx l_dl_foc
        jsr l_dl_toggle
        jsr l_dl_place
        jmp l_dl_loop
+       cmp #TK_DOWN
        beq +
        cmp #TK_RIGHT
        bne ++
+       jsr l_dl_radio_step
        jmp l_dl_loop
+       cmp #TK_UP
        beq +
        cmp #TK_LEFT
        bne l_dl_k_end
+       jsr l_dl_radio_back
l_dl_k_end:
        jmp l_dl_loop

; the next or previous control, when it's a radio button: move there and turn it on
l_dl_radio_step:
        ldx l_dl_foc
        inx
        cpx l_dl_n
        bcs l_dl_rs_end
        bra l_dl_rs
l_dl_radio_back:
        ldx l_dl_foc
        beq l_dl_rs_end
        dex
l_dl_rs:
        stx l_dl_rsx
        jsr l_dl_type_of
        cmp #DC_RADIO
        bne l_dl_rs_end
        ldx l_dl_foc
        jsr l_dl_type_of
        cmp #DC_RADIO
        bne l_dl_rs_end
        lda l_dl_rsx
        jsr l_dl_set_focus
        ldx l_dl_foc
        jsr l_dl_toggle
        jmp l_dl_place
l_dl_rs_end:
        rts
l_dl_rsx:       .byte 0

; flip check box or set radio button X; all radio buttons on that variable redraw
l_dl_toggle:
        stx l_dl_tg
        jsr l_dl_type_of
        sta l_dl_t2
        ldy #L_DC_P2
        lda (tui_dp),y
        sta tui_str
        iny
        lda (tui_dp),y
        sta tui_str+1
        lda l_dl_t2
        cmp #DC_CHECK
        bne +
        ldy #0
        lda (tui_str),y
        eor #1
        sta (tui_str),y
        ldx l_dl_tg
        jsr tui_dlg_redraw
        bra l_dl_tg_hook
+       ldy #L_DC_ID
        lda (tui_dp),y
        ldy #0
        sta (tui_str),y
        lda #0
        sta l_dl_i
-       lda l_dl_i
        cmp l_dl_n
        beq l_dl_tg_hook
        tax
        jsr l_dl_type_of
        cmp #DC_RADIO
        bne +
        ldx l_dl_i
        jsr tui_dlg_redraw
+       inc l_dl_i
        bra -
l_dl_tg_hook:
        lda #DH_TOGGLE
        ldx l_dl_tg
        jsr l_dl_call_hook
        rts
l_dl_tg:        .byte 0

l_dl_call_hook:
        pha
        lda l_dl_hook
        ora l_dl_hook+1
        beq l_dl_nohook
        pla
        jmp (l_dl_hook)
l_dl_nohook:
        pla
        clc
        rts

; nothing to do yet: fields are live. (A place for validation.)
l_dl_commit_text:
        rts

l_dl_press_default:
        lda #0
        sta l_dl_i
-       lda l_dl_i
        cmp l_dl_n
        beq l_dl_pd_end
        tax
        jsr l_dl_type_of
        cmp #DC_BUTTON
        bne +
        ldy #L_DC_P2
        lda (tui_dp),y
        beq +
        ldx l_dl_i
        pla                             ; (drop the return: this ends the dialog or loops)
        pla
        jmp l_dl_press_x
+       inc l_dl_i
        bra -
l_dl_pd_end:
        rts

; press button X
l_dl_press_x:
        stx l_dl_px
        jsr l_dl_type_of
        ldy #L_DC_ID
        lda (tui_dp),y
        sta tui_dlg_result
        lda #DH_BUTTON
        ldx l_dl_px
        jsr l_dl_call_hook
        bcc +
        jsr l_dl_place
        jmp l_dl_loop                   ; the hook kept the dialog open
+       lda tui_dlg_result
        jmp l_dl_exit
l_dl_px:        .byte 0

;---------------------------------------------------------------------------------------
; text field
;---------------------------------------------------------------------------------------
l_dt_buf_ptr:
        ldx l_dl_foc
        jsr l_dl_ctl
        jsr l_dl_p1
        sta tui_str
        stx tui_str+1
        rts

; keep the cursor inside the visible part
l_dt_scrollfix:
        ldx l_dl_foc
        jsr l_dl_ctl
        lda l_dt_pos
        cmp l_dt_off
        bcs +
        sta l_dt_off
+       sec
        lda l_dt_pos
        sbc l_dt_off
        ldy #L_DC_W
        cmp (tui_dp),y
        bcc +
        lda l_dt_pos
        sec
        sbc (tui_dp),y
        clc
        adc #1
        sta l_dt_off
+       rts

l_dt_key:
        jsr l_dt_buf_ptr
        lda tui_ev_key
        cmp #TK_LEFT
        bne +
        lda l_dt_pos
        beq l_dt_unsel
        dec l_dt_pos
        bra l_dt_unsel
+       cmp #TK_RIGHT
        bne +
        lda l_dt_pos
        cmp l_dt_len
        bcs l_dt_unsel
        inc l_dt_pos
        bra l_dt_unsel
+       cmp #TK_HOME
        bne +
        lda #0
        sta l_dt_pos
        bra l_dt_unsel
+       cmp #TK_END
        bne +
        lda l_dt_len
        sta l_dt_pos
l_dt_unsel:
        lda #0
        sta l_dt_sel
        jmp l_dt_show
+       cmp #TK_BKSP
        bne l_dt_k1
        lda l_dt_sel
        bne l_dt_clear_show
        lda l_dt_pos
        beq l_dt_end
        dec l_dt_pos
        jsr l_dt_remove
        jmp l_dt_show
l_dt_k1:
        cmp #TK_DEL
        bne l_dt_k2
        lda l_dt_sel
        bne l_dt_clear_show
        lda l_dt_pos
        cmp l_dt_len
        bcs l_dt_end
        jsr l_dt_remove
        jmp l_dt_show
l_dt_clear_show:
        jsr l_dt_clear
        jmp l_dt_show
l_dt_k2:
        cmp #32
        bcc l_dt_end
        lda tui_ev_mods
        and #KM_CTRL | KM_MEGA
        bne l_dt_end
        ; printable
        lda l_dt_sel
        beq +
        jsr l_dt_clear
+       ldx l_dl_foc
        jsr l_dl_ctl
        ldy #L_DC_P2
        lda l_dt_len
        cmp (tui_dp),y
        bcs l_dt_show                   ; full
        ldy #L_DC_P2 + 1
        lda (tui_dp),y
        beq +
        lda tui_ev_key                  ; upper case
        cmp #'a'
        bcc +
        cmp #'z'+1
        bcs +
        and #$DF
        sta tui_ev_key
+       jsr l_dt_buf_ptr
        ; open a gap
        ldy l_dt_len
        iny
-       dey
        lda (tui_str),y
        iny
        sta (tui_str),y
        dey
        cpy l_dt_pos
        bne -
        lda tui_ev_key
        sta (tui_str),y
        inc l_dt_pos
        inc l_dt_len
l_dt_show:
        jsr l_dt_scrollfix
        ldx l_dl_foc
        jmp tui_dlg_redraw
l_dt_end:
        rts

; remove the character at l_dt_pos
l_dt_remove:
        jsr l_dt_buf_ptr
        ldy l_dt_pos
-       iny
        lda (tui_str),y
        dey
        sta (tui_str),y
        iny
        cpy l_dt_len
        bne -
        dec l_dt_len
        rts

l_dt_clear:
        jsr l_dt_buf_ptr
        lda #0
        ldy #0
        sta (tui_str),y
        sta l_dt_len
        sta l_dt_pos
        sta l_dt_sel
        sta l_dt_off
        rts

;---------------------------------------------------------------------------------------
; list
;---------------------------------------------------------------------------------------
l_dl_list_key:
        ldx l_dl_foc
        jsr l_dl_ctl
        jsr l_dl_load_list
        lda l_dl_lcount
        ora l_dl_lcount+1
        beq l_dl_lk_end
        lda tui_ev_key
        cmp #TK_UP
        bne +
        lda #1
        jmp l_dl_list_up
+       cmp #TK_DOWN
        bne +
        lda #1
        jmp l_dl_list_down
+       cmp #TK_PGUP
        bne +
        lda l_dl_lh
        jmp l_dl_list_up
+       cmp #TK_PGDN
        bne +
        lda l_dl_lh
        jmp l_dl_list_down
+       cmp #TK_HOME
        beq +
        cmp #TK_BOF
        bne ++
+       lda #0
        sta l_dl_lsel
        sta l_dl_lsel+1
        jmp l_dl_list_moved
+       cmp #TK_END
        beq +
        cmp #TK_EOF
        bne l_dl_lk_end
+       sec
        lda l_dl_lcount
        sbc #1
        sta l_dl_lsel
        lda l_dl_lcount+1
        sbc #0
        sta l_dl_lsel+1
        jmp l_dl_list_moved
l_dl_lk_end:
        rts

l_dl_list_up:
        sta l_dl_t
        sec
        lda l_dl_lsel
        sbc l_dl_t
        sta l_dl_lsel
        lda l_dl_lsel+1
        sbc #0
        sta l_dl_lsel+1
        bcs l_dl_list_moved
        lda #0
        sta l_dl_lsel
        sta l_dl_lsel+1
        bra l_dl_list_moved
l_dl_list_down:
        clc
        adc l_dl_lsel
        sta l_dl_lsel
        lda l_dl_lsel+1
        adc #0
        sta l_dl_lsel+1
        cmp l_dl_lcount+1
        bcc l_dl_list_moved
        bne +
        lda l_dl_lsel
        cmp l_dl_lcount
        bcc l_dl_list_moved
+       sec
        lda l_dl_lcount
        sbc #1
        sta l_dl_lsel
        lda l_dl_lcount+1
        sbc #0
        sta l_dl_lsel+1
; keep the selection on screen, store, draw, tell the hook
l_dl_list_moved:
        ; above the top?
        lda l_dl_lsel+1
        cmp l_dl_ltop+1
        bcc l_dl_lm_top
        bne l_dl_lm_b
        lda l_dl_lsel
        cmp l_dl_ltop
        bcs l_dl_lm_b
l_dl_lm_top:
        lda l_dl_lsel
        sta l_dl_ltop
        lda l_dl_lsel+1
        sta l_dl_ltop+1
        bra l_dl_lm_go
l_dl_lm_b:
        ; below the bottom? bottom = top + h
        clc
        lda l_dl_ltop
        adc l_dl_lh
        sta l_dl_t
        lda l_dl_ltop+1
        adc #0
        cmp l_dl_lsel+1
        bcc l_dl_lm_down
        bne l_dl_lm_go
        lda l_dl_lsel
        cmp l_dl_t
        bcc l_dl_lm_go
l_dl_lm_down:
        sec
        lda l_dl_lsel
        sbc l_dl_lh
        sta l_dl_ltop
        lda l_dl_lsel+1
        sbc #0
        sta l_dl_ltop+1
        inc l_dl_ltop
        bne l_dl_lm_go
        inc l_dl_ltop+1
l_dl_lm_go:
        jsr l_dl_save_list
        ldx l_dl_foc
        jsr tui_dlg_redraw
        lda #DH_LIST
        ldx l_dl_foc
        jsr l_dl_call_hook
        rts

; only the scroll position moves: the selection stays
l_dl_list_scrolled:
        jsr l_dl_save_list
        ldx l_dl_lctl
        jmp tui_dlg_redraw
l_dl_lctl:      .byte 0

;---------------------------------------------------------------------------------------
; mouse
;---------------------------------------------------------------------------------------
; X = control -> carry clear if the pointer is on it
l_dl_hit:
        stx l_dl_hx
        jsr l_dl_ctl
        ldy #L_DC_TYPE
        lda (tui_dp),y
        cmp #DC_LIST
        bne l_dl_hit1
        ldy #L_DC_ID
        lda (tui_dp),y
        sta l_dl_t
        lda tui_mrow
        cmp l_dl_row
        bcc l_dl_h_no
        sec
        sbc l_dl_row
        cmp l_dl_t
        bcs l_dl_h_no
        ; includes the scroll bar column
        lda tui_mcol
        cmp l_dl_col
        bcc l_dl_h_no
        sec
        sbc l_dl_col
        ldy #L_DC_W
        cmp (tui_dp),y
        beq l_dl_h_yes
        bcs l_dl_h_no
l_dl_h_yes:
        clc
        rts
l_dl_hit1:
        lda tui_mrow
        cmp l_dl_row
        bne l_dl_h_no
        ldy #L_DC_TYPE
        lda (tui_dp),y
        cmp #DC_TEXT
        bne +
        ldy #L_DC_W
        lda (tui_dp),y
        bra l_dl_h_w
+       jsr l_dl_p1
        jsr l_dl_slen
        clc
        adc #4
        bra l_dl_h_w
l_dl_h_w:
        sta l_dl_t
        lda tui_mcol
        cmp l_dl_col
        bcc l_dl_h_no
        sec
        sbc l_dl_col
        cmp l_dl_t
        bcc l_dl_h_yes
l_dl_h_no:
        sec
        rts
l_dl_hx:        .byte 0

; A = the control under the pointer that takes focus, carry set if none
l_dl_find:
        lda #0
        sta l_dl_i
-       lda l_dl_i
        cmp l_dl_n
        bcs l_dl_f_no
        tax
        jsr l_dl_takes
        bcs +
        ldx l_dl_i
        jsr l_dl_hit
        bcs +
        lda l_dl_i
        clc
        rts
+       inc l_dl_i
        bra -
l_dl_f_no:
        sec
        rts

l_dl_down:
        jsr l_dl_find
        bcc +
        jmp l_dl_loop
+       sta l_dl_downc
        tax
        jsr l_dl_type_of
        cmp #DC_BUTTON
        bne +
        lda l_dl_downc
        sta l_dl_press
        jsr l_dl_set_focus
        jsr l_dl_place
        jmp l_dl_loop
+       cmp #DC_CHECK
        beq l_dl_d_tog
        cmp #DC_RADIO
        bne +
l_dl_d_tog:
        lda l_dl_downc
        jsr l_dl_set_focus
        ldx l_dl_downc
        jsr l_dl_toggle
        jsr l_dl_place
        jmp l_dl_loop
+       cmp #DC_TEXT
        bne +
        lda l_dl_downc
        jsr l_dl_set_focus
        ; the cursor goes under the pointer
        sec
        lda tui_mcol
        sbc l_dl_col
        clc
        adc l_dt_off
        cmp l_dt_len
        bcc *+5
        lda l_dt_len
        sta l_dt_pos
        lda #0
        sta l_dt_sel
        ldx l_dl_foc
        jsr tui_dlg_redraw
        jsr l_dl_place
        jmp l_dl_loop
+       ; the list
        lda l_dl_downc
        jsr l_dl_set_focus
        lda l_dl_downc
        sta l_dl_lctl
        tax
        jsr l_dl_ctl
        jsr l_dl_load_list
        jsr l_dl_list_click
        jsr l_dl_place
        jmp l_dl_loop
l_dl_downc:     .byte 0

; a click in the list: its scroll bar or a row. tui_dp = the list.
l_dl_list_click:
        ldy #L_DC_W
        lda (tui_dp),y
        clc
        adc l_dl_col
        cmp tui_mcol
        bne l_dl_lc_row
        jmp l_dl_list_bar
l_dl_lc_row:
        sec
        lda tui_mrow
        sbc l_dl_row
        clc
        adc l_dl_ltop
        sta l_dl_item
        lda l_dl_ltop+1
        adc #0
        sta l_dl_item+1
        ; past the end?
        cmp l_dl_lcount+1
        bcc +
        bne l_dl_lc_end
        lda l_dl_item
        cmp l_dl_lcount
        bcs l_dl_lc_end
+       lda l_dl_item
        sta l_dl_lsel
        lda l_dl_item+1
        sta l_dl_lsel+1
        jsr l_dl_list_moved
        lda tui_dbl
        beq l_dl_lc_end
        jmp l_dl_press_default
l_dl_lc_end:
        rts

; the scroll bar: arrows move a line, the track a page
l_dl_list_bar:
        lda tui_mrow
        cmp l_dl_row
        bne +
        lda #1
        jmp l_dl_scroll_up
+       clc
        lda l_dl_row
        adc l_dl_lh
        sec
        sbc #1
        cmp tui_mrow
        bne +
        lda #1
        jmp l_dl_scroll_down
+       sec
        lda tui_mrow
        sbc l_dl_row
        cmp l_dl_lh
        bcc +
        rts
+       ; which side of the middle
        asl
        cmp l_dl_lh
        bcs +
        lda l_dl_lh
        jmp l_dl_scroll_up
+       lda l_dl_lh
        jmp l_dl_scroll_down

l_dl_scroll_up:
        sta l_dl_t
        sec
        lda l_dl_ltop
        sbc l_dl_t
        sta l_dl_ltop
        lda l_dl_ltop+1
        sbc #0
        sta l_dl_ltop+1
        bcs +
        lda #0
        sta l_dl_ltop
        sta l_dl_ltop+1
+       jmp l_dl_list_scrolled
l_dl_scroll_down:
        clc
        adc l_dl_ltop
        sta l_dl_ltop
        lda l_dl_ltop+1
        adc #0
        sta l_dl_ltop+1
        ; limit = count - h
        sec
        lda l_dl_lcount
        sbc l_dl_lh
        sta l_dl_t
        lda l_dl_lcount+1
        sbc #0
        sta l_dl_t2
        bcs +
        lda #0
        sta l_dl_t
        sta l_dl_t2
+       lda l_dl_ltop+1
        cmp l_dl_t2
        bcc l_dl_sd_ok
        bne +
        lda l_dl_ltop
        cmp l_dl_t
        bcc l_dl_sd_ok
+       lda l_dl_t
        sta l_dl_ltop
        lda l_dl_t2
        sta l_dl_ltop+1
l_dl_sd_ok:
        jmp l_dl_list_scrolled

l_dl_repeat:
        ; held on a list's scroll bar
        jsr l_dl_find
        bcs l_dl_rp_end
        sta l_dl_downc
        tax
        jsr l_dl_type_of
        cmp #DC_LIST
        bne l_dl_rp_end
        lda l_dl_downc
        sta l_dl_lctl
        ldx l_dl_downc
        jsr l_dl_ctl
        jsr l_dl_load_list
        ldy #L_DC_W
        lda (tui_dp),y
        clc
        adc l_dl_col
        cmp tui_mcol
        bne l_dl_rp_end
        jsr l_dl_list_bar
l_dl_rp_end:
        jmp l_dl_loop

l_dl_up:
        ldx l_dl_press
        cpx #$ff
        bne +
        jmp l_dl_loop
+       lda #$ff
        sta l_dl_press
        stx l_dl_px
        jsr l_dl_hit
        bcc +
        jmp l_dl_loop                   ; let go somewhere else: not pressed
+       ldx l_dl_px
        jmp l_dl_press_x

;---------------------------------------------------------------------------------------
; message boxes
;---------------------------------------------------------------------------------------
tui_msgbox:
        sta l_mb_lab_text
        stx l_mb_lab_text+1
        sty l_mb_style
        jsr l_dl_slen
        clc
        adc #8
        cmp #36
        bcs +
        lda #36
+       sta l_mb_def+1
        ; everything centres itself: reset that from the last box
        lda #DLG_AUTO
        sta l_mb_lab_col
        sta l_mb_b1+2
        sta l_mb_b2+2
        sta l_mb_b3+2
        ; the first button, and the other two as buttons or empty labels
        lda #DC_BUTTON
        sta l_mb_b2
        sta l_mb_b3
        lda #<l_mb_str_cancel
        sta l_mb_b3_text
        lda #>l_mb_str_cancel
        sta l_mb_b3_text+1
        lda l_mb_style
        cmp #MB_YESNOCANCEL
        bne l_mb_notync
        lda #<l_mb_str_yes
        sta l_mb_b1_text
        lda #>l_mb_str_yes
        sta l_mb_b1_text+1
        lda #<l_mb_str_no
        sta l_mb_b2_text
        lda #>l_mb_str_no
        sta l_mb_b2_text+1
        bra l_mb_go
l_mb_notync:
        lda #<l_mb_str_ok
        sta l_mb_b1_text
        lda #>l_mb_str_ok
        sta l_mb_b1_text+1
        lda #DC_LABEL
        sta l_mb_b2
        lda #<l_mb_str_none
        sta l_mb_b2_text
        lda #>l_mb_str_none
        sta l_mb_b2_text+1
        lda l_mb_style
        cmp #MB_OKCANCEL
        beq l_mb_go
        lda #DC_LABEL
        sta l_mb_b3
        lda #<l_mb_str_none
        sta l_mb_b3_text
        lda #>l_mb_str_none
        sta l_mb_b3_text+1
l_mb_go:
        lda #<l_mb_def
        ldx #>l_mb_def
        jmp tui_dialog

l_mb_style:     .byte 0
l_mb_str_ok:    .null "OK"
l_mb_str_yes:   .null "Yes"
l_mb_str_no:    .null "No"
l_mb_str_cancel: .null "Cancel"
l_mb_str_none:  .null ""

l_mb_def:
        #DLG 7, 36, 0, 0
        .byte DC_LABEL, 2
l_mb_lab_col:
        .byte DLG_AUTO, 0
l_mb_lab_text:
        .word 0, 0
        .byte 0
        #DLG_HLINE 3
l_mb_b1:
        .byte DC_BUTTON, 4, DLG_AUTO, 0
l_mb_b1_text:
        .word 0
        .byte 1, 0
l_mb_b1_id:
        .byte 1
l_mb_b2:
        .byte DC_BUTTON, 4, DLG_AUTO, 0
l_mb_b2_text:
        .word 0
        .byte 0, 0
l_mb_b2_id:
        .byte 2
l_mb_b3:
        .byte DC_BUTTON, 4, DLG_AUTO, 0
l_mb_b3_text:
        .word l_mb_str_cancel
        .byte 0, 0, 0
        #DLG_END
