;=======================================================================================
; link.asm - is the server still there? The connectivity icon at the very right of the
; menu bar (GUI notification slot LINK_SLOT, the server's slots are one place left of it).
;
; Any frame from the server counts as a sign of life. After LINK_EVERY frames (30 s) with
; nothing from it, the client sends PING and the server answers PONG. No answer within
; LINK_WAIT frames (10 s): the icon gets an X, and a PING goes every LINK_RETRY frames (10 s)
; until something comes back, which puts the plain icon back. Clicking the icon pings now.
;=======================================================================================
        .cpu "45gs02"

LINK_SLOT       = 0
LINK_EVERY      = 30 * 50               ; quiet this long (frames): PING
LINK_RETRY      = 10 * 50               ; while it has the X: PING this often
LINK_WAIT       = 10 * 50               ; no answer this long: the X
NI_WIFI         = 3                     ; gui.asm icons
NI_WIFI_OFF     = 4

link_quiet:     .word 0                 ; frames since the last frame from the server (or PING)
link_wait:      .word 0                 ; frames since the PING that's not answered yet
link_pend:      .byte 0                 ; a PING not answered yet
link_ok:        .byte 1                 ; 0: no answer: the X
link_icon:      .byte 0                 ; the icon shown

; a frame came from the server (proto_dispatch)
link_rx:
        lda #0
        sta link_quiet
        sta link_quiet+1
        sta link_pend
        lda #1
        sta link_ok
        rts

; the icon clicked: PING at the next frame
link_click:
        lda #<LINK_EVERY
        sta link_quiet
        lda #>LINK_EVERY
        sta link_quiet+1
        rts

; once a frame
link_frame:
        lda login_state
        cmp #LS_ON
        beq _on
        jsr link_rx                     ; not signed on: nothing to watch, no icon
        lda #0
        bra _icon
_on:    inc link_quiet
        bne +
        inc link_quiet+1
+       lda link_pend
        beq _due
        inc link_wait
        bne +
        inc link_wait+1
+       lda link_wait+1                 ; waited LINK_WAIT: the X
        cmp #>LINK_WAIT
        bcc _due
        bne _lost
        lda link_wait
        cmp #<LINK_WAIT
        bcc _due
_lost:  lda #0
        sta link_ok
_due:   ldx #<LINK_EVERY                ; PING now?
        ldy #>LINK_EVERY
        lda link_ok
        bne +
        ldx #<LINK_RETRY
        ldy #>LINK_RETRY
+       stx link_t
        cpy link_quiet+1
        bcc _ping                       ; (high byte above the limit's)
        bne _show
        lda link_quiet
        cmp link_t
        bcc _show
_ping:  lda #0
        sta link_quiet
        sta link_quiet+1
        lda link_pend                   ; (an earlier PING still unanswered: keep its time)
        bne +
        lda #1
        sta link_pend
        lda #0
        sta link_wait
        sta link_wait+1
+       lda #C_PING
        jsr tx_begin
        jsr tx_end
_show:  lda #NI_WIFI
        ldx link_ok
        bne _icon
        lda #NI_WIFI_OFF
_icon:  cmp link_icon
        beq +
        sta link_icon
        tax
        lda #LINK_SLOT
        jmp gui_notify
+       rts
link_t: .byte 0
