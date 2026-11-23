;=======================================================================================
; proto.asm - the MegaNet protocol on the client (server-src/meganet/protocol.py is the
; reference): frames from the server -> gui calls, gui events -> frames to the server.
;
; A frame is u16 length (little-endian, type + payload), u8 type, payload. Strings are
; u8 length + ASCII. x is u16, y u8.
;
;   proto_reset     a new connection: the deframer starts afresh
;   proto_feed      A = a byte from the server
;   proto_hello     send HELLO
;   proto_login     send LOGIN (login_new; the sign-on window's name and password)
;   proto_gui_event a gui_update event in a server window: VALUE for each of its text
;                   boxes, then CLICK; WIN_CLOSED for the close box; KEY for RAWKEYS gadgets
;
; Server messages handled so far: HELLO, LOGIN_RESULT, WIN_OPEN, WIN_CLOSE, GADGET,
; SET_TEXT, SET_VALUE, FOCUS, ALERT, WIN_DONE, LIST_ROWS, APPEND, MENU, the File Library's,
; CELLS and RESOURCE (lib/gui/grid.asm), PICTURE, PICTURE_END and RESOURCE_PACKED
; (picture.asm), CANVAS, CANVAS_END, CANVAS_RECT and CANVAS_PEN (canvas.asm). UPDATE is dropped for now (see TODO.md).
;=======================================================================================

        .weak
CLIENT_BUILD    = 1                     ; (gen/version.asm sets it: client-src/VERSION)
        .endweak
PROTO_VERSION   = 1
PF_MAX          = 2048                  ; the biggest frame kept (bigger ones are skipped)

S_HELLO         = $01
S_LOGIN_RESULT  = $02
S_WIN_OPEN      = $10
S_WIN_CLOSE     = $11
S_GADGET        = $12
S_SET_TEXT      = $13
S_SET_VALUE     = $14
S_LIST_ROWS     = $15
S_APPEND        = $16
S_FOCUS         = $17
S_MENU          = $18
S_ALERT         = $19
S_WIN_DONE      = $1a
S_NOTIFY        = $1b
S_PONG          = $1c
S_SET_FLAGS     = $1d
S_TOAST         = $1e
S_DESK_ICON     = $1f
S_BROADCAST     = $23
S_SOUND         = $24
S_CELLS         = $29
S_RESOURCE      = $30
C_HELLO         = $80
C_CLICK         = $81
C_VALUE         = $82
C_DESK_OPEN     = $8c
C_SELECT        = $83
C_MENU_PICK     = $85
C_WIN_CLOSED    = $86
C_KEY           = $87
C_LOGIN         = $89
C_NOTIFY_CLICK  = $8a
C_TEXT          = $8b
C_PING          = $8f

AW              = $fe                   ; the alert window (a client window)

proto_txn:      .word 0                 ; frames sent on this connection
proto_session:  .word 0
proto_login_ok: .byte 0                 ; LOGIN_RESULT: 0 none yet, 1 ok, 2 refused
pf_state:       .byte 0
pf_len:         .word 0
pf_n:           .word 0
tx_n:           .word 0

; The frame buffers live in the RAM under the KERNAL ROM ($01 = $35 shows RAM there): they
; only matter from one frame to the next, and nothing in them has to outlive a KERNAL call
; (MEGA65_NOTES section 1 has $E000-$EFFF as data with the KERNAL kept, too).
        .virtual $e000
pf_buf:         .fill PF_MAX
str_buf:        .fill 256
str_buf2:       .fill 256
tx_buf:         .fill 256                ; (indexed by X: frames up to 255 bytes)
proto_bufs_end:
        .endv
        .cerror proto_bufs_end > $f000, "the frame buffers overflow $E000-$EFFF"

proto_reset:
        lda #0
        sta pf_state
        sta proto_txn
        sta proto_txn+1
        sta proto_login_ok
        sta st_mode                     ; (storage.asm: no transfer left from before)
        rts

;=======================================================================================
; receiving
;=======================================================================================
proto_feed:
        ldx pf_state
        bne +
        sta pf_len                      ; length, low byte
        inc pf_state
        rts
+       dex
        bne _body
        sta pf_len+1                    ; high byte
        lda #0
        sta pf_n
        sta pf_n+1
        lda pf_len
        ora pf_len+1
        beq _reset                      ; an empty frame: nonsense, skip it
        inc pf_state
        rts
_body:  ldx pf_n+1                      ; keep it if there's room
        cpx #>PF_MAX
        bcs +
        pha
        clc
        lda #<pf_buf
        adc pf_n
        sta pr_ptr
        lda #>pf_buf
        adc pf_n+1
        sta pr_ptr+1
        pla
        ldy #0
        sta (pr_ptr),y
+       inc pf_n
        bne +
        inc pf_n+1
+       lda pf_n
        cmp pf_len
        bne _out
        lda pf_n+1
        cmp pf_len+1
        bne _out
        lda #0
        sta pf_state
        .if DEBUG_NET
        jsr nl_rx                       ; (the log)
        .endif
        lda pf_len+1                    ; whole and kept: act on it
        cmp #>PF_MAX
        bcs _out
        jmp proto_dispatch
_reset: lda #0
        sta pf_state
_out:   rts

; readers: pr_ptr walks through the frame
rd_u8:
        ldy #0
        lda (pr_ptr),y
        inw pr_ptr
        rts
rd_u16:                                 ; A = low, X = high
        jsr rd_u8
        pha
        jsr rd_u8
        tax
        pla
        rts
; a string -> str_buf (X = 0) or str_buf2 (X = 1), zero-terminated; A/X = it
rd_str:
        lda #<str_buf
        sta tmp6
        lda #>str_buf
        cpx #0
        beq +
        lda #<str_buf2
        sta tmp6
        lda #>str_buf2
+       sta tmp6+1
        jsr rd_u8
        sta rd_n
        ldy #0
-       cpy rd_n
        beq +
        lda (pr_ptr),y
        sta (tmp6),y
        iny
        bra -
+       lda #0
        sta (tmp6),y
        clc                             ; past it
        lda pr_ptr
        adc rd_n
        sta pr_ptr
        bcc +
        inc pr_ptr+1
+       lda tmp6
        ldx tmp6+1
        rts
rd_n:   .byte 0

proto_dispatch:
        jsr link_rx                     ; the server is there
        lda pf_buf
        cmp #S_PONG                     ; (only that: it answers no click)
        bne +
        rts
+       lda busy_wait                   ; answering a click or menu pick: for a moment, a
        beq +                           ; minimized window it opens again is restored
        lda #25                         ; (otherwise one the server sends again unasked,
        sta answer_wait                 ; such as a refresh, stays minimized)
        lda #1
        sta gui_open_restore
+       lda #0                          ; the server answered: no longer waiting
        sta busy_wait
        lda #<pf_buf
        sta pr_ptr
        lda #>pf_buf
        sta pr_ptr+1
        jsr rd_u8
        ldx #0
-       cmp _types,x
        beq _go
        inx
        cpx #_n
        bne -
        rts                             ; not handled (yet)
_go:    txa
        asl
        tax
        jmp (_jumps,x)
_types: .byte S_HELLO, S_LOGIN_RESULT, S_WIN_OPEN, S_WIN_CLOSE, S_GADGET, S_SET_TEXT
        .byte S_SET_VALUE, S_FOCUS, S_ALERT, S_WIN_DONE, S_LIST_ROWS, S_APPEND, S_MENU
        .byte S_NOTIFY, S_SET_FLAGS, S_TOAST, S_DESK_ICON, S_BROADCAST, S_SOUND
        .byte S_LOCAL_DIR, S_SAVE_BEGIN, S_FILE_DATA, S_FILE_END, S_LOAD_FILE, S_LOCAL_CANCEL
        .byte S_CELLS, S_RESOURCE
        .byte S_PICTURE, S_PICTURE_END, S_RESOURCE_PACKED
        .byte S_CANVAS, S_CANVAS_END, S_CANVAS_RECT, S_CANVAS_PEN
        .byte S_SPRITE, S_SPRITE_MOVE, S_SPRITE_OFF
        .byte S_SID_PLAY, S_SID_STOP, S_SID_PAUSE
_n = * - _types
_jumps: .word pm_hello, pm_login, pm_win_open, pm_win_close, pm_gadget, pm_set_text
        .word pm_set_value, pm_focus, pm_alert, pm_win_done, pm_list_rows, pm_append
        .word pm_menu, pm_notify, pm_set_flags, pm_toast, pm_desk_icon, pm_broadcast
        .word pm_sound
        .word far_local_dir, far_save_begin, far_file_data, far_file_end  ; (storage.asm,
        .word far_load_file, far_local_cancel                             ; an overlay)
        .word pm_cells, pm_resource
        .word far_picture, far_picture_end, pm_resource_packed    ; (picture.asm: overlay)
        .word far_canvas, far_canvas_end, far_canvas_rect, far_canvas_pen ; (canvas.asm: too)
        .word pm_sprite, pm_sprite_move, pm_sprite_off                    ; (sprites.asm)
        .word pm_sid_play, pm_sid_stop, pm_sid_pause                      ; (sidplay.asm)
        .cerror (_jumps - _types) != _n, "a message without its handler"

; S.RESOURCE_PACKED: u8 slot, u16 offset, the rest PackBits bytes (lib/gui/grid.asm)
S_RESOURCE_PACKED = $2c
pm_resource_packed:
        jsr rd_u8
        sta gui_res_slot
        jsr rd_u16
        sta gui_res_off
        stx gui_res_off+1
        lda pr_ptr
        sta tmp6
        lda pr_ptr+1
        sta tmp6+1
        sec                             ; the bytes: the frame's length - 4
        lda pf_len
        sbc #4
        sta tmp5
        lda pf_len+1
        sbc #0
        sta tmp5+1
        bcc +
        jmp gui_resource_packed
+       rts

; u8 win, u8 gid, u8 first, u8 n, n bytes: a grid's cells (lib/gui/grid.asm)
pm_cells:
        jsr rd_u8
        pha
        jsr rd_u8
        pha
        jsr rd_u8
        sta gp_x
        jsr rd_u8
        sta gp_w
        lda pr_ptr
        sta tmp6
        lda pr_ptr+1
        sta tmp6+1
        plx
        pla
        jmp gui_grid_cells

; u8 slot, u16 offset, the rest bytes: into a resource slot (a grid's tiles)
pm_resource:
        jsr rd_u8
        sta gui_res_slot
        jsr rd_u16
        sta gui_res_off
        stx gui_res_off+1
        lda pr_ptr
        sta tmp6
        lda pr_ptr+1
        sta tmp6+1
        sec                             ; the bytes: the frame's length - 4 (type, slot,
        lda pf_len                      ; offset)
        sbc #4
        sta tmp5
        lda pf_len+1
        sbc #0
        sta tmp5+1
        bcc +
        jmp gui_resource
+       rts

; u8 slot, u8 icon, str hint (the hint isn't shown yet). The server's slot n is the GUI's
; n + 1: the GUI's slot 0, rightmost, is the connectivity icon (link.asm)
pm_notify:
        jsr rd_u8
        inc a
        beq +                           ; (255: nonsense)
        pha
        jsr rd_u8
        tax
        pla
        jmp gui_notify
+       rts

; u8 n, n x (u8 id, u8 parent, str label): the whole menu bar, replaced. Title ids
; MENU_LATE-$EF go right of the Window menu (the server's Admin menu)
MENU_LATE       = $e0
pm_menu:
        jsr gui_menu_clear
        lda #MENU_LATE
        sta gui_menu_late
        jsr exit_menu                   ; the client's own MegaNet menu comes first
        jsr rd_u8
        sta pl_n
_e:     lda pl_n
        beq _done
        jsr rd_u8
        sta gp_gid
        jsr rd_u8
        sta gp_win
        ldx #0
        jsr rd_str
        sta gp_text
        stx gp_text+1
        jsr gui_menu_add
        dec pl_n
        bra _e
_done:  jsr exit_menu_end               ; MegaNet's line and Exit: last, after the server's items
        jmp gui_redraw_later

; u8 win, u8 gid, u16 total, u16 first, u8 n, n strings
pm_list_rows:
        jsr rd_u8
        sta gp_win
        jsr rd_u8
        sta gp_gid
        jsr rd_u16
        sta gp_w
        stx gp_w+1
        jsr gui_list_total
        jsr rd_u16
        sta gp_x
        stx gp_x+1
        jsr rd_u8
        sta pl_n
_row:   lda pl_n
        beq _done
        ldx #0
        jsr rd_str
        sta txt_ptr
        stx txt_ptr+1
        jsr gui_list_row
        inc gp_x
        bne +
        inc gp_x+1
+       dec pl_n
        bra _row
_done:  lda gp_win
        ldx gp_gid
        jmp gui_gad_redraw
pl_n:   .byte 0

; u8 win, u8 gid, str line
pm_append:
        jsr rd_u8
        pha
        jsr rd_u8
        pha
        ldx #0
        jsr rd_str
        sta txt_ptr
        stx txt_ptr+1
        plx
        pla
        jmp gui_view_append

pm_hello:
        jsr rd_u8                       ; (protocol version)
        jsr rd_u16
        sta proto_session
        stx proto_session+1
        rts

pm_login:
        jsr rd_u8
        tay
        ldx #0
        phy
        jsr rd_str
        ply
        sta login_msg
        stx login_msg+1
        lda #1
        cpy #0
        bne +
        lda #2
+       sta proto_login_ok
        rts
login_msg:      .word 0

pm_win_open:
        jsr rd_u8
        sta gp_win
        jsr rd_u16
        sta gp_x
        stx gp_x+1
        jsr rd_u8
        sta gp_y
        jsr rd_u16                      ; the server gives the client area's size:
        clc                             ; the frame and title bar are ours to add
        adc #GUI_FRAME_W
        sta gp_w
        txa
        adc #0
        sta gp_w+1
        jsr rd_u8
        clc
        adc #GUI_FRAME_H
        bcc +
        lda #255
+       sta gp_h
        jsr rd_u8
        sta gp_flags
        ldx #0
        jsr rd_str
        sta gp_text
        stx gp_text+1
        jmp gui_win_open

pm_win_close:
        jsr rd_u8
        jmp gui_win_close

pm_gadget:
        jsr rd_u8
        sta gp_win
        jsr rd_u8
        sta gp_gid
        jsr rd_u8
        sta gp_kind
        jsr rd_u16
        sta gp_x
        stx gp_x+1
        jsr rd_u8
        sta gp_y
        jsr rd_u16
        sta gp_w
        stx gp_w+1
        jsr rd_u8
        sta gp_h
        jsr rd_u8
        sta gp_flags
        lda #0
        sta gp_max
        ldx #0
        jsr rd_str
        sta gp_text
        stx gp_text+1
        jmp gui_gad_add

pm_set_text:
        jsr rd_u8
        sta gp_win
        jsr rd_u8
        sta gp_gid
        ldx #0
        jsr rd_str
        sta gp_text
        stx gp_text+1
        jmp gui_set_text

pm_set_value:
        jsr rd_u8
        sta gp_win
        jsr rd_u8
        sta gp_gid
        jsr rd_u16
        sta gp_x
        stx gp_x+1
        lda gp_win
        ldx gp_gid
        jmp gui_set_value

; u8 seconds, u8 slot (the server's notify slot a click on it reports, $ff none), str text:
; a toast at the bottom right (an instant message arriving)
pm_toast:
        jsr rd_u8
        pha
        jsr rd_u8
        inc a                           ; (server slot n = the GUI's n + 1; $ff -> 0: none)
        bne +
        lda #$ff
+       pha
        ldx #0
        jsr rd_str
        sta txt_ptr
        stx txt_ptr+1
        plx
        pla
        jmp gui_toast

; u8 seconds, str text: a message to everyone, across the bottom row
pm_broadcast:
        jsr rd_u8
        pha
        ldx #0
        jsr rd_str
        sta txt_ptr
        stx txt_ptr+1
        pla
        jmp gui_banner

; u8 slot, str line 1 ("" removes it), str line 2, then the picture's 32 x 16 bytes: a
; desktop icon
pm_desk_icon:
        jsr rd_u8
        pha
        ldx #0
        jsr rd_str
        sta gui_dk_l1
        stx gui_dk_l1+1
        ldx #1
        jsr rd_str
        sta gui_dk_l2
        stx gui_dk_l2+1
        lda pr_ptr
        sta gui_dk_px
        lda pr_ptr+1
        sta gui_dk_px+1
        pla
        jmp gui_desk_icon

; u8 win, u8 gid, u8 flags: e.g. a button greyed out or back
pm_set_flags:
        jsr rd_u8
        pha
        jsr rd_u8
        pha
        jsr rd_u8
        sta gp_flags
        plx
        pla
        jmp gui_set_flags

pm_focus:
        jsr rd_u8
        pha
        jsr rd_u8
        tax
        pla
        jmp gui_focus

pm_win_done:
        jsr rd_u8
        jmp gui_win_show

; an alert: a small modal window of the client's own with the text and OK
pm_alert:
        jsr rd_u8                       ; (icon)
        ldx #0
        jsr rd_str                      ; title -> str_buf
        ldx #1
        jsr rd_str                      ; text -> str_buf2
alert_open:                             ; the text word-wrapped (rd_n = its length), centred
        ; break str_buf2 into lines of at most AL_COLS characters, at spaces
        lda #0
        sta al_n
        sta al_pos
        lda #22                         ; the width: at least 22 characters
        sta al_max
_line:  lda al_n
        cmp #AL_LINES
        bcs _laid
        lda al_pos
        cmp rd_n
        bcs _laid
        ldx al_n
        sta al_start,x
        sec                             ; what's left fits?
        lda rd_n
        sbc al_pos
        cmp #AL_COLS + 1
        bcs _long
        sta al_len,x
        lda rd_n
        sta al_pos
        bra _next
_long:  clc                             ; break at the last space within AL_COLS
        lda al_pos
        adc #AL_COLS
        tay
-       lda str_buf2,y
        cmp #' '
        beq _sp
        dey
        cpy al_pos
        bne -
        lda #AL_COLS                    ; no space: cut it
        sta al_len,x
        clc
        lda al_pos
        adc #AL_COLS
        sta al_pos
        bra _next
_sp:    tya
        sec
        sbc al_pos
        sta al_len,x
        iny                             ; (the space goes)
        sty al_pos
_next:  lda al_len,x
        cmp al_max
        bcc +
        sta al_max
+       inc al_n
        bra _line
_laid:  lda al_n
        bne +
        inc al_n                        ; (no text: one empty line)
        lda #0
        sta al_start
        sta al_len
+       lda al_max                      ; outer width = longest * 8 + 32
        sta al_w
        lda #0
        sta al_w+1
        asl al_w
        rol al_w+1
        asl al_w
        rol al_w+1
        asl al_w
        rol al_w+1
        clc
        lda al_w
        adc #32
        sta al_w
        sta gp_w
        lda al_w+1
        adc #0
        sta al_w+1
        sta gp_w+1
        sec                             ; x = (640 - width) / 2
        lda #<640
        sbc al_w
        sta gp_x
        lda #>640
        sbc al_w+1
        lsr
        sta gp_x+1
        ror gp_x
        lda al_n                        ; height: 18 (frame) + 6 + lines * 10 + 6 + 16 + 6
        asl
        sta al_h
        asl
        asl
        clc
        adc al_h
        adc #52
        sta gp_h
        lda #AW
        sta gp_win
        lda #70
        sta gp_y
        lda #GWF_MODAL | GWF_CLOSE | GWF_MOVABLE
        sta gp_flags
        lda #<str_buf
        sta gp_text
        lda #>str_buf
        sta gp_text+1
        jsr gui_win_open
        ; a label a line (each one ends where the line does: a 0 put there for a moment)
        lda #0
        sta al_i
_lab:   ldx al_i
        cpx al_n
        beq _ok
        clc
        lda al_start,x
        adc al_len,x
        tay
        lda str_buf2,y
        sta al_save
        lda #0
        sta str_buf2,y
        sty al_end
        lda #AW
        sta gp_win
        txa
        clc
        adc #3                          ; gadgets 3 ..
        sta gp_gid
        lda #GK_LABEL
        sta gp_kind
        lda #6
        sta gp_x
        lda #0
        sta gp_x+1
        sta gp_max
        txa                             ; y = 6 + line * 10
        asl
        sta al_h
        asl
        asl
        clc
        adc al_h
        adc #6
        sta gp_y
        sec
        lda al_w
        sbc #20
        sta gp_w
        lda al_w+1
        sbc #0
        sta gp_w+1
        lda #10
        sta gp_h
        lda #GGF_CENTRE
        sta gp_flags
        clc
        lda #<str_buf2
        adc al_start,x
        sta gp_text
        lda #>str_buf2
        adc #0
        sta gp_text+1
        jsr gui_gad_add
        ldy al_end
        lda al_save
        sta str_buf2,y
        inc al_i
        bra _lab
_ok:    lda #AW                         ; OK in the middle, under the lines
        sta gp_win
        lda #2
        sta gp_gid
        lda #GK_BUTTON
        sta gp_kind
        sec                             ; x = (width - 88) / 2
        lda al_w
        sbc #88
        sta gp_x
        lda al_w+1
        sbc #0
        lsr
        sta gp_x+1
        ror gp_x
        lda al_n                        ; y = 6 + lines * 10 + 4
        asl
        sta al_h
        asl
        asl
        clc
        adc al_h
        adc #10
        sta gp_y
        lda #80
        sta gp_w
        lda #0
        sta gp_w+1
        lda #16
        sta gp_h
        lda #GGF_DEFAULT
        sta gp_flags
        lda #<s_ok
        sta gp_text
        lda #>s_ok
        sta gp_text+1
        jsr gui_gad_add
        lda #AW
        jmp gui_win_show
AL_COLS         = 52                    ; characters a line
AL_LINES        = 4
al_w:   .word 0
al_h:   .byte 0
al_n:   .byte 0
al_i:   .byte 0
al_pos: .byte 0
al_max: .byte 0
al_end: .byte 0
al_save: .byte 0
al_start: .fill AL_LINES
al_len: .fill AL_LINES
s_ok:   .null "OK"

; the alert's OK or close box
alert_event:
        lda ge_win
        cmp #AW
        bne +
        lda ge_type
        cmp #GE_KEY
        beq +
        lda #AW
        jmp gui_win_close
+       rts

;=======================================================================================
; sending
;=======================================================================================
tx_begin:                               ; A = type
        sta tx_buf+2
        lda #3
        sta tx_n
        lda #0
        sta tx_n+1
        rts
tx_u8:
        ldx tx_n
        sta tx_buf,x
        inc tx_n
        rts
tx_u16:                                 ; A = low, X = high
        phx
        jsr tx_u8
        pla
        jmp tx_u8
tx_str:                                 ; A/X = a zero-terminated string: as much of it
        sta tmp6                        ; as fits in the frame (tx_buf: 255 bytes)
        stx tmp6+1
        sec
        lda #254                        ; room left after its length byte
        sbc tx_n
        bcs +
        lda #0
+       sta tx_sm
        ldy #0
-       cpy tx_sm
        beq +
        lda (tmp6),y
        beq +
        iny
        bra -
+       sty tx_sn
        tya
        jsr tx_u8
        ldy #0
-       cpy tx_sn
        beq +
        lda (tmp6),y
        jsr tx_u8
        iny
        bra -
+       rts
tx_sn:  .byte 0
tx_sm:  .byte 0

; send the frame built in tx_buf. Carry set = failed
tx_end:
        sec
        lda tx_n
        sbc #2
        sta tx_buf
        lda #0
        sta tx_buf+1
        .if DEBUG_NET
        jsr nl_tx                       ; (the log)
        .endif
        lda #0
        sta tx_i
-       ldx tx_i
        lda tx_buf,x
        jsr net_send
        bcs _fail
        inc tx_i
        lda tx_i
        cmp tx_n
        bne -
        inc proto_txn
        bne +
        inc proto_txn+1
+       clc
_fail:  rts
tx_i:   .byte 0

proto_hello:
        lda #C_HELLO
        jsr tx_begin
        lda #PROTO_VERSION
        jsr tx_u8
        lda #<CLIENT_BUILD
        ldx #>CLIENT_BUILD
        jsr tx_u16
        lda #CLIENT_CAPS                ; what storage.asm can do (protocol.Caps)
        jsr tx_u8
        lda #<s_client
        ldx #>s_client
        jsr tx_str
        jmp tx_end
s_client:       .null "MegaNet MEGA65"

proto_login:
        lda #250                        ; (the hourglass until the server answers, 5 s at most)
        sta busy_wait
        lda #C_LOGIN
        jsr tx_begin
        lda login_new
        jsr tx_u8
        lda login_new                   ; (tx_u8 changes the flags)
        beq +
        lda #0                          ; New User: an empty name and password start the
        jsr tx_u8                       ; server's step-by-step sign-up
        lda #0
        jsr tx_u8
        jmp tx_end
+       lda #LW
        ldx #LG_NAME
        jsr gui_get_text
        jsr tx_str
        lda #LW
        ldx #LG_PASS
        jsr gui_get_text
        jsr tx_str
        jmp tx_end

proto_gui_event:
        lda ge_type
        cmp #GE_CLICK
        beq _click
        cmp #GE_CLOSE
        beq _close
        cmp #GE_KEY
        beq _key
        cmp #GE_DESK
        bne +
        jsr busy_click
        lda #C_DESK_OPEN
        jsr tx_begin
        lda ge_val
        jsr tx_u8
        jmp tx_end
+       cmp #GE_NOTIFY
        bne +
        jsr busy_click
        lda #C_NOTIFY_CLICK
        jsr tx_begin
        lda ge_val
        jsr tx_u8
        jmp tx_end
+       cmp #GE_MENU
        bne +
        jsr busy_click
        lda #C_MENU_PICK
        jsr tx_begin
        lda ge_val
        jsr tx_u8
        jmp tx_end
+       cmp #GE_SELECT
        bne _out
        lda #C_SELECT
        jsr tx_begin
        lda ge_win
        jsr tx_u8
        lda ge_gid
        jsr tx_u8
        lda ge_val
        ldx ge_val+1
        jsr tx_u16
        jmp tx_end
_click: jsr busy_click
        lda ge_win                      ; VALUE for each text box of the window first
        jsr gui_find_win
        bcs _out
        stx pe_ws
        ldx #0
_tb:    stx pe_i
        lda gg_win,x
        cmp pe_ws
        bne _ntb
        lda gg_kind,x
        cmp #GK_EDIT
        bne +
        jsr proto_text
        bra _ntb
+       cmp #GK_TEXT
        beq +
        cmp #GK_PASSWORD
        bne _ntb
+       lda #C_VALUE
        jsr tx_begin
        lda ge_win
        jsr tx_u8
        ldx pe_i
        lda gg_id,x
        jsr tx_u8
        ldx pe_i
        lda gg_id,x
        tax
        lda ge_win
        jsr gui_get_text
        jsr tx_str
        jsr tx_end
_ntb:   ldx pe_i
        inx
        cpx #GUI_MAXGAD
        bne _tb
        lda #C_CLICK
        jsr tx_begin
        lda ge_win
        jsr tx_u8
        lda ge_gid
        jsr tx_u8
        jmp tx_end
_close: lda #C_WIN_CLOSED
        jsr tx_begin
        lda ge_win
        jsr tx_u8
        jsr tx_end
        lda ge_win
        jmp gui_win_close
_key:   lda ge_win                      ; only for gadgets that ask for raw keys
        ldx ge_gid
        jsr gui_find_gad
        bcs _out
        lda gg_flags,x
        and #GGF_RAWKEYS
        beq _out
        lda #C_KEY
        jsr tx_begin
        lda ge_win
        jsr tx_u8
        lda ge_gid
        jsr tx_u8
        lda ge_key
        jsr tx_u8
        jmp tx_end
_out:   rts
pe_ws:  .byte 0

; TEXT for text area pe_i of window ge_win: u8 win, u8 gid, u8 n, n strings. It can be
; longer than tx_buf, so it goes straight out: the length first, then each line
proto_text:
        ldx pe_i
        lda gg_id,x
        sta pt_gid
        lda ge_win
        ldx pt_gid
        jsr gui_edit_count
        bcs _out
        sta pt_n
_trim:  lda pt_n                        ; no empty lines at the end
        beq _len
        dec a
        tay
        lda ge_win
        ldx pt_gid
        jsr gui_edit_line
        ldy #0
        lda (txt_ptr),y
        bne _len
        dec pt_n
        bra _trim
_len:   lda #4                          ; frame length: type, win, gid, n + each line
        sta pt_len
        lda #0
        sta pt_len+1
        sta pt_i
_sum:   lda pt_i
        cmp pt_n
        beq _send
        jsr pt_line
        sec                             ; + 1 + its length
        adc pt_len
        sta pt_len
        bcc _next
        inc pt_len+1
_next:  inc pt_i
        bra _sum
_send:
        .if DEBUG_NET
        jsr nl_txt                      ; (the log)
        .endif
        lda pt_len
        jsr net_send
        lda pt_len+1
        jsr net_send
        lda #C_TEXT
        jsr net_send
        lda ge_win
        jsr net_send
        lda pt_gid
        jsr net_send
        lda pt_n
        jsr net_send
        lda #0
        sta pt_i
_l:     lda pt_i
        cmp pt_n
        beq _done
        jsr pt_line
        sta pt_k
        jsr net_send
        ldy #0
-       cpy pt_k
        beq +
        lda (txt_ptr),y
        phy
        jsr net_send
        ply
        iny
        bra -
+       inc pt_i
        bra _l
_done:  inc proto_txn
        bne _out
        inc proto_txn+1
_out:   rts
; line pt_i -> txt_ptr, A = its length
pt_line:
        ldy pt_i
        lda ge_win
        ldx pt_gid
        jsr gui_edit_line
        ldy #0
-       lda (txt_ptr),y
        beq +
        iny
        bra -
+       tya
        rts
pt_gid: .byte 0
pt_n:   .byte 0
pt_i:   .byte 0
pt_k:   .byte 0
pt_len: .word 0
pe_i:   .byte 0

; the hourglass for a moment after a click the server answers (cleared by its answer)
busy_click:
        lda #75                         ; 1.5 s at most (some clicks get no answer)
        sta busy_wait
        rts
busy_wait:      .byte 0                 ; frames left to wait for the server
answer_wait:    .byte 0                 ; frames left of the server's answer to a click

; once a frame: busy (the hourglass, no input) while connecting or waiting for an answer
busy_frame:
        lda answer_wait
        beq +
        dec answer_wait
+       lda answer_wait
        beq +
        lda #1
+       sta gui_open_restore
        lda busy_wait
        beq +
        dec busy_wait
+       lda login_state                ; connecting (DHCP, TCP)
        cmp #1
        beq _on
        lda busy_wait
        beq _off
_on:    lda #1
        jmp gui_busy
_off:   lda #0
        jmp gui_busy
