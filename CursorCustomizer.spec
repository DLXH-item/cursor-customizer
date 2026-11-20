# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules

_EXCLUDES = [
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickControls2',
    'PySide6.QtQuickWidgets', 'PySide6.QtDesigner', 'PySide6.QtHelp',
    'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtDBus', 'PySide6.QtUiTools',
    'PySide6.QtNetwork', 'PySide6.QtLottie', 'PySide6.Qt3D',
    'PySide6.QtMultimedia', 'PySide6.QtCharts', 'PySide6.QtPdf',
    # 视频解码栈不打入安装包（体积过大），运行时按需检测
    'cv2', 'numpy', 'imageio', 'imageio_ffmpeg', 'scipy',
]

_BAD_PARTS = ('opengl32sw', '_avif', 'avif', 'libwebpdemux', 'qt6quick',
              'qt6network', 'libcrypto', 'libssl', 'libssl-3')

def _keep(entry):
    name = entry[0].replace('\\', '/').lower()
    return not any(part in name for part in _BAD_PARTS)


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('app.ico', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_EXCLUDES,
    noarchive=False,
    optimize=0,
)

a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CursorCustomizer',
    icon='app.ico',
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
