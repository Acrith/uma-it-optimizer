# PyInstaller spec: build a single-file umaladder-extract.exe
#
# Run:   pyinstaller build_exe.spec
# Requires:  pip install pyinstaller  (Windows Python)
# Result:    dist/umaladder-extract.exe   (~15 MB, self-contained)

# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['dump_it_run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('vendor/il2cpp_bridge.js', 'vendor'),  # bundle bridge JS
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='umaladder-extract',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # keep console window (users see progress + errors)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
