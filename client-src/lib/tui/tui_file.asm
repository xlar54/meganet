;=======================================================================================
; lib/tui/tui_file.asm - the file dialog: Open and Save As with a file list, its types, a choice
; of drives 8-11, and subdirectories. Keyboard and mouse. Needs tui_dialog.asm (included
; first) and lib/kstream.asm.
;
;   tui_file_dialog   A = TFD_OPEN or TFD_SAVE. tfd_name = the starting name, usually "*" for
;                     opening. Returns A = ID_OK with the chosen name in tfd_name, on the drive
;                     and directory chosen (tfd_unit, kst_dev), ready to use with kstream. Or
;                     A = 0 if cancelled, with the drive put back as it was. The directory on the
;                     drive may still have moved: see tfd_moved. The caller opens or saves the
;                     file, and asks before replacing one.
;   tfd_name          34 bytes
;   tfd_set_unit      A = the drive to use
;   tfd_start_unit    the drive in use when the dialog opened
;   tfd_home_unit, tfd_moved   If your document lives on a drive, keep its number in tfd_home_unit
;                     and clear tfd_moved. tfd_moved becomes 1 when the user browses to another
;                     directory on that drive, even if they then cancel: the drive's current
;                     directory is no longer the document's, so saving by name would go to the
;                     wrong place. Ask for a location again.
;
; For your own lists:
;   tfd_read_dir      A/X = a pattern: read the current directory into tfd_dir. Carry set if the
;                     drive doesn't answer.
;   tfd_dir_count, tfd_entry_ptr, tfd_entry_name    the entries. The table is in bank 1, at
;                     TFD_DIR_BASE, reached through tui_fp: override it if you use that memory.
;   tfd_is_sub        A/X = a name: carry clear if the listing has it as a subdirectory
;   tfd_enter_dir, tfd_parent_dir    move about
;
; Listing entries are 16 characters of name, a flag (* = not closed properly), 3 of type.
;
; There are two kinds of subdirectory:
;   CBM  the MEGA65's own drives (and 1581s): "/0:NAME" goes in and "/" to the root. There's no
;        way up one level, so the path is kept here to walk back down from the root.
;   DIR  CMD native partitions, sd2iec and the like: "CD:NAME" goes in, "CD" + left arrow goes up.
;        (CMD HD manual, section 9; the arrow is $5F. sd2iec takes "CD:_" too.)
;---------------------------------------------------------------------------------------
;=======================================================================================

TFD_OPEN        = 0
TFD_SAVE        = 1
TFD_NAME_LEN    = 16
        .weak
TFD_DIR_MAX     = 144                   ; 21 bytes each
TFD_DIR_BASE    = $13000                ; the list: chip RAM, any bank but not bank 0's need
TFD_PATH_BASE   = TFD_DIR_BASE + TFD_DIR_MAX * TFD_ENTRY    ; 544 bytes
        .endweak

tfd_dir         = TFD_DIR_BASE
l_tfd_path      = TFD_PATH_BASE
        .section bss
l_tfd_row:      .fill TFD_ENTRY         ; an entry fetched for showing
        .send
l_tfd_level:    .fill TFD_NAME_LEN + 1  ; a level of the path fetched for sending
tfd_dir_state:
tfd_dir_count:  .word 0
tfd_dir_top:    .word 0
tfd_dir_sel:    .word 0
l_tfd_nm:       .word 0
l_tfd_ok:       .null "OK"
l_tfd_cancel:   .null "Cancel"
l_tfd_t2:       .byte 0

TFD_ENTRY        = TFD_NAME_LEN + 5
TFD_PATH_MAX     = 8

tfd_unit:        .byte 8                 ; the drive in use
        .section bss
l_tfd_depth:     .fill 4                 ; for each drive, how far into CBM subdirectories
        .send
        .section bss
l_tfd_noup:      .fill 4                 ; for each drive, 1 = its root has no parent
        .send
l_tfd_dotdot:    .null ".."
l_tfd_type_dir:  .null "DIR"
l_tfd_cmd_part:  .null "/0:"
l_tfd_cmd_root:  .null "/"
l_tfd_cmd_cd:    .null "CD:"
l_tfd_cmd_up1:   .text "CD", $5F, 0
l_tfd_cmd_up2:   .text "CD:", $5F, 0
l_tfd_cmd_up3:   .null "CD:.."

; use drive A
tfd_set_unit:
        sta tfd_unit
        sta kst_dev
        rts

; X = tfd_unit - 8
l_tfd_unit_x:
        lda tfd_unit
        sec
        sbc #8
        tax
        rts

; A = level on this drive: tui_fp points at that level's name in the path
l_tfd_path_ptr:
        sta l_tfd_t
        jsr l_tfd_unit_x
        txa
        asl
        asl
        asl
        clc
        adc l_tfd_t
        sta MULTINA
        lda #0
        sta MULTINA+1
        sta MULTINA+2
        sta MULTINA+3
        sta MULTINB+1
        sta MULTINB+2
        sta MULTINB+3
        lda #TFD_NAME_LEN + 1
        sta MULTINB
        clc
        lda MULTOUT
        adc #<l_tfd_path
        sta tui_fp
        lda MULTOUT+1
        adc #>l_tfd_path
        sta tui_fp+1
        lda #`l_tfd_path
        adc #0
        sta tui_fp+2
        lda #0
        sta tui_fp+3
        rts

; A/X = a string for the DOS, plain, then A/X in l_tfd_nm as a name: send the command. A = reply.
l_tfd_cmd_named:
        ldy #0
        jsr kst_name_raw
        lda l_tfd_nm
        ldx l_tfd_nm+1
        jsr kst_name_put
        tya
        jmp kst_command
; A/X = a whole command
l_tfd_cmd_plain:
        ldy #0
        jsr kst_name_raw
        tya
        jmp kst_command

; A/X = a directory's name, Y = 1 for CBM, 0 for DIR. Carry set = failed, with the drive's
; reply in KS_BUF.
tfd_enter_dir:
        sta l_tfd_nm
        stx l_tfd_nm+1
        cpy #0
        beq l_tfd_tfd_dir
        lda #<l_tfd_cmd_part
        ldx #>l_tfd_cmd_part
        jsr l_tfd_cmd_named
        cmp #20
        bcc +
        rts
+       ; note it, to find the way back
        jsr l_tfd_unit_x
        lda l_tfd_depth,x
        cmp #TFD_PATH_MAX
        bcs l_tfd_ed_ok
        jsr l_tfd_path_ptr
        lda l_tfd_nm
        sta tui_str
        lda l_tfd_nm+1
        sta tui_str+1
        ldy #0
-       tya
        taz
        lda (tui_str),y
        sta [tui_fp],z
        beq +
        iny
        bra -
+       ldz #0
        jsr l_tfd_unit_x
        inc l_tfd_depth,x
l_tfd_ed_ok:
        clc
        rts
l_tfd_tfd_dir:
        lda #<l_tfd_cmd_cd
        ldx #>l_tfd_cmd_cd
        jsr l_tfd_cmd_named
        cmp #20
        rts

; up a level. A root that has no parent just stays put, and stops offering "..".
tfd_parent_dir:
        jsr l_tfd_unit_x
        lda l_tfd_depth,x
        beq l_tfd_pd_native
        ; CBM: to the root, and down again to one level above
        dec l_tfd_depth,x
        lda #<l_tfd_cmd_root
        ldx #>l_tfd_cmd_root
        jsr l_tfd_cmd_plain
        lda #0
        sta l_tfd_pdi
l_tfd_pd_replay:
        jsr l_tfd_unit_x
        lda l_tfd_pdi
        cmp l_tfd_depth,x
        bcs l_tfd_pd_end
        jsr l_tfd_path_ptr
        ldz #0
-       tza
        tax
        lda [tui_fp],z
        sta l_tfd_level,x
        beq +
        inz
        bra -
+       ldz #0
        lda #<l_tfd_level
        sta l_tfd_nm
        lda #>l_tfd_level
        sta l_tfd_nm+1
        lda #<l_tfd_cmd_part
        ldx #>l_tfd_cmd_part
        jsr l_tfd_cmd_named
        inc l_tfd_pdi
        bra l_tfd_pd_replay
l_tfd_pd_native:
        lda #<l_tfd_cmd_up1
        ldx #>l_tfd_cmd_up1
        jsr l_tfd_cmd_plain
        cmp #20
        bcc l_tfd_pd_end
        lda #<l_tfd_cmd_up2
        ldx #>l_tfd_cmd_up2
        jsr l_tfd_cmd_plain
        cmp #20
        bcc l_tfd_pd_end
        lda #<l_tfd_cmd_up3
        ldx #>l_tfd_cmd_up3
        jsr l_tfd_cmd_plain
        cmp #20
        bcc l_tfd_pd_end
        jsr l_tfd_unit_x
        lda #1
        sta l_tfd_noup,x
l_tfd_pd_end:
        rts
l_tfd_pdi:       .byte 0

; A/X = a pattern ("*"): fills tfd_dir from the current directory of the current drive.
; Carry set if the drive doesn't answer.
tfd_read_dir:
        sta l_tfd_pat
        stx l_tfd_pat+1
        lda #0
        sta tfd_dir_count
        sta tfd_dir_count+1
        sta tfd_dir_top
        sta tfd_dir_top+1
        sta tfd_dir_sel
        sta tfd_dir_sel+1
        jsr kst_present
        bcc +
        rts
+       ; ".." first, unless this is a root known to have no parent
        jsr l_tfd_unit_x
        lda l_tfd_depth,x
        bne l_tfd_dr_up
        lda l_tfd_noup,x
        bne l_tfd_dr_open
l_tfd_dr_up:
        lda #'.'
        sta l_tfd_name
        sta l_tfd_name+1
        lda #2
        sta l_tfd_got
        ldx #2
-       lda l_tfd_type_dir-2,x
        sta l_tfd_ty-2,x
        inx
        cpx #5
        bne -
        lda #32
        sta l_tfd_flag
        jsr l_tfd_dr_add
l_tfd_dr_open:
        lda #<l_tfd_dollar
        ldx #>l_tfd_dollar
        ldy #0
        jsr kst_name_raw
        lda l_tfd_pat
        ldx l_tfd_pat+1
        jsr kst_name_put
        tya
        ldx #0
        stx kst_sa                      ; secondary 0 gives the BASIC-listing form
        jsr kst_open
        bcc +
        jmp l_tfd_dr_end
+       jsr kst_rewind
        ; the load address
        jsr kst_getc
        jsr kst_getc
        lda #1
        sta l_tfd_dr_first
l_tfd_dr_line:
        ; link pointer: 0 ends the listing
        jsr kst_getc
        bcs l_tfd_dr_end
        sta l_tfd_t
        jsr kst_getc
        bcs l_tfd_dr_end
        ora l_tfd_t
        beq l_tfd_dr_end
        ; the line number (blocks)
        jsr kst_getc
        jsr kst_getc
        ; text: a name in quotes, then the type
        lda #0
        sta l_tfd_inq
        sta l_tfd_got
        sta l_tfd_tyn
        lda #32
        sta l_tfd_flag
l_tfd_dr_ch:
        jsr kst_getc
        bcs l_tfd_dr_end
        cmp #0
        beq l_tfd_dr_eol
        cmp #34
        beq l_tfd_dr_quote
        ldx l_tfd_inq
        beq l_tfd_dr_ch                  ; before the name
        cpx #1
        bne l_tfd_dr_after
        ; a character of the name
        ldx l_tfd_got
        cpx #TFD_NAME_LEN
        bcs l_tfd_dr_ch
        cmp #$C1
        bcc +
        cmp #$DB
        bcs +
        sbc #$5F                        ; (carry clear: -$60) $C1-$DA -> a-z
+       sta l_tfd_name,x
        inc l_tfd_got
        bra l_tfd_dr_ch
l_tfd_dr_after:
        ; after the name: spaces, perhaps *, the type
        cmp #32
        beq l_tfd_dr_ch
        ldx l_tfd_tyn
        bne +
        cmp #'*'
        bne +
        sta l_tfd_flag
        bra l_tfd_dr_ch
+       cpx #3
        bcs l_tfd_dr_ch
        sta l_tfd_ty,x
        inc l_tfd_tyn
        bra l_tfd_dr_ch
l_tfd_dr_quote:
        inc l_tfd_inq
        bra l_tfd_dr_ch
l_tfd_dr_eol:
        ; the first line is the disk's name
        lda l_tfd_dr_first
        beq +
        lda #0
        sta l_tfd_dr_first
        bra l_tfd_dr_line
+       lda l_tfd_got
        beq l_tfd_dr_line
        ; pad a short or missing type
-       ldx l_tfd_tyn
        cpx #3
        bcs +
        lda #32
        sta l_tfd_ty,x
        inc l_tfd_tyn
        bra -
+       jsr l_tfd_dr_add
        bra l_tfd_dr_line
l_tfd_dr_end:
        jsr kst_close
        jsr kst_status                  ; (clears any drive message)
        clc
        rts

; add l_tfd_name (l_tfd_got characters), l_tfd_flag, l_tfd_ty
l_tfd_dr_add:
        lda tfd_dir_count
        cmp #TFD_DIR_MAX
        bcs l_tfd_da_end
        tax
        jsr tfd_entry_ptr
        ldy #0
        ldz #0
-       cpy l_tfd_got
        beq +
        lda l_tfd_name,y
        sta [tui_fp],z
        iny
        inz
        bra -
+
-       cpz #TFD_NAME_LEN
        beq +
        lda #32
        sta [tui_fp],z
        inz
        bra -
+       lda l_tfd_flag
        sta [tui_fp],z
        inz
        ldx #0
-       lda l_tfd_ty,x
        sta [tui_fp],z
        inz
        inx
        cpx #3
        bne -
        lda #0
        sta [tui_fp],z
        ldz #0
        inc tfd_dir_count
l_tfd_da_end:
        rts

; X = entry: tui_fp points at it. Keeps A.
tfd_entry_ptr:
        pha
        txa
        sta MULTINA
        lda #0
        sta MULTINA+1
        sta MULTINA+2
        sta MULTINA+3
        sta MULTINB+1
        sta MULTINB+2
        sta MULTINB+3
        lda #TFD_ENTRY
        sta MULTINB
        clc
        lda MULTOUT
        adc #<tfd_dir
        sta tui_fp
        lda MULTOUT+1
        adc #>tfd_dir
        sta tui_fp+1
        lda #`tfd_dir
        adc #0
        sta tui_fp+2
        lda #0
        sta tui_fp+3
        pla
        rts

; entry X's name -> the zero-terminated buffer at tui_str, without the padding
tfd_entry_name:
        jsr tfd_entry_ptr
        ldy #TFD_NAME_LEN
-       dey
        bmi l_tfd_dn_end
        tya
        taz
        lda [tui_fp],z
        cmp #32
        beq -
l_tfd_dn_end:
        iny
        lda #0
        sta (tui_str),y
-       dey
        bmi +
        tya
        taz
        lda [tui_fp],z
        sta (tui_str),y
        bra -
+       ldz #0
        rts

; A/X = a name. Is it a subdirectory in the listing? Carry clear if so, Y = 1 for CBM, 0 for DIR.
tfd_is_sub:
        sta tui_str
        stx tui_str+1
        lda #0
        sta l_tfd_t
l_tfd_is_next:
        ldx l_tfd_t
        cpx tfd_dir_count
        bcs l_tfd_is_no
        jsr tfd_entry_ptr
        ldy #0
-       tya
        taz
        lda (tui_str),y
        beq l_tfd_is_end
        cmp [tui_fp],z
        bne l_tfd_is_diff
        iny
        cpy #TFD_NAME_LEN
        bne -
        bra l_tfd_is_same
l_tfd_is_end:
        ; the rest of the entry's name must be padding
        lda [tui_fp],z
        cmp #32
        bne l_tfd_is_diff
l_tfd_is_same:
        ldz #TFD_NAME_LEN + 1
        lda [tui_fp],z
        cmp #'C'
        bne +
        inz
        lda [tui_fp],z
        cmp #'B'
        bne l_tfd_is_diff
        ldy #1
        ldz #0
        clc
        rts
+       cmp #'D'
        bne l_tfd_is_diff
        inz
        lda [tui_fp],z
        cmp #'I'
        bne l_tfd_is_diff
        ldy #0
        ldz #0
        clc
        rts
l_tfd_is_diff:
        inc l_tfd_t
        bra l_tfd_is_next
l_tfd_is_no:
        ldz #0
        sec
        rts

l_tfd_dollar:    .null "$:"
l_tfd_pat:       .word 0
l_tfd_t:         .byte 0
l_tfd_inq:       .byte 0
l_tfd_got:       .byte 0
l_tfd_tyn:       .byte 0
l_tfd_flag:      .byte 32
        .section bss
l_tfd_ty:        .fill 3
        .send
l_tfd_dr_first:  .byte 0
l_tfd_name:      .fill TFD_NAME_LEN + 1
; Open and Save As: the same dialog
L_TFD_FIELD        = 1                     ; (control numbers)
L_TFD_LIST         = 3
L_TFD_RADIO        = 5
l_tfd_file_dlg:
        #DLG 22, 50, l_tfd_t_open, l_tfd_file_hook
l_tfd_file_title = l_tfd_file_dlg + 2
        #DLG_LABEL 2, 2, l_tfd_filename
        #DLG_TEXT 2, 14, 32, tfd_name, 32, 1
        #DLG_LABEL 4, 15, l_tfd_files
        #DLG_LIST 6, 14, 22, 8, l_tfd_dir_item, tfd_dir_state
        #DLG_LABEL 16, 9, l_tfd_drive
        #DLG_RADIO 16, 16, l_tfd_d8, l_tfd_unit_var, 8
        #DLG_RADIO 16, 22, l_tfd_d9, l_tfd_unit_var, 9
        #DLG_RADIO 16, 28, l_tfd_d10, l_tfd_unit_var, 10
        #DLG_RADIO 16, 35, l_tfd_d11, l_tfd_unit_var, 11
        #DLG_HLINE 18
        #DLG_BUTTON 19, DLG_AUTO, l_tfd_ok, ID_OK, 1
        #DLG_BUTTON 19, DLG_AUTO, l_tfd_cancel, 0
        #DLG_END
l_tfd_t_open:     .null "Open"
l_tfd_t_saveas:   .null "Save As"
l_tfd_filename:   .null "File Name:"
l_tfd_files:      .null "Name             Type"
l_tfd_drive:      .null "Drive:"
l_tfd_d8:         .null "8"
l_tfd_d9:         .null "9"
l_tfd_d10:        .null "10"
l_tfd_d11:        .null "11"
l_tfd_unit_var:   .byte 8
tfd_start_unit: .byte 8
l_tfd_saving:     .byte 0                 ; 1 = this is Save As
tfd_home_unit:    .byte 8                 ; the drive the document came from
tfd_moved:       .byte 0                 ; 1 = that drive has since moved to another directory
        .section bss
tfd_name:       .fill 34
        .send
l_tfd_star:       .null "*"
l_tfd_nodrive:    .null "That drive isn't responding"

; the list's strings: fetched from the far table, one row at a time
l_tfd_dir_item:
        tax
        jsr tfd_entry_ptr
        ldx #0
        ldz #0
-       lda [tui_fp],z
        sta l_tfd_row,x
        inz
        inx
        cpx #TFD_ENTRY
        bne -
        ldz #0
        lda #<l_tfd_row
        ldx #>l_tfd_row
        rts

; Open and Save As.
;   the list's selection goes into the name field
;   a drive button changes drive
;   OK on a subdirectory or ".." goes there, on a wildcard re-reads the list
l_tfd_file_hook:
        cmp #DH_LIST
        bne l_tfd_fh1
        lda tfd_dir_count
        beq l_tfd_fh_ok
        lda #<tfd_name
        sta tui_str
        lda #>tfd_name
        sta tui_str+1
        ldx tfd_dir_sel
        jsr tfd_entry_name
        ldx #L_TFD_FIELD
        jsr tui_dlg_redraw
l_tfd_fh_ok:
        clc
        rts
l_tfd_fh1:
        cmp #DH_TOGGLE
        bne l_tfd_fh2
        ; a radio button: try that drive
        lda l_tfd_unit_var
        cmp tfd_unit
        beq l_tfd_fh_ok
        ldx tfd_unit
        stx l_tfd_t2
        jsr tfd_set_unit
        jsr kst_present
        bcc l_tfd_fh_listing
        ; nothing there: back to the one we had
        lda l_tfd_t2
        jsr tfd_set_unit
        lda l_tfd_t2
        sta l_tfd_unit_var
        ldx #L_TFD_RADIO
-       phx
        jsr tui_dlg_redraw
        plx
        inx
        cpx #L_TFD_RADIO + 4
        bne -
        lda #<l_tfd_nodrive
        ldx #>l_tfd_nodrive
        ldy #MB_OK
        jsr tui_msgbox
        clc
        rts
l_tfd_fh2:
        cmp #DH_BUTTON
        bne l_tfd_fh_ok
        lda tui_dlg_result
        beq l_tfd_fh_ok                   ; Cancel
        lda tfd_name
        bne +
        sec                             ; nothing typed: stay
        rts
+       ; ".."?
        cmp #'.'
        bne l_tfd_fh_sub
        lda tfd_name+1
        cmp #'.'
        bne l_tfd_fh_sub
        lda tfd_name+2
        bne l_tfd_fh_sub
        jsr tfd_parent_dir
        bra l_tfd_fh_moved
l_tfd_fh_sub:
        ; a subdirectory?
        lda #<tfd_name
        ldx #>tfd_name
        jsr tfd_is_sub
        bcs l_tfd_fh_wild
        lda #<tfd_name
        ldx #>tfd_name
        jsr tfd_enter_dir
        bcc l_tfd_fh_moved
        lda #<KS_BUF
        ldx #>KS_BUF
        ldy #MB_OK
        jsr tui_msgbox
        sec
        rts
l_tfd_fh_moved:
        ; the next Save mustn't quietly go to this directory
        lda tfd_unit
        cmp tfd_home_unit
        bne l_tfd_fh_listing
        lda #1
        sta tfd_moved
l_tfd_fh_listing:
        lda #'*'
        sta tfd_name
        lda #0
        sta tfd_name+1
l_tfd_fh_reread:
        lda #<tfd_name
        ldx #>tfd_name
        jsr tfd_read_dir
        ldx #L_TFD_LIST
        jsr tui_dlg_redraw
        jsr l_tfd_refield
        sec
        rts
l_tfd_fh_wild:
        ldy #0
-       lda tfd_name,y
        beq l_tfd_fh_plain
        cmp #'*'
        beq l_tfd_fh_reread
        cmp #'?'
        beq l_tfd_fh_reread
        iny
        bra -
l_tfd_fh_plain:
        ; a name to use. Opening asks nothing more of it.
        lda l_tfd_saving
        beq l_tfd_fh_ok2
        ; names the DOS would misread are refused
        cpy #TFD_NAME_LEN + 1
        bcs l_tfd_fh_badname
        ldy #0
l_tfd_fh_chk:
        lda tfd_name,y
        beq l_tfd_fh_ok2
        ldx #l_tfd_bad_n - 1
-       cmp l_tfd_bad,x
        beq l_tfd_fh_badname
        dex
        bpl -
        iny
        bra l_tfd_fh_chk
l_tfd_fh_badname:
        lda #<l_tfd_badname
        ldx #>l_tfd_badname
        ldy #MB_OK
        jsr tui_msgbox
        sec
        rts
l_tfd_fh_ok2:
        clc
        rts
l_tfd_bad:        .text ",:=", 34
l_tfd_bad_n = * - l_tfd_bad
l_tfd_badname:    .null "A name is 16 characters, without , : = or quotes"

; the field may have just changed: if it has the focus, tidy its cursor
l_tfd_refield:
        lda l_dl_foc
        cmp #L_TFD_FIELD
        bne +
        jmp tui_dlg_refield
+       ldx #L_TFD_FIELD
        jmp tui_dlg_redraw

; the dialog, for the current drive: A = 1 for Save As. Returns A = ID_OK or 0. tfd_name is the
; starting name, and a cancel leaves the drive as it was.
tui_file_dialog:
        sta l_tfd_saving
        lda tfd_unit
        sta l_tfd_unit_var
        sta tfd_start_unit
        lda l_tfd_saving
        beq +
        lda #<l_tfd_t_saveas
        ldx #>l_tfd_t_saveas
        bra ++
+       lda #<l_tfd_t_open
        ldx #>l_tfd_t_open
+       sta l_tfd_file_title
        stx l_tfd_file_title+1
        lda #<l_tfd_star
        ldx #>l_tfd_star
        jsr tfd_read_dir
        lda #<l_tfd_file_dlg
        ldx #>l_tfd_file_dlg
        jsr tui_dialog
        cmp #ID_OK
        beq +
        lda tfd_start_unit
        jsr tfd_set_unit
        lda #0
+       rts

