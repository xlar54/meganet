;=======================================================================================
; login.asm - signing on, in two windows over the MegaNet logo on a dark backdrop:
;   1. Connect: the MEGA65's own address (DHCP starts by itself) and the server's address;
;      Connect.
;   2. Sign On (once connected): screen name and password; Sign On, New User (the server's
;      step-by-step sign-up), Back (another server).
; The port is fixed (SERVER_PORT).
;
;   login_open     draw the screen, open the Connect window
;   login_event    a gui_update event in either window
;   login_step     once a frame: the network, the connection, the sign-on
;
; login_state: 0 the Connect window (typing; the network starts), 1 connecting,
;              4 the Sign On window (connected), 2 waiting for LOGIN_RESULT (the sign-up
;              wizard runs then), 3 signed on
;=======================================================================================

SERVER_PORT     = 6400
CW              = $f0                   ; the Connect window (ids $F0-$FF are the client's)
CG_MYIP         = 2
CG_SERVER       = 4
CG_STATUS       = 5
CG_CONNECT      = 6
LW              = $f1                   ; the Sign On window
LG_NAME         = 2
LG_PASS         = 4
LG_STATUS       = 7
LG_SIGNON       = 8
LG_NEW          = 9
LG_BACK         = 10

LS_CONNECT      = 0                     ; login_state
LS_CONNECTING   = 1
LS_WAIT         = 2
LS_ON           = 3
LS_SIGNON       = 4

LOGO_COL        = (80 - LOGO_CW) / 2    ; where the logo goes, in cells
LOGO_ROW        = 1

LOGIN_X         = 172
LOGIN_Y         = 70
LOGIN_W         = 296
LOGIN_H         = 94

login_state:    .byte 0
login_new:      .byte 0                 ; 1 = New User
login_ip:       .fill 4                 ; the server's address
logo_ok:        .byte 0                 ; set at boot when the logo loaded
l_win:          .byte CW                ; the window the status line is in
l_stgid:        .byte CG_STATUS
l_ipshown:      .byte 0                 ; our own address is on the Connect window
l_wait:         .byte 0                 ; frames before starting the network (so the
                                        ; window is drawn before the 4 s Ethernet reset)
l_server:       .text DEFAULT_SERVER    ; the server's address as typed (kept for Back);
        .fill 16 - len(DEFAULT_SERVER)  ; at first the build's default (gen/server.asm)
        .cerror len(DEFAULT_SERVER) > 15, "DEFAULT_SERVER is too long"
l_myip:         .fill 16                ; our address as text

login_open:
        lda #<login_backdrop
        sta gui_desk_hook
        lda #>login_backdrop
        sta gui_desk_hook+1
        lda #0                          ; no menu bar until signed on
        sta gui_menubar
        jsr gui_menu_clear
        jsr gui_desk_clear              ; nor desktop icons
        ; (fall through)
; the Connect window
open_connect:
        lda #LS_CONNECT
        sta login_state
        lda #CW
        sta l_win
        lda #CG_STATUS
        sta l_stgid
        lda #0
        sta l_ipshown
        lda #3
        sta l_wait
        #GUI_WIN CW, LOGIN_X, LOGIN_Y, LOGIN_W, LOGIN_H, 0, s_cw_title
        #GUI_GAD CW, 1, GK_LABEL, 8, 4, 108, 12, 0, 0, s_cw_myip
        #GUI_GAD CW, CG_MYIP, GK_LABEL, 118, 4, 162, 12, 0, 0, s_cw_getting
        #GUI_GAD CW, 3, GK_LABEL, 8, 20, 108, 12, 0, 0, s_cw_server
        #GUI_GAD CW, CG_SERVER, GK_TEXT, 118, 20, 162, 12, 0, 15, l_server
        #GUI_GAD CW, CG_STATUS, GK_LABEL, 10, 38, 268, 10, GGF_CENTRE, 0, s_cw_hint
        #GUI_GAD CW, CG_CONNECT, GK_BUTTON, 92, 56, 104, 16, GGF_DEFAULT, 0, s_cw_connect
        jsr show_myip                   ; (if the network is already up)
        lda #CW
        jmp gui_win_show

; the Sign On window
open_signon:
        lda #LS_SIGNON
        sta login_state
        lda #LW
        sta l_win
        lda #LG_STATUS
        sta l_stgid
        #GUI_WIN LW, LOGIN_X, LOGIN_Y, LOGIN_W, LOGIN_H, 0, s_lw_title
        #GUI_GAD LW, 1, GK_LABEL, 8, 4, 100, 12, 0, 0, s_lw_name
        #GUI_GAD LW, LG_NAME, GK_TEXT, 110, 4, 170, 12, 0, 10, 0
        #GUI_GAD LW, 3, GK_LABEL, 8, 20, 100, 12, 0, 0, s_lw_pass
        #GUI_GAD LW, LG_PASS, GK_PASSWORD, 110, 20, 170, 12, 0, 16, 0
        #GUI_GAD LW, LG_STATUS, GK_LABEL, 10, 38, 268, 10, GGF_CENTRE, 0, s_lw_hint
        #GUI_GAD LW, LG_SIGNON, GK_BUTTON, 12, 56, 84, 16, GGF_DEFAULT, 0, s_lw_signon
        #GUI_GAD LW, LG_NEW, GK_BUTTON, 102, 56, 84, 16, 0, 0, s_lw_new
        #GUI_GAD LW, LG_BACK, GK_BUTTON, 192, 56, 84, 16, 0, 0, s_lw_back
        lda #LW
        jmp gui_win_show

; our own address on the Connect window, once DHCP has given us one
show_myip:
        lda l_ipshown
        bne _out
        lda net_state
        cmp #NS_READY
        bcc _out                        ; (off, DHCP: not yet)
        cmp #NS_FAILED
        beq _out
        jsr net_local_ip                ; -> net_myip
        ldx #0                          ; as text: a.b.c.d
        ldy #0
_oct:   phy
        lda net_myip,y
        jsr l_dec
        ply
        iny
        cpy #4
        beq _end
        lda #'.'
        sta l_myip,x
        inx
        bra _oct
_end:   lda #0
        sta l_myip,x
        lda #1
        sta l_ipshown
        lda #CW
        sta gp_win
        lda #CG_MYIP
        sta gp_gid
        lda #<l_myip
        sta gp_text
        lda #>l_myip
        sta gp_text+1
        jmp gui_set_text
_out:   rts
; A as decimal at l_myip,x, no leading zeros (x moves on)
l_dec:  ldy #0
-       cmp #100
        bcc +
        sbc #100
        iny
        bra -
+       sty l_dh
        ldy #0
-       cmp #10
        bcc +
        sbc #10
        iny
        bra -
+       sty l_dt
        sta l_do
        lda l_dh
        beq _t
        ora #'0'
        sta l_myip,x
        inx
        lda l_dt                        ; (hundreds: the tens always show)
        bra _tt
_t:     lda l_dt
        beq _o
_tt:    ora #'0'
        sta l_myip,x
        inx
_o:     lda l_do
        ora #'0'
        sta l_myip,x
        inx
        rts
l_dh:   .byte 0
l_dt:   .byte 0
l_do:   .byte 0

; the desktop behind the sign-on windows
login_backdrop:
        lda #0
        sta gr_x0
        sta gr_x0+1
        sta gr_y0
        sta gr_y0+1
        sta gr_y1+1
        lda #<639
        sta gr_x1
        lda #>639
        sta gr_x1+1
        lda #199
        sta gr_y1
        lda #GC_BLACK
        jsr l_gd_fill
        ldx #0                          ; signed on: one cell row lower, under the menu bar
        lda login_state
        cmp #LS_ON
        bne +
        ldx #4
+       stx ll_which
        lda logo_ok
        beq +
        jsr login_logo
+       lda login_state
        cmp #LS_ON
        beq _in
        #LTEXT 320 - (s_tag_end - s_tag) * 4, 58, GC_LIGHT, s_tag
        #LTEXT 320 - (s_foot_end - s_foot) * 4, 189, GC_SHADOW, s_foot
        rts
_in:    #LTEXT 320 - (s_tag_end - s_tag) * 4, 66, GC_LIGHT, s_tag
        rts

LTEXT .macro x, y, fg, str
        lda #<(\x)
        sta gt_x
        lda #>(\x)
        sta gt_x+1
        lda #\y
        sta gt_y
        lda #\fg
        sta gt_fg
        lda #$ff
        sta gt_bg
        sta gt_n
        lda #0
        sta gt_pw
        lda #<\str
        sta txt_ptr
        lda #>\str
        sta txt_ptr+1
        jsr gui_text
.endmacro

; the logo from attic, one row of cells (one DMA copy) at a time
login_logo:
        ldx #3
-       lda _src0,x
        sta ll_src,x
        phx
        txa
        clc
        adc ll_which
        tax
        lda _dst0,x
        plx
        sta ll_dst,x
        dex
        bpl -
        lda #LOGO_CH
        sta ll_n
_row:   ldx #3
-       lda ll_src,x
        sta ptr1,x
        lda ll_dst,x
        sta ptr2,x
        dex
        bpl -
        lda #<(LOGO_CW * 64)
        sta tmp5
        lda #>(LOGO_CW * 64)
        sta tmp5+1
        jsr dma_copy_far
        clc
        lda ll_src
        adc #<(LOGO_CW * 64)
        sta ll_src
        lda ll_src+1
        adc #>(LOGO_CW * 64)
        sta ll_src+1
        bcc +
        inc ll_src+2
+       clc
        lda ll_dst+1                    ; + 5120 = $1400
        adc #$14
        sta ll_dst+1
        bcc +
        inc ll_dst+2
+       dec ll_n
        bne _row
        rts
_src0:  .dword LOGO_ATTIC
_dst0:  .dword F640_BUF0 + LOGO_ROW * 5120 + LOGO_COL * 64
        .dword F640_BUF0 + (LOGO_ROW + 1) * 5120 + LOGO_COL * 64
ll_which: .byte 0                       ; 0: the sign-on screen's place, 4: one row lower
ll_src: .dword 0
ll_dst: .dword 0
ll_n:   .byte 0

login_event:
        lda ge_type
        cmp #GE_CLICK
        beq +
_out:   rts
+       lda ge_win
        cmp #CW
        beq _cw
        cmp #LW
        bne _out
        lda login_state                 ; the Sign On window: only while it's up
        cmp #LS_SIGNON
        bne _out
        lda ge_gid
        cmp #LG_BACK
        beq _back
        cmp #LG_SIGNON
        beq _sign
        cmp #LG_NEW
        bne _out
        lda #1                          ; New User: the server's sign-up wizard asks it all,
        sta login_new                   ; in its own windows: this one goes
        lda #LW
        jsr gui_win_close
        jsr proto_login
        lda #LS_WAIT
        sta login_state
        rts
_sign:  lda #0
        sta login_new
        lda #LW                         ; a screen name?
        ldx #LG_NAME
        jsr gui_get_text
        cpy #0
        bne +
        lda #<s_lw_noname
        ldx #>s_lw_noname
        jmp login_status
+       lda #LW                         ; a password?
        ldx #LG_PASS
        jsr gui_get_text
        cpy #0
        bne _go
        lda #<s_lw_nopass
        ldx #>s_lw_nopass
        jmp login_status
_go:    jsr proto_login
        lda #LS_WAIT
        sta login_state
        lda #<s_lw_signing
        ldx #>s_lw_signing
        jmp login_status
_back:  jsr net_close                   ; another server: back to the Connect window
        lda #LW
        jsr gui_win_close
        jmp open_connect
_cw:    lda login_state                 ; the Connect window: Connect
        cmp #LS_CONNECT
        bne _out
        lda ge_gid
        cmp #CG_CONNECT
        bne _out
        lda #CW                         ; the server's address
        ldx #CG_SERVER
        jsr gui_get_text
        sta txt_ptr
        stx txt_ptr+1
        ldy #0                          ; (kept, for Back)
-       lda (txt_ptr),y
        sta l_server,y
        beq +
        iny
        cpy #15
        bne -
        lda #0
        sta l_server,y
+       jsr parse_ip
        bcc +
        lda #<s_cw_badip
        ldx #>s_cw_badip
        jmp login_status
+       lda #LS_CONNECTING
        sta login_state
        lda #<s_cw_conn
        ldx #>s_cw_conn
login_status:                           ; A/X = a message on the open window's status line
        sta gp_text
        stx gp_text+1
        lda l_win
        sta gp_win
        lda l_stgid
        sta gp_gid
        jmp gui_set_text

; "a.b.c.d" at txt_ptr -> login_ip; carry set if it isn't one
parse_ip:
        ldy #0
        ldx #0                          ; which number
_num:   lda #0
        sta pi_v
        sta pi_v+1
        sta pi_d
_dig:   lda (txt_ptr),y
        cmp #'0'
        bcc _end
        cmp #'9' + 1
        bcs _end
        and #$0f
        pha                             ; v = v * 10 + digit
        lda pi_v
        asl
        sta pi_t
        lda pi_v+1
        rol
        sta pi_t+1                      ; t = 2v
        asl pi_v
        rol pi_v+1
        asl pi_v
        rol pi_v+1
        asl pi_v
        rol pi_v+1                      ; v = 8v
        clc
        lda pi_v
        adc pi_t
        sta pi_v
        lda pi_v+1
        adc pi_t+1
        sta pi_v+1
        pla
        clc
        adc pi_v
        sta pi_v
        bcc +
        inc pi_v+1
+       lda pi_v+1                      ; over 255?
        bne _bad
        inc pi_d
        lda pi_d
        cmp #4
        bcs _bad
        iny
        bra _dig
_end:   ldz pi_d                        ; no digits
        beq _bad
        pha
        lda pi_v
        sta login_ip,x
        pla
        inx
        cpx #4
        beq _last
        cmp #'.'
        bne _bad
        iny
        bra _num
_last:  cmp #0                          ; nothing after the fourth number
        bne _bad
        clc
        rts
_bad:   sec
        rts
pi_v:   .word 0
pi_t:   .word 0
pi_d:   .byte 0

s_cw_title:     .null "Connect"
s_cw_myip:      .null "Your address:"
s_cw_getting:   .null "Getting one..."
s_cw_server:    .null "Server:"
        .if MOCK_NET || BRIDGE_NET              ; (so a test disk is never taken for the real one)
s_cw_hint:      .null "Xemu test build: no Ethernet."
        .else
s_cw_hint:      .null "Check the server, then Connect."
        .endif
s_cw_connect:   .null "Connect"
s_cw_badip:     .null "Server: four numbers, like 192.168.1.10"
s_cw_conn:      .null "Connecting to the server..."
s_cw_noaddr:    .null "None: check the cable"
s_lw_title:     .null "Sign On"
s_lw_name:      .null "Screen name:"
s_lw_pass:      .null "Password:"
s_lw_hint:      .null "Sign On, or New User to join."
s_lw_signon:    .null "Sign On"
s_lw_new:       .null "New User"
s_lw_back:      .null "Back"
s_lw_noname:    .null "Please type a screen name."
s_lw_nopass:    .null "Please type a password."
s_lw_signing:   .null "Signing on..."
s_lw_lost:      .null "The connection was lost."

; the error for net_err
err_lo:         .byte <s_e0, <s_e1, <s_e2, <s_e3, <s_e4, <s_e5
err_hi:         .byte >s_e0, >s_e1, >s_e2, >s_e3, >s_e4, >s_e5
s_e0:           .null "Network error."
s_e1:           .null "The network stack didn't load."
s_e2:           .null "No address from DHCP: check cable."
s_e3:           .null "Can't reach the server."
s_e4:           .null "Sending to the server failed."
s_e5:           .null "The connection was lost."

;---------------------------------------------------------------------------------------
; login_step: once a frame, moves the sign-on along
;---------------------------------------------------------------------------------------
login_step:
        lda login_state
        cmp #LS_CONNECT
        beq _typing
        cmp #LS_CONNECTING
        beq _conn
        cmp #LS_SIGNON
        beq _signon
        cmp #LS_WAIT
        bne +
        jmp _wait
+       cmp #LS_ON
        bne _out
        lda net_state                   ; signed on: watch the connection
        cmp #NS_FAILED
        bne _out
        jmp login_lost
_out:   rts
_typing:                                ; the Connect window is up: start the network
        jsr show_myip
        lda net_state
        cmp #NS_FAILED
        bne +
        lda net_err                     ; DHCP failed: say so (Connect tries again)
        cmp #E_DHCP
        bne _out
        lda #NS_OFF
        sta net_state
        lda #CW
        sta gp_win
        lda #CG_MYIP
        sta gp_gid
        lda #<s_cw_noaddr
        sta gp_text
        lda #>s_cw_noaddr
        sta gp_text+1
        jmp gui_set_text
+       cmp #NS_OFF
        bne _out
        lda l_wait                      ; (a few frames, so the window is on screen first)
        beq +
        dec l_wait
        rts
+       lda #250                        ; (wait a long while for the next try)
        sta l_wait
        jmp net_start                   ; (blocks about 4 s: the Ethernet reset)
_signon:
        lda net_state                   ; connected, typing: watch the connection
        cmp #NS_FAILED
        bne _out
        jmp login_lost
_conn:  jsr show_myip
        lda net_state
        cmp #NS_OFF
        bne +
        jsr net_start
        bcs _out
        rts
+       cmp #NS_READY
        bne +
        jmp net_connect
+       cmp #NS_ONLINE
        bne +
        lda proto_txn                   ; HELLO once per connection
        ora proto_txn+1
        bne _up
        jsr proto_hello
_up:    lda #CW                         ; connected: the Sign On window instead
        jsr gui_win_close
        jmp open_signon
+       cmp #NS_FAILED
        bne _out
        lda #LS_CONNECT                 ; back to the Connect window, with the reason
        sta login_state
        lda net_was                     ; DHCP never finished: start again from scratch
        cmp #NS_DHCP
        beq +
        cmp #NS_OFF
        beq +
        lda #NS_READY
        bra ++
+       lda #NS_OFF
+       sta net_state
        jsr l_err
        jmp login_status
_wait:  lda net_state
        cmp #NS_FAILED
        bne +
        jmp login_lost
+       lda proto_login_ok
        bne +
        rts
+       cmp #1
        beq login_done
        lda #0                          ; refused (or the sign-up cancelled): the server
        sta proto_login_ok              ; says why, and the Sign On window is back
        lda login_new
        beq +
        jsr open_signon                 ; (New User closed it)
+       lda #LS_SIGNON
        sta login_state
        lda login_msg
        ldx login_msg+1
        jmp login_status
; A/X = the message for net_err
l_err:  ldx net_err
        cpx #6
        bcc +
        ldx #0
+       lda err_lo,x
        pha
        lda err_hi,x
        tax
        pla
        rts

; signed on: the sign-on window goes, the server's windows stay
login_done:
        lda #LS_ON
        sta login_state
        lda #1                          ; the menu bar (the server has sent its menus);
        sta gui_menubar                 ; the same black backdrop and logo behind
        lda #LW
        jmp gui_win_close

; the connection dropped: back to the Connect window, with the reason
login_lost:
        jsr far_pic_off                 ; (a picture showing: the desktop back)
        jsr far_cv_off                  ; (Paint: the same)
        jsr sprites_off                 ; (the server's sprites)
        jsr gui_close_all
        lda #NS_READY                   ; (DHCP is still good)
        sta net_state
        jsr login_open
        lda #<s_lw_lost
        ldx #>s_lw_lost
        jmp login_status
s_tag:          .text "The online service for the MEGA65"
s_tag_end:      .byte 0
s_foot:         .text "Port 6400"
s_foot_end:     .byte 0
