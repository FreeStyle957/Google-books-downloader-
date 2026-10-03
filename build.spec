# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: builds a single self-contained .exe (no console)."""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
for _pkg in (
    "uvicorn",
    "uvicorn.lifespan",
    "uvicorn.loops",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.websockets",
    "starlette",
    "anyio",
    "pydantic",
    "pydantic.deprecated",
    "fastapi",
    "requests",
    "websocket",
    "PIL",
    # core._driver_classes imports these lazily, so PyInstaller cannot see them.
    "selenium.webdriver.edge.options",
    "selenium.webdriver.edge.webdriver",
    "selenium.webdriver.edge.service",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.chrome.webdriver",
    "selenium.webdriver.chrome.service",
    "selenium.webdriver.common.selenium_manager",
):
    hiddenimports += collect_submodules(_pkg)

# Selenium Manager is the binary that downloads the matching Edge/Chrome driver
# at runtime. Selenium resolves it relative to its own package directory, so it
# must land at selenium/webdriver/common/windows/ inside the bundle.
import os
import selenium

_selenium_root = os.path.dirname(selenium.__file__)
binaries = [
    (
        os.path.join(_selenium_root, "webdriver", "common", "windows", "selenium-manager.exe"),
        os.path.join("selenium", "webdriver", "common", "windows"),
    )
]

datas = [("static", "static"), ("README.md", "."), ("LICENSE", ".")]

block_cipher = None

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pytest", "IPython"],
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
    name="GoogleBooksDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no black console window on double-click
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
