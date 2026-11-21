MEGA65 library modules
======================

Include only what a project needs, after `platform.asm`, `lib/zp.asm` and the project's `zp.asm`.
Each file documents its routines at the top. Everything was tested in Xemu:
`private/examples/libdemo.asm`, `libdemo2.asm` and `libdemo3.asm` (kept out of git) between them use every module. The code comes
from mega-dust, mega-kong, deluxepaint65, mega-simcity, mega-elite, mega-python and
little-mega-people.

| Module | Needs | Gives |
|--------|-------|-------|
| `system.asm` | – | `#TAKEOVER` (macro), `irq_install` + `irq_hook` (per-frame routine), `wait_frame`, `rom_unprotect` |
| `dma.asm` | – | `#DMA_RUN list`, `dma_job` / `dma_go`, `dma_fill`, `dma_copy_far` (28-bit, splits at 1 MB boundaries), `dma_blit` list |
| `loader.asm` | dma | Boot-time KERNAL loading: `load_file` (to chip RAM), `load_to_attic` (through a staging buffer), `mount_d81` (HYPPO, D81 from the SD card), `print` |
| `unpack.asm` | loader, dma | Boot-time `load_packed_to_attic`: files packed by `tools/pack.py` (zero runs; graphics often halve), unpacked through chip RAM into attic. `unpack` on its own |
| `manifest.asm` | loader, unpack, dma | Boot-time `load_manifest`: loads every file in `src/gen/manifest.asm` (written by `tools/m65assets.py` `write_manifest`) to its attic address; `manifest_hook` per file (progress dots). Include `gen/manifest.asm` too |
| `overlay.asm` | dma, loader | Code overlays: more program than fits below `$D000`. `ovl_boot_load` (boot: every `OVLn` file into attic), `ovl_init`, `ovl_load` (one DMA into the window), `ovl_reload` (after disk calls), `#FAR OVL_X, routine` (call into another overlay and back, both keeping their variables; nests). See "Overlays" below |
| `kfile.asm` | – | `kfile_save` / `kfile_load` **after** the takeover (high scores, save games), through a KERNAL trampoline below `$2000`. `kfile_capture` must run at boot. |
| `kstream.asm` | – | SEQ and PRG files of any size **after** the takeover, a block at a time: `kst_open`, `kst_read`, `kst_write`, `kst_close`, `kst_status`, `kst_command` (DOS commands), `kst_getc` (a byte at a time), `kst_exists`, `kst_remove`, `kst_name_put`, `kst_present`, and `kst_dev` for the drive; directories (open `$`). `kst_to_basic` returns to READY. `kst_capture` must be the first call at boot. |
| `input.asm` | – | `read_input`: both joysticks, cursor keys, WASD, SPACE/RETURN fire, RUN/STOP; `joy`/`joy_new`, `dbg_joy`. Each source alone too, for two players: `joy_port1`, `joy_port2`, `joy_keys` |
| `keyboard.asm` | – | `key_get` / `key_wait` / `key_flush`: typed keys from the `$D610` hardware queue (for text entry); `dbg_keys` injection |
| `mouse.asm` | – | `mouse_init` / `mouse_poll`: 1351 mouse in either port, clamped position, debounced click and release edges |
| `video_fcm.asm` | dma | 320x200 Full Colour framebuffers (double-buffered, optional static HUD rows), palette, `fcm_present` / `fcm_irq` (hooked automatically), `fcm_clear`, full-screen picture screen |
| `fcm640.asm` | dma | 640x200 Full Colour Mode, 256 colours: two 128,000-byte framebuffers (row-major cells), `f640_init`, `f640_show`, `f640_clear`, `f640_row` + `#F640_PUT` (write a scan line pixel by pixel), `f640_palette` (256 entries from three tables), `f640_copy10` (buffer 1 to 0). Needs `f640_ptr` (dword) and `f640_pal_r/g/b` (words) on the project's base page. The buffers can be anywhere (`F640_BUF0/1`: buffer 1 in attic is drawn into, then shown with `f640_copy10`), and so can the screen RAMs (`F640_SCR0/1`, default `$12000` / `$13000` in bank 1, which leaves bank 0 to the program). A buffer in `$20000-$3FFFF` needs `rom_unprotect` first |
| `draw640.asm` | fcm640, font8, `dma_init` (the DMA list address bank 0) | Drawing into the 640x200 framebuffer, clipped to `d6_cx0..d6_cy1`: `d6_plot`, `d6_fill` (by DMA: one fill a cell, or one down each column of a part cell), `d6_hline` / `d6_vline` (one-row / one-column fills), `d6_frame`, `d6_line` (signed ends, clipped per pixel unless both ends are inside; `d6_line_in` when the caller knows they are), `d6_inside`, `d6_text` / `d6_char` (8x8 ASCII at any pixel row, transparent or on a colour). Font: `D6_FONT` (default `font8`) |
| `font8.asm` | - | An 8x8 font, ASCII 32-127, bit 7 = the left pixel (the IBM PC CGA ROM font, public domain) |
| `blit.asm` | dma, video_fcm | `blit_sprite`: column-major FCM sprites, transparent, clipped, bounding boxes |
| `vblit.asm` | dma, video_fcm | `vblit_sprite`: sprites of any size up to 255x255 (tables from a build tool, trimmed to the opaque box), from any chip-RAM or attic address; anchor-relative, clipped, `vb_clip` right edge for side panels |
| `fcm_text.asm` | video_fcm | `ftext_draw` / `ftext_centre` / `ftext_char` / `ftext_dec`: 8x8 text at any pixel position in the back buffer, any palette colour, optional drop shadow, multi-line (13). Font: `FTEXT_FONT`, 64 screen-code glyphs |
| `fcm_cache.asm` | dma, video_fcm | `cache_restore` / `cache_save`: keep a scene's static background in attic and restore it with one DMA copy a frame, instead of redrawing it |
| `sprite_touch.asm` | blit | `sprite_touch`: pixel-exact collision of two sprites at an offset (like hardware sprite collisions), reading only their bounding boxes' overlap |
| `draw.asm` | dma, video_fcm | `draw_plot`, `draw_vline` (one DMA), `draw_hline`, `draw_rect`, `draw_fill`, `draw_line`, `draw_circle`, `draw_disc` |
| `c64gfx.asm` | dma, blit, video_fcm | `c64_sprite`, `c64_charset`, `c64_koala`: C64 graphics to Full Colour |
| `hwsprite.asm` | – | The VIC-IV's 8 hardware sprites: `hws_init` (16-bit pointers, Xemu/hardware detection), `hws_shape`, `hws_place` (screen coordinates, all high bits, hardware X correction), `hws_on`/`off`, `hws_colour`, `is_real_hw`. VIC-IV extras: `hws_full_colour` (16 colours, 16 px wide), `hws_height` (tall sprites), `hws_pal_bank` / `hws_pal_edit` (a palette bank of their own; `hws_screen_bank`). `hws_from_bitmap`: 16-colour sprite data from 256-colour pixels anywhere (a tile, part of a framebuffer, attic): any width up to 16, any height up to 64, a pixel step (2 for art drawn two screen pixels to one in H640), a row stride and a colour table; the rest see-through |
| `text.asm` | dma | 40 or 80 column text console without the KERNAL: `text_init`, `text_clear`, `text_goto`, `putc`, `puts`, `#PRINT`, `put_hex`, `put_dec`; scrolls by DMA |
| `palette.asm` | video_fcm | `pal_set`, `pal_set_level` (brightness 0-255), `pal_fade_out` / `pal_fade_in` |
| `audio.asm` | – | `audio_init` (mixer routing), `audio_play` / `audio_stop` (samples on any channel), `stream_start` / `stream_frame` (long 8-bit or packed 4-bit audio from attic) |
| `sid.asm` | – | `sid_init`, `sfx_play`, `sfx_frame`: table-driven SID effects; `SID_MIRROR` = a second SID's address sends every write there too, for both speakers |
| `rtc.asm` | – | `rtc_read`: time and date in binary, 24-hour, validated (handles Xemu's binary month) |
| `fixed.asm` | – | 16.16 signed fixed point on the 32-bit Q register: `fmul`, `fdiv`, `fsqrt` (exact floor, Newton on the divider), `ppow` (Phong powers); `#MOVQ #ADDQ #SUBQ #NEGQ #FMUL #FDIV`, vector `#VADD #VSUB #VSCALE #DOT`, the Q shifts 64tass lacks (`#ASLQ_Q` ...), compare-and-branch segments (`#BGTQ #BLEQ #BLTQ #BEQZ #BNEZ`), `#ABSQ`, `#DBLQ`, `FX(v)` for tables. Include `lib/fixed_zp.asm` inside the project's base-page block (39 bytes) |
| `fixtrig.asm` | fixed | `fsin_deg` / `fcos_deg`: sine and cosine of an angle in degrees (16.16), whole degrees from a table and linear in between. `FT_PTR`: a base-page word it may change (default `ptr0`) |
| `math.asm` | – | `mul16`, `div16` (hardware), `rand`, `rand_seed_hw` (hardware RNG, bounded wait) |

For a DOS-style text interface (menus, dialogs, a file dialog, mouse, per-cell colours), see `src/lib/tui/README.md`.

For a graphical, Windows 95-style interface on the 640x200 256-colour screen (overlapping windows, buttons, text boxes, mouse pointer), see `lib/gui/README.md` (from MegaNet).

## Default memory layout

Override any default by defining the symbol before the `.include` (the defaults are `.weak`).

| Area | Default | Notes |
|------|---------|-------|
| Program | `$2001`-`$C7FF` | BASIC stub + `SYS 8210`. Must end below `$C800` when `video_fcm`'s picture screen is used. |
| Screen RAMs A / B | `$0800` / `$1000` | `video_fcm`: 2000 bytes each (16-bit chars) |
| Screen RAM C (pictures) | `$C800` | `video_fcm` |
| Text screen | `$0800` | `text.asm`: a different mode from `video_fcm`, so it can share the space |
| kfile trampoline | `$1800`-`$18C8` | Must be below `$2000`. Not `$0600`-`$07FF`, where the C65's sprite shapes live. |
| HYPPO name buffer | `$1E00` | Only while mounting at boot |
| Hardware sprite pointers | inside the program | `hws_ptrs`, 16-byte aligned. Shapes must be 64-byte aligned. |
| Audio ring | `$14000`-`$15FFF` | Must be chip RAM for audio DMA |
| `fcm640` buffers 0 / 1 | `$40000` / `$20000` (or attic) | 128,000 bytes each; screen RAMs `$12000` and `$13000` (4000 bytes each, bank 1) |
| FCM sprites | `$20000`-`$3FFFF` | Call `rom_unprotect` first. The text font is read from `$29800`, so don't overwrite it while text mode is in use. |
| Framebuffer A / picture | `$40000` | 64,000 bytes at 25 rows |
| Framebuffer B | `$50000` | |
| Loader staging | `$50000` | Boot only |
| Static HUD rows | `$4C800` | Only when `FB_ROWS` < 25 |
| Unpack buffer | `$40000` | `unpack.asm`, boot only |
| Overlay window | `$8000`-`$CFFF` | `overlay.asm` (`OVL_BASE` / `OVL_END`); the resident part must end below it |
| Overlays in attic | `$8700000` + n × `$10000` | `overlay.asm` (`OVL_ATTIC`), up to 16 |
| Background cache | `$8100000` | `fcm_cache.asm`, 64,000 bytes. Not in bank 1: `$1F800`-`$1FFFF` is colour RAM |
| Attic | `$8000000`-`$87FFFFF` | 8 MB |

Base page: `lib/zp.asm` uses `$02` to about `$44`; the project continues from `LIB_ZP_END`.
Everything stays below `$90` while the KERNAL is in use, either at boot or during `kfile` calls.

## Overlays

`lib/overlay.asm` lets a program be bigger than chip RAM's `$2000`-`$CFFF`: a resident part
that is always there, plus up to 16 overlays that take turns in one window (default
`$8000`-`$CFFF`, 20 KB). It comes from Lightsource (8 overlays: ray tracer, parser,
modeller, panel ...). `private/examples/ovldemo.asm` is a complete small example and test.

1. **Lay `main.asm` out in sections.** One assembly, so every overlay can use the resident
   part's labels:

   ```
   OVL_COUNT = 3                       ; (before including lib/overlay.asm)
   OVL_GAME  = 0
           * = $1fff
           .dsection res               ; the resident part
           .cerror * > OVL_BASE, "the resident part runs into the overlay window"
           * = $100000
           .dsection ovl0              ; overlay n at physical $100000 + n * $10000
           * = $110000
           .dsection ovl1
   ...
           .section res
           .word $2001                 ; the PRG's load address, then the BASIC stub
           ...
           .include "lib/overlay.asm"
           .send res

           .section ovl0
           .word 0                     ; the two bytes a LOAD skips
           .logical OVL_BASE
           .include "game.asm"
           .cerror * > OVL_END, "overlay 0 is too big"
           .endlogical
           .send ovl0
   ```

2. **Set `OVERLAYS=0 1 2` in `build.bat`** (hex digits). It writes the `res` section as the
   program and each `ovlN` as file `OVLN` on the disk (`64tass --flat --output-section`, then
   `tools/cut.py`).
3. **Boot:** `jsr ovl_boot_load` before `#TAKEOVER` (carry set: a file is missing), then
   `jsr ovl_init` after it.
4. **Run one:** `lda #OVL_GAME / jsr ovl_load`, then `jsr` its routines. A new `ovl_load` starts
   that overlay from its loaded state, so keep long-lived variables resident.
5. **From one overlay to another:** `#FAR OVL_MENU, menu_open`. The window goes back to attic
   first and returns afterwards, so both overlays keep their variables, and calls nest. A, X,
   Y and the flags pass both ways. A plain `jsr` to another overlay's label assembles but
   runs whatever is in the window: `python private/tools/ovl_check.py` finds those.
6. **After KERNAL disk calls** (`kstream`, `kfile`): `jsr ovl_reload`, because the DOS may
   have used part of the window.

Data an overlay reads only now and then (help text, error messages) can go past `OVL_END` in
its file (`.fill OVL_END - *, 0` first). `ovl_load` copies only the window, so it stays in
attic at `OVL_ATTIC + n * $10000 + (address - OVL_BASE)`, and the overlay DMAs in what it
needs. `docs/MEGA65_NOTES.md` section 11 has the rest of what was learned.

## Known working code elsewhere (not ported, use as reference)

| Need | Where |
|------|-------|
| RRB / GOTOX software sprites | `mega65-rrb-sample/src/modules/rrb_sprite.asm` (64tass, character rows only); `Mega65Tutorials/tutorial_8-10_*.asm` ("pixies", KickAss: pixel Y via colour-RAM Y shift, parallax, flipping) |
| NCM (16-colour chars), screen modes, NCM 4-way pixel scrolling | `m65-fcm/src/ncm.asm`, `fcm.asm` (`set_screen_mode`), `ncm_scroll.asm` |
| Flood fill, polygon, ellipse, arcs, gradients (row-major FCM; port the plot/address maths) | `m65-fcm/src/floodfill.asm`, `polygon.asm`, `ellipse.asm`, `gradient.asm`; `basic65-compiler/src/gfx/lib/arc.asm`; `deluxepaint65/src/graphics/` |
| Directory listing, file-exists, scratch, streamed save (KERNAL, boot state) | `deluxepaint65/src/paint/files.asm`; `mega-simcity/src/overlays/ovr-disk.asm` |
| SD-card FAT32 files: HYPPO `loadfile_attic` / findfile / rmfile; raw FAT32 writer | `megapc/src/disk.asm` (1054, 1371), `megapc/src/fat_writer.asm` |
| D81 file loading through the floppy controller (no KERNAL, read-only) | `M65_Examples/_include/floppyio.s` (KickAss) |
| LZ decompressor that copies with DMA, plus its cruncher | `Mega65Tutorials/build/MegaTool/DecrZero.s` (ca65) |
| Line editor with history | `mega-python/src/keyboard.asm` (`rl_read`) |
| Music: BASIC65 PLAY player (6 voices, SID1 + SID3), Elite title-music interpreter, small tune player | `basic65-compiler/src/runtime/runtime.asm` ~8109; `mega-elite/src/overlays/title_music.asm`; `little-mega-people/src/engine/sound.asm` |
| TCP/IP (ARP, DHCP, DNS, TCP) | `mega-ip/src` (64tass, built as a BASIC SYS library) |
| SAM speech into an audio-DMA ring | `megasam/src` |
| IFF ILBM load/save (ByteRun1) | `deluxepaint65/src/overlays/ovr-iff.asm` |
| Signed hardware maths, star field, 3D wireframe | `mega-elite/src/elite_math.asm`, `stars.asm`, `render.asm` |
| Returning cleanly to BASIC | `little-mega-people/src/engine/render.asm` (`screen_restore_basic`). Save the 4 CHARPTR bytes at boot: the font lives in WOM (`$FF7E000`) on real hardware. |
