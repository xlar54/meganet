;=======================================================================================
; lib/fixed_zp.asm - base-page variables for lib/fixed.asm (39 bytes). Include it inside
; the project's base-page .virtual block (src/zp.asm):
;         .virtual LIB_ZP_END
;         .include "lib/fixed_zp.asm"
;   ...
;=======================================================================================
fm_a:           .dword ?                ; fmul: a (b comes in Q)
fm_b:           .dword ?
fm_r:           .dword ?
fd_a:           .dword ?                ; fdiv: a (b comes in Q)
fd_b:           .dword ?
fd_sgn:         .byte ?
dt_s:           .dword ?                ; #DOT
dt_t:           .dword ?
sq_x:           .dword ?                ; fsqrt
sq_g:           .dword ?
sq_n:           .dword ?
sq_t:           .byte ?
