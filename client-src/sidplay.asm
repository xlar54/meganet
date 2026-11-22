;=======================================================================================
; sidplay.asm - C64 SID tunes in the background (Caps.SID): S.SID_PLAY, S.SID_STOP.
;
; The tune (a PSID's C64 data) comes in a resource slot like any of the server's pictures,
; then S.SID_PLAY says where it loads and its init / play addresses. It gets a C64 of its own:
;   $0000-$7FFF  -> $52000-$59FFF   (MAP blocks 0-3: its zero page and stack are its own)
;   $8000-$BFFF  -> $48000-$4BFFF   (blocks 4, 5)
;   $E000-$FFFF  -> $4E000-$4FFFF   (block 7: its vectors point at an RTI here)
;   $C000-$CFFF  the client's (SDP_TRAMP, this file's call routine, lives at its top)
;   $D000-$DFFF  the I/O: it writes the "right" SIDs at $D400 (the mixer's source 1)
; sdt_call maps it in, calls init (once) or play (from the frame IRQ, irq_hook: 50 or 60
; times a second, sdp_rate, whatever the screen's rate), maps the client back and puts $01
; and the CIAs' interrupt masks back. The server only sends tunes that a 6502 check found
; well behaved (server-src/meganet/sidcheck.py): legal opcodes, no CLI, only the SID and its
; own memory touched, and every call returning.
;
; The client's own sounds (sound.asm) play on the left SIDs ($D440, $D460: source 0). When
; one starts, the tune pauses (no play calls, the right SIDs muted in the mixer); a moment
; after it ends, it carries on (sdp_duck / sdp_unduck).
;
;   sdp_install      at boot (after irq_install, sid_init): the call routine, the IRQ hook,
;                   the mixer (both SID pairs to both speakers and the headphones)
;   pm_sid_play     S.SID_PLAY: u8 slot, u16 load, u16 length, u16 init, u16 play, u8 song
;                   (0-based), u8 rate (50 or 60 calls a second)
;   pm_sid_stop     S.SID_STOP
;   sdp_stop         the tune stops; the right SIDs silent
;   sdp_duck         pause it (a sound is starting); sdp_unduck carries on
;=======================================================================================

S_SID_PLAY      = $35
S_SID_STOP      = $36
S_SID_PAUSE     = $37                   ; u8 1 = hold the tune (the menu bar's note), 0 = go on
SDP_TRAMP        = $cf10                 ; the call routine: block 6, never mapped
SID_RIGHT       = $d400                 ; the right SIDs (two): the tune's
MIX_SRC_LEFT    = 0 * 2                 ; mixer sources (coefficient register offsets): the
MIX_SRC_RIGHT   = 1 * 2                 ; left SIDs (the client's sounds), the right (the tune)
SDP_LEVEL_LO     = $ff                   ; the SIDs' mixer level if it can't be read
SDP_LEVEL_HI     = $bf

sdp_on:          .byte 0                 ; a tune is playing (or paused)
sdp_paused:      .byte 0                 ; a sound is playing: the tune waits (sound.asm)
sdp_held:        .byte 0                 ; the user paused it (S.SID_PAUSE)
sdp_rate:        .byte 50                ; play calls a second
sdp_hz:          .byte 50                ; frames a second (60 on an NTSC screen)
sdp_acc:         .byte 0
sdp_level:       .word 0                 ; the SIDs' level in the mixer
sdp_slot:        .byte 0
sdp_load:        .word 0
sdp_len:         .word 0
sdp_init:        .word 0
sdp_play:        .word 0
sdp_song:        .byte 0
sdp_n1:          .word 0

; ---- the call routine: copied to SDP_TRAMP at boot ----
sdp_image:
        .logical SDP_TRAMP
; A = the tune's A (the song, for init); sdt_jsr+1/+2 = where. Interrupts off.
sdt_call:
        sta sdt_a
        lda #$35                        ; $01 afresh for each call, as a PSID player does
        sta $01
        lda #$20                        ; $0000-$7FFF -> $52000 (blocks 0-3)
        ldx #$f5
        ldy #$00                        ; $8000-$BFFF, $E000-$FFFF -> $48000.. (4, 5, 7)
        ldz #$b4
        map
        eom
        ldz #0
        cld
        ldx #0
        ldy #0
        lda sdt_a
sdt_jsr: jsr $ffff
        lda #0                          ; the client again
        tax
        tay
        taz
        map
        eom
        lda #$35
        sta $01
        lda #$7f                        ; the CIAs' interrupts off again (a tune may set them)
        sta $dc0d
        sta $dd0d
        lda $dc0d
        lda $dd0d
        lda #$ff                        ; the keyboard port's directions
        sta $dc02
        lda #0
        sta $dc03
        rts
sdt_a:  .byte 0
sdt_rti: rti                            ; the tune's own NMI / IRQ vectors point here
SDT_END:
        .endlogical
SDT_SIZE = SDT_END - SDP_TRAMP
        .cerror SDT_END > $d000, "the SID call routine runs into the I/O"
        .cerror OVL_END > SDP_TRAMP, "the overlay window reaches the SID call routine"

sdp_install:
        ldx #0
-       lda sdp_image,x
        sta SDP_TRAMP,x
        inx
        cpx #SDT_SIZE
        bne -
        lda #<sdp_frame
        sta irq_hook
        lda #>sdp_frame
        sta irq_hook+1
        lda #0
        sta sdp_on
        sta sdp_paused
        ; the SIDs' level: the right SIDs' coefficient for the left speaker or the right,
        ; whichever is louder; a fixed one if the mixer reads 0
        lda #MIX_SRC_RIGHT + 1          ; (the MSB: output 0)
        jsr sdp_mix_read
        sta sdp_level+1
        lda #32 + MIX_SRC_RIGHT + 1     ; output 1
        jsr sdp_mix_read
        cmp sdp_level+1
        bcc +
        sta sdp_level+1
        lda #32 + MIX_SRC_RIGHT
        jsr sdp_mix_read
        sta sdp_level
        bra ++
+       lda #MIX_SRC_RIGHT
        jsr sdp_mix_read
        sta sdp_level
+       lda sdp_level+1
        bne +
        lda #SDP_LEVEL_LO
        sta sdp_level
        lda #SDP_LEVEL_HI
        sta sdp_level+1
+       lda #MIX_SRC_LEFT               ; both pairs to both speakers and the headphones
        jsr sdp_mix_on
        lda #MIX_SRC_RIGHT
        jmp sdp_mix_on

; ---- the mixer (book appendix V: register = output * 32 + source * 2; 32 cycles between
; selects) ----
sdp_outs:        .byte 0 * 32, 1 * 32, 6 * 32, 7 * 32

; A = register: its value
sdp_mix_read:
        sta MIX_SEL
        jsr sdp_mix_wait
        lda MIX_DATA
        rts

sdp_mix_wait:
        phy
        ldy #48
-       dey
        bne -
        ply
        rts

; A = source offset: its coefficient on the four outputs = sdp_level (sdp_mix_on) or 0
sdp_mix_on:
        ldy #1
        bra sdp_mix_set
sdp_mix_off:
        ldy #0
sdp_mix_set:
        sta sdp_mx_src
        sty sdp_mx_on
        ldx #0
-       lda sdp_outs,x
        clc
        adc sdp_mx_src
        sta MIX_SEL
        jsr sdp_mix_wait
        lda sdp_mx_on
        beq +
        lda sdp_level
+       sta MIX_DATA
        jsr sdp_mix_wait
        lda sdp_outs,x
        clc
        adc sdp_mx_src
        inc a
        sta MIX_SEL
        jsr sdp_mix_wait
        lda sdp_mx_on
        beq +
        lda sdp_level+1
+       sta MIX_DATA
        jsr sdp_mix_wait
        inx
        cpx #4
        bne -
        rts
sdp_mx_src:      .byte 0
sdp_mx_on:       .byte 0

; ---- the frame IRQ's hook: the play calls due ----
sdp_frame:
        lda sdp_on
        beq _out
        lda sdp_paused
        ora sdp_held
        bne _out
        clc
        lda sdp_acc
        adc sdp_rate
        sta sdp_acc
_due:   lda sdp_acc
        cmp sdp_hz
        bcc _out
        sbc sdp_hz
        sta sdp_acc
        lda sdp_play
        sta sdt_jsr+1
        lda sdp_play+1
        sta sdt_jsr+2
        lda #0
        jsr sdt_call
        inc sdp_calls                   ; (tests count them)
        bne _due
        inc sdp_calls+1
        bra _due
_out:   rts
sdp_calls:      .word 0                 ; play calls so far

; ---- S.SID_PLAY / S.SID_STOP / S.SID_PAUSE ----
pm_sid_stop:
        jmp sdp_stop

; u8 1 = hold the tune where it is (no play calls, its SIDs muted), 0 = carry on (unless a
; sound is playing: then when it ends)
pm_sid_pause:
        jsr rd_u8
        sta sdp_held
        lda sdp_on
        beq _out
        lda sdp_held
        beq +
        lda #MIX_SRC_RIGHT
        jmp sdp_mix_off
+       lda sdp_paused
        bne _out
        lda #MIX_SRC_RIGHT
        jmp sdp_mix_on
_out:   rts

pm_sid_play:
        jsr rd_u8
        and #15
        sta sdp_slot
        jsr rd_u16
        sta sdp_load
        stx sdp_load+1
        jsr rd_u16
        sta sdp_len
        stx sdp_len+1
        jsr rd_u16
        sta sdp_init
        stx sdp_init+1
        jsr rd_u16
        sta sdp_play
        stx sdp_play+1
        jsr rd_u8
        sta sdp_song
        jsr rd_u8
        sta sdp_rate
        jsr sdp_stop
        lda sdp_len                      ; nothing to play: stopped
        ora sdp_len+1
        bne +
        rts
        ; the tune's memory: cleared, then its data (from the resource slot in attic)
+       lda #$20
        ldy #5
        jsr _clear8k4                   ; $52000-$59FFF
        lda #$80
        ldy #4
        jsr _clear4                     ; $48000-$4BFFF
        lda #$e0
        sta tmp4+1
        lda #0
        sta tmp4
        sta tmp5
        lda #$20
        sta tmp5+1
        lda #0
        ldx #0
        ldy #4
        jsr dma_fill                    ; $4E000-$4FFFF
        lda #0                          ; ptr1: the slot, $8400000 + slot * $10000
        sta ptr1
        sta ptr1+1
        lda sdp_slot
        clc
        adc #$40
        sta ptr1+2
        lda #$08
        sta ptr1+3
        lda sdp_len
        sta sdp_n1
        lda sdp_len+1
        sta sdp_n1+1
        lda sdp_load+1                   ; under $8000: as much as fits there first
        bmi _high
        sec
        lda #0
        sbc sdp_load
        sta tmp0
        lda #$80
        sbc sdp_load+1
        sta tmp0+1                      ; tmp0 = $8000 - load
        lda sdp_len+1                    ; n1 = min(len, $8000 - load)
        cmp tmp0+1
        bcc +
        bne _cap
        lda sdp_len
        cmp tmp0
        bcc +
_cap:   lda tmp0
        sta sdp_n1
        lda tmp0+1
        sta sdp_n1+1
+       lda sdp_load                     ; to $52000 + load
        sta ptr2
        clc
        lda sdp_load+1
        adc #$20
        sta ptr2+1
        lda #5
        sta ptr2+2
        lda #0
        sta ptr2+3
        lda sdp_n1
        sta tmp5
        lda sdp_n1+1
        sta tmp5+1
        jsr dma_copy_far
        sec                             ; the rest (from $8000), if any
        lda sdp_len
        sbc sdp_n1
        sta tmp5
        lda sdp_len+1
        sbc sdp_n1+1
        sta tmp5+1
        ora tmp5
        beq _loaded
        lda sdp_n1                       ; (dma_copy_far moves ptr1 on only at a megabyte)
        sta ptr1
        lda sdp_n1+1
        sta ptr1+1
        lda #0
        sta ptr2
        lda #$80
        sta ptr2+1
        lda #4
        sta ptr2+2
        jsr dma_copy_far
        bra _loaded
_high:  lda sdp_load                     ; at $8000 or above: to $40000 + load
        sta ptr2
        lda sdp_load+1
        sta ptr2+1
        lda #4
        sta ptr2+2
        lda #0
        sta ptr2+3
        lda sdp_len
        sta tmp5
        lda sdp_len+1
        sta tmp5+1
        jsr dma_copy_far
_loaded:
        ; its NMI / reset / IRQ vectors -> sdt_rti (unless the tune itself is there)
        clc
        lda sdp_load
        adc sdp_len
        lda sdp_load+1
        adc sdp_len+1
        bcs +                           ; (it reaches $FFFF)
        cmp #$ff
        bcc _vec
        bra +
_vec:   lda #$fa
        sta ptr0
        lda #$ff
        sta ptr0+1
        lda #$04
        sta ptr0+2
        lda #0
        sta ptr0+3
        ldz #0
-       lda #<sdt_rti
        sta [ptr0],z
        inz
        lda #>sdt_rti
        sta [ptr0],z
        inz
        cpz #6
        bne -
        ldz #0
+       ; the rate: the screen's frames a second (an NTSC screen: 60)
        lda #50
        bit $d06f
        bpl +
        lda #60
+       sta sdp_hz
        lda #0
        sta sdp_acc
        lda sdp_init                     ; init (A = the song), interrupts off
        sta sdt_jsr+1
        lda sdp_init+1
        sta sdt_jsr+2
        php
        sei
        lda sdp_song
        jsr sdt_call
        plp
        lda #0                          ; (a new tune isn't held)
        sta sdp_held
        lda snd_tail                    ; a sound going on: paused until it ends
        ora snd_wait
        sta sdp_paused
        bne +
        lda #MIX_SRC_RIGHT
        jsr sdp_mix_on
+       lda #1
        sta sdp_on
        rts

; A = address bits 8-15, Y = bank: 32 KB from there cleared (two 16 KB fills)
_clear8k4:
        pha
        jsr _clear4
        pla
        clc
        adc #$40
; A = address bits 8-15, Y = bank: 16 KB cleared
_clear4:
        sta tmp4+1
        lda #0
        sta tmp4
        sta tmp5
        lda #$40
        sta tmp5+1
        phy
        lda #0
        ldx #0
        jsr dma_fill
        ply
        rts

sdp_stop:
        lda #0
        sta sdp_on
        sta sdp_held
        ldx #$3f                        ; the right SIDs silent (both: a 2SID tune's too)
-       sta SID_RIGHT,x
        dex
        bpl -
        rts

; a sound is starting: the tune waits (no play calls), its SIDs muted
sdp_duck:
        lda sdp_paused
        bne +
        lda #1
        sta sdp_paused
        lda #MIX_SRC_RIGHT
        jmp sdp_mix_off
+       rts

; the sound is over: the tune carries on (unless the user has it paused)
sdp_unduck:
        lda sdp_paused
        beq +
        lda #0
        sta sdp_paused
        lda sdp_held
        bne +
        lda #MIX_SRC_RIGHT
        jsr sdp_mix_on
+       rts
