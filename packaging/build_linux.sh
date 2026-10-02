#!/usr/bin/env bash
# Builds dist/SC-Toolkit-linux.AppImage (run from anywhere; needs pyinstaller).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
TOOLS="build/tools"
APPDIR="build/SC-Toolkit.AppDir"

# LayerShellQt for the KDE Wayland overlay; without it the build only has the X11 overlay.
if [ ! -f build/layershellqt/lib/libLayerShellQtInterface.so.6 ]; then
    if [ -n "${CI:-}" ]; then
        echo "build/layershellqt is missing: run packaging/build_layershellqt.sh first" >&2
        exit 1
    fi
    echo "WARNING: no build/layershellqt (packaging/build_layershellqt.sh): the overlay will be X11-only" >&2
fi

pyinstaller --noconfirm --clean --distpath build/pyinstaller --workpath build/work packaging/sc-toolkit.spec

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -a build/pyinstaller/SC-Toolkit/. "$APPDIR/usr/bin/"
cp assets/app_icon.png "$APPDIR/sc-toolkit.png"
cp packaging/sc-toolkit.desktop "$APPDIR/sc-toolkit.desktop"
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/SC-Toolkit" "$@"
RUN
chmod +x "$APPDIR/AppRun"

mkdir -p "$TOOLS" dist
if [ ! -x "$TOOLS/appimagetool" ]; then
    curl -fsSL "$APPIMAGETOOL_URL" -o "$TOOLS/appimagetool"
    chmod +x "$TOOLS/appimagetool"
fi
# Extract-and-run: works without FUSE (CI containers, immutable distros).
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$TOOLS/appimagetool" --no-appstream \
    "$APPDIR" dist/SC-Toolkit-linux.AppImage
echo "Built dist/SC-Toolkit-linux.AppImage"
