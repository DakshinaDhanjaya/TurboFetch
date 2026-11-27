@echo off
setlocal enabledelayedexpansion

echo === TurboFetch Build Script ===
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.11+ is not installed or not in PATH.
    exit /b 1
)

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
python -c "import PySide6, httpx, yt_dlp, imageio_ffmpeg, mutagen, PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies.
        exit /b 1
    )
)

echo Running unit tests...
python -m unittest discover -s turbofetch/tests -v
if errorlevel 1 (
    echo ERROR: Tests failed. Aborting build.
    exit /b 1
)

echo Building TurboFetch stage with PyInstaller...
python -m PyInstaller --noconfirm --onedir --windowed ^
    --name TurboFetch ^
    --distpath "%cd%\build\portable" ^
    --workpath "%cd%\build\work" ^
    --specpath "%cd%\build\work" ^
    --icon "%cd%\turbofetch\app\ui\icon.ico" ^
    --add-data "%cd%\turbofetch\extension;extension" ^
    --add-data "%cd%\turbofetch\app\ui\icon.ico;turbofetch\app\ui" ^
    --hidden-import "socksio" ^
    --collect-all "imageio_ffmpeg" ^
    --collect-all "mutagen" ^
    --collect-all "yt_dlp" ^
    "%cd%\turbofetch\app\main.py"
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)

if exist "dist\TurboFetch" rmdir /S /Q "dist\TurboFetch"

where iscc >nul 2>&1
if not errorlevel 1 (
    iscc "turbofetch\installer\turbofetch.iss"
    goto check_out
)
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "turbofetch\installer\turbofetch.iss"
    goto check_out
)
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" (
    "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" "turbofetch\installer\turbofetch.iss"
    goto check_out
)

echo Building standalone TurboFetch-Setup.exe...
python "turbofetch\installer\build_installer.py"

:check_out
if errorlevel 1 (
    echo ERROR: Installer build failed.
    exit /b 1
)
echo Build complete! Output: dist\TurboFetch-Setup.exe
