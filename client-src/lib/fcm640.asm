;=======================================================================================
; lib/fcm640.asm - 640x200 Full Colour Mode: 256 colours, one byte per pixel, 80 x 25
; cells (H640, CHR16 + FCLRHI). Two framebuffers of 128,000 bytes each.
;
; Cells are laid out ROW by row (unlike video_fcm's columns): cell (cx, cy) is char
;     F640_BUFn / 64 + cy * 80 + cx
; so a pixel is at
;     buffer + (y >> 3) * 5120 + (x >> 3) * 64 + (y & 7) * 8 + (x & 7)
; and a scan line is 80 runs of 8 bytes, 64 bytes apart.
;
;   f640_init        mode, both screen RAMs, colour RAM cleared; shows buffer 0.
;                    Doesn't touch the framebuffers or the palette.
;   f640_show        A = 0/1: show that buffer (the screen-pointer write; call it right
;                    after wait_frame to switch cleanly)
;   f640_clear       A = 0/1: fill that buffer with colour f640_fill (DMA)
;   f640_row         f640_buf = 0/1, f640_y = line 0..199: f640_ptr -> pixel (0, y);
;                    then write pixels with #F640_PUT (x = f640_x, counts it on)
;   f640_palette     load 256 entries from the tables at f640_pal_r/g/b (pointers set
;                    by the caller: 3 x 256 bytes, plain 8-bit values; swapped here)
;
; Pixel value $FF shows the cell's colour-RAM colour, not palette entry 255: use 0..254.
; Buffer 1 defaults to $20000-$3F3FF, the C65 ROM area: call rom_unprotect first, and
; only after the takeover (no KERNAL or BASIC afterwards).
;=======================================================================================

        .weak
F640_BUF0       = $40000                ; 128,000 bytes each, starting a 64 KB bank
F640_BUF1       = $20000                ; (any 28-bit address: in attic it can be drawn
                                        ; into but not shown; f640_copy10 shows it)
F640_SCR0       = $12000                ; 4000-byte screen RAMs (any chip RAM: bank 1
F640_SCR1       = $13000                ; leaves bank 0 to the program)
        .endweak

F640_ROWBYTES   = 80 * 64               ; one row of cells

; write A as the next pixel of the line set up by f640_row (A, Z changed)
F640_PUT .macro
        ldz f640_x
        sta [f640_ptr],z
        inz
        cpz #8
        bne +
        ldz #0
        clc                             ; next cell: +64
        lda f640_ptr
        adc #64
        sta f640_ptr
        bcc +
        inc f640_ptr+1
        bne +
        inc f640_ptr+2
+       stz f640_x
.endmacro

f640_init:
        lda #$47
        sta VIC4_KEY
        lda #$53
        sta VIC4_KEY
        lda #$80
        trb VIC4_HOTREG                 ; hot registers off: the layout must stick
        lda VIC_CTRL1                   ; display off while we rebuild (bit 7: see notes)
        and #%01101111
        ora #(>IRQ_LINE) << 7
        sta VIC_CTRL1
        lda VIC4_CTRL                   ; CHR16 + FCLRHI (keep VFAST)
        and #%01000000
        ora #%00000101
        sta VIC4_CTRL
        lda VIC3_CTRL                   ; H640, no V400, no ATTR (keep 40 MHz)
        and #%01010111
        ora #%10000000
        sta VIC3_CTRL
        lda #160
        sta VIC4_LINESTEP
        lda #0
        sta VIC4_LINESTEP+1
        lda #80
        sta VIC4_CHRCOUNT
        lda #25
        sta VIC4_DISPROWS
        lda #0
        sta VIC4_COLPTR
        sta VIC4_COLPTR+1
        sta $d015                       ; no hardware sprites
        lda #$50
        sta VIC4_TEXTXPOS
        sta VIC4_SDBDRWD
        ; the two screen RAMs
        lda #<F640_SCR0
        sta ptr0
        lda #>F640_SCR0
        sta ptr0+1
        lda #`F640_SCR0
        sta ptr0+2
        lda #0
        sta ptr0+3
        lda #<(F640_BUF0 / 64)
        sta tmp4
        lda #>(F640_BUF0 / 64)
        sta tmp4+1
        jsr l_f640_screen
        .if F640_BUF1 < $60000          ; (buffer 1 in chip RAM: a screen RAM of its own)
        lda #<F640_SCR1
        sta ptr0
        lda #>F640_SCR1
        sta ptr0+1
        lda #`F640_SCR1
        sta ptr0+2
        lda #0
        sta ptr0+3
        lda #<(F640_BUF1 / 64)
        sta tmp4
        lda #>(F640_BUF1 / 64)
        sta tmp4+1
        jsr l_f640_screen
        .endif
        ; colour RAM: 2 bytes per cell, all zero
        lda #<4000
        sta tmp5
        lda #>4000
        sta tmp5+1
        lda #0
        sta tmp4
        sta tmp4+1
        ldx #$ff
        ldy #$08
        jsr dma_fill
        lda #0
        sta BORDERCOL
        sta BACKCOL
        jsr f640_show
        lda VIC_CTRL1                   ; display on
        and #%01111111
        ora #%00010000
        ora #(>IRQ_LINE) << 7
        sta VIC_CTRL1
        rts

; 2000 words: tmp4, tmp4 + 1, ... at the 28-bit address in ptr0 (it stays inside its bank)
l_f640_screen:
        lda #25
        sta tmp0
l_f640_srow:
        ldx #80
-       ldz #0
        lda tmp4
        sta [ptr0],z
        inz
        lda tmp4+1
        sta [ptr0],z
        inw tmp4
        clc
        lda ptr0
        adc #2
        sta ptr0
        bcc +
        inc ptr0+1
+       dex
        bne -
        dec tmp0
        bne l_f640_srow
        ldz #0
        rts

f640_show:
        tax
        lda l_f640_scr_lo,x
        sta VIC4_SCRNPTR
        lda l_f640_scr_hi,x
        sta VIC4_SCRNPTR+1
        lda l_f640_scr_bk,x
        sta VIC4_SCRNPTR+2
        lda #0
        sta VIC4_SCRNPTR+3
        rts
l_f640_scr_lo:  .byte <F640_SCR0, <F640_SCR1
l_f640_scr_hi:  .byte >F640_SCR0, >F640_SCR1
l_f640_scr_bk:  .byte `F640_SCR0, `F640_SCR1

; fill a whole buffer (two DMA fills: 64000 bytes each)
f640_clear:
        tax
        lda l_f640_bank,x
        and #$0f                        ; (the DMA's bank byte: bits 16-19)
        sta tmp6
        lda #<64000
        sta tmp5
        lda #>64000
        sta tmp5+1
        lda l_f640_mb,x
        sta tmp7
        lda #<F640_BUF0                 ; (both buffers start on a bank boundary)
        sta tmp4
        lda #>F640_BUF0
        sta tmp4+1
        lda f640_fill
        ldx tmp7
        ldy tmp6
        jsr dma_fill
        lda #<64000
        sta tmp4
        lda #>64000
        sta tmp4+1
        lda f640_fill
        ldx tmp7
        ldy tmp6
        jmp dma_fill
; each buffer's bits 16-23 (f640_row), bits 16-19 and the megabyte (DMA)
l_f640_bank:    .byte `F640_BUF0, `F640_BUF1
l_f640_mb:      .byte F640_BUF0 >> 20, F640_BUF1 >> 20
l_f640_hi:      .byte F640_BUF0 >> 24, F640_BUF1 >> 24
        .cerror (F640_BUF0 & $ffff) != 0 || (F640_BUF1 & $ffff) != 0, "fcm640 buffers must start a bank"

; buffer 1 -> buffer 0 (two DMA copies of 64,000 bytes)
f640_copy10:
        .for l_h = 0, l_h < 2, l_h += 1
        lda #<(F640_BUF1 + l_h * 64000)
        sta ptr1
        lda #>(F640_BUF1 + l_h * 64000)
        sta ptr1+1
        lda #`(F640_BUF1 + l_h * 64000)
        sta ptr1+2
        lda #(F640_BUF1 + l_h * 64000) >> 24
        sta ptr1+3
        lda #<(F640_BUF0 + l_h * 64000)
        sta ptr2
        lda #>(F640_BUF0 + l_h * 64000)
        sta ptr2+1
        lda #`(F640_BUF0 + l_h * 64000)
        sta ptr2+2
        lda #(F640_BUF0 + l_h * 64000) >> 24
        sta ptr2+3
        lda #<64000
        sta tmp5
        lda #>64000
        sta tmp5+1
        jsr dma_copy_far
        .next
        rts

f640_row:
        ldx f640_buf
        lda #0
        sta f640_x
        sta f640_ptr
        sta f640_ptr+1
        lda l_f640_hi,x
        sta f640_ptr+3
        lda l_f640_bank,x
        sta f640_ptr+2
        ; + (y >> 3) * 5120: 5120 = $1400
        lda f640_y
        lsr
        lsr
        lsr
        tax
        lda l_f640_rowlo,x
        clc
        adc f640_ptr+1
        sta f640_ptr+1
        lda l_f640_rowhi,x
        adc f640_ptr+2
        sta f640_ptr+2
        ; + (y & 7) * 8
        lda f640_y
        and #7
        asl
        asl
        asl
        sta f640_ptr
        rts
; (y >> 3) * $1400, as the middle and high bytes
l_f640_rowlo:
        .for l_r = 0, l_r < 25, l_r += 1
        .byte <((l_r * F640_ROWBYTES) >> 8)
        .next
l_f640_rowhi:
        .for l_r = 0, l_r < 25, l_r += 1
        .byte >((l_r * F640_ROWBYTES) >> 8)
        .next

f640_palette:
        ldy #0
-       lda (f640_pal_r),y
        jsr l_f640_swap
        sta $d100,y
        lda (f640_pal_g),y
        jsr l_f640_swap
        sta $d200,y
        lda (f640_pal_b),y
        jsr l_f640_swap
        sta $d300,y
        iny
        bne -
        rts
l_f640_swap:                            ; nibble swap (the VIC-IV's palette format)
        asl
        adc #$80
        rol
        asl
        adc #$80
        rol
        rts

; variables (base page pointers are in lib/zp.asm style: give f640_ptr / f640_pal_* to
; the project's base page)
f640_buf:       .byte 0
f640_y:         .byte 0
f640_x:         .byte 0
f640_fill:      .byte 0
