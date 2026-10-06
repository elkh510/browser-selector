#!/bin/bash
# One launch as one line of launch.log: the name of the browser and its argv,
# tab separated. Sourced by the fake browsers, which write the line, and by
# _boot.sh, which builds the line a scenario expects.

# A backslash, a tab or a newline inside an argument is escaped, so one launch
# is always one line and every tab is a boundary between two arguments
launch_line() {
    local line="" sep="" arg
    for arg in "$@"; do
        arg="${arg//\\/\\\\}"
        arg="${arg//$'\t'/\\t}"
        arg="${arg//$'\n'/\\n}"
        line="$line$sep$arg"
        sep=$'\t'
    done
    printf '%s\n' "$line"
}
