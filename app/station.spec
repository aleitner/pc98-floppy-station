# PyInstaller build of the Floppy Station: one file per system.
#   pyinstaller station.spec
# The result lands in dist/. The Greaseweazle package carries its disk definitions as data
# files and finds its serial-port helpers by name, so both are collected explicitly.
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
hidden = collect_submodules("greaseweazle") + collect_submodules("serial")
datas = collect_data_files("greaseweazle") + [("static", "static"), ("icon.png", ".")]

a = Analysis(
    ["station.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon = {"win32": "icon.ico", "darwin": "icon.icns"}.get(sys.platform, "icon.png")

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="pc98-floppy-station",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=sys.platform.startswith("linux"),   # a terminal on Linux shows the address; none elsewhere
    icon=icon,
)

if sys.platform == "darwin":
    app = BUNDLE(exe, name="PC-98 Floppy Station.app", icon="icon.icns",
                 bundle_identifier="net.pc98floppystation.app",
                 info_plist={"NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0",
                             "CFBundleShortVersionString": "0.2.0", "CFBundleVersion": "0.2.0"})
