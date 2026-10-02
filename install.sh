#!/usr/bin/env bash
# Installs browser-selector into the home of the caller. The default browser
# is left alone unless --set-default is given.
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
python=/usr/bin/python3

if [[ $# -gt 1 || ( $# -eq 1 && $1 != --set-default ) ]]; then
    echo "usage: install.sh [--set-default]" >&2
    exit 1
fi
# Never through a link and never onto the checkout itself: the files in the
# data directory are replaced on install and removed on uninstall.
if [[ -L $lib ]]; then
    echo "install.sh: $lib is a symbolic link, the files behind it are not touched" >&2
    exit 1
fi
if [[ -d $lib && $(cd "$lib" && pwd -P) == "$here" ]]; then
    echo "install.sh: $lib is the directory of this script, that is not an install" >&2
    exit 1
fi
if [[ ! -x $python ]]; then
    echo "install.sh: $python is not there" >&2
    exit 1
fi
if [[ $bin == *[[:cntrl:]]* ]]; then
    echo "install.sh: the home directory has a control character in its name" >&2
    exit 1
fi

# put MODE FILE: stdin becomes FILE through a temporary file and a rename. A
# symlink that sits at FILE is replaced, nothing is ever written through it.
put() {
    local tmp
    tmp=$(mktemp "$(dirname "$2")/.browser-selector.XXXXXX")
    if cat > "$tmp" && chmod "$1" "$tmp" && mv -fT "$tmp" "$2"; then
        return 0
    fi
    rm -f "$tmp"
    return 1
}

# desktop_word TEXT: TEXT as one argument of an Exec line, with %% for a
# percent sign. Quoted the way the Desktop Entry specification asks, and only
# when it has one of the characters the specification reserves: double quotes,
# a backslash before " ` $ and \, then every backslash once more, because
# Exec is a string value. A letter that is not ASCII is not reserved, and
# xdg-settings 1.1.3 cannot register a quoted entry.
reserved=$' \t\n"\'\\><~|&;$*?#()`'
desktop_word() {
    local word=$1
    if [[ $word != *["$reserved"]* ]]; then
        printf '%s' "${word//%/%%}"
        return
    fi
    word=${word//\\/\\\\}
    word=${word//\"/\\\"}
    word=${word//\`/\\\`}
    word=${word//\$/\\\$}
    word=${word//\\/\\\\}
    word=${word//%/%%}
    printf '"%s"' "$word"
}

mkdir -p "$lib" "$apps" "$(dirname "$bin")"

# The handler runs in the environment of whatever app a link is clicked in.
# Isolated mode keeps the PYTHONPATH, the PYTHONHOME and the virtualenv of
# that app away from it.
{
    printf '#!%s -I\n' "$python"
    tail -n +2 "$here/browser_selector.py"
} | put 755 "$lib/browser_selector.py"
put 644 "$lib/browser_selector_gui.py" < "$here/browser_selector_gui.py"

link=$(mktemp -u "$(dirname "$bin")/.browser-selector.XXXXXX")
ln -s "$lib/browser_selector.py" "$link"
if ! mv -fT "$link" "$bin"; then
    rm -f "$link"
    exit 1
fi

word=$(desktop_word "$bin")
for file in "$entry" "$settings_entry"; do
    desktop=$(<"$here/$file")
    printf '%s%s%s\n' "${desktop%%@BIN@*}" "$word" "${desktop#*@BIN@}" | put 644 "$apps/$file"
done

current=$(xdg-settings get default-web-browser 2>/dev/null || true)
# The browser to go back to: the current default, or the recorded one when
# the handler is the default already.
previous=$current
if [[ -z $current || $current == "$entry" ]]; then
    previous=$(cat "$state/previous-default" 2>/dev/null || true)
fi

if [[ -e $config || -L $config ]]; then
    echo "Config kept:  $config"
elif written=$("$bin" --init-config); then
    echo "Config:       $written"
else
    echo "Config:       not written. Until there is one every link goes to the first"
    echo "              browser the handler finds."
fi
echo "Handler:      $bin -> $lib/browser_selector.py"
echo "Desktop file: $apps/$entry"
echo "Settings:     $bin --settings, or Browser Selector in the app grid"

if [[ $# -eq 0 ]]; then
    echo
    echo "The default browser is not changed. To switch:"
    echo "    xdg-settings set default-web-browser $entry"
    echo "To go back:"
    echo "    xdg-settings set default-web-browser ${previous:-<browser>.desktop}"
    exit 0
fi

if ! command -v xdg-settings > /dev/null; then
    echo "install.sh: xdg-settings is not found, the default browser is not changed" >&2
    exit 1
fi
if ! xdg-settings set default-web-browser "$entry"; then
    echo "install.sh: xdg-settings could not make $entry the default browser" >&2
    if [[ $word == \"* ]]; then
        echo "a home directory with a reserved character in its path cannot be registered by xdg-settings 1.1.3" >&2
    fi
    exit 1
fi
# Written down after the switch: one that did not happen leaves nothing behind.
if [[ -n $current && $current != "$entry" ]]; then
    mkdir -p "$state"
    printf '%s\n' "$current" | put 644 "$state/previous-default"
fi
echo
echo "browser-selector is the default browser now. To go back:"
echo "    xdg-settings set default-web-browser ${previous:-<browser>.desktop}"
