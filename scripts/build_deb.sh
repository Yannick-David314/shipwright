#!/bin/sh
#
# build_deb.sh --- builds the shipwright Debian package.
#
# Usage: sh scripts/build_deb.sh [OUTPUT_DIR]
#
# The package carries one file, /usr/bin/ship, built from packaging/ship.sh.
# The image it runs comes from the registry on first use, so the package holds
# no image and the build needs no Docker.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
OUT_DIR=${1:-$ROOT/dist}
IMAGE=${SHIPWRIGHT_IMAGE_REF:-ghcr.io/abj360/shipwright}
VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$ROOT/agent/__init__.py")
[ -n "$VERSION" ] || { echo "E: no version in agent/__init__.py" >&2; exit 1; }

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
# mktemp makes it private; the package's own root has to be world readable.
chmod 755 "$STAGE"

mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/bin" "$STAGE/usr/share/doc/shipwright"
sed "s|@VERSION@|$VERSION|" "$ROOT/packaging/deb/DEBIAN/control.in" > "$STAGE/DEBIAN/control"
cp "$ROOT/packaging/deb/DEBIAN/postinst" "$ROOT/packaging/deb/DEBIAN/postrm" "$STAGE/DEBIAN/"
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

# Each user keeps their own state, so the launcher expands $HOME at run time.
sed "s|@IMAGE_NAME@|$IMAGE:$VERSION|; s|@STATE_DIR@|\$HOME/.local/share/shipwright/state|" \
    "$ROOT/packaging/ship.sh" > "$STAGE/usr/bin/ship"
chmod 755 "$STAGE/usr/bin/ship"
cp "$ROOT/LICENSE.md" "$STAGE/usr/share/doc/shipwright/copyright"

mkdir -p "$OUT_DIR"
PACKAGE="$OUT_DIR/shipwright_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$PACKAGE" > /dev/null
echo "$PACKAGE"
