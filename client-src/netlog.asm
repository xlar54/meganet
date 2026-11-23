;=======================================================================================
; netlog.asm - the debug build's connection log (build.bat debug -> meganet-debug.d81,
; -D DEBUG_NET=1). For a member whose connection fails: what the client and mega-ip did,
; in a window, and saved as a SEQ file on drive 8.
;
; Two parts:
;   the recorder, at NL_HI (the RAM under the KERNAL after the gadget texts: the debug
;     build has 60 gadgets, not 80). Copied there at boot by nl_install. The resident code
;     calls it (all .if DEBUG_NET):
;       nl_frame   main.asm, once a frame: the clock; net_state and login_state changes;
;                  a copy of mega-ip's variables (two DMAs from bank 4) and its TCP state,
;                  resends and the peer's window; opens the log after a failure
;       nl_event   main.asm on_event: F1 opens the log; the log window's buttons
;       nl_rx      proto.asm proto_feed: a whole frame arrived
;       nl_tx      proto.asm tx_end, nl_txt the multi-line C.TEXT: a frame going out
;       nl_fail    net.asm net_fail: the error, the state, the poll result (tmp0); keeps a
;                  copy of mega-ip's variables as they were then
;       nl_stall   net.asm net_send: mega-ip's send queue refused a byte
;   the window (this overlay, OVL_DEBUG): nl_show, nl_ev, nl_save.
;
; The last NL_N events are kept: time (tenths of a second since boot), kind, a, b, c.
; The window shows the header and as many of the newest as its view holds (64 lines); the
; file has them all, ASCII with CR LF line ends ("MEGANET-LOG", replaced each time).
;=======================================================================================

NW              = $f3                   ; the log window
NG_VIEW         = 1
NG_STATUS       = 2
NG_SAVE         = 3
NG_OK           = 4

NL_HI           = GUI_TBUF + GUI_MAXGAD * 64
NL_N            = 64                    ; events kept (a power of two)

NK_RX           = 1                     ; a = type ($ff: too big, skipped), b = length,
NK_TX           = 2                     ;   c = the first two payload bytes
NK_NET          = 3                     ; a = net_state, b = net_err, c = net_was
NK_LOGIN        = 4                     ; a = login_state
NK_FAIL         = 5                     ; a = error, b = net_state / poll result, c = tcp state
NK_TCP          = 6                     ; a = mega-ip TCP_STATE, b = ETH_STATE, c = queued
NK_RETRY        = 7                     ; a = tries left, b = unacked, c = peer window
NK_WIN          = 8                     ; a = 1 the peer's window closed / 0 open, b = window,
                                        ;   c = queued
NK_START        = 9

; mega-ip's variables: two blocks, copied side by side into nl_snap
MB_A            = MIPV_LOCAL_IP
MB_A_LEN        = MIPV_LOCAL_ISN + 4 - MB_A
MB_B            = MIPV_TXQ_HEAD
MB_B_LEN        = MIPV_TCP_PEER_MAC + 6 - MB_B
NL_SNAPN        = MB_A_LEN + MB_B_LEN
        .cerror NL_SNAPN > 127, "mega-ip's variables: too many to copy"
OA              .function name
                .endf name - MB_A
OB              .function name
                .endf MB_A_LEN + name - MB_B
O_LOCAL_IP      = OA(MIPV_LOCAL_IP)
O_LOCAL_PORT    = OA(MIPV_LOCAL_PORT)
O_REMOTE_IP     = OA(MIPV_REMOTE_IP)
O_REMOTE_PORT   = OA(MIPV_REMOTE_PORT)
O_GATEWAY_IP    = OA(MIPV_GATEWAY_IP)
O_SUBNET_MASK   = OA(MIPV_SUBNET_MASK)
O_ETH_STATE     = OA(MIPV_ETH_STATE)
O_TCP_STATE     = OA(MIPV_TCP_STATE)
O_REMOTE_ISN    = OA(MIPV_REMOTE_ISN)
O_LOCAL_ISN     = OA(MIPV_LOCAL_ISN)
O_TXQ_COUNT     = OB(MIPV_TXQ_COUNT)
O_TXQ_INFLIGHT  = OB(MIPV_TXQ_INFLIGHT)
O_PEER_WINDOW   = OB(MIPV_TX_PEER_WINDOW)
O_SEG_WND       = OB(MIPV_SEG_WND)
O_RT_PENDING    = OB(MIPV_TX_UNACK_PENDING)
O_RT_LEFT       = OB(MIPV_TX_UNACK_RETRY_LEFT)
O_UNACK_SEQ     = OB(MIPV_TX_UNACK_SEQ)
O_MAC_VALID     = OB(MIPV_TCP_PEER_MAC_VALID)
O_MAC           = OB(MIPV_TCP_PEER_MAC)

;=======================================================================================
; the overlay: installing the recorder, the window, saving
;=======================================================================================
nl_install:
        lda #<nl_image
        sta ptr1
        lda #>nl_image
        sta ptr1+1
        lda #<NL_HI
        sta ptr2
        lda #>NL_HI
        sta ptr2+1
        lda #0
        sta ptr1+2
        sta ptr1+3
        sta ptr2+2
        sta ptr2+3
        lda #<(nl_image_end - nl_image)
        sta tmp5
        lda #>(nl_image_end - nl_image)
        sta tmp5+1
        jsr dma_copy_far
        lda frame_count
        sta nl_lastf
        lda #NK_START
        jmp nl_addz

; open (or fill again) the log window
nl_show:
        #GUI_WIN NW, 36, 10, 568, 174, GWF_CLOSE | GWF_MOVABLE, s_nl_title
        #GUI_GAD NW, NG_VIEW, GK_VIEW, 2, 2, 556, 130, 0, 0, 0
        #GUI_GAD NW, NG_STATUS, GK_LABEL, 4, 140, 368, 10, 0, 0, s_nl_hint
        #GUI_GAD NW, NG_SAVE, GK_BUTTON, 378, 136, 84, 16, 0, 0, s_nl_save
        #GUI_GAD NW, NG_OK, GK_BUTTON, 470, 136, 84, 16, GGF_DEFAULT, 0, s_nl_ok
        lda #0
        sta nl_mode
        jsr nl_fill
        lda #NW
        jmp gui_win_show

; a click or the close box in the log window
nl_ev:
        lda ge_type
        cmp #GE_CLOSE
        beq _close
        lda ge_gid
        cmp #NG_SAVE
        beq nl_save
        cmp #NG_OK
        bne _out
_close: lda #NW
        jmp gui_win_close
_out:   rts

; the whole log -> "MEGANET-LOG" on drive 8 (any old one replaced)
nl_save:
        lda #8
        sta kst_dev
        jsr disk_begin
        jsr kst_status
        cmp #74                         ; (no drive)
        beq _said
        lda #<s_nl_fname
        ldx #>s_nl_fname
        jsr kst_remove
        lda #<s_nl_fname
        ldx #>s_nl_fname
        ldy #0
        jsr kst_name_raw
        lda #<s_nl_sw
        ldx #>s_nl_sw
        jsr kst_name_raw
        phy
        lda #2
        sta kst_sa
        pla
        jsr kst_open
        bcs _fail
        lda #1
        sta nl_mode
        jsr nl_fill
        jsr kst_close
        jsr kst_status
        cmp #20
        bcs _said
        lda nl_werr
        bne _said
        jsr disk_end
        lda #<s_nl_saved
        ldx #>s_nl_saved
        bra _status
_fail:  jsr kst_close
        jsr kst_status
_said:  jsr disk_end                    ; what the drive said
        lda #0
        sta nl_lp
        lda #<s_nl_drive
        ldx #>s_nl_drive
        jsr put_s
        ldx #0
-       lda KS_BUF,x
        beq +
        jsr put_c
        inx
        cpx #40
        bne -
+       ldy nl_lp
        lda #0
        sta nl_line,y
        lda #<nl_line
        ldx #>nl_line
_status:
        sta gp_text
        stx gp_text+1
        lda #NW
        sta gp_win
        lda #NG_STATUS
        sta gp_gid
        jmp gui_set_text

;---------------------------------------------------------------------------------------
; the lines: the header, then the events, each to nl_emit (nl_mode 0: the view, 1: the file)
;---------------------------------------------------------------------------------------
nl_fill:
        lda #0
        sta nl_hn
        sta nl_lp
        sta nl_werr
        jsr nl_header
        lda nl_hn                       ; header lines: the view keeps 64 lines in all
        sta nl_hdr
        lda nl_total+1                  ; how many events are kept
        bne _full
        lda nl_total
        cmp #NL_N
        bcc _cnt
_full:  lda #NL_N
_cnt:   sta nl_cnt
        lda #0
        sta nl_skip
        lda nl_mode
        bne _go
        lda #64                         ; the view: only the newest that fit
        sec
        sbc nl_hdr
        sta nl_room
        lda nl_cnt
        sec
        sbc nl_room
        bcc _go
        sta nl_skip
_go:    lda nl_head                     ; the first: head - count + skip
        sec
        sbc nl_cnt
        clc
        adc nl_skip
        and #NL_N - 1
        sta nl_ix
        lda nl_cnt
        sec
        sbc nl_skip
        sta nl_left
        beq _done
_ev:    jsr nl_event_line
        jsr nl_emit
        lda nl_ix
        inc a
        and #NL_N - 1
        sta nl_ix
        dec nl_left
        bne _ev
_done:  rts

; the line so far -> the view or the file
nl_emit:
        ldy nl_lp
        lda #0
        sta nl_line,y
        lda nl_mode
        bne _file
        lda #<nl_line
        sta txt_ptr
        lda #>nl_line
        sta txt_ptr+1
        lda #NW
        ldx #NG_VIEW
        jsr gui_view_append
        bra _next
_file:  lda nl_werr
        bne _next
        ldx #0
-       cpx nl_lp
        beq +
        lda nl_line,x
        sta KS_BUF,x
        inx
        bra -
+       lda #13
        sta KS_BUF,x
        inx
        lda #10
        sta KS_BUF,x
        inx
        stx kst_count
        jsr kst_write
        lda kst_st
        sta nl_werr
_next:  lda #0
        sta nl_lp
        inc nl_hn
        rts

nl_header:
        lda #<s_h_title                 ; the build and the time
        ldx #>s_h_title
        jsr put_s
        lda #<CLIENT_BUILD
        ldx #>CLIENT_BUILD
        jsr put_d16
        lda #<s_h_now
        ldx #>s_h_now
        jsr put_s
        lda nl_t
        ldx nl_t+1
        jsr put_time
        lda #'s'
        jsr put_c
        jsr nl_emit
        lda #<s_h_server                ; the server
        ldx #>s_h_server
        jsr put_s
        lda #<login_ip
        ldx #>login_ip
        jsr put_ip
        lda #<s_h_port
        ldx #>s_h_port
        jsr put_s
        lda #<SERVER_PORT
        ldx #>SERVER_PORT
        jsr put_d16
        jsr nl_emit
        lda #<s_h_net                   ; the client's state
        ldx #>s_h_net
        jsr put_s
        lda net_state
        jsr put_netname
        lda #<s_h_err
        ldx #>s_h_err
        jsr put_s
        lda net_err
        jsr put_d8
        lda #<s_h_fails
        ldx #>s_h_fails
        jsr put_s
        lda nl_fails
        jsr put_d8
        jsr nl_emit
        lda #<s_h_sent                  ; the totals
        ldx #>s_h_sent
        jsr put_s
        lda nl_txm
        ldx nl_txm+1
        jsr put_d16
        lda #<s_h_msgs
        ldx #>s_h_msgs
        jsr put_s
        ldx #2
-       lda nl_txb,x
        sta nv,x
        dex
        bpl -
        jsr put_d24
        lda #<s_h_full
        ldx #>s_h_full
        jsr put_s
        lda nl_stalls
        ldx nl_stalls+1
        jsr put_d16
        jsr nl_emit
        lda #<s_h_rcvd
        ldx #>s_h_rcvd
        jsr put_s
        lda nl_rxm
        ldx nl_rxm+1
        jsr put_d16
        lda #<s_h_msgs
        ldx #>s_h_msgs
        jsr put_s
        ldx #2
-       lda nl_rxb,x
        sta nv,x
        dex
        bpl -
        jsr put_d24
        lda #<s_h_bytes
        ldx #>s_h_bytes
        jsr put_s
        jsr nl_emit
        lda nl_fails                    ; mega-ip: at the last failure, and now
        beq _now
        ldx #NL_SNAPN - 1
-       lda nl_frozen,x
        sta nl_work,x
        dex
        bpl -
        lda #<s_h_atfail
        ldx #>s_h_atfail
        jsr nl_block
_now:   ldx #NL_SNAPN - 1
-       lda nl_snap,x
        sta nl_work,x
        dex
        bpl -
        lda #<s_h_mipnow
        ldx #>s_h_mipnow
        jsr nl_block
        lda #<s_h_events
        ldx #>s_h_events
        jsr put_s
        lda nl_total
        ldx nl_total+1
        jsr put_d16
        lda #<s_h_inall
        ldx #>s_h_inall
        jsr put_s
        jmp nl_emit

; A/X = the block's title: mega-ip's variables in nl_work
nl_block:
        jsr put_s
        jsr nl_emit
        lda #<s_b_us                    ; addresses
        ldx #>s_b_us
        jsr put_s
        lda #<(nl_work + O_LOCAL_IP)
        ldx #>(nl_work + O_LOCAL_IP)
        jsr put_ip
        lda #<s_b_gw
        ldx #>s_b_gw
        jsr put_s
        lda #<(nl_work + O_GATEWAY_IP)
        ldx #>(nl_work + O_GATEWAY_IP)
        jsr put_ip
        lda #<s_b_mask
        ldx #>s_b_mask
        jsr put_s
        lda #<(nl_work + O_SUBNET_MASK)
        ldx #>(nl_work + O_SUBNET_MASK)
        jsr put_ip
        jsr nl_emit
        lda #<s_b_tcp                   ; states, our port
        ldx #>s_b_tcp
        jsr put_s
        lda nl_work + O_TCP_STATE
        jsr put_tcpname
        lda #<s_b_open
        ldx #>s_b_open
        jsr put_s
        lda nl_work + O_TCP_STATE
        jsr put_h8
        lda #<s_b_eth
        ldx #>s_b_eth
        jsr put_s
        lda nl_work + O_ETH_STATE
        jsr put_h8
        lda #<s_b_port
        ldx #>s_b_port
        jsr put_s
        lda nl_work + O_LOCAL_PORT + 1  ; (big-endian)
        ldx nl_work + O_LOCAL_PORT
        jsr put_d16
        jsr nl_emit
        lda #<s_b_peer                  ; the peer
        ldx #>s_b_peer
        jsr put_s
        lda #<(nl_work + O_REMOTE_IP)
        ldx #>(nl_work + O_REMOTE_IP)
        jsr put_ip
        lda #':'
        jsr put_c
        lda nl_work + O_REMOTE_PORT + 1
        ldx nl_work + O_REMOTE_PORT
        jsr put_d16
        lda #<s_b_mac
        ldx #>s_b_mac
        jsr put_s
        lda nl_work + O_MAC_VALID
        bne +
        lda #<s_b_nomac
        ldx #>s_b_nomac
        jsr put_s
        bra _mac
+       ldx #0
-       lda nl_work + O_MAC,x
        jsr put_h8
        inx
        cpx #6
        bne -
_mac:   jsr nl_emit
        lda #<s_b_queued                ; the send queue and the windows
        ldx #>s_b_queued
        jsr put_s
        lda nl_work + O_TXQ_COUNT
        ldx nl_work + O_TXQ_COUNT + 1
        jsr put_d16
        lda #<s_b_unacked
        ldx #>s_b_unacked
        jsr put_s
        lda nl_work + O_TXQ_INFLIGHT
        ldx nl_work + O_TXQ_INFLIGHT + 1
        jsr put_d16
        lda #<s_b_pwin
        ldx #>s_b_pwin
        jsr put_s
        lda nl_work + O_PEER_WINDOW
        ldx nl_work + O_PEER_WINDOW + 1
        jsr put_d16
        lda #<s_b_swin
        ldx #>s_b_swin
        jsr put_s
        lda nl_work + O_SEG_WND
        ldx nl_work + O_SEG_WND + 1
        jsr put_d16
        jsr nl_emit
        lda #<s_b_resend                ; resending
        ldx #>s_b_resend
        jsr put_s
        lda nl_work + O_RT_PENDING
        beq +
        lda #<s_b_on
        ldx #>s_b_on
        bra ++
+       lda #<s_b_off
        ldx #>s_b_off
+       jsr put_s
        lda #<s_b_left
        ldx #>s_b_left
        jsr put_s
        lda nl_work + O_RT_LEFT
        jsr put_d8
        lda #'/'
        jsr put_c
        lda #MIPV_TCP_TX_MAX_RETRIES
        jsr put_d8
        jsr nl_emit
        lda #<s_b_una                   ; sequence numbers (as stored: network order)
        ldx #>s_b_una
        jsr put_s
        ldx #O_UNACK_SEQ
        jsr put_h32
        lda #<s_b_nxt
        ldx #>s_b_nxt
        jsr put_s
        ldx #O_LOCAL_ISN
        jsr put_h32
        lda #<s_b_rcv
        ldx #>s_b_rcv
        jsr put_s
        ldx #O_REMOTE_ISN
        jsr put_h32
        jmp nl_emit

; event nl_ix -> the line
nl_event_line:
        ldx nl_ix
        lda ev_k,x
        sta e_k
        lda ev_a,x
        sta e_a
        lda ev_bl,x
        sta e_b
        lda ev_bh,x
        sta e_b+1
        lda ev_cl,x
        sta e_c
        lda ev_ch,x
        sta e_c+1
        lda #' '
        jsr put_c
        lda ev_tl,x
        pha
        lda ev_th,x
        tax
        pla
        jsr put_time
        lda #' '
        jsr put_c
        lda e_k
        cmp #NK_RX
        beq _rx
        cmp #NK_TX
        beq _tx
        cmp #NK_NET
        beq _net
        cmp #NK_LOGIN
        beq _login
        cmp #NK_FAIL
        bne +
        jmp _fail
+       cmp #NK_TCP
        bne +
        jmp _tcp
+       cmp #NK_RETRY
        bne +
        jmp _retry
+       cmp #NK_WIN
        bne +
        jmp _win
+       lda #<s_e_start
        ldx #>s_e_start
        jmp put_s
_rx:    lda #<s_e_rx
        ldx #>s_e_rx
        bra _msg
_tx:    lda #<s_e_tx
        ldx #>s_e_tx
_msg:   jsr put_s
        lda e_a
        cmp #$ff
        bne +
        lda #<s_e_big
        ldx #>s_e_big
        jsr put_s
        bra _len
+       jsr put_h8
        lda #' '
        jsr put_c
        lda e_a
        jsr put_msgname
_len:   lda #<s_e_len
        ldx #>s_e_len
        jsr put_s
        lda e_b
        ldx e_b+1
        jsr put_d16
        lda e_a
        cmp #$ff
        beq _out
        lda #<s_e_data
        ldx #>s_e_data
        jsr put_s
        lda e_c
        jsr put_h8
        lda #' '
        jsr put_c
        lda e_c+1
        jsr put_h8
        lda #']'
        jmp put_c
_out:   rts
_net:   lda #<s_e_net
        ldx #>s_e_net
        jsr put_s
        lda e_a
        jmp put_netname
_login: lda #<s_e_login
        ldx #>s_e_login
        jsr put_s
        lda e_a
        cmp #5
        bcc +
        lda #5
+       tax
        lda ls_lo,x
        pha
        lda ls_hi,x
        tax
        pla
        jmp put_s
_fail:  lda #<s_e_fail
        ldx #>s_e_fail
        jsr put_s
        ldx e_a
        cpx #6
        bcc +
        ldx #0
+       lda err_lo,x
        pha
        lda err_hi,x
        tax
        pla
        jsr put_s
        lda #<s_e_in
        ldx #>s_e_in
        jsr put_s
        lda e_b
        jsr put_netname
        lda #<s_e_poll
        ldx #>s_e_poll
        jsr put_s
        lda e_b+1
        jsr put_h8
        lda #')'
        jmp put_c
_tcp:   lda #<s_e_tcp
        ldx #>s_e_tcp
        jsr put_s
        lda e_a
        jsr put_tcpname
        lda #<s_e_eth
        ldx #>s_e_eth
        jsr put_s
        lda e_b
        jsr put_h8
        lda #<s_e_queued
        ldx #>s_e_queued
        jsr put_s
        lda e_c
        ldx e_c+1
        jsr put_d16
        lda #')'
        jmp put_c
_retry: lda #<s_e_retry
        ldx #>s_e_retry
        jsr put_s
        lda e_a
        jsr put_d8
        lda #<s_e_rleft
        ldx #>s_e_rleft
        jsr put_s
        lda e_b
        ldx e_b+1
        jsr put_d16
        lda #<s_e_rwin
        ldx #>s_e_rwin
        jsr put_s
        lda e_c
        ldx e_c+1
        jsr put_d16
        lda #')'
        jmp put_c
_win:   lda e_a
        beq +
        lda #<s_e_wclosed
        ldx #>s_e_wclosed
        jsr put_s
        lda e_c
        ldx e_c+1
        jsr put_d16
        lda #')'
        jmp put_c
+       lda #<s_e_wopen
        ldx #>s_e_wopen
        jsr put_s
        lda e_b
        ldx e_b+1
        jmp put_d16

;---------------------------------------------------------------------------------------
; text into nl_line (nl_lp: its length so far)
;---------------------------------------------------------------------------------------
put_c:  ldy nl_lp                       ; A (keeps X)
        cpy #NL_LINEMAX
        bcs +
        sta nl_line,y
        inc nl_lp
+       rts
put_s:  sta txt_ptr                     ; A/X = a zero-terminated string
        stx txt_ptr+1
-       ldy #0
        lda (txt_ptr),y
        beq +
        jsr put_c
        inw txt_ptr
        bra -
+       rts
put_h8: pha                             ; A as two hex digits (keeps X)
        lsr
        lsr
        lsr
        lsr
        jsr _dig
        pla
        and #$0f
_dig:   cmp #10
        bcc +
        adc #6                          ; (carry set: + 7)
+       adc #'0'
        jmp put_c
put_h32: lda #4                         ; nl_work,x: four bytes as hex
        sta nl_i
-       lda nl_work,x
        jsr put_h8
        inx
        dec nl_i
        bne -
        rts
put_d8: ldx #0                          ; A as decimal
put_d16: sta nv                         ; A/X
        stx nv+1
        lda #0
        sta nv+2
put_d24: ldx #0                         ; nv (3 bytes)
_dig:   jsr nl_div10
        lda nl_rem
        ora #'0'
        sta nl_digs,x
        inx
        lda nv
        ora nv+1
        ora nv+2
        bne _dig
_out:   dex
        lda nl_digs,x
        jsr put_c
        cpx #0
        bne _out
        rts
; nv / 10 -> nv, the remainder -> nl_rem
nl_div10:
        lda #0
        sta nl_rem
        ldy #24
-       asl nv
        rol nv+1
        rol nv+2
        rol nl_rem
        lda nl_rem
        cmp #10
        bcc +
        sbc #10
        sta nl_rem
        inc nv
+       dey
        bne -
        rts
; A/X = tenths of a second: "12.3"
put_time:
        sta nv
        stx nv+1
        lda #0
        sta nv+2
        jsr nl_div10
        lda nl_rem
        pha
        jsr put_d24
        lda #'.'
        jsr put_c
        pla
        ora #'0'
        jmp put_c
; A/X = 4 bytes: "a.b.c.d"
put_ip: sta tmp6
        stx tmp6+1
        lda #0
        sta nl_i
-       ldy nl_i
        lda (tmp6),y
        jsr put_d8
        inc nl_i
        lda nl_i
        cmp #4
        beq +
        lda #'.'
        jsr put_c
        bra -
+       rts
put_netname:                            ; A = net_state
        cmp #6
        bcc +
        lda #6
+       tax
        lda ns_lo,x
        pha
        lda ns_hi,x
        tax
        pla
        jmp put_s
put_tcpname:                            ; A = mega-ip's TCP_STATE
        cmp #11
        bcc +
        lda #11
+       tax
        lda ts_lo,x
        pha
        lda ts_hi,x
        tax
        pla
        jmp put_s
put_msgname:                            ; A = a message type (nothing if it isn't known)
        ldx #0
-       cmp nlm_type,x
        beq +
        inx
        cpx #nlm_n
        bne -
        rts
+       lda nlm_lo,x
        pha
        lda nlm_hi,x
        tax
        pla
        jmp put_s

NL_LINEMAX      = 70
nl_line:        .fill NL_LINEMAX + 1
nl_lp:          .byte 0
nl_mode:        .byte 0                 ; 0 the view, 1 the file
nl_werr:        .byte 0                 ; a write failed (the KERNAL status)
nl_hn:          .byte 0                 ; lines made
nl_hdr:         .byte 0
nl_cnt:         .byte 0
nl_skip:        .byte 0
nl_room:        .byte 0
nl_ix:          .byte 0
nl_left:        .byte 0
nl_i:           .byte 0
nl_rem:         .byte 0
nv:             .fill 3
nl_digs:        .fill 8
e_k:            .byte 0
e_a:            .byte 0
e_b:            .word 0
e_c:            .word 0
nl_work:        .fill NL_SNAPN

ns_lo:  .byte <s_ns0, <s_ns1, <s_ns2, <s_ns3, <s_ns4, <s_ns5, <s_q
ns_hi:  .byte >s_ns0, >s_ns1, >s_ns2, >s_ns3, >s_ns4, >s_ns5, >s_q
s_ns0:  .null "off"
s_ns1:  .null "DHCP"
s_ns2:  .null "ready"
s_ns3:  .null "connecting"
s_ns4:  .null "online"
s_ns5:  .null "FAILED"
s_q:    .null "?"
ls_lo:  .byte <s_ls0, <s_ls1, <s_ls2, <s_ls3, <s_ls4, <s_q
ls_hi:  .byte >s_ls0, >s_ls1, >s_ls2, >s_ls3, >s_ls4, >s_q
s_ls0:  .null "Connect window"
s_ls1:  .null "connecting"
s_ls2:  .null "waiting for the server (sign-on or sign-up)"
s_ls3:  .null "signed on"
s_ls4:  .null "Sign On window"
ts_lo:  .byte <s_ts0, <s_q, <s_ts2, <s_ts3, <s_ts4, <s_ts5, <s_ts6, <s_ts7, <s_q, <s_ts9
        .byte <s_ts10, <s_q
ts_hi:  .byte >s_ts0, >s_q, >s_ts2, >s_ts3, >s_ts4, >s_ts5, >s_ts6, >s_ts7, >s_q, >s_ts9
        .byte >s_ts10, >s_q
s_ts0:  .null "CLOSED"
s_ts2:  .null "SYN_SENT"
s_ts3:  .null "SYN_RECEIVED"
s_ts4:  .null "ESTABLISHED"
s_ts5:  .null "FIN_WAIT_1"
s_ts6:  .null "FIN_WAIT_2"
s_ts7:  .null "CLOSE_WAIT"
s_ts9:  .null "LAST_ACK"
s_ts10: .null "TIME_WAIT"

nlm_type:
        .byte S_HELLO, S_LOGIN_RESULT, S_WIN_OPEN, S_WIN_CLOSE, S_GADGET, S_SET_TEXT
        .byte S_SET_VALUE, S_LIST_ROWS, S_APPEND, S_FOCUS, S_MENU, S_ALERT, S_WIN_DONE
        .byte S_NOTIFY, S_PONG, S_SET_FLAGS, S_TOAST, S_DESK_ICON, S_BROADCAST, S_SOUND
        .byte S_CELLS, S_RESOURCE
        .byte C_HELLO, C_CLICK, C_VALUE, C_SELECT, C_MENU_PICK, C_WIN_CLOSED, C_KEY
        .byte C_LOGIN, C_NOTIFY_CLICK, C_TEXT, C_DESK_OPEN, C_PING
nlm_n = * - nlm_type
nlm_names = ["HELLO", "LOGIN_RESULT", "WIN_OPEN", "WIN_CLOSE", "GADGET", "SET_TEXT"]
nlm_names2 = ["SET_VALUE", "LIST_ROWS", "APPEND", "FOCUS", "MENU", "ALERT", "WIN_DONE"]
nlm_names3 = ["NOTIFY", "PONG", "SET_FLAGS", "TOAST", "DESK_ICON", "BROADCAST", "SOUND"]
nlm_names4 = ["CELLS", "RESOURCE"]
nlm_names5 = ["HELLO", "CLICK", "VALUE", "SELECT", "MENU_PICK", "WIN_CLOSED", "KEY"]
nlm_names6 = ["LOGIN", "NOTIFY_CLICK", "TEXT", "DESK_OPEN", "PING"]
nlm_all = nlm_names .. nlm_names2 .. nlm_names3 .. nlm_names4 .. nlm_names5 .. nlm_names6
        .cerror len(nlm_all) != nlm_n, "the message names don't match the types"
nlm_text:
        .for _n in nlm_all
        .null _n
        .endfor
nlm_ofs := [0]
        .for _i in range(len(nlm_all) - 1)
nlm_ofs := nlm_ofs .. [nlm_ofs[-1] + len(nlm_all[_i]) + 1]
        .endfor
nlm_lo:  .byte <(nlm_text + nlm_ofs)
nlm_hi:  .byte >(nlm_text + nlm_ofs)

s_nl_title:     .null "Connection Log (debug build)"
s_nl_hint:      .null "F1 opens this. Save: MEGANET-LOG on drive 8."
s_nl_save:      .null "Save"
s_nl_ok:        .null "OK"
s_nl_fname:     .null "MEGANET-LOG"
s_nl_sw:        .null ",S,W"
s_nl_saved:     .null "Saved as MEGANET-LOG on drive 8."
s_nl_drive:     .null "Drive 8: "
s_h_title:      .null "MegaNet connection log, client build "
s_h_now:        .null ", now "
s_h_server:     .null "Server "
s_h_port:       .null " port "
s_h_net:        .null "Network: "
s_h_err:        .null ", error "
s_h_fails:      .null ", failures "
s_h_sent:       .null "Sent "
s_h_rcvd:       .null "Received "
s_h_msgs:       .null " messages, bytes "
s_h_full:       .null ", queue full "
s_h_bytes:      .null ""
s_h_atfail:     .null "mega-ip at the last failure:"
s_h_mipnow:     .null "mega-ip now:"
s_h_events:     .null "Events, oldest first (seconds since boot; "
s_h_inall:      .null " in all):"
s_b_us:         .null "  us "
s_b_gw:         .null ", gateway "
s_b_mask:       .null ", mask "
s_b_tcp:        .null "  tcp "
s_b_open:       .null " ($"
s_b_eth:        .null "), eth $"
s_b_port:       .null ", our port "
s_b_peer:       .null "  peer "
s_b_mac:        .null ", MAC "
s_b_nomac:      .null "not known"
s_b_queued:     .null "  queued "
s_b_unacked:    .null ", unacked "
s_b_pwin:       .null ", peer window "
s_b_swin:       .null ", last "
s_b_resend:     .null "  resend timer "
s_b_on:         .null "on"
s_b_off:        .null "off"
s_b_left:       .null ", tries left "
s_b_una:        .null "  snd.una "
s_b_nxt:        .null " snd.nxt "
s_b_rcv:        .null " rcv.nxt "
s_e_start:      .null "log started"
s_e_rx:         .null "rx "
s_e_tx:         .null "tx "
s_e_big:        .null "(too big: skipped)"
s_e_len:        .null " len "
s_e_data:       .null " ["
s_e_net:        .null "network: "
s_e_login:      .null "screen: "
s_e_fail:       .null "FAILED: "
s_e_in:         .null " (in "
s_e_poll:       .null ", poll $"
s_e_tcp:        .null "tcp: "
s_e_eth:        .null " (eth $"
s_e_queued:     .null ", queued "
s_e_retry:      .null "tcp: resent, tries left "
s_e_rleft:      .null " (unacked "
s_e_rwin:       .null ", peer window "
s_e_wclosed:    .null "tcp: the peer's window is closed (queued "
s_e_wopen:      .null "tcp: the peer's window is open: "

;=======================================================================================
; the recorder: copied to NL_HI by nl_install
;=======================================================================================
nl_image:
        .logical NL_HI
nl_frame:
        lda frame_count                 ; the clock: tenths of a second (5 frames each)
        sec
        sbc nl_lastf
        clc
        adc nl_acc
        sta nl_acc
        lda frame_count
        sta nl_lastf
_tick:  lda nl_acc
        cmp #5
        bcc _states
        sbc #5
        sta nl_acc
        inc nl_t
        bne _tick
        inc nl_t+1
        bra _tick
_states:
        lda net_state                   ; the client's states
        cmp nl_ns
        beq +
        sta nl_ns
        sta nl_a
        lda net_err
        sta nl_b
        lda net_was
        sta nl_c
        lda #NK_NET
        jsr nl_addz
+       lda login_state
        cmp nl_ls
        beq +
        sta nl_ls
        sta nl_a
        lda #NK_LOGIN
        jsr nl_addz
+       lda net_state                   ; mega-ip, while it's working (after a failure the
        beq _open                       ; last copy stays)
        cmp #NS_FAILED
        beq _open
        lda #>nl_dma_a
        sta DMA_ADDRMSB
        lda #<nl_dma_a
        sta DMA_ADDRLSB_ETRIG
        lda #>nl_dma_b
        sta DMA_ADDRMSB
        lda #<nl_dma_b
        sta DMA_ADDRLSB_ETRIG
        lda nl_snap + O_TCP_STATE       ; its TCP state
        cmp nl_ptcp
        beq _resend
        sta nl_ptcp
        sta nl_a
        lda nl_snap + O_ETH_STATE
        sta nl_b
        lda #0
        sta nl_b+1
        lda nl_snap + O_TXQ_COUNT
        sta nl_c
        lda nl_snap + O_TXQ_COUNT + 1
        sta nl_c+1
        lda #NK_TCP
        jsr nl_add
_resend:
        lda nl_snap + O_RT_LEFT         ; fewer tries left: a segment was sent again
        cmp nl_pleft
        beq _window
        sta nl_pleft
        bcs _window                     ; (more: a new segment's count)
        sta nl_a
        lda nl_snap + O_TXQ_INFLIGHT
        sta nl_b
        lda nl_snap + O_TXQ_INFLIGHT + 1
        sta nl_b+1
        lda nl_snap + O_PEER_WINDOW
        sta nl_c
        lda nl_snap + O_PEER_WINDOW + 1
        sta nl_c+1
        lda #NK_RETRY
        jsr nl_add
_window:
        lda nl_snap + O_TCP_STATE       ; the peer's window shut or open (when connected)
        cmp #4
        bne _open
        ldx #0
        lda nl_snap + O_PEER_WINDOW
        ora nl_snap + O_PEER_WINDOW + 1
        bne +
        inx
+       cpx nl_pzero
        beq _open
        stx nl_pzero
        stx nl_a
        lda nl_snap + O_PEER_WINDOW
        sta nl_b
        lda nl_snap + O_PEER_WINDOW + 1
        sta nl_b+1
        lda nl_snap + O_TXQ_COUNT
        sta nl_c
        lda nl_snap + O_TXQ_COUNT + 1
        sta nl_c+1
        lda #NK_WIN
        jsr nl_add
_open:  lda nl_pend                     ; a failure: the log opens over the Connect window
        beq _out
        lda login_state
        cmp #LS_CONNECT
        bne _out
        lda #0
        sta nl_pend
        lda #NW
        jsr gui_find_win
        bcc _out                        ; (open already)
        #FAR OVL_DEBUG, nl_show
_out:   rts

; on_event: F1, or the log window's clicks (then it returns from on_event itself)
nl_event:
        lda ge_type
        cmp #GE_KEY
        bne _win
        lda ge_key
        cmp #K_F1
        bne _no
        pla
        pla
        #FAR OVL_DEBUG, nl_show
        rts
_win:   cmp #GE_CLICK
        beq +
        cmp #GE_CLOSE
        bne _no
+       lda ge_win
        cmp #NW
        bne _no
        pla
        pla
        #FAR OVL_DEBUG, nl_ev
        rts
_no:    rts

; a whole frame arrived (proto_feed)
nl_rx:  inc nl_rxm
        bne +
        inc nl_rxm+1
+       clc
        lda nl_rxb
        adc pf_len
        sta nl_rxb
        lda nl_rxb+1
        adc pf_len+1
        sta nl_rxb+1
        bcc +
        inc nl_rxb+2
+       lda pf_len+1
        cmp #>PF_MAX
        bcc _kept
        lda #$ff                        ; (too big: proto_feed skips it)
        bra _type
_kept:  lda pf_buf
        cmp #S_PONG                     ; (counted, not listed)
        beq _out
_type:  sta nl_a
        lda pf_len
        sta nl_b
        lda pf_len+1
        sta nl_b+1
        lda pf_buf+1
        sta nl_c
        lda pf_buf+2
        sta nl_c+1
        lda #NK_RX
        jmp nl_add
_out:   rts

; a frame going out (tx_end: tx_buf = its length, type, payload)
nl_tx:  inc nl_txm
        bne +
        inc nl_txm+1
+       clc
        lda nl_txb
        adc tx_buf
        sta nl_txb
        bcc +
        inc nl_txb+1
        bne +
        inc nl_txb+2
+       lda tx_buf+2
        cmp #C_PING                     ; (counted, not listed)
        beq _out
        sta nl_a
        lda tx_buf
        sta nl_b
        lda #0
        sta nl_b+1
        lda tx_buf+3
        sta nl_c
        lda tx_buf+4
        sta nl_c+1
        lda #NK_TX
        jmp nl_add
_out:   rts

; C.TEXT (proto.asm: its length in pt_len)
nl_txt: inc nl_txm
        bne +
        inc nl_txm+1
+       clc
        lda nl_txb
        adc pt_len
        sta nl_txb
        lda nl_txb+1
        adc pt_len+1
        sta nl_txb+1
        bcc +
        inc nl_txb+2
+       lda #C_TEXT
        sta nl_a
        lda pt_len
        sta nl_b
        lda pt_len+1
        sta nl_b+1
        lda ge_win
        sta nl_c
        lda pt_gid
        sta nl_c+1
        lda #NK_TX
        jmp nl_add

; net_fail: A = the error (A, X and Y kept)
nl_fail:
        pha
        phx
        phy
        sta nl_a
        lda net_state
        sta nl_b
        lda tmp0                        ; (the poll's result: mega-ip's event bits)
        sta nl_b+1
        lda nl_snap + O_TCP_STATE
        sta nl_c
        lda #0
        sta nl_c+1
        lda #NK_FAIL
        jsr nl_add
        ldx #NL_SNAPN - 1               ; mega-ip as it was
-       lda nl_snap,x
        sta nl_frozen,x
        dex
        bpl -
        lda nl_fails
        cmp #$ff
        beq +
        inc nl_fails
+       lda #1
        sta nl_pend
        ply
        plx
        pla
        rts

nl_stall:
        inc nl_stalls
        bne +
        inc nl_stalls+1
+       rts

; A = kind: an event (nl_addz: with b and c's high bytes 0)
nl_addz:
        pha
        lda #0
        sta nl_b+1
        sta nl_c+1
        pla
nl_add: ldx nl_head
        sta ev_k,x
        lda nl_t
        sta ev_tl,x
        lda nl_t+1
        sta ev_th,x
        lda nl_a
        sta ev_a,x
        lda nl_b
        sta ev_bl,x
        lda nl_b+1
        sta ev_bh,x
        lda nl_c
        sta ev_cl,x
        lda nl_c+1
        sta ev_ch,x
        inx
        txa
        and #NL_N - 1
        sta nl_head
        inc nl_total
        bne +
        inc nl_total+1
+       rts

nl_dma_a:
        .byte DMAOPT_F018B, DMAOPT_SRC_MB, 0, DMAOPT_DST_MB, 0, DMAOPT_END
        .byte DMACMD_COPY
        .word MB_A_LEN
        .word MB_A                      ; bank 4 ($42000 is mega-ip's $2000)
        .byte 4
        .word nl_snap
        .byte 0
        .byte 0
        .word 0
nl_dma_b:
        .byte DMAOPT_F018B, DMAOPT_SRC_MB, 0, DMAOPT_DST_MB, 0, DMAOPT_END
        .byte DMACMD_COPY
        .word MB_B_LEN
        .word MB_B
        .byte 4
        .word nl_snap + MB_A_LEN
        .byte 0
        .byte 0
        .word 0

nl_t:           .word 0                 ; tenths of a second since boot
nl_acc:         .byte 0
nl_lastf:       .byte 0
nl_ns:          .byte $ff               ; the last net_state, login_state, TCP state seen
nl_ls:          .byte $ff
nl_ptcp:        .byte $ff
nl_pleft:       .byte 0
nl_pzero:       .byte 0
nl_pend:        .byte 0                 ; 1: open the log (a failure)
nl_fails:       .byte 0
nl_a:           .byte 0
nl_b:           .word 0
nl_c:           .word 0
nl_rxm:         .word 0                 ; frames and bytes
nl_rxb:         .fill 3
nl_txm:         .word 0
nl_txb:         .fill 3
nl_stalls:      .word 0
nl_head:        .byte 0
nl_total:       .word 0
nl_snap:        .fill NL_SNAPN          ; mega-ip's variables, this frame
nl_frozen:      .fill NL_SNAPN          ; and at the last failure
ev_tl:          .fill NL_N
ev_th:          .fill NL_N
ev_k:           .fill NL_N
ev_a:           .fill NL_N
ev_bl:          .fill NL_N
ev_bh:          .fill NL_N
ev_cl:          .fill NL_N
ev_ch:          .fill NL_N
nl_hi_end:
        .cerror nl_hi_end > $fffa || nl_hi_end < NL_HI, format("the log's recorder runs into the vectors: to $%04x", nl_hi_end)
        .endlogical
nl_image_end:
