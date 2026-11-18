;=======================================================================================
; lib/tui/tui_petscii.asm - a font for showing PETSCII as well as ASCII, for TUI_CHARSET = 1.
;
; Letters, digits, punctuation and the TUI's own lines and arrows keep the bundled CGA look
; (tui_font_mixed.asm). PETSCII's graphics come from the machine's ROM font at startup, into
; the slots above 127. A ROM set's second half is only reversed copies of its first, which a
; cell can do by swapping its colours, so every glyph of both sets fits in the 256 slots, and
; both are available at once. Slot:
;     0-31    TG_ glyphs
;     32-127  ASCII, at their usual codes
;     128-191 the graphics of set 0 (upper case and graphics), screen codes 64-127
;     192-194 set 0's pound sign, up arrow and left arrow
;     195-    the few glyphs set 1 (lower and upper case) doesn't share with set 0
;
;   tui_font_compose  build the font image at TUI_FONT_IMAGE, and the maps. tui_init does this.
;   tui_pet_set       0 = PETSCII's upper case and graphics set, 1 = its lower and upper case set
;   tui_pet_glyph     A = a PETSCII byte: A = its slot, carry set = show it reversed (swap the
;                     cell's colours). Control codes show as reversed symbols, as in quote mode.
;                     Keeps X and Y.
;=======================================================================================

        .weak
TUI_ROM_FONT    = $29000                ; set 0, and set 1 at + $800
TUI_FONT_IMAGE  = $16000                ; 2 KB of bank 1, needed only while tui_init runs
        .endweak

l_tp_gfx0       = 128
l_tp_extra0     = 192
l_tp_extra1     = 195

tui_pet_set:    .byte 1
        .section bss
l_tp_map0:      .fill 128               ; screen code -> slot, for each set
        .send
        .section bss
l_tp_map1:      .fill 128
        .send
l_tp_next:      .byte 0
l_tp_save:      .byte 0

; screen codes 0-31 of each set, as slots. (32-63 are the same in both, and in ASCII.)
l_tp_low0:
        .byte '@'
        .text "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        .byte '[', l_tp_extra0, ']', l_tp_extra0 + 1, l_tp_extra0 + 2
l_tp_low1:
        .byte '@'
        .text "abcdefghijklmnopqrstuvwxyz"
        .byte '[', '\', ']', '^', '_'
; set 1, screen codes 64-94
l_tp_high1:
        .byte '`'
        .text "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        .byte '{', '|', '}', '~'

; A = screen code, X = set: tui_fp points at that glyph in the ROM
l_tp_rom:
        sta l_tp_save
        lda #0
        sta tui_fp+3
        lda l_tp_save
        asl
        asl
        asl
        sta tui_fp
        lda l_tp_save
        lsr
        lsr
        lsr
        lsr
        lsr
        clc
        adc #>TUI_ROM_FONT
        cpx #0
        beq +
        clc
        adc #>$800
+       sta tui_fp+1
        lda #`TUI_ROM_FONT
        sta tui_fp+2
        rts

; A = slot: ptr0 points at it in the image
l_tp_img:
        sta l_tp_save
        lda #0
        sta ptr0+3
        lda l_tp_save
        asl
        asl
        asl
        sta ptr0
        lda l_tp_save
        lsr
        lsr
        lsr
        lsr
        lsr
        clc
        adc #>TUI_FONT_IMAGE
        sta ptr0+1
        lda #`TUI_FONT_IMAGE
        sta ptr0+2
        rts

; tui_fp -> ptr0, one glyph
l_tp_copy:
        ldz #7
-       lda [tui_fp],z
        sta [ptr0],z
        dez
        bpl -
        ldz #0
        rts

; A = a table in bank 0 (A/X), Y = glyphs, tmp2 = the first slot: copy them to the image
l_tp_table:
        sta txt_ptr
        stx txt_ptr+1
        sty tmp3
-       lda tmp2
        jsr l_tp_img
        ldz #0
        ldy #0
-       lda (txt_ptr),y
        sta [ptr0],z
        inz
        iny
        cpy #8
        bne -
        ldz #0
        clc
        lda txt_ptr
        adc #8
        sta txt_ptr
        bcc +
        inc txt_ptr+1
+       inc tmp2
        dec tmp3
        bne --
        rts

tui_font_compose:
        ; the bundled glyphs
        lda #1
        sta tmp2
        lda #<tui_font_low
        ldx #>tui_font_low
        ldy #TUI_LOW_GLYPHS
        jsr l_tp_table
        lda #32
        sta tmp2
        lda #<tui_font_ascii
        ldx #>tui_font_ascii
        ldy #96
        jsr l_tp_table
        ; set 0
        ldx #0
-       lda l_tp_low0,x
        sta l_tp_map0,x
        lda l_tp_low1,x
        sta l_tp_map1,x
        inx
        cpx #32
        bne -
-       txa                             ; 32-63: the same in both
        sta l_tp_map0,x
        sta l_tp_map1,x
        inx
        cpx #64
        bne -
        ; 64-127 of set 0: from the ROM
        ldy #64
-       tya
        clc
        adc #l_tp_gfx0 - 64
        sta l_tp_map0,y
        jsr l_tp_img
        tya
        ldx #0
        jsr l_tp_rom
        jsr l_tp_copy
        iny
        cpy #128
        bne -
        ; set 0's pound sign and arrows
        lda #l_tp_extra0
        jsr l_tp_img
        lda #28
        ldx #0
        jsr l_tp_rom
        jsr l_tp_copy
        lda #l_tp_extra0 + 1
        jsr l_tp_img
        lda #30
        ldx #0
        jsr l_tp_rom
        jsr l_tp_copy
        lda #l_tp_extra0 + 2
        jsr l_tp_img
        lda #31
        ldx #0
        jsr l_tp_rom
        jsr l_tp_copy
        ; set 1: 64-94 are letters and ASCII
        ldx #0
-       lda l_tp_high1,x
        sta l_tp_map1 + 64,x
        inx
        cpx #31
        bne -
        ; 95-127: shared with set 0 where the ROM has the same glyph, otherwise a slot of its own
        lda #l_tp_extra1
        sta l_tp_next
        ldy #95
l_tp_s1:
        tya
        ldx #0
        jsr l_tp_rom
        lda tui_fp
        sta ptr0
        lda tui_fp+1
        sta ptr0+1
        lda tui_fp+2
        sta ptr0+2
        lda #0
        sta ptr0+3
        tya
        ldx #1
        jsr l_tp_rom
        ldz #7
-       lda [tui_fp],z
        cmp [ptr0],z
        bne l_tp_s1_new
        dez
        bpl -
        ldz #0
        lda l_tp_map0,y
        sta l_tp_map1,y
        bra l_tp_s1_next
l_tp_s1_new:
        ldz #0
        lda l_tp_next
        sta l_tp_map1,y
        jsr l_tp_img
        jsr l_tp_copy
        inc l_tp_next
l_tp_s1_next:
        iny
        cpy #128
        bne l_tp_s1
        rts

tui_pet_glyph:
        phx
        ; to a screen code, and whether it's reversed
        ldx #0
        cmp #$FF
        bne +
        lda #$5E
        bra l_tp_look
+       cmp #$20
        bcs +
        ldx #1                          ; $00-$1F: reversed @, A...
        bra l_tp_look
+       cmp #$40
        bcc l_tp_look                   ; $20-$3F
        cmp #$60
        bcs +
        sec                             ; $40-$5F
        sbc #$40
        bra l_tp_look
+       cmp #$80
        bcs +
        sec                             ; $60-$7F
        sbc #$20
        bra l_tp_look
+       cmp #$A0
        bcs +
        ldx #1                          ; $80-$9F: control codes, reversed
        sec
        sbc #$40
        bra l_tp_look
+       cmp #$C0
        bcs +
        sec                             ; $A0-$BF
        sbc #$40
        bra l_tp_look
+       sec                             ; $C0-$FE
        sbc #$80
l_tp_look:
        stx l_tp_save
        tax
        lda tui_pet_set
        bne +
        lda l_tp_map0,x
        bra ++
+       lda l_tp_map1,x
+       plx
        pha
        lda l_tp_save
        lsr                             ; carry = reversed
        pla
        rts
