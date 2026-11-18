;=======================================================================================
; lib/tui/tui_dialog.inc - the dialog table format: the constants and the macros that build one.
; Included by tui_dialog.asm. Code that only builds dialog tables, for a tui_dialog it doesn't
; contain itself, includes just this (an MSEdit plugin does, for API_DIALOG).
;=======================================================================================

DLG_AUTO        = $FF                   ; as a column: centre this control
DC_LABEL        = 1
DC_TEXT         = 2
DC_CHECK        = 3
DC_RADIO        = 4
DC_BUTTON       = 5
DC_LIST         = 6
DC_FRAME        = 7
DC_HLINE        = 8

DH_LIST         = 1
DH_BUTTON       = 2
DH_TOGGLE       = 3
DH_INIT         = 4

ID_OK           = 1
ID_YES          = 1
ID_NO           = 2
MB_OK           = 0
MB_YESNOCANCEL  = 1
MB_OKCANCEL     = 2

DLG     .macro h, w, title, hook
        .byte \h, \w
        .word \title, \hook
        .endmacro
DLG_END .macro
        .byte 0
        .endmacro
DLG_LABEL .macro row, col, text
        .byte DC_LABEL, \row, \col, 0
        .word \text, 0
        .byte 0
        .endmacro
DLG_TEXT .macro row, col, width, buffer, maxlen, upper=0
        .byte DC_TEXT, \row, \col, \width
        .word \buffer
        .byte \maxlen, \upper, 0
        .endmacro
DLG_CHECK .macro row, col, text, var
        .byte DC_CHECK, \row, \col, 0
        .word \text, \var
        .byte 0
        .endmacro
DLG_RADIO .macro row, col, text, var, value
        .byte DC_RADIO, \row, \col, 0
        .word \text, \var
        .byte \value
        .endmacro
DLG_BUTTON .macro row, col, text, id, default=0
        .byte DC_BUTTON, \row, \col, 0
        .word \text
        .byte \default, 0, \id
        .endmacro
DLG_LIST .macro row, col, width, height, provider, state
        .byte DC_LIST, \row, \col, \width
        .word \provider, \state
        .byte \height
        .endmacro
DLG_FRAME .macro row, col, height, width, title
        .byte DC_FRAME, \row, \col, \width
        .word \title
        .byte \height, 0, 0
        .endmacro
DLG_HLINE .macro row
        .byte DC_HLINE, \row, 0, 0
        .word 0, 0
        .byte 0
        .endmacro
