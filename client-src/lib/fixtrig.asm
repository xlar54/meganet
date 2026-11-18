;=======================================================================================
; lib/fixtrig.asm - sine and cosine in 16.16 fixed point, of an angle in degrees: whole
; degrees from a table, linear in between (Lightsource's parser and modeller; bit-exact
; with private/tools/fxmath.py fsin_deg).
;
;   fsin_deg / fcos_deg   fs_a = the angle (16.16 degrees; changed) -> Q
; Needs lib/fixed.asm. FT_PTR: a base-page word it may change (default ptr0; Lightsource
; sets it to lp, because its parser keeps the text pointer in ptr0).
;=======================================================================================

        .weak
FT_PTR          = ptr0
        .endweak
; sine and cosine of fs_a (degrees, 16.16) -> Q: whole degrees from a table, linear in
; between (pov.py's fxmath.fsin_deg)
;---------------------------------------------------------------------------------------
fcos_deg:
        #LDIMM 90 * ONE, l_ft_t
        #ADDQ fs_a, l_ft_t, fs_a
fsin_deg:
        ; r = a mod 360, 0 <= r < 360
        #ABSQ fs_a, fs_r
        ldq fs_r
        stq MULTINA
        #LDIMM 360 * ONE, l_ft_t
        stq MULTINB
-       bit DIVBUSY
        bmi -
        ldq DIVOUT+4                    ; q = |a| div 360
        stq MULTINA
        #LDIMM 360 * ONE, l_ft_t
        stq MULTINB
        #SUBQ fs_r, MULTOUT, fs_r       ; |a| - q 360
        bit fs_a+3
        bpl +
        #BEQZ fs_r, +
        #LDIMM 360 * ONE, l_ft_t            ; a < 0: 360 - that
        #SUBQ l_ft_t, fs_r, fs_r
+       lda #0
        sta fs_neg
        #LDIMM 180 * ONE, l_ft_t
        #BLTQ fs_r, l_ft_t, +               ; r >= 180: -sin(r - 180)
        lda #1
        sta fs_neg
        #SUBQ fs_r, l_ft_t, fs_r
+       #LDIMM 90 * ONE, l_ft_t
        #BLEQ fs_r, l_ft_t, +               ; r > 90: sin(180 - r)
        #LDIMM 180 * ONE, l_ft_t
        #SUBQ l_ft_t, fs_r, fs_r
+       lda fs_r+2                      ; i = whole degrees (0..90), f = the fraction
        cmp #90
        bcc +
        #MOVQ sin_t+90*4, fs_s
        bra _sign
+       sta FT_PTR                          ; FT_PTR = sin_t + 4 i (16-bit: i reaches 89)
        lda #0
        sta FT_PTR+1
        asl FT_PTR
        rol FT_PTR+1
        asl FT_PTR
        rol FT_PTR+1
        clc
        lda FT_PTR
        adc #<sin_t
        sta FT_PTR
        lda FT_PTR+1
        adc #>sin_t
        sta FT_PTR+1
        ldy #0
-       lda (FT_PTR),y
        sta fs_s,y
        iny
        cpy #4
        bne -
        ldx #0
-       lda (FT_PTR),y
        sta fs_n,x
        iny
        inx
        cpx #4
        bne -
        #SUBQ fs_n, fs_s, fs_n          ; s = t[i] + (t[i+1] - t[i]) f
        lda fs_r
        sta l_ft_t
        lda fs_r+1
        sta l_ft_t+1
        lda #0
        sta l_ft_t+2
        sta l_ft_t+3
        #FMUL fs_n, l_ft_t, l_ft_t
        #ADDQ fs_s, l_ft_t, fs_s
_sign:
        lda fs_neg
        beq +
        #NEGQ fs_s, fs_s
+       ldq fs_s
        rts

sin_t:
        .for xi = 0, xi < 91, xi += 1
        .dint FX(sin(rad(xi)))
        .next

fs_a:           .dword 0
l_ft_t:         .dword 0
fs_r:           .dword 0
fs_s:           .dword 0
fs_n:           .dword 0
fs_neg:         .byte 0
