@echo off
setlocal
REM MEGA65 build: (optional) build assets, assemble with 64tass, write the D81 with c1541.
REM Rename PROJECT for a new project. The disk's first file is AUTOBOOT.C65, a one-line
REM BASIC program (10 RUN "PROJECT", from tools\autoboot.py): Xemu -autoload runs the first
REM file and a real MEGA65 runs AUTOBOOT.C65 at power-on, so both start the game, which is
REM on the disk only once.
set PROJECT=meganet
REM Overlays (lib/overlay.asm): their numbers in hex, e.g. set OVERLAYS=0 1 2. Empty: one
REM plain program. With overlays, main.asm is laid out in sections (res, ovl0, ovl1, ...;
REM src/lib/README.md, "Overlays") and each one becomes its own file on the disk.
set OVERLAYS=
if not exist target mkdir target
REM c1541 writes its settings under the user profile: keep them inside target\
if not exist target\userprofile\AppData\Roaming mkdir target\userprofile\AppData\Roaming
set "USERPROFILE=%CD%\target\userprofile"
set "APPDATA=%USERPROFILE%\AppData\Roaming"

del target\*.d81 2>nul
del target\*.lst 2>nul
del target\*.lbl 2>nul
del target\%PROJECT% 2>nul

REM build.bat mock FILE: the Xemu replay build (no network there). FILE is a server session
REM recorded by private\tools\record_mock.py; it replaces the network.
set MOCKDEF=
set MOCKARG=
if /i "%~1"=="mock" (
    set MOCKDEF=-D MOCK_NET=1
    set "MOCKARG=--mock %~2"
)
REM build.bat bridge: the live Xemu build. private\tools\xemu_bridge.py (bridge.bat) carries
REM its traffic to and from the real server through Xemu's monitor.
if /i "%~1"=="bridge" set MOCKDEF=-D BRIDGE_NET=1

REM Assets: client-src\assets (the logo PNG) -> client-src\gen\*, target\assets\*; the
REM TCP/IP stack (client-src\mega-ip) -> target\assets\ethbin
python tools\build_assets.py %MOCKARG%
if errorlevel 1 exit /b 1

REM M65DEFS: extra 64tass defines for test builds, e.g. set M65DEFS=-D DBG_ROWS=8
set TASS=.\64tass.exe -C -I client-src %MOCKDEF% %M65DEFS% client-src\main.asm
if not "%OVERLAYS%"=="" goto overlays
%TASS% --cbm-prg -l target\%PROJECT%.lbl -L target\%PROJECT%.lst -o target\%PROJECT%
if errorlevel 1 exit /b 1
goto assembled
:overlays
REM one assembly, one file per section: --flat writes from address 0, cut.py keeps the section
%TASS% --flat --output-section=res -l target\%PROJECT%.lbl -L target\%PROJECT%.lst -o target\%PROJECT%
if errorlevel 1 exit /b 1
python tools\cut.py target\%PROJECT% 0x1fff
if errorlevel 1 exit /b 1
for %%n in (%OVERLAYS%) do (
    %TASS% --flat --output-section=ovl%%n -o target\ovl%%n >nul
    if errorlevel 1 (echo overlay %%n failed & exit /b 1)
    python tools\cut.py target\ovl%%n 0x1%%n0000
    if errorlevel 1 exit /b 1
)
:assembled

python tools\autoboot.py %PROJECT% target\autoboot
if errorlevel 1 exit /b 1
REM BASIC 65 programs (src\basic\NAME.bas, in lower case) -> target\NAME, tokenised by petcat
if exist client-src\basic\*.bas for %%f in (client-src\basic\*.bas) do (
    .\petcat.exe -w65 -l 2001 -o target\%%~nf -- %%f >nul
    if errorlevel 1 (echo petcat failed on %%f & exit /b 1)
)
cd target
..\c1541.exe -format "%PROJECT%,01" d81 %PROJECT%.d81 >nul
if errorlevel 1 (cd .. & exit /b 1)
..\c1541.exe -attach %PROJECT%.d81 -write autoboot autoboot.c65 >nul
if errorlevel 1 (cd .. & exit /b 1)
..\c1541.exe -attach %PROJECT%.d81 -write %PROJECT% %PROJECT% >nul
if errorlevel 1 (cd .. & exit /b 1)
for %%n in (%OVERLAYS%) do (
    ..\c1541.exe -attach %PROJECT%.d81 -write ovl%%n ovl%%n >nul
    if errorlevel 1 (echo failed writing ovl%%n & cd .. & exit /b 1)
)
if exist ..\client-src\basic\*.bas for %%f in (..\client-src\basic\*.bas) do (
    ..\c1541.exe -attach %PROJECT%.d81 -write %%~nf %%~nf >nul
    if errorlevel 1 (echo failed writing %%~nf & cd .. & exit /b 1)
)
REM asset files listed by tools\build_assets.py (written lower case = PETSCII upper case)
if exist assets\files.txt for /f %%f in (assets\files.txt) do (
    ..\c1541.exe -attach %PROJECT%.d81 -write assets\%%f %%f >nul
    if errorlevel 1 (echo failed writing %%f & cd .. & exit /b 1)
)
cd ..

REM keep only the D81, the listing and the labels (the Xemu test harness reads them)
for %%f in (target\*) do (
    if /i not "%%~xf"==".d81" if /i not "%%~xf"==".lst" if /i not "%%~xf"==".lbl" del "%%f"
)
for /d %%d in (target\*) do rmdir /s /q "%%d"

echo Built target\%PROJECT%.d81
