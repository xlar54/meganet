;=======================================================================================
; storage.asm - the MEGA65's own disks, for the server's File Library (docs/DESIGN.md,
; "Local storage"; server-src/meganet/filelib.py drives it). The server asks, this answers:
;
;   S.LOCAL_DIR     a drive's directory (lib/kstream.asm: OPEN "$") or an SD card folder
;                   (HYPPO opendir / readdir): C.LOCAL_ENTRY each, then C.LOCAL_DONE
;   S.SAVE_BEGIN    checks it can (the drive answers, no file of that name) and answers
;                   C.FILE_ACK 0; then FILE_DATA chunks are staged in attic (ST_ATTIC) with
;                   the CRC-32 kept as they come, each acknowledged; FILE_END checks the CRC
;                   and writes the file to the drive (kstream, "NAME,P,W")
;   S.LOAD_FILE     a drive file (kstream) or an SD card file (HYPPO openfile / readfile)
;                   read into attic; C.UP_BEGIN, then storage_frame sends C.UP_DATA a few
;                   frames a frame (the GUI keeps going), then C.UP_END with the CRC
;   S.LOCAL_CANCEL  stop
;
; One request at a time: a new one ends the last. SD paths are folder names from the root
; ("GAMES/ELITE.D81"), each matched against the 8.3 names readdir gives, so any case of
; long name works (HYPPO's findfile only finds upper-case long names).
;
;   storage_frame   from the main loop: sends the upload, if one is going
;=======================================================================================

ST_ATTIC        = $8300000              ; staging: 1 MB (protocol.LOCAL_MAX)
ST_DIRENT       = KS_BUF                ; HYPPO readdir's page ($1C00: kstream is idle then)
SD_BUF          = $FFD6E00              ; the SD card's sector buffer (HYPPO readfile)
UP_CHUNK        = 240
UP_PER_FRAME    = 4                     ; C.UP_DATA frames a main-loop pass

S_FILE_DATA     = $21
S_FILE_END      = $22
S_LOCAL_DIR     = $25
S_SAVE_BEGIN    = $26
S_LOAD_FILE     = $27
S_LOCAL_CANCEL  = $28
C_FILE_ACK      = $88
C_LOCAL_ENTRY   = $8d
C_LOCAL_DONE    = $8e
C_UP_BEGIN      = $90
C_UP_DATA       = $91
C_UP_END        = $92
CLIENT_CAPS     = 15                    ; protocol.Caps: DRIVES | SD_READ | SD_WRITE | GRID

; protocol.Local
LK_HEADER       = 0
LK_DIR          = 1
LK_PRG          = 2
LK_SEQ          = 3
LK_USR          = 4
LK_REL          = 5
LK_DEL          = 6
LK_D81          = 7
LK_D64          = 8
LK_FILE         = 9
LK_FREE         = 15
; protocol.LocalStatus
LS_OK           = 0
LS_NO_DEVICE    = 1
LS_NOT_FOUND    = 2
LS_EXISTS       = 3
LS_DISK_FULL    = 4
LS_BAD_CRC      = 5
LS_IO_ERROR     = 6
LS_UNSUPPORTED  = 7
LS_TOO_BIG      = 8

HYPPO   .macro n
        lda #\n
        sta HTRAP00
        clv
        .endm
H_GETDEFAULTDRIVE = $02
H_CHDIR         = $0C
H_OPENDIR       = $12
H_READDIR       = $14
H_CLOSEDIR      = $16
H_OPENFILE      = $18
H_READFILE      = $1A
H_CLOSEFILE     = $20
H_CDROOTDIR     = $3C

st_mode:        .byte 0                 ; 0 idle, 1 a download arriving, 2 an upload going
st_req:         .byte 0
st_dev:         .byte 0
st_kind:        .byte 0
st_size:        .fill 3                 ; (24 bits: files are at most 1 MB)
st_pos:         .fill 3
st_crc:         .fill 4                 ; running (inverted) CRC-32
st_cn:          .word 0                 ; crc_add's count
st_n:           .word 0
st_t0:          .byte 0
st_t1:          .byte 0
st_t2:          .byte 0
ST_PATH_MAX     = 127                   ; (filelib.LOCAL_PATH_MAX)
st_path:        .fill ST_PATH_MAX + 1

;---------------------------------------------------------------------------------------
; the requests
;---------------------------------------------------------------------------------------
; u8 req, u8 dev (for every request): a new one ends any other
st_head:
        jsr rd_u8
        sta st_req
        jsr rd_u8
        sta st_dev
        lda #0
        sta st_mode
        rts

; the string just read (str_buf) -> st_path. Carry set if it's longer than ST_PATH_MAX
; (refused: a path cut short would name somewhere else)
st_copy_path:
        ldx #0
-       lda str_buf,x
        sta st_path,x
        beq +
        inx
        cpx #ST_PATH_MAX + 1
        bne -
        lda #0
        sta st_path
        sec
        rts
+       clc
        rts

; st_path as a CBM drive's file name: 1-16 characters, none of * ? , : = " and not starting
; with @ $ # (the DOS reads those as wildcards and commands: "*" would scratch every
; file). The server checks this too (filelib.check_cbm_name). Carry set if not
st_cbm_ok:
        lda st_path
        ldy #2
-       cmp _first,y
        beq _no
        dey
        bpl -
        ldx #0
_ch:    lda st_path,x
        beq _end
        ldy #5
-       cmp _bad,y
        beq _no
        dey
        bpl -
        inx
        cpx #17
        bne _ch
_no:    sec
        rts
_end:   txa
        beq _no
        clc
        rts
_first: .text "@$#"
_bad:   .text "*?,:=", $22

; u8 req: stop it
pm_local_cancel:
        jsr rd_u8
        cmp st_req
        bne +
        lda #0
        sta st_mode
+       rts

; A = status: C.LOCAL_DONE with no text
st_done:
        ldx #<st_empty
        ldy #>st_empty
; A = status, X/Y = the text (zero-terminated)
st_done_text:
        sta st_t0
        stx st_t1
        sty st_t2
        jsr disk_end                    ; (the framebuffer back, if a drive was used)
        lda #0
        sta st_mode
        lda #C_LOCAL_DONE
        jsr tx_begin
        lda st_req
        jsr tx_u8
        lda st_t0
        jsr tx_u8
        lda st_t1
        ldx st_t2
        jsr tx_str
        jmp tx_end
st_empty:       .byte 0
; the drive said something (A = its number, KS_BUF its text): IO_ERROR, NOT_FOUND, DISK_FULL
st_drive_said:
        ldx #LS_NOT_FOUND
        cmp #62
        beq +
        ldx #LS_DISK_FULL
        cmp #72
        beq +
        ldx #LS_EXISTS
        cmp #63
        beq +
        ldx #LS_IO_ERROR
+       txa
        ldx #<KS_BUF
        ldy #>KS_BUF
        jmp st_done_text

; st_dev = a drive unit (8-11) -> kst_dev; carry set if nothing answers there (or it has
; no disk: 74), with the drive's text in KS_BUF. First the ROM goes back for the KERNAL
; (exit.asm disk_begin; whatever ends the request calls disk_end).
st_unit:
        lda st_dev
        cmp #8
        bcc _none
        cmp #12
        bcs _none
        sta kst_dev
        jsr disk_begin
        jsr kst_status
        cmp #74
        beq +
        clc
        rts
+       sec
        rts
_none:  lda #0                          ; (not a drive number: no drive text either)
        sta KS_BUF
        sec
        rts
; st_unit failed: C.LOCAL_DONE NO_DEVICE with what the drive said
st_no_unit:
        lda #LS_NO_DEVICE
        ldx #<KS_BUF
        ldy #>KS_BUF
        jmp st_done_text

; pos = 0, the CRC started
st_start:
        lda #0
        sta st_pos
        sta st_pos+1
        sta st_pos+2
        lda #$ff
        sta st_crc
        sta st_crc+1
        sta st_crc+2
        sta st_crc+3
        rts

; pos += st_n (16 bits)
st_advance:
        clc
        lda st_pos
        adc st_n
        sta st_pos
        lda st_pos+1
        adc st_n+1
        sta st_pos+1
        lda st_pos+2
        adc #0
        sta st_pos+2
        rts

; carry set if pos is past LOCAL_MAX (1 MB)
st_too_far:
        lda st_pos+2
        cmp #$10
        bcc _ok
        bne _far
        lda st_pos
        ora st_pos+1
        bne _far
_ok:    clc
        rts
_far:   sec
        rts

; ptr2 = ST_ATTIC + pos (a DMA destination), ptr1 = the same (a source)
st_attic_ptrs:
        lda st_pos
        sta ptr1
        sta ptr2
        lda st_pos+1
        sta ptr1+1
        sta ptr2+1
        lda st_pos+2
        clc
        adc #(ST_ATTIC >> 16) & $ff
        sta ptr1+2
        sta ptr2+2
        lda #ST_ATTIC >> 24
        sta ptr1+3
        sta ptr2+3
        rts

; A/X = a bank-0 address -> the other pointer of a DMA: ptr1 (st_from) or ptr2 (st_to)
st_from:
        sta ptr1
        stx ptr1+1
        lda #0
        sta ptr1+2
        sta ptr1+3
        rts
st_to:
        sta ptr2
        stx ptr2+1
        lda #0
        sta ptr2+2
        sta ptr2+3
        rts

; send the u32 pos
tx_pos:
        lda st_pos
        ldx st_pos+1
        jsr tx_u16
        lda st_pos+2
        ldx #0
        jmp tx_u16

; the CRC-32 (zlib's) of st_cn bytes at (tmp7), into st_crc (kept inverted: the final
; value is st_crc ^ $FFFFFFFF). Bit by bit: about 9 ms a KB at 40 MHz.
crc_add:
        lda st_cn
        ora st_cn+1
        beq _out
        ldy #0
        lda (tmp7),y
        eor st_crc
        sta st_crc
        ldx #8
_bit:   lsr st_crc+3
        ror st_crc+2
        ror st_crc+1
        ror st_crc
        bcc +
        lda st_crc+3
        eor #$ed
        sta st_crc+3
        lda st_crc+2
        eor #$b8
        sta st_crc+2
        lda st_crc+1
        eor #$83
        sta st_crc+1
        lda st_crc
        eor #$20
        sta st_crc
+       dex
        bne _bit
        inw tmp7
        lda st_cn
        bne +
        dec st_cn+1
+       dec st_cn
        bra crc_add
_out:   rts

;---------------------------------------------------------------------------------------
; S.LOCAL_DIR: u8 req, u8 dev, str path
;---------------------------------------------------------------------------------------
pm_local_dir:
        jsr st_head
        ldx #0
        jsr rd_str
        jsr st_copy_path
        bcs _long
        lda st_dev
        bne dir_drive
        jmp dir_sd
_long:  lda #LS_UNSUPPORTED
        jmp st_done

dir_drive:
        jsr st_unit
        bcc +
        jmp st_no_unit
+       lda #'$'
        sta kst_name
        lda #0
        sta kst_sa
        lda #1
        jsr kst_open
        bcc +
        lda #LS_IO_ERROR
        jmp st_done
+       jsr kst_rewind
        jsr kst_getc                    ; the load address
        jsr kst_getc
        lda #1
        sta dd_first
_line:  jsr kst_getc                    ; the link: 0 0 at the end
        bcs _end
        sta dd_t
        jsr kst_getc
        bcs _end
        ora dd_t
        beq _end
        jsr kst_getc                    ; the blocks
        bcs _end
        sta st_size
        jsr kst_getc
        bcs _end
        sta st_size+1
        lda #0
        sta dd_n
-       jsr kst_getc                    ; the text, to its 0
        bcs _end
        cmp #0
        beq +
        ldx dd_n
        cpx #39
        bcs -
        sta dd_text,x
        inc dd_n
        bra -
+       ldx dd_n
        sta dd_text,x
        jsr dd_entry
        bra _line
_end:   jsr kst_close
        jsr kst_status
        cmp #20                         ; 00-19: fine; 73: the power-on message
        bcc +
        cmp #73
        beq +
        jmp st_drive_said
+       lda #LS_OK
        jmp st_done

; one line of the listing (dd_text, st_size = its blocks): the header, a file, or the
; blocks free
dd_entry:
        ldx #0                          ; the first quote
-       lda dd_text,x
        beq _free
        cmp #'"'
        beq +
        inx
        bra -
+       ldy #0                          ; the name, to the next quote
        inx
-       lda dd_text,x
        beq _q
        cmp #'"'
        beq _q
        jsr pet2asc
        sta dd_name,y
        iny
        inx
        cpy #16
        bne -
-       lda dd_text,x                   ; (a name longer than 16: to its quote)
        beq _q
        cmp #'"'
        beq _q
        inx
        bra -
_q:     lda #0
        sta dd_name,y
        lda dd_first
        beq _file
        lda #0
        sta dd_first
-       dey                             ; the disk name: without its padding
        bmi +
        lda dd_name,y
        cmp #' '
        bne +
        lda #0
        sta dd_name,y
        bra -
+       lda #0
        sta st_size
        sta st_size+1
        lda #LK_HEADER
        jmp dd_send
_file:  lda dd_text,x                   ; after the name: spaces, maybe *, the type
        beq _skip
        inx
-       lda dd_text,x
        cmp #' '
        beq +
        cmp #'*'
        bne ++
+       inx
        bra -
+       ldy #0
_type:  lda dd_types,y
        beq _skip
        cmp dd_text,x
        bne _nt
        lda dd_types+1,y
        cmp dd_text+1,x
        bne _nt
        lda dd_types+2,y
        cmp dd_text+2,x
        bne _nt
        lda dd_types+3,y
        jmp dd_send
_nt:    iny
        iny
        iny
        iny
        bra _type
_skip:  rts
_free:  lda dd_first                    ; no quotes: "BLOCKS FREE."
        bne _skip
        lda #<dd_free
        ldx #>dd_free
        ldy #LK_FREE
        jmp dd_send_name
dd_types:       .text "PRG", LK_PRG, "SEQ", LK_SEQ, "USR", LK_USR, "REL", LK_REL
                .text "DEL", LK_DEL, 0
dd_free:        .null "BLOCKS FREE."

; A = kind: C.LOCAL_ENTRY with st_size (blocks) and dd_name
dd_send:
        tay
        lda #<dd_name
        ldx #>dd_name
; Y = kind, A/X = the name
dd_send_name:
        sta st_t1
        stx st_t2
        sty st_t0
        lda #C_LOCAL_ENTRY
        jsr tx_begin
        lda st_req
        jsr tx_u8
        lda st_t0
        jsr tx_u8
        lda st_size
        ldx st_size+1
        jsr tx_u16
        lda #0
        tax
        jsr tx_u16
        lda st_t1
        ldx st_t2
        jsr tx_str
        jmp tx_end

; a PETSCII byte of a file name -> what the server sees (kstream's convention, backwards:
; $41-$5A are A-Z, $C1-$DA a-z); anything else unprintable is ?
pet2asc:
        cmp #$c1
        bcc +
        cmp #$db
        bcs _q
        sec
        sbc #$60
        rts
+       cmp #$20
        bcc _q
        cmp #$5e
        bcs _q
        rts
_q:     lda #'?'
        rts

dd_first:       .byte 0
dd_t:           .byte 0
dd_n:           .byte 0
dd_text:        .fill 40
dd_name:        .fill 17

;---------------------------------------------------------------------------------------
; the SD card (HYPPO): folders and reading files
;---------------------------------------------------------------------------------------
dir_sd:
        lda #0
        sta sd_leaf
        jsr sd_walk
        bcc +
        jmp st_done
+       #HYPPO H_OPENDIR
        bcs +
        jsr sd_root
        lda #LS_IO_ERROR
        jmp st_done
+       sta sd_fd
_next:  ldx sd_fd
        ldy #>ST_DIRENT
        #HYPPO H_READDIR
        bcc _end
        jsr sd_entry
        bra _next
_end:   ldx sd_fd
        #HYPPO H_CLOSEDIR
        jsr sd_root
        lda #LS_OK
        jmp st_done

; the entry readdir gave: C.LOCAL_ENTRY (8.3 name, long name), unless it's a volume label
; or . / ..
sd_entry:
        lda ST_DIRENT+$56
        and #$08
        bne _skip
        jsr sd_fmt
        lda sd_name
        cmp #'.'
        beq _skip
        ldy #LK_DIR
        lda ST_DIRENT+$56
        and #$10
        bne _kind
        ldy #LK_FILE
        lda ST_DIRENT+$49
        cmp #'D'
        bne _kind
        lda ST_DIRENT+$4a
        cmp #'8'
        bne +
        lda ST_DIRENT+$4b
        cmp #'1'
        bne _kind
        ldy #LK_D81
        bra _kind
+       cmp #'6'
        bne _kind
        lda ST_DIRENT+$4b
        cmp #'4'
        bne _kind
        ldy #LK_D64
_kind:  sty st_t0
        lda #0
        sta ST_DIRENT+$3f               ; (the long name ends in the 64 bytes,
        ldx ST_DIRENT+$40               ; and at its length, +$40: readdir needn't clear
        cpx #$3f                        ; what's after it)
        bcs +
        sta ST_DIRENT,x
+       lda #C_LOCAL_ENTRY
        jsr tx_begin
        lda st_req
        jsr tx_u8
        lda st_t0
        jsr tx_u8
        lda ST_DIRENT+$52
        ldx ST_DIRENT+$53
        jsr tx_u16
        lda ST_DIRENT+$54
        ldx ST_DIRENT+$55
        jsr tx_u16
        lda #<sd_name
        ldx #>sd_name
        jsr tx_str
        lda #<ST_DIRENT
        ldx #>ST_DIRENT
        jsr tx_str
        jmp tx_end
_skip:  rts

; the 8.3 name of the entry readdir gave -> sd_name: NAME.EXT, without the padding
sd_fmt:
        ldx #0
        ldy #0
-       lda ST_DIRENT+$41,x
        cmp #' '
        beq +
        sta sd_name,y
        iny
+       inx
        cpx #8
        bne -
        lda ST_DIRENT+$49
        cmp #' '
        beq _end
        lda #'.'
        sta sd_name,y
        iny
        ldx #0
-       lda ST_DIRENT+$49,x
        cmp #' '
        beq +
        sta sd_name,y
        iny
+       inx
        cpx #3
        bne -
_end:   lda #0
        sta sd_name,y
        rts

; back to the root of the default drive (HYPPO's current folder as we found it)
sd_root:
        #HYPPO H_GETDEFAULTDRIVE
        bcc +
        tax
        #HYPPO H_CDROOTDIR
+       rts

; into the folders of st_path from the root. sd_leaf = 1: all but the last part, which is
; then in sd_part. Carry set = failed, A = the status (and back at the root)
sd_walk:
        #HYPPO H_GETDEFAULTDRIVE
        bcc _nodev
        tax
        #HYPPO H_CDROOTDIR
        bcc _nodev
        lda #0
        sta sd_i
        sta sd_long
        sta sd_part                     ; (no stale name if the path is empty)
        sta sd_dircl                    ; (the folder we end in: 0 = the root)
        sta sd_dircl+1
        sta sd_dircl+2
        sta sd_dircl+3
_part:  jsr sd_next_part
        bcs _done
        lda sd_long                     ; a part longer than 8.3: nothing can match it
        bne _long
        lda sd_leaf
        beq +
        ldx sd_i                        ; the last part: the file
        lda st_path,x
        beq _done
+       jsr sd_find
        bcs _fail
        lda ST_DIRENT+$56
        and #$10
        beq _nf
        ldx #3                          ; its first cluster, for sdwrite.asm
-       lda ST_DIRENT+$4e,x
        sta sd_dircl,x
        dex
        bpl -
        #HYPPO H_CHDIR
        php
        ldx sd_fd
        #HYPPO H_CLOSEDIR
        plp
        bcs _part
        jsr sd_root
        lda #LS_IO_ERROR
        sec
        rts
_nf:    ldx sd_fd
        #HYPPO H_CLOSEDIR
        jsr sd_root
        lda #LS_NOT_FOUND
        sec
        rts
_fail:  pha
        jsr sd_root
        pla
        sec
        rts
_done:  clc
        rts
_nodev: lda #LS_NO_DEVICE
        sec
        rts
_long:  jsr sd_root
        lda #LS_NOT_FOUND
        sec
        rts

; the next part of st_path (from sd_i, to a / or the end) -> sd_part, upper case. Carry
; set when there are none left
sd_next_part:
        ldx sd_i
        lda st_path,x
        bne +
        sec
        rts
+       ldy #0
-       lda st_path,x
        beq _end
        inx
        cmp #'/'
        beq _end
        cmp #'a'
        bcc +
        cmp #'z'+1
        bcs +
        and #$df
+       cpy #12
        bcs _lng
        sta sd_part,y
        iny
        bra -
_lng:   lda #1                          ; too long for an 8.3 name: sd_walk refuses it
        sta sd_long                     ; (it isn't cut short to something that matches)
        bra -
_end:   stx sd_i
        lda #0
        sta sd_part,y
        clc
        rts

; find sd_part in the current folder: carry clear = found, its entry in ST_DIRENT and the
; folder still open (sd_fd); carry set = A is the status (the folder closed)
sd_find:
        #HYPPO H_OPENDIR
        bcs +
        lda #LS_IO_ERROR
        sec
        rts
+       sta sd_fd
_next:  ldx sd_fd
        ldy #>ST_DIRENT
        #HYPPO H_READDIR
        bcc _nf
        lda ST_DIRENT+$56
        and #$08
        bne _next
        jsr sd_fmt
        ldx #0
-       lda sd_name,x
        cmp sd_part,x
        bne _next
        inx
        cmp #0
        bne -
        clc
        rts
_nf:    ldx sd_fd
        #HYPPO H_CLOSEDIR
        lda #LS_NOT_FOUND
        sec
        rts

sd_err:         .byte 0, 0                  ; HYPPO's last openfile / readfile A (tests)
; st_path on the SD card: a D64 or D81, its folders there (sd_dircl = the last one's first
; cluster), and no file of its name (sd_part). Carry set = no, A = the status; back at the
; root either way
sd_check_new:
        lda st_kind
        cmp #LK_D81
        beq +
        cmp #LK_D64
        beq +
        lda #LS_UNSUPPORTED
        sec
        rts
+       lda #1
        sta sd_leaf
        jsr sd_walk
        bcs _out
        jsr sd_valid_name               ; a real 8.3 name with the right extension (the
        bcc +                           ; server checks it too: sdwrite.asm writes it as is)
        jsr sd_root
        lda #LS_UNSUPPORTED
        sec
        rts
+       jsr sd_find
        bcs _nf
        ldx sd_fd                       ; it's there
        #HYPPO H_CLOSEDIR
        jsr sd_root
        lda #LS_EXISTS
        sec
        rts
_nf:    pha
        jsr sd_root
        pla
        cmp #LS_NOT_FOUND
        beq +
        sec
        rts
+       clc
_out:   rts

; sd_part as a new image's name: 1-8 of A-Z 0-9 _ - ! # $ % & ( ) @ ^ { } ~ (the server's
; SD_NAME_RE), then .D64 or .D81 as st_kind says. Carry set if not
sd_valid_name:
        ldx #0
_n:     lda sd_part,x
        cmp #'.'
        beq _dot
        jsr sd_char_ok
        bcs _no
        inx
        cpx #9
        bne _n
_no:    sec
        rts
_dot:   txa
        beq _no
        lda sd_part+1,x
        cmp #'D'
        bne _no
        lda st_kind
        cmp #LK_D81
        beq _81
        lda sd_part+2,x
        cmp #'6'
        bne _no
        lda sd_part+3,x
        cmp #'4'
        bne _no
        bra _end
_81:    lda sd_part+2,x
        cmp #'8'
        bne _no
        lda sd_part+3,x
        cmp #'1'
        bne _no
_end:   lda sd_part+4,x
        bne _no
        clc
        rts

; carry clear if A may be in an 8.3 name (sd_valid_name); X kept
sd_char_ok:
        cmp #'A'
        bcc +
        cmp #'Z'+1
        bcc _ok
+       cmp #'0'
        bcc +
        cmp #'9'+1
        bcc _ok
+       ldy #14 - 1                     ; (the 14 of _set)
-       cmp _set,y
        beq _ok
        dey
        bpl -
        sec
        rts
_ok:    clc
        rts
_set:   .text "_-!#$%&()@^{}~"

sd_dircl:       .dword 0                    ; sd_walk: the last folder's first cluster
sd_long:        .byte 0                     ; sd_next_part: a part was too long
sd_leaf:        .byte 0
sd_i:           .byte 0
sd_fd:          .byte 0
sd_ffd:         .byte 0
sd_name:        .fill 13
sd_part:        .fill 13

;---------------------------------------------------------------------------------------
; S.SAVE_BEGIN: u8 req, u8 dev, u8 kind, u32 size, str path; then FILE_DATA, FILE_END
;---------------------------------------------------------------------------------------
pm_save_begin:
        jsr st_head
        jsr rd_u8
        sta st_kind
        jsr rd_u16
        sta st_size
        stx st_size+1
        jsr rd_u16
        sta st_size+2
        stx st_t0
        ldx #0
        jsr rd_str
        jsr st_copy_path
        bcs _unsup
        lda st_size                     ; more than 1 MB: too big to stage
        sta st_pos
        lda st_size+1
        sta st_pos+1
        lda st_size+2
        sta st_pos+2
        lda st_t0
        bne _big
        jsr st_too_far
        bcs _big
        lda st_dev
        bne +
        jsr sd_check_new                ; the SD card: its folders there, the name free
        bcc _ready
        jmp st_done
+       jsr st_kind_letter
        bcs _unsup
        jsr st_cbm_ok
        bcs _unsup
        jsr st_unit
        bcc +
        jmp st_no_unit
+       lda #<st_path                   ; already there? (saves never overwrite)
        ldx #>st_path
        jsr kst_exists
        bcc _there
        cmp #62
        beq _ready
        jmp st_drive_said
_there: lda #LS_EXISTS
        ldx #<KS_BUF
        ldy #>KS_BUF
        jmp st_done_text
_big:   lda #LS_TOO_BIG
        jmp st_done
_unsup: lda #LS_UNSUPPORTED
        jmp st_done
_ready: jsr disk_end
        jsr st_start
        lda #1
        sta st_mode
        lda #C_FILE_ACK
        jsr tx_begin
        jsr tx_pos
        jmp tx_end

; st_kind -> A = the DOS's letter for it (P S U); carry set if it isn't a drive kind
st_kind_letter:
        lda st_kind
        sec
        sbc #LK_PRG
        cmp #3
        bcs +
        tax
        lda _l,x
        clc
+       rts
_l:     .text "PSU"

; u32 offset, bytes: the next part of the download
pm_file_data:
        lda st_mode
        cmp #1
        bne _out
        jsr rd_u16                      ; it must be where we are
        cmp st_pos
        bne _out
        cpx st_pos+1
        bne _out
        jsr rd_u16
        cmp st_pos+2
        bne _out
        cpx #0
        bne _out
        sec                             ; its bytes: the frame less type and offset
        lda pf_len
        sbc #5
        sta st_n
        lda pf_len+1
        sbc #0
        sta st_n+1
        bcc _out
        ora st_n
        beq _out
        clc                             ; not past the size it said
        lda st_pos
        adc st_n
        sta st_t0
        lda st_pos+1
        adc st_n+1
        sta st_t1
        lda st_pos+2
        adc #0
        cmp st_size+2
        bcc _fits
        bne _out
        lda st_t1
        cmp st_size+1
        bcc _fits
        bne _out
        lda st_size
        cmp st_t0
        bcc _out
_fits:  jsr st_attic_ptrs               ; into attic
        lda #<(pf_buf+5)
        ldx #>(pf_buf+5)
        jsr st_from
        lda st_n
        sta tmp5
        lda st_n+1
        sta tmp5+1
        jsr dma_copy_far
        lda #<(pf_buf+5)
        sta tmp7
        lda #>(pf_buf+5)
        sta tmp7+1
        lda st_n
        sta st_cn
        lda st_n+1
        sta st_cn+1
        jsr crc_add
        jsr st_advance
        lda #C_FILE_ACK
        jsr tx_begin
        jsr tx_pos
        jmp tx_end
_out:   rts

; u32 crc: all there and the same CRC? Then write it
pm_file_end:
        lda st_mode
        cmp #1
        bne _out
        lda #0
        sta st_mode
        lda st_pos
        cmp st_size
        bne _bad
        lda st_pos+1
        cmp st_size+1
        bne _bad
        lda st_pos+2
        cmp st_size+2
        bne _bad
        ldx #0
-       jsr rd_u8
        eor #$ff
        cmp st_crc,x
        bne _bad
        inx
        cpx #4
        bne -
        lda st_dev
        bne save_drive
        jsr sd_check_new                ; (again: it's been a while) then sdwrite.asm
        bcs +
        jsr sd_write_file
        php
        pha
        jsr sd_root                     ; (HYPPO back at the root, past our writes)
        pla
        plp
        bcs +
        lda #LS_OK
+       jmp st_done
_bad:   lda #LS_BAD_CRC
        jmp st_done
_out:   rts

; the staged file -> the drive, as "NAME,P,W" (S, U)
save_drive:
        jsr st_unit
        bcc +
        jmp st_no_unit
+       lda #<st_path                   ; (again, as on the SD card: the disk may have been
        ldx #>st_path                   ; changed since SAVE_BEGIN; saves never overwrite)
        jsr kst_exists
        bcs +
        lda #LS_EXISTS
        ldx #<KS_BUF
        ldy #>KS_BUF
        jmp st_done_text
+       cmp #62
        beq +
        jmp st_drive_said
+       jsr st_kind_letter
        sta sv_suffix+1
        lda #<st_path
        ldx #>st_path
        ldy #0
        jsr kst_name_put
        lda #<sv_suffix
        ldx #>sv_suffix
        jsr kst_name_raw
        phy
        lda #2
        sta kst_sa
        pla
        jsr kst_open
        bcc +
        lda #LS_IO_ERROR
        jmp st_done
+       lda st_size                     ; (pos counts down what's left from here)
        sta sv_left
        lda st_size+1
        sta sv_left+1
        lda st_size+2
        sta sv_left+2
        lda #0
        sta st_pos
        sta st_pos+1
        sta st_pos+2
_blk:   lda sv_left
        ora sv_left+1
        ora sv_left+2
        beq _close
        lda #255                        ; a block of up to 255 bytes
        ldx sv_left+1
        bne +
        ldx sv_left+2
        bne +
        lda sv_left
        cmp #255
        bcc +
        lda #255
+       sta st_n
        sta kst_count
        lda #0
        sta st_n+1
        jsr st_attic_ptrs
        lda #<KS_BUF
        ldx #>KS_BUF
        jsr st_to
        lda st_n
        sta tmp5
        lda #0
        sta tmp5+1
        jsr dma_copy_far
        jsr kst_write
        lda kst_st
        bne _werr
        jsr st_advance
        sec
        lda sv_left
        sbc st_n
        sta sv_left
        lda sv_left+1
        sbc #0
        sta sv_left+1
        lda sv_left+2
        sbc #0
        sta sv_left+2
        bra _blk
_close: jsr kst_close
        jsr kst_status
        cmp #20
        bcs +                           ; (refused at the close: the part goes too)
        lda #LS_OK
        jmp st_done
+       sta sv_err
        bra _rm
_werr:  jsr kst_close                   ; the drive stopped: why, then take the part away
        jsr kst_status
        sta sv_err
_rm:    cmp #63                         ; (63: a file of that name was there first: it
        beq _said                       ; isn't ours to scratch)
        ldx #0
-       lda KS_BUF,x
        sta dd_text,x
        beq +
        inx
        cpx #39
        bne -
        lda #0
        sta dd_text,x
+       lda #<st_path
        ldx #>st_path
        jsr kst_remove
        ldx #0
-       lda dd_text,x
        sta KS_BUF,x
        beq +
        inx
        bra -
+
_said:  lda sv_err
        jmp st_drive_said
sv_suffix:      .null ",P,W"
sv_left:        .fill 3
sv_err:         .byte 0

;---------------------------------------------------------------------------------------
; S.LOAD_FILE: u8 req, u8 dev, u8 kind, str path: read it into attic, then send it
;---------------------------------------------------------------------------------------
pm_load_file:
        jsr st_head
        jsr rd_u8
        sta st_kind
        ldx #0
        jsr rd_str
        jsr st_copy_path
        bcc +
_unsup: lda #LS_UNSUPPORTED
        jmp st_done
+       jsr st_start
        lda st_dev
        bne +
        jmp load_sd
+       jsr st_kind_letter
        bcs _unsup
        sta ld_suffix+1
        jsr st_cbm_ok
        bcs _unsup
        jsr st_unit
        bcc +
        jmp st_no_unit
+       lda #<st_path
        ldx #>st_path
        ldy #0
        jsr kst_name_put
        lda #<ld_suffix
        ldx #>ld_suffix
        jsr kst_name_raw
        phy
        lda #2
        sta kst_sa
        pla
        jsr kst_open
        bcc _read
        lda #LS_IO_ERROR
        jmp st_done
_read:  jsr kst_read
        lda kst_count
        beq _st
        sta st_n
        lda #0
        sta st_n+1
        jsr st_attic_ptrs
        lda #<KS_BUF
        ldx #>KS_BUF
        jsr st_from
        lda st_n
        sta tmp5
        lda #0
        sta tmp5+1
        jsr dma_copy_far
        jsr st_advance
        jsr st_too_far
        bcs _big
_st:    lda kst_st
        beq _read
        sta sv_err
        jsr kst_close
        jsr kst_status
        cmp #20
        bcc +
        jmp st_drive_said
+       lda sv_err
        and #$bf                        ; anything but the end of the file
        beq up_start
        lda #LS_IO_ERROR
        jmp st_done
_big:   jsr kst_close
        lda #LS_TOO_BIG
        jmp st_done
ld_suffix:      .null ",P,R"

; the file is in attic (pos bytes): C.UP_BEGIN, then storage_frame sends it
up_start:
        jsr disk_end
        lda st_pos
        sta st_size
        lda st_pos+1
        sta st_size+1
        lda st_pos+2
        sta st_size+2
        lda #C_UP_BEGIN
        jsr tx_begin
        lda st_req
        jsr tx_u8
        jsr tx_pos
        jsr tx_end
        jsr st_start
        lda #2
        sta st_mode
        rts

; an SD card file: HYPPO openfile, then a sector at a time from its buffer into attic
load_sd:
        lda #1
        sta sd_leaf
        jsr sd_walk
        bcc +
        jmp st_done
+       jsr sd_find
        bcc +
        pha
        jsr sd_root
        pla
        jmp st_done
+       lda ST_DIRENT+$56
        and #$10
        beq +
        ldx sd_fd                       ; a folder
        #HYPPO H_CLOSEDIR
        jsr sd_root
        lda #LS_NOT_FOUND
        jmp st_done
+       lda ST_DIRENT+$55               ; the size from its entry: read that much (HYPPO's
        bne _big                        ; end-of-file answers differ: carry set with 0 bytes,
        lda ST_DIRENT+$52               ; or carry clear with A = $FF or 0)
        sta st_size
        lda ST_DIRENT+$53
        sta st_size+1
        lda ST_DIRENT+$54
        sta st_size+2
        sta st_pos+2                    ; (st_too_far on the size)
        lda st_size
        ora st_size+1
        sta st_pos
        jsr st_too_far
        lda #0
        sta st_pos
        sta st_pos+2
        bcc +
_big:   ldx sd_fd
        #HYPPO H_CLOSEDIR
        jsr sd_root
        lda #LS_TOO_BIG
        jmp st_done
+       #HYPPO H_OPENFILE               ; (the folder stays open until it's read: closing
        bcs +                           ; it first leaves HYPPO with no current file, $89)
        sta sd_err
        ldx sd_fd
        #HYPPO H_CLOSEDIR
        jsr sd_root
        lda #LS_IO_ERROR
        jmp st_done
+       sta sd_ffd
_sec:   jsr sd_at_size                  ; all of it?
        bcs _eof
        ldx sd_ffd
        #HYPPO H_READFILE
        bcs +
        sta sd_err+1
        jsr sd_close_both
        lda #LS_IO_ERROR
        jmp st_done
+       stx st_n
        sty st_n+1
        txa
        ora st_n+1
        beq _eof
        jsr st_attic_ptrs
        lda #<SD_BUF
        sta ptr1
        lda #>SD_BUF
        sta ptr1+1
        lda #(SD_BUF >> 16) & $ff
        sta ptr1+2
        lda #SD_BUF >> 24
        sta ptr1+3
        lda st_n
        sta tmp5
        lda st_n+1
        sta tmp5+1
        lda $d689                       ; BUFSEL: $FFD6E00 shows the SD card's buffer, not
        pha                             ; the floppy controller's (which it does at 0)
        ora #$80
        sta $d689
        jsr dma_copy_far
        pla
        sta $d689
        jsr st_advance
        jsr st_too_far
        bcc _sec
        jsr sd_close_both
        lda #LS_TOO_BIG
        jmp st_done
_eof:   jsr sd_close_both
        jsr sd_at_size                  ; past the size? (the last sector came whole: a
        bcc +                           ; D64's 174,848 bytes end half-way through one)
        lda st_size
        sta st_pos
        lda st_size+1
        sta st_pos+1
        lda st_size+2
        sta st_pos+2
+       jmp up_start

; carry set when pos has reached st_size
sd_at_size:
        lda st_pos+2
        cmp st_size+2
        bne +
        lda st_pos+1
        cmp st_size+1
        bne +
        lda st_pos
        cmp st_size
+       rts

; the file and its folder closed, back at the root
sd_close_both:
        ldx sd_ffd
        #HYPPO H_CLOSEFILE
        ldx sd_fd
        #HYPPO H_CLOSEDIR
        jmp sd_root

;---------------------------------------------------------------------------------------
; the upload going out: from the main loop, a few C.UP_DATA frames a pass
;---------------------------------------------------------------------------------------
storage_frame:
        .if BRIDGE_NET                  ; (a test: write what's staged to st_path on the SD
        lda dbg_sdw                     ; card, as a download would: bridge_test.py
        beq +                           ; filessdw)
        lda #0
        sta dbg_sdw
        sta st_mode
        lda #LK_D81
        sta st_kind
        jsr sd_check_new
        bcs _dbg
        jsr sd_write_file
        php
        pha
        jsr sd_root
        pla
        plp
        bcs _dbg
        lda #LS_OK
_dbg:   sta dbg_sdw+1
        inc dbg_sdw+2
        rts
+
        .endif
        lda st_mode
        cmp #2
        beq +
        rts
+       lda net_state                   ; the connection went: the upload with it (no
        cmp #NS_ONLINE                  ; sending into a dead one, and nothing left over
        beq +                           ; for the next)
        lda #0
        sta st_mode
        rts
+       lda #UP_PER_FRAME
        sta sf_n
_one:   sec                             ; what's left
        lda st_size
        sbc st_pos
        sta sf_left
        lda st_size+1
        sbc st_pos+1
        sta sf_left+1
        lda st_size+2
        sbc st_pos+2
        ora sf_left+1
        bne _full
        lda sf_left
        beq _end
        cmp #UP_CHUNK
        bcc +
_full:  lda #UP_CHUNK
+       sta st_n
        lda #0
        sta st_n+1
        lda #C_UP_DATA
        jsr tx_begin
        lda st_req
        jsr tx_u8                       ; (the bytes go at tx_buf+4)
        jsr st_attic_ptrs
        lda #<(tx_buf+4)
        ldx #>(tx_buf+4)
        jsr st_to
        lda st_n
        sta tmp5
        lda #0
        sta tmp5+1
        jsr dma_copy_far
        lda #<(tx_buf+4)
        sta tmp7
        lda #>(tx_buf+4)
        sta tmp7+1
        lda st_n
        sta st_cn
        lda #0
        sta st_cn+1
        jsr crc_add
        clc
        lda tx_n
        adc st_n
        sta tx_n
        jsr tx_end
        bcs _gone
        jsr st_advance
        dec sf_n
        bne _one
        rts
_end:   lda #C_UP_END
        jsr tx_begin
        lda st_req
        jsr tx_u8
        ldx #0
-       lda st_crc,x
        eor #$ff
        phx
        jsr tx_u8
        plx
        inx
        cpx #4
        bne -
        jsr tx_end
_gone:  lda #0
        sta st_mode
        rts
        .if BRIDGE_NET
dbg_sdw:        .byte 0, 0, 0           ; poke 1: write; then the status, and a count
        .endif
sf_n:           .byte 0
sf_left:        .word 0
