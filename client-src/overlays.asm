;=======================================================================================
; overlays.asm - the client's overlays (lib/overlay.asm): code used now and then runs in one
; window (OVL_BASE..OVL_END) and lives in attic the rest of the time. Resident: this file.
;
;   OVL_FILES (OVL0)  storage.asm, sdwrite.asm: the File Library's disk and SD-card work
;   OVL_ART   (OVL1)  picture.asm, canvas.asm: the Art Gallery's pictures and Paint
;   OVL_UI    (OVL2)  desk.asm, signon.asm: the live desktop (ticker, who's online, icon
;                     badges); the Connect, Sign On and Static Address windows
;   OVL_DEBUG (OVL3)  netlog.asm: the debug build's connection log (build.bat debug)
;
; Everything outside an overlay reaches into it through the stubs here (#FAR: the window is
; written back to attic after each call, so an overlay keeps its variables). Variables the
; resident part reads (st_mode, pic_on) live here. The overlays call the resident part
; directly; they never call each other.
;
; For the Xemu harness, at_*: where an overlay's variable is in attic (current between
; calls, since every call writes the overlay back).
;=======================================================================================

OVL_COUNT       = DEBUG_NET ? 4 : 3
OVL_FILES       = 0
OVL_ART         = 1
OVL_UI        = 2
OVL_DEBUG       = 3                     ; (the debug build: netlog.asm)
OVL_END         = BRIDGE_NET ? $cd00 : $cf00    ; (the bridge build's rings start at $CD00;
                                                ; sidplay.asm's call routine is at $CF10)
OVL_BASE        = OVL_END - $16a0       ; the window: as big as the biggest overlay (OVL0:
                                        ; $1668 bytes, $1694 in the bridge build; main.asm
                                        ; stops the build if one grows past it, or the
                                        ; resident part reaches it)

st_mode:        .byte 0                 ; storage.asm: 0 idle, 1 a download arriving, 2 an
                                        ; upload going
pic_on:         .byte 0                 ; picture.asm: 1 while a picture shows
        .if BRIDGE_NET
dbg_sdw:        .byte 0, 0, 0           ; storage.asm (a test): poke 1: write the staged file
        .endif                          ; to the SD card; then the status, and a count

; the protocol's handlers (proto.asm's table)
far_local_dir:  #FAR OVL_FILES, pm_local_dir
        rts
far_save_begin: #FAR OVL_FILES, pm_save_begin
        rts
far_file_data:  #FAR OVL_FILES, pm_file_data
        rts
far_file_end:   #FAR OVL_FILES, pm_file_end
        rts
far_load_file:  #FAR OVL_FILES, pm_load_file
        rts
far_local_cancel: #FAR OVL_FILES, pm_local_cancel
        rts
far_picture:    #FAR OVL_ART, pm_picture
        rts
far_picture_end: #FAR OVL_ART, pm_picture_end
        rts
far_canvas:     #FAR OVL_ART, pm_canvas
        rts
far_canvas_end: #FAR OVL_ART, pm_canvas_end
        rts
far_canvas_rect: #FAR OVL_ART, pm_canvas_rect
        rts
far_canvas_pen: #FAR OVL_ART, pm_canvas_pen
        rts
far_ticker:     #FAR OVL_UI, pm_ticker
        rts
far_desk_line:  #FAR OVL_UI, pm_desk_line
        rts
far_desk_badge: #FAR OVL_UI, pm_desk_badge
        rts
far_desk_draw:  #FAR OVL_UI, desk_draw        ; (login.asm's desktop hook, signed on)
        rts

; every 8th frame, signed on: the ticker one character on (desk.asm)
desk_frame:
        lda frames
        and #7
        bne +
        lda login_state
        cmp #LS_ON
        bne +
        #FAR OVL_UI, desk_tick
+       rts

; once a frame: an upload going out (only then into the overlay)
storage_frame:
        .if BRIDGE_NET
        lda dbg_sdw
        bne +
        .endif
        lda st_mode
        cmp #2
        beq +
        rts
+       #FAR OVL_FILES, st_frame
        rts

far_pic_frame:  #FAR OVL_ART, pic_frame
        rts
far_pic_off:    #FAR OVL_ART, pic_off
        rts
far_cv_off:     #FAR OVL_ART, cv_off
        rts
; Paint's desktop hooks (gui_desk_hook, gui_desk_input: A = GUI_DK_*)
far_cv_draw:    #FAR OVL_ART, cv_draw
        rts
far_cv_input:   #FAR OVL_ART, cv_input
        rts

; the harness's view of overlay variables, in attic
; ((x - OVL_BASE) * 1: 64tass keeps a label difference a 16-bit address, which wraps when
; added to a 28-bit one; times 1 makes it a plain number)
at_st_size      = OVL_ATTIC + OVL_FILES * $10000 + (st_size - OVL_BASE) * 1
at_fw_need      = OVL_ATTIC + OVL_FILES * $10000 + (fw_need - OVL_BASE) * 1
at_st_pos       = OVL_ATTIC + OVL_FILES * $10000 + (st_pos - OVL_BASE) * 1
at_dd_first     = OVL_ATTIC + OVL_FILES * $10000 + (dd_first - OVL_BASE) * 1
