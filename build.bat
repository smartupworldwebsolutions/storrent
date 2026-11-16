@echo off
REM Builds STorrent.exe and the Windows installer.
REM Needs: Python 3.11 (64-bit) and Inno Setup 6 (https://jrsoftware.org/isdl.php)
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name STorrent --icon storrent.ico ^
  --add-data "storrent.ico;." --add-data "storrent.png;." --collect-all libtorrent storrent.py
if errorlevel 1 goto :fail
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" installer.iss
if errorlevel 1 goto :fail
echo.
echo Done. Installer is in the Output folder.
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1
