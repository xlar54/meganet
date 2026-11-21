;=======================================================================================
; sprites.asm - the server's sprites (Caps.SPRITES): two hardware sprites the server can
; make from any picture it has sent (a resource slot), put over a window, glide across the
; screen and take away. One's cards fly with them; anything that should move over the GUI
; (a piece being dragged, a marker) can. Built with lib/hwsprite.asm hws_from_bitmap.
;
;   pm_sprite       S.SPRITE: u8 n (0-1), u8 win, u8 slot, u16 offset, u8 w (1-16), u8 h
;                   (1-64), u16 stride, u8 step, u16 x, u8 y, u8 c, c x (u8 colour, r, g, b):
;                   sprite n becomes the picture at `offset` in resource slot `slot` (w
;                   pixels across, `step` bytes apart; h rows, `stride` bytes apart), with
;                   the c palette colours listed as its colours (their RGB into the sprites'
;                   palette bank) and everything else see-through, shown at (x, y) in window
;                   win's client area (wherever the window is now). Not shown if win isn't
;                   open or is minimized.
;   pm_sprite_move  S.SPRITE_MOVE: u8 n, s16 dx, s16 dy, u8 frames, u8 hide: it moves (dx, dy)
;                   a frame (8.8 fixed point, screen pixels) for `frames` frames, then goes if
;                   `hide` is 1. Another move replaces it.
;   pm_sprite_off   S.SPRITE_OFF: u8 n ($ff: both): gone
;   sprites_frame   once a frame, from the main loop
;   sprites_off     both gone (the connection went)
;
; Server sprite n is hardware sprite SP_HW + n (below the pointer, 0-1, and the window drag
; corners, 2-5). The sprites take their colours from palette bank SP_BANK, set up at the
; first S.SPRITE with the GUI's 16 colours (the pointer's) as well. The two share the
; tall-sprite height: the taller one's (the other's extra rows are see-through).
;=======================================================================================

S_SPRITE        = $32
S_SPRITE_MOVE   = $33
S_SPRITE_OFF    = $34
SP_COUNT        = 2
SP_HW           = 6
SP_BANK         = 1
SP_DATA         = $14000                ; bank 1: 512 bytes a sprite (64 rows of 8)
SP_MAP          = $14400                ; the colour table hws_from_bitmap reads (256)

sp_ready:       .byte 0                 ; the sprites' palette bank is set up
sp_on:          .fill SP_COUNT
sp_h:           .fill SP_COUNT
sp_xf:          .fill SP_COUNT          ; screen x: fraction, low, high
sp_xl:          .fill SP_COUNT
sp_xh:          .fill SP_COUNT
sp_yf:          .fill SP_COUNT          ; screen y: fraction, line
sp_y:           .fill SP_COUNT
sp_dxl:         .fill SP_COUNT          ; a frame's move (8.8)
sp_dxh:         .fill SP_COUNT
sp_dyl:         .fill SP_COUNT
sp_dyh:         .fill SP_COUNT
sp_left:        .fill SP_COUNT          ; frames of moving to go
sp_hide:        .fill SP_COUNT          ; 1: gone when they end
sp_n:           .byte 0
sp_c:           .byte 0

pm_sprite:
        jsr rd_u8
        and #SP_COUNT - 1
        sta sp_n
        jsr sprite_off                  ; (X = n after)
        jsr rd_u8                       ; the window: where its client area is now
        jsr gui_find_win
        bcs _out
        lda gw_min,x
        bne _out
        ldy sp_n
        clc
        lda gw_xl,x
        adc #GUI_CLIENT_X
        sta sp_xl,y
        lda gw_xh,x
        adc #0
        sta sp_xh,y
        clc
        lda gw_y,x
        adc #GUI_CLIENT_Y
        sta sp_y,y
        jsr rd_u8                       ; the picture: in resource slot..., at offset...
        and #GUI_RES_SLOTS - 1
        clc
        adc #`GUI_RES_MEM
        sta ptr0+2
        lda #GUI_RES_MEM >> 24
        sta ptr0+3
        jsr rd_u16
        sta ptr0
        stx ptr0+1
        jsr rd_u8                       ; w pixels, h rows: within a sprite
        beq _out
        cmp #17
        bcs _out
        sta hws_bm_w
        jsr rd_u8
        beq _out
        cmp #HWS_BM_ROWS + 1
        bcs _out
        sta hws_bm_h
        ldy sp_n
        sta sp_h,y
        jsr rd_u16
        sta hws_bm_stride
        stx hws_bm_stride+1
        jsr rd_u8
        sta hws_bm_step
        jsr rd_u16                      ; x, y in the client area
        ldy sp_n
        clc
        adc sp_xl,y
        sta sp_xl,y
        txa
        adc sp_xh,y
        sta sp_xh,y
        jsr rd_u8
        ldy sp_n
        clc
        adc sp_y,y
        sta sp_y,y
        lda #$80                        ; (a half: a move's steps add up to the nearest)
        sta sp_xf,y
        sta sp_yf,y
        jsr l_sp_colours
        lda sp_n                        ; the data: SP_DATA + n * 512
        asl
        clc
        adc #>SP_DATA
        sta ptr1+1
        lda #<SP_DATA
        sta ptr1
        lda #`SP_DATA
        sta ptr1+2
        lda #0
        sta ptr1+3
        jsr l_sp_map_ptr
        jsr hws_from_bitmap
        lda sp_n
        clc
        adc #SP_HW
        tax
        lda sp_n
        asl
        clc
        adc #>SP_DATA
        tay
        lda #<SP_DATA
        ldz #`SP_DATA
        jsr hws_shape_far
        ldz #0
        lda sp_n
        clc
        adc #SP_HW
        tax
        jsr hws_full_colour
        ldx sp_n
        lda #1
        sta sp_on,x
        jsr l_sp_height
        ldx sp_n
        jsr l_sp_place
        lda sp_n
        clc
        adc #SP_HW
        tax
        jmp hws_on
_out:   rts

; the colour list -> SP_MAP (index -> 1..c, the rest 0) and their RGB into the bank
l_sp_colours:
        lda sp_ready                    ; the bank, once: the GUI's colours (the pointer's)
        bne +
        inc sp_ready
        lda #SP_BANK
        jsr hws_pal_edit
        jsr gui_palette
        lda #SP_BANK
        jsr hws_pal_bank
+       jsr l_sp_map_ptr
        lda #0
        tay
        taz
-       sta [ptr2],z
        inz
        bne -
        lda #SP_BANK
        jsr hws_pal_edit
        jsr rd_u8
        cmp #16
        bcc +
        lda #15
+       sta sp_c
        ldx #0
_one:   cpx sp_c
        beq _done
        phx
        jsr rd_u8                       ; its palette index: colour x + 1
        taz
        plx
        inx
        txa
        sta [ptr2],z
        lda sp_n                        ; entry (SP_HW + n) * 16 + x + 1
        clc
        adc #SP_HW
        asl
        asl
        asl
        asl
        sta tmp0
        txa
        clc
        adc tmp0
        tay
        phx
        phy
        jsr rd_u8
        jsr gui_swap
        ply
        sta $d100,y
        phy
        jsr rd_u8
        jsr gui_swap
        ply
        sta $d200,y
        phy
        jsr rd_u8
        jsr gui_swap
        ply
        sta $d300,y
        plx
        bra _one
_done:  ldz #0
        lda hws_screen_bank
        jmp hws_pal_edit

l_sp_map_ptr:
        lda #<SP_MAP
        sta ptr2
        lda #>SP_MAP
        sta ptr2+1
        lda #`SP_MAP
        sta ptr2+2
        lda #0
        sta ptr2+3
        rts

; the tall-sprite height: the tallest shown one's
l_sp_height:
        lda #0
        ldx #SP_COUNT - 1
-       ldy sp_on,x
        beq +
        cmp sp_h,x
        bcs +
        lda sp_h,x
+       dex
        bpl -
        cmp #0
        beq +
        pha
        ldx #SP_HW
        jsr hws_height
        pla
        ldx #SP_HW + 1
        jmp hws_height
+       rts

; X = n: the sprite where sp_x*, sp_y say (sprites are placed in 320-wide units)
l_sp_place:
        lda sp_xh,x
        lsr
        sta hws_x+1
        lda sp_xl,x
        ror
        sta hws_x
        lda sp_y,x
        sta hws_y
        lda #0
        sta hws_y+1
        txa
        clc
        adc #SP_HW
        tax
        jmp hws_place

pm_sprite_move:
        jsr rd_u8
        and #SP_COUNT - 1
        sta sp_n
        jsr rd_u16
        ldy sp_n
        sta sp_dxl,y
        txa
        sta sp_dxh,y
        jsr rd_u16
        ldy sp_n
        sta sp_dyl,y
        txa
        sta sp_dyh,y
        jsr rd_u8
        ldy sp_n
        sta sp_left,y
        jsr rd_u8
        ldy sp_n
        sta sp_hide,y
        rts

pm_sprite_off:
        jsr rd_u8
        cmp #$ff
        beq sprites_off
        and #SP_COUNT - 1
        sta sp_n
; sprite sp_n gone (X = sp_n after)
sprite_off:
        ldx sp_n
        lda #0
        sta sp_on,x
        sta sp_left,x
        txa
        clc
        adc #SP_HW
        tax
        jsr hws_off
        ldx sp_n
        rts

sprites_off:
        lda #SP_COUNT - 1
        sta sp_n
-       jsr sprite_off
        dec sp_n
        bpl -
        rts

sprites_frame:
        ldx #SP_COUNT - 1
_one:   lda sp_on,x
        beq _next
        lda sp_left,x
        beq _next
        dec sp_left,x
        clc
        lda sp_xf,x
        adc sp_dxl,x
        sta sp_xf,x
        lda sp_xl,x
        adc sp_dxh,x
        sta sp_xl,x
        lda sp_dxh,x                    ; (the sign into the high byte)
        and #$80
        beq +
        lda #$ff
+       adc sp_xh,x
        sta sp_xh,x
        clc
        lda sp_yf,x
        adc sp_dyl,x
        sta sp_yf,x
        lda sp_y,x
        adc sp_dyh,x
        sta sp_y,x
        phx
        lda sp_left,x                   ; the last step: gone, if asked
        bne +
        lda sp_hide,x
        beq +
        stx sp_n
        jsr sprite_off
        bra ++
+       jsr l_sp_place
+       plx
_next:  dex
        bpl _one
        rts
