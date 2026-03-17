#!/bin/bash
# Syncs latest i9_audit.py from the feature branch to the standalone deployment branch
set -e

SRC_BRANCH="claude/i9-audit-app-fovn5"
DEST_BRANCH="claude/i9-audit-standalone-fovn5"
FILE="api/i9_audit.py"

echo "Syncing $FILE → $DEST_BRANCH..."

git checkout "$DEST_BRANCH"
git show "$SRC_BRANCH:i9-audit/$FILE" > "$FILE"
git add "$FILE"
git diff --cached --quiet && echo "Nothing to sync." && git checkout "$SRC_BRANCH" && exit 0
git commit -m "Sync i9_audit.py from $SRC_BRANCH"
git push origin "$DEST_BRANCH"
git checkout "$SRC_BRANCH"

echo "Done."
