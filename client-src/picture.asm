;=======================================================================================
; picture.asm - S.PICTURE: a picture over the whole screen (the Art Gallery). The server
; has put its pixels in resource slots (lib/gui/grid.asm) already, in the framebuffer's
; own order (server-src/meganet/gallery/picture.py):
;   hires (640x200): 128,000 bytes from the slot on (two slots): copied straight in
;   lores (320x200): 64,000 bytes, each shown twice across
;
;   pm_picture      S.PICTURE: u8 slot, u8 mode, u8 border, u8 n, n x (r, g, b): the
;                   picture shows, with its colours in palette entries 0..n-1 and the
;                   screen's border in colour `border`; the desktop is held
;                   (gui_hold) and the pointer hidden. Another one while it shows replaces it
;   pm_picture_end  S.PICTURE_END: back to the desktop
;   pic_frame       from the main loop instead of gui_update while pic_on: keys and clicks
;                   go to the server as C.PIC_KEY
;   pic_off         back to the desktop: its palette, the pointer, everything drawn again
;                   (also when the connection goes)
;
; Overlay OVL_ART with canvas.asm (overlays.asm: the resident part calls in through #FAR
; stubs, and keeps pic_on). S.RESOURCE_PACKED, which the games' tiles use too, is resident
; (proto.asm).
;=======================================================================================

S_PICTURE       = $2a
S_PICTURE_END   = $2b
C_PIC_KEY       = $93
PIC_HIRES       = 1
PIC_CLICK       = 1                     ; C.PIC_KEY for a left click (a right one: Esc)
PIC_ESC         = 27

                                        ; (pic_on: resident, overlays.asm)
pic_slot:       .byte 0
pic_mode:       .byte 0
pic_n:          .byte 0
pic_border:     .byte 0
pic_bg:         .byte 0, 0              ; $D020 / $D021 from before
pic_cnt:        .word 0

pm_picture:
        jsr rd_u8
        sta pic_slot
        jsr rd_u8
        sta pic_mode
        jsr rd_u8
        sta pic_border
        jsr rd_u8
        sta pic_n
        lda pic_on
        bne +
        lda #1                          ; the desktop goes behind it
        sta pic_on
        sta gui_hold
        lda $d020
        sta pic_bg
        lda $d021
        sta pic_bg+1
        ldx #GUI_PTR_SPR
        jsr hws_off
        ldx #GUI_PTR_SPR + 1
        jsr hws_off
+       lda pic_border                  ; the border in the picture's colour round it
        sta $d020
        lda #0                          ; (FCM pixels of 0 show $D021: entry 0 it must be)
        sta $d021
        tax                             ; black while it's drawn
-       sta $d100,x
        sta $d200,x
        sta $d300,x
        inx
        bne -
        jsr pic_draw
        ldx #0                          ; then its colours
-       cpx pic_n
        beq _out
        phx
        jsr rd_u8
        jsr gui_swap
        plx
        sta $d100,x
        phx
        jsr rd_u8
        jsr gui_swap
        plx
        sta $d200,x
        phx
        jsr rd_u8
        jsr gui_swap
        plx
        sta $d300,x
        inx
        bne -
_out:   rts

; the pixels from the slot into the framebuffer
pic_draw:
        lda pic_slot
        jsr pic_ptrs
        lda pic_mode
        cmp #PIC_HIRES
        beq +
        jmp pic_double
+
        lda #<64000                     ; hires: 2 x 64,000 bytes as they are
        sta tmp5
        lda #>64000
        sta tmp5+1
        jsr dma_copy_far
        lda #<64000
        sta ptr1
        sta ptr2
        lda #>64000
        sta ptr1+1
        sta ptr2+1
        lda #<64000
        sta tmp5
        lda #>64000
        sta tmp5+1
        jmp dma_copy_far

; A = a resource slot: ptr1 = its start, ptr2 = the framebuffer's
pic_ptrs:
        and #GUI_RES_SLOTS - 1
        clc
        adc #`GUI_RES_MEM
        sta ptr1+2
        lda #0
        sta ptr1
        sta ptr1+1
        sta ptr2
        sta ptr2+1
        lda #GUI_RES_MEM >> 24
        sta ptr1+3
        lda #`F640_BUF0
        sta ptr2+2
        lda #F640_BUF0 >> 24
        sta ptr2+3
        rts

; a lores picture (64,000 bytes from ptr1) into the framebuffer (ptr2), each byte twice
pic_double:
        lda ptr1                        ; (ptr0 = the source)
        sta ptr0
        lda ptr1+1
        sta ptr0+1
        lda ptr1+2
        sta ptr0+2
        lda ptr1+3
        sta ptr0+3
        lda #<64000
        sta pic_cnt
        lda #>64000
        sta pic_cnt+1
_lp:    ldz #0
        lda [ptr0],z
        sta [ptr2],z
        ldz #1
        sta [ptr2],z
        inw ptr0
        clc
        lda ptr2
        adc #2
        sta ptr2
        bcc +
        inw ptr2+1                      ; (bytes 1-2: carries into the bank)
+       lda pic_cnt
        bne +
        dec pic_cnt+1
+       dec pic_cnt
        lda pic_cnt
        ora pic_cnt+1
        bne _lp
        ldz #0
        rts

pm_picture_end:
pic_off:
        lda pic_on
        beq _out
        lda #0
        sta pic_on
        sta gui_hold
        lda pic_bg
        sta $d020
        lda pic_bg+1
        sta $d021
        jsr gui_palette                 ; entries 0-15, then the art's 16-254
        jsr art_palette
        ldx #GUI_PTR_SPR
        jsr hws_on
        ldx #GUI_PTR_SPR + 1
        jsr hws_on
        jmp gui_redraw_later
_out:   rts

; a key or a click while it shows: C.PIC_KEY (u8 key)
pic_frame:
        lda gui_dbg_evp                 ; an injected event (tests)?
        cmp gui_dbg_evn
        bcs _real
        asl
        asl
        tax
        inc gui_dbg_evp
        lda gui_dbg_ev,x
        cmp #EV_KEY
        bne +
        jsr key_get
        bne _send
        rts
+       cmp #EV_DOWN
        bne +
        lda #PIC_CLICK
        bra _send
+       cmp #EV_RDOWN
        bne _none
        lda #PIC_ESC
        bra _send
_real:  jsr mouse_poll
        jsr key_get
        bne _send
        lda mouse_left_click
        beq +
        lda #PIC_CLICK
        bra _send
+       lda mouse_right_click
        beq _none
        lda #PIC_ESC
_send:  pha
        lda #C_PIC_KEY
        jsr tx_begin
        pla
        jsr tx_u8
        jmp tx_end
_none:  rts
