#!/bin/zsh

set -eu
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

plugin_dir="${0:A:h}"
python_script="${plugin_dir}/gallery.py"
selection_state_file="${TMPDIR:-/tmp}/gallery-yazi-selection.txt"
result_state_file="${TMPDIR:-/tmp}/gallery-yazi-selection-result.txt"
focus_state_file="${TMPDIR:-/tmp}/gallery-yazi-focus.txt"

if [[ ! -f "$python_script" ]]; then
	printf 'Gallery launcher is missing: %s\n' "$python_script" >&2
	exit 1
fi

hovered_path="${1:-}"

/usr/bin/env python3 "$python_script" "$hovered_path" "$selection_state_file" "$result_state_file" "$focus_state_file"
exit_code=$?

exit "$exit_code"
