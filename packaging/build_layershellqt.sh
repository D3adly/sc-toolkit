#!/usr/bin/env bash
# Builds LayerShellQt (KDE's Qt layer-shell integration) against the exact Qt
# that ships inside our PySide6 wheel, so the Linux build can bundle it and
# use the layer-shell overlay on KDE Wayland (GitHub #20). A distro's
# LayerShellQt is built against the distro's Qt and won't load into ours.
#
# The wheel has no headers, so the matching Qt SDK comes from aqtinstall
# (the same official Qt binaries the wheel is made from).
# Output (laid out like PySide6/Qt, whose lib/ and plugins/ they go into):
#   build/layershellqt/lib/libLayerShellQtInterface.so.6
#   build/layershellqt/plugins/wayland-shell-integration/liblayer-shell.so
#
# Needs: a C++ compiler, pkg-config, git and the dev packages
#   wayland-protocols libxkbcommon-dev libgl-dev libegl-dev libffi-dev libexpat1-dev
# (see .github/workflows/build.yml), plus the app's requirements installed.
# cmake, meson and ninja come from pip (Ubuntu 22.04's are too old), and
# libwayland is built from source: Qt 6.11's private headers need >= 1.24.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
QT_VERSION="$("$PYTHON" -c 'import PySide6.QtCore as q; print(q.qVersion())')"
LAYERSHELLQT_TAG="v6.7.5"
WAYLAND_TAG="1.24.0"
ECM_TAG="v6.26.0"            # LayerShellQt's KF6_MIN_VERSION
WORK="build/layershellqt-work"
OUT="build/layershellqt"

mkdir -p "$WORK"
WORK="$(cd "$WORK" && pwd)"

"$PYTHON" -m pip install --quiet aqtinstall cmake meson ninja patchelf
PATH="$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_path("scripts"))'):$PATH"
if [ ! -d "$WORK/qt/$QT_VERSION" ]; then
    (cd "$WORK" && "$PYTHON" -m aqt install-qt linux desktop "$QT_VERSION" linux_gcc_64 -O "$WORK/qt")
fi
QT_PREFIX="$WORK/qt/$QT_VERSION/gcc_64"

fetch() {   # fetch <git url> <tag> <dir>
    [ -d "$3" ] || git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$2" "$1" "$3"
}
fetch https://gitlab.freedesktop.org/wayland/wayland.git "$WAYLAND_TAG" "$WORK/wayland-src"
fetch https://invent.kde.org/frameworks/extra-cmake-modules.git "$ECM_TAG" "$WORK/ecm-src"
fetch https://invent.kde.org/plasma/layer-shell-qt.git "$LAYERSHELLQT_TAG" "$WORK/lsq-src"

# Headers and wayland-scanner only: at runtime the user's own libwayland is used.
if [ ! -d "$WORK/wayland" ]; then
    meson setup "$WORK/wayland-build" "$WORK/wayland-src" --prefix="$WORK/wayland" --libdir=lib \
        -Ddocumentation=false -Dtests=false -Ddtd_validation=false >/dev/null
    meson install -C "$WORK/wayland-build" >/dev/null
fi
export PKG_CONFIG_PATH="$WORK/wayland/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
export PATH="$WORK/wayland/bin:$PATH"

cmake -S "$WORK/ecm-src" -B "$WORK/ecm-build" -G Ninja -DBUILD_TESTING=OFF -DBUILD_DOC=OFF \
    -DCMAKE_INSTALL_PREFIX="$WORK/ecm" >/dev/null
cmake --build "$WORK/ecm-build" --target install >/dev/null

cmake -S "$WORK/lsq-src" -B "$WORK/lsq-build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    -DCMAKE_PREFIX_PATH="$QT_PREFIX;$WORK/ecm"
# Just the library and the Qt plugin (the test program and QML module aren't needed).
cmake --build "$WORK/lsq-build" --target LayerShellQtInterface layer-shell

rm -rf "$OUT"
mkdir -p "$OUT/lib" "$OUT/plugins/wayland-shell-integration"
cp -a "$WORK"/lsq-build/bin/libLayerShellQtInterface.so.6* "$OUT/lib/"
cp "$WORK/lsq-build/bin/liblayer-shell.so" "$OUT/plugins/wayland-shell-integration/"
# Find Qt (and each other) next to the bundled Qt, not in this build tree.
patchelf --set-rpath '$ORIGIN' "$OUT/lib/libLayerShellQtInterface.so.6"
patchelf --set-rpath '$ORIGIN/../../lib' "$OUT/plugins/wayland-shell-integration/liblayer-shell.so"
echo "Built LayerShellQt $LAYERSHELLQT_TAG for Qt $QT_VERSION in $OUT"
