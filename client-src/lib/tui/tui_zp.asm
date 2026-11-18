;=======================================================================================
; lib/tui/tui_zp.asm - base-page variables for the TUI. Include after lib/zp.asm; a project's
; own base-page variables continue from TUI_ZP_END.
;=======================================================================================
        .virtual LIB_ZP_END
tui_sp:         .dword ?                ; screen RAM address of the output position
tui_cp:         .dword ?                ; colour RAM address of the output position
tui_str:        .word ?                 ; string being printed
tui_dp:         .word ?                 ; dialog control / menu item being handled
tui_fp:         .dword ?                ; far pointer: file lists and help text in other banks
TUI_ZP_END:
        .endv
