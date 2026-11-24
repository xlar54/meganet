;=======================================================================================
; signon.asm - the sign-on windows (in the OVL_UI overlay; login.asm keeps the state machine
; and calls in here): the Connect window and the Sign On window.
;
; The Connect window: Network: ( ) DHCP ( ) Static IP, then the IP address, subnet mask,
; gateway and DNS server, then the server's address, a status line and Connect. Nothing is
; picked at first, and the network doesn't start until something is (login_mode):
;   DHCP       the four boxes greyed; login_step asks for an address, and they show what
;              DHCP gave (ui_show_dhcp). Connect: to the server once there's an address
;   Static IP  the four boxes typed in (the DNS server may stay empty). Connect checks them,
;              then login_step restarts mega-ip with them (ui_static_start, about 4 s) and
;              connects
; Connect is greyed until one is picked.
;
;   ui_connect        build the Connect window (login.asm open_connect shows it)
;   ui_signon         build and show the Sign On window
;   ui_connect_click  a click in the Connect window: DHCP, Static IP, or Connect
;   ui_show_dhcp      (show_myip) the DHCP address and the rest in the four boxes
;   ui_static_start   (login_step) mega-ip again, with the static addresses
;
; What's in the boxes is kept here (the overlay is written back to attic after each call), so
; the window shows it again after Back or a lost connection.
;=======================================================================================

CONNECT_X       = 82
CONNECT_Y       = 66
CONNECT_W       = 476
CONNECT_H       = 116
CG_IP           = 10                    ; the four address boxes: CG_IP + n
CG_MASK         = 11
CG_GW           = 12
CG_DNS          = 13

;---------------------------------------------------------------------------------------
; the windows
;---------------------------------------------------------------------------------------
ui_connect:
        #GUI_WIN CW, CONNECT_X, CONNECT_Y, CONNECT_W, CONNECT_H, 0, s_cw_title
        #GUI_GAD CW, 20, GK_LABEL, 6, 4, 92, 12, 0, 0, s_cw_net
        #GUI_GAD CW, CG_DHCP, GK_RADIO, 100, 3, 64, 12, 0, 0, s_cw_dhcp
        #GUI_GAD CW, CG_STATIC, GK_RADIO, 172, 3, 100, 12, 0, 0, s_cw_static
        #GUI_GAD CW, 21, GK_LABEL, 6, 20, 92, 12, 0, 0, s_cw_ip
        #GUI_GAD CW, CG_IP, GK_TEXT, 100, 19, 126, 12, GGF_DISABLED, 15, ui_txt
        #GUI_GAD CW, 22, GK_LABEL, 236, 20, 100, 12, 0, 0, s_cw_mask
        #GUI_GAD CW, CG_MASK, GK_TEXT, 336, 19, 126, 12, GGF_DISABLED, 15, (ui_txt + 16)
        #GUI_GAD CW, 23, GK_LABEL, 6, 35, 92, 12, 0, 0, s_cw_gw
        #GUI_GAD CW, CG_GW, GK_TEXT, 100, 34, 126, 12, GGF_DISABLED, 15, (ui_txt + 32)
        #GUI_GAD CW, 24, GK_LABEL, 236, 35, 100, 12, 0, 0, s_cw_dns
        #GUI_GAD CW, CG_DNS, GK_TEXT, 336, 34, 126, 12, GGF_DISABLED, 15, (ui_txt + 48)
        #GUI_GAD CW, 3, GK_LABEL, 6, 51, 92, 12, 0, 0, s_cw_server
        #GUI_GAD CW, CG_SERVER, GK_TEXT, 100, 50, 126, 12, 0, 15, l_server
        #GUI_GAD CW, CG_STATUS, GK_LABEL, 6, 66, 456, 10, GGF_CENTRE, 0, s_cw_hint
        #GUI_GAD CW, CG_CONNECT, GK_BUTTON, 182, 80, 104, 16, GGF_DEFAULT | GGF_DISABLED, 0, s_cw_connect
        lda login_mode                  ; (picked before: Back, or a lost connection)
        beq +
        jsr ui_mode
+       lda #CW
        ldx #CG_SERVER
        jmp gui_focus

; the gadgets as login_mode says: the radio buttons, the four boxes (Static IP only), Connect
ui_mode:
        ldx #CG_DHCP                    ; the radio buttons
        ldy #1
        jsr _radio
        ldx #CG_STATIC
        ldy #2
        jsr _radio
        lda #GGF_DISABLED               ; the boxes
        ldx login_mode
        cpx #2
        bne +
        lda #0
+       sta ui_t
        lda #CG_IP
        sta ui_k
-       lda ui_t
        sta gp_flags
        lda #CW
        ldx ui_k
        jsr gui_set_flags
        inc ui_k
        lda ui_k
        cmp #CG_DNS + 1
        bne -
        lda #GGF_DEFAULT                ; Connect
        sta gp_flags
        lda #CW
        ldx #CG_CONNECT
        jmp gui_set_flags
; X = a radio button: on if login_mode = Y
_radio: lda #0
        cpy login_mode
        bne +
        lda #1
+       sta gp_x
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
        bne _static
        lda login_mode                  ; DHCP
        cmp #1
        beq _out
        jsr ui_keep                     ; (what was typed stays, for Static IP later)
        lda #1
        sta login_mode
        lda #0
        sta l_ipshown                   ; (its boxes: DHCP's answer, when there is one)
        lda login_staticup              ; the static addresses in use: the stack afresh
        beq +
        lda #0
        sta login_staticup
        lda #NS_OFF
        sta net_state
+       lda #3                          ; (login_step: a few frames, then the request)
        sta l_wait
        jsr ui_mode
        lda #<s_cw_asking
        ldx #>s_cw_asking
        jmp login_status
_static:
        cmp #CG_STATIC
        bne _connect
        lda login_mode
        cmp #2
        beq _out
        lda #2
        sta login_mode
        jsr ui_mode
        lda #CW
        ldx #CG_IP
        jsr gui_focus
        lda #<s_cw_type
        ldx #>s_cw_type
        jmp login_status
_out:   rts
_connect:
        cmp #CG_CONNECT
        bne _out
        lda login_mode
        beq _out
        lda #CW                         ; the server's address (kept, for Back)
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
        lda login_mode                  ; Static IP: the addresses checked first
        cmp #2
        bne +
        jmp ui_static_ok
+       lda #LS_CONNECTING
        sta login_state
        lda #<s_cw_conn
        ldx #>s_cw_conn
        jmp login_status

; Connect with Static IP: every address checked (the DNS server may be empty), then
; login_step restarts mega-ip with them (ui_static_start) once the screen is drawn
ui_static_ok:
        jsr ui_keep
        lda #0                          ; each box in turn: its offset in ui_txt
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
        lda #NS_OFF                     ; login_step: LS_CONNECTING with the network off and
        sta net_state                   ; Static IP: ui_static_start, after a redraw
        lda #2
        sta l_wait
        lda #LS_CONNECTING
        sta login_state
        lda #<s_cw_start
        ldx #>s_cw_start
        jmp login_status
_bad:   lda ui_k                        ; which one
        lsr
        lsr
        lsr
        lsr
        tax
        lda ui_err_lo,x
        pha
        lda ui_err_hi,x
        tax
        pla
        jmp login_status

; the four boxes' texts -> ui_txt (16 bytes each)
ui_keep:
        lda #0
        sta ui_k
_box:   lda ui_k                        ; gadget CG_IP + k / 16
        lsr
        lsr
        lsr
        lsr
        clc
        adc #CG_IP
        tax
        lda #CW
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
        rts

; (show_myip, DHCP: the network is ready) its address, mask, gateway and DNS server in the
; four boxes
ui_show_dhcp:
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
        .else
        ldx #63                         ; (no network of its own: stand-ins)
-       lda ui_standin,x
        sta ui_txt,x
        dex
        bpl -
        .endif
        lda #CG_IP
        sta ui_k
        lda #<ui_txt
        sta gp_text
        lda #>ui_txt
        sta gp_text+1
-       lda #CW
        sta gp_win
        lda ui_k
        sta gp_gid
        jsr gui_set_text
        clc
        lda gp_text
        adc #16
        sta gp_text
        bcc +
        inc gp_text+1
+       inc ui_k
        lda ui_k
        cmp #CG_DNS + 1
        bne -
        lda #1
        sta l_ipshown
        lda #<s_cw_ready
        ldx #>s_cw_ready
        jmp login_status

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
        .null "255.255.255.0"           ; (a sensible mask to start with)
        .fill 2
        .fill 32
        .if MOCK_NET || BRIDGE_NET
ui_standin:     .null "10.0.0.65"       ; (what DHCP "gives" a build with no network)
        .fill 6
        .null "255.255.255.0"
        .fill 2
        .null "10.0.0.1"
        .fill 7
        .null "8.8.8.8"
        .fill 8
        .endif
ui_dns:         .byte 0
ui_k:           .byte 0
ui_t:           .byte 0
ui_h:           .byte 0
ui_o:           .byte 0
ui_err_lo:      .byte <s_cw_badmy, <s_cw_badmask, <s_cw_badgw, <s_cw_baddns
ui_err_hi:      .byte >s_cw_badmy, >s_cw_badmask, >s_cw_badgw, >s_cw_baddns

s_cw_title:     .null "Connect"
s_cw_net:       .null "Network:"
s_cw_dhcp:      .null "DHCP"
s_cw_static:    .null "Static IP"
s_cw_ip:        .null "IP address:"
s_cw_mask:      .null "Subnet mask:"
s_cw_gw:        .null "Gateway:"
s_cw_dns:       .null "DNS server:"
s_cw_server:    .null "Server:"
        .if MOCK_NET || BRIDGE_NET              ; (so a test disk is never taken for the real one)
s_cw_hint:      .null "Xemu test build: no Ethernet. Pick DHCP or Static IP."
        .elsif DEBUG_NET
s_cw_hint:      .null "Debug build: F1 shows the log. Pick DHCP or Static IP."
        .else
s_cw_hint:      .null "Pick DHCP or Static IP, then Connect."
        .endif
s_cw_connect:   .null "Connect"
s_cw_asking:    .null "Asking for an address (DHCP)..."
s_cw_ready:     .null "Address found: check the server, then Connect."
s_cw_type:      .null "Type the addresses (DNS may be empty), then Connect."
s_cw_start:     .null "Starting the network..."
s_cw_badip:     .null "Server: four numbers, like 192.168.1.10"
s_cw_badmy:     .null "IP address: four numbers, 0-255"
s_cw_badmask:   .null "Subnet mask: four numbers, 0-255"
s_cw_badgw:     .null "Gateway: four numbers, 0-255"
s_cw_baddns:    .null "DNS server: four numbers, 0-255"
s_cw_conn:      .null "Connecting to the server..."
s_lw_title:     .null "Sign On"
s_lw_name:      .null "Screen name:"
s_lw_pass:      .null "Password:"
s_lw_hint:      .null "Sign On, or New User to join."
s_lw_signon:    .null "Sign On"
s_lw_new:       .null "New User"
s_lw_back:      .null "Back"
