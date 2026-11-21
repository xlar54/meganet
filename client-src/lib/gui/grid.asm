;=======================================================================================
; lib/gui/grid.asm - GK_GRID: a board of picture tiles (board games), and the resource slots
; its tiles live in. Part of the GUI (include it after gui.asm).
;
; The gadget's text is 7 bytes, each value + 1: cols, rows, tile w, tile h, resource slot,
; mark colour 1, mark colour 2. Its cells (one byte each, at most 256, all 0 at first) are
; kept in attic at GUI_GRID_MEM + gadget slot * 256: bits 0-5 the tile, bit 6 a frame in mark
; colour 2, bit 7 one in mark colour 1. Tile t is at GUI_RES_MEM + slot * $10000 + t * w * h,
; row by row, a palette index a pixel (any x: it's drawn a pixel at a time).
;
;   gui_resource    ptr0 = where in the slot (gui_res_slot, gui_res_off), tmp6 = the bytes
;                   (chip RAM), tmp5 = how many: copied in
;   gui_resource_packed   the same, but tmp6 / tmp5 are PackBits bytes, unpacked in
;   gui_grid_cells  A = window, X = gadget id, gp_x = first cell, gp_w = how many, tmp6 =
;                   the values: set, and the grid drawn again at the next frame
;   A click on a cell gives GE_SELECT with ge_val = the cell (row * cols + col).
;=======================================================================================

GUI_GRID_MEM    = $8250000              ; cells: 256 a gadget slot (GUI_MAXGAD x 256)
GUI_RES_MEM     = $8400000              ; resource slots: 16 x 64 KB
GUI_RES_SLOTS   = 16
        .cerror GUI_MAXGAD > 256, "the grids' cells run past their 64 KB"

gui_res_slot:   .byte 0
gui_res_off:    .word 0

; gui_resource: tmp5 bytes from tmp6 to slot gui_res_slot at gui_res_off
gui_resource:
        lda gui_res_slot
        cmp #GUI_RES_SLOTS
        bcs _out
        jsr l_gr_dest
        ldy #0
        ldz #0
_lp:    lda tmp5
        ora tmp5+1
        beq _done
        lda (tmp6),y
        sta [ptr0],z
        inw tmp6
        inw ptr0                        ; (past the slot's end: wraps inside it)
        lda tmp5
        bne +
        dec tmp5+1
+       dec tmp5
        bra _lp
_done:  ldz #0
_out:   rts

; gui_resource_packed: tmp5 bytes of PackBits (ByteRun1) from tmp6, unpacked into slot
; gui_res_slot from gui_res_off on (wrapping inside the slot): n < 128 = the next n + 1
; bytes as they are, n > 128 = the next byte 257 - n times, 128 = nothing
gui_resource_packed:
        lda gui_res_slot
        cmp #GUI_RES_SLOTS
        bcs _out
        jsr l_gr_dest
        ldz #0
_cmd:   jsr l_gr_next
        bcs _done
        cmp #128
        beq _cmd
        bcs _run
        inc a                           ; n + 1 bytes as they are (1-128)
        sta l_gr_pn
_lit:   jsr l_gr_next
        bcs _done
        sta [ptr0],z
        inw ptr0
        dec l_gr_pn
        bne _lit
        bra _cmd
_run:   eor #$ff                        ; 257 - n = (255 - n) + 2: 2-128 times
        clc
        adc #2
        sta l_gr_pn
        jsr l_gr_next
        bcs _done
-       sta [ptr0],z
        inw ptr0
        dec l_gr_pn
        bne -
        bra _cmd
_done:  ldz #0
_out:   rts
l_gr_pn:        .byte 0

; the next packed byte -> A (from tmp6, tmp5 left), carry set when there are none
l_gr_next:
        lda tmp5
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

; ptr0 = slot gui_res_slot at offset gui_res_off
l_gr_dest:
        lda gui_res_off
        sta ptr0
        lda gui_res_off+1
        sta ptr0+1
        clc
        lda gui_res_slot
        adc #`GUI_RES_MEM
        sta ptr0+2
        lda #GUI_RES_MEM >> 24
        sta ptr0+3
        rts

; ptr2 = gadget slot X's cells (X kept)
l_gr_cells:
        lda #0
        sta ptr2
        txa
        clc
        adc #>GUI_GRID_MEM
        sta ptr2+1
        lda #`GUI_GRID_MEM
        sta ptr2+2
        lda #GUI_GRID_MEM >> 24
        sta ptr2+3
        rts

; a new grid gadget X: its cells all 0 (X kept)
l_gr_clear:
        jsr l_gr_cells
        lda #0
        ldz #0
-       sta [ptr2],z
        inz
        bne -
        rts

; gui_grid_cells: A = window id, X = gadget id; gp_x first, gp_w how many, tmp6 the values
gui_grid_cells:
        jsr l_gg_find
        bcs _out
        lda gg_kind,x
        cmp #GK_GRID
        bne _out
        jsr l_gr_cells
        ldy #0
        ldz gp_x
-       cpy gp_w
        beq _done
        lda (tmp6),y
        sta [ptr2],z
        iny
        inz
        bne -                           ; (256 cells at most)
_done:  ldz #0
        jmp l_gg_later
_out:   rts

; the 7 parameter bytes of gadget X -> l_gr_cols ... (each - 1); X kept
l_gr_params:
        lda l_gtb_lo,x
        sta tmp6
        lda l_gtb_hi,x
        sta tmp6+1
        ldy #6
-       lda (tmp6),y
        sec
        sbc #1
        sta l_gr_cols,y
        dey
        bpl -
        rts
l_gr_cols:      .byte 0
l_gr_rows:      .byte 0
l_gr_tw:        .byte 0
l_gr_th:        .byte 0
l_gr_slot:      .byte 0
l_gr_m1:        .byte 0
l_gr_m2:        .byte 0

; draw grid gadget X: gr = its rectangle (l_gui_draw_gad0 has set it)
l_gd_grid:
        stx l_gr_g
        jsr l_gr_params
        lda l_gr_tw                     ; a tile's bytes: w * h
        sta $d770
        lda #0
        sta $d771
        sta $d772
        sta $d773
        sta $d775
        sta $d776
        sta $d777
        lda l_gr_th
        sta $d774
        lda $d778
        sta l_gr_ts
        lda $d779
        sta l_gr_ts+1
        lda gr_y0
        sta l_gr_cy
        lda #0
        sta l_gr_r
        sta l_gr_n
_row:   lda gr_x0
        sta l_gr_cx
        lda gr_x0+1
        sta l_gr_cx+1
        lda #0
        sta l_gr_c
_cell:  ldx l_gr_g
        jsr l_gr_cells
        ldz l_gr_n
        lda [ptr2],z
        ldz #0
        sta l_gr_v
        jsr l_gr_tile
        lda l_gr_v                      ; the frames: mark 2, then mark 1 over it
        and #$40
        beq +
        lda l_gr_m2
        jsr l_gr_frame
+       lda l_gr_v
        bpl +
        lda l_gr_m1
        jsr l_gr_frame
+       inc l_gr_n
        clc
        lda l_gr_cx
        adc l_gr_tw
        sta l_gr_cx
        bcc +
        inc l_gr_cx+1
+       inc l_gr_c
        lda l_gr_c
        cmp l_gr_cols
        bne _cell
        clc
        lda l_gr_cy
        adc l_gr_th
        bcs _done                       ; (off the bottom)
        sta l_gr_cy
        inc l_gr_r
        lda l_gr_r
        cmp l_gr_rows
        bne _row
_done:  ldx l_gr_g
        rts

; the tile l_gr_v & 63 at (l_gr_cx, l_gr_cy), clipped to the screen
l_gr_tile:
        lda l_gr_cx+1                   ; n = the pixels a row on screen: min(tw, 640 - x)
        cmp #>640
        bcc +
        bne _none
        lda l_gr_cx
        cmp #<640
        bcs _none
+       sec
        lda #<640
        sbc l_gr_cx
        sta l_gr_w
        lda #>640
        sbc l_gr_cx+1
        bne +                           ; (256 or more left: all of it)
        lda l_gr_w
        cmp l_gr_tw
        bcc ++
+       lda l_gr_tw
+       sta l_gr_w
        lda l_gr_v                      ; ptr0 = the tile: RES + slot * 64 KB + t * size
        and #$3f
        sta $d770
        lda #0
        sta $d771
        sta $d772
        sta $d773
        sta $d776
        sta $d777
        lda l_gr_ts
        sta $d774
        lda l_gr_ts+1
        sta $d775
        lda $d778
        sta ptr0
        lda $d779
        sta ptr0+1
        clc
        lda $d77a
        adc l_gr_slot
        adc #`GUI_RES_MEM
        sta ptr0+2
        lda #GUI_RES_MEM >> 24
        sta ptr0+3
        lda #0
        sta l_gr_y
_ln:    clc                             ; this row's y on screen
        lda l_gr_cy
        adc l_gr_y
        bcs _none
        cmp #200
        bcs _none
        sta d6_y
        lda #0
        sta d6_y+1
        lda l_gr_cx
        sta d6_x
        and #7
        sta l_gr_b                      ; x & 7: where in the cell's 8 pixels
        lda l_gr_cx+1
        sta d6_x+1
        jsr d6_addr
        ldy #0
_px:    tya
        taz
        lda [ptr0],z
        ldz #0
        sta [d6_p],z
        inc l_gr_b
        lda l_gr_b
        cmp #8
        beq _next
        inw d6_p                        ; the next pixel in the cell
        bne _nx
        inc d6_p+2
        bra _nx
_next:  lda #0                          ; the next cell: 64 on, back 7
        sta l_gr_b
        clc
        lda d6_p
        adc #57
        sta d6_p
        bcc _nx
        inw d6_p+1
_nx:    iny
        cpy l_gr_w
        bne _px
        clc                             ; the tile's next row
        lda ptr0
        adc l_gr_tw
        sta ptr0
        bcc +
        inw ptr0+1
+       inc l_gr_y
        lda l_gr_y
        cmp l_gr_th
        bne _ln
_none:  ldz #0
        rts

; a frame round the cell at (l_gr_cx, l_gr_cy) in colour A: two pixels wide at the sides
; (pixels are twice as tall as wide), one at the top and bottom
l_gr_frame:
        sta d6_col
        lda #0
        sta l_gr_k
_fr:    clc
        lda l_gr_cx
        adc l_gr_k
        sta d6_x
        lda l_gr_cx+1
        adc #0
        sta d6_x+1
        lda l_gr_cy
        sta d6_y
        lda #0
        sta d6_y+1
        sta d6_y1+1
        clc                             ; x1 = x + tw - 1 - k
        lda l_gr_cx
        adc l_gr_tw
        sta d6_x1
        lda l_gr_cx+1
        adc #0
        sta d6_x1+1
        lda l_gr_k
        clc
        adc #1
        sta l_gr_t
        sec
        lda d6_x1
        sbc l_gr_t
        sta d6_x1
        lda d6_x1+1
        sbc #0
        sta d6_x1+1
        clc
        lda l_gr_cy
        adc l_gr_th
        sec
        sbc #1
        sta d6_y1
        jsr d6_frame
        inc l_gr_k
        lda l_gr_k
        cmp #2
        bne _fr
        rts

; a press on grid X (gr = its rectangle): GE_SELECT with the cell. Carry set = an event
l_gu_grid:
        stx l_gr_g
        jsr l_gr_params
        lda l_gr_tw                     ; (nonsense sizes: no cells)
        beq _no
        lda l_gr_th
        beq _no
        sec                             ; col = (x - x0) / tw
        lda ev_x
        sbc gr_x0
        sta l_gr_t
        lda ev_x+1
        sbc gr_x0+1
        sta l_gr_t+1
        ldx #0
-       lda l_gr_t+1
        bne +
        lda l_gr_t
        cmp l_gr_tw
        bcc ++
+       sec
        lda l_gr_t
        sbc l_gr_tw
        sta l_gr_t
        lda l_gr_t+1
        sbc #0
        sta l_gr_t+1
        inx
        bra -
+       cpx l_gr_cols
        bcs _no
        stx l_gr_c
        sec                             ; row = (y - y0) / th
        lda ev_y
        sbc gr_y0
        ldx #0
-       cmp l_gr_th
        bcc +
        sbc l_gr_th
        inx
        bra -
+       cpx l_gr_rows
        bcs _no
        txa                             ; cell = row * cols + col
        sta $d770
        lda #0
        sta $d771
        sta $d772
        sta $d773
        sta $d775
        sta $d776
        sta $d777
        lda l_gr_cols
        sta $d774
        clc
        lda $d778
        adc l_gr_c
        sta ge_val
        lda $d779
        adc #0
        sta ge_val+1
        ldx l_gr_g
        lda gg_id,x
        sta ge_gid
        ldy gg_win,x
        lda gw_id,y
        sta ge_win
        lda #GE_SELECT
        sta ge_type
        sec
        rts
_no:    ldx l_gr_g
        clc
        rts

l_gr_g:         .byte 0
l_gr_ts:        .word 0                 ; a tile's bytes
l_gr_cx:        .word 0                 ; the cell being drawn
l_gr_cy:        .byte 0
l_gr_r:         .byte 0
l_gr_c:         .byte 0
l_gr_n:         .byte 0                 ; its number
l_gr_v:         .byte 0                 ; its value
l_gr_w:         .byte 0                 ; pixels a row on screen
l_gr_y:         .byte 0
l_gr_b:         .byte 0
l_gr_k:         .byte 0
l_gr_t:         .word 0
