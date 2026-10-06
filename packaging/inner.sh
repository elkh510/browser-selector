#!/usr/bin/env bash
# Runs in the container of build-deb.sh: /src is the checkout, /out gets the package.
set -euo pipefail

owner=$1
# The version: $VERSION when the caller gives one (CI counts it from the tags),
# else VERSION of the code. The packaged handler reports what the package is.
version=${VERSION:-$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' /src/browser_selector.py)}
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+(~[0-9a-z]+)?$ ]] || { echo "inner.sh: not a version: '$version'" >&2; exit 1; }

root=$(mktemp -d)
chmod 755 "$root"
lib=$root/usr/lib/browser-selector
install -d "$root/DEBIAN" "$lib" "$root/usr/bin" "$root/usr/share/applications" \
    "$root/usr/share/doc/browser-selector"
install -m 644 /src/browser_selector.py /src/browser_selector_gui.py "$lib/"
sed -i "s/^VERSION = \".*\"$/VERSION = \"$version\"/" "$lib/browser_selector.py"
install -m 755 /src/packaging/launcher "$lib/browser-selector"
ln -s ../lib/browser-selector/browser-selector "$root/usr/bin/browser-selector"
sed 's|@BIN@|/usr/bin/browser-selector|' /src/browser-selector.desktop \
    > "$root/usr/share/applications/browser-selector.desktop"
install -m 644 /src/README.md /src/config.example.ini "$root/usr/share/doc/browser-selector/"

cat > "$root/DEBIAN/control" <<CONTROL
Package: browser-selector
Version: $version
Architecture: all
Maintainer: browser-selector <noreply@localhost>
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, x11-utils, xdg-utils
Section: web
Priority: optional
Description: Default browser that picks a browser and profile by rule
 Opens each link in the browser and profile a rule names, by where the link
 was clicked: the application, the focused window, the URL, a probe command.
CONTROL
# Bytecode for the Python of this machine, written once here and not on every click.
cat > "$root/DEBIAN/postinst" <<'SCRIPT'
#!/bin/sh
set -e
/usr/bin/python3 -I -m compileall -q /usr/lib/browser-selector > /dev/null || true
SCRIPT
cat > "$root/DEBIAN/prerm" <<'SCRIPT'
#!/bin/sh
set -e
rm -rf /usr/lib/browser-selector/__pycache__
SCRIPT
chmod 755 "$root/DEBIAN/postinst" "$root/DEBIAN/prerm"

deb=/out/browser-selector_${version}_all.deb
dpkg-deb --root-owner-group --build "$root" "$deb" > /dev/null
chown "$owner" "$deb"

# The package installs, starts, compiled, and leaves nothing behind.
dpkg -i --force-depends "$deb" > /dev/null 2>&1
[[ $(browser-selector --version) == "browser-selector $version" ]]
ls /usr/lib/browser-selector/__pycache__/browser_selector.*.pyc > /dev/null
[[ $(browser-selector --explain https://example.com/ 2>&1) == *example.com* ]]
dpkg -r browser-selector > /dev/null 2>&1
[[ ! -e /usr/lib/browser-selector && ! -e /usr/bin/browser-selector ]]
echo "built and tried: dist/$(basename "$deb")"
