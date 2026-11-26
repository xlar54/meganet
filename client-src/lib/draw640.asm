;=======================================================================================
; lib/draw640.asm - drawing into a lib/fcm640.asm framebuffer (640x200, 256 colours, cells
; laid out row by row). Everything is clipped to the rectangle d6_cx0..d6_cx1 (words),
; d6_cy0..d6_cy1.
;
;   d6_clip_all    clip to the whole screen
;   d6_plot        (d6_x, d6_y) in d6_col
;   d6_hline       d6_x .. d6_x1 on row d6_y
;   d6_vline       d6_y .. d6_y1 in column d6_x
;   d6_fill        the rectangle d6_x..d6_x1, d6_y..d6_y1
;   d6_frame       its outline
;   d6_line        (d6_x, d6_y) to (d6_x1, d6_y1), signed 16-bit ends (clipped per pixel,
;                  unless both ends are inside); d6_line_in when the caller knows they are
;   d6_inside      carry set if point X (0: d6_x, d6_y; 4: d6_x1, d6_y1) is inside the clip
;   d6_text        A/X = zero-terminated ASCII at column d6_tc (0-79, 8-pixel cells), row
;                  d6_y (any pixel row), in d6_col on d6_bg ($ff = transparent)
;   d6_char        one character A there; d6_tc moves on
;
;   d6_target      A/X/Y = bits 16-23, 24-31 of the buffer to draw into (bank aligned, may
;                  be in attic: an off-screen buffer); d6_target_screen puts F640_BUF0 back
;
; Needs fcm640 (F640_BUF0 is drawn into) and a font: D6_FONT, glyphs for ASCII 32-127,
; 8 bytes each, bit 7 = the left pixel. d6_p is a 4-byte base-page pointer (default ptr1).
;=======================================================================================

        .weak
D6_FONT         = font8
d6_p            = ptr1
        .endweak

d6_x:           .word 0
d6_y:           .word 0                 ; (words: lines can start off screen)
d6_x1:          .word 0
d6_y1:          .word 0
d6_col:         .byte 1
d6_bg:          .byte 0
d6_tc:          .byte 0
d6_cx0:         .word 0
d6_cx1:         .word 639
d6_cy0:         .word 0
d6_cy1:         .word 199
l_d6_t:         .byte 0
l_d6_n:         .word 0
l_d6_dx:        .word 0
l_d6_dy:        .word 0
l_d6_sx:        .byte 0
l_d6_sy:        .byte 0
l_d6_err:       .word 0
l_d6_e2:        .word 0
l_d6_str:       .word 0
l_d6_gl:        .word 0
l_d6_row:       .byte 0
l_d6_fast:      .byte 0
d6_bk:          .byte `F640_BUF0        ; the buffer drawn into: bits 16-23, 24-31
d6_hi:          .byte F640_BUF0 >> 24

d6_target_screen:
        lda #`F640_BUF0
        ldx #F640_BUF0 >> 24
d6_target:
        sta d6_bk
        stx d6_hi
        rts

d6_clip_all:
        lda #0
        sta d6_cx0
        sta d6_cx0+1
        sta d6_cy0
        sta d6_cy0+1
        lda #<639
        sta d6_cx1
        lda #>639
        sta d6_cx1+1
        lda #199
        sta d6_cy1
        lda #0
        sta d6_cy1+1
        rts

; carry set if (d6_x, d6_y) is inside the clip rectangle (signed compares); d6_inside:
; X = 0 for (d6_x, d6_y), 4 for (d6_x1, d6_y1)
l_d6_inside:
        ldx #0
d6_inside:
        lda d6_x,x                      ; x >= cx0
        cmp d6_cx0
        lda d6_x+1,x
        sbc d6_cx0+1
        bvc +
        eor #$80
+       bmi _no
        lda d6_cx1                      ; cx1 >= x
        cmp d6_x,x
        lda d6_cx1+1
        sbc d6_x+1,x
        bvc +
        eor #$80
+       bmi _no
        lda d6_y,x
        cmp d6_cy0
        lda d6_y+1,x
        sbc d6_cy0+1
        bvc +
        eor #$80
+       bmi _no
        lda d6_cy1
        cmp d6_y,x
        lda d6_cy1+1
        sbc d6_y+1,x
        bvc +
        eor #$80
+       bmi _no
        sec
        rts
_no:    clc
        rts

; d6_p = the byte of pixel (d6_x, d6_y) (on screen)
d6_addr:
        lda d6_y
        and #7
        asl
        asl
        asl
        sta l_d6_t
        lda d6_x
        and #7
        ora l_d6_t
        sta d6_p                        ; (y & 7) * 8 + (x & 7)
        lda d6_x+1                      ; xc = x >> 3
        sta l_d6_t
        lda d6_x
        lsr l_d6_t
        ror
        lsr l_d6_t
        ror
        lsr l_d6_t
        ror
        pha
        and #3                          ; + (xc & 3) << 6
        lsr
        ror
        ror
        ora d6_p
        sta d6_p
        pla
        lsr
        lsr
        sta l_d6_t                      ; + (xc >> 2) << 8
        lda d6_y
        lsr
        lsr
        lsr
        tax
        clc
        lda l_d6_t
        adc l_d6_rowm,x
        sta d6_p+1
        lda l_d6_rowh,x
        adc d6_bk
        sta d6_p+2
        lda d6_hi
        sta d6_p+3
        rts
l_d6_rowm:      .byte <((range(25) * 5120) >> 8)
l_d6_rowh:      .byte >((range(25) * 5120) >> 8)

d6_plot:
        jsr l_d6_inside
        bcc +
        jsr d6_addr
        lda d6_col
        ldz #0
        sta [d6_p],z
+       rts

; d6_hline and d6_vline are one-row and one-column fills (the ends and Y are kept)
d6_hline:
        lda d6_y1
        pha
        lda d6_y1+1
        pha
        lda d6_y
        sta d6_y1
        lda d6_y+1
        sta d6_y1+1
        jsr d6_fill
        pla
        sta d6_y1+1
        pla
        sta d6_y1
        rts

d6_vline:
        lda d6_x1
        pha
        lda d6_x1+1
        pha
        lda d6_x
        sta d6_x1
        lda d6_x+1
        sta d6_x1+1
        jsr d6_fill
        pla
        sta d6_x1+1
        pla
        sta d6_x1
        rts

; d6_fill: the rectangle d6_x..d6_x1, d6_y..d6_y1, clipped (the corners and Y are kept).
; By DMA, band by band (8 pixel rows: one cell row). A whole cell's rows in the band are
; contiguous: one fill. A part cell: one fill down each of its columns (step 8).
L_D6W_X0        = 0                     ; l_d6w: a copy of d6_x .. d6_cy1
L_D6W_Y0        = d6_y - d6_x
L_D6W_X1        = d6_x1 - d6_x
L_D6W_Y1        = d6_y1 - d6_x
d6_fill:
        phy
        ldx #d6_cy1 + 1 - d6_x
-       lda d6_x,x
        sta l_d6w,x
        dex
        bpl -
        ldx #L_D6W_X0                   ; x0 = max(x0, cx0)
        ldy #d6_cx0 - d6_x
        lda #0
        jsr l_d6_clamp
        ldx #L_D6W_Y0                   ; y0 = max(y0, cy0)
        ldy #d6_cy0 - d6_x
        lda #0
        jsr l_d6_clamp
        ldx #L_D6W_X1                   ; x1 = min(x1, cx1)
        ldy #d6_cx1 - d6_x
        lda #$80
        jsr l_d6_clamp
        ldx #L_D6W_Y1                   ; y1 = min(y1, cy1)
        ldy #d6_cy1 - d6_x
        lda #$80
        jsr l_d6_clamp
        ldx #L_D6W_X1                   ; nothing if x1 < x0 or y1 < y0
        ldy #L_D6W_X0
        jsr l_d6_lt
        bmi _r
        ldx #L_D6W_Y1
        ldy #L_D6W_Y0
        jsr l_d6_lt
        bmi _r
        lda l_d6w+L_D6W_X0              ; the first and last cells, and the columns in them
        and #7
        sta l_d6f_xa
        lda l_d6w+L_D6W_X1
        and #7
        sta l_d6f_xb
        ldx #L_D6W_X0
        jsr l_d6_cell
        sta l_d6f_c0
        ldx #L_D6W_X1
        jsr l_d6_cell
        sta l_d6f_c1
        lda l_d6w+L_D6W_Y0
        sta l_d6f_y
_band:  lda l_d6f_y                     ; this band: rows ra .. rb
        and #7
        sta l_d6f_ra
        lda l_d6f_y
        lsr
        lsr
        lsr
        tax
        lda l_d6_rowm,x
        sta l_d6f_bm
        lda l_d6_rowh,x
        sta l_d6f_bh
        ldx #7
        lda l_d6f_y                     ; (y1's band: to y1 & 7)
        eor l_d6w+L_D6W_Y1
        cmp #8
        bcs +
        lda l_d6w+L_D6W_Y1
        and #7
        tax
+       txa
        sec
        sbc l_d6f_ra
        inc a
        sta l_d6f_n                     ; rows
        lda l_d6f_c0
        sta l_d6f_c
_cell:  ldx #0                          ; columns pa .. pb of this cell
        lda l_d6f_c
        cmp l_d6f_c0
        bne +
        ldx l_d6f_xa
+       stx l_d6f_pa
        ldx #7
        cmp l_d6f_c1
        bne +
        ldx l_d6f_xb
+       stx l_d6f_pb
        lda l_d6f_pa                    ; the whole cell: one fill of rows * 8
        bne _cols
        cpx #7
        bne _cols
        lda l_d6f_n
        asl
        asl
        asl
        ldx #1
        ldy #0
        jsr l_d6_dma
        bra _nc
_cols:  lda l_d6f_n                     ; else down each column
        ldx #8
        ldy l_d6f_pa
        jsr l_d6_dma
        lda l_d6f_pa
        inc l_d6f_pa
        cmp l_d6f_pb
        bcc _cols
_nc:    lda l_d6f_c
        inc l_d6f_c
        cmp l_d6f_c1
        bcc _cell
        lda l_d6f_y                     ; the next band, if y1 is past this one
        ora #7
        cmp l_d6w+L_D6W_Y1
        bcs _r
        inc a
        sta l_d6f_y
        jmp _band
_r:     ply
        rts

; N set if the word l_d6w + X < l_d6w + Y (signed)
l_d6_lt:
        lda l_d6w,x
        cmp l_d6w,y
        lda l_d6w+1,x
        sbc l_d6w+1,y
        bvc +
        eor #$80
+       rts

; A = 0: raise the word l_d6w + X to l_d6w + Y; A = $80: lower it to it
l_d6_clamp:
        sta l_d6_t
        jsr l_d6_lt
        eor l_d6_t
        bpl +
        lda l_d6w,y
        sta l_d6w,x
        lda l_d6w+1,y
        sta l_d6w+1,x
+       rts

; A = the word l_d6w + X (0-639) >> 3
l_d6_cell:
        lda l_d6w+1,x
        asl
        asl
        asl
        asl
        asl
        sta l_d6_t
        lda l_d6w,x
        lsr
        lsr
        lsr
        ora l_d6_t
        rts

; fill A bytes with d6_col, destination step X, from column Y of row ra of cell c in this
; band
l_d6_dma:
        sta l_d6_fj_n
        stx l_d6_fj_st
        lda l_d6f_ra                    ; (c & 3) << 6 | ra << 3 | column
        asl
        asl
        asl
        sta l_d6_t
        tya
        ora l_d6_t
        sta l_d6_t
        lda l_d6f_c
        and #3
        lsr
        ror
        ror
        ora l_d6_t
        sta l_d6_fj_d
        lda l_d6f_c                     ; + (c >> 2) << 8 + the band
        lsr
        lsr
        clc
        adc l_d6f_bm
        sta l_d6_fj_d+1
        lda l_d6f_bh
        adc d6_bk
        pha
        and #$0f
        sta l_d6_fj_b
        pla
        lsr
        lsr
        lsr
        lsr
        sta l_d6_fj_mb                  ; (bits 20-23, then 24-27 above them)
        lda d6_hi
        asl
        asl
        asl
        asl
        ora l_d6_fj_mb
        sta l_d6_fj_mb
        lda d6_col
        sta l_d6_fj_v
        lda #>l_d6_fj
        sta DMA_ADDRMSB
        lda #<l_d6_fj
        sta DMA_ADDRLSB_ETRIG
        rts

l_d6_fj:        .byte DMAOPT_F018B, DMAOPT_DST_MB
l_d6_fj_mb:     .byte 0
                .byte DMAOPT_DST_STEP_INT
l_d6_fj_st:     .byte 1
                .byte DMAOPT_END, DMACMD_FILL
l_d6_fj_n:      .word 0
l_d6_fj_v:      .byte 0, 0, 0           ; (a fill's value is the source's low byte)
l_d6_fj_d:      .word 0
l_d6_fj_b:      .byte 0
                .byte 0
                .word 0
l_d6w:          .fill d6_cy1 + 2 - d6_x
l_d6f_c0:       .byte 0
l_d6f_c1:       .byte 0
l_d6f_xa:       .byte 0
l_d6f_xb:       .byte 0
l_d6f_y:        .byte 0
l_d6f_ra:       .byte 0
l_d6f_pa:       .byte 0
l_d6f_pb:       .byte 0
l_d6f_c:        .byte 0
l_d6f_n:        .byte 0
l_d6f_bm:       .byte 0
l_d6f_bh:       .byte 0

d6_frame:
        lda d6_y                        ; save the corners
        pha
        lda d6_x
        pha
        lda d6_x+1
        pha
        lda d6_x1
        pha
        lda d6_x1+1
        pha
        jsr d6_hline                    ; top
        pla
        sta d6_x1+1
        pla
        sta d6_x1
        pla
        sta d6_x+1
        pla
        sta d6_x
        pla
        sta d6_y
        jsr d6_vline                    ; left
        lda d6_x
        pha
        lda d6_x+1
        pha
        lda d6_x1                       ; right
        sta d6_x
        lda d6_x1+1
        sta d6_x+1
        jsr d6_vline
        pla
        sta d6_x+1
        pla
        sta d6_x
        lda d6_y
        pha
        lda d6_y1                       ; bottom
        sta d6_y
        jsr d6_hline
        pla
        sta d6_y
        rts

; Bresenham, every pixel clipped. When both ends are inside the clip (so every pixel is),
; the pixels' address steps along with them instead (l_d6_fast).
d6_line:
        lda #0
        sta l_d6_fast
        jsr l_d6_inside                 ; both ends inside?
        bcc l_d6_slow
        ldx #d6_x1 - d6_x
        jsr d6_inside
        bcc l_d6_slow
d6_line_in:                             ; (the caller knows both ends are inside)
        lda #$80
        sta l_d6_fast
        jsr d6_addr
        ldz #0
l_d6_slow:
        sec                             ; dx = |x1 - x|, sx
        lda d6_x1
        sbc d6_x
        sta l_d6_dx
        lda d6_x1+1
        sbc d6_x+1
        sta l_d6_dx+1
        lda #1
        sta l_d6_sx
        bit l_d6_dx+1
        bpl +
        lda #$ff
        sta l_d6_sx
        sec
        lda #0
        sbc l_d6_dx
        sta l_d6_dx
        lda #0
        sbc l_d6_dx+1
        sta l_d6_dx+1
+       sec                             ; dy = -|y1 - y|, sy
        lda d6_y1
        sbc d6_y
        sta l_d6_dy
        lda d6_y1+1
        sbc d6_y+1
        sta l_d6_dy+1
        lda #1
        sta l_d6_sy
        bit l_d6_dy+1
        bmi +
        sec                             ; (dy = -dy when positive)
        lda #0
        sbc l_d6_dy
        sta l_d6_dy
        lda #0
        sbc l_d6_dy+1
        sta l_d6_dy+1
        bra ++
+       lda #$ff
        sta l_d6_sy
+       clc                             ; err = dx + dy
        lda l_d6_dx
        adc l_d6_dy
        sta l_d6_err
        lda l_d6_dx+1
        adc l_d6_dy+1
        sta l_d6_err+1
_l:
        bit l_d6_fast
        bpl _plot
        lda d6_col
        sta [d6_p],z
        bra _end
_plot:  jsr d6_plot
_end:   lda d6_x
        cmp d6_x1
        bne +
        lda d6_x+1
        cmp d6_x1+1
        bne +
        lda d6_y
        cmp d6_y1
        bne +
        lda d6_y+1
        cmp d6_y1+1
        bne +
        rts
+       lda l_d6_err                    ; e2 = 2 err
        asl
        sta l_d6_e2
        lda l_d6_err+1
        rol
        sta l_d6_e2+1
        ; e2 >= dy: err += dy, x += sx
        lda l_d6_e2
        cmp l_d6_dy
        lda l_d6_e2+1
        sbc l_d6_dy+1
        bvc +
        eor #$80
+       bmi _ny
        clc
        lda l_d6_err
        adc l_d6_dy
        sta l_d6_err
        lda l_d6_err+1
        adc l_d6_dy+1
        sta l_d6_err+1
        lda l_d6_sx
        jsr l_d6_addx
_ny:    ; e2 <= dx: err += dx, y += sy
        lda l_d6_dx
        cmp l_d6_e2
        lda l_d6_dx+1
        sbc l_d6_e2+1
        bvc +
        eor #$80
+       bmi _l
        clc
        lda l_d6_err
        adc l_d6_dx
        sta l_d6_err
        lda l_d6_err+1
        adc l_d6_dx+1
        sta l_d6_err+1
        lda l_d6_sy
        bmi _up
        inc d6_y                        ; down: + 8, or + 5120 - 56 into the next cell row
        bne +
        inc d6_y+1
+       lda d6_y
        and #7
        beq +
        lda #8
        ldx #0
        bra _dy
+       lda #<(5120 - 56)
        ldx #>(5120 - 56)
        bra _dy
_up:    lda d6_y                        ; up: - 8, or - (5120 - 56)
        bne +
        dec d6_y+1
+       dec d6_y
        lda d6_y
        and #7
        cmp #7
        beq +
        lda #<-8
        ldx #>-8
        bra _dy
+       lda #<-(5120 - 56)
        ldx #>-(5120 - 56)
_dy:    jsr l_d6_padd
        jmp _l
; x += A (1 or -1): + 1, or + 64 - 7 into the next cell
l_d6_addx:
        cmp #1
        bne _left
        inc d6_x
        bne +
        inc d6_x+1
+       lda d6_x
        and #7
        beq +
        lda #1
        ldx #0
        bra l_d6_padd
+       lda #57
        ldx #0
        bra l_d6_padd
_left:  lda d6_x
        bne +
        dec d6_x+1
+       dec d6_x
        lda d6_x
        and #7
        cmp #7
        beq +
        lda #<-1
        ldx #>-1
        bra l_d6_padd
+       lda #<-57
        ldx #>-57
; d6_p (24 bits) += X:A (signed)
l_d6_padd:
        clc
        adc d6_p
        sta d6_p
        txa
        adc d6_p+1
        sta d6_p+1
        txa
        and #$80
        beq +
        lda #$ff
+       adc d6_p+2
        sta d6_p+2
        rts

; text: 8-pixel columns, any row
d6_text:
        sta l_d6_str
        stx l_d6_str+1
_c:     lda l_d6_str
        sta txt_ptr
        lda l_d6_str+1
        sta txt_ptr+1
        ldy #0
        lda (txt_ptr),y
        beq +
        jsr d6_char
        inc l_d6_str
        bne _c
        inc l_d6_str+1
        bra _c
+       rts

d6_char:
        sec                             ; the glyph: D6_FONT + (A - 32) * 8
        sbc #32
        bcs +
        lda #0
+       cmp #96
        bcc +
        lda #0
+       sta l_d6_gl
        lda #0
        sta l_d6_gl+1
        asl l_d6_gl
        rol l_d6_gl+1
        asl l_d6_gl
        rol l_d6_gl+1
        asl l_d6_gl
        rol l_d6_gl+1
        clc
        lda l_d6_gl
        adc #<D6_FONT
        sta l_d6_gl
        lda l_d6_gl+1
        adc #>D6_FONT
        sta l_d6_gl+1
        lda d6_tc                       ; on screen at all?
        cmp #80
        bcs _done
        lda d6_y
        pha
        lda d6_y+1
        pha
        lda d6_tc                       ; x = column * 8
        asl
        asl
        asl
        sta d6_x
        lda d6_tc
        lsr
        lsr
        lsr
        lsr
        lsr
        sta d6_x+1
        lda #0
        sta l_d6_row
_r:
        jsr l_d6_inside                 ; this row inside the clip? (column only checked once)
        bcc _next
        jsr d6_addr
        lda l_d6_gl
        sta tmp6
        lda l_d6_gl+1
        sta tmp6+1
        ldy l_d6_row
        lda (tmp6),y
        sta l_d6_t
        ldz #0
_px:    asl l_d6_t
        bcc _bgp
        lda d6_col
        bra _st
_bgp:   lda d6_bg
        cmp #$ff
        beq _skip
_st:    sta [d6_p],z
_skip:  inz
        cpz #8
        bne _px
        ldz #0
_next:
        inc d6_y
        bne +
        inc d6_y+1
+       inc l_d6_row
        lda l_d6_row
        cmp #8
        bne _r
        pla
        sta d6_y+1
        pla
        sta d6_y
_done:
        inc d6_tc
        rts
