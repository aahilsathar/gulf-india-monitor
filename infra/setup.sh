#!/usr/bin/env bash
# STRAIT stack bootstrap — run as root on any fresh Ubuntu 22/24 box.
set -e
REPO="https://github.com/aahilsathar/gulf-india-monitor.git"

apt update && apt install -y python3-venv git nginx curl zip
mkdir -p /opt
[ -d /opt/gim/.git ] || git clone "$REPO" /opt/gim
cd /opt/gim && git pull
python3 -m venv .venv 2>/dev/null || true
.venv/bin/pip install -q -r requirements.txt

cp infra/gim.service /etc/systemd/system/gim.service
mkdir -p /var/www/html
cp infra/desk-index.html /var/www/html/index.html
cp infra/nginx-desk.conf /etc/nginx/sites-available/default
ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
if [ -d /var/www/gryd ] || [ -d /var/www/bharatgrid ]; then
  cp infra/nginx-gryd.conf /etc/nginx/sites-available/gryd
  ln -sf /etc/nginx/sites-available/gryd /etc/nginx/sites-enabled/gryd
fi

systemctl daemon-reload && systemctl enable --now gim
nginx -t && systemctl reload nginx
echo "DONE — desk on :80, STRAIT on :8010. Restore data with infra/restore.sh <backup.tgz>"
