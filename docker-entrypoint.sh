#!/bin/sh
# Resmara container entrypoint.
#
# The app runs unprivileged (uid 10001). Named volumes and bind mounts, however, arrive owned
# by root — which is how a fresh deployment greets you with "sqlite3.OperationalError: unable
# to open database file" and an unhealthy container. So: as root, make the writable paths ours,
# then drop to the app user and exec the server. Anything but a server command is passed
# through untouched, so `docker compose exec app python scripts/create_operator.py ...` works.
set -e

if [ "$(id -u)" = "0" ]; then
  for d in "${UPLOAD_DIR:-/app/uploads}" /app/uploads; do
    [ -n "$d" ] || continue
    mkdir -p "$d" 2>/dev/null || true
    chown -R resmara:resmara "$d" 2>/dev/null || true
  done

  # A sqlite file needs its directory to be writable too (Postgres ignores all of this).
  case "${DATABASE_URL:-}" in
    sqlite:*)
      p="${DATABASE_URL#sqlite://}"
      p="${p#/}"
      dir="$(dirname "$p")"
      [ -d "$dir" ] && chown resmara:resmara "$dir" 2>/dev/null || true
      ;;
  esac

  exec gosu resmara "$@"
fi

exec "$@"
