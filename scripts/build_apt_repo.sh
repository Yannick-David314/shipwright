#!/bin/sh
#
# build_apt_repo.sh --- lays out the APT repository that serves the package.
#
# Usage: sh scripts/build_apt_repo.sh REPO_DIR PACKAGE.deb...
#
# Adds each package to REPO_DIR, rebuilds the indexes, and signs the release
# when a signing key is available. The layout is a one-suite, one-component,
# architecture-independent repository:
#
#   pool/main/s/shipwright/shipwright_<version>_all.deb
#   dists/stable/main/binary-all/Packages{,.gz}
#   dists/stable/{Release,Release.gpg,InRelease}
set -eu

SUITE=${SHIPWRIGHT_APT_SUITE:-stable}
COMPONENT=main
ARCH=all
ORIGIN="shipwright"

[ $# -ge 2 ] || { echo "usage: build_apt_repo.sh REPO_DIR PACKAGE.deb..." >&2; exit 2; }
REPO=$1
shift

POOL="$REPO/pool/$COMPONENT/s/shipwright"
DIST="$REPO/dists/$SUITE"
BINARY="$DIST/$COMPONENT/binary-$ARCH"
mkdir -p "$POOL" "$BINARY"

for package in "$@"; do
    cp "$package" "$POOL/"
done

# One stanza per package: its own control fields, then where it sits and what
# it hashes to, which is what apt checks before unpacking anything.
: > "$BINARY/Packages"
for package in "$POOL"/*.deb; do
    relative="pool/$COMPONENT/s/shipwright/$(basename "$package")"
    dpkg-deb --field "$package" >> "$BINARY/Packages"
    {
        echo "Filename: $relative"
        echo "Size: $(wc -c < "$package" | tr -d ' ')"
        echo "MD5sum: $(md5sum "$package" | cut -d' ' -f1)"
        echo "SHA256: $(sha256sum "$package" | cut -d' ' -f1)"
        echo
    } >> "$BINARY/Packages"
done
gzip -9 -c "$BINARY/Packages" > "$BINARY/Packages.gz"

{
    echo "Origin: $ORIGIN"
    echo "Label: $ORIGIN"
    echo "Suite: $SUITE"
    echo "Codename: $SUITE"
    echo "Architectures: $ARCH"
    echo "Components: $COMPONENT"
    echo "Description: shipwright packages"
    echo "Date: $(date -Ru)"
    echo "SHA256:"
    for index in "$COMPONENT/binary-$ARCH/Packages" "$COMPONENT/binary-$ARCH/Packages.gz"; do
        printf ' %s %s %s\n' \
            "$(sha256sum "$DIST/$index" | cut -d' ' -f1)" \
            "$(wc -c < "$DIST/$index" | tr -d ' ')" \
            "$index"
    done
} > "$DIST/Release"

# Unsigned is fine for a local check; apt refuses it, so a release signs here.
if [ -n "${SHIPWRIGHT_GPG_KEY_ID:-}" ]; then
    rm -f "$DIST/Release.gpg" "$DIST/InRelease"
    gpg --batch --yes --local-user "$SHIPWRIGHT_GPG_KEY_ID" \
        --armor --detach-sign --output "$DIST/Release.gpg" "$DIST/Release"
    gpg --batch --yes --local-user "$SHIPWRIGHT_GPG_KEY_ID" \
        --clearsign --output "$DIST/InRelease" "$DIST/Release"
    gpg --batch --yes --armor --export "$SHIPWRIGHT_GPG_KEY_ID" > "$REPO/key.gpg"
fi

echo "$REPO"
