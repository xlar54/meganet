;=======================================================================================
; exit.asm - the client's own MegaNet menu (always first on the bar, ids $F8+): My Account
; (opened by the server), and Exit:
; "are you sure", then drop the connection and go back to BASIC's READY prompt.
;
;   exit_menu       add the MegaNet menu (proto.asm pm_menu calls it before the server's)
;   exit_menu_pick  a GE_MENU with ge_val >= $F0
;   exit_event      the confirm window's buttons
;   rom_save        at boot: $20000-$3FFFF (the ROM image) to attic, before the framebuffer
;                   overwrites it; Exit copies it back so BASIC finds its ROM again
;=======================================================================================

XM_TITLE        = $f8
XM_EXIT         = $f9
XM_ACCOUNT      = $fa
XM_LINE         = $fb
SM_ACCOUNT      = $22                   ; the server's My Account (always allowed)
XW              = $fd                   ; the confirm window
XG_EXIT         = 2
XG_CANCEL       = 3
ROM_ATTIC       = $8100000              ; 128 KB

; MegaNet: the title and My Account first (before the server's menus, so it's first on the
; bar); then exit_menu_end after them: a line and Exit, so Exit stays last under the server's
; own MegaNet items (System Stats: sent with parent XM_TITLE)
exit_menu:
        ldx #0
        ldy #2
        bra xm_add
exit_menu_end:
        ldx #2
        ldy #4
xm_add:
        sty xm_to
-       lda xm_ids,x
        sta gp_gid
        lda xm_par,x
        sta gp_win
        lda xm_lo,x
        sta gp_text
        lda xm_hi,x
        sta gp_text+1
        phx
        jsr gui_menu_add
        plx
        inx
        cpx xm_to
        bne -
        rts
xm_to: .byte 0
xm_ids: .byte XM_TITLE, XM_ACCOUNT, XM_LINE, XM_EXIT
xm_par: .byte 0, XM_TITLE, XM_TITLE, XM_TITLE
xm_lo:  .byte <s_xm_title, <s_xm_account, <s_xm_line, <s_xm_exit
xm_hi:  .byte >s_xm_title, >s_xm_account, >s_xm_line, >s_xm_exit

exit_menu_pick:
        lda ge_val
        cmp #XM_ACCOUNT                 ; the server keeps the account: ask it (its id $22)
        bne +
        lda login_state
        cmp #3
        bne _out
        jsr busy_click
        lda #C_MENU_PICK
        jsr tx_begin
        lda #SM_ACCOUNT
        jsr tx_u8
        jmp tx_end
+       cmp #XM_EXIT
        bne _out
        #GUI_WIN XW, 180, 70, 280, 70, GWF_MODAL | GWF_CLOSE | GWF_MOVABLE, s_xw_title
        #GUI_GAD XW, 1, GK_LABEL, 4, 6, 264, 10, GGF_CENTRE, 0, s_xw_text
        #GUI_GAD XW, XG_EXIT, GK_BUTTON, 48, 28, 88, 16, 0, 0, s_xm_exit    ; centred
        #GUI_GAD XW, XG_CANCEL, GK_BUTTON, 144, 28, 88, 16, GGF_DEFAULT, 0, s_xw_cancel
        lda #XW
        jmp gui_win_show
_out:   rts

exit_event:
        lda ge_type
        cmp #GE_CLOSE                   ; the close box: Cancel
        beq _cancel
        cmp #GE_CLICK
        bne _out
        lda ge_gid
        cmp #XG_EXIT
        beq exit_to_basic
_cancel: lda #XW                        ; Cancel
        jmp gui_win_close
_out:   rts

; drop the connection, put the ROM image back, return to BASIC (doesn't return)
exit_to_basic:
        lda net_state
        cmp #NS_OFF
        beq +
        jsr net_close
+       jsr sdp_stop                     ; no SID tune (the IRQ hook goes with the takeover)
        sei
        lda #0                          ; screen and sprites off while the ROM goes back
        sta SPR_ENABLE
        lda #1                          ; attic -> $20000-$3FFFF
        jsr rom_copy
        jsr l_rom_writable              ; write-protect it again
        bcc +
        lda #$70
        sta HTRAP00
        clv
+       jmp kst_to_basic

; the ROM image: A = 0 to attic (rom_save), 1 back from attic. Two 64 KB banks, each one
; DMA of 65535 bytes plus its last byte
rom_save:
        lda #0
rom_copy:
        sta rc_dir
        lda #0
        sta rc_bank
_bank:  lda #0
        sta ptr1
        sta ptr1+1
        sta ptr2
        sta ptr2+1
        lda #$ff
        sta tmp5
        sta tmp5+1
        jsr rc_ptrs
        jsr dma_copy_far
        lda #$ff
        sta ptr1
        sta ptr1+1
        sta ptr2
        sta ptr2+1
        jsr rc_ptrs
        ldz #0
        lda [ptr1],z
        sta [ptr2],z
        inc rc_bank
        lda rc_bank
        cmp #2
        bne _bank
        rts
; ptr1 = source, ptr2 = destination banks (bits 16-27) for rc_bank, rc_dir
rc_ptrs:
        clc
        lda #$02                        ; ROM side: $20000 + bank * $10000
        adc rc_bank
        tax
        clc
        lda rc_attic                    ; attic side: $8100000 + bank * $10000
        adc rc_bank
        tay
        lda rc_dir
        bne _back
        stx ptr1+2
        lda #0
        sta ptr1+3
        sty ptr2+2
        lda #$08
        sta ptr2+3
        rts
_back:  sty ptr1+2
        lda #$08
        sta ptr1+3
        stx ptr2+2
        lda #0
        sta ptr2+3
        rts
rc_dir:         .byte 0
rc_bank:        .byte 0
rc_attic:       .byte $10               ; attic bits 16-23: $10 the ROM image, $12 the
                                        ; framebuffer while the ROM is back (disk_begin)

; The framebuffer is where the ROMs were ($20000-$3F3FF): the DOS ($20000), the interface
; ROM ($2C000), BASIC and the KERNAL. A KERNAL disk call needs them, so for disk work
; (storage.asm) the display is blanked, the framebuffer saved to attic and the ROM image put
; back; disk_end undoes it. About 384 KB of DMA: a few milliseconds.
FB_ATTIC_HI     = $12                   ; $8120000: 128 KB
disk_begin:
        lda disk_on
        bne _out
        inc disk_on
        lda VIC_CTRL1                   ; display off (bit 7: see MEGA65_NOTES)
        and #%01101111
        ora #(>IRQ_LINE) << 7
        sta VIC_CTRL1
        lda #FB_ATTIC_HI                ; the framebuffer to attic
        sta rc_attic
        lda #0
        jsr rom_copy
        lda #$10                        ; the ROM back
        sta rc_attic
        lda #1
        jsr rom_copy
_out:   rts
disk_end:
        lda disk_on
        beq _out
        lda #0
        sta disk_on
        lda #FB_ATTIC_HI                ; the framebuffer back
        sta rc_attic
        lda #1
        jsr rom_copy
        lda #$10
        sta rc_attic
        lda VIC_CTRL1                   ; display on
        and #%01111111
        ora #%00010000
        ora #(>IRQ_LINE) << 7
        sta VIC_CTRL1
_out:   rts
disk_on:        .byte 0

s_xm_title:     .null "MegaNet"
s_xm_exit:      .null "Exit"
s_xm_account:   .null "My Account"
s_xm_line:      .null "-"
s_xw_title:     .null "Exit MegaNet"
s_xw_text:      .null "Disconnect and go back to BASIC?"
s_xw_cancel:    .null "Cancel"
