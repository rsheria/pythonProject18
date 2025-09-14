# -*- mode: python ; coding: utf-8 -*-

# PyInstaller spec file for ForumBot - optimized for minimal size

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Define the main script
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Include any config files or data files your app needs
    ] + (
        [('.env', '.')] if os.path.exists('.env') else []
    ) + (
        [('config', 'config')] if os.path.exists('config') else []
    ) + (
        [('templates', 'templates')] if os.path.exists('templates') else []
    ) + (
        [('utils', 'utils')] if os.path.exists('utils') else []
    ),
    hiddenimports=[
        # Core app modules
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'requests',
        'selenium',
        'dotenv',
        'configobj',
        'logging',
        'pathlib',
        'json',
        'sqlite3',
        'threading',
        'queue',
        'subprocess',
        'shutil',
        'zipfile',
        'time',
        'datetime',
        'urllib3',
        'certifi',
        # Add other critical imports your app uses
        'mega',
        'lxml',
        'cryptography',
        'myjdapi',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unused modules to reduce size
        'tkinter',
        'matplotlib',
        'scipy',
        'jupyter',
        'notebook',
        'IPython',
        'pywin32_system32',
        'setuptools',
        'distutils',
        'unittest',
        'doctest',
        'pdb',
        'bdb',
        'pydoc',
        'email',
        'xml',
        'xmlrpc',
        'html',
        'http.server',
        'wsgiref',
        'multiprocessing',
        'concurrent.futures',
        'asyncio',
        'test',
        'tests',
        '_pytest',
        'pytest',
        'nose',
        # Exclude heavy packages if not strictly needed
        'pandas',
        'openpyxl',
        'numpy',
        'cv2',
        'PIL',
        'pillow',
        'scipy',
        'matplotlib',
        'seaborn',
        'sklearn',
        'tensorflow',
        'torch',
        'keras',
        'plotly',
        'dash',
        'bokeh',
        'altair',
        'statsmodels',
        'networkx',
        'nibabel',
        'nipype',
        'prov',
        'rdflib',
        'tabula',
        'pdf2docx',
        'pdfminer',
        'PyMuPDF',
        'python-docx',
        'python-pptx',
        'xlsxwriter',
        'fonttools',
        'git-filter-repo',
        # Qt modules not needed
        'PyQt5.QtNetwork',
        'PyQt5.QtOpenGL',
        'PyQt5.QtPrintSupport',
        'PyQt5.QtSql',
        'PyQt5.QtSvg',
        'PyQt5.QtTest',
        'PyQt5.QtWebKit',
        'PyQt5.QtWebKitWidgets',
        'PyQt5.QtXml',
        'PyQt5.QtXmlPatterns',
        'PyQt5.QtDesigner',
        'PyQt5.QtHelp',
        'PyQt5.QtMultimedia',
        'PyQt5.QtMultimediaWidgets',
        'PyQt5.QtPositioning',
        'PyQt5.QtQml',
        'PyQt5.QtQuick',
        'PyQt5.QtQuickWidgets',
        'PyQt5.QtSensors',
        'PyQt5.QtSerialPort',
        'PyQt5.QtWebChannel',
        'PyQt5.QtWebEngine',
        'PyQt5.QtWebEngineCore',
        'PyQt5.QtWebEngineWidgets',
        'PyQt5.QtWinExtras',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# No need to filter datas now since we properly constructed the list

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ForumBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # Enable UPX compression for smaller size
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to False for windowed app
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add path to .ico file if you have one
    version_file=None,
)