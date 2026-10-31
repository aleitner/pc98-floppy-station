# PyInstaller build of the Floppy Station: one file per system.
#   pyinstaller station.spec
# The result lands in dist/. The Greaseweazle package carries its disk definitions as data
# files and finds its serial-port helpers by name, so both are collected explicitly.
import re
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

version = re.search(r'^VERSION = "([^"]+)"', open("station.py", encoding="utf-8").read(), re.M).group(1)
hidden = collect_submodules("greaseweazle") + collect_submodules("serial")
datas = collect_data_files("greaseweazle") + [("static", "static"), ("icon.png", ".")]

a = Analysis(["station.py"], pathex=["."], datas=datas, hiddenimports=hidden)
pyz = PYZ(a.pure)

icon = {"win32": "icon.ico", "darwin": "icon.icns"}.get(sys.platform, "icon.png")

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="pc98-floppy-station",
    console=sys.platform.startswith("linux"),   # on Linux the address prints when started from a terminal
    icon=icon,
)

if sys.platform == "darwin":
    app = BUNDLE(exe, name="PC-98 Floppy Station.app", icon="icon.icns",
                 bundle_identifier="net.pc98floppystation.app",
                 info_plist={"NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0",
                             "CFBundleShortVersionString": version, "CFBundleVersion": version})
