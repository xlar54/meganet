;=======================================================================================
; lib/tui/tui_screen.asm - an 80x25 character screen where every cell has its own foreground
; and background colour, DOS style. Needs lib/dma.asm, tui_font.asm, tui_zp.asm.
;
; How: Full Colour Mode. The font is rendered 8 times at TUI_ATLAS, once per background
; colour, with foreground pixels set to $FF. The VIC-IV draws pixel value $FF in the
; cell's colour-RAM colour, so glyph and background come from the character number and
; the foreground from colour RAM.
;
;   attribute byte  (bg << 4) | fg, as in VGA text mode: bg 0-7, fg 0-15. TUI_BLACK etc.
;
;   tui_init        after #TAKEOVER: video mode, palette, glyphs (about 50 ms), clear
;   tui_goto        X = row, Y = col: set the output position
;   tui_setattr     A = attribute for following output
;   tui_putc        A = glyph (any of 256, no control codes). Keeps A, X, Y.
;   tui_puts        A/X = zero-terminated string (lo/hi). Keeps nothing.
;   tui_puts_hot    the same, '&' marks the next character as a hotkey (tui_hotattr)
;   tui_rep         A = glyph, X = count: repeat along the row
;   tui_rect        A = glyph: fill tui_r,tui_c,tui_h,tui_w with the current attribute
;   tui_frame       single-line frame around tui_r,tui_c,tui_h,tui_w, no fill
;   tui_box         A/X = title or 0: tui_rect with spaces + tui_frame + title
;   tui_shadow      drop shadow right of and below tui_r,tui_c,tui_h,tui_w
;   tui_recolour    X = count: set the attribute of cells, keeping their glyphs
;   tui_rtext       A/X = string: print it right-aligned, ending at the output position
;   tui_centre      A/X = string, Y = width: print it centred in width from the position
;   tui_dec16       A/X = number: print it in decimal, without padding
;   tui_dec5        A/X = number: print it as 5 digits with leading zeros
;   tui_dec3        A = number: print it as 3 digits with leading zeros
;   tui_push        save the whole screen on a stack in attic (TUI_LAYERS levels)
;   tui_pop         restore the most recent tui_push
;   tui_vscroll     a vertical scroll bar at tui_r,tui_c, tui_h cells long, arrows included:
;                   tui_sb_pos, tui_sb_range say where the thumb goes, tui_sb_attr the colours
;   tui_hscroll     the same, horizontal, tui_w cells long
;
; Library calls may change tmp0-tmp7 and ptr1, ptr2. tui_r etc. are ordinary variables.
;=======================================================================================

        .weak
TUI_SCREEN      = $12000                ; screen RAM, 4000 bytes
TUI_COLOUR_OFS  = $0800                 ; colour RAM offset: above the KERNAL's 2 KB window
TUI_LAYER_BASE  = $87F0000              ; attic: saved screens
TUI_LAYERS      = 8                     ; 8 KB per level
TUI_CHARSET     = 0                     ; 0 = the whole CP437 font (tui_font.asm); 1 = ASCII and
                                        ; lines from it plus PETSCII graphics from ROM
                                        ; (tui_font_mixed.asm, tui_petscii.asm)
        .endweak

TUI_COLS        = 80
TUI_ROWS        = 25
TUI_ATLAS       = $40000                ; 128 KB of glyphs in banks 4-5
TUI_CHAR_HI     = TUI_ATLAS >> 14       ; high byte of the character number for background 0

; EGA colour numbers (the palette tui_init loads)
TUI_BLACK       = 0
TUI_BLUE        = 1
TUI_GREEN       = 2
TUI_CYAN        = 3
TUI_RED         = 4
TUI_MAGENTA     = 5
TUI_BROWN       = 6
TUI_GREY        = 7
TUI_DGREY       = 8
TUI_LBLUE       = 9
TUI_LGREEN      = 10
TUI_LCYAN       = 11
TUI_LRED        = 12
TUI_LMAGENTA    = 13
TUI_YELLOW      = 14
TUI_WHITE       = 15

; the glyphs the widgets use
        .if TUI_CHARSET == 1
TG_HLINE        = 1
TG_VLINE        = 2
TG_TL           = 3
TG_TR           = 4
TG_BL           = 5
TG_BR           = 6
TG_LTEE         = 7
TG_RTEE         = 8
TG_SHADE        = 9
TG_BLOCK        = 10
TG_UP           = 11
TG_DOWN         = 12
TG_RIGHT        = 13
TG_LEFT         = 14
TG_LLINK        = 15
TG_RLINK        = 16
TG_BULLET       = 17
TG_LOWER        = 18                    ; the lower half of a cell
TG_UPPER        = 19                    ; the upper half
        .else
TG_HLINE        = $C4
TG_VLINE        = $B3
TG_TL           = $DA
TG_TR           = $BF
TG_BL           = $C0
TG_BR           = $D9
TG_LTEE         = $C3
TG_RTEE         = $B4
TG_SHADE        = $B0
TG_BLOCK        = $DB
TG_UP           = $18
TG_DOWN         = $19
TG_RIGHT        = $1A
TG_LEFT         = $1B
TG_LLINK        = $11
TG_RLINK        = $10
TG_BULLET       = $07
TG_LOWER        = $DC
TG_UPPER        = $DF
        .endif

tui_r:          .byte 0
tui_c:          .byte 0
tui_h:          .byte 0
tui_w:          .byte 0
tui_row:        .byte 0                 ; output position
tui_col:        .byte 0
tui_attr:       .byte $07               ; current attribute
tui_hotattr:    .byte $0F               ; attribute of '&' hotkeys
tui_bgbyte:     .byte TUI_CHAR_HI       ; attribute split up for tui_putc
tui_fgbyte:     .byte 7
tui_layer:      .byte 0
l_tui_t:        .byte 0
l_tui_t2:       .byte 0
l_tui_num:      .word 0

; row * 160
l_tui_rowlo:
        .for l_r = 0, l_r < TUI_ROWS, l_r += 1
        .byte <(l_r * 160)
        .next
l_tui_rowhi:
        .for l_r = 0, l_r < TUI_ROWS, l_r += 1
        .byte >(l_r * 160)
        .next

; colours as 4-bit values (the palette registers are nibble-swapped: see below)
l_tui_pal_r: .byte $0,$0,$0,$0,$A,$A,$A,$A,$5,$5,$5,$5,$F,$F,$F,$F
l_tui_pal_g: .byte $0,$0,$A,$A,$0,$0,$5,$A,$5,$5,$F,$F,$5,$5,$F,$F
l_tui_pal_b: .byte $0,$A,$0,$A,$0,$A,$0,$A,$5,$F,$5,$F,$5,$F,$5,$F

tui_init:
        lda #$47
        sta VIC4_KEY
        lda #$53
        sta VIC4_KEY
        lda #$80
        trb VIC4_HOTREG                 ; so C64-style writes don't undo the layout
        lda #%00000101                  ; CHR16 + FCLRHI: characters above 255 are FCM
        sta VIC4_CTRL
        lda VIC3_CTRL
        and #%01010111                  ; no ATTR, no V400, keep 40 MHz
        ora #%10000000                  ; H640
        sta VIC3_CTRL
        lda #160
        sta VIC4_LINESTEP
        lda #0
        sta VIC4_LINESTEP+1
        lda #TUI_COLS
        sta VIC4_CHRCOUNT
        lda #TUI_ROWS
        sta VIC4_DISPROWS
        lda #<TUI_SCREEN
        sta VIC4_SCRNPTR
        lda #>TUI_SCREEN
        sta VIC4_SCRNPTR+1
        lda #`TUI_SCREEN
        sta VIC4_SCRNPTR+2
        lda #0
        sta VIC4_SCRNPTR+3
        lda #<TUI_COLOUR_OFS
        sta VIC4_COLPTR
        lda #>TUI_COLOUR_OFS
        sta VIC4_COLPTR+1
        lda #$50
        sta VIC4_TEXTXPOS
        sta VIC4_SDBDRWD
        lda #0
        sta BORDERCOL
        sta BACKCOL
        sta tui_layer
        ldx #15
-       lda l_tui_pal_r,x               ; a 4-bit value v reads as $vv: swapped it is the same
        asl
        asl
        asl
        asl
        ora l_tui_pal_r,x
        sta $D100,x
        lda l_tui_pal_g,x
        asl
        asl
        asl
        asl
        ora l_tui_pal_g,x
        sta $D200,x
        lda l_tui_pal_b,x
        asl
        asl
        asl
        asl
        ora l_tui_pal_b,x
        sta $D300,x
        dex
        bpl -
        jsr l_tui_atlas
        lda #$07
        jsr tui_setattr
        ldx #0
        ldy #0
        jsr tui_goto
        lda #0
        sta tui_r
        sta tui_c
        lda #TUI_ROWS
        sta tui_h
        lda #TUI_COLS
        sta tui_w
        lda #32
        jmp tui_rect

; build the eight copies of the font
l_tui_atlas:
        .if TUI_CHARSET == 1
        jsr tui_font_compose
        .endif
        lda #<TUI_ATLAS
        sta ptr0
        lda #>TUI_ATLAS
        sta ptr0+1
        lda #`TUI_ATLAS
        sta ptr0+2
        lda #0
        sta ptr0+3
        sta tmp1                        ; background
l_tui_a_bg:
        .if TUI_CHARSET == 1
        lda #<TUI_FONT_IMAGE
        sta tui_fp
        lda #>TUI_FONT_IMAGE
        sta tui_fp+1
        lda #`TUI_FONT_IMAGE
        sta tui_fp+2
        lda #0
        sta tui_fp+3
        .else
        lda #<tui_font
        sta tui_str
        lda #>tui_font
        sta tui_str+1
        .endif
        lda #0
        sta tmp2                        ; glyphs done (256 wraps to 0)
l_tui_a_glyph:
        ; this glyph's rows
        ldz #0
        ldy #0
-
        .if TUI_CHARSET == 1
        lda [tui_fp],z
        inz
        .else
        lda (tui_str),y
        .endif
        sta l_tui_g,y
        iny
        cpy #8
        bne -
        ldz #0
        ldy #0
l_tui_a_row:
        lda l_tui_g,y
        sta tmp3
        ldx #8
-       asl tmp3
        lda tmp1
        bcc +
        lda #$FF
+       sta [ptr0],z
        inz
        dex
        bne -
        iny
        cpy #8
        bne l_tui_a_row
        clc
        lda ptr0
        adc #64
        sta ptr0
        lda ptr0+1
        adc #0
        sta ptr0+1
        lda ptr0+2
        adc #0
        sta ptr0+2
        .if TUI_CHARSET == 1
        clc
        lda tui_fp
        adc #8
        sta tui_fp
        bcc +
        inc tui_fp+1
+
        .else
        clc
        lda tui_str
        adc #8
        sta tui_str
        bcc +
        inc tui_str+1
+
        .endif
        inc tmp2
        bne l_tui_a_glyph
        inc tmp1
        lda tmp1
        cmp #8
        bne l_tui_a_bg
        ldz #0
        rts

        .section bss
l_tui_g:        .fill 8
        .send

tui_setattr:
        sta tui_attr
        pha
        and #$0F
        sta tui_fgbyte
        pla
        pha
        lsr
        lsr
        lsr
        lsr
        and #7
        clc
        adc #TUI_CHAR_HI
        sta tui_bgbyte
        pla
        rts

tui_goto:
        stx tui_row
        sty tui_col
        tya
        asl
        clc
        adc l_tui_rowlo,x
        sta l_tui_t
        lda l_tui_rowhi,x
        adc #0
        sta l_tui_t2
        clc
        lda l_tui_t
        adc #<TUI_SCREEN
        sta tui_sp
        lda l_tui_t2
        adc #>TUI_SCREEN
        sta tui_sp+1
        lda #`TUI_SCREEN
        adc #0
        sta tui_sp+2
        lda #0
        sta tui_sp+3
        clc
        lda l_tui_t
        adc #<TUI_COLOUR_OFS
        sta tui_cp
        lda l_tui_t2
        adc #>TUI_COLOUR_OFS
        sta tui_cp+1
        lda #$F8
        sta tui_cp+2
        lda #$0F
        sta tui_cp+3
        rts

tui_putc:
        phz
        pha
        ldz #0
        sta [tui_sp],z
        inz
        lda tui_bgbyte
        sta [tui_sp],z
        lda tui_fgbyte
        sta [tui_cp],z                  ; colour byte 1: the colour (byte 0 stays 0)
        dez
        lda #0
        sta [tui_cp],z
        pla
        plz
l_tui_next:
        pha
        clc
        lda tui_sp
        adc #2
        sta tui_sp
        bcc +
        inc tui_sp+1
+       clc
        lda tui_cp
        adc #2
        sta tui_cp
        bcc +
        inc tui_cp+1
+       inc tui_col
        pla
        rts

tui_puts:
        sta tui_str
        stx tui_str+1
        ldy #0
-       lda (tui_str),y
        beq +
        jsr tui_putc
        iny
        bne -
+       rts

tui_puts_hot:
        sta tui_str
        stx tui_str+1
        ldy #0
l_tui_ph:
        lda (tui_str),y
        beq l_tui_ph_end
        cmp #'&'
        beq l_tui_ph_hot
        jsr tui_putc
        iny
        bne l_tui_ph
l_tui_ph_end:
        rts
l_tui_ph_hot:
        lda tui_attr
        pha
        lda tui_hotattr
        jsr tui_setattr
        iny
        lda (tui_str),y
        jsr tui_putc
        pla
        jsr tui_setattr
        iny
        bra l_tui_ph

tui_rep:
        cpx #0
        beq +
-       jsr tui_putc
        dex
        bne -
+       rts

tui_rect:
        sta l_tui_rc
        lda tui_r
        sta l_tui_rrow
        lda tui_h
        sta l_tui_rn
        beq l_tui_rend
-       ldx l_tui_rrow
        ldy tui_c
        jsr tui_goto
        lda l_tui_rc
        ldx tui_w
        jsr tui_rep
        inc l_tui_rrow
        dec l_tui_rn
        bne -
l_tui_rend:
        rts
l_tui_rc:       .byte 0
l_tui_rrow:     .byte 0
l_tui_rn:       .byte 0

tui_frame:
        ldx tui_r
        ldy tui_c
        jsr tui_goto
        lda #TG_TL
        jsr tui_putc
        lda #TG_HLINE
        ldx tui_w
        dex
        dex
        jsr tui_rep
        lda #TG_TR
        jsr tui_putc
        lda tui_r
        sta l_tui_rrow
        ldx tui_h
        dex
        dex
        stx l_tui_rn
        beq l_tui_fb
-       inc l_tui_rrow
        ldx l_tui_rrow
        ldy tui_c
        jsr tui_goto
        lda #TG_VLINE
        jsr tui_putc
        clc
        lda tui_c
        adc tui_w
        tay
        dey
        ldx l_tui_rrow
        jsr tui_goto
        lda #TG_VLINE
        jsr tui_putc
        dec l_tui_rn
        bne -
l_tui_fb:
        clc
        lda tui_r
        adc tui_h
        tax
        dex
        ldy tui_c
        jsr tui_goto
        lda #TG_BL
        jsr tui_putc
        lda #TG_HLINE
        ldx tui_w
        dex
        dex
        jsr tui_rep
        lda #TG_BR
        jmp tui_putc

tui_box:
        sta l_tui_title
        stx l_tui_title+1
        lda #32
        jsr tui_rect
        jsr tui_frame
tui_title:
        lda l_tui_title+1
        beq +
        ; centre " title " on the top edge
        sta tui_str+1
        lda l_tui_title
        sta tui_str
        ldy #0
-       lda (tui_str),y
        beq l_tui_tl
        iny
        bne -
l_tui_tl:
        tya
        clc
        adc #2
        sta l_tui_t
        sec
        lda tui_w
        sbc l_tui_t
        lsr
        clc
        adc tui_c
        tay
        ldx tui_r
        jsr tui_goto
        lda #32
        jsr tui_putc
        lda l_tui_title
        ldx l_tui_title+1
        jsr tui_puts
        lda #32
        jsr tui_putc
+       rts
l_tui_title:    .word 0

tui_recolour:
        cpx #0
        beq l_tui_rc_end
        phz
-       ldz #1
        lda tui_bgbyte
        sta [tui_sp],z
        lda tui_fgbyte
        sta [tui_cp],z
        jsr l_tui_next
        dex
        bne -
        plz
l_tui_rc_end:
        rts

; the shadow is 2 cells wide and 1 high, offset one row down and two columns right
tui_shadow:
        lda tui_attr
        pha
        lda #$08                        ; dark grey on black, keeping each cell's glyph
        jsr tui_setattr
        ; bottom edge
        clc
        lda tui_r
        adc tui_h
        cmp #TUI_ROWS
        bcs l_tui_sr
        tax
        clc
        lda tui_c
        adc #2
        tay
        jsr tui_goto
        lda tui_c
        clc
        adc #2
        adc tui_w
        cmp #TUI_COLS + 1
        lda tui_w
        bcc +
        sec
        lda #TUI_COLS
        sbc tui_c
        sec
        sbc #2
+       tax
        jsr tui_recolour
l_tui_sr:
        ; right edge
        clc
        lda tui_c
        adc tui_w
        sta l_tui_sc
        cmp #TUI_COLS - 1
        bcs l_tui_send
        lda tui_r
        inc a
        sta l_tui_rrow
        lda tui_h
        sta l_tui_rn
-       lda l_tui_rrow
        cmp #TUI_ROWS
        bcs l_tui_send
        tax
        ldy l_tui_sc
        jsr tui_goto
        ldx #2
        jsr tui_recolour
        inc l_tui_rrow
        dec l_tui_rn
        bne -
l_tui_send:
        pla
        jmp tui_setattr
l_tui_sc:       .byte 0

; A/X = string. The output position is the cell after the last character.
tui_rtext:
        sta tui_str
        stx tui_str+1
        ldy #0
-       lda (tui_str),y
        beq +
        iny
        bne -
+       sty l_tui_t
        sec
        lda tui_col
        sbc l_tui_t
        tay
        ldx tui_row
        jsr tui_goto
        lda tui_str
        ldx tui_str+1
        jmp tui_puts

; A/X = string, Y = width
tui_centre:
        sta tui_str
        stx tui_str+1
        sty l_tui_t2
        ldy #0
-       lda (tui_str),y
        beq +
        iny
        bne -
+       sty l_tui_t
        sec
        lda l_tui_t2
        sbc l_tui_t
        lsr
        clc
        adc tui_col
        tay
        ldx tui_row
        jsr tui_goto
        lda tui_str
        ldx tui_str+1
        jmp tui_puts

tui_dec3:
        ldx #0
        sta l_tui_num
        stx l_tui_num+1
        jsr l_tui_digits
        ldx #2
        bra l_tui_dpr
tui_dec5:
        sta l_tui_num
        stx l_tui_num+1
        jsr l_tui_digits
        ldx #0
l_tui_dpr:
-       lda l_tui_buf,x
        jsr tui_putc
        inx
        cpx #5
        bne -
        rts
tui_dec16:
        sta l_tui_num
        stx l_tui_num+1
        jsr l_tui_digits
        ldx #0
-       lda l_tui_buf,x
        cmp #'0'
        bne l_tui_dpr
        inx
        cpx #4
        bne -
        bra l_tui_dpr

; l_tui_num -> five ASCII digits
l_tui_digits:
        ldx #0
l_tui_dg:
        lda #'0'
        sta l_tui_buf,x
-       sec
        lda l_tui_num
        sbc l_tui_tens,x
        tay
        lda l_tui_num+1
        sbc l_tui_tenh,x
        bcc +
        sta l_tui_num+1
        sty l_tui_num
        inc l_tui_buf,x
        bra -
+       inx
        cpx #5
        bne l_tui_dg
        rts
        .section bss
l_tui_buf:      .fill 5
        .send
l_tui_tens:     .byte <10000, <1000, <100, <10, <1
l_tui_tenh:     .byte >10000, >1000, >100, >10, >1

; save the screen and its colours (2 x 4000 bytes) on the attic stack
tui_push:
        jsr l_tui_layerptr
        jsr l_tui_scr1
        jsr l_tui_copy
        jsr l_tui_layerptr2
        jsr l_tui_col1
        jsr l_tui_copy
        inc tui_layer
        rts
tui_pop:
        dec tui_layer
        jsr l_tui_layerptr
        jsr l_tui_swap
        jsr l_tui_scr2
        jsr l_tui_copy
        jsr l_tui_layerptr2
        jsr l_tui_swap
        jsr l_tui_col2
        jmp l_tui_copy

; ptr2 = layer + 0
l_tui_layerptr:
        lda tui_layer                   ; 8 KB a level: bits 13+
        asl
        asl
        asl
        asl
        asl
        sta ptr2+1
        lda #0
        sta ptr2
        lda #`TUI_LAYER_BASE
        sta ptr2+2
        lda #TUI_LAYER_BASE >> 24
        sta ptr2+3
        rts
; ptr2 = layer + 4 KB
l_tui_layerptr2:
        jsr l_tui_layerptr
        lda ptr2+1
        ora #$10
        sta ptr2+1
        rts
l_tui_swap:
        ldx #3
-       lda ptr2,x
        sta ptr1,x
        dex
        bpl -
        rts
; source ptr1 = the screen, or destination ptr2 = the screen
l_tui_scr1:
        lda #<TUI_SCREEN
        sta ptr1
        lda #>TUI_SCREEN
        sta ptr1+1
        lda #`TUI_SCREEN
        sta ptr1+2
        lda #0
        sta ptr1+3
        rts
l_tui_scr2:
        lda #<TUI_SCREEN
        sta ptr2
        lda #>TUI_SCREEN
        sta ptr2+1
        lda #`TUI_SCREEN
        sta ptr2+2
        lda #0
        sta ptr2+3
        rts
l_tui_col1:
        lda #<TUI_COLOUR_OFS
        sta ptr1
        lda #>TUI_COLOUR_OFS
        sta ptr1+1
        lda #$F8
        sta ptr1+2
        lda #$0F
        sta ptr1+3
        rts
l_tui_col2:
        lda #<TUI_COLOUR_OFS
        sta ptr2
        lda #>TUI_COLOUR_OFS
        sta ptr2+1
        lda #$F8
        sta ptr2+2
        lda #$0F
        sta ptr2+3
        rts
l_tui_copy:
        lda #<4000
        sta tmp5
        lda #>4000
        sta tmp5+1
        jmp dma_copy_far

; Scroll bars. tui_sb_pos / tui_sb_range (words) say where the thumb goes.
tui_sb_pos:     .word 0
tui_sb_range:   .word 0                 ; pos runs 0..range
tui_sb_attr:    .byte $70               ; arrows and track, black on grey, whatever's around them

; thumb cell (0-based inside the track of A cells) -> A
tui_sb_thumb:
        sta l_tui_t2                    ; track cells
        lda tui_sb_range
        ora tui_sb_range+1
        beq l_tui_sb0
        ; thumb = pos * (cells - 1) / range
        lda tui_sb_pos
        sta MULTINA
        lda tui_sb_pos+1
        sta MULTINA+1
        lda #0
        sta MULTINA+2
        sta MULTINA+3
        sta MULTINB+1
        sta MULTINB+2
        sta MULTINB+3
        ldx l_tui_t2
        dex
        stx MULTINB
        lda MULTOUT                     ; pos * (cells-1), 24 bits. Copied out first: the
        ldx MULTOUT+1                   ; output changes as soon as an input does.
        ldy MULTOUT+2
        sta MULTINA
        stx MULTINA+1
        sty MULTINA+2
        lda #0
        sta MULTINA+3
        lda tui_sb_range
        sta MULTINB
        lda tui_sb_range+1
        sta MULTINB+1
-       bit DIVBUSY
        bmi -
        lda DIVOUT+4
        rts
l_tui_sb0:
        lda #0
        rts

; vertical bar: column tui_c, rows tui_r .. tui_r + tui_h - 1, arrows included
tui_vscroll:
        lda tui_sb_attr
        jsr tui_setattr
        ldx tui_r
        ldy tui_c
        jsr tui_goto
        lda #TG_UP
        jsr tui_putc
        sec
        lda tui_h
        sbc #2
        sta l_tui_vcells
        jsr tui_sb_thumb
        sta l_tui_vthumb
        ldx #0
-       phx
        txa
        clc
        adc tui_r
        inc a
        tax
        ldy tui_c
        jsr tui_goto
        plx
        lda #TG_SHADE
        cpx l_tui_vthumb
        bne +
        lda tui_attr
        pha
        lda #$00                        ; a black thumb
        jsr tui_setattr
        lda #32
        jsr tui_putc
        pla
        jsr tui_setattr
        bra ++
+       jsr tui_putc
+       inx
        cpx l_tui_vcells
        bne -
        clc
        lda tui_r
        adc tui_h
        tax
        dex
        ldy tui_c
        jsr tui_goto
        lda #TG_DOWN
        jmp tui_putc
l_tui_vcells:   .byte 0
l_tui_vthumb:   .byte 0

; horizontal bar: row tui_r, columns tui_c .. tui_c + tui_w - 1, arrows included
tui_hscroll:
        lda tui_sb_attr
        jsr tui_setattr
        ldx tui_r
        ldy tui_c
        jsr tui_goto
        lda #TG_LEFT
        jsr tui_putc
        sec
        lda tui_w
        sbc #2
        sta l_tui_vcells
        jsr tui_sb_thumb
        sta l_tui_vthumb
        ldx #0
-       lda #TG_SHADE
        cpx l_tui_vthumb
        bne +
        lda tui_attr
        pha
        lda #$00
        jsr tui_setattr
        lda #32
        jsr tui_putc
        pla
        jsr tui_setattr
        bra ++
+       jsr tui_putc
+       inx
        cpx l_tui_vcells
        bne -
        lda #TG_RIGHT
        jmp tui_putc
