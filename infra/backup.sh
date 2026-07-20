#!/usr/bin/env bash
# One-file backup of everything not in git: journal, cache, GRYD site.
set -e
OUT="/root/strait-backup-$(date +%Y%m%d-%H%M).tgz"
tar czf "$OUT" /opt/gim/data /var/www/bharatgrid /var/www/gryd 2>/dev/null || \
tar czf "$OUT" /opt/gim/data
echo "Backup written: $OUT — pull it to your laptop with:"
echo "  scp root@$(hostname -I | awk '{print $1}'):$OUT ~/Downloads/"
