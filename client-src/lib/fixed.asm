;=======================================================================================
; lib/fixed.asm - 16.16 signed fixed point on the 45GS02's 32-bit Q register (A, X, Y, Z
; = bytes 0..3) and the hardware multiplier / divider.
;
;   fmul     Q = fm_a * Q          floor((a * b) >> 16), signed
;   fdiv     Q = fd_a / Q          trunc((|a| << 16) / |b|), with the sign of a * b. The
;                                  caller keeps the quotient in range (and b nonzero)
;   fsqrt    Q = sqrt(Q)           floor(sqrt(x << 16)), x >= 0 (Newton on the divider)
;   ppow     Q = Q ^ pw_e          x >= 0, pw_e = 16-bit exponent, worked in 0.32: for
;                                  Phong highlights (x <= 1)
; All of them change A, X, Y and Z. q_zero and q_one are the constants 0 and 1.0.
;
; Macros (operands are addresses of dwords; vectors are 12 bytes: x, y, z):
;   #MOVQ src, dst   #ADDQ a, b, dst   #SUBQ a, b, dst   #NEGQ src, dst   #LDIMM v, dst
;   #FMUL a, b, dst  #FDIV a, b, dst
;   #VMOV src, dst   #VADD a, b, dst   #VSUB a, b, dst   #VSCALE v, s, dst   #DOT a, b, dst
;   #ASLQ_Q / #LSRQ_Q / #ASRQ_Q (the Q register), #ASLQ_M / #LSRQ_M addr (a dword)
;   #BGTQ a, b, label / #BLEQ / #BLTQ (branch on a compare), #BEQZ / #BNEZ a, label,
;   #ABSQ src, dst, #DBLQ src, dst
;   FX(v) (a function): float -> 16.16, for tables: .dint FX(0.4)
;
; The macros leave their result in Q as well as in dst, so a test can follow directly:
;   #SUBQ a, b, tmp / bmi a_less_than_b   (N = bit 31; test zero with lda/ora of the bytes)
;
; Needs the base-page variables in lib/fixed_zp.asm: include that inside the project's
; .virtual block in zp.asm.
;
; 64tass 1.60 has ldq/stq/adq/sbq/cpq/anq/orq/eoq but not the Q shifts: they are the
; $42 $42 prefix on the 8-bit opcodes, emitted here as bytes. Lightsource tested all of it
; bit-exact against a Python model (private/tools/ref_trace.py there) in Xemu.
;=======================================================================================

ONE             = $10000                ; 1.0

FX              .function v
                .endf int(round(v * 65536.0))   ; float -> 16.16

; ---- Q shifts (whole Q register) ----------------------------------------------------
ASLQ_Q .macro
        .byte $42, $42, $0a
.endm
LSRQ_Q .macro
        .byte $42, $42, $4a
.endm
ASRQ_Q .macro
        .byte $42, $42, $43
.endm
; ---- Q shifts of a dword in memory (absolute) ----------------------------------------
ASLQ_M .macro addr
        .byte $42, $42, $0e, <(\addr), >(\addr)
.endm
LSRQ_M .macro addr
        .byte $42, $42, $4e, <(\addr), >(\addr)
.endm

; ---- moves and arithmetic --------------------------------------------------------------
MOVQ .macro src, dst
        ldq \src
        stq \dst
.endm
ADDQ .macro a, b, dst                   ; dst = a + b
        clc
        ldq \a
        adq \b
        stq \dst
.endm
SUBQ .macro a, b, dst                   ; dst = a - b
        sec
        ldq \a
        sbq \b
        stq \dst
.endm
NEGQ .macro src, dst                    ; dst = -src
        sec
        ldq q_zero
        sbq \src
        stq \dst
.endm
FMUL .macro a, b, dst                   ; dst = a * b
        ldq \a
        stq fm_a
        ldq \b
        jsr fmul
        stq \dst
.endm
FDIV .macro a, b, dst                   ; dst = a / b
        ldq \a
        stq fd_a
        ldq \b
        jsr fdiv
        stq \dst
.endm
LDIMM .macro v, dst                     ; dst = constant (raw 32-bit)
        lda #<(\v)
        ldx #>(\v)
        ldy #`(\v)
        ldz #(((\v) >> 24) & $ff)
        stq \dst
.endm

; ---- comparing dwords, and branching (signed; the values must not differ by 2^31 or
; more). Segments, not macros: their + labels stay inside. ---------------------------
; branch if a > b
BGTQ .segment a, b, label
        sec
        ldq \b
        sbq \a
        bmi \label
.endsegment
; branch if a <= b
BLEQ .segment a, b, label
        sec
        ldq \b
        sbq \a
        bpl \label
.endsegment
; branch if a < b
BLTQ .segment a, b, label
        sec
        ldq \a
        sbq \b
        bmi \label
.endsegment
; branch if the dword is zero
BEQZ .segment a, label
        lda \a
        ora \a+1
        ora \a+2
        ora \a+3
        beq \label
.endsegment
BNEZ .segment a, label
        lda \a
        ora \a+1
        ora \a+2
        ora \a+3
        bne \label
.endsegment
; dst = |src|
ABSQ .segment src, dst
        ldq \src
        stq \dst
        bit \dst+3
        bpl +
        #NEGQ \src, \dst
+
.endsegment
; dst = arithmetic shift left of src by one
DBLQ .segment src, dst
        ldq \src
        #ASLQ_Q
        stq \dst
.endsegment

; ---- vectors ---------------------------------------------------------------------------
VMOV .macro src, dst
        #MOVQ \src, \dst
        #MOVQ \src+4, \dst+4
        #MOVQ \src+8, \dst+8
.endm
VADD .macro a, b, dst
        #ADDQ \a, \b, \dst
        #ADDQ \a+4, \b+4, \dst+4
        #ADDQ \a+8, \b+8, \dst+8
.endm
VSUB .macro a, b, dst
        #SUBQ \a, \b, \dst
        #SUBQ \a+4, \b+4, \dst+4
        #SUBQ \a+8, \b+8, \dst+8
.endm
VSCALE .macro a, s, dst                 ; dst = a * scalar s
        #FMUL \a, \s, \dst
        #FMUL \a+4, \s, \dst+4
        #FMUL \a+8, \s, \dst+8
.endm
DOT .macro a, b, dst                    ; dst = a . b  (x, y, z products summed in order)
        #FMUL \a, \b, dt_s
        #FMUL \a+4, \b+4, dt_t
        clc
        ldq dt_s
        adq dt_t
        stq dt_s
        #FMUL \a+8, \b+8, dt_t
        clc
        ldq dt_s
        adq dt_t
        stq \dst
.endm

;---------------------------------------------------------------------------------------
; fmul: Q = fm_a * Q (signed 16.16). The multiplier is unsigned: the signed product's
; bits 32..47 lose b (if a < 0) and a (if b < 0). Both positive: the product as it comes.
;---------------------------------------------------------------------------------------
fmul:
        stq fm_b
        stq MULTINB
        ldq fm_a
        stq MULTINA
        cpz #$80                        ; (Z = a's top byte)
        bcs _signed
        bit fm_b+3
        bmi _signed
        ldq MULTOUT+2
        rts
_signed:
        ldq MULTOUT+2
        stq fm_r
        bit fm_a+3
        bpl +
        sec
        lda fm_r+2
        sbc fm_b
        sta fm_r+2
        lda fm_r+3
        sbc fm_b+1
        sta fm_r+3
+       bit fm_b+3
        bpl +
        sec
        lda fm_r+2
        sbc fm_a
        sta fm_r+2
        lda fm_r+3
        sbc fm_a+1
        sta fm_r+3
+       ldq fm_r
        rts

;---------------------------------------------------------------------------------------
; fdiv: Q = fd_a / Q, truncated towards zero. Caller keeps the quotient in range.
;---------------------------------------------------------------------------------------
fdiv:
        stq fd_b
        lda fd_a+3
        eor fd_b+3
        sta fd_sgn
        bit fd_b+3
        bpl +
        #NEGQ fd_b, fd_b
+       ldq fd_b
        stq MULTINB
        bit fd_a+3
        bpl +
        #NEGQ fd_a, fd_a
+       ldq fd_a
        stq MULTINA
-       bit DIVBUSY
        bmi -
        ldq DIVOUT+2
        bit fd_sgn
        bpl +
        stq fd_b
        #NEGQ fd_b, fd_b                ; (leaves the result in Q)
+       rts

;---------------------------------------------------------------------------------------
; fsqrt: Q = floor(sqrt(Q << 16)) for Q >= 0 (negative inputs give 0).
; Newton from above: g = 2^ceil((bits(x) + 16) / 2) >= the root; g' = (g + N/g) / 2,
; where N/g = floor(x * 2^16 / g) = DIVOUT bytes 2..5 of x / g; stop when g' >= g.
;---------------------------------------------------------------------------------------
fsqrt:
        stq sq_x
        bit sq_x+3
        bmi _zero
        ; bit length of x -> e = ceil((len + 16) / 2)
        ldx #3
-       lda sq_x,x
        bne +
        dex
        bpl -
_zero:
        ldq q_zero
        rts
+       tay
        lda l_fx_bitlen,y                   ; 1..8
        sta sq_t
        txa                             ; byte index * 8
        asl
        asl
        asl
        clc
        adc sq_t                        ; bit length 1..32
        clc
        adc #17                         ; len + 16 + 1
        lsr                             ; e
        tay
        lda #0
        sta sq_g
        sta sq_g+1
        sta sq_g+2
        sta sq_g+3
        tya
        lsr
        lsr
        lsr
        tax                             ; byte e / 8
        tya
        and #7
        tay
        lda l_fx_bit,y
        sta sq_g,x
        ldq sq_x
        stq MULTINA
_loop:
        ldq sq_g
        stq MULTINB
-       bit DIVBUSY
        bmi -
        ldq DIVOUT+2                    ; floor(N / g)
        clc
        adq sq_g
        #LSRQ_Q
        stq sq_n                        ; g'
        sec
        sbq sq_g                        ; g' - g >= 0: done
        bpl +
        #MOVQ sq_n, sq_g
        bra _loop
+       ldq sq_g
        rts

;---------------------------------------------------------------------------------------
; ppow: Q = Q ^ pw_e (pw_e = 16-bit exponent), 0 <= Q, result 16.16. Works in 0.32:
; u = x << 16 (1.0 or more -> $FFFFFFFF), r = $FFFFFFFF, then square-and-multiply from
; the lowest exponent bit; each product keeps its top 32 bits.
;---------------------------------------------------------------------------------------
ppow:
        stq l_fx_pu
        lda l_fx_pu+3
        ora l_fx_pu+2
        beq +
        #LDIMM $ffffffff, l_fx_pu          ; x >= 1.0
        bra _go
+       lda l_fx_pu+1                      ; u = x << 16
        sta l_fx_pu+3
        lda l_fx_pu
        sta l_fx_pu+2
        lda #0
        sta l_fx_pu
        sta l_fx_pu+1
_go:
        #LDIMM $ffffffff, l_fx_pr
        lda pw_e
        sta l_fx_pk
        lda pw_e+1
        sta l_fx_pk+1
_loop:
        lda l_fx_pk
        ora l_fx_pk+1
        beq _done
        lsr l_fx_pk+1
        ror l_fx_pk
        bcc +
        ldq l_fx_pr                        ; r = r * u
        stq MULTINA
        ldq l_fx_pu
        stq MULTINB
        ldq MULTOUT+4
        stq l_fx_pr
+       lda l_fx_pk                        ; (no further bits: skip the last squaring)
        ora l_fx_pk+1
        beq _done
        ldq l_fx_pu                        ; u = u * u
        stq MULTINA
        stq MULTINB
        ldq MULTOUT+4
        stq l_fx_pu
        bra _loop
_done:
        lda l_fx_pr+2                      ; >> 16
        ldx l_fx_pr+3
        ldy #0
        ldz #0
        rts

pw_e:           .word 0                 ; ppow's exponent
l_fx_pu:        .dword 0
l_fx_pr:        .dword 0
l_fx_pk:        .word 0
q_zero:         .dword 0
q_one:          .dword ONE
l_fx_bit:        .byte 1, 2, 4, 8, 16, 32, 64, 128
l_fx_bitlen:
        .for l_fx_i = 0, l_fx_i < 256, l_fx_i += 1
        .byte (l_fx_i == 0) ? 0 : (l_fx_i < 2 ? 1 : (l_fx_i < 4 ? 2 : (l_fx_i < 8 ? 3 : (l_fx_i < 16 ? 4 : (l_fx_i < 32 ? 5 : (l_fx_i < 64 ? 6 : (l_fx_i < 128 ? 7 : 8)))))))
        .next
