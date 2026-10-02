#!/usr/bin/env bash
# Removes what install.sh put into the home of the caller and puts the
# previous default browser back when browser-selector is the default. The
# config and the log stay.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)

# The base directory specification: a relative path in an XDG variable is to
# be taken as not set. Unset here, the handler and xdg-settings see the same.
for variable in XDG_DATA_HOME XDG_CONFIG_HOME XDG_STATE_HOME; do
    [[ ${!variable:-} == /* ]] || unset "$variable"
done

entry=browser-selector.desktop
settings_entry=browser-selector-settings.desktop
data="${XDG_DATA_HOME:-$HOME/.local/share}"
lib="$data/browser-selector"
apps="$data/applications"
bin="$HOME/.local/bin/browser-selector"
config="${XDG_CONFIG_HOME:-$HOME/.config}/browser-selector/config.ini"
state="${XDG_STATE_HOME:-$HOME/.local/state}/browser-selector"

if [[ $# -gt 1 || ( $# -eq 1 && $1 != --force ) ]]; then
    echo "usage: uninstall.sh [--force]" >&2
    exit 1
fi

# Never through a link and never onto the checkout itself: the files in the
# data directory are replaced on install and removed on uninstall.
if [[ -L $lib ]]; then
    echo "uninstall.sh: $lib is a symbolic link, the files behind it are not touched" >&2
    exit 1
fi
if [[ -d $lib && $(cd "$lib" && pwd -P) == "$here" ]]; then
    echo "uninstall.sh: $lib is the directory of this script, that is not an install" >&2
    exit 1
fi

# The browser to go back to, by the test the handler has for it: the plain
# name of a desktop entry, and not one of the two that are removed here.
previous=$(cat "$state/previous-default" 2>/dev/null || true)
if [[ ! $previous =~ ^[[:alnum:]_.+-]+\.desktop$ || $previous == "$entry" || $previous == "$settings_entry" ]]; then
    previous=
fi

if ! command -v xdg-settings > /dev/null || ! current=$(xdg-settings get default-web-browser 2> /dev/null); then
    current=
    if [[ $# -eq 0 ]]; then
        # It may be the default browser: without the handler such a default opens nothing.
        echo "uninstall.sh: xdg-settings cannot be asked whether browser-selector is the default" >&2
        echo "browser. Nothing is removed. Remove anyway with: uninstall.sh --force" >&2
        exit 1
    fi
    echo "uninstall.sh: xdg-settings cannot be asked, the default browser is left as it is" >&2
fi
if [[ $current == "$entry" ]]; then
    if [[ -n $previous ]] && xdg-settings set default-web-browser "$previous"; then
        echo "Default browser: $previous"
    elif [[ $# -eq 1 ]]; then
        echo "uninstall.sh: browser-selector was the default browser and the previous one" >&2
        echo "could not be put back. Set one:" >&2
        echo "    xdg-settings set default-web-browser <browser>.desktop" >&2
    else
        # Without the handler a default browser that points at it opens nothing.
        echo "uninstall.sh: browser-selector is the default browser and the previous one" >&2
        echo "could not be put back. Nothing is removed. Set a default browser first:" >&2
        echo "    xdg-settings set default-web-browser <browser>.desktop" >&2
        echo "or remove anyway with: uninstall.sh --force" >&2
        exit 1
    fi
fi

# Only what install.sh put there: a ~/.local/bin/browser-selector that is not
# the link into the data directory belongs to someone else.
if [[ -L $bin && $(readlink "$bin") == "$lib/browser_selector.py" ]]; then
    rm -f "$bin"
    echo "Removed: $bin"
elif [[ -e $bin || -L $bin ]]; then
    echo "Left:    $bin (not the link install.sh makes)"
fi
for file in "$apps/$entry" "$apps/$settings_entry" "$lib/browser_selector.py" "$lib/browser_selector_gui.py" \
        "$state/previous-default"; do
    if [[ -f $file || -L $file ]]; then
        rm -f "$file"
        echo "Removed: $file"
    fi
done
if [[ -d $lib ]]; then
    # Python leaves the compiled windows module next to the source.
    rm -rf "$lib/__pycache__"
    rmdir "$lib" 2>/dev/null && echo "Removed: $lib" || echo "Left:    $lib (not empty)"
fi
echo "Kept:    $config"
if [[ -e $state/log ]]; then
    echo "Kept:    $state/log"
fi
