;=======================================================================================
; lib/overlay.asm - code overlays: more program than fits in chip RAM, swapped by DMA.
;
; The program is a resident part (always in memory) and up to 16 overlays that all run at
; one window, OVL_BASE..OVL_END-1. At boot every overlay file is loaded into attic RAM;
; after that, bringing one into the window is one DMA copy (about 0.5 ms for 20 KB).
; Needs lib/dma.asm and, for ovl_boot_load, lib/loader.asm.
;
;   ovl_boot_load  BEFORE #TAKEOVER: loads OVL0, OVL1, ... (OVL_COUNT files, the digit is
;                  hex: OVLA is overlay 10) to OVL_ATTIC + n * $10000, each area zeroed
;                  first (so an overlay's buffers after its last byte start at 0). Carry
;                  set on failure, A = the overlay that failed.
;   ovl_init       after #TAKEOVER: no overlay in the window yet.
;   ovl_load       A = overlay: copy it into the window from attic, unless it is the one
;                  there. The copy in attic is not updated, so the overlay's variables
;                  start again from their loaded values each time it is loaded.
;   ovl_reload     the current overlay again, fresh from attic. Use after KERNAL disk
;                  calls (kstream, kfile): the DOS may have used part of the window.
;   ovl_far        call a routine in another overlay and come back: the FAR macro,
;                  #FAR OVL_X, routine. The overlay in the window is written back to attic
;                  first, so both keep their variables, and calls can nest (the overlay to
;                  go back to is on the stack). A, X, Y and the flags pass through both
;                  ways; the base page is untouched. The resident part can call it too,
;                  and comes back to whatever overlay was in the window.
;   ovl_cur        the overlay in the window ($ff: none).
;
; The project sets OVL_COUNT and names its overlays (OVL_GAME = 0 ...). Defaults:
;   OVL_BASE  $8000      the window; the resident part must end below it
;   OVL_END   $d000      (the window may not reach I/O at $D000)
;   OVL_ATTIC $8700000   overlay n at OVL_ATTIC + n * $10000 (bits 16-19 must be 0)
;
; Layout (see src/lib/README.md, "Overlays"): main.asm puts the resident part in section
; res at $1FFF (with the PRG's load address word first) and overlay n in section ovlN at
; physical $100000 + n * $10000, each as
;           .section ovl1
;           .word 0                     ; the two bytes a LOAD skips
;           .logical OVL_BASE
;           .include "level.asm"
;           .cerror * > OVL_END, "overlay 1 is too big"
;           .endlogical
;           .send ovl1
; build.bat (OVERLAYS=...) writes each section to its own file with
; 64tass --flat --output-section and tools/cut.py. All of it is one assembly, so the
; overlays can call the resident part and the resident part can name overlay labels; but
; the assembler can't tell that a direct jsr from one overlay to another's label is wrong.
; private/tools/ovl_check.py lists those.
;
; Variables kept across ovl_load (not ovl_far) belong in the resident part. Data only an
; overlay reads may go past OVL_END in its file (pad with .fill OVL_END - *, 0 first): it
; stays in attic, where the overlay reads it with DMA, and never reaches the window.
;=======================================================================================

        .weak
OVL_BASE        = $8000
OVL_END         = $d000
OVL_ATTIC       = $8700000
OVL_COUNT       = 1
        .endweak
        .cerror ((OVL_ATTIC >> 16) & $0f) != 0, "OVL_ATTIC: bits 16-19 must be 0 (overlay n is in attic bank n)"
        .cerror OVL_COUNT < 1 || OVL_COUNT > 16, "OVL_COUNT: 1 to 16 overlays"
        .cerror OVL_END > $d000 || OVL_BASE >= OVL_END, "OVL_BASE..OVL_END: inside $2000-$CFFF"

; a call into another overlay: A, X, Y and the flags go through both ways
FAR     .macro ovl, routine
        jsr ovl_far
        .byte \ovl
        .word \routine
.endmacro

ovl_cur:        .byte $ff               ; the overlay in the window ($ff: none)

;---------------------------------------------------------------------------------------
; ovl_boot_load: every overlay into attic, through the KERNAL (before #TAKEOVER)
;---------------------------------------------------------------------------------------
ovl_boot_load:
        lda #0
        sta l_ovl_n
l_ovl_bl:
        lda #0                          ; its area zeroed (buffers aren't in the file)
        sta tmp4
        sta tmp4+1
        lda #<(OVL_END - OVL_BASE)
        sta tmp5
        lda #>(OVL_END - OVL_BASE)
        sta tmp5+1
        ldy l_ovl_n                     ; bank (bits 16-19): OVL_ATTIC's are 0
        ldx #OVL_ATTIC >> 20            ; megabyte
        lda #0
        jsr dma_fill
        lda #0
        sta ld_attic
        sta ld_attic+1
        lda l_ovl_n
        clc
        adc #`OVL_ATTIC
        sta ld_attic+2
        lda #OVL_ATTIC >> 24
        sta ld_attic+3
        lda l_ovl_n                     ; the name's last character: hex
        cmp #10
        bcc +
        adc #'A' - '0' - 10 - 1         ; (carry set)
+       adc #'0'
        sta l_ovl_name+3
        lda #4
        ldx #<l_ovl_name
        ldy #>l_ovl_name
        jsr load_to_attic
        bcc +
        lda l_ovl_n
        rts                             ; carry set: that file is missing
+       inc l_ovl_n
        lda l_ovl_n
        cmp #OVL_COUNT
        bne l_ovl_bl
        clc
        rts

;---------------------------------------------------------------------------------------
; ovl_init: after #TAKEOVER, before the first ovl_load
;---------------------------------------------------------------------------------------
ovl_init:
        lda #$ff
        sta ovl_cur
        rts

;---------------------------------------------------------------------------------------
; ovl_reload: the current overlay again, fresh from attic
;---------------------------------------------------------------------------------------
ovl_reload:
        lda ovl_cur
        ldx #$ff
        stx ovl_cur
;---------------------------------------------------------------------------------------
; ovl_load: A = overlay: into the window from attic, unless it is there already
;           (changes ptr1, ptr2, tmp5 and dma_copy_far's temporaries)
;---------------------------------------------------------------------------------------
ovl_load:
        cmp ovl_cur
        bne +
        rts
+       sta ovl_cur
        clc
        adc #`OVL_ATTIC
        sta ptr1+2
        lda #0
        sta ptr1
        sta ptr1+1
        lda #OVL_ATTIC >> 24
        sta ptr1+3
        lda #<OVL_BASE
        sta ptr2
        lda #>OVL_BASE
        sta ptr2+1
        lda #0
        sta ptr2+2
        sta ptr2+3
        lda #<(OVL_END - OVL_BASE)
        sta tmp5
        lda #>(OVL_END - OVL_BASE)
        sta tmp5+1
        jmp dma_copy_far

;---------------------------------------------------------------------------------------
; ovl_far: jsr ovl_far / .byte overlay / .word routine (the FAR macro)
;---------------------------------------------------------------------------------------
ovl_far:
        sta l_of_a
        stx l_of_x
        sty l_of_y
        pla                             ; the return address - 1: the inline bytes follow
        sta l_of_rd+1
        pla
        sta l_of_rd+2
        ldx #3
l_of_rd:
        lda $ffff,x                     ; (self-modified)
        sta l_of_t-1,x
        dex
        bne l_of_rd
        clc                             ; back past them
        lda l_of_rd+1
        adc #3
        tax
        lda l_of_rd+2
        adc #0
        pha
        txa
        pha
        lda ovl_cur                     ; the caller's overlay, to go back to
        pha
        lda l_of_t+1
        sta l_of_j+1
        lda l_of_t+2
        sta l_of_j+2
        lda l_of_t
        jsr l_ovl_swap
        lda l_of_a
        ldx l_of_x
        ldy l_of_y
        jsr l_of_j
        php
        sta l_of_a
        stx l_of_x
        sty l_of_y
        pla
        sta l_of_p
        pla
        jsr l_ovl_swap
        lda l_of_p
        pha
        lda l_of_a
        ldx l_of_x
        ldy l_of_y
        plp
        rts
l_of_j: jmp $ffff                       ; (self-modified)
l_of_t:         .fill 3                 ; the overlay, the routine
l_of_a:         .byte 0
l_of_x:         .byte 0
l_of_y:         .byte 0
l_of_p:         .byte 0

; A = the overlay to have in the window; the one there goes back to attic first ($ff:
; none, as when the resident part calls with nothing loaded)
l_ovl_swap:
        cmp ovl_cur
        beq l_os_r
        pha
        lda ovl_cur
        bmi +                           ; (none)
        sta l_os_wbank
        lda #>l_os_wjob
        sta DMA_ADDRMSB
        lda #<l_os_wjob
        sta DMA_ADDRLSB_ETRIG
+       pla
        sta ovl_cur
        bmi l_os_r                      ; back to "none"
        sta l_os_lbank
        lda #>l_os_ljob
        sta DMA_ADDRMSB
        lda #<l_os_ljob
        sta DMA_ADDRLSB_ETRIG
l_os_r: rts
l_os_wjob:      .byte DMAOPT_F018B, DMAOPT_SRC_MB, 0, DMAOPT_DST_MB, OVL_ATTIC >> 20, DMAOPT_END
                .byte DMACMD_COPY
                .word OVL_END - OVL_BASE
                .word OVL_BASE
                .byte 0
                .word OVL_ATTIC & $ffff
l_os_wbank:     .byte 0                 ; overlay n: attic bank n
                .byte 0
                .word 0
l_os_ljob:      .byte DMAOPT_F018B, DMAOPT_SRC_MB, OVL_ATTIC >> 20, DMAOPT_DST_MB, 0, DMAOPT_END
                .byte DMACMD_COPY
                .word OVL_END - OVL_BASE
                .word OVL_ATTIC & $ffff
l_os_lbank:     .byte 0
                .word OVL_BASE
                .byte 0
                .byte 0
                .word 0

l_ovl_n:        .byte 0
l_ovl_name:     .text "OVL0"
