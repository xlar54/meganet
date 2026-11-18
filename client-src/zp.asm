;=======================================================================================
; Project base-page variables, after the library's (lib/zp.asm). Keep below $90 if the
; program loads files with the KERNAL at boot.
;=======================================================================================
        .virtual LIB_ZP_END
f640_ptr:       .dword ?                ; lib/fcm640.asm
f640_pal_r:     .word ?
f640_pal_g:     .word ?
f640_pal_b:     .word ?
pr_ptr:         .word ?                 ; proto.asm: the frame being read
zp_end:
        .endv
        .cerror zp_end > $90, "base page variables overflow into KERNAL space"
