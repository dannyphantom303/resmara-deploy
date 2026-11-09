#!/usr/bin/env bash
# Re-home the resmara repository on a new GitHub account.
#
# Run AFTER the new account exists and `gh auth login` is signed in as it.
#   ./scripts/attach_github_account.sh <new-owner>            # execute
#   ./scripts/attach_github_account.sh <new-owner> --dry-run  # print only
#
# Keeps the old repository reachable as remote `old-github`; the new account
# becomes `origin`. Nothing is deleted from GitHub.
set -euo pipefail

OWNER="${1:-}"
DRY=0
[[ "${2:-}" == "--dry-run" ]] && DRY=1

[[ -n "$OWNER" ]] || { echo "usage: $0 <github-owner> [--dry-run]"; exit 2; }

cd "$(dirname "$0")/.."
REPO="$(basename "$PWD")"

ACTIVE="$(gh api user --jq .login)"
echo "gh account : $ACTIVE"
echo "target repo: $OWNER/$REPO"
if [[ "$OWNER" != "$ACTIVE" ]]; then
  echo "WARNING: logged-in account ($ACTIVE) differs from target owner ($OWNER)."
  echo "         Repo will be created under $ACTIVE unless $OWNER is an org it can write to."
fi

# 1. Nothing uncommitted, nothing secret tracked.
git diff --quiet && git diff --cached --quiet || { echo "ERROR: working tree dirty — commit first."; exit 1; }
if git ls-files | grep -qE '(^|/)\.env$|\.db$|\.pem$'; then
  echo "ERROR: secrets or local db are tracked. Refusing to push."; exit 1
fi

run() { if [[ $DRY -eq 1 ]]; then echo "  [dry-run] $*"; else "$@"; fi; }

# 2. Preserve the current origin under a second name. It stays the source for
#    branches that were never checked out locally.
SRC=origin
if ! git remote | grep -qx old-github; then
  run git remote rename origin old-github
  SRC=old-github
elif git remote | grep -qx old-github; then
  SRC=old-github
fi

# 3. Create the new repository.
if gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  echo "repo exists — wiring remote only"
  run git remote remove origin 2>/dev/null || true
  run git remote add origin "https://github.com/$OWNER/$REPO.git"
else
  run gh repo create "$OWNER/$REPO" --private --source=. --remote=origin --push
fi

# 4. Every branch and tag. `push --all` covers local branches only, and this
#    repo carries branches that exist solely on the remote — mirror those too.
run git push origin --all
while read -r ref; do
  [[ "$ref" == */HEAD ]] && continue
  run git push origin "$ref:refs/heads/${ref#refs/remotes/$SRC/}"
done < <(git for-each-ref --format='%(refname)' "refs/remotes/$SRC" 2>/dev/null || true)
run git push origin --tags
run git remote set-head origin -a

echo "remote now:"
git remote -v
echo
echo "Next, in the Render dashboard signed in as resmaraai@gmail.com:"
echo "  Settings -> Build & Deploy -> Repository -> reconnect to $OWNER/$REPO,"
echo "  otherwise auto-deploy keeps watching the old repository."
echo "README 'Deploy to Render' badge must also point at https://github.com/$OWNER/$REPO"
