@echo off
:: ============================================================================
:: build.bat  —  One-click portable build for UR Financial Extractor
::
:: Creates dist\UR_Financial_Extractor\ — zip it to distribute.
::
:: Usage
:: -----
::   build.bat              standard build
::   build.bat --clean      wipe previous output first, then build
::   build.bat --zip        build + create UR_Financial_Extractor_v1.0.zip
::
:: Prerequisites
:: -------------
::   pip install pyinstaller      (once, in the same venv)
::   UPX (optional, for compression): https://upx.github.io/
::
:: What the portable zip contains
:: --------------------------------
::   UR_Financial_Extractor.exe   launcher with extractor.ico icon
::   config.py                    user-editable settings (colours, timeouts …)
::   playwright/driver/           Node.js bridge that controls Edge via CDP
::   (all Python packages embedded — no separate installation needed)
::
:: Target machine requirements
:: ----------------------------
::   Windows 10 / 11 (x64)
::   Microsoft Edge   (pre-installed on all Windows 10/11 machines)
::   Nothing else     — no Python, no pip, no additional setup
:: ============================================================================

setlocal EnableDelayedExpansion
set NAME=UR_Financial_Extractor
set SPEC=UR_Extractor.spec
set VERSION=1.0
set ICO=extractor.ico

:: ── Activate the project virtual environment ─────────────────────────────────
:: build.bat may be launched from Explorer (no venv active in that shell).
:: We look for .venv in the same folder as this script and activate it so
:: pyinstaller and all project packages are on the PATH.
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%.venv\Scripts\activate.bat" (
    call "%SCRIPT_DIR%.venv\Scripts\activate.bat"
    echo [build] Virtual environment activated.
) else (
    echo [warn]  No .venv found next to build.bat.
    echo         Trying system Python / PATH instead.
)

:: ── Argument parsing ─────────────────────────────────────────────────────────
set DO_CLEAN=0
set DO_ZIP=0
for %%A in (%*) do (
    if /I "%%A"=="--clean" set DO_CLEAN=1
    if /I "%%A"=="--zip"   set DO_ZIP=1
)

:: ── Pre-flight checks ────────────────────────────────────────────────────────
if not exist "%SPEC%" (
    echo [error] %SPEC% not found.  Run from the project root directory.
    pause & exit /b 1
)
if not exist "%ICO%" (
    echo [error] %ICO% not found.  Place extractor.ico in the project root.
    pause & exit /b 1
)
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo [error] PyInstaller not found.
    echo         Run:  pip install pyinstaller
    pause & exit /b 1
)

:: ── Optional clean ───────────────────────────────────────────────────────────
if %DO_CLEAN%==1 (
    echo [build] Cleaning previous artefacts...
    if exist build\%NAME%  rmdir /s /q build\%NAME%
    if exist dist\%NAME%   rmdir /s /q dist\%NAME%
    echo [build] Done.
    echo.
)

:: ── Build ────────────────────────────────────────────────────────────────────
echo.
echo  +--------------------------------------------------+
echo  ^|  Building: %NAME%
echo  ^|  Icon:     %ICO%
echo  +--------------------------------------------------+
echo.

pyinstaller %SPEC%

if errorlevel 1 (
    echo.
    echo [error] BUILD FAILED — see output above.
    pause & exit /b 1
)

:: ── Copy user-editable files next to the exe ─────────────────────────────────
:: config.py and README.txt must sit alongside the exe so the user can edit
:: them without opening the bundle.
echo [build] Copying config.py and README.txt to dist\ ...
copy /Y config.py   dist\ >nul
copy /Y README.txt  dist\ >nul

:: ── Success report ───────────────────────────────────────────────────────────
echo.
echo  +--------------------------------------------------+
echo  ^|  BUILD SUCCESSFUL                               ^|
echo  ^|  Exe:    dist\%NAME%.exe      ^|
echo  ^|  Config: dist\config.py                        ^|
echo  ^|  Guide:  dist\README.txt                       ^|
echo  +--------------------------------------------------+
echo.

:: ── Optional ZIP ─────────────────────────────────────────────────────────────
if %DO_ZIP%==1 (
    set ZIPNAME=%NAME%_v%VERSION%.zip
    echo [build] Creating !ZIPNAME!...
    powershell -NoProfile -Command ^
        "Compress-Archive -Path 'dist\%NAME%.exe','dist\config.py','dist\README.txt' -DestinationPath '!ZIPNAME!' -Force"
    if errorlevel 1 (
        echo [error] ZIP creation failed.
    ) else (
        echo [build] ZIP ready: !ZIPNAME!
    )
    echo.
)

echo  Contents of the portable ZIP:
echo    %NAME%.exe    ^<- double-click to run
echo    config.py     ^<- edit colours / timeouts
echo    README.txt    ^<- user guide
echo.
pause
endlocal
