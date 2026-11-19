;=======================================================================================
; sdwrite.asm - writes a new file (a D64 / D81 image staged in attic) to the SD card's
; FAT32 partition, with raw sector writes: HYPPO can't write files (mkfile / writefile are
; "not implemented"). Used by storage.asm for downloads to the SD card.
;
;   sd_write_file   st_size bytes from ST_ATTIC, as sd_part (an 8.3 name) in the folder whose
;                   first cluster is sd_dircl (0 = the root). The caller has checked that
;                   no file of that name is there. Carry set = failed, A = the status.
;
; The steps, safest order first:
;   1. the MBR and the first FAT32 partition's boot sector (refusing anything unexpected:
;      not 512-byte sectors, not two FATs, missing signatures)
;   2. a run of free clusters long enough for the whole file, contiguous so that HYPPO can
;      mount the image (DISK_FULL if there is none), scanning only real clusters
;   3. the data sectors
;   4. the chain in both FATs (the top 4 bits of each entry kept)
;   5. an 8.3 entry in the folder (DISK_FULL if its clusters are full: it isn't grown)
;   6. FSInfo's free count set to "unknown"
; Every sector of 4-6 is read back and compared. A failure part-way leaves at worst lost
; clusters (marked used, in no file), never a damaged file. Sector 0 of the card (the MBR)
; is only ever read.
;
; (45GS02: no lda/sta abs,z; ldq loads X and Y too, so no Q loads in X-counted loops;
; compares are done a byte at a time.)
;=======================================================================================

SD_CMD          = $d680                 ; write: $02 read, $03 write, $57 open the write gate
SD_SECTOR       = $d681                 ; 4 bytes
SD_BUFSEL       = $d689                 ; bit 7: $FFD6E00 is the SD card's buffer
FW_COPY         = $8140000              ; attic: a sector's copy, to compare after writing
FW_DATE         = (46 << 9) | (11 << 5) | 18    ; a FAT date: 2026-11-18

fw_part:        .dword 0                ; the partition's first sector
fw_fat:         .dword 0                ; FAT 1's first sector
fw_fatsz:       .dword 0                ; sectors in a FAT
fw_data:        .dword 0                ; cluster 2's first sector
fw_root:        .dword 0
fw_end:         .dword 0                ; the last cluster + 1
fw_fsinfo:      .dword 0
fw_shift:       .byte 0                 ; log2 of the sectors a cluster
fw_lba:         .dword 0
fw_c:           .dword 0                ; a cluster
fw_t:           .dword 0                ; (scratch: fw_entry_at and fw_dword use it)
fw_v:           .dword 0                ; a FAT entry's new value
fw_need:        .dword 0                ; clusters for the file
fw_run:         .dword 0                ; the first of the run
fw_len:         .dword 0                ; its length so far
fw_left:        .dword 0
fw_k:           .byte 0
fw_n:           .byte 0
fw_wait:        .fill 3

LSRM    .macro addr                     ; a dword in memory >>= 1 (LSRQ abs)
        .byte $42, $42, $4e
        .word \addr
        .endm
ASLM    .macro addr                     ; <<= 1 (ASLQ abs)
        .byte $42, $42, $0e
        .word \addr
        .endm
; carry set if dword a >= dword b
CMP32   .macro a, b
        lda \a
        cmp \b
        lda \a+1
        sbc \b+1
        lda \a+2
        sbc \b+2
        lda \a+3
        sbc \b+3
        .endm
; dword a += 1 (64tass takes no memory operand for inq)
INC32   .macro a
        inc \a
        bne _x
        inc \a+1
        bne _x
        inc \a+2
        bne _x
        inc \a+3
_x:
        .endm
; Z set if dword a = 0
ZERO32  .macro a
        lda \a
        ora \a+1
        ora \a+2
        ora \a+3
        .endm

;---------------------------------------------------------------------------------------
; the card: sector fw_lba <-> the buffer at $FFD6E00 (BUFSEL set by sd_write_file)
;---------------------------------------------------------------------------------------
fw_busy:                                ; carry set if it stays busy (2-3 s: an SDXC card
        lda #0                          ; may take half a second over a write; one pass
        sta fw_wait                     ; is ~16 cycles, so $60 x 65536 of them at 40 MHz)
        sta fw_wait+1
        lda #$60
        sta fw_wait+2
-       lda SD_CMD
        and #$03
        beq +
        dec fw_wait
        bne -
        dec fw_wait+1
        bne -
        dec fw_wait+2
        bne -
        sec
        rts
+       clc
        rts

fw_setlba:
        ldx #3
-       lda fw_lba,x
        sta SD_SECTOR,x
        dex
        bpl -
        rts

; read sector fw_lba; carry set = failed
fw_read:
        jsr fw_busy
        bcs fw_fail
        jsr fw_setlba
        lda #$02
        sta SD_CMD
fw_done:
        jsr fw_busy
        bcs fw_fail
        lda SD_CMD
        and #$40                        ; error
        bne fw_fail
        clc
        rts
fw_fail:
        sec
        rts

; write the buffer to sector fw_lba (never sector 0); carry set = failed
fw_write:
        #ZERO32 fw_lba
        beq fw_fail
        jsr fw_busy
        bcs fw_fail
        jsr fw_setlba
        lda #$57                        ; the write gate, then the write at once
        sta SD_CMD
        lda #$03
        sta SD_CMD
        bra fw_done

; ptr1 = the buffer, ptr2 = FW_COPY
fw_ptrs:
        lda #<SD_BUF
        sta ptr1
        lda #>SD_BUF
        sta ptr1+1
        lda #(SD_BUF >> 16) & $ff
        sta ptr1+2
        lda #SD_BUF >> 24
        sta ptr1+3
        lda #0
        sta ptr2
        sta ptr2+1
        lda #(FW_COPY >> 16) & $ff
        sta ptr2+2
        lda #FW_COPY >> 24
        sta ptr2+3
        rts

; write the buffer to fw_lba, read it back and compare: carry set = failed
fw_write_check:
        jsr fw_ptrs                     ; keep a copy
        lda #0
        sta tmp5
        lda #2
        sta tmp5+1
        jsr dma_copy_far
        jsr fw_write
        bcs _out
        jsr fw_read
        bcs _out
        jsr fw_ptrs                     ; and compare
        ldx #2
_page:  ldz #0
-       lda [ptr1],z
        cmp [ptr2],z
        bne _bad
        inz
        bne -
        inc ptr1+1
        inc ptr2+1
        dex
        bne _page
        clc
_out:   ldz #0
        rts
_bad:   ldz #0
        sec
        rts

; ptr0 -> the buffer + A/X (an offset 0-511), Z = 0
fw_at:
        sta ptr0
        txa
        clc
        adc #>SD_BUF
        sta ptr0+1
        lda #(SD_BUF >> 16) & $ff
        sta ptr0+2
        lda #SD_BUF >> 24
        sta ptr0+3
        ldz #0
        rts

; fw_t = the dword at buffer offset A/X
fw_dword:
        jsr fw_at
        lda [ptr0],z
        sta fw_t
        inz
        lda [ptr0],z
        sta fw_t+1
        inz
        lda [ptr0],z
        sta fw_t+2
        inz
        lda [ptr0],z
        sta fw_t+3
        ldz #0
        rts

; fw_lba = fw_data + (fw_c - 2) << shift: cluster fw_c's first sector
fw_csect:
        ldq fw_c
        sec
        sbq fw_two
        stq fw_t
        ldx fw_shift
        beq +
-       #ASLM fw_t
        dex
        bne -
+       ldq fw_t
        clc
        adq fw_data
        stq fw_lba
        rts
fw_two:         .dword 2

;---------------------------------------------------------------------------------------
; 1. the partition
;---------------------------------------------------------------------------------------
fw_open:
        lda #0
        ldx #3
-       sta fw_lba,x
        dex
        bpl -
        jsr fw_read                     ; the MBR
        bcs _io
        jsr fw_sig
        bne _io
        #HYPPO H_GETDEFAULTDRIVE        ; HYPPO's drive n = the n-th FAT32 partition: the
        bcc _io                         ; one its folders (and sd_dircl) belong to
        sta fw_n
        lda #0                          ; (type $0B or $0C)
        sta fw_k
_p:     lda fw_k
        asl
        asl
        asl
        asl
        clc
        adc #<(446 + 4)
        ldx #>(446 + 4)
        jsr fw_at
        lda [ptr0],z
        cmp #$0b
        beq _fat32
        cmp #$0c
        bne _np
_fat32: lda fw_n
        beq _found
        dec fw_n
_np:    inc fw_k
        lda fw_k
        cmp #4
        bne _p
_io:    lda #LS_IO_ERROR
        sec
        rts
_found: ldz #4                          ; its first sector
        ldx #0
-       lda [ptr0],z
        sta fw_part,x
        sta fw_lba,x
        inz
        inx
        cpx #4
        bne -
        ldz #0
        jsr fw_read                     ; its boot sector
        bcs _io
        jsr fw_sig
        bne _io
        lda #11                         ; 512 bytes a sector, two FATs
        ldx #0
        jsr fw_at
        lda [ptr0],z
        bne _io
        inz
        lda [ptr0],z
        cmp #2
        bne _io
        ldz #5
        lda [ptr0],z
        cmp #2
        bne _io
        ldz #11                         ; FATSz16 (22) = 0: really FAT32
        lda [ptr0],z
        inz
        ora [ptr0],z
        bne _io
        ldz #29                         ; ExtFlags (40) bit 7: the FATs aren't mirrored
        lda [ptr0],z                    ; (one is active, maybe not the first): refused,
        bmi _io                         ; as the free clusters come from FAT 1
        ldz #2                          ; sectors a cluster: a power of two
        lda [ptr0],z
        ldz #0
        cmp #0
        beq _io
        ldx #0
-       lsr a
        bcs +
        inx
        bra -
+       cmp #0                          ; (another bit set: not a power of two)
        bne _io
        stx fw_shift
        lda #36                         ; the FAT size
        ldx #0
        jsr fw_dword
        ldq fw_t
        stq fw_fatsz
        #ZERO32 fw_fatsz
        bne +
        jmp _iox
+       lda #44                         ; the root's cluster
        ldx #0
        jsr fw_dword
        ldq fw_t
        stq fw_root
        lda #48                         ; FSInfo's sector (16 bits, in the partition)
        ldx #0
        jsr fw_dword
        lda #0
        sta fw_t+2
        sta fw_t+3
        ldq fw_t
        clc
        adq fw_part
        stq fw_fsinfo
        lda #14                         ; the reserved sectors (16 bits)
        ldx #0
        jsr fw_dword
        lda #0
        sta fw_t+2
        sta fw_t+3
        ldq fw_part                     ; FAT 1 = partition + reserved
        clc
        adq fw_t
        stq fw_fat
        clc                             ; data = FAT 1 + two FATs
        adq fw_fatsz
        clc
        adq fw_fatsz
        stq fw_data
        lda #32                         ; clusters = (total - (data - partition)) >> shift
        ldx #0
        jsr fw_dword
        ldq fw_t
        sec
        sbq fw_data
        clc
        adq fw_part
        stq fw_t
        ldx fw_shift
        beq +
-       #LSRM fw_t
        dex
        bne -
+       ldq fw_t                        ; (and the last cluster + 1 = that + 2)
        clc
        adq fw_two
        stq fw_end
        ldq fw_fatsz                    ; a FAT has an entry for every cluster: 128 a
        stq fw_v                        ; sector (fw_v is free until the chain)
        ldx #7
-       #ASLM fw_v
        dex
        bne -
        ldq fw_v
        clc
        adq fw_two
        stq fw_v
        #CMP32 fw_v, fw_end             ; carry clear: more clusters than entries
        bcc _iox
        #CMP32 fw_root, fw_end          ; the root is one of the clusters (2 and up)
        bcs _iox
        lda fw_root+3
        ora fw_root+2
        ora fw_root+1
        bne +
        lda fw_root
        cmp #2
        bcc _iox
+       clc
        rts
_iox:   lda #LS_IO_ERROR
        sec
        rts

; Z clear if the buffer doesn't end in $55 $AA
fw_sig:
        lda #<510
        ldx #>510
        jsr fw_at
        lda [ptr0],z
        cmp #$55
        bne +
        inz
        lda [ptr0],z
        ldz #0
        cmp #$aa
+       rts

;---------------------------------------------------------------------------------------
; FAT entries
;---------------------------------------------------------------------------------------
; fw_c -> fw_lba = its FAT sector in FAT fw_k (0 or 1); ptr0 = its entry in the buffer
fw_entry_at:
        lda fw_c                        ; c >> 7 = the bytes of c << 1, one up
        asl
        lda fw_c+1
        rol
        sta fw_t
        lda fw_c+2
        rol
        sta fw_t+1
        lda fw_c+3
        rol
        sta fw_t+2
        lda #0
        rol
        sta fw_t+3
        ldq fw_t
        clc
        adq fw_fat
        stq fw_lba
        lda fw_k
        beq +
        ldq fw_lba
        clc
        adq fw_fatsz
        stq fw_lba
+       lda fw_c                        ; (c & 127) * 4
        and #$7f
        asl
        asl
        sta fw_n
        lda #0
        rol
        tax
        lda fw_n
        jmp fw_at

; the entry at ptr0 = fw_v (its top 4 bits kept)
fw_put_entry:
        lda fw_v
        sta [ptr0],z
        inz
        lda fw_v+1
        sta [ptr0],z
        inz
        lda fw_v+2
        sta [ptr0],z
        inz
        lda [ptr0],z
        and #$f0
        ora fw_v+3
        sta [ptr0],z
        ldz #0
        rts

;---------------------------------------------------------------------------------------
; 2. a run of fw_need free clusters -> fw_run
;---------------------------------------------------------------------------------------
fw_find_run:
        lda #2
        sta fw_c
        lda #0
        sta fw_c+1
        sta fw_c+2
        sta fw_c+3
        sta fw_k
        sta fw_len
        sta fw_len+1
        sta fw_len+2
        sta fw_len+3
_sect:  jsr fw_entry_at                 ; a new FAT sector
        jsr fw_read
        bcc _scan
        lda #LS_IO_ERROR
        rts
_scan:  #CMP32 fw_c, fw_end             ; past the last cluster: no room
        bcs _full
        jsr fw_entry_at                 ; (ptr0 only: the sector is in)
        ldz #3
        lda [ptr0],z
        and #$0f
        dez
        ora [ptr0],z
        dez
        ora [ptr0],z
        dez
        ora [ptr0],z
        ldz #0
        cmp #0
        bne _used
        #ZERO32 fw_len                  ; free: a run starts or goes on
        bne +
        ldq fw_c
        stq fw_run
+       #INC32 fw_len
        #CMP32 fw_len, fw_need
        bcs _got
        bra _next
_used:  lda #0
        sta fw_len
        sta fw_len+1
        sta fw_len+2
        sta fw_len+3
_next:  #INC32 fw_c
        lda fw_c
        and #$7f
        bne _scan
        bra _sect
_got:   clc
        rts
_full:  lda #LS_DISK_FULL
        sec
        rts

;---------------------------------------------------------------------------------------
; the whole file
;---------------------------------------------------------------------------------------
sd_write_file:
        lda SD_BUFSEL
        pha
        ora #$80
        sta SD_BUFSEL
        jsr fw_steps
        tax
        pla
        sta SD_BUFSEL
        txa
        rts

fw_steps:
        jsr fw_open
        bcs _out
        clc                             ; sectors = (size + 511) >> 9
        lda st_size
        adc #<511
        lda st_size+1
        adc #>511
        sta fw_need
        lda st_size+2
        adc #0
        sta fw_need+1
        lda #0
        adc #0
        sta fw_need+2
        lda #0
        sta fw_need+3
        #LSRM fw_need
        lda #1                          ; clusters = (sectors + spc - 1) >> shift
        ldx fw_shift
        beq +
-       asl a
        dex
        bne -
+       sec
        sbc #1
        clc
        adc fw_need
        sta fw_need
        bcc +
        inc fw_need+1
        bne +
        inc fw_need+2
+       ldx fw_shift
        beq +
-       #LSRM fw_need
        dex
        bne -
+       #ZERO32 fw_need
        bne +
        inc fw_need                     ; (an empty file still gets a cluster)
+       jsr fw_find_run
        bcs _out
        jsr fw_put_data
        bcs _out
        jsr fw_put_chain
        bcs _out
        jsr fw_put_dir_entry
        bcs _out
        jmp fw_put_fsinfo
_out:   rts

;---------------------------------------------------------------------------------------
; 3. the data: sectors from cluster fw_run on
;---------------------------------------------------------------------------------------
fw_put_data:
        ldq fw_run
        stq fw_c
        jsr fw_csect
        jsr st_start                    ; (pos from 0)
_sect:  sec                             ; what's left
        lda st_size
        sbc st_pos
        sta fw_left
        lda st_size+1
        sbc st_pos+1
        sta fw_left+1
        lda st_size+2
        sbc st_pos+2
        sta fw_left+2
        ora fw_left+1
        ora fw_left
        bne +
        clc
        rts
+       lda #0                          ; a sector of zeros, then up to 512 bytes over them
        sta tmp4
        lda #>SD_BUF
        sta tmp4+1
        lda #0
        sta tmp5
        lda #2
        sta tmp5+1
        lda #0
        ldx #SD_BUF >> 20
        ldy #(SD_BUF >> 16) & $0f
        jsr dma_fill
        lda #0
        sta st_n
        lda #2
        sta st_n+1
        lda fw_left+2
        bne +
        lda fw_left+1
        cmp #2
        bcs +
        lda fw_left                     ; (the last, short one)
        sta st_n
        lda fw_left+1
        sta st_n+1
+       jsr st_attic_ptrs
        lda #<SD_BUF
        sta ptr2
        lda #>SD_BUF
        sta ptr2+1
        lda #(SD_BUF >> 16) & $ff
        sta ptr2+2
        lda #SD_BUF >> 24
        sta ptr2+3
        lda st_n
        sta tmp5
        lda st_n+1
        sta tmp5+1
        jsr dma_copy_far
        jsr fw_write
        bcs _bad
        jsr st_advance
        #INC32 fw_lba
        bra _sect
_bad:   lda #LS_IO_ERROR
        rts

;---------------------------------------------------------------------------------------
; 4. the chain: run -> run+1 -> ... -> the end; in FAT 1, then the same in FAT 2
;---------------------------------------------------------------------------------------
fw_put_chain:
        lda #0
        sta fw_k
_fat:   ldq fw_run
        stq fw_c
        ldq fw_need
        stq fw_left
_sect:  jsr fw_entry_at                 ; the sector with fw_c's entry
        jsr fw_read
        bcs _bad
_ent:   lda fw_left                     ; the last one: the end of the chain
        cmp #1
        bne _next
        lda fw_left+1
        ora fw_left+2
        ora fw_left+3
        bne _next
        lda #$ff
        sta fw_v
        sta fw_v+1
        sta fw_v+2
        lda #$0f
        sta fw_v+3
        bra +
_next:  ldq fw_c                        ; otherwise the next cluster
        clc
        adq fw_one
        stq fw_v
+       jsr fw_entry_at                 ; (ptr0 for fw_c)
        jsr fw_put_entry
        ldq fw_left
        sec
        sbq fw_one
        stq fw_left
        #ZERO32 fw_left
        beq _write                      ; all done: write this sector
        #INC32 fw_c
        lda fw_c                        ; still in this sector?
        and #$7f
        bne _ent
        jsr fw_back                     ; no: write it (fw_lba of fw_c - 1), on to the next
        bcs _bad
        #INC32 fw_c
        bra _sect
_write: #INC32 fw_c
        jsr fw_back
        bcs _bad
        inc fw_k
        lda fw_k
        cmp #2
        bne _fat
        clc
        rts
_bad:   lda #LS_IO_ERROR
        sec
        rts
; write and check the FAT sector holding fw_c - 1
fw_back:
        ldq fw_c
        sec
        sbq fw_one
        stq fw_c
        jsr fw_entry_at
        jmp fw_write_check
fw_one:         .dword 1

;---------------------------------------------------------------------------------------
; 5. the folder entry: the first free slot in the folder's clusters
;---------------------------------------------------------------------------------------
fw_put_dir_entry:
        ldq sd_dircl
        stq fw_c
        #ZERO32 fw_c
        bne _sub
        ldq fw_root
        stq fw_c
        bra _clus
_sub:   jsr fw_self                     ; (a folder of this partition, or write nothing)
        bcs _bad
_clus:  jsr fw_csect                    ; its first sector
        lda #1                          ; sectors in a cluster
        ldx fw_shift
        beq +
-       asl a
        dex
        bne -
+       sta fw_len
_sect:  jsr fw_read
        bcs _bad
        lda #0
        sta fw_n                        ; slot 0-15
_slot:  lda fw_n
        asl
        asl
        asl
        asl
        asl                             ; * 32: carry = bit 8
        ldx #0
        bcc +
        inx
+       jsr fw_at
        lda [ptr0],z
        beq _here
        cmp #$e5
        beq _here
        inc fw_n
        lda fw_n
        cmp #16
        bne _slot
        #INC32 fw_lba
        dec fw_len
        bne _sect
        lda #0                          ; the cluster is full: the folder's next one
        sta fw_k
        jsr fw_entry_at
        jsr fw_read
        bcs _bad
        jsr fw_entry_at
        lda [ptr0],z
        sta fw_c
        inz
        lda [ptr0],z
        sta fw_c+1
        inz
        lda [ptr0],z
        sta fw_c+2
        inz
        lda [ptr0],z
        and #$0f
        sta fw_c+3
        ldz #0
        cmp #$0f                        ; the end of the chain: no free slot
        beq _full
        lda fw_c+3                      ; (0 or 1: not a chain at all)
        ora fw_c+2
        ora fw_c+1
        bne _chain
        lda fw_c
        cmp #2
        bcc _full
_chain: #CMP32 fw_c, fw_end             ; past the last cluster: a damaged chain, and no
        bcs _bad                        ; writing to wherever it points
        jmp _clus
_full:  lda #LS_DISK_FULL
        sec
        rts
_bad:   lda #LS_IO_ERROR
        sec
        rts
_here:  lda #' '                        ; 32 bytes: the name, archive, the date, the
-       sta [ptr0],z                    ; cluster, the size
        inz
        cpz #11
        bne -
        lda #0
-       sta [ptr0],z
        inz
        cpz #32
        bne -
        ldx #0                          ; NAME.EXT -> "NAME    EXT"
        ldz #0
-       lda sd_part,x
        beq _ext
        cmp #'.'
        beq _dot
        sta [ptr0],z
        inx
        inz
        cpz #8
        bne -
-       lda sd_part,x                   ; (a name of 8: on to its dot)
        beq _ext
        cmp #'.'
        beq _dot
        inx
        bra -
_dot:   inx
        ldz #8
-       lda sd_part,x
        beq _ext
        sta [ptr0],z
        inx
        inz
        cpz #11
        bne -
_ext:   ldz #11
        lda #$20                        ; archive
        sta [ptr0],z
        lda #<FW_DATE                   ; created, accessed, written: the date
        ldz #16
        sta [ptr0],z
        ldz #18
        sta [ptr0],z
        ldz #24
        sta [ptr0],z
        lda #>FW_DATE
        ldz #17
        sta [ptr0],z
        ldz #19
        sta [ptr0],z
        ldz #25
        sta [ptr0],z
        ldz #20                         ; the first cluster: high word at +20, low at +26
        lda fw_run+2
        sta [ptr0],z
        inz
        lda fw_run+3
        sta [ptr0],z
        ldz #26
        lda fw_run
        sta [ptr0],z
        inz
        lda fw_run+1
        sta [ptr0],z
        ldz #28                         ; the size
        lda st_size
        sta [ptr0],z
        inz
        lda st_size+1
        sta [ptr0],z
        inz
        lda st_size+2
        sta [ptr0],z
        ldz #0
        jsr fw_write_check
        bcs _bad
        clc
        rts

; carry clear if cluster fw_c starts a folder of this partition: its first entry is "."
; pointing at itself
fw_self:
        jsr fw_csect
        jsr fw_read
        bcs _no
        lda #0
        tax
        jsr fw_at
        lda [ptr0],z
        cmp #'.'
        bne _no
        inz
        lda [ptr0],z
        cmp #' '
        bne _no
        ldz #11
        lda [ptr0],z
        and #$10
        beq _no
        ldz #26
        lda [ptr0],z
        cmp fw_c
        bne _no
        inz
        lda [ptr0],z
        cmp fw_c+1
        bne _no
        ldz #20
        lda [ptr0],z
        cmp fw_c+2
        bne _no
        inz
        lda [ptr0],z
        cmp fw_c+3
        bne _no
        ldz #0
        clc
        rts
_no:    ldz #0
        sec
        rts

;---------------------------------------------------------------------------------------
; 6. FSInfo: the free count becomes "unknown" ($FFFFFFFF), as the spec allows
;---------------------------------------------------------------------------------------
fw_put_fsinfo:
        ldq fw_fsinfo
        stq fw_lba
        jsr fw_read
        bcs _skip
        lda #0                          ; its signatures, or leave it alone
        ldx #0
        jsr fw_dword
        ldx #3
-       lda fw_t,x
        cmp fw_fsi1,x
        bne _skip
        dex
        bpl -
        lda #<484
        ldx #>484
        jsr fw_dword
        ldx #3
-       lda fw_t,x
        cmp fw_fsi2,x
        bne _skip
        dex
        bpl -
        lda #<488
        ldx #>488
        jsr fw_at
        lda #$ff
        ldz #3
-       sta [ptr0],z
        dez
        bpl -
        ldz #0
        jsr fw_write_check
        bcs _bad
_skip:  clc
        rts
_bad:   lda #LS_IO_ERROR
        sec
        rts
fw_fsi1:        .dword $41615252
fw_fsi2:        .dword $61417272
