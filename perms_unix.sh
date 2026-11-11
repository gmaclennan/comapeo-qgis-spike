#!/usr/bin/env bash
# Run via: SPIKE_SOCKET_DIR=/tmp node run.js bash perms_unix.sh
# Checks that the 0600 socket rejects another local user.
set -u
P="$SPIKE_PATH"

try_connect() {
  "$@" python3 -c '
import socket, sys
s = socket.socket(socket.AF_UNIX)
try:
    s.connect(sys.argv[1])
    print("connect OK")
except OSError as e:
    print("connect FAILED: %s %s" % (type(e).__name__, e))
' "$P" 2>&1
}

ls -l "$P"
owner=$(try_connect)
echo "owner, mode 600:   $owner"
other=$(try_connect sudo -u nobody)
echo "nobody, mode 600:  $other"
chmod 666 "$P"
control=$(try_connect sudo -u nobody)
echo "nobody, mode 666:  $control (control)"

{
  echo "**unix socket permissions ($(uname -s))**"
  echo
  echo "- owner, mode 600: $owner"
  echo "- nobody, mode 600: $other"
  echo "- nobody, mode 666 (control): $control"
  echo
} >>"${GITHUB_STEP_SUMMARY:-/dev/null}"

[[ "$owner" == "connect OK" ]] || exit 1
[[ "$other" == *PermissionError* ]] || exit 1
[[ "$control" == "connect OK" ]] || exit 1
echo "OK: 0600 restricts connections to the owner"
