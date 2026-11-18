;=======================================================================================
; lib/tui/tui_charmap.asm - pick a character from a grid of all 256, by keyboard or mouse.
; Needs tui_screen.asm and tui_event.asm.
;
;   tui_charmap      returns carry clear and A = the byte chosen, or carry set if cancelled.
;                    The screen is put back as it was.
;   tui_cm_glyph     word: routine called with A = a byte: A = the glyph to show for it, carry
;                    set = show it reversed. (tui_pet_glyph suits PETSCII.)
;   tui_cm_cur       the byte the cursor starts on, and ends on
;
; Keys: the cursor keys move, RETURN or SPACE chooses, ESC cancels. Mouse: click moves, a second
; click on the same character chooses, a click outside cancels.
;=======================================================================================

l_cm_cols       = 32
l_cm_rows       = 8
l_cm_w          = l_cm_cols * 2 + 3
l_cm_h          = l_cm_rows + 6
l_cm_top        = (TUI_ROWS - l_cm_h) / 2
l_cm_left       = (TUI_COLS - l_cm_w) / 2
l_cm_gridr      = l_cm_top + 2
l_cm_gridc      = l_cm_left + 2

tui_cm_glyph:   .word 0
tui_cm_cur:     .byte 0
l_cm_i:         .byte 0
l_cm_old:       .byte 0
l_cm_title:     .null "Characters"
l_cm_hint:      .null "RETURN chooses, ESC cancels. Code: $"
l_cm_hex:       .text "0123456789ABCDEF"

; X = byte: row and column of its cell in Y (column) and X (row)
l_cm_place:
        txa
        and #l_cm_cols - 1
        asl
        clc
        adc #l_cm_gridc
        tay
        txa
        lsr
        lsr
        lsr
        lsr
        lsr
        clc
        adc #l_cm_gridr
        tax
        rts

l_cm_call:
        jmp (tui_cm_glyph)

; draw byte A's cell
l_cm_cell:
        sta l_cm_i
        tax
        jsr l_cm_place
        jsr tui_goto
        lda l_cm_i
        jsr l_cm_call
        sta l_cm_old
        ; colours: reversed or not, inverted again under the cursor
        lda #0
        rol
        ldx l_cm_i
        cpx tui_cm_cur
        bne +
        eor #1
+       cmp #0
        beq +
        lda #$07
        bra ++
+       lda #$70
+       jsr tui_setattr
        lda l_cm_old
        jsr tui_putc
        rts

l_cm_status:
        lda #$70
        jsr tui_setattr
        ldx #l_cm_top + l_cm_h - 2
        ldy #l_cm_left + 2
        jsr tui_goto
        lda #<l_cm_hint
        ldx #>l_cm_hint
        jsr tui_puts
        lda tui_cm_cur
        lsr
        lsr
        lsr
        lsr
        tax
        lda l_cm_hex,x
        jsr tui_putc
        lda tui_cm_cur
        and #15
        tax
        lda l_cm_hex,x
        jmp tui_putc

; move the cursor to A
l_cm_move:
        ldx tui_cm_cur
        sta tui_cm_cur
        txa
        jsr l_cm_cell
        lda tui_cm_cur
        jsr l_cm_cell
        jmp l_cm_status

tui_charmap:
        jsr tui_cursor_off
        jsr tui_push
        lda #$70
        jsr tui_setattr
        lda #l_cm_top
        sta tui_r
        lda #l_cm_left
        sta tui_c
        lda #l_cm_h
        sta tui_h
        lda #l_cm_w
        sta tui_w
        lda #<l_cm_title
        ldx #>l_cm_title
        jsr tui_box
        jsr tui_shadow
        lda #0
-       pha
        jsr l_cm_cell
        pla
        inc a
        bne -
        jsr l_cm_status
l_cm_loop:
        jsr tui_wait_event
        cmp #EV_KEY
        beq l_cm_key
        cmp #EV_DOWN
        bne l_cm_loop
        ; the mouse
        sec
        lda tui_mrow
        sbc #l_cm_gridr
        bcc l_cm_out
        cmp #l_cm_rows
        bcs l_cm_out
        asl
        asl
        asl
        asl
        asl
        sta l_cm_i
        sec
        lda tui_mcol
        sbc #l_cm_gridc
        bcc l_cm_out
        lsr
        cmp #l_cm_cols
        bcs l_cm_out
        ora l_cm_i
        cmp tui_cm_cur
        beq l_cm_choose                 ; the second click
        jsr l_cm_move
        bra l_cm_loop
l_cm_out:
        ; outside the box cancels; inside it does nothing
        sec
        lda tui_mrow
        sbc #l_cm_top
        cmp #l_cm_h
        bcs l_cm_cancel
        sec
        lda tui_mcol
        sbc #l_cm_left
        cmp #l_cm_w
        bcs l_cm_cancel
        bra l_cm_loop
l_cm_key:
        lda tui_ev_key
        cmp #TK_ESC
        beq l_cm_cancel
        cmp #TK_ENTER
        beq l_cm_choose
        cmp #32
        beq l_cm_choose
        cmp #TK_LEFT
        bne +
        lda tui_cm_cur
        dec a
        bra l_cm_go
+       cmp #TK_RIGHT
        bne +
        lda tui_cm_cur
        inc a
        bra l_cm_go
+       cmp #TK_UP
        bne +
        sec
        lda tui_cm_cur
        sbc #l_cm_cols
        bra l_cm_go
+       cmp #TK_DOWN
        bne l_cm_loop
        clc
        lda tui_cm_cur
        adc #l_cm_cols
l_cm_go:
        jsr l_cm_move
        bra l_cm_loop
l_cm_cancel:
        jsr tui_pop
        sec
        rts
l_cm_choose:
        jsr tui_pop
        lda tui_cm_cur
        clc
        rts
