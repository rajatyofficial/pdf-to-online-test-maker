# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[],
    datas=[('static', 'static')],
    hiddenimports=['pdfplumber', 'pdfplumber.utils', 'pdfplumber.page', 'pdfplumber.table', 'pdfplumber.display', 'pdfminer', 'pdfminer.high_level', 'pdfminer.layout', 'pdfminer.pdfparser', 'pdfminer.pdfdocument', 'pdfminer.pdfpage', 'pdfminer.pdfinterp', 'pdfminer.converter', 'pdfminer.cmapdb', 'pdfminer.psparser', 'pypdf', 'PIL', 'PIL.Image'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MCQ_Test_Maker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
