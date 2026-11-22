;=======================================================================================
; sound.asm - the client's sounds, played on the SID when the server sends S.SOUND
; (lib/sid.asm plays them; SID 1 and its mirror SID 2 are the two speakers).
;   1 = the chime: a "ding-dong" (C6 then A-flat 5, triangle waves that ring out), with the
;       flashing page icon when someone pages an admin
;   2 = ka-ching: a cash register (a click of noise, then two high square-wave notes, B6
;       and E7, that ring out together): you won a poker hand
;   3 = the doorbell: the four Westminster notes (E5 C5 D5 G4, bells on three voices that
;       overlap): a new instant or private message
; A sound is a list of steps: (effect, frames to the next step), ending with effect $FF.
; 0 frames plays the next step at once (notes together). Other numbers are ignored, so
; the server can send new sounds to old clients.
;=======================================================================================
SFX_TABLES_OWN  = 1                     ; (lib/sid.asm: these tables, not its game ones)
SID_MIRROR      = SID2

SFX_DING        = 0
SFX_DONG        = 1
SFX_KA          = 2
SFX_CHING1      = 3
SFX_CHING2      = 4
SFX_BELL_E      = 5
SFX_BELL_C      = 6
SFX_BELL_D      = 7
SFX_BELL_G      = 8
;               ding  dong  ka    ching ching bellE bellC bellD bellG
sfx_voice:  .byte 0,    7,    14,   0,    7,    0,    7,    14,   0     ; voice register offset
sfx_wave:   .byte $11,  $11,  $81,  $41,  $41,  $11,  $11,  $11,  $11   ; triangle / noise /
                                                                        ; pulse, + gate
sfx_fhi:    .byte $45,  $37,  $c0,  $83,  $af,  $2c,  $23,  $27,  $1a   ; C6, A-flat 5; noise;
                                                ; B6, E7; E5, C5, D5, G4 (PAL SID values)
sfx_fstep:  .byte $00,  $00,  $00,  $00,  $00,  $00,  $00,  $00,  $00   ; no slide
sfx_len:    .byte 10,   14,   2,    3,    3,    8,    8,    8,    14    ; frames the gate is held
sfx_ad:     .byte $09,  $0a,  $00,  $09,  $09,  $0a,  $0a,  $0a,  $0b   ; no attack; a long
sfx_sr:     .byte $09,  $0a,  $00,  $0a,  $0a,  $0a,  $0a,  $0a,  $0b   ; decay rings like a
                                                                        ; bell, on release too

SND_END         = $ff
snd_steps:
_chime: .byte SFX_DING, 13, SFX_DONG, 0, SND_END
_kaching: .byte SFX_KA, 3, SFX_CHING1, 0, SFX_CHING2, 0, SND_END
_doorbell: .byte SFX_BELL_E, 16, SFX_BELL_C, 16, SFX_BELL_D, 16, SFX_BELL_G, 0, SND_END
snd_first:      .byte 0, _chime - snd_steps, _kaching - snd_steps, _doorbell - snd_steps
SOUNDS          = 4                     ; (by sound number: protocol.py Sound)

snd_pos:        .byte 0                 ; the next step (an index into snd_steps)
snd_wait:       .byte 0                 ; frames until it plays, 0 = nothing to come

; u8 sound
pm_sound:
        jsr rd_u8
        cmp #SOUNDS
        bcs _out
        tax
        beq _out
        lda snd_first,x
        sta snd_pos
        jmp snd_step
_out:   rts

; play the step at snd_pos, and any after it that go at once
snd_step:
        ldx snd_pos
        lda snd_steps,x
        cmp #SND_END
        beq _end
        jsr sfx_play
        ldx snd_pos
        inx
        inx
        stx snd_pos
        lda snd_steps-1,x               ; (the step's frames: its second byte; the flags
        sta snd_wait                    ; come from this LDA, not the INX)
        beq snd_step                    ; (0: together)
        rts
_end:   lda #0
        sta snd_wait
        rts

; once a frame: the effects, and the next step of a sound
sound_frame:
        jsr sfx_frame
        lda snd_wait
        beq _out
        dec snd_wait
        bne _out
        jmp snd_step
_out:   rts
