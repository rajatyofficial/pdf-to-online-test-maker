$ErrorActionPreference = "Stop"

Write-Host "Installing project dependencies and PyInstaller..."
python -m pip install pyinstaller pdfplumber "pypdf>=6" "Pillow>=12"

Write-Host ""
Write-Host "Building single-file executable..."
# --onefile   : produces a single MCQ_Test_Maker.exe
# --windowed  : hides the console window on double-click
# --add-data  : bundles the static/ web assets inside the exe
# --hidden-import : explicitly includes packages PyInstaller can't auto-detect
python -m PyInstaller --noconfirm --onefile --windowed `
    --add-data "static;static" `
    --hidden-import pdfplumber `
    --hidden-import pdfplumber.utils `
    --hidden-import pdfplumber.page `
    --hidden-import pdfplumber.table `
    --hidden-import pdfplumber.display `
    --hidden-import pdfminer `
    --hidden-import pdfminer.high_level `
    --hidden-import pdfminer.layout `
    --hidden-import pdfminer.pdfparser `
    --hidden-import pdfminer.pdfdocument `
    --hidden-import pdfminer.pdfpage `
    --hidden-import pdfminer.pdfinterp `
    --hidden-import pdfminer.converter `
    --hidden-import pdfminer.cmapdb `
    --hidden-import pdfminer.psparser `
    --hidden-import pypdf `
    --hidden-import PIL `
    --hidden-import PIL.Image `
    --name "MCQ_Test_Maker" `
    server.py

Write-Host ""
Write-Host "========================================"
Write-Host "Build complete!"
Write-Host "The executable is located at: .\dist\MCQ_Test_Maker.exe"
Write-Host ""
Write-Host "To use it:"
Write-Host "  1. Double-click MCQ_Test_Maker.exe"
Write-Host "  2. Your browser will open to http://127.0.0.1:8765"
Write-Host "  3. A 'data' folder will be created next to the exe for your database."
Write-Host "========================================"
