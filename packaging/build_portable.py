"""Builds the direct-download PDFDrop zip (for Gumroad / Lemon Squeezy).

    build\\venv\\Scripts\\python packaging\\build_portable.py

Output: build\\PDFDrop-Windows.zip containing
    Install PDFDrop.cmd     copies the app to %LOCALAPPDATA%\\Programs\\PDFDrop and starts it
    Uninstall PDFDrop.cmd   removes the right-click menu, shortcuts and the program folder
    READ ME FIRST.txt
    PDFDrop\\               self-contained app (bundled python.org Python, PSF-signed pythonw.exe)
"""
import compileall
import os
import shutil
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_msix as bm  # noqa: E402

ROOT = bm.ROOT
STAGE = os.path.join(os.path.expanduser("~"), "PDFDrop-portable")
OUT = os.path.join(ROOT, "build", "PDFDrop-Windows.zip")
VERSION = "1.0.0"

INSTALL_CMD = r"""@echo off
setlocal
title Install PDFDrop
set "DEST=%LOCALAPPDATA%\Programs\PDFDrop"
echo.
echo  Installing PDFDrop to %DEST% ...
robocopy "%~dp0PDFDrop" "%DEST%" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo  Copy failed. Close PDFDrop and run this again.
  pause
  exit /b 1
)
start "" "%DEST%\python\pythonw.exe" "%DEST%\app\main.py"
echo.
echo  Done! PDFDrop is on your Desktop and in the Start menu.
echo  Tip: right-click any PDF and choose "Edit with PDFDrop".
echo.
timeout /t 8 >nul
"""

UNINSTALL_CMD = r"""@echo off
setlocal
title Uninstall PDFDrop
set "DEST=%LOCALAPPDATA%\Programs\PDFDrop"
taskkill /f /fi "WINDOWTITLE eq PDFDrop" >nul 2>&1
if exist "%DEST%\python\python.exe" "%DEST%\python\python.exe" "%DEST%\app\main.py" --uninstall --quiet
timeout /t 1 >nul 2>&1
rd /s /q "%DEST%" 2>nul
rd /s /q "%APPDATA%\PDFDrop" 2>nul
echo PDFDrop has been removed. Your PDFs were not touched.
timeout /t 6 >nul
"""

README = f"""PDFDrop {VERSION} for Windows 10/11
===================================

Edit, merge, split, compress, sign and protect PDFs - all offline.
Your files never leave your PC.

INSTALL
1. Right-click the zip > Extract All... (don't run it from inside the zip).
2. Double-click "Install PDFDrop.cmd".
   If Windows says "Windows protected your PC", click "More info" > "Run anyway".
   (PDFDrop is a small indie app that isn't code-signed yet.)
3. PDFDrop opens and is added to your Desktop and Start menu.

USE
- Pick a tool (Merge, Split, Compress, Watermark...) or open a PDF to edit it.
- Or right-click a PDF in File Explorer > "Edit with PDFDrop"
  (on Windows 11: Show more options first).
- Tools never change your original file; they save a new one next to it.

SMART APP CONTROL
If your PC has Smart App Control turned on and blocks this download,
get PDFDrop from the Microsoft Store instead (search "PDFDrop").

UNINSTALL
Double-click "Uninstall PDFDrop.cmd".

Licence: GNU AGPL v3 (see PDFDrop\\app\\LICENSE and THIRD_PARTY_NOTICES.txt)
Source code and support: https://github.com/tiger1247/pdfdrop
"""

def clear(path):
    for _ in range(5):
        if not os.path.exists(path):
            return
        try:
            shutil.rmtree(path)
        except OSError:
            time.sleep(2)
    os.rename(path, f"{path}-old-{int(time.time())}")


def main():
    clear(STAGE)
    app_root = os.path.join(STAGE, "PDFDrop")
    os.makedirs(app_root)
    print("Bundling Python runtimeâ€¦")
    bm.copy_python(os.path.join(app_root, "python"))
    bm.copy_app(os.path.join(app_root, "app"))
    with open(os.path.join(app_root, "app", "DIRECT_EDITION"), "w") as fh:
        fh.write(VERSION)
    compileall.compile_dir(app_root, quiet=1, workers=0)
    for name, text in (("Install PDFDrop.cmd", INSTALL_CMD), ("Uninstall PDFDrop.cmd", UNINSTALL_CMD),
                       ("READ ME FIRST.txt", README)):
        with open(os.path.join(STAGE, name), "w", encoding="ascii", newline="\r\n") as fh:
            fh.write(text)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _, files in os.walk(STAGE):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, STAGE))
    print(f"Wrote {OUT} ({os.path.getsize(OUT) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()

