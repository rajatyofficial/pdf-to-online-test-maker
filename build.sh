#!/bin/bash
set -e

echo "Installing PyInstaller..."
python3 -m pip install pyinstaller

echo "Building executable..."
# We use --add-data with a colon ":" on Mac/Linux instead of semicolon ";"
python3 -m PyInstaller --noconfirm --onefile --windowed --add-data "static:static" --name "MCQ_Test_Maker" server.py

echo ""
echo "========================================"
echo "Build complete!"
echo "The executable is located at: ./dist/MCQ_Test_Maker"
echo "IMPORTANT: Make sure to copy the 'data' folder to the same directory as the executable if you want to keep your previous uploads and database!"
echo "========================================"
