;=======================================================================================
; lib/tui/tui_menu.asm - a menu bar with drop-down menus, for keyboard and mouse.
; Needs tui_screen.asm and tui_event.asm.
;
;   tui_menu_init    A/X = the menu table
;   tui_menu_draw    draw the bar on row 0, nothing highlighted
;   tui_menu_hit     A = column: A = the menu at it, carry set if none
;   tui_menu_run     A = menu, Y = how it starts: 0 = the bar is active (a tap of ALT),
;                    1 = dropped down (a key), 2 = dropped down and the button is held.
;                    Returns A = the chosen command's id, or 0 if cancelled. The screen
;                    is put back as it was.
;   tui_menu_key     tui_ev_key = letter (MEGA+letter): A = the menu with that hotkey,
;                    carry set if none
;   tui_menu_off     byte per command id (up to TUI_MENU_IDS): non-zero = greyed out
;   tui_menu_status  word: routine called with A/X = the item's description, A/X = 0 for
;                    the bar on its own (0 = no routine). Draw it wherever you like.
;   tui_mc_*         the colours
;
; Menu table entries, 0 title to end:
;   .word title ("&File": & marks the hotkey), .byte column on the bar, .word items,
;   .byte column of the drop-down's left edge
; Item entries, 0 text to end, text 1 for a divider:
;   .word text ("&Open..."), .word shortcut text or 0, .word description, .byte id
;=======================================================================================

TUI_MENU_IDS    = 40
l_mn_entry      = 6                     ; bytes per menu
l_mn_item       = 7                     ; bytes per item

        .section bss
tui_menu_off:   .fill TUI_MENU_IDS
        .send
tui_menu_status: .word 0
tui_mc_bar:     .byte $70
tui_mc_hot:     .byte $7F
tui_mc_sel:     .byte $07
tui_mc_selhot:  .byte $0F
tui_mc_off:     .byte $78
tui_mc_offsel:  .byte $08

l_mn_table:     .word 0
l_mn_cur:       .byte 0                 ; current menu
l_mn_item_i:    .byte 0                 ; current item
l_mn_drop:      .byte 0                 ; 1 = dropped down
l_mn_mouse:     .byte 0                 ; 1 = the button is held from the opening click
l_mn_nitems:    .byte 0
l_mn_boxw:      .byte 0
l_mn_boxc:      .byte 0
l_mn_count:     .byte 0
l_mn_t:         .byte 0
l_mn_result:    .byte 0
l_mn_items:     .word 0

tui_menu_init:
        sta l_mn_table
        stx l_mn_table+1
        ldy #0
        ldx #0
-       lda l_mn_table
        sta tui_dp
        lda l_mn_table+1
        sta tui_dp+1
        lda (tui_dp),y
        iny
        ora (tui_dp),y
        beq +
        iny
        iny
        iny
        iny
        iny
        inx
        bra -
+       stx l_mn_count
        rts

; tui_dp = menu A's entry
l_mn_entry_ptr:
        ldx l_mn_table
        stx tui_dp
        ldx l_mn_table+1
        stx tui_dp+1
        tax
        beq +
-       clc
        lda tui_dp
        adc #l_mn_entry
        sta tui_dp
        bcc *+4
        inc tui_dp+1
        dex
        bne -
+       rts

tui_menu_draw:
        lda #$ff
; A = the menu to highlight, $ff none
l_mn_bar:
        sta l_mn_t
        lda tui_mc_hot
        sta tui_hotattr
        lda tui_mc_bar
        jsr tui_setattr
        ldx #0
        ldy #0
        jsr tui_goto
        lda #32
        ldx #TUI_COLS
        jsr tui_rep
        lda #0
        sta l_mn_bar_i
l_mn_bar_loop:
        lda l_mn_bar_i
        cmp l_mn_count
        beq l_mn_bar_end
        jsr l_mn_entry_ptr
        ldy #2
        lda (tui_dp),y
        tay
        dey                             ; a space on each side
        ldx #0
        jsr tui_goto
        lda l_mn_bar_i
        cmp l_mn_t
        bne +
        lda tui_mc_selhot
        sta tui_hotattr
        lda tui_mc_sel
        bra l_mn_bar_attr
+       lda tui_mc_hot                  ; letters light up only while the bar is active
        ldx l_mn_t
        cpx #$ff
        bne +
        lda tui_mc_bar
+       sta tui_hotattr
        lda tui_mc_bar
l_mn_bar_attr:
        jsr tui_setattr
        lda #32
        jsr tui_putc
        ldy #0
        lda (tui_dp),y
        pha
        iny
        lda (tui_dp),y
        tax
        pla
        jsr tui_puts_hot
        lda #32
        jsr tui_putc
        inc l_mn_bar_i
        bra l_mn_bar_loop
l_mn_bar_end:
        rts
l_mn_bar_i:     .byte 0

; string length without its '&'
l_mn_len:
        sta tui_str
        stx tui_str+1
        ldy #0
        ldx #0
-       lda (tui_str),y
        beq +
        iny
        cmp #'&'
        beq -
        inx
        bra -
+       txa
        rts

tui_menu_hit:
        sta l_mn_hitc
        lda #0
        sta l_mn_hiti
-       lda l_mn_hiti
        cmp l_mn_count
        bcs l_mn_hit_no
        jsr l_mn_entry_ptr
        ldy #2
        lda (tui_dp),y
        dec a
        cmp l_mn_hitc
        bcc +
        beq +
        bra l_mn_hit_next
+       sta l_mn_t
        ldy #0
        lda (tui_dp),y
        pha
        iny
        lda (tui_dp),y
        tax
        pla
        jsr l_mn_len
        clc
        adc #2
        adc l_mn_t
        cmp l_mn_hitc
        beq l_mn_hit_next
        bcc l_mn_hit_next
        lda l_mn_hiti
        clc
        rts
l_mn_hit_next:
        inc l_mn_hiti
        bra -
l_mn_hit_no:
        sec
        rts
l_mn_hitc:      .byte 0
l_mn_hiti:      .byte 0

; A = upper-case letter: the hotkey of a string at tui_str, compared. Z set if equal.
l_mn_str_hot:
        sta l_mn_t
        ldy #0
-       lda (tui_str),y
        beq l_mn_sh_no
        iny
        cmp #'&'
        bne -
        lda (tui_str),y
        and #$DF
        cmp l_mn_t
        rts
l_mn_sh_no:
        lda #1
        rts

tui_menu_key:
        lda tui_ev_key
l_mn_find_title:
        sta l_mn_hitc
        lda #0
        sta l_mn_hiti
-       lda l_mn_hiti
        cmp l_mn_count
        bcs l_mn_hit_no
        jsr l_mn_entry_ptr
        ldy #0
        lda (tui_dp),y
        sta tui_str
        iny
        lda (tui_dp),y
        sta tui_str+1
        lda l_mn_hitc
        jsr l_mn_str_hot
        beq +
        inc l_mn_hiti
        bra -
+       lda l_mn_hiti
        clc
        rts

; tui_dp = item A of the current menu
l_mn_item_ptr:
        pha
        lda l_mn_items
        sta tui_dp
        lda l_mn_items+1
        sta tui_dp+1
        plx
        beq +
-       clc
        lda tui_dp
        adc #l_mn_item
        sta tui_dp
        bcc *+4
        inc tui_dp+1
        dex
        bne -
+       rts

; load this menu's item list and measure it
l_mn_measure:
        lda l_mn_cur
        jsr l_mn_entry_ptr
        ldy #3
        lda (tui_dp),y
        sta l_mn_items
        iny
        lda (tui_dp),y
        sta l_mn_items+1
        iny
        lda (tui_dp),y
        sta l_mn_boxc
        lda #0
        sta l_mn_nitems
        lda #10
        sta l_mn_boxw
l_mn_m_loop:
        lda l_mn_nitems
        jsr l_mn_item_ptr
        ldy #0
        lda (tui_dp),y
        iny
        ora (tui_dp),y
        beq l_mn_m_end
        lda (tui_dp),y
        bne +                           ; a text above page 0
        dey
        lda (tui_dp),y
        cmp #1
        beq l_mn_m_next                 ; a divider
+       ldy #2                          ; shortcut length
        lda (tui_dp),y
        pha
        iny
        ora (tui_dp),y
        beq l_mn_m_nosc
        lda (tui_dp),y
        tax
        pla
        jsr l_mn_len
        clc
        adc #3
        bra l_mn_m_sc
l_mn_m_nosc:
        pla
        lda #0
l_mn_m_sc:
        sta l_mn_t2
        lda l_mn_nitems                 ; text length
        jsr l_mn_item_ptr
        ldy #0
        lda (tui_dp),y
        pha
        iny
        lda (tui_dp),y
        tax
        pla
        jsr l_mn_len
        clc
        adc l_mn_t2
        adc #4                          ; the frame and a space on each side
        cmp l_mn_boxw
        bcc l_mn_m_next
        sta l_mn_boxw
l_mn_m_next:
        inc l_mn_nitems
        bra l_mn_m_loop
l_mn_m_end:
        ; keep the box and its shadow on the screen
        clc
        lda l_mn_boxc
        adc l_mn_boxw
        cmp #TUI_COLS - 1
        bcc +
        sec
        lda #TUI_COLS - 2
        sbc l_mn_boxw
        sta l_mn_boxc
+       rts
l_mn_t2:        .byte 0

; carry set if the current item can't be selected (a divider)
l_mn_is_divider:
        lda l_mn_item_i
        jsr l_mn_item_ptr
        ldy #1
        lda (tui_dp),y
        bne +
        dey
        lda (tui_dp),y
        cmp #1
        bne +
        sec
        rts
+       clc
        rts

; draw item A
l_mn_draw_item:
        sta l_mn_di
        clc
        adc #2
        tax
        ldy l_mn_boxc
        iny
        jsr tui_goto
        lda l_mn_di
        jsr l_mn_item_ptr
        ldy #1
        lda (tui_dp),y
        bne l_mn_di_real
        dey
        lda (tui_dp),y
        cmp #1
        bne l_mn_di_real
        ; a divider joins the frame
        sec
        lda tui_col
        sbc #1
        tay
        ldx tui_row
        jsr tui_goto
        lda tui_mc_bar
        jsr tui_setattr
        lda #TG_LTEE
        jsr tui_putc
        lda #TG_HLINE
        ldx l_mn_boxw
        dex
        dex
        jsr tui_rep
        lda #TG_RTEE
        jmp tui_putc
l_mn_di_real:
        ; colours: off / selected
        ldy #6
        lda (tui_dp),y
        tax
        lda tui_menu_off,x
        sta l_mn_dis
        lda l_mn_di
        cmp l_mn_item_i
        beq l_mn_di_sel
        lda tui_mc_hot
        sta tui_hotattr
        lda tui_mc_bar
        ldx l_mn_dis
        beq +
        lda tui_mc_off
        sta tui_hotattr
+       jmp l_mn_di_go
l_mn_di_sel:
        lda tui_mc_selhot
        sta tui_hotattr
        lda tui_mc_sel
        ldx l_mn_dis
        beq l_mn_di_go
        lda tui_mc_offsel
        sta tui_hotattr
l_mn_di_go:
        jsr tui_setattr
        lda #32
        ldx l_mn_boxw
        dex
        dex
        jsr tui_rep
        ; text
        lda l_mn_di
        clc
        adc #2
        tax
        ldy l_mn_boxc
        iny
        iny
        jsr tui_goto
        lda l_mn_di
        jsr l_mn_item_ptr
        ldy #0
        lda (tui_dp),y
        pha
        iny
        lda (tui_dp),y
        tax
        pla
        jsr tui_puts_hot
        ; shortcut, right-aligned
        lda l_mn_di
        jsr l_mn_item_ptr
        ldy #2
        lda (tui_dp),y
        sta l_mn_sc
        iny
        lda (tui_dp),y
        sta l_mn_sc+1
        ora l_mn_sc
        beq l_mn_di_end
        lda l_mn_di
        clc
        adc #2
        tax
        clc
        lda l_mn_boxc
        adc l_mn_boxw
        tay
        dey
        dey
        jsr tui_goto
        lda l_mn_sc
        ldx l_mn_sc+1
        jsr tui_rtext
l_mn_di_end:
        rts
l_mn_di:        .byte 0
l_mn_dis:       .byte 0
l_mn_sc:        .word 0

; the whole state of the menus on screen
l_mn_redraw:
        jsr tui_pop
        jsr tui_push
        lda l_mn_cur
        jsr l_mn_bar
        lda l_mn_drop
        bne +
        lda tui_menu_status
        ora tui_menu_status+1
        beq l_mn_rd_end
        lda #0
        tax
        jmp l_mn_call_status
+       jsr l_mn_measure
        lda tui_mc_hot
        sta tui_hotattr
        lda tui_mc_bar
        jsr tui_setattr
        lda #1
        sta tui_r
        lda l_mn_boxc
        sta tui_c
        clc
        lda l_mn_nitems
        adc #2
        sta tui_h
        lda l_mn_boxw
        sta tui_w
        lda #0
        tax
        jsr tui_box
        jsr tui_shadow
        lda #0
        sta l_mn_rd_i
-       lda l_mn_rd_i
        cmp l_mn_nitems
        beq +
        jsr l_mn_draw_item
        inc l_mn_rd_i
        bra -
+       jsr l_mn_show_status
l_mn_rd_end:
        rts
l_mn_rd_i:      .byte 0

l_mn_show_status:
        lda tui_menu_status
        ora tui_menu_status+1
        beq +
        lda l_mn_item_i
        jsr l_mn_item_ptr
        ldy #4
        lda (tui_dp),y
        pha
        iny
        lda (tui_dp),y
        tax
        pla
        jmp l_mn_call_status
+       rts
l_mn_call_status:
        jmp (tui_menu_status)

; change the selected item to A, redrawing only what changed
l_mn_select:
        ldx l_mn_item_i
        sta l_mn_item_i
        txa
        jsr l_mn_draw_item
        lda l_mn_item_i
        jsr l_mn_draw_item
        jmp l_mn_show_status

; move by one, skipping dividers. A = 1 or $ff.
l_mn_step:
        sta l_mn_t
        lda l_mn_item_i
        sta l_mn_old
-       clc
        lda l_mn_item_i
        adc l_mn_t
        bpl +
        lda l_mn_nitems
        dec a
+       cmp l_mn_nitems
        bcc +
        lda #0
+       sta l_mn_item_i
        jsr l_mn_is_divider
        bcs -
        lda l_mn_item_i
        ldx l_mn_old
        stx l_mn_item_i
        jmp l_mn_select
l_mn_old:       .byte 0

; A = step to another menu
l_mn_other:
        clc
        adc l_mn_cur
        bpl +
        lda l_mn_count
        dec a
+       cmp l_mn_count
        bcc +
        lda #0
+       sta l_mn_cur
        lda #0
        sta l_mn_item_i
        jmp l_mn_redraw

tui_menu_run:
        sta l_mn_cur
        sty l_mn_drop
        lda #0
        sta l_mn_mouse
        cpy #2
        bne +
        lda #1
        sta l_mn_mouse
        sta l_mn_drop
+       lda #0
        sta l_mn_item_i
        sta l_mn_result
        jsr tui_cursor_off
        jsr tui_push
        jsr l_mn_redraw
l_mn_loop:
        jsr tui_wait_event
        cmp #EV_KEY
        beq l_mn_key
        cmp #EV_DOWN
        bne +
        jmp l_mn_down
+       cmp #EV_DRAG
        bne +
        jmp l_mn_drag
+       cmp #EV_UP
        bne l_mn_loop
        jmp l_mn_up

l_mn_key:
        lda tui_ev_key
        cmp #TK_ESC
        beq l_mn_cancel
        cmp #TK_ALT
        beq l_mn_cancel
        cmp #TK_LEFT
        bne +
        lda #$ff
        jsr l_mn_other
        bra l_mn_loop
+       cmp #TK_RIGHT
        bne +
        lda #1
        jsr l_mn_other
        bra l_mn_loop
+       cmp #TK_DOWN
        bne l_mn_k1
        lda l_mn_drop
        bne +
        lda #1
        sta l_mn_drop
        jsr l_mn_redraw
        bra l_mn_loop
+       lda #1
        jsr l_mn_step
        bra l_mn_loop
l_mn_k1:
        cmp #TK_UP
        bne l_mn_k2
        lda l_mn_drop
        beq l_mn_loop
        lda #$ff
        jsr l_mn_step
        bra l_mn_loop
l_mn_k2:
        cmp #TK_ENTER
        bne l_mn_k3
        lda l_mn_drop
        bne l_mn_choose
        lda #1
        sta l_mn_drop
        jsr l_mn_redraw
        bra l_mn_loop
l_mn_k3:
        cmp #33
        bcs +
        jmp l_mn_loop
+       and #$DF                        ; upper case
        sta l_mn_keyc
        lda l_mn_drop
        bne l_mn_k_item
        lda l_mn_keyc
        jsr l_mn_find_title
        bcc +
        jmp l_mn_loop
+       sta l_mn_cur
        lda #1
        sta l_mn_drop
        lda #0
        sta l_mn_item_i
        jsr l_mn_redraw
        jmp l_mn_loop
l_mn_k_item:
        lda #0
        sta l_mn_ki
-       lda l_mn_ki
        cmp l_mn_nitems
        bcc +
        jmp l_mn_loop
+       jsr l_mn_item_ptr
        ldy #1
        lda (tui_dp),y
        bne +
        dey
        lda (tui_dp),y
        cmp #1
        beq l_mn_ki_next
+       ldy #0
        lda (tui_dp),y
        sta tui_str
        iny
        lda (tui_dp),y
        sta tui_str+1
        lda l_mn_keyc
        jsr l_mn_str_hot
        bne l_mn_ki_next
        lda l_mn_ki
        sta l_mn_item_i
        bra l_mn_choose
l_mn_ki_next:
        inc l_mn_ki
        bra -
l_mn_keyc:      .byte 0
l_mn_ki:        .byte 0

; take the current item
l_mn_choose:
        lda l_mn_item_i
        jsr l_mn_item_ptr
        ldy #6
        lda (tui_dp),y
        tax
        lda tui_menu_off,x
        beq +
        jmp l_mn_loop                   ; greyed out: stay
+       stx l_mn_result
l_mn_cancel:
        jsr tui_pop
        lda l_mn_result
        rts

; carry clear = the pointer is over item A (not a divider)
l_mn_over:
        lda l_mn_drop
        beq l_mn_ov_no
        sec
        lda tui_mrow
        sbc #2
        bcc l_mn_ov_no
        cmp l_mn_nitems
        bcs l_mn_ov_no
        sta l_mn_t
        lda tui_mcol
        cmp l_mn_boxc
        bcc l_mn_ov_no
        sec
        sbc l_mn_boxc
        cmp l_mn_boxw
        bcs l_mn_ov_no
        lda l_mn_t
        jsr l_mn_item_ptr
        ldy #1
        lda (tui_dp),y
        bne +
        dey
        lda (tui_dp),y
        cmp #1
        beq l_mn_ov_no
+       lda l_mn_t
        clc
        rts
l_mn_ov_no:
        sec
        rts

l_mn_down:
        lda #1
        sta l_mn_mouse
        lda tui_mrow
        bne l_mn_d_notbar
        lda tui_mcol
        jsr tui_menu_hit
        bcs l_mn_cancel
        cmp l_mn_cur
        bne +
        ldx l_mn_drop
        beq +
        jmp l_mn_cancel                 ; a click on the open menu's title closes it
+       sta l_mn_cur
        lda #1
        sta l_mn_drop
        lda #0
        sta l_mn_item_i
        jsr l_mn_redraw
        jmp l_mn_loop
l_mn_d_notbar:
        jsr l_mn_over
        bcc +
        jmp l_mn_cancel                 ; outside: close
+       jsr l_mn_select
        jmp l_mn_loop

l_mn_drag:
        lda l_mn_mouse
        bne +
        jmp l_mn_loop
+       lda tui_mrow
        bne l_mn_dg_item
        lda tui_mcol
        jsr tui_menu_hit
        bcc +
        jmp l_mn_loop
+       cmp l_mn_cur
        bne +
        jmp l_mn_loop
+       sta l_mn_cur
        lda #1
        sta l_mn_drop
        lda #0
        sta l_mn_item_i
        jsr l_mn_redraw
        jmp l_mn_loop
l_mn_dg_item:
        jsr l_mn_over
        bcc +
        jmp l_mn_loop
+       jsr l_mn_select
        jmp l_mn_loop

l_mn_up:
        lda l_mn_mouse
        bne +
        jmp l_mn_loop
+       lda #0
        sta l_mn_mouse
        lda tui_mrow
        bne +
        jmp l_mn_loop                   ; on the bar: the menu stays open
+       jsr l_mn_over
        bcc +
        jmp l_mn_cancel                 ; released outside
+       sta l_mn_item_i
        jmp l_mn_choose
