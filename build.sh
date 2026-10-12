#!/usr/bin/env bash
# Build PhoneCam.app for this Mac's CPU (Apple Silicon or Intel) from a clean venv.
#
#   ./build.sh                          # uses python3 from PATH (3.12+)
#   PYTHON=/path/to/python3.14 ./build.sh
#
# Output: dist/PhoneCam.app and dist/PhoneCam-<version>-<apple-silicon|intel>.zip
# Python is only needed here, on the build Mac; the app bundles its own.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 12))' \
  || { echo "Python 3.12 or newer is required (found: $("$PYTHON" --version))." >&2; exit 1; }

# The CPU of the Python interpreter decides the CPU of the app.
case "$("$PYTHON" -c 'import platform; print(platform.machine())')" in
  arm64) FLAVOR=apple-silicon ;;
  x86_64) FLAVOR=intel ;;
  *) echo "Unsupported CPU type." >&2; exit 1 ;;
esac
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' phonecam/__init__.py)"
echo "==> Building PhoneCam $VERSION for $FLAVOR"

echo "==> Creating a clean build environment"
rm -rf .build-venv build dist
"$PYTHON" -m venv .build-venv
.build-venv/bin/pip install --quiet --upgrade pip
.build-venv/bin/pip install --quiet -r requirements.txt -r requirements-build.txt

echo "==> Running PyInstaller"
.build-venv/bin/pyinstaller --noconfirm --clean --log-level WARN PhoneCam.spec
APP=dist/PhoneCam.app

echo "==> Checking that the app needs nothing outside its bundle"
# Every native library must point only into the bundle (@rpath, @loader_path,
# @executable_path) or at macOS itself (/usr/lib, /System). A path into
# Homebrew, a Python install or a home folder would break on other Macs.
bad=0
while IFS= read -r -d '' file; do
  if file -b "$file" | grep -q Mach-O; then
    if otool -L "$file" | tail -n +2 | awk '{print $1}' | grep -E '^/(usr/local|opt/homebrew|Library/Frameworks|Users)/'; then
      echo "   ^ referenced by ${file#$APP/}" >&2
      bad=1
    fi
  fi
done < <(find "$APP" -type f \( -name '*.so' -o -name '*.dylib' -o -perm -u+x \) -print0)
[ "$bad" = 0 ] || { echo "The app depends on files outside the bundle (see above)." >&2; exit 1; }

echo "==> Checking the code signature"
# PyInstaller signs everything ad hoc. Apple Silicon refuses to run unsigned
# code, so make sure the bundle's signature is intact.
codesign --verify --deep --strict "$APP"

echo "==> Self-test of the built app (clean environment, no venv)"
env -i HOME="$HOME" PATH=/usr/bin:/bin "$APP/Contents/MacOS/PhoneCam" --self-test

ZIP="dist/PhoneCam-$VERSION-$FLAVOR.zip"
ditto -c -k --keepParent "$APP" "$ZIP"  # ditto keeps the bundle's symlinks and signature intact
echo "==> Done: $APP and $ZIP ($(du -h "$ZIP" | cut -f1))"
