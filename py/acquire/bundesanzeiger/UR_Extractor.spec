# -*- mode: python ; coding: utf-8 -*-
# ============================================================================
# UR_Extractor.spec — PyInstaller spec (onefile, portable)
# ============================================================================

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_all

# ── Playwright Node.js bridge ─────────────────────────────────────────────────
import playwright as _pw_pkg
PLAYWRIGHT_DRIVER = str(Path(_pw_pkg.__file__).parent / "driver")

# ── Hidden imports (must be defined before collect_all calls below) ───────────
hidden = [
    "pdfminer", "pdfminer.high_level", "pdfminer.layout", "pdfminer.utils",
    "pdfminer.pdfparser", "pdfminer.pdfdocument", "pdfminer.pdfpage",
    "pdfminer.pdfinterp", "pdfminer.pdfdevice", "pdfminer.pdffont",
    "pdfminer.pdfcolor", "pdfminer.image", "pdfminer.converter",
    "pdfminer.cmapdb",
    "openpyxl", "openpyxl.styles", "openpyxl.utils", "openpyxl.writer.excel",
    "PIL", "PIL._imaging", "PIL.Image",
    "tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox",
]

# ── Data files ────────────────────────────────────────────────────────────────
datas  = []
datas += collect_data_files("customtkinter")
datas += collect_data_files("pdfplumber")
datas += [(PLAYWRIGHT_DRIVER, "playwright/driver")]

# ── numpy: collect everything (native DLLs, data, hidden imports) ─────────────
# pandas depends on numpy; its native DLLs are not found by static analysis.
np_datas, np_binaries, np_hidden = collect_all("numpy")
datas  += np_datas
hidden += np_hidden

block_cipher = None

a = Analysis(
    ["ur_gui.py"],
    pathex=[],
    binaries=np_binaries,       # numpy native DLLs
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "scipy", "IPython", "notebook",
        "pytest", "sphinx", "docutils",
    ],
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
    name="UR_Financial_Extractor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    icon="extractor.ico",
    runtime_tmpdir=None,
)
