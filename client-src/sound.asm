;=======================================================================================
; sound.asm - the client's sounds, played on the SID when the server sends S.SOUND
; (lib/sid.asm plays them; SID 1 and its mirror SID 2 are the two speakers).
;   1 = the chime: a "ding-dong" (C6 then A-flat 5, triangle waves that ring out), with the
;       flashing page icon when someone pages an admin
;=======================================================================================
SFX_TABLES_OWN  = 1                     ; (lib/sid.asm: these tables, not its game ones)
SID_MIRROR      = SID2

SFX_DING        = 0
SFX_DONG        = 1
;               ding  dong
sfx_voice:  .byte 0,    7                ; voice register offset
sfx_wave:   .byte $11,  $11              ; triangle + gate
sfx_fhi:    .byte $45,  $37              ; C6 (1047 Hz), A-flat 5 (831 Hz): PAL SID values
sfx_fstep:  .byte $00,  $00              ; no slide
sfx_len:    .byte 10,   14               ; frames the gate is held
sfx_ad:     .byte $09,  $0a              ; no attack, a long decay: a bell
sfx_sr:     .byte $09,  $0a              ; no sustain; it rings out on release

SOUND_CHIME     = 1
SND_DONG_AT     = 14                    ; frames after the ding

snd_t:          .byte 0                 ; frames into the chime, 0 = none

; u8 sound
pm_sound:
        jsr rd_u8
        cmp #SOUND_CHIME
        bne _out
        lda #1
        sta snd_t
        lda #SFX_DING
        jmp sfx_play
_out:   rts

; once a frame: the effects, and the chime's second note
sound_frame:
        jsr sfx_frame
        lda snd_t
        beq _out
        inc snd_t
        lda snd_t
        cmp #SND_DONG_AT
        bne _out
        lda #0
        sta snd_t
        lda #SFX_DONG
        jmp sfx_play
_out:   rts
