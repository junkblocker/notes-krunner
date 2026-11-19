#!/usr/bin/env bash

set -euo pipefail

shopt -q -o xtrace && DEBUG=1
shopt -q -o verbose && VERBOSE=1
[[ -n ${DEBUG:-} ]] && set -x
[[ -n ${VERBOSE:-} ]] && set -v

APPNAME="Notes" # One word is better
export APPNAME
APPNAMELC="$(LC=C tr "[:upper:]" "[:lower:]" <<<"$APPNAME")"
APPNAMELC="${APPNAMELC//[^a-z]/}"
export APPNAMELC

prefix="${XDG_DATA_HOME:-$HOME/.local/share}"
krunner_dbusdir="$prefix/krunner/dbusplugins"
PROJECTDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

rm -f -- "$krunner_dbusdir/${APPNAMELC}.desktop" \
    "$prefix/dbus-1/services/org.kde.${APPNAMELC}.service" \
    "$HOME/.config/autostart/${APPNAMELC}_autostart.desktop" \
    "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/${APPNAMELC}_autostart.desktop" \
    "$PROJECTDIR/$APPNAMELC.py" "$PROJECTDIR/krunner-plugininstallerrc"
/usr/bin/python3 "$PROJECTDIR/stop-runner.py" "$PROJECTDIR/$APPNAMELC.py"
kquitapp6 krunner >/dev/null 2>&1 || true
echo "Done."
