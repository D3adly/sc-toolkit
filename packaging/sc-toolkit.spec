# PyInstaller spec for SC-Toolkit — one spec for both platforms.
#   Windows: a single-file SC-Toolkit-windows.exe
#   Linux:   a SC-Toolkit/ folder, wrapped into an AppImage by build_linux.sh
# Build from the repository root:  pyinstaller packaging/sc-toolkit.spec
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
WINDOWS = sys.platform.startswith("win")

# Only the assets the app loads at runtime (not the icon sources/scripts).
assets = ROOT / "assets"
datas = [
    (str(assets / "background.jpg"), "assets"),
    (str(assets / "app_icon.png"), "assets"),
    (str(assets / "icons" / "*.png"), "assets/icons"),
]

# The app only uses QtCore, QtGui and QtWidgets; keep the rest of Qt out.
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

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    datas=datas,
    excludes=excludes,
    # Tool views are imported lazily (and by name in --smoke-test).
    hiddenimports=[
        "app.ui.bindings_view", "app.ui.mining_view", "app.ui.salvage_view",
        "app.ui.settings_view",
    ],
    noarchive=False,
)
# Qt plugins drag in libraries a plain-widgets app never uses (Quick/QML,
# the virtual keyboard, PDF, GTK 3 and its whole stack, EGLFS/VNC/framebuffer
# backends, TLS for QtNetwork). Dropping them roughly halves the bundle.
import re

_DROP = re.compile(
    r"(plugins[/\\](egldeviceintegrations|generic|networkinformation|tls|iconengines)[/\\])"
    r"|(q(gtk3|tvirtualkeyboard\w*|pdf|tiff|webp|gif|icns|tga|wbmp|svg|eglfs\w*|linuxfb|minimalegl|vnc"
    r"|vkkhrdisplay|minimal|direct2d)\.(so|dll))"
    r"|(qt6(pdf|quick|qml|virtualkeyboard|eglfs|svg)\w*\.(so|dll))"
    r"|(^|[/\\])lib(gtk-3|gdk-3|atk|atspi|cairo|pango|glycin|gdk_pixbuf|tinysparql|cloudproviders"
    r"|json-glib|epoxy|thai|datrie|lcms2|seccomp)[\w.-]*\.so"
    r"|opengl32sw\.dll"
    r"|[/\\]translations[/\\]",
    re.IGNORECASE,
)
a.binaries = [b for b in a.binaries if not _DROP.search(b[0])]
a.datas = [d for d in a.datas if not _DROP.search(d[0])]

pyz = PYZ(a.pure)

if WINDOWS:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="SC-Toolkit-windows",
        icon=str(assets / "app_icon.ico"),
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
