# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Cerebro Companion.

Build with: pyinstaller cerebro_companion.spec
"""

import os
from pathlib import Path

block_cipher = None

# Get the project directory
project_dir = Path(SPECPATH)

# Data files to include
datas = [
    # Templates and static files
    (str(project_dir / 'templates'), 'templates'),
    (str(project_dir / 'static'), 'static'),
    # .env.example for reference
    (str(project_dir / '.env.example'), '.'),
]

# Check for bundled OCR binaries
tesseract_dir = project_dir / 'third_party' / 'tesseract'
poppler_dir = project_dir / 'third_party' / 'poppler'

if tesseract_dir.exists():
    datas.append((str(tesseract_dir), 'tesseract'))
    print(f"[SPEC] Bundling Tesseract from {tesseract_dir}")

if poppler_dir.exists():
    datas.append((str(poppler_dir), 'poppler'))
    print(f"[SPEC] Bundling Poppler from {poppler_dir}")

# Hidden imports that PyInstaller might miss
hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'httptools',
    'websockets',
    'watchfiles',
    'email_validator',
    'multipart',
    'python_multipart',
    # HTTP client
    'httpx',
    'httpx._transports',
    'httpx._transports.default',
    'httpcore',
    'h11',
    'h2',
    'hpack',
    'hyperframe',
    'aiofiles',
    # Crypto
    'cryptography',
    'nacl',
    'argon2',
    'argon2.low_level',
    'argon2._ffi',
    # FastAPI/Starlette
    'starlette.responses',
    'starlette.routing',
    'starlette.middleware',
    'starlette.middleware.cors',
    'anyio',
    'anyio._backends',
    'anyio._backends._asyncio',
    # PIL for image processing
    'PIL',
    'PIL.Image',
    # cerebro_care and dependencies
    'cerebro_care',
    'dateutil',
    'dateutil.parser',
]

# Runtime hooks to fix numpy issues
runtime_hooks = []

a = Analysis(
    ['main.py'],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(project_dir / 'hooks')],
    hooksconfig={},
    runtime_hooks=[str(project_dir / 'hooks' / 'rthook_numpy.py')],
    excludes=[
        'tkinter',
        'matplotlib.tests',
        'numpy.testing',
        'scipy',
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
    [],
    exclude_binaries=True,
    name='CerebroCompanion',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Keep console for debugging output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon path here if you have one
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CerebroCompanion',
)
