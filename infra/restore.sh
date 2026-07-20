#!/usr/bin/env bash
# Restore a backup.tgz made by backup.sh onto a new box (run after setup.sh).
set -e
[ -f "$1" ] || { echo "usage: restore.sh <backup.tgz>"; exit 1; }
tar xzf "$1" -C /
systemctl restart gim && systemctl reload nginx
echo "Restored journal, cache and GRYD. Done."
