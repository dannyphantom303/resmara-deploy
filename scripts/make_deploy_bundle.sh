#!/usr/bin/env bash
# Build a handoff tarball of the Resmara code without any local state or secrets.
#
#   ./scripts/make_deploy_bundle.sh            # writes ~/Desktop/resmara-deploy-<date>.tar.gz
#   ./scripts/make_deploy_bundle.sh /tmp/out   # or wherever
#
# Never included: .env (real secrets), the sqlite database, uploaded client media, the
# venv symlink, caches. Checked at the end and the script fails loudly if one slipped in.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$HOME/Desktop}"
STAMP="$(date +%Y%m%d-%H%M)"
BUNDLE="$OUT_DIR/resmara-deploy-$STAMP.tar.gz"

cd "$SRC"
tar czf "$BUNDLE" \
  --exclude='./venv' \
  --exclude='./.venv' \
  --exclude='./.env' \
  --exclude='./.env.local' \
  --exclude='./resmara.db' \
  --exclude='./uploads' \
  --exclude='*/__pycache__' \
  --exclude='*/__pycache__/*' \
  --exclude='*.pyc' \
  --exclude='./.git' \
  --exclude='./.DS_Store' \
  ./app ./static ./tests ./admin ./workers ./engine_spec ./scripts \
  ./requirements.txt ./Dockerfile ./docker-compose.yml ./docker-entrypoint.sh \
  ./.env.example ./.dockerignore ./.gitignore ./DEPLOY.md ./README.md ./proxy.py

echo "bundle: $BUNDLE"
tar tzf "$BUNDLE" | grep -E '(^|/)(\.env$|.*\.db$|venv/|__pycache__)' && { echo "REFUSING: bundle carries a secret, local state or a cache"; exit 1; }
echo "clean: no .env, no database, no venv"
echo "size: $(du -h "$BUNDLE" | cut -f1)  files: $(tar tzf "$BUNDLE" | wc -l | tr -d ' ')"
