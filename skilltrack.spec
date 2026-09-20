# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 빌드 스펙. Windows 에서:  pyinstaller skilltrack.spec
# 결과: dist/mabiaura/ (mabiaura.exe + _internal/). 폴더째 zip 해서 배포.
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["win/run.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("assets/glyphs.json", "assets"),
        ("assets/boss_icons", "assets/boss_icons"),
        ("assets/sounds", "assets/sounds"),
        ("assets/fonts", "assets/fonts"),
    ],
    hiddenimports=collect_submodules("dxcam") + ["win32gui", "win32con", "win32api"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tests", "pytest", "matplotlib", "tkinter",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtMultimedia", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="mabiaura",
    console=False,           # 콘솔 없음. 로그는 exe 옆 skilltrack.log (win/run.py)
    icon=None,               # assets/icon.ico 만들면 여기에
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="mabiaura")
