#!/usr/bin/env bash
# Candidate fix for the macOS package (2026-09-24 report, blocking failure 9).
#
# ExecutePipeline, and any other tool in bin/ that opens a Qt application, aborts with
# 'Could not find the Qt platform plugin "cocoa" in ""': the package ships
# lib/plugins/platforms/libqcocoa.dylib, but only the app bundles get a qt.conf that points at
# it. This writes the bin/qt.conf that cmake/package_mac_productbuild.cmake has commented out
# ("Plugins = ../${INSTALL_PLUGIN_DIR}", with INSTALL_PLUGIN_DIR = lib/plugins). The Windows
# installer already installs the same file (src/openms_gui/CMakeLists.txt).
#
# Usage: fixes/macos-bin-qt-conf.sh <installation root>
set -euo pipefail
root="$1"
if [ ! -f "$root/lib/plugins/platforms/libqcocoa.dylib" ]; then
  echo "no cocoa platform plugin under $root/lib/plugins; this fix does not apply" >&2
  exit 1
fi
if [ -e "$root/bin/qt.conf" ]; then
  echo "$root/bin/qt.conf exists already; the package may carry the fix" >&2
  cat "$root/bin/qt.conf" >&2
  exit 1
fi
write=(tee "$root/bin/qt.conf")
[ -w "$root/bin" ] || write=(sudo tee "$root/bin/qt.conf")
printf '[Paths]\nPlugins = ../lib/plugins\n' | "${write[@]}" >/dev/null
echo "wrote $root/bin/qt.conf:"
cat "$root/bin/qt.conf"
