;=======================================================================================
; lib/tui/tui_help_defs.asm - what help text needs, without the viewer: include this to assemble
; help topics by themselves.
;=======================================================================================
HLINK_BACK      = $FE

HLINK   .macro topic, words
        .byte 1, \topic + 1
        .text \words
        .byte 2
        .endmacro
