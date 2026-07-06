$ErrorActionPreference = "Stop"

Write-Host "Installing PyInstaller..."
python -m pip install pyinstaller

Write-Host "Building executable..."
# We use --add-data to bundle the static directory inside the executable
# We use --noconsole to hide the terminal window when the user double clicks the exe
# We use --icon if we had an icon, but we don't right now
python -m PyInstaller --noconfirm --onefile --windowed --add-data "static;static" --name "MCQ_Test_Maker" server.py

Write-Host ""
Write-Host "========================================"
Write-Host "Build complete!"
Write-Host "The executable is located at: .\dist\MCQ_Test_Maker.exe"
Write-Host "IMPORTANT: Make sure to copy the 'data' folder to the same directory as the executable if you want to keep your previous uploads and database!"
Write-Host "========================================"
