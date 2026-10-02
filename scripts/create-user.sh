#!/usr/bin/env bash
set -euo pipefail
set +x

task_project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$task_project"

read -r -p 'Login (for example demo1): ' task_login
if [[ ! "$task_login" =~ ^[a-z0-9._=-]+$ ]]; then
  echo 'Use a nonempty login with lowercase Latin letters, digits, . _ = or -.' >&2
  exit 1
fi

IFS= read -rs -p 'Password (hidden): ' task_password
printf '\n'
IFS= read -rs -p 'Repeat password (hidden): ' task_confirmation
printf '\n'
if [[ "$task_password" != "$task_confirmation" ]]; then
  echo 'Passwords do not match; user was not created.' >&2
  exit 1
fi
# Synapse --password-file strips whitespace: reject it instead of changing a password.
if ! builtin printf '%s' "$task_password" | python3 -c 'import sys; p=sys.stdin.read(); sys.exit(0 if p and p == p.strip() else 1)'; then
  echo 'Password must be nonempty and have no leading or trailing whitespace.' >&2
  exit 1
fi

[[ ${#task_password} -ge 12 ]] || {
  echo 'Password must be at least 12 characters; user was not created.' >&2
  exit 1
}

builtin printf '%s' "$task_password" |
  docker compose exec -T synapse register_new_matrix_user \
    -c /data/homeserver.yaml -u "$task_login" --no-admin \
    --password-file /dev/stdin http://localhost:8008
unset task_password task_confirmation
