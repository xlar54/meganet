;=======================================================================================
; lib/hwsprite.asm - the VIC-IV's eight hardware sprites (pointers, cursors, a few
; objects over any screen mode). From deluxepaint65 / mega-simcity.
;
;   hws_init       16-bit sprite pointers from a table in bank 0, all sprites off and
;                  in front, platform detected (hws_xfix: real hardware draws sprites
;                  about 16 px further left than Xemu - $D60F bit 5 tells them apart -
;                  in H320 modes only: at H640 they agree, so hws_place skips the fix)
;   hws_shape      X = sprite, A/Y = shape address lo/hi (bank 0, 64-byte aligned;
;                  21 rows x 3 bytes, C64 format). hws_shape_far: A/Y/Z = address
;                  bits 0-7 / 8-15 / 16-23 (any chip RAM).
;   hws_place      X = sprite, hws_x (word) / hws_y (word) = SCREEN pixels (0,0 = top
;                  left of the 320x200 text area): adds the border offset and hws_xfix,
;                  sets all X/Y high bits
;   hws_on / hws_off   X = sprite
;   hws_colour     X = sprite, A = colour
;   is_real_hw     A = 1 on a real MEGA65, 0 in Xemu (set by hws_init)
;
; VIC-IV extras (MEGA65 book, appendix Q, "Variable Sprite Size" / "Full-Colour Sprite Mode"):
;   hws_full_colour  X = sprite: 4 bits a pixel, 16 pixels wide (8 bytes a row, high nibble
;                  = left pixel), nibble 0 transparent. Sprite n's colour c is palette
;                  entry n * 16 + c of the sprites' palette bank.
;   hws_height     A = rows, X = sprite: makes it that tall (all tall sprites share A)
;   hws_pal_bank   A = palette bank 0-3 the sprites take their colours from
;   hws_pal_edit   A = palette bank that writes to $D100-$D3FF go to. Put it back to the
;                  screen's bank afterwards (hws_screen_bank, read by hws_init).
;   hws_from_bitmap  16-colour sprite data from 256-colour pixels anywhere (a tile, a part
;                  of a framebuffer, art in attic): ptr0 = the first pixel (28 bits), ptr1 =
;                  the sprite data (HWS_BM_ROWS rows of 8 bytes are written), ptr2 = a
;                  256-byte table, palette index -> sprite colour (0-15; 0 see-through).
;                  hws_bm_w pixels (1-16) across, hws_bm_h rows, hws_bm_step bytes from one
;                  pixel to the next (2: every second, for art drawn 2 screen pixels to 1 in
;                  H640), hws_bm_stride (word) bytes from one row to the next. Pixels past
;                  the width and rows past the height are see-through, so sprites of
;                  different heights can share the one tall-sprite height. Changes ptr0,
;                  ptr1, tmp0-tmp3; Z is 0 after.
;
; Multicolour, expansion and priority: set SPR_MC / SPR_XEXP / SPR_YEXP / SPR_PRIO bits
; directly.
;=======================================================================================

        .weak
HWS_SCREEN_X    = 24                    ; sprite coordinate of the first text pixel
HWS_SCREEN_Y    = 50
HWS_REALHW_FIX  = 16
SPR_HGTEN       = $D055                 ; tall sprite enables
SPR_HGT         = $D056                 ; their height
SPR_X64         = $D057                 ; 64-bit rows (16 px in 16-colour mode)
VIC4_PALSEL     = $D070                 ; bits 6-7 edited bank, 4-5 screen, 2-3 sprites
        .endweak

hws_x:          .word 0
hws_y:          .word 0
hws_xfix:       .byte 0
is_real_hw:     .byte 0
hws_screen_bank: .byte 0                ; the screen's palette bank (VIC4_PALSEL bits 4-5)
l_hws_bit:      .byte 1, 2, 4, 8, 16, 32, 64, 128

        .align 16
hws_ptrs:       .fill 16                ; 2-byte pointer (address / 64) per sprite

hws_init:
        lda #$47
        sta VIC4_KEY
        lda #$53
        sta VIC4_KEY
        lda #0
        sta SPR_ENABLE
        sta SPR_XMSB
        sta SPR_XMSB9
        sta SPR_YMSB8
        sta SPR_YMSB9
        sta SPR_XEXP
        sta SPR_YEXP
        sta SPR_MC
        sta SPR_PRIO
        sta SPR_16COL
        sta SPR_X64
        sta SPR_HGTEN
        sta hws_xfix
        lda VIC4_PALSEL
        lsr
        lsr
        lsr
        lsr
        and #3
        sta hws_screen_bank
        lda #0
        sta is_real_hw
        lda #<hws_ptrs
        sta SPR_PTRLO
        lda #>hws_ptrs
        sta SPR_PTRHI
        lda #$80                        ; 16-bit pointers, table in bank 0
        sta SPR_PTRBNK
        lda PLATFORM_FLAGS
        and #%00100000
        beq +
        lda #1
        sta is_real_hw
        lda #HWS_REALHW_FIX
        sta hws_xfix
+       rts

hws_shape:
        ldz #0
hws_shape_far:
        sta tmp4
        sty tmp4+1
        stz tmp1                        ; (Z register: bits 16-23)
        ldy #6                          ; address / 64
-       lsr tmp1
        ror tmp4+1
        ror tmp4
        dey
        bne -
        txa
        asl
        tay
        lda tmp4
        sta hws_ptrs,y
        lda tmp4+1
        sta hws_ptrs+1,y
        rts

hws_full_colour:
        lda l_hws_bit,x
        tsb SPR_16COL
        tsb SPR_X64
        lda #0                          ; nibble 0 is the transparent one
        sta SPR_COLOR,x
        rts

hws_height:
        sta SPR_HGT
        lda l_hws_bit,x
        tsb SPR_HGTEN
        rts

hws_pal_bank:
        and #3
        asl
        asl
        sta tmp0
        lda VIC4_PALSEL
        and #%11110011
        ora tmp0
        sta VIC4_PALSEL
        rts

hws_pal_edit:
        and #3
        lsr
        ror
        ror
        sta tmp0                        ; bank << 6
        lda VIC4_PALSEL
        and #%00111111
        ora tmp0
        sta VIC4_PALSEL
        rts

hws_bm_w:       .byte 16
hws_bm_h:       .byte 21
hws_bm_step:    .byte 1
hws_bm_stride:  .word 16
        .weak
HWS_BM_ROWS     = 64                    ; rows hws_from_bitmap writes (the tallest sprite)
        .endweak

hws_from_bitmap:
        lda #HWS_BM_ROWS
        sta tmp2                        ; rows to write
        lda hws_bm_h
        sta tmp3                        ; rows of the bitmap left
l_hfb_row:
        ldx #0                          ; the pixel across
        ldy #0                          ; the sprite byte across
        lda #0
        sta tmp1                        ; the bitmap byte across
l_hfb_byte:
        jsr l_hfb_px                    ; the left pixel: the high nibble
        asl
        asl
        asl
        asl
        sta tmp0
        jsr l_hfb_px
        ora tmp0
        sta tmp0
        tya
        taz
        lda tmp0
        sta [ptr1],z
        iny
        cpy #8
        bne l_hfb_byte
        clc                             ; the next sprite row
        lda ptr1
        adc #8
        sta ptr1
        bcc +
        inc ptr1+1
        bne +
        inc ptr1+2
+       lda tmp3                        ; the next bitmap row
        beq +
        dec tmp3
        clc
        lda ptr0
        adc hws_bm_stride
        sta ptr0
        lda ptr0+1
        adc hws_bm_stride+1
        sta ptr0+1
        bcc +
        inc ptr0+2
+       dec tmp2
        bne l_hfb_row
        ldz #0
        rts
; the next pixel's sprite colour -> A (0 past the bitmap's width or height); X, tmp1 move on
l_hfb_px:
        lda tmp3
        beq l_hfb_0
        cpx hws_bm_w
        bcs l_hfb_0
        inx
        lda tmp1
        taz
        clc
        adc hws_bm_step
        sta tmp1
        lda [ptr0],z
        taz
        lda [ptr2],z
        and #$0f
        rts
l_hfb_0:
        lda #0
        rts

hws_on:
        lda l_hws_bit,x
        tsb SPR_ENABLE
        rts
hws_off:
        lda l_hws_bit,x
        trb SPR_ENABLE
        rts
hws_colour:
        sta SPR_COLOR,x
        rts

hws_place:
        clc
        lda hws_x
        adc #HWS_SCREEN_X
        sta tmp4
        lda hws_x+1
        adc #0
        sta tmp4+1
        bit VIC3_CTRL                   ; H640: real hardware matches Xemu, no fix
        bmi l_hws_nofix
        clc
        lda tmp4
        adc hws_xfix
        sta tmp4
        lda tmp4+1
        adc #0
        sta tmp4+1
l_hws_nofix:
        clc
        lda hws_y
        adc #HWS_SCREEN_Y
        sta tmp5
        lda hws_y+1
        adc #0
        sta tmp5+1
        txa
        asl
        tay
        lda tmp4
        sta SPR_XLO,y
        lda tmp5
        sta SPR_XLO+1,y
        lda l_hws_bit,x
        sta tmp0
        ; X bit 8, X bit 9, Y bit 8, Y bit 9
        lda tmp4+1
        ldy #SPR_XMSB - SPR_XMSB
        jsr l_hws_bit0
        lda tmp4+1
        lsr
        ldy #SPR_XMSB9 - SPR_XMSB
        jsr l_hws_bit0
        lda tmp5+1
        ldy #SPR_YMSB8 - SPR_XMSB
        jsr l_hws_bit0
        lda tmp5+1
        lsr
        ldy #SPR_YMSB9 - SPR_XMSB
; set/clear this sprite's bit (tmp0) in register SPR_XMSB+Y from bit 0 of A
l_hws_bit0:
        lsr
        lda tmp0
        bcs +
        eor #$ff
        and SPR_XMSB,y
        sta SPR_XMSB,y
        rts
+       ora SPR_XMSB,y
        sta SPR_XMSB,y
        rts
