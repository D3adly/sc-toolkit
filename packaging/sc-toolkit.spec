# PyInstaller spec for SC-Toolkit — one spec for both platforms.
#   Windows: a single-file SC-Toolkit-windows.exe
#   Linux:   a SC-Toolkit/ folder, wrapped into an AppImage by build_linux.sh
# Build from the repository root:  pyinstaller packaging/sc-toolkit.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

ROOT = Path(SPECPATH).parent
WINDOWS = sys.platform.startswith("win")

# Only the assets the app loads at runtime (not the icon sources/scripts).
assets = ROOT / "assets"
datas = [
    (str(assets / "background.jpg"), "assets"),
    (str(assets / "app_icon.png"), "assets"),
    (str(assets / "icons" / "*.png"), "assets/icons"),
    (str(assets / "icons" / "glyphs" / "*.png"), "assets/icons/glyphs"),
    (str(assets / "fonts" / "*"), "assets/fonts"),        # Inter, Rajdhani (OFL), loaded by app.theme
    (str(ROOT / "CHANGELOG.md"), "."),     # What's new (app.changelog)
    (str(assets / "ships.json"), "assets"),  # ship catalogue snapshot (app.ships)
    (str(assets / "refining.json"), "assets"),  # refining table (app.refining)
]

# The app only uses QtCore, QtGui, QtWidgets and QtSvg (loadout icons); keep the rest of Qt out.
UNUSED_QT = """
Qt3DAnimation Qt3DCore Qt3DExtras Qt3DInput Qt3DLogic Qt3DRender QtBluetooth
QtCanvasPainter QtCharts QtConcurrent QtDataVisualization QtDesigner QtGraphs
QtGraphsWidgets QtHelp QtHttpServer QtLocation QtMultimedia QtMultimediaWidgets
QtNetworkAuth QtNfc QtOpenGL QtOpenGLWidgets QtPdf QtPdfWidgets QtPositioning
QtPrintSupport QtQml QtQuick QtQuick3D QtQuickControls2 QtQuickTest QtQuickWidgets
QtRemoteObjects QtScxml QtSensors QtSerialBus QtSerialPort QtSpatialAudio QtSql
QtStateMachine QtSvgWidgets QtTest QtTextToSpeech QtUiTools QtWebChannel
QtWebEngineCore QtWebEngineQuick QtWebEngineWidgets QtWebSockets QtWebView QtXml
""".split()
excludes = [f"PySide6.{m}" for m in UNUSED_QT] + ["tkinter", "unittest", "pydoc"]

binaries = collect_dynamic_libs("sdl2dll")   # SDL2 shipped inside pysdl2-dll (joystick input)
# LayerShellQt built for our PySide6's Qt (packaging/build_layershellqt.sh):
# the layer-shell overlay on KDE Wayland (see app.overlay_host).
layershellqt = ROOT / "build" / "layershellqt"
if not WINDOWS and (layershellqt / "lib").is_dir():
    binaries += [
        (str(layershellqt / "lib" / "libLayerShellQtInterface.so.6"), "PySide6/Qt/lib"),
        (str(layershellqt / "plugins" / "wayland-shell-integration" / "liblayer-shell.so"),
         "PySide6/Qt/plugins/wayland-shell-integration"),
    ]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    datas=datas,
    binaries=binaries,
    excludes=excludes,
    # Tool views and the overlay are imported lazily (and by name in --smoke-test).
    hiddenimports=[
        "app.ui.bindings_view", "app.ui.maps_view", "app.ui.mining_view", "app.ui.salvage_view",
        "app.ui.settings_view", "app.ui.overlay", "app.ui.overlay_panels", "app.ui.layer_overlay",
        "app.ui.whats_new_view", "app.ui.hangar_view",
        "app.hotkeys",
        "jeepney", "jeepney.io.blocking", "jeepney.bus_messages",
        # Sign-in storage (app.portal): keyring picks its OS backend at runtime.
        "keyring.backends.Windows", "keyring.backends.SecretService", "keyring.backends.fail",
        "sdl2", "sdl2dll",
    ],
    noarchive=False,
)
# Qt plugins drag in libraries a plain-widgets app never uses (Quick/QML,
# the virtual keyboard, PDF, GTK 3 and its whole stack, EGLFS/VNC/framebuffer
# backends, TLS for QtNetwork). Dropping them roughly halves the bundle.
# (qwebp stays: ship pictures from the Star Citizen Wiki are WebP.)
import re

_DROP = re.compile(
    r"(plugins[/\\](egldeviceintegrations|generic|networkinformation|tls|iconengines)[/\\])"
    r"|(q(gtk3|tvirtualkeyboard\w*|pdf|tiff|gif|icns|tga|wbmp|svg|eglfs\w*|linuxfb|minimalegl|vnc"
    r"|vkkhrdisplay|minimal|direct2d)\.(so|dll))"
    r"|(qt6(pdf|quick|qml|virtualkeyboard|eglfs|svgwidgets)\w*\.(so|dll))"
    r"|(^|[/\\])lib(gtk-3|gdk-3|atk|atspi|cairo|pango|glycin|gdk_pixbuf|tinysparql|cloudproviders"
    r"|json-glib|epoxy|thai|datrie|lcms2|seccomp)[\w.-]*\.so"
    r"|SDL2_(gfx|image|mixer|ttf)[\w.-]*\.(so|dll)"  # only SDL2 core is used
    r"|opengl32sw\.dll"
    r"|[/\\]translations[/\\]",
    re.IGNORECASE,
)
a.binaries = [b for b in a.binaries if not _DROP.search(b[0])]
a.datas = [d for d in a.datas if not _DROP.search(d[0])]

pyz = PYZ(a.pure)


def windows_version_info():
    """The exe's Properties → Details (product, version, description). An exe without them looks
    more like malware to antivirus heuristics (Defender's "!ml" detections)."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo)

    version = re.search(r'__version__ = "([^"]+)"', (ROOT / "app" / "__init__.py").read_text()).group(1)
    numbers = tuple(int(n) for n in re.findall(r"\d+", version)[:4])
    numbers += (0,) * (4 - len(numbers))
    strings = {
        "CompanyName": "SC-Toolbox",
        "FileDescription": "SC-Toolbox: Star Citizen companion launcher",
        "FileVersion": version,
        "InternalName": "SC-Toolbox",
        "LegalCopyright": "GPL-3.0, github.com/D3adly/sc-toolkit",
        "OriginalFilename": "SC-Toolkit-windows.exe",
        "ProductName": "SC-Toolbox",
        "ProductVersion": version,
    }
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo([StringTable("040904B0", [StringStruct(k, v) for k, v in strings.items()])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),  # US English, Unicode
        ],
    )


if WINDOWS:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="SC-Toolkit-windows",
        icon=str(assets / "app_icon.ico"),
        version=windows_version_info(),
        console=False,
        upx=False,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="SC-Toolkit",
        console=False,
        upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="SC-Toolkit", upx=False)
