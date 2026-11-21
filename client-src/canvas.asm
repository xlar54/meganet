;=======================================================================================
; canvas.asm - the Art Gallery's Paint (server-src/meganet/gallery/paint.py): the server
; keeps the picture and does the painting; the client shows it as the desktop, sends the
; mouse, and draws a stroke or a shape's outline at once while the server's answer comes.
;
; The picture (320x200, each pixel shown twice across) is kept in a resource slot in the
; framebuffer's own order, a byte a pixel holding its palette entry (CV_FIRST on): pixel
; (x, y) is byte (y >> 3) * 2560 + (x >> 2) * 32 + (y & 7) * 4 + (x & 3), and its two
; screen bytes are at twice that in the framebuffer.
;
;   pm_canvas       S.CANVAS: u8 slot, u8 n, n x (r, g, b): the picture in that slot is the
;                   desktop, its colours palette entries CV_FIRST on; the windows open now
;                   are hidden and the menu bar goes (until S.CANVAS_END). Again while it
;                   shows: new colours (and the slot)
;   pm_canvas_end   S.CANVAS_END: the desktop, the windows and the menu bar back
;   pm_canvas_rect  S.CANVAS_RECT: u16 x, u8 y, u16 w, u8 h, PackBits of w * h bytes (rows):
;                   those pixels changed, in the slot and on the screen (not over windows)
;   pm_canvas_pen   S.CANVAS_PEN: u8 mode, u8 colour (a palette entry), u8 size: what to
;                   draw at once while the mouse is held (CP_*)
;   cv_input        gui_desk_input: presses, moves and releases -> C.CANVAS
;   cv_off          (also when the connection goes)
;=======================================================================================

S_CANVAS        = $2d
S_CANVAS_END    = $2e
S_CANVAS_RECT   = $2f
S_CANVAS_PEN    = $31
C_CANVAS        = $94
CV_FIRST        = 16                    ; the picture's colour 0 is this palette entry
CP_NONE         = 0                     ; S.CANVAS_PEN modes: nothing at once
CP_FREE         = 1                     ; the brush along the pointer
CP_LINE         = 2                     ; a line from the press, 1 pixel, until the release
CP_BOX          = 3                     ; a box's outline from the press

cv_on:          .byte 0
cv_slot:        .byte 0
cv_n:           .byte 0
cv_hook:        .word 0                 ; gui_desk_hook from before
cv_pen:         .byte 0
cv_col:         .byte CV_FIRST
cv_size:        .byte 1
cv_px:          .word 0                 ; the pointer, in picture pixels
cv_py:          .byte 0
cv_lx:          .word 0                 ; freehand: the last point; shapes: the press
cv_ly:          .byte 0
cv_bx:          .word 0                 ; a shape's other corner, as drawn
cv_by:          .byte 0
cv_shown:       .byte 0                 ; a shape's outline is on the screen
cv_sx:          .word 0                 ; C.CANVAS: the last point sent
cv_sy:          .byte 0
; plotting
cv_x:           .word 0                 ; the pixel
cv_y:           .byte 0
cv_v:           .byte 0                 ; its value
cv_how:         .byte 0                 ; cv_dot: 0 the brush in cv_col, 1 a pixel in cv_col,
                                        ; 2 a pixel as the picture has it (an outline gone)
; lines
cv_x0:          .word 0
cv_y0:          .word 0
cv_x1:          .word 0
cv_y1:          .word 0
cv_dx:          .word 0
cv_dy:          .word 0                 ; (minus |dy|)
cv_sxs:         .byte 0                 ; x step: 1 or $ff
cv_sys:         .byte 0
cv_err:         .word 0
cv_e2:          .word 0
; S.CANVAS_RECT
cv_rx:          .word 0
cv_ry:          .byte 0
cv_rw:          .word 0
cv_rh:          .byte 0
cv_cx:          .word 0
cv_cw:          .word 0
cv_rn:          .byte 0                 ; PackBits: bytes left of this run / literal
cv_rl:          .byte 0                 ; 1 literal, 0 a run
cv_rv:          .byte 0
cv_bi:          .byte 0
cv_bj:          .byte 0

; ---- S.CANVAS / S.CANVAS_END ----

pm_canvas:
        jsr rd_u8
        sta cv_slot
        jsr rd_u8
        sta cv_n
        lda cv_on
        bne +
        lda #1
        sta cv_on
        lda gui_desk_hook
        sta cv_hook
        lda gui_desk_hook+1
        sta cv_hook+1
        lda #<far_cv_draw               ; (resident stubs: this is an overlay)
        sta gui_desk_hook
        lda #>far_cv_draw
        sta gui_desk_hook+1
        lda #<far_cv_input
        sta gui_desk_input
        lda #>far_cv_input
        sta gui_desk_input+1
        lda #0
        sta gui_menubar
        sta cv_shown
        sta cv_pen
        jsr gui_hide_all
+       ldx #CV_FIRST                   ; its colours
        ldy cv_n
        beq _done
-       phx
        phy
        jsr rd_u8
        jsr gui_swap
        ply
        plx
        sta $d100,x
        phx
        phy
        jsr rd_u8
        jsr gui_swap
        ply
        plx
        sta $d200,x
        phx
        phy
        jsr rd_u8
        jsr gui_swap
        ply
        plx
        sta $d300,x
        inx
        cpx #255
        beq _done
        dey
        bne -
_done:  jmp gui_redraw_later

pm_canvas_end:
cv_off:
        lda cv_on
        beq _out
        lda #0
        sta cv_on
        sta gui_desk_input
        sta gui_desk_input+1
        lda cv_hook
        sta gui_desk_hook
        lda cv_hook+1
        sta gui_desk_hook+1
        lda #1
        sta gui_menubar
        jsr art_palette
        jmp gui_show_all
_out:   rts

; gui_desk_hook: the whole picture as the desktop
cv_draw:
        lda cv_slot
        jsr pic_ptrs
        jmp pic_double

; ---- S.CANVAS_PEN ----

pm_canvas_pen:
        jsr rd_u8
        sta cv_pen
        jsr rd_u8
        sta cv_col
        jsr rd_u8
        bne +
        lda #1
+       cmp #17
        bcc +
        lda #16
+       sta cv_size
        rts

; ---- S.CANVAS_RECT ----

pm_canvas_rect:
        jsr rd_u16
        sta cv_rx
        stx cv_rx+1
        jsr rd_u8
        sta cv_ry
        jsr rd_u16
        sta cv_rw
        stx cv_rw+1
        jsr rd_u8
        sta cv_rh
        lda cv_on
        beq _out
        lda pr_ptr                      ; the packed bytes: the frame's length - 7 (type,
        sta tmp6                        ; x, y, w, h)
        lda pr_ptr+1
        sta tmp6+1
        sec
        lda pf_len
        sbc #7
        sta tmp5
        lda pf_len+1
        sbc #0
        sta tmp5+1
        bcc _out
        lda #0
        sta cv_rn
        jsr gui_win_rects
        lda cv_ry
        sta cv_y
_row:   lda cv_rh
        beq _out
        lda cv_rx
        sta cv_x
        lda cv_rx+1
        sta cv_x+1
        lda cv_rw
        sta cv_cw
        lda cv_rw+1
        sta cv_cw+1
_px:    lda cv_cw
        ora cv_cw+1
        beq _nrow
        jsr cv_next
        sta cv_v
        jsr cv_put
        inc cv_x
        bne +
        inc cv_x+1
+       lda cv_cw
        bne +
        dec cv_cw+1
+       dec cv_cw
        bra _px
_nrow:  inc cv_y
        dec cv_rh
        bra _row
_out:   rts

; the next unpacked byte -> A (0 once the packed bytes run out)
cv_next:
        lda cv_rn
        bne _have
_hdr:   jsr l_cv_byte
        bcs _none
        cmp #128
        beq _hdr
        bcs _run
        inc a                           ; n + 1 bytes as they are
        sta cv_rn
        lda #1
        sta cv_rl
        bra _have
_run:   eor #$ff                        ; 257 - n times the next byte
        clc
        adc #2
        sta cv_rn
        lda #0
        sta cv_rl
        jsr l_cv_byte
        sta cv_rv
_have:  dec cv_rn
        lda cv_rl
        beq +
        jsr l_cv_byte
        bcc _ret
_none:  lda #0
        sta cv_rn
_ret:   rts
+       lda cv_rv
        rts
l_cv_byte:                              ; the next packed byte (tmp6, tmp5 left): carry set
        lda tmp5                        ; when there are none
        ora tmp5+1
        bne +
        sec
        rts
+       lda tmp5
        bne +
        dec tmp5+1
+       dec tmp5
        ldy #0
        lda (tmp6),y
        inw tmp6
        clc
        rts

; ---- plotting: cv_x / cv_y, value cv_v ----

; ptr0 = pixel (cv_x, cv_y) in the slot, ptr2 = its first byte on the screen. Carry set if
; it's off the picture
l_cv_addr:
        lda cv_x+1                      ; x < 320, y < 200
        beq +
        cmp #1
        bne _off
        lda cv_x
        cmp #320 - 256
        bcs _off
+       lda cv_y
        cmp #200
        bcs _off
        lda cv_x+1                      ; t = x >> 2 (0-79)
        lsr
        lda cv_x
        ror
        lsr
        sta tmp0
        asl                             ; low byte: (t << 5) | (y & 7) << 2 | (x & 3)
        asl
        asl
        asl
        asl
        sta ptr0
        lda cv_y
        and #7
        asl
        asl
        ora ptr0
        sta ptr0
        lda cv_x
        and #3
        ora ptr0
        sta ptr0
        lda cv_y                        ; high byte: (t >> 3) + (y >> 3) * 10
        lsr
        lsr
        lsr
        sta tmp1
        asl
        asl
        adc tmp1                        ; * 5
        asl                             ; * 10
        sta tmp1
        lda tmp0
        lsr
        lsr
        lsr
        clc
        adc tmp1
        sta ptr0+1
        lda ptr0                        ; the screen: F640_BUF0 + 2 * offset
        asl
        sta ptr2
        lda ptr0+1
        rol
        sta ptr2+1
        lda #0
        rol
        clc
        adc #`F640_BUF0
        sta ptr2+2
        lda #F640_BUF0 >> 24
        sta ptr2+3
        clc
        lda cv_slot
        and #GUI_RES_SLOTS - 1
        adc #`GUI_RES_MEM
        sta ptr0+2
        lda #GUI_RES_MEM >> 24
        sta ptr0+3
        clc
        rts
_off:   sec
        rts

; cv_v into the picture and onto the screen (where no window covers it)
cv_put:
        jsr l_cv_addr
        bcs _out
        ldz #0
        lda cv_v
        sta [ptr0],z
        jmp l_cv_screen
_out:   rts

; cv_v onto the screen only (ptr2 set by l_cv_addr): both of its screen pixels, unless a
; window or the bar covers them
l_cv_screen:
        lda cv_x                        ; d6_x = 2x, d6_y = y
        asl
        sta d6_x
        lda cv_x+1
        rol
        sta d6_x+1
        lda cv_y
        sta d6_y
        lda #0
        sta d6_y+1
        jsr gui_covered
        bcs +
        ldz #0
        lda cv_v
        sta [ptr2],z
+       inc d6_x                        ; (2x is even: no carry)
        jsr gui_covered
        bcs +
        ldz #1
        lda cv_v
        sta [ptr2],z
+       ldz #0
        rts

; one dot of a stroke or an outline at (cv_x, cv_y), as cv_how says
cv_dot:
        lda cv_how
        beq _brush
        cmp #1
        beq _pix
        jsr l_cv_addr                   ; 2: as the picture has it
        bcs _out
        ldz #0
        lda [ptr0],z
        sta cv_v
        jmp l_cv_screen
_pix:   jsr l_cv_addr
        bcs _out
        lda cv_col
        sta cv_v
        jmp l_cv_screen
_out:   rts
_brush: lda cv_x                        ; a square cv_size across, from (size - 1) / 2
        pha                             ; up and left of the point (paint.py: the same)
        lda cv_x+1
        pha
        lda cv_y
        pha
        lda cv_size
        sec
        sbc #1
        lsr
        sta tmp2
        sec
        lda cv_x
        sbc tmp2
        sta cv_x
        lda cv_x+1
        sbc #0
        sta cv_x+1
        sec
        lda cv_y
        sbc tmp2
        sta cv_y                        ; (above the top wraps to 200+: off, skipped)
        lda cv_col
        sta cv_v
        lda #0
        sta cv_bj
_bj:    lda #0
        sta cv_bi
_bi:    jsr l_cv_addr
        bcs +
        jsr l_cv_screen
+       inc cv_x
        bne +
        inc cv_x+1
+       inc cv_bi
        lda cv_bi
        cmp cv_size
        bne _bi
        sec
        lda cv_x
        sbc cv_size
        sta cv_x
        lda cv_x+1
        sbc #0
        sta cv_x+1
        inc cv_y
        inc cv_bj
        lda cv_bj
        cmp cv_size
        bne _bj
        pla
        sta cv_y
        pla
        sta cv_x+1
        pla
        sta cv_x
        rts

; a line of cv_dot from (cv_x0, cv_y0) to (cv_x1, cv_y1) (Bresenham)
cv_line:
        ldx #1                          ; dx = |x1 - x0|, sx
        sec
        lda cv_x1
        sbc cv_x0
        sta cv_dx
        lda cv_x1+1
        sbc cv_x0+1
        sta cv_dx+1
        bpl +
        ldx #$ff
        sec
        lda #0
        sbc cv_dx
        sta cv_dx
        lda #0
        sbc cv_dx+1
        sta cv_dx+1
+       stx cv_sxs
        ldx #1                          ; dy = -|y1 - y0|, sy
        sec
        lda cv_y1
        sbc cv_y0
        sta cv_dy
        lda cv_y1+1
        sbc cv_y0+1
        sta cv_dy+1
        bmi +
        ldx #$ff                        ; (positive: negate it; y goes down)
        sec
        lda #0
        sbc cv_dy
        sta cv_dy
        lda #0
        sbc cv_dy+1
        sta cv_dy+1
        ldx #1
        bra ++
+       ldx #$ff
+       stx cv_sys
        clc                             ; err = dx + dy
        lda cv_dx
        adc cv_dy
        sta cv_err
        lda cv_dx+1
        adc cv_dy+1
        sta cv_err+1
_lp:    lda cv_x0
        sta cv_x
        lda cv_x0+1
        sta cv_x+1
        lda cv_y0
        sta cv_y
        jsr cv_dot
        lda cv_x0                       ; at the end?
        cmp cv_x1
        bne +
        lda cv_x0+1
        cmp cv_x1+1
        bne +
        lda cv_y0
        cmp cv_y1
        bne +
        rts
+       lda cv_err                      ; e2 = 2 * err
        asl
        sta cv_e2
        lda cv_err+1
        rol
        sta cv_e2+1
        sec                             ; e2 >= dy: err += dy, x0 += sx
        lda cv_e2
        sbc cv_dy
        lda cv_e2+1
        sbc cv_dy+1
        bvc +
        eor #$80
+       bmi _noxs
        clc
        lda cv_err
        adc cv_dy
        sta cv_err
        lda cv_err+1
        adc cv_dy+1
        sta cv_err+1
        lda cv_sxs
        bmi +
        inc cv_x0
        bne _noxs
        inc cv_x0+1
        bra _noxs
+       lda cv_x0
        bne +
        dec cv_x0+1
+       dec cv_x0
_noxs:  sec                             ; e2 <= dx: err += dx, y0 += sy
        lda cv_dx
        sbc cv_e2
        lda cv_dx+1
        sbc cv_e2+1
        bvc +
        eor #$80
+       bmi _lp
        clc
        lda cv_err
        adc cv_dx
        sta cv_err
        lda cv_err+1
        adc cv_dx+1
        sta cv_err+1
        clc                             ; (y stays 0-199: the low byte is enough)
        lda cv_y0
        adc cv_sys
        sta cv_y0
        jmp _lp

; the press -> (cv_lx, cv_ly) and the other corner (cv_bx, cv_by) as a line or a box's
; outline, with cv_dot as cv_how says
cv_shape:
        lda cv_pen
        cmp #CP_BOX
        beq _box
        lda cv_lx                       ; a line
        ldx cv_lx+1
        ldy cv_ly
        jsr l_cv_from
        lda cv_bx
        ldx cv_bx+1
        ldy cv_by
        jsr l_cv_to
        jmp cv_line
_box:   lda cv_lx                       ; four sides: top, bottom, left, right
        ldx cv_lx+1
        ldy cv_ly
        jsr l_cv_from
        lda cv_bx
        ldx cv_bx+1
        ldy cv_ly
        jsr l_cv_to
        jsr cv_line
        lda cv_lx
        ldx cv_lx+1
        ldy cv_by
        jsr l_cv_from
        lda cv_bx
        ldx cv_bx+1
        ldy cv_by
        jsr l_cv_to
        jsr cv_line
        lda cv_lx
        ldx cv_lx+1
        ldy cv_ly
        jsr l_cv_from
        lda cv_lx
        ldx cv_lx+1
        ldy cv_by
        jsr l_cv_to
        jsr cv_line
        lda cv_bx
        ldx cv_bx+1
        ldy cv_ly
        jsr l_cv_from
        lda cv_bx
        ldx cv_bx+1
        ldy cv_by
        jsr l_cv_to
        jmp cv_line
l_cv_from:
        sta cv_x0
        stx cv_x0+1
        sty cv_y0
        lda #0
        sta cv_y0+1
        rts
l_cv_to:
        sta cv_x1
        stx cv_x1+1
        sty cv_y1
        lda #0
        sta cv_y1+1
        rts

; ---- the mouse on the picture (gui_desk_input: A = GUI_DK_*) ----

cv_input:
        pha
        lda ev_x+1                      ; the pointer in picture pixels
        lsr
        sta cv_px+1
        lda ev_x
        ror
        sta cv_px
        lda ev_y
        cmp #200
        bcc +
        lda #199
+       sta cv_py
        jsr gui_win_rects
        pla
        cmp #GUI_DK_DOWN
        beq _down
        cmp #GUI_DK_MOVE
        beq _move
        cmp #GUI_DK_UP
        beq _up
        lda #4                          ; a right click
        jsr l_cv_send
        clc
        rts
_down:  lda #1
        jsr l_cv_send
        jsr l_cv_here                   ; the press: the last point, the anchor
        lda cv_pen
        cmp #CP_FREE
        bne +
        lda #0
        sta cv_how
        lda cv_px
        sta cv_x
        lda cv_px+1
        sta cv_x+1
        lda cv_py
        sta cv_y
        jsr cv_dot
        clc
        rts
+       cmp #CP_LINE
        bcc _ok
        jsr l_cv_corner
        lda #1                          ; the outline, in the colour
        sta cv_how
        jsr cv_shape
        lda #1
        sta cv_shown
_ok:    clc
        rts
_move:  lda cv_px                       ; (still the same picture pixel: nothing)
        cmp cv_sx
        bne +
        lda cv_px+1
        cmp cv_sx+1
        bne +
        lda cv_py
        cmp cv_sy
        beq _ok
+       lda #2
        jsr l_cv_send
        lda cv_pen
        cmp #CP_FREE
        bne +
        lda #0                          ; the brush from the last point to here
        sta cv_how
        lda cv_lx
        ldx cv_lx+1
        ldy cv_ly
        jsr l_cv_from
        lda cv_px
        ldx cv_px+1
        ldy cv_py
        jsr l_cv_to
        jsr cv_line
        jsr l_cv_here
        clc
        rts
+       cmp #CP_LINE
        bcc _ok
        lda cv_shown                    ; the old outline goes, the new one comes
        beq +
        lda #2
        sta cv_how
        jsr cv_shape
+       jsr l_cv_corner
        lda #1
        sta cv_how
        jsr cv_shape
        lda #1
        sta cv_shown
        clc
        rts
_up:    lda #3
        jsr l_cv_send
        lda cv_shown                    ; (the server draws the real one)
        beq _ok
        lda #2
        sta cv_how
        jsr cv_shape
        lda #0
        sta cv_shown
        clc
        rts

l_cv_here:
        lda cv_px
        sta cv_lx
        lda cv_px+1
        sta cv_lx+1
        lda cv_py
        sta cv_ly
        rts
l_cv_corner:
        lda cv_px
        sta cv_bx
        lda cv_px+1
        sta cv_bx+1
        lda cv_py
        sta cv_by
        rts

; C.CANVAS: u8 event (A), u16 x, u8 y
l_cv_send:
        pha
        lda #C_CANVAS
        jsr tx_begin
        pla
        jsr tx_u8
        lda cv_px
        sta cv_sx
        ldx cv_px+1
        stx cv_sx+1
        jsr tx_u16
        lda cv_py
        sta cv_sy
        jsr tx_u8
        jmp tx_end
