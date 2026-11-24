;=======================================================================================
; desk.asm - the live desktop (an overlay, OVL_DESK): what the server says is happening,
; drawn on the desktop behind the windows (server-src/meganet/livedesk.py):
;
;   S.TICKER      u8 n, text: scrolls right to left along the bottom (rows TK_Y0-199) with
;                 a red NOW tag, over and over, the end joined to the start by TK_SEP (and
;                 spaces, when it's shorter than the strip). Empty: no ticker
;   S.DESK_LINE   u8 n, text: one line above it, centred: who's online. A $01 draws a
;                 green dot, and the text after the first one is in the names' colour
;   S.DESK_BADGE  u8 slot, u8 n, text: on that desktop icon, at its picture's top right: ""
;                 none, "*" a green dot, else the text (up to 3 characters) on red
;
;   pm_ticker, pm_desk_line, pm_desk_badge   the messages (overlays.asm's far_ stubs)
;   desk_draw     login.asm's desktop hook, signed on: the line, the badges, the ticker
;                 (a full redraw, so under every window)
;   desk_tick     main.asm, every 8th frame while signed on: the ticker one character on,
;                 drawn at once unless something is over its strip (a window, a toast or a
;                 broadcast, a picture, Paint): then it moves on unseen until the next redraw
;=======================================================================================

S_TICKER        = $38
S_DESK_LINE     = $39
S_DESK_BADGE    = $3a

TK_Y0           = 188                   ; the strip: rows 188-199
TK_TY           = 190                   ; its text row
TK_X            = 48                    ; the text's left edge (the NOW tag before it)
TK_COLS         = (640 - TK_X) / 8      ; characters across
DL_Y            = 176                   ; the online line's row
DK_SLOTS        = GUI_MAXICON
DK_BMAX         = 3                     ; a badge's characters

dk_tape:        .fill 256               ; S.TICKER's text
dk_tlen:        .byte 0
dk_loop:        .byte 0                 ; the text and TK_SEP: where it starts again
dk_pos:         .byte 0                 ; the strip's first character, in that loop
dk_line:        .fill 81                ; S.DESK_LINE's
dk_badge:       .fill DK_SLOTS * (DK_BMAX + 1)
dk_win:         .fill TK_COLS + 1       ; the strip's characters, now
dk_i:           .byte 0
dk_j:           .byte 0
dk_k:           .byte 0
s_tk_sep:       .text "   *   "
TK_SEPLEN       = * - s_tk_sep
s_tk_now:       .null "NOW"

;---------------------------------------------------------------------------------------
; the messages
;---------------------------------------------------------------------------------------
pm_ticker:
        lda dk_tlen                     ; (had one: is there one now?)
        sta dk_k
        ldx #0
        jsr rd_str                      ; -> str_buf, A/X; its length in rd_n
        ldx #0
-       lda str_buf,x
        sta dk_tape,x
        beq +
        inx
        bne -
+       stx dk_tlen
        txa
        beq +
        clc
        adc #TK_SEPLEN
        cmp #TK_COLS                    ; shorter than the strip: spaces after it, so it
        bcs +                           ; crosses the strip rather than showing twice
        lda #TK_COLS
+       sta dk_loop
        lda #0
        sta dk_pos
        lda dk_k                        ; it comes or goes: the whole desktop; otherwise the
        beq +                           ; next tick shows the new text
        lda dk_tlen
        bne _out
+       jmp gui_redraw_later
_out:   rts

pm_desk_line:
        ldx #0
        jsr rd_str
        ldx #0
-       lda str_buf,x
        sta dk_line,x
        beq +
        inx
        cpx #80
        bne -
        lda #0
        sta dk_line,x
+       jmp gui_redraw_later

pm_desk_badge:
        jsr rd_u8
        cmp #DK_SLOTS
        bcs _out
        asl                             ; its 4 bytes
        asl
        sta dk_k
        ldx #0
        jsr rd_str
        ldy dk_k
        ldx #0
-       lda str_buf,x
        sta dk_badge,y
        beq +
        iny
        inx
        cpx #DK_BMAX
        bne -
        lda #0
        sta dk_badge,y
+       jmp gui_redraw_later
_out:   rts

;---------------------------------------------------------------------------------------
; drawing: the whole of it (login.asm's desktop hook, signed on)
;---------------------------------------------------------------------------------------
desk_draw:
        jsr dk_draw_badges
        jsr dk_draw_line
        lda dk_tlen
        bne +
        rts
+       lda #<0                         ; the strip
        ldx #>0
        ldy #TK_Y0
        jsr dk_rect_xy0
        lda #<639
        ldx #>639
        ldy #199
        jsr dk_rect_xy1
        lda #GC_NIGHT
        jsr l_gd_fill
        lda #<0                         ; a light line along its top
        ldx #>0
        ldy #TK_Y0
        jsr dk_rect_xy0
        lda #<639
        ldx #>639
        ldy #TK_Y0
        jsr dk_rect_xy1
        lda #GC_BLUE
        jsr l_gd_fill
        lda #<2                         ; the NOW tag
        ldx #>2
        ldy #TK_Y0 + 2
        jsr dk_rect_xy0
        lda #<(TK_X - 7)
        ldx #>(TK_X - 7)
        ldy #198
        jsr dk_rect_xy1
        lda #GC_RED
        jsr l_gd_fill
        lda #<s_tk_now
        sta txt_ptr
        lda #>s_tk_now
        sta txt_ptr+1
        lda #<8
        ldx #>8
        ldy #GC_WHITE
        jsr dk_text_at
        jmp dk_text

; gr_x0 / gr_y0 = A/X, Y; gr_x1 / gr_y1 the same
dk_rect_xy0:
        sta gr_x0
        stx gr_x0+1
        sty gr_y0
        lda #0
        sta gr_y0+1
        rts
dk_rect_xy1:
        sta gr_x1
        stx gr_x1+1
        sty gr_y1
        lda #0
        sta gr_y1+1
        rts

; txt_ptr at x = A/X on the ticker's row, colour Y, no background
dk_text_at:
        sta gt_x
        stx gt_x+1
        sty gt_fg
        lda #TK_TY
        sta gt_y
        lda #$ff
        sta gt_bg
        sta gt_n
        lda #0
        sta gt_pw
        jmp gui_text

; the strip's text from dk_pos, with its background (so it doesn't flicker)
dk_text:
        lda dk_pos
        sta dk_j
        ldx #0
_ch:    stx dk_i
        ldy dk_j                        ; the loop's character j: the text, then TK_SEP
        cpy dk_tlen
        bcs +
        lda dk_tape,y
        bra _put
+       tya
        sec
        sbc dk_tlen
        tay
        lda #' '
        cpy #TK_SEPLEN
        bcs _put
        lda s_tk_sep,y
_put:   ldx dk_i
        sta dk_win,x
        inc dk_j
        lda dk_j
        cmp dk_loop
        bne +
        lda #0
        sta dk_j
+       inx
        cpx #TK_COLS
        bne _ch
        lda #0
        sta dk_win,x
        lda #<dk_win
        sta txt_ptr
        lda #>dk_win
        sta txt_ptr+1
        lda #<TK_X
        sta gt_x
        lda #>TK_X
        sta gt_x+1
        lda #TK_TY
        sta gt_y
        lda #GC_YELLOW
        sta gt_fg
        lda #GC_NIGHT                   ; (over what was there)
        sta gt_bg
        lda #$ff
        sta gt_n
        lda #0
        sta gt_pw
        jmp gui_text

; the online line, centred: "Online now:" grey, a green dot for each $01, names in cyan
dk_draw_line:
        ldx #0                          ; its length
-       lda dk_line,x
        beq +
        inx
        bra -
+       cpx #0
        bne +
        rts
+       stx dk_k                        ; x = 320 - n * 4
        lda #0
        sta gt_x+1
        txa
        asl
        rol gt_x+1
        asl
        rol gt_x+1
        sta dk_i
        sec
        lda #<320
        sbc dk_i
        sta gt_x
        lda #>320
        sbc gt_x+1
        sta gt_x+1
        lda #GC_SHADOW + 0              ; (grey: "Online now:")
        sta dk_j
        ldx #0
_ch:    stx dk_i
        lda dk_line,x
        beq _done
        cmp #1
        bne _text
        lda #GC_CYAN                    ; a dot, then the names' colour
        sta dk_j
        jsr dk_dot
        bra _next
_text:  sta dk_win                      ; one character
        lda #0
        sta dk_win+1
        lda #<dk_win
        sta txt_ptr
        lda #>dk_win
        sta txt_ptr+1
        lda dk_j
        sta gt_fg
        lda #DL_Y
        sta gt_y
        lda #$ff
        sta gt_bg
        sta gt_n
        lda #0
        sta gt_pw
        lda gt_x                        ; (gui_text may move it on: keep it)
        pha
        lda gt_x+1
        pha
        jsr gui_text
        pla
        sta gt_x+1
        pla
        sta gt_x
_next:  clc                             ; the next cell
        lda gt_x
        adc #8
        sta gt_x
        bcc +
        inc gt_x+1
+       ldx dk_i
        inx
        bra _ch
_done:  rts

; a green dot in the cell at gt_x, row DL_Y
dk_dot:
        clc
        lda gt_x
        adc #1
        sta gr_x0
        lda gt_x+1
        adc #0
        sta gr_x0+1
        clc
        lda gr_x0
        adc #4
        sta gr_x1
        lda gr_x0+1
        adc #0
        sta gr_x1+1
        lda #DL_Y + 2
        sta gr_y0
        lda #DL_Y + 5
        sta gr_y1
        lda #0
        sta gr_y0+1
        sta gr_y1+1
        lda #GC_GREEN
        jmp l_gd_fill

; each icon's badge, right of its picture's top (the icons are drawn after the hook, over
; their own pictures only)
dk_draw_badges:
        lda #0
        sta dk_k
_slot:  lda dk_k
        asl
        asl
        tay
        lda dk_badge,y
        bne +
        jmp _next
+       ldx dk_k                        ; the cell: x = its centre + 16, y = its top
        lda dk_cx_lo,x
        sta gr_x0
        lda dk_cx_hi,x
        sta gr_x0+1
        lda dk_top,x
        sta gr_y0
        lda #0
        sta gr_y0+1
        sta gr_y1+1
        lda dk_badge,y
        cmp #'*'
        bne _num
        lda dk_badge+1,y
        bne _num
        clc                             ; a dot: 6 x 5
        lda gr_x0
        adc #6
        sta gr_x1
        lda gr_x0+1
        adc #0
        sta gr_x1+1
        clc
        lda gr_y0
        adc #1
        sta gr_y0
        adc #4
        sta gr_y1
        lda #GC_GREEN
        jsr l_gd_fill
        bra _next
_num:   ldx #0                          ; its length: 8 a character + 4 across, 10 down
-       lda dk_badge,y
        beq +
        iny
        inx
        bra -
+       txa
        asl
        asl
        asl
        clc
        adc #3
        adc gr_x0
        sta gr_x1
        lda gr_x0+1
        adc #0
        sta gr_x1+1
        clc
        lda gr_y0
        adc #9
        sta gr_y1
        lda #GC_RED
        jsr l_gd_fill
        clc                             ; its text, white
        lda gr_x0
        adc #2
        sta gt_x
        lda gr_x0+1
        adc #0
        sta gt_x+1
        lda gr_y0
        clc
        adc #1
        sta gt_y
        lda #GC_WHITE
        sta gt_fg
        lda #$ff
        sta gt_bg
        sta gt_n
        lda #0
        sta gt_pw
        lda dk_k
        asl
        asl
        clc
        adc #<dk_badge
        sta txt_ptr
        lda #>dk_badge
        adc #0
        sta txt_ptr+1
        jsr gui_text
_next:  inc dk_k
        lda dk_k
        cmp #DK_SLOTS
        beq +
        jmp _slot
+       rts

; where icon k's badge goes: its cell's centre + 16 (lib/gui/gui.asm's layout), its top - 1
dk_cx           .function k
                .endf (k < GUI_ICON_LEFT ? (k / GUI_ICON_ROWS) * GUI_ICON_CELLW + GUI_ICON_CELLW / 2 : 640 - GUI_ICON_CELLW / 2 - ((k - GUI_ICON_LEFT) / GUI_ICON_ROWS) * GUI_ICON_CELLW) + GUI_ICON_W / 2 - 2
dk_cx_lo:
.for k in range(DK_SLOTS)
        .byte <dk_cx(k)
.endfor
dk_cx_hi:
.for k in range(DK_SLOTS)
        .byte >dk_cx(k)
.endfor
dk_top:
.for k in range(DK_SLOTS)
        .byte GUI_ICON_TOP + ((k < GUI_ICON_LEFT ? k : k - GUI_ICON_LEFT) % GUI_ICON_ROWS) * GUI_ICON_CELLH - 1
.endfor

;---------------------------------------------------------------------------------------
; every 8th frame, signed on (main.asm)
;---------------------------------------------------------------------------------------
desk_tick:
        lda dk_tlen
        beq _out
        inc dk_pos                      ; one character on
        lda dk_pos
        cmp dk_loop
        bcc +
        lda #0
        sta dk_pos
+       lda gui_hold                    ; drawn now? not under a picture, Paint, a toast,
        bne _out                        ; a broadcast or a window
        lda gui_desk_input+1
        bne _out
        lda gui_toast_t
        ora gui_toast_t+1
        ora gui_banner_t
        ora gui_banner_t+1
        bne _out
        lda disk_on
        bne _out
        jsr gui_win_rects
        lda #TK_Y0
        sta d6_y
        lda #0
        sta d6_y+1
        lda #4                          ; points 64 apart along its top: every window is wider
        sta d6_x
        lda #0
        sta d6_x+1
_pt:    jsr gui_covered
        bcs _out
        clc
        lda d6_x
        adc #64
        sta d6_x
        bcc +
        inc d6_x+1
+       lda d6_x+1
        cmp #>640
        bcc _pt
        lda d6_x
        cmp #<640
        bcc _pt
        jsr d6_clip_all
        jmp dk_text
_out:   rts
