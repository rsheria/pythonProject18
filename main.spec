# -*- mode: python ; coding: utf-8 -*-
import certifi
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyQt5.QtCore import QLibraryInfo

block_cipher = None

# Collect resource files
_datas = collect_data_files('gui', includes=['*.qss', '*.ico', '*.json'])
_datas += collect_data_files('config', includes=['*.json'])
_datas += [(certifi.where(), 'certifi')]

# Bundle Qt plugins
qt_plugins = QLibraryInfo.location(QLibraryInfo.PluginsPath)
_datas.append((qt_plugins, 'PyQt5/Qt/plugins'))

# Hidden imports for dynamic modules
_hiddenimports = collect_submodules('PyQt5') + collect_submodules('selenium')

# Optional binaries such as chromedriver
_binaries = []
_chromedriver = Path('drivers') / 'chromedriver'
if _chromedriver.exists():
    _binaries.append((str(_chromedriver), '.'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='main'
)