;=======================================================================================
; lib/tui/tui_help.asm - a help viewer: scrolling topics with links, in a panel at the top of
; the screen. Keyboard and mouse. Needs tui_screen.asm and tui_event.asm.
;
;   tui_help         A/X = topic table, Y = topic to open. Returns when closed; the
;                    screen is put back as it was.
;   tui_help_bank    the chip-RAM bank holding the table and all of the text (default 0): the
;                    addresses in the table are 16-bit addresses within that bank
;
; Topic table: .word title, text for each topic. Title strings are zero-terminated.
; Text is zero-terminated, lines end in 13. A link is:
;       HLINK topic, "words"       which assembles 1, topic + 1, words, 2
; Topic HLINK_BACK goes back through the topics viewed (the last 20).
; Keys: arrows and F9/F11 scroll, TAB moves between links, RETURN or F1 follows one, a
; letter jumps to the next link starting with it, ESC closes. Mouse: click or right-click
; a link, click the scroll bar. A click below the panel closes it.
;=======================================================================================

        .include "tui_help_defs.asm"

        .weak
TUI_HELP_ROWS   = 19                    ; rows of the panel, frame included
        .endweak

l_hp_textrows   = TUI_HELP_ROWS - 2
L_HP_MAXLINES   = 120
L_HP_MAXLINKS   = 24

tui_hc_text:    .byte $07
tui_hc_arrow:   .byte $0A
tui_hc_link:    .byte $07
tui_hc_focus:   .byte $0F
tui_hc_bar:     .byte $3F

tui_help_bank:  .byte 0
        .section bss
l_hp_title:     .fill 40
        .send
l_hp_table:     .word 0
l_hp_topic:     .byte 0
l_hp_top:       .byte 0                 ; first line shown
l_hp_nlines:    .byte 0
l_hp_nlinks:    .byte 0
l_hp_focus:     .byte 0
        .section bss
l_hp_back:      .fill 20
        .send
l_hp_backn:     .byte 0
l_hp_text:      .word 0
        .section bss
l_hp_lo:        .fill L_HP_MAXLINES     ; start of each line
        .send
        .section bss
l_hp_hi:        .fill L_HP_MAXLINES
        .send
        .section bss
l_hp_lrow:      .fill L_HP_MAXLINKS     ; the links on screen
        .send
        .section bss
l_hp_lcol:      .fill L_HP_MAXLINKS
        .send
        .section bss
l_hp_llen:      .fill L_HP_MAXLINKS
        .send
        .section bss
l_hp_ltopic:    .fill L_HP_MAXLINKS
        .send
        .section bss
l_hp_lhot:      .fill L_HP_MAXLINKS     ; each link's first letter, upper case
        .send
l_hp_i:         .byte 0
l_hp_r:         .byte 0
l_hp_y:         .byte 0
l_hp_t:         .byte 0
l_hp_cur:       .word 0
l_hp_inlink:    .byte 0

l_hp_refbar:    .null " <F1=Follow>  <Tab=Next link>  <F9/F11=Page>  <Esc=Close>"

tui_help:
        sta l_hp_table
        stx l_hp_table+1
        sty l_hp_topic
        lda #0
        sta l_hp_backn
        jsr tui_cursor_off
        jsr tui_push
        jsr l_hp_open
l_hp_loop:
        jsr tui_wait_event
        cmp #EV_KEY
        beq l_hp_key
        cmp #EV_DOWN
        bne +
        jmp l_hp_mouse
+       cmp #EV_RDOWN
        bne +
        jmp l_hp_mouse
+       cmp #EV_REPEAT
        bne l_hp_loop
        jsr l_hp_bar_click
        bra l_hp_loop
l_hp_close:
        jmp tui_pop

l_hp_key:
        lda tui_ev_key
        cmp #TK_ESC
        beq l_hp_close
        cmp #TK_UP
        bne +
        jsr l_hp_up
        bra l_hp_loop
+       cmp #TK_DOWN
        bne +
        jsr l_hp_down
        bra l_hp_loop
+       cmp #TK_PGUP
        bne +
        lda #l_hp_textrows
        jsr l_hp_up_n
        bra l_hp_loop
+       cmp #TK_PGDN
        bne +
        lda #l_hp_textrows
        jsr l_hp_down_n
        bra l_hp_loop
+       cmp #TK_TAB
        bne +
        jsr l_hp_nextlink
        bra l_hp_loop
+       cmp #TK_BTAB
        bne +
        jsr l_hp_prevlink
        bra l_hp_loop
+       cmp #TK_ENTER
        beq +
        cmp #TK_F1
        bne l_hp_k_letter
+       lda l_hp_focus
        jsr l_hp_follow
        jmp l_hp_loop
l_hp_k_letter:
        cmp #33
        bcc l_hp_k_end
        cmp #127
        bcs l_hp_k_end
        and #$DF
        jsr l_hp_letter
l_hp_k_end:
        jmp l_hp_loop

; a topic opens at its top
l_hp_open:
        lda #0
        sta l_hp_top
        sta l_hp_focus
        jsr l_hp_scan
        jmp l_hp_draw

; A/X = an address in the help bank: tui_fp points at it
l_hp_far:
        sta tui_fp
        stx tui_fp+1
        lda tui_help_bank
        sta tui_fp+2
        lda #0
        sta tui_fp+3
        rts

; tui_fp = this topic's table entry, + A
l_hp_entry:
        sta l_hp_t
        lda l_hp_topic
        asl
        asl
        clc
        adc l_hp_t
        adc l_hp_table
        pha
        lda l_hp_table+1
        adc #0
        tax
        pla
        jmp l_hp_far

; index the lines of the text
l_hp_scan:
        lda #2
        jsr l_hp_entry
        ldz #0
        lda [tui_fp],z
        sta l_hp_lo
        inz
        lda [tui_fp],z
        sta l_hp_hi
        tax
        lda l_hp_lo
        ldz #0
        jsr l_hp_far
        lda #1
        sta l_hp_nlines
-       lda [tui_fp],z
        beq l_hp_sc_end
        inc tui_fp
        bne +
        inc tui_fp+1
+       cmp #13
        bne -
        ldx l_hp_nlines
        cpx #L_HP_MAXLINES
        bcs -
        lda tui_fp
        sta l_hp_lo,x
        lda tui_fp+1
        sta l_hp_hi,x
        inc l_hp_nlines
        bra -
l_hp_sc_end:
        rts

; the panel, its title and the text
l_hp_draw:
        lda tui_hc_text
        jsr tui_setattr
        lda #1
        sta tui_r
        lda #0
        sta tui_c
        lda #TUI_HELP_ROWS
        sta tui_h
        lda #TUI_COLS
        sta tui_w
        lda #32
        jsr tui_rect
        jsr tui_frame
        ; title: "HELP: name"
        ldx #1
        ldy #30
        jsr tui_goto
        lda #$70
        jsr tui_setattr
        lda #<l_hp_helpstr
        ldx #>l_hp_helpstr
        jsr tui_puts
        lda #0
        jsr l_hp_entry
        ldz #0
        lda [tui_fp],z
        pha
        inz
        lda [tui_fp],z
        tax
        pla
        jsr l_hp_far
        ldz #0
        ldx #0
-       lda [tui_fp],z
        sta l_hp_title,x
        beq +
        inz
        inx
        cpx #39
        bne -
        lda #0
        sta l_hp_title,x
+       ldz #0
        lda #<l_hp_title
        ldx #>l_hp_title
        jsr tui_puts
        lda #32
        jsr tui_putc
        ; reference bar
        lda tui_hc_bar
        jsr tui_setattr
        ldx #TUI_ROWS - 1
        ldy #0
        jsr tui_goto
        lda #32
        ldx #TUI_COLS
        jsr tui_rep
        ldx #TUI_ROWS - 1
        ldy #0
        jsr tui_goto
        lda #<l_hp_refbar
        ldx #>l_hp_refbar
        jsr tui_puts
; just the text and the scroll bar
l_hp_render:
        lda #0
        sta l_hp_nlinks
        sta l_hp_r
l_hp_rowloop:
        lda l_hp_r
        clc
        adc #2
        tax
        ldy #1
        jsr tui_goto
        lda tui_hc_text
        jsr tui_setattr
        clc
        lda l_hp_r
        adc l_hp_top
        cmp l_hp_nlines
        bcs l_hp_blank
        jsr l_hp_line
l_hp_blank:
        ; clear the rest of the row
        sec
        lda #TUI_COLS - 1
        sbc tui_col
        tax
        lda tui_hc_text
        jsr tui_setattr
        lda #32
        jsr tui_rep
        inc l_hp_r
        lda l_hp_r
        cmp #l_hp_textrows
        bne l_hp_rowloop
        ; scroll bar in the frame
        lda tui_hc_text
        jsr tui_setattr
        lda #2
        sta tui_r
        lda #TUI_COLS - 1
        sta tui_c
        lda #l_hp_textrows
        sta tui_h
        lda l_hp_top
        sta tui_sb_pos
        lda #0
        sta tui_sb_pos+1
        sta tui_sb_range+1
        sec
        lda l_hp_nlines
        sbc #l_hp_textrows
        bcs +
        lda #0
+       sta tui_sb_range
        jmp tui_vscroll

; print line A, noting its links
l_hp_line:
        tax
        lda l_hp_lo,x
        pha
        lda l_hp_hi,x
        tax
        pla
        jsr l_hp_far
        lda #0
        sta l_hp_y
        sta l_hp_inlink
l_hp_ln:
        ldz l_hp_y
        lda [tui_fp],z
        beq l_hp_ln_end
        cmp #13
        beq l_hp_ln_end
        inc l_hp_y
        cmp #1
        beq l_hp_ln_link
        cmp #2
        beq l_hp_ln_linkend
        ldx tui_col
        cpx #TUI_COLS - 1
        bcs l_hp_ln
        jsr tui_putc
        bra l_hp_ln
l_hp_ln_end:
        ldz #0
        rts
l_hp_ln_link:
        ldx l_hp_nlinks
        cpx #L_HP_MAXLINKS
        bcs l_hp_ln_skip
        ldz l_hp_y
        lda [tui_fp],z
        dec a
        sta l_hp_ltopic,x
        lda l_hp_r
        clc
        adc #2
        sta l_hp_lrow,x
        lda tui_col
        sta l_hp_lcol,x
        inz
        lda [tui_fp],z
        and #$DF
        sta l_hp_lhot,x
l_hp_ln_skip:
        inc l_hp_y
        lda tui_hc_arrow
        jsr tui_setattr
        lda #TG_LLINK
        jsr tui_putc
        ldx l_hp_nlinks
        lda tui_hc_link
        cpx l_hp_focus
        bne +
        lda tui_hc_focus
+       jsr tui_setattr
        lda #1
        sta l_hp_inlink
        bra l_hp_ln
l_hp_ln_linkend:
        lda tui_hc_arrow
        jsr tui_setattr
        lda #TG_RLINK
        jsr tui_putc
        lda tui_hc_text
        jsr tui_setattr
        ldx l_hp_nlinks
        cpx #L_HP_MAXLINKS
        bcs +
        sec
        lda tui_col
        sbc l_hp_lcol,x
        sta l_hp_llen,x
        inc l_hp_nlinks
+       bra l_hp_ln

l_hp_helpstr:   .null " HELP: "

l_hp_up:
        lda #1
l_hp_up_n:
        sta l_hp_t
        sec
        lda l_hp_top
        sbc l_hp_t
        bcs +
        lda #0
+       sta l_hp_top
        jmp l_hp_rerender
l_hp_down:
        lda #1
l_hp_down_n:
        clc
        adc l_hp_top
        sta l_hp_top
        ; limit
        sec
        lda l_hp_nlines
        sbc #l_hp_textrows
        bcs +
        lda #0
+       cmp l_hp_top
        bcs +
        sta l_hp_top
+
l_hp_rerender:
        lda #0
        sta l_hp_focus
        jmp l_hp_render

l_hp_nextlink:
        lda l_hp_nlinks
        beq l_hp_nl_end
        inc l_hp_focus
        lda l_hp_focus
        cmp l_hp_nlinks
        bcc +
        lda #0
        sta l_hp_focus
+       jmp l_hp_render
l_hp_nl_end:
        rts
l_hp_prevlink:
        lda l_hp_nlinks
        beq l_hp_nl_end
        lda l_hp_focus
        bne +
        lda l_hp_nlinks
        sta l_hp_focus
+       dec l_hp_focus
        jmp l_hp_render

; A = upper-case letter: the next link starting with it
l_hp_letter:
        sta l_hp_t
        ldx l_hp_nlinks
        beq l_hp_nl_end
        stx l_hp_i
        ldx l_hp_focus
-       inx
        cpx l_hp_nlinks
        bcc +
        ldx #0
+       lda l_hp_lhot,x
        cmp l_hp_t
        bne +
        stx l_hp_focus
        jmp l_hp_render
+       dec l_hp_i
        bne -
        rts

; follow link A
l_hp_follow:
        cmp l_hp_nlinks
        bcs l_hp_fl_end
        tax
        lda l_hp_ltopic,x
        cmp #HLINK_BACK
        bne +
        ldx l_hp_backn
        beq l_hp_fl_end
        dex
        stx l_hp_backn
        lda l_hp_back,x
        sta l_hp_topic
        jmp l_hp_open
+       pha
        ldx l_hp_backn
        cpx #20
        bcc +
        ; full: forget the oldest
        ldx #0
-       lda l_hp_back+1,x
        sta l_hp_back,x
        inx
        cpx #19
        bne -
        stx l_hp_backn
+       lda l_hp_topic
        ldx l_hp_backn
        sta l_hp_back,x
        inc l_hp_backn
        pla
        sta l_hp_topic
        jmp l_hp_open
l_hp_fl_end:
        rts

l_hp_mouse:
        lda tui_mrow
        cmp #TUI_HELP_ROWS + 1
        bcc +
        jmp l_hp_close                  ; below the panel
+       lda tui_mcol
        cmp #TUI_COLS - 1
        bne l_hp_m_link
        jsr l_hp_bar_click
        jmp l_hp_loop
l_hp_m_link:
        ldx #0
-       cpx l_hp_nlinks
        beq l_hp_m_end
        lda l_hp_lrow,x
        cmp tui_mrow
        bne +
        lda tui_mcol
        cmp l_hp_lcol,x
        bcc +
        sec
        sbc l_hp_lcol,x
        cmp l_hp_llen,x
        bcs +
        txa
        jsr l_hp_follow
        jmp l_hp_loop
+       inx
        bra -
l_hp_m_end:
        jmp l_hp_loop

; the pointer on the scroll bar: arrows a line, the track a page
l_hp_bar_click:
        lda tui_mcol
        cmp #TUI_COLS - 1
        bne l_hp_bc_end
        lda tui_mrow
        cmp #2
        bne +
        jmp l_hp_up
+       cmp #1 + l_hp_textrows
        bne +
        jmp l_hp_down
+       bcs l_hp_bc_end
        cmp #2 + l_hp_textrows / 2
        bcs +
        lda #l_hp_textrows
        jmp l_hp_up_n
+       lda #l_hp_textrows
        jmp l_hp_down_n
l_hp_bc_end:
        rts
