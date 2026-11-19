;=======================================================================================
; net.asm - the network for MegaNet: mega-ip after the takeover (weather65's method), as a
; state machine the main loop drives, so the GUI keeps running while DHCP and the
; connection happen.
;
; mega-ip (client-src/mega-ip, built to ETHBIN) is loaded at boot to $42000 and expects bank
; 4 at $2000-$7FFF. A trampoline below $2000 (NC_LOW) maps it in for each call, with
; interrupts off, and maps it out again. Registers pass straight through.
;
;   net_install     copy the trampoline (after #TAKEOVER)
;   net_start       self test, Ethernet reset (about 4 s, interrupts off), DHCP started.
;                   Carry set = failed (net_err). net_state -> NS_DHCP
;   net_connect     login_ip : SERVER_PORT. net_state -> NS_CONNECTING
;   net_wait_frame  instead of wait_frame while the network is up: polls the stack about
;                   5 times a frame (its timers need that) and passes what arrives to
;                   proto_feed. Moves net_state on: NS_READY once DHCP is done, NS_ONLINE
;                   when connected, NS_FAILED (net_err) when something goes wrong
;   net_send        A = a byte for the server. Carry set = failed
;   net_close       drop the connection (back to NS_READY)
;
; -D MOCK_NET=1 builds a replay version for Xemu, which has no network: DHCP and the
; connection succeed after a few frames, what the server sends comes from the MOCKRX file
; (a session recorded from the real server by private/tools/record_mock.py), and what the
; client sends is logged in attic at MOCK_TX (count in mock_txn) to compare with the
; recording.
;=======================================================================================

; mega-ip entry points, as seen with bank 4 mapped
MIP_INIT        = $2000
MIP_SET_LOCAL_PORT = $2009
MIP_SET_REMOTE_IP = $200c
MIP_SET_REMOTE_PORT = $200f
MIP_SET_XLATE   = $2015
MIP_DISCONNECT  = $2021
MIP_POLL        = $2024
MIP_CONN_START  = $2027
MIP_CONN_POLL   = $202a
MIP_DHCP_START  = $2042
MIP_DHCP_POLL   = $2045
MIP_GET_REMOTE_IP = $205a
MIP_GET_LOCAL_IP = $204e
MIP_FORCE_CLOSE = $205d
MIP_ABI_INFO    = $2060
MIP_SEND_BYTE   = $7600
MIP_RECV_BLOCK  = $7621
MIP_LOAD        = $42000
CONN_OK         = 1
CONN_BAD        = 2
DHCP_BOUND      = 4
DHCP_FAILED     = $7f

NC_LOW          = $1900                 ; the trampoline (below the MAP window)
RX_BUF          = $1e80                 ; a receive block (bank 0, below $2000; kstream has $1600-$1DFF)
RX_MAX          = 128

NS_OFF          = 0                     ; net_state
NS_DHCP         = 1
NS_READY        = 2
NS_CONNECTING   = 3
NS_ONLINE       = 4
NS_FAILED       = 5

E_NONE          = 0                     ; net_err
E_STACK         = 1
E_DHCP          = 2
E_CONN          = 3
E_SEND          = 4
E_LOST          = 5

net_state:      .byte 0
net_err:        .byte 0
net_was:        .byte 0                 ; the state before NS_FAILED
net_timer:      .word 0
net_last:       .byte 0
net_band:       .byte 0
net_wf:         .byte 0
net_rxn:        .byte 0
net_rxi:        .byte 0

; A/X/Y/Z = arguments: returns the routine's A/X/Y/Z
NET .macro addr
        pha
        lda #<\addr
        sta NC_JSR+1
        lda #>\addr
        sta NC_JSR+2
        pla
        jsr NC_LOW
.endmacro
NET_A .macro addr, a=0, x=0, y=0, z=0
        lda #<\addr
        sta NC_JSR+1
        lda #>\addr
        sta NC_JSR+2
        lda #\a
        ldx #\x
        ldy #\y
        ldz #\z
        jsr NC_LOW
.endmacro

; ---- the trampoline: copied to NC_LOW at boot ----
nc_image:
        .logical NC_LOW
        php
        sei
        sta nc_a
        stx nc_x
        sty nc_y
        tza
        sta nc_z
        lda #$00                        ; offset $40000 for blocks 1-3 ($2000-$7FFF)
        ldx #$e4
        ldy #$00
        ldz #$00
        map
        eom
        lda nc_z
        taz
        ldy nc_y
        ldx nc_x
        lda nc_a
NC_JSR: jsr $ffff
        sta nc_a
        stx nc_x
        sty nc_y
        tza
        sta nc_z
        lda #$00
        tax
        tay
        taz
        map
        eom
        lda nc_z
        taz
        ldy nc_y
        ldx nc_x
        lda nc_a
        plp
        rts
nc_a:   .byte 0
nc_x:   .byte 0
nc_y:   .byte 0
nc_z:   .byte 0
NC_END:
        .endlogical
NC_SIZE = NC_END - NC_LOW
        .cerror NC_END > RX_BUF, "the trampoline overlaps the receive block"

net_install:
        ldx #0
-       lda nc_image,x
        sta NC_LOW,x
        inx
        cpx #NC_SIZE
        bne -
        lda #NS_OFF
        sta net_state
        rts

; A = error: NS_FAILED (the state it failed in kept in net_was)
net_fail:                               ; A = the error (the first one stays: a send that
        pha                             ; fails after the connection is lost isn't E_SEND)
        lda net_state
        cmp #NS_FAILED
        bne +
        pla
        rts
+       sta net_was
        pla
        sta net_err
        lda #NS_FAILED
        sta net_state
        rts

; frames-based timers (A/X = frames)
net_timer_set:
        sta net_timer
        stx net_timer+1
        lda frame_count
        sta net_last
        rts
; carry set = expired
net_timer_tick:
        lda frame_count
        cmp net_last
        beq _no
        sta net_last
        lda net_timer
        bne +
        dec net_timer+1
+       dec net_timer
        lda net_timer
        ora net_timer+1
        beq _exp
_no:    clc
        rts
_exp:   sec
        rts

; wait for the next frame, keeping the network going
net_wait_frame:
        lda net_state
        cmp #NS_OFF
        beq _plain
        cmp #NS_FAILED
        beq _plain
        lda frame_count
        sta net_wf
-       jsr net_service
        jsr net_pace
        lda frame_count
        cmp net_wf
        beq -
        rts
_plain: jmp wait_frame

; about a fifth of a frame
net_pace:
        lda $d012
        and #$c0
        sta net_band
-       lda $d012
        and #$c0
        cmp net_band
        beq -
        rts

; our own address (from DHCP) -> net_myip (4 bytes). In the replay and bridge builds,
; which have no network of their own, a stand-in: 10.0.0.65
net_myip:       .fill 4
net_local_ip:
        .if MOCK_NET == 0 && BRIDGE_NET == 0
        #NET_A MIP_GET_LOCAL_IP
        sta net_myip
        stx net_myip+1
        sty net_myip+2
        tza
        sta net_myip+3
        .else
        lda #10
        sta net_myip
        lda #0
        sta net_myip+1
        sta net_myip+2
        lda #65
        sta net_myip+3
        .endif
        rts

        .if MOCK_NET == 0 && BRIDGE_NET == 0
;=======================================================================================
; the real network
;=======================================================================================
net_selftest:
        #NET_A MIP_ABI_INFO             ; a real answer from bank 4 proves the mapping
        cmp #1
        bne _bad
        cpx #0
        bne _bad
        cpy #1
        bne _bad
        cpz #1
        bne _bad
        clc
        rts
_bad:   sec
        rts

net_start:
        lda #E_NONE
        sta net_err
        jsr net_selftest
        bcc +
        lda #E_STACK
        jsr net_fail
        sec
        rts
+       #NET_A MIP_INIT                 ; about 4 s with interrupts off (PHY reset)
        #NET_A MIP_SET_XLATE, 0         ; binary: no PETSCII translation
        lda $d012                       ; a different local port each boot (the server
        eor $d7ef                       ; may still hold the last one in TIME_WAIT)
        and #$1f
        ora #$c0
        tax
        lda $d7ef
        eor frame_count
        sta tmp0
        txa
        ldx tmp0
        #NET MIP_SET_LOCAL_PORT
        #NET_A MIP_DHCP_START
        lda #<1500                      ; 30 s
        ldx #>1500
        jsr net_timer_set
        lda #NS_DHCP
        sta net_state
        clc
        rts

net_connect:
        lda login_ip+1
        sta tmp0
        lda login_ip+2
        tay
        lda login_ip+3
        taz
        ldx tmp0
        lda login_ip
        #NET MIP_SET_REMOTE_IP
        #NET_A MIP_SET_REMOTE_PORT, >SERVER_PORT, <SERVER_PORT
        #NET_A MIP_CONN_START
        lda #<750                       ; 15 s
        ldx #>750
        jsr net_timer_set
        lda #NS_CONNECTING
        sta net_state
        rts

net_close:
        #NET_A MIP_FORCE_CLOSE
        lda #NS_READY
        sta net_state
        rts

; one poll, and whatever the state needs
net_service:
        #NET_A MIP_POLL
        sta tmp0
        lda net_state
        cmp #NS_DHCP
        beq _dhcp
        cmp #NS_CONNECTING
        beq _conn
        cmp #NS_ONLINE
        beq _online
        rts
_dhcp:  #NET_A MIP_DHCP_POLL
        cmp #DHCP_BOUND
        beq _bound
        cmp #DHCP_FAILED
        beq _nodhcp
        jsr net_timer_tick
        bcs _nodhcp
        rts
_nodhcp:
        lda #E_DHCP
        jmp net_fail
_bound: #NET_A MIP_FORCE_CLOSE          ; as ansi-term does before its first connection
        lda #NS_READY
        sta net_state
        rts
_conn:  #NET_A MIP_CONN_POLL
        sta tmp0
        and #CONN_OK
        bne _up
        lda tmp0
        and #CONN_BAD
        bne _noconn
        jsr net_timer_tick
        bcs _noconn
        rts
_noconn:
        #NET_A MIP_FORCE_CLOSE
        lda #E_CONN
        jmp net_fail
_up:    lda #NS_ONLINE
        sta net_state
        jmp proto_reset
_online:
        lda tmp0                        ; an event (reset, FIN, timeout) or closed
        bne _lost
        lda #4                          ; up to 4 blocks a poll
        sta net_rxi
_blk:   lda #<RX_BUF
        ldx #>RX_BUF
        ldy #0
        ldz #RX_MAX
        #NET MIP_RECV_BLOCK
        cmp #0
        beq _out
        sta net_rxn
        ldx #0
-       phx
        lda RX_BUF,x
        jsr proto_feed
        plx
        inx
        cpx net_rxn
        bne -
        dec net_rxi
        bne _blk
_out:   rts
_lost:  #NET_A MIP_FORCE_CLOSE
        lda #E_LOST
        jmp net_fail

; A = byte to send; the queue can refuse it while it drains. Carry set = failed
net_send:
        sta net_sb
        lda net_state                   ; no connection: fail now, not after 5 s
        cmp #NS_ONLINE
        beq +
        sec
        rts
+       lda #<250
        ldx #>250
        jsr net_timer_set
_again: lda net_sb
        #NET MIP_SEND_BYTE
        cmp #1
        beq _sent
        #NET_A MIP_POLL
        jsr net_pace
        jsr net_timer_tick
        bcc _again
        lda #E_SEND
        jsr net_fail
        sec
        rts
_sent:  clc
        rts
net_sb: .byte 0

        .elsif BRIDGE_NET
;=======================================================================================
; the bridge version (Xemu, live): private/tools/xemu_bridge.py connects to Xemu's monitor
; and to the real server, and moves the bytes through two rings here. DHCP is pretended;
; "connecting" asks the bridge to open a TCP connection to the server.
;   BR_CTL+0 rx_w  (the bridge)   +1 rx_r  (the client)   - BR_RX, server -> client
;         +2 tx_w  (the client)   +3 tx_r  (the bridge)   - BR_TX, client -> server
;         +4 session (the client: 0 = no connection wanted, else a new number each connect)
;         +5 state (the bridge: 0 working on it, 1 connected, 2 can't connect, 3 closed)
;=======================================================================================
BR_RX           = $cd00                 ; (the top of bank 0's RAM, under the I/O at $D000;
BR_TX           = $ce00                 ; private/tools/xemu_bridge.py has the same three)
BR_CTL          = $cf00
br_session:     .byte 0

net_start:
        lda #E_NONE
        sta net_err
        lda #<25
        ldx #>25
        jsr net_timer_set
        lda #NS_DHCP
        sta net_state
        clc
        rts

net_connect:
        lda #0                          ; fresh rings, then a new session for the bridge
        sta BR_CTL
        sta BR_CTL+1
        sta BR_CTL+2
        sta BR_CTL+3
        sta BR_CTL+5
        lda br_session                  ; a new number: random the first time, so a re-run
        bne +                           ; client never repeats the bridge's last one
        lda HWRNG
        eor $d012
        sta br_session
+       inc br_session
        bne +
        inc br_session
+       lda br_session
        sta BR_CTL+4
        lda #<750                       ; 15 s
        ldx #>750
        jsr net_timer_set
        lda #NS_CONNECTING
        sta net_state
        rts

net_close:
        lda #0
        sta BR_CTL+4
        lda #NS_READY
        sta net_state
        rts

net_service:
        lda net_state
        cmp #NS_DHCP
        beq _dhcp
        cmp #NS_CONNECTING
        beq _conn
        cmp #NS_ONLINE
        beq _online
        rts
_dhcp:  jsr net_timer_tick
        bcc +
        lda #NS_READY
        sta net_state
+       rts
_conn:  lda BR_CTL+5
        cmp #1
        beq _up
        cmp #2
        beq _noconn
        jsr net_timer_tick
        bcs _noconn
        rts
_noconn:
        lda #0
        sta BR_CTL+4
        lda #E_CONN
        jmp net_fail
_up:    lda #NS_ONLINE
        sta net_state
        jmp proto_reset
_online:
        lda BR_CTL+5                    ; the server went away
        cmp #1
        bne _lost
-       ldx BR_CTL+1                    ; everything that has arrived
        cpx BR_CTL
        beq +
        lda BR_RX,x
        inc BR_CTL+1
        jsr proto_feed
        bra -
+       rts
_lost:  lda #0
        sta BR_CTL+4
        lda #E_LOST
        jmp net_fail

; A = a byte for the server; waits while the ring is full (the bridge empties it)
net_send:
        sta net_sb
        lda net_state                   ; no connection: fail now, not after 5 s
        cmp #NS_ONLINE
        beq +
        sec
        rts
+       lda #<250                       ; 5 s
        ldx #>250
        jsr net_timer_set
-       lda BR_CTL+2
        inc a
        cmp BR_CTL+3
        bne +
        jsr net_timer_tick
        bcc -
        lda #E_SEND
        jsr net_fail
        sec
        rts
+       ldx BR_CTL+2
        lda net_sb
        sta BR_TX,x
        inc BR_CTL+2
        clc
        rts
net_sb: .byte 0

        .else
;=======================================================================================
; the replay version (Xemu)
;=======================================================================================
MOCK_RX         = $8600000              ; the MOCKRX file: segments of (u16 after-frames,
MOCK_TX         = $8610000              ; u16 length, bytes); what the client sent
mock_rx_len:    .word 0                 ; (set at boot from the load)
mock_pos:       .word 0
mock_left:      .word 0
mock_txn:       .word 0
mock_tmp:       .dword 0

net_start:
        lda #E_NONE
        sta net_err
        lda #<25
        ldx #>25
        jsr net_timer_set
        lda #NS_DHCP
        sta net_state
        clc
        rts

net_connect:
        lda #<10
        ldx #>10
        jsr net_timer_set
        lda #NS_CONNECTING
        sta net_state
        rts

net_close:
        lda #NS_READY
        sta net_state
        rts

net_service:
        lda net_state
        cmp #NS_DHCP
        beq _wait
        cmp #NS_CONNECTING
        beq _wait
        cmp #NS_ONLINE
        beq _online
        rts
_wait:  jsr net_timer_tick
        bcc +
        lda net_state
        cmp #NS_DHCP
        beq _ready
        lda #NS_ONLINE
        sta net_state
        lda #0
        sta mock_pos
        sta mock_pos+1
        sta mock_left
        sta mock_left+1
        jmp proto_reset
_ready: lda #NS_READY
        sta net_state
+       rts
_online:
        lda #RX_MAX                     ; up to RX_MAX bytes a call
        sta net_rxi
_more:  lda mock_left
        ora mock_left+1
        bne _byte
        lda mock_pos                    ; a new segment, once the client has sent enough
        cmp mock_rx_len
        lda mock_pos+1
        sbc mock_rx_len+1
        bcs _out                        ; the recording is over
        jsr mock_rd                     ; after this many frames
        sta mock_tmp
        jsr mock_rd
        sta mock_tmp+1
        lda proto_txn
        cmp mock_tmp
        lda proto_txn+1
        sbc mock_tmp+1
        bcs +
        sec                             ; not yet: back up
        lda mock_pos
        sbc #2
        sta mock_pos
        bcs _out
        dec mock_pos+1
        rts
+       jsr mock_rd
        sta mock_left
        jsr mock_rd
        sta mock_left+1
        bra _more
_byte:  jsr mock_rd
        jsr proto_feed
        lda mock_left
        bne +
        dec mock_left+1
+       dec mock_left
        dec net_rxi
        bne _more
_out:   rts

; A = the next recorded byte (ptr0 is free here: called from the main loop only)
mock_rd:
        clc
        lda mock_pos
        adc #<MOCK_RX
        sta ptr0
        lda mock_pos+1
        adc #>MOCK_RX
        sta ptr0+1
        lda #(MOCK_RX >> 16) & $ff
        adc #0
        sta ptr0+2
        lda #MOCK_RX >> 24
        sta ptr0+3
        ldz #0
        lda [ptr0],z
        inc mock_pos
        bne +
        inc mock_pos+1
+       rts

net_send:
        pha
        clc
        lda mock_txn
        adc #<MOCK_TX
        sta ptr0
        lda mock_txn+1
        adc #>MOCK_TX
        sta ptr0+1
        lda #(MOCK_TX >> 16) & $ff
        adc #0
        sta ptr0+2
        lda #MOCK_TX >> 24
        sta ptr0+3
        pla
        ldz #0
        sta [ptr0],z
        inc mock_txn
        bne +
        inc mock_txn+1
+       clc
        rts
        .endif
