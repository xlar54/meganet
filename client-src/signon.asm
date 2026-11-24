;=======================================================================================
; signon.asm - the sign-on windows (in the OVL_UI overlay; login.asm keeps the state machine
; and calls in here): the Connect window, the Sign On window, and the Static Address window.
;
;   ui_connect        build the Connect window (login.asm open_connect shows it):
;                     Your address, Network: (o) DHCP ( ) Static IP, Server, a status line,
;                     Connect
;   ui_signon         build and show the Sign On window
;   ui_connect_click  a click in the Connect window: the radio buttons, or Connect. With
;                     Static IP chosen, Connect opens the Static Address window first
;   ui_static_event   the Static Address window: OK (check the addresses, then login.asm's
;                     login_step starts the network with them: ui_static_start), Cancel
;   ui_static_start   (login_step) restart mega-ip with the static addresses: about 4 s
;
; The static addresses typed are kept here (the overlay is written back to attic after each
; call), so the window shows them again; at first, what DHCP found, if it found anything.
;=======================================================================================

SW              = $f2                   ; the Static Address window
SG_IP           = 2                     ; its text boxes (labels are the odd ids)
SG_MASK         = 4
SG_GW           = 6
SG_DNS          = 8
SG_STATUS       = 9
SG_OK           = 10
SG_CANCEL       = 11
SW_H            = 124
CONNECT_H       = LOGIN_H + 16          ; the Connect window: the Network row more

;---------------------------------------------------------------------------------------
; the windows
;---------------------------------------------------------------------------------------
ui_connect:
        #GUI_WIN CW, LOGIN_X, LOGIN_Y, LOGIN_W, CONNECT_H, 0, s_cw_title
        #GUI_GAD CW, 1, GK_LABEL, 8, 4, 108, 12, 0, 0, s_cw_myip
        #GUI_GAD CW, CG_MYIP, GK_LABEL, 118, 4, 162, 12, 0, 0, s_cw_getting
        #GUI_GAD CW, 7, GK_LABEL, 8, 20, 108, 12, 0, 0, s_cw_net
        #GUI_GAD CW, CG_DHCP, GK_RADIO, 118, 19, 64, 12, 0, 0, s_cw_dhcp
        #GUI_GAD CW, CG_STATIC, GK_RADIO, 186, 19, 96, 12, 0, 0, s_cw_static
        #GUI_GAD CW, 3, GK_LABEL, 8, 36, 108, 12, 0, 0, s_cw_server
        #GUI_GAD CW, CG_SERVER, GK_TEXT, 118, 36, 162, 12, 0, 15, l_server
        #GUI_GAD CW, CG_STATUS, GK_LABEL, 10, 54, 268, 10, GGF_CENTRE, 0, s_cw_hint
        #GUI_GAD CW, CG_CONNECT, GK_BUTTON, 92, 72, 104, 16, GGF_DEFAULT, 0, s_cw_connect
        jmp ui_radios

; the radio buttons as login_static says
ui_radios:
        lda #1
        ldx login_static
        beq +
        lda #0
+       ldx #CG_DHCP
        jsr _set
        lda login_static
        ldx #CG_STATIC
_set:   sta gp_x
        lda #0
        sta gp_x+1
        lda #CW
        jmp gui_set_value

ui_signon:
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

;---------------------------------------------------------------------------------------
; the Connect window's clicks (login_state LS_CONNECT)
;---------------------------------------------------------------------------------------
ui_connect_click:
        lda ge_gid
        cmp #CG_DHCP
        bne +
        lda #0
        bra _mode
+       cmp #CG_STATIC
        bne +
        lda #1
_mode:  sta login_static
        jmp ui_radios
+       cmp #CG_CONNECT
        beq +
        rts
+       lda #CW                         ; the server's address (kept, for Back)
        ldx #CG_SERVER
        jsr gui_get_text
        sta txt_ptr
        stx txt_ptr+1
        ldy #0
-       lda (txt_ptr),y
        sta l_server,y
        beq +
        iny
        cpy #15
        bne -
        lda #0
        sta l_server,y
+       jsr ui_parse_ip
        bcc +
        lda #<s_cw_badip
        ldx #>s_cw_badip
        jmp login_status
+       ldx #3
-       lda ui_ip,x
        sta login_ip,x
        dex
        bpl -
        lda login_static                ; Static IP: its addresses first
        beq +
        jmp ui_static_open
+       lda login_staticup              ; DHCP again after static addresses: start afresh
        beq +
        lda #0
        sta login_staticup
        sta l_ipshown
        lda #NS_OFF
        sta net_state
        lda #CW
        sta gp_win
        lda #CG_MYIP
        sta gp_gid
        lda #<s_cw_getting
        sta gp_text
        lda #>s_cw_getting
        sta gp_text+1
        jsr gui_set_text
+       lda #LS_CONNECTING
        sta login_state
        lda #<s_cw_conn
        ldx #>s_cw_conn
        jmp login_status

;---------------------------------------------------------------------------------------
; the Static Address window
;---------------------------------------------------------------------------------------
ui_static_open:
        lda ui_have                     ; nothing typed yet: what DHCP found, if anything
        bne _win
        lda net_state
        cmp #NS_READY
        bne _win
        .if MOCK_NET == 0 && BRIDGE_NET == 0
        #NET_A MIP_GET_LOCAL_IP
        jsr ui_ip_in
        ldx #0
        jsr ui_ip_text
        #NET_A MIP_GET_SUBNET_MASK
        jsr ui_ip_in
        ldx #16
        jsr ui_ip_text
        #NET_A MIP_GET_GATEWAY_IP
        jsr ui_ip_in
        ldx #32
        jsr ui_ip_text
        #NET_A MIP_GET_PRIMARY_DNS
        jsr ui_ip_in
        ldx #48
        jsr ui_ip_text
        .endif
_win:   #GUI_WIN SW, LOGIN_X, LOGIN_Y + 8, LOGIN_W, SW_H, GWF_MODAL | GWF_CLOSE | GWF_MOVABLE, s_sw_title
        #GUI_GAD SW, 1, GK_LABEL, 8, 4, 108, 12, 0, 0, s_sw_ip
        #GUI_GAD SW, SG_IP, GK_TEXT, 118, 4, 162, 12, 0, 15, ui_txt
        #GUI_GAD SW, 3, GK_LABEL, 8, 20, 108, 12, 0, 0, s_sw_mask
        #GUI_GAD SW, SG_MASK, GK_TEXT, 118, 20, 162, 12, 0, 15, (ui_txt + 16)
        #GUI_GAD SW, 5, GK_LABEL, 8, 36, 108, 12, 0, 0, s_sw_gw
        #GUI_GAD SW, SG_GW, GK_TEXT, 118, 36, 162, 12, 0, 15, (ui_txt + 32)
        #GUI_GAD SW, 7, GK_LABEL, 8, 52, 108, 12, 0, 0, s_sw_dns
        #GUI_GAD SW, SG_DNS, GK_TEXT, 118, 52, 162, 12, 0, 15, (ui_txt + 48)
        #GUI_GAD SW, SG_STATUS, GK_LABEL, 10, 70, 268, 10, GGF_CENTRE, 0, s_sw_hint
        #GUI_GAD SW, SG_OK, GK_BUTTON, 52, 86, 88, 16, GGF_DEFAULT, 0, s_sw_ok
        #GUI_GAD SW, SG_CANCEL, GK_BUTTON, 148, 86, 88, 16, 0, 0, s_sw_cancel
        lda #SW
        ldx #SG_IP
        jsr gui_focus
        lda #SW
        jmp gui_win_show

ui_static_event:
        lda ge_type
        cmp #GE_CLOSE
        beq _cancel
        cmp #GE_CLICK
        bne _out
        lda ge_gid
        cmp #SG_CANCEL
        beq _cancel
        cmp #SG_OK
        beq ui_static_ok
_out:   rts
_cancel:
        jsr ui_keep                     ; (what was typed stays for next time)
        lda #SW
        jmp gui_win_close

; OK: every address checked (DNS may be empty), then login_step starts the network with them
ui_static_ok:
        jsr ui_keep
        lda #0                          ; each box in turn: A = its offset in ui_txt
        sta ui_k
_box:   lda ui_k
        clc
        adc #<ui_txt
        sta txt_ptr
        lda #>ui_txt
        adc #0
        sta txt_ptr+1
        ldy #0
        lda (txt_ptr),y
        bne _parse
        lda ui_k                        ; empty: only the DNS server may be
        cmp #48
        beq _next
        bra _bad
_parse: jsr ui_parse_ip
        bcs _bad
        lda ui_k                        ; -> ui_addr + k / 4
        lsr
        lsr
        tay
        ldx #0
-       lda ui_ip,x
        sta ui_addr,y
        iny
        inx
        cpx #4
        bne -
_next:  lda ui_k
        clc
        adc #16
        sta ui_k
        cmp #64
        bne _box
        lda ui_txt + 48                 ; (DNS given?)
        sta ui_dns
        lda #SW
        jsr gui_win_close
        lda #NS_OFF                     ; login_step: LS_CONNECTING with the network off and
        sta net_state                   ; Static IP: ui_static_start, after a redraw
        lda #2
        sta l_wait
        lda #LS_CONNECTING
        sta login_state
        lda #<s_sw_start
        ldx #>s_sw_start
        jmp login_status
_bad:   lda ui_k                        ; which one
        lsr
        lsr
        lsr
        lsr
        tax
        lda ui_err_lo,x
        sta gp_text
        lda ui_err_hi,x
        sta gp_text+1
        lda #SW
        sta gp_win
        lda #SG_STATUS
        sta gp_gid
        jmp gui_set_text

; the four boxes' texts -> ui_txt (16 bytes each), and remember they were typed
ui_keep:
        lda #0
        sta ui_k
_box:   lda ui_k                        ; gadget 2, 4, 6, 8
        lsr
        lsr
        lsr
        clc
        adc #SG_IP
        tax
        lda #SW
        jsr gui_get_text
        bcs _next
        sta txt_ptr
        stx txt_ptr+1
        ldx ui_k
        ldy #0
-       lda (txt_ptr),y
        sta ui_txt,x
        beq _next
        inx
        iny
        cpy #15
        bne -
        lda #0
        sta ui_txt,x
_next:  lda ui_k
        clc
        adc #16
        sta ui_k
        cmp #64
        bne _box
        lda #1
        sta ui_have
        rts

; (login_step) mega-ip again, with the static addresses: carry set if it failed
ui_static_start:
        jsr net_start_static            ; (about 4 s: the Ethernet reset)
        bcs _out
        .if MOCK_NET == 0 && BRIDGE_NET == 0
        lda ui_addr + 1
        ldx ui_addr + 2
        ldy ui_addr + 3
        jsr ui_net_args
        lda ui_addr
        #NET MIP_SET_LOCAL_IP
        lda ui_addr + 5
        ldx ui_addr + 6
        ldy ui_addr + 7
        jsr ui_net_args
        lda ui_addr + 4
        #NET MIP_SET_SUBNET_MASK
        lda ui_addr + 9
        ldx ui_addr + 10
        ldy ui_addr + 11
        jsr ui_net_args
        lda ui_addr + 8
        #NET MIP_SET_GATEWAY_IP
        lda ui_dns
        beq +
        lda ui_addr + 13
        ldx ui_addr + 14
        ldy ui_addr + 15
        jsr ui_net_args
        lda ui_addr + 12
        #NET MIP_SET_PRIMARY_DNS
+       ldz #0
        .endif
        lda #1
        sta login_staticup
        lda #0
        sta l_ipshown                   ; (Your address: the static one)
        clc
_out:   rts
; A, X, Y = bytes 1, 2, 3 -> X, Y, Z for the #NET call (byte 0 goes in A after)
ui_net_args:
        sta ui_t
        tya
        taz
        txa
        tay
        ldx ui_t
        rts

;---------------------------------------------------------------------------------------
; addresses as text
;---------------------------------------------------------------------------------------
; a #NET_A call's A, X, Y, Z (an address) -> ui_ip
ui_ip_in:
        sta ui_ip
        stx ui_ip+1
        sty ui_ip+2
        tza
        sta ui_ip+3
        ldz #0
        rts

; ui_ip as "a.b.c.d" at ui_txt + X
ui_ip_text:
        ldy #0
_oct:   phy
        lda ui_ip,y
        jsr _dec
        ply
        iny
        cpy #4
        beq _end
        lda #'.'
        sta ui_txt,x
        inx
        bra _oct
_end:   lda #0
        sta ui_txt,x
        rts
_dec:   ldy #0                          ; A in decimal, no leading zeros
-       cmp #100
        bcc +
        sbc #100
        iny
        bra -
+       sty ui_h
        ldy #0
-       cmp #10
        bcc +
        sbc #10
        iny
        bra -
+       sty ui_t
        sta ui_o
        lda ui_h
        beq _t
        ora #'0'
        sta ui_txt,x
        inx
        lda ui_t
        bra _tt
_t:     lda ui_t
        beq _o
_tt:    ora #'0'
        sta ui_txt,x
        inx
_o:     lda ui_o
        ora #'0'
        sta ui_txt,x
        inx
        rts

; "a.b.c.d" at txt_ptr -> ui_ip; carry set if it isn't one
ui_parse_ip:
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
        ldz #0
        pha
        lda pi_v
        sta ui_ip,x
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
_bad:   ldz #0
        sec
        rts
pi_v:   .word 0
pi_t:   .word 0
pi_d:   .byte 0

ui_ip:          .fill 4
ui_addr:        .fill 16                ; IP, mask, gateway, DNS (4 bytes each)
ui_txt:         .fill 16                ; the same as typed (16 each)
        .null "255.255.255.0"         ; (a sensible mask to start with)
        .fill 2
        .fill 32
ui_have:        .byte 0                 ; 1 once the window has been used
ui_dns:         .byte 0
ui_k:           .byte 0
ui_t:           .byte 0
ui_h:           .byte 0
ui_o:           .byte 0
ui_err_lo:      .byte <s_sw_badip, <s_sw_badmask, <s_sw_badgw, <s_sw_baddns
ui_err_hi:      .byte >s_sw_badip, >s_sw_badmask, >s_sw_badgw, >s_sw_baddns

s_cw_title:     .null "Connect"
s_cw_myip:      .null "Your address:"
s_cw_net:       .null "Network:"
s_cw_dhcp:      .null "DHCP"
s_cw_static:    .null "Static IP"
s_cw_server:    .null "Server:"
        .if MOCK_NET || BRIDGE_NET              ; (so a test disk is never taken for the real one)
s_cw_hint:      .null "Xemu test build: no Ethernet."
        .elsif DEBUG_NET
s_cw_hint:      .null "Debug build: F1 shows the log."
        .else
s_cw_hint:      .null "Check the server, then Connect."
        .endif
s_cw_connect:   .null "Connect"
s_cw_badip:     .null "Server: four numbers, like 192.168.1.10"
s_cw_conn:      .null "Connecting to the server..."
s_lw_title:     .null "Sign On"
s_lw_name:      .null "Screen name:"
s_lw_pass:      .null "Password:"
s_lw_hint:      .null "Sign On, or New User to join."
s_lw_signon:    .null "Sign On"
s_lw_new:       .null "New User"
s_lw_back:      .null "Back"
s_sw_title:     .null "Static Address"
s_sw_ip:        .null "IP address:"
s_sw_mask:      .null "Subnet mask:"
s_sw_gw:        .null "Gateway:"
s_sw_dns:       .null "DNS server:"
s_sw_hint:      .null "The DNS server may be left empty."
s_sw_ok:        .null "OK"
s_sw_cancel:    .null "Cancel"
s_sw_start:     .null "Starting the network..."
s_sw_badip:     .null "IP address: four numbers, 0-255"
s_sw_badmask:   .null "Subnet mask: four numbers, 0-255"
s_sw_badgw:     .null "Gateway: four numbers, 0-255"
s_sw_baddns:    .null "DNS server: four numbers, 0-255"
