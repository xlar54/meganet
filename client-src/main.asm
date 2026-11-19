;=======================================================================================
; MegaNet client: a graphical online-service client for the MEGA65 (see docs/DESIGN.md).
;
; Boot: the packed assets (the logo) into attic, while the KERNAL still works. Then the
; takeover, the 640x200 256-colour screen, the GUI (lib/gui/), the sign-on screen.
;
; Memory:
;   $2001-       program
;   $12000/$13000  screen RAMs (fcm640)
;   $20000-$3F3FF  the framebuffer (the ROM area, unprotected after the takeover):
;                  mega-ip will take $42000-$47FFF and $50000-$515FF (weather65's layout)
;   $8000000     the logo (attic)
;   $8300000     File Library downloads and uploads, staged (storage.asm, 1 MB)
;   $8200000     GUI list / view rows (16 x 8 KB); $8240000 desktop icon pictures (12 x 512)
;   $8250000     grid cells (256 a gadget slot); $8400000 resource slots, 16 x 64 KB: a
;                grid's tiles, sent by the server (lib/gui/grid.asm)
;   $CD00-$CF05  the bridge build's rings (Xemu only)
;=======================================================================================
        .cpu "45gs02"

        .include "platform.asm"
        .include "lib/zp.asm"
        .include "zp.asm"
        .include "gen/logo.asm"         ; (constants only)

F640_BUF0       = $20000
F640_BUF1       = $40000                ; (not used)
MOUSE_MAX_X     = 639
; the GUI's limits (lib/gui/gui.asm's defaults are 8 / 48 / 8): an admin with the User Editor,
; Message Boards, Private Messages and a chat room open needs more than 48 gadgets
GUI_MAXWIN      = 12                    ; windows open at once
GUI_MAXGAD      = 80                    ; gadgets in all of them (< 128: some loops use bpl)
GUI_MAXBIG      = 16                    ; lists, views, text areas, drop-downs (attic, 8 KB each)
GUI_TBUF        = $eb00                 ; the gadget texts (80 x 64): under the KERNAL ROM,
                                        ; after proto.asm's frame buffers ($E000-$EAFF)
        .cerror GUI_TBUF + GUI_MAXGAD * 64 > $fffa, "the gadget texts run into the vectors"
        .weak
MOCK_NET        = 0                     ; -D MOCK_NET=1 (build.bat mock FILE): replay build
BRIDGE_NET      = 0                     ; -D BRIDGE_NET=1 (build.bat bridge): Xemu + bridge
        .endweak
UNPACK_BUF      = $40000                ; boot only

        * = $2001                       ; BASIC stub: BANK 0 : SYS 8210
        .word (+), 2026
        .byte $fe, $02, $30
        .byte ':'
        .byte $9e
        .text "8210"
        .byte 0
+       .word 0

        * = $2012
entry:
        cld
        jsr kst_capture                 ; first: BASIC's state, for MegaNet > Exit
        jsr load_manifest               ; the logo -> attic
        lda #0
        bcs +
        lda #1
+       sta logo_ok
        lda #<MIP_LOAD                  ; the TCP/IP stack, last: the unpacker used bank 4
        sta ld_dest
        lda #>MIP_LOAD
        sta ld_dest+1
        lda #`MIP_LOAD
        sta ld_dest+2
        lda #s_ethbin_end - s_ethbin
        ldx #<s_ethbin
        ldy #>s_ethbin
        jsr load_file                   ; (missing: net_start's self test says so)
        .if MOCK_NET
        lda #<MOCK_RX                   ; the recorded server session
        sta ld_attic
        lda #>MOCK_RX
        sta ld_attic+1
        lda #(MOCK_RX >> 16) & $ff
        sta ld_attic+2
        lda #MOCK_RX >> 24
        sta ld_attic+3
        lda #s_mockrx_end - s_mockrx
        ldx #<s_mockrx
        ldy #>s_mockrx
        jsr load_to_attic
        lda ld_len
        sta mock_rx_len
        lda ld_len+1
        sta mock_rx_len+1
        .endif

        #TAKEOVER
        lda #0                          ; clear the base page (random on real hardware)
        ldx #2
-       sta $00,x
        inx
        cpx #zp_end
        bne -
        jsr dma_init
        jsr net_install
        jsr irq_install
        jsr rom_save                    ; the ROM image to attic: Exit puts it back
        jsr rom_unprotect               ; the framebuffer lives in $20000-$3FFFF
        lda #GC_BLACK
        sta f640_fill
        lda #0
        jsr f640_clear
        jsr f640_init
        cli
        jsr gui_init
        jsr sid_init                    ; (the page chime; sound.asm)
        jsr art_palette
        jsr login_open
        lda #1
        sta dbg_ready

main_loop:
        jsr net_wait_frame              ; (plain wait_frame while the network is off)
        inc frames
        bne +
        inc frames+1
+       jsr busy_frame                  ; (the hourglass while waiting for the server)
        jsr link_frame                  ; (the connectivity icon; PING when it's quiet)
        jsr sound_frame                 ; (the chime's notes)
        jsr storage_frame               ; (an upload going out)
        jsr gui_update
        bcc +
        jsr on_event
+       jsr login_step
        bra main_loop

; a gui event: the client's own windows ($F0-$FF) here, the server's go to the server
on_event:
        lda ge_type                     ; a notification icon: the connectivity icon is ours,
        cmp #GE_NOTIFY                  ; the rest the server's (its slot = ours - 1)
        bne +
        lda login_state
        cmp #3
        bne _out
        lda ge_val
        cmp #LINK_SLOT
        bne _srv
        jmp link_click
_srv:   dec ge_val
        jmp proto_gui_event
+       cmp #GE_MENU                    ; a menu pick: ours ($F0+) or the server's
        bne _win
        lda ge_val
        cmp #$f0
        bcc +
        jmp exit_menu_pick
+       lda login_state
        cmp #3
        bne _out
        jmp proto_gui_event
_out:   rts
_win:   lda ge_win
        cmp #AW
        bne +
        jmp alert_event
+       cmp #XW
        bne +
        jmp exit_event
+       cmp #$f0
        bcc +
        jmp login_event
+       lda login_state                 ; signed on, or signing up (state 2: the server's
        cmp #2                          ; sign-up wizard runs before LOGIN_RESULT)
        bcc +
        jmp proto_gui_event
+       rts

; palette entries 16-254: the art's (gen/palette.asm)
art_palette:
        ldx #16
-       lda palette_rgb,x
        jsr gui_swap
        sta $d100,x
        lda palette_rgb+256,x
        jsr gui_swap
        sta $d200,x
        lda palette_rgb+512,x
        jsr gui_swap
        sta $d300,x
        inx
        cpx #255
        bne -
        rts

frames:         .word 0
dbg_ready:      .byte 0                 ; 1 once the sign-on screen is up (tests)
s_ethbin:       .text "ETHBIN"
s_ethbin_end:
s_mockrx:       .text "MOCKRX"
s_mockrx_end:

        .include "login.asm"
        .include "exit.asm"
        .include "net.asm"
        .include "proto.asm"
        .include "sound.asm"
        .include "link.asm"
        .include "storage.asm"
        .include "sdwrite.asm"
        .include "lib/kstream.asm"
        .include "lib/system.asm"
        .include "lib/dma.asm"
        .include "lib/loader.asm"
        .include "lib/unpack.asm"
        .include "lib/manifest.asm"
        .include "lib/fcm640.asm"
        .include "lib/draw640.asm"
        .include "lib/font8.asm"
        .include "lib/keyboard.asm"
        .include "lib/mouse.asm"
        .include "lib/hwsprite.asm"
        .include "lib/sid.asm"
        .include "lib/gui/gui.asm"
        .include "lib/gui/grid.asm"
        .include "gen/manifest.asm"
        .include "gen/palette.asm"

        .dsection bss

        .cerror * > $cfff, "program overflows into I/O space at $D000"
        .cerror BRIDGE_NET && * > BR_RX, format("the program (to $%04x) runs into the bridge rings at $CD00", *)
