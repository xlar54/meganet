;=======================================================================================
; lib/kstream.asm - streaming disk files AFTER #TAKEOVER: SEQ and PRG files of any size,
; directories and the drive status, through the KERNAL. Like lib/kfile.asm, but a block
; at a time rather than a whole file through LOAD/SAVE.
;
; A trampoline below $2000 (KS_LOW) puts back the boot MAP, $01 and $D030, runs one KERNAL
; job and restores the program's. The KERNAL changes the VIC-IV's pointers (MEGA65_NOTES,
; "Calling the KERNAL after the takeover"), so those are saved and put back around every
; job. The KERNAL overwrites base page $90-$FF and $0200-$03FF.
;
;   kst_capture    call ONCE at boot, before #TAKEOVER. To use kstream before #TAKEOVER as well,
;                  SEI straight after this: a job leaves the machine with no MAP, so an interrupt
;                  between jobs would read its vector from RAM that doesn't have one. Each job
;                  allows interrupts while the KERNAL itself is running.
;   kst_open       A = name length, kst_name = the name as the DOS wants it (PETSCII, with
;                  any ",S,R" or "@0:"), kst_sa = secondary address. Carry set = failed.
;   kst_read       up to 255 bytes into KS_BUF. kst_count = bytes, kst_st = KERNAL status
;                  (bit 6 = end of file; other bits = trouble).
;   kst_write      kst_count bytes from KS_BUF. kst_st as above.
;   kst_close      close the file.
;   kst_status     read the drive's status channel into KS_BUF (zero-terminated):
;                  A = its number (00 = fine, 62 = file not found, ...), as binary.
;                  Only with no data file open: closing the channel closes them all.
;   kst_command    A = length, kst_name = a DOS command ("S0:NAME", "R0:NEW=OLD"): sends it
;                  and reads the reply, as kst_status. The same rule about open files.
;   kst_name_raw   A/X = a string, Y = offset: copy it into kst_name as it is. Y = the new end.
;   kst_name_put   A/X = a file name as typed, Y = offset: the same, converting to the DOS's
;                  bytes: A-Z stay $41-$5A, a-z become $C1-$DA (see MEGA65_NOTES section 10)
;   kst_rewind     before reading an open file a byte at a time
;   kst_getc       A = the next byte of the open file, carry set at the end. Fills from the drive.
;                  Changes X (and Y when it fills): keep loop counters in memory.
;   kst_fill       the next block for kst_getc. kst_avail = bytes.
;   kst_exists     A/X = a name: carry clear if it's on disk. A = the drive's reply: 00 or 63
;                  there, 62 not, anything else is other trouble (the text is in KS_BUF).
;                  Renames the file to its own name, which changes nothing and needs no type.
;   kst_remove     A/X = a name: remove it, validating if it was an unclosed file.
;   kst_dev        the unit used by all of the above (default KS_DEVICE)
;   kst_present    carry clear if a device answers at kst_dev. Listens to it and checks the
;                  status, without opening anything (from Todd Elliott's drive-polling routine).
;   kst_to_basic   leave the program and go back to BASIC's READY prompt, as if the SYS
;                  had returned. Doesn't return. (Not a reset: that would run AUTOBOOT.C65
;                  again.) kst_capture must be the first thing the program calls, from
;                  the top level, as it records the stack the SYS left.
;
; On real hardware, test it there: see MEGA65_NOTES "Where Xemu and hardware differ".
;=======================================================================================

        .weak
KS_LOW          = $1600                 ; the trampoline: $1600-$1EFF is always free
KS_SAVE         = $1A00                 ; 512 bytes: BASIC's base page and stack
KS_BUF          = $1C00                 ; 256 bytes
kst_name        = $1D00                 ; 64 bytes
KS_DEVICE       = 8
        .endweak

KS_LFN          = 2
KERNAL_READST   = $FFB7
KERNAL_OPEN     = $FFC0
KERNAL_CLOSE    = $FFC3
KERNAL_CHKIN    = $FFC6
KERNAL_CHKOUT   = $FFC9
KERNAL_CLRCHN   = $FFCC
KERNAL_CHRIN    = $FFCF
KERNAL_CINT     = $FF81
KERNAL_IOINIT   = $FF84
KERNAL_SECOND   = $FF93
KERNAL_UNLSN    = $FFAE
KERNAL_LISTEN   = $FFB1

L_KS_OPEN       = 0
L_KS_READ       = 1
L_KS_WRITE      = 2
L_KS_CLOSE      = 3
L_KS_STATUS     = 4
L_KS_PROBE      = 5

kst_sa:         .byte 2
kst_count:      .byte 0
kst_st:         .byte 0

; the VIC-IV registers the KERNAL may change. The order matters: $D05D goes first, and
; $D031 before the sprite pointer, because writing it resets that.
l_ks_regs:
        .word $D05D, $D031, $D054, $D058, $D059, $D05C, $D05E, $D04C, $D04D
        .word $D060, $D061, $D062, $D063, $D064, $D065
        .word $D068, $D069, $D06A, $D06B, $D06C, $D06D, $D06E
        .word $D070, $D07B, $D015, $D020, $D021
l_ks_nregs = (* - l_ks_regs) / 2
l_ks_vals:      .fill l_ks_nregs
l_ks_charptr:   .fill 4                 ; the boot font pointer, for kst_to_basic
l_ks_boot_ctl:  .fill 8                 ; boot $D031, $D054, $D058, $D059, $D05E, $D05C, $D05D, $D07B
l_ks_boot_scr:  .fill 4                 ; boot screen pointer

kst_capture:
        tsx                             ; the stack as the SYS left it: above our return
        inx
        inx
        stx l_ks_sp_save
        ldx #0                          ; BASIC's base page and stack
-       lda $00,x
        sta KS_SAVE,x
        lda $0100,x
        sta KS_SAVE+256,x
        inx
        bne -
        ldx #0                          ; the trampoline, before anything is stored in it
-       lda l_ks_src,x
        sta KS_LOW,x
        lda l_ks_src+256,x
        sta KS_LOW+256,x
        lda l_ks_src+512,x
        sta KS_LOW+512,x
        inx
        bne -
        lda $01
        sta l_ks_t_b01
        lda $d030
        sta l_ks_t_bd030
        ; the RAM under the vectors at boot: see the trampoline
        lda #$FA
        sta ptr0
        lda #$FF
        sta ptr0+1
        lda #0
        sta ptr0+2
        sta ptr0+3
        ldz #0
-       tza
        tax
        lda [ptr0],z
        sta l_ks_t_bvec,x
        inz
        cpz #6
        bne -
        ldz #0
        ldx #3
-       lda $D068,x
        sta l_ks_charptr,x
        lda $D060,x
        sta l_ks_boot_scr,x
        dex
        bpl -
        lda $D031
        sta l_ks_boot_ctl
        lda $D054
        sta l_ks_boot_ctl+1
        lda $D058
        sta l_ks_boot_ctl+2
        lda $D059
        sta l_ks_boot_ctl+3
        lda $D05E
        sta l_ks_boot_ctl+4
        lda $D05C
        sta l_ks_boot_ctl+5
        lda $D05D
        sta l_ks_boot_ctl+6
        lda $D07B
        sta l_ks_boot_ctl+7
        rts

; A = job
l_ks_job:
        sta l_ks_t_op
        ; save
        ldx #0
        ldy #0
-       lda l_ks_regs,y
        sta txt_ptr
        lda l_ks_regs+1,y
        sta txt_ptr+1
        phy
        ldy #0
        lda (txt_ptr),y
        ply
        sta l_ks_vals,x
        iny
        iny
        inx
        cpx #l_ks_nregs
        bne -
        jsr KS_LOW
        ; restore
        lda #$47
        sta VIC4_KEY
        lda #$53
        sta VIC4_KEY
        ldx #0
        ldy #0
-       lda l_ks_regs,y
        sta txt_ptr
        lda l_ks_regs+1,y
        sta txt_ptr+1
        lda l_ks_vals,x
        phy
        ldy #0
        sta (txt_ptr),y
        ply
        iny
        iny
        inx
        cpx #l_ks_nregs
        bne -
        lda #$ff                        ; the KERNAL may have moved these
        sta CIA1_DDRA
        lda #0
        sta CIA1_DDRB
        sta DMA_ADDRMB
        sta DMA_ADDRBANK
        lda #$7f                        ; no CIA interrupts
        sta CIA1_ICR
        sta CIA2_ICR
        lda CIA1_ICR
        lda CIA2_ICR
        rts

kst_open:
        sta l_ks_t_len
        lda kst_sa
        sta l_ks_t_sa
        lda #L_KS_OPEN
        jsr l_ks_job
        lda l_ks_t_ok
        cmp #1                          ; carry set = failed
        rts

kst_read:
        lda #L_KS_READ
        jsr l_ks_job
        lda l_ks_t_n
        sta kst_count
        lda l_ks_t_st
        sta kst_st
        rts

kst_write:
        lda kst_count
        sta l_ks_t_n
        lda #L_KS_WRITE
        jsr l_ks_job
        lda l_ks_t_st
        sta kst_st
        rts

kst_present:
        lda #L_KS_PROBE
        jsr l_ks_job
        lda l_ks_t_st
        cmp #$80                        ; bit 7 of the status: no device
        rts

kst_close:
        lda #L_KS_CLOSE
        jmp l_ks_job

kst_status:
        lda #0
kst_command:
        sta l_ks_t_len
        lda #L_KS_STATUS
        jsr l_ks_job
        lda KS_BUF
        sec
        sbc #'0'
        bcc l_ks_st_bad
        cmp #10
        bcs l_ks_st_bad
        asl
        sta l_ks_t10
        asl
        asl
        clc
        adc l_ks_t10
        sta l_ks_t10
        lda KS_BUF+1
        sec
        sbc #'0'
        clc
        adc l_ks_t10
        rts
l_ks_st_bad:
        lda #99
        rts
l_ks_t10:       .byte 0

;---------------------------------------------------------------------------------------
; names, reading a byte at a time, and whole-file operations
;---------------------------------------------------------------------------------------
; copy the zero-terminated text at A/X to kst_name at offset Y, as PETSCII. Y = the new
; length.
kst_name_put:
        sta txt_ptr
        stx txt_ptr+1
        sty l_ks_nlen
        ldy #0
-       lda (txt_ptr),y
        beq +
        cmp #'a'
        bcc l_ks_np
        cmp #'z' + 1
        bcs l_ks_np
        clc
        adc #$60                        ; a-z -> $C1-$DA
l_ks_np:
        ldx l_ks_nlen
        sta kst_name,x
        inc l_ks_nlen
        iny
        bne -
+       ldy l_ks_nlen
        rts

; append a plain string at A/X to kst_name at Y
kst_name_raw:
        sta txt_ptr
        stx txt_ptr+1
        sty l_ks_nlen
        ldy #0
-       lda (txt_ptr),y
        beq +
        ldx l_ks_nlen
        sta kst_name,x
        inc l_ks_nlen
        iny
        bne -
+       ldy l_ks_nlen
        rts

; the next block
kst_fill:
        jsr kst_read
        lda kst_count
        sta kst_avail
        lda #0
        sta l_ks_pos
        lda kst_st
        beq +
        lda #1
        sta l_ks_eof
+       rts

; A = the next byte of the file, carry set at the end
kst_getc:
        ldx l_ks_pos
        cpx kst_avail
        bcc l_ks_gc
        lda l_ks_eof
        bne l_ks_gc_end
        jsr kst_fill
        ldx l_ks_pos
        cpx kst_avail
        bcs l_ks_gc_end
l_ks_gc:
        lda KS_BUF,x
        inc l_ks_pos
        clc
        rts
l_ks_gc_end:
        sec
        rts

; A/X = name: carry clear if a file of that name exists. A = the drive's reply: 63 (or 00)
; it's there, 62 it isn't, anything else is some other trouble, with the text in KS_BUF.
; Done by renaming the file to its own name, which changes nothing, and works whatever the
; file's type.
kst_exists:
        sta l_ks_ex
        stx l_ks_ex+1
        lda #<l_ks_cmd_r
        ldx #>l_ks_cmd_r
        ldy #0
        jsr kst_name_raw
        lda l_ks_ex
        ldx l_ks_ex+1
        jsr kst_name_put
        lda #<l_ks_equals
        ldx #>l_ks_equals
        jsr kst_name_raw
        lda l_ks_ex
        ldx l_ks_ex+1
        jsr kst_name_put
        tya
        jsr kst_command
        cmp #63
        beq l_ks_ex_yes
        cmp #0
        beq l_ks_ex_yes
        sec
        rts
l_ks_ex_yes:
        clc
        rts
l_ks_ex:        .word 0
; A/X = a name: remove that file. A write that failed leaves an unclosed file (shown as *SEQ),
; which the DOS won't scratch, and which would then block the next save with "file exists".
; Only validating the disk removes those, so that's done when the scratch didn't work. It's
; slow on a real drive, and rarely needed.
kst_remove:
        sta l_ks_rm
        stx l_ks_rm+1
        lda #<l_ks_cmd_s
        ldx #>l_ks_cmd_s
        ldy #0
        jsr kst_name_raw
        lda l_ks_rm
        ldx l_ks_rm+1
        jsr kst_name_put
        tya
        jsr kst_command
        lda l_ks_rm
        ldx l_ks_rm+1
        jsr kst_exists
        bcs l_ks_rm_end                 ; it went
        lda #<l_ks_cmd_v
        ldx #>l_ks_cmd_v
        ldy #0
        jsr kst_name_raw
        tya
        jmp kst_command
l_ks_rm_end:
        rts
l_ks_rm:        .word 0
l_ks_cmd_v: .null "V0:"

kst_rewind:
        lda #0
        sta l_ks_eof
        sta kst_avail
        sta l_ks_pos
        rts
kst_avail:      .byte 0                 ; bytes kst_fill got
l_ks_pos:       .byte 0
l_ks_eof:       .byte 0
l_ks_nlen:      .byte 0
l_ks_cmd_r:     .null "R0:"
l_ks_cmd_s:     .null "S0:"
l_ks_equals:    .null "="

;---------------------------------------------------------------------------------------
kst_to_basic:
        sei
        ; undo what the program set
        lda #0
        sta SPR_ENABLE
        lda #$47
        sta VIC4_KEY
        lda #$53
        sta VIC4_KEY
        lda #0
        sta VIC_IRQ_MASK
        lda #$ff
        sta VIC_IRQ_STATUS
        ; the trampoline finishes it, from below $2000
        lda l_ks_charptr
        sta l_ks_t_cp
        lda l_ks_charptr+1
        sta l_ks_t_cp+1
        lda l_ks_charptr+2
        sta l_ks_t_cp+2
        lda l_ks_charptr+3
        sta l_ks_t_cp+3
        lda l_ks_sp_save
        sta l_ks_t_sp
        ; the ROM's colours, while the palette is in view
        ldx #15
-       lda l_ks_def_r,x
        sta $D100,x
        lda l_ks_def_g,x
        sta $D200,x
        lda l_ks_def_b,x
        sta $D300,x
        dex
        bpl -
        lda #6
        sta BORDERCOL
        sta BACKCOL
        lda #0
        sta $D064                       ; colour RAM from the start again
        sta $D065
        ldx #5                          ; the vectors as they were at boot
-       lda l_ks_t_bvec,x
        sta $fffa,x
        dex
        bpl -
        jmp l_ks_t_basic
l_ks_sp_save:   .byte 0
; 4-bit values: the same either way round in the nibble-swapped registers once doubled
l_ks_def_r:     .byte $00,$FF,$FF,$00,$FF,$00,$00,$FF,$FF,$AA,$FF,$55,$88,$99,$99,$BB
l_ks_def_g:     .byte $00,$FF,$00,$FF,$00,$FF,$00,$FF,$66,$44,$77,$55,$88,$FF,$99,$BB
l_ks_def_b:     .byte $00,$FF,$00,$FF,$FF,$00,$FF,$00,$00,$00,$77,$55,$88,$99,$FF,$BB

;---------------------------------------------------------------------------------------
; the trampoline
;---------------------------------------------------------------------------------------
l_ks_src:
        .logical KS_LOW
        php
        sei
        lda $01
        sta l_ks_t_g01
        lda $d030
        sta l_ks_t_gd030
        lda VIC_IRQ_MASK
        sta l_ks_t_girq
        lda #0
        sta VIC_IRQ_MASK                ; no frame IRQ while the KERNAL runs
        lda #$ff
        sta VIC_IRQ_STATUS
        ; The DOS maps the ROM away from $E000, so an interrupt during disk work reads its
        ; vector from RAM. Our IRQ handler must not be there then.
        ldx #5
-       lda $fffa,x
        sta l_ks_t_gvec,x
        lda l_ks_t_bvec,x
        sta $fffa,x
        dex
        bpl -
        lda #$00                        ; boot MAP
        ldx #$e3
        ldy #$00
        ldz #$b3
        map
        eom
        lda l_ks_t_b01
        sta $01
        lda l_ks_t_bd030
        sta $d030
        cli
        lda #0                          ; data and name in bank 0
        ldx #0
        jsr KERNAL_SETBNK
        lda l_ks_t_op
        beq l_ks_t_open
        cmp #L_KS_READ
        beq l_ks_t_read
        cmp #L_KS_WRITE
        bne +
        jmp l_ks_t_write
+       cmp #L_KS_CLOSE
        bne +
        jmp l_ks_t_close
+       cmp #L_KS_PROBE
        bne +
        jmp l_ks_t_probe
+       jmp l_ks_t_status

l_ks_t_open:
        lda l_ks_t_len
        ldx #<kst_name
        ldy #>kst_name
        jsr KERNAL_SETNAM
        lda #KS_LFN
        ldx l_ks_t_dev
        ldy l_ks_t_sa
        jsr KERNAL_SETLFS
        jsr KERNAL_OPEN
        lda #0
        rol                             ; carry -> ok flag (0 = success)
        sta l_ks_t_ok
        jmp l_ks_t_done

l_ks_t_read:
        lda #0
        sta l_ks_t_n
        sta l_ks_t_st
        ldx #KS_LFN
        jsr KERNAL_CHKIN
        bcc l_ks_t_rloop
        lda #$80
        sta l_ks_t_st
        bra l_ks_t_rend
l_ks_t_rloop:
        jsr KERNAL_CHRIN
        ldx l_ks_t_n
        sta KS_BUF,x
        jsr KERNAL_READST
        sta l_ks_t_st
        and #$BF                        ; a real error: the byte doesn't count
        bne l_ks_t_rend
        inc l_ks_t_n
        lda l_ks_t_st
        bne l_ks_t_rend                 ; end of file: that was the last byte
        lda l_ks_t_n
        cmp #255
        bne l_ks_t_rloop
l_ks_t_rend:
        jsr KERNAL_CLRCHN
        jmp l_ks_t_done

l_ks_t_write:
        lda #0
        sta l_ks_t_st
        sta l_ks_t_i
        ldx #KS_LFN
        jsr KERNAL_CHKOUT
        bcc l_ks_t_wloop
        lda #$80
        sta l_ks_t_st
        bra l_ks_t_wend
l_ks_t_wloop:
        lda l_ks_t_i
        cmp l_ks_t_n
        beq l_ks_t_wend
        tax
        lda KS_BUF,x
        jsr KERNAL_CHROUT
        inc l_ks_t_i
        jsr KERNAL_READST
        sta l_ks_t_st
        beq l_ks_t_wloop
l_ks_t_wend:
        jsr KERNAL_CLRCHN
        bra l_ks_t_done

l_ks_t_close:
        jsr KERNAL_CLRCHN
        lda #KS_LFN
        jsr KERNAL_CLOSE
        bra l_ks_t_done

l_ks_t_status:
        lda l_ks_t_len                  ; 0 = just read the channel, else a command
        ldx #<kst_name
        ldy #>kst_name
        jsr KERNAL_SETNAM
        lda #15
        ldx l_ks_t_dev
        ldy #15
        jsr KERNAL_SETLFS
        jsr KERNAL_OPEN
        bcs l_ks_t_nodev
        ldx #15
        jsr KERNAL_CHKIN
        bcs l_ks_t_nodev                ; (CHRIN would then wait for the keyboard, for ever)
        jsr KERNAL_READST
        bmi l_ks_t_nodev
        lda #0
        sta l_ks_t_i
-       jsr KERNAL_CHRIN
        ldx l_ks_t_i
        sta KS_BUF,x
        inc l_ks_t_i
        jsr KERNAL_READST
        bne +
        lda l_ks_t_i
        cmp #60
        bne -
+       ldx l_ks_t_i
        dex                             ; (without the CR it ends in)
        lda #0
        sta KS_BUF,x
        jsr KERNAL_CLRCHN
        lda #15
        jsr KERNAL_CLOSE
        bra l_ks_t_done

l_ks_t_nodev:
        jsr KERNAL_CLRCHN
        lda #15
        jsr KERNAL_CLOSE
        ldx #0
-       lda l_ks_t_nomsg,x
        sta KS_BUF,x
        beq l_ks_t_done
        inx
        bra -

l_ks_t_probe:
        lda #0
        sta $90
        lda l_ks_t_dev
        jsr KERNAL_LISTEN
        lda #$FF                        ; secondary address 15
        jsr KERNAL_SECOND
        jsr KERNAL_READST
        sta l_ks_t_st
        jsr KERNAL_UNLSN

l_ks_t_done:
        sei
        lda l_ks_t_gd030
        sta $d030
        lda l_ks_t_g01
        sta $01
        lda #0                          ; the program's MAP (none)
        tax
        tay
        taz
        map
        eom
        ldx #5
-       lda l_ks_t_gvec,x
        sta $fffa,x
        dex
        bpl -
        lda #$ff
        sta VIC_IRQ_STATUS
        lda l_ks_t_girq
        sta VIC_IRQ_MASK
        plp
        rts

; (running from the program, interrupts off)
l_ks_t_basic:
        lda #$00                        ; boot MAP
        ldx #$e3
        ldy #$00
        ldz #$b3
        map
        eom
        lda #$37
        sta $01
        lda l_ks_t_bd030
        sta $d030
        ldx #$ff
        txs
        lda #$80
        tsb $D05D                       ; hot registers back on
        lda #0
        sta $D054
        jsr KERNAL_IOINIT               ; the interrupts and chips
        jsr KERNAL_CINT                 ; the KERNAL's screen
        ldx #3
-       lda l_ks_t_cp,x
        sta $D068,x
        dex
        bpl -
        ; BASIC's own state back, and return from the SYS
        ldx #2
-       lda KS_SAVE,x
        sta $00,x
        inx
        cpx #$90                        ; (the KERNAL's own part stays as it is now)
        bne -
        ldx #0
-       lda KS_SAVE+256,x
        sta $0100,x
        inx
        bne -
        ldx l_ks_t_sp
        txs
        lda l_ks_t_b01
        sta $01
        lda l_ks_t_bd030
        sta $d030
        cli
        rts

l_ks_t_op:      .byte 0
l_ks_t_ok:      .byte 0
l_ks_t_len:     .byte 0
l_ks_t_sa:      .byte 0
l_ks_t_n:       .byte 0
l_ks_t_i:       .byte 0
l_ks_t_st:      .byte 0
l_ks_t_b01:     .byte 0
l_ks_t_bd030:   .byte 0
l_ks_t_g01:     .byte 0
l_ks_t_gd030:   .byte 0
l_ks_t_girq:    .byte 0
l_ks_t_cp:      .fill 4
l_ks_t_sp:      .byte 0
l_ks_t_dev:
kst_dev:        .byte KS_DEVICE
l_ks_t_nomsg:   .null "74,DRIVE NOT RESPONDING"
l_ks_t_bvec:    .fill 6
l_ks_t_gvec:    .fill 6
        .endlogical
l_ks_size = * - l_ks_src
        .cerror l_ks_size > 768, "kstream trampoline too big for the copy loop"
        .cerror KS_LOW + l_ks_size > KS_SAVE, "kstream trampoline overlaps its save area"
