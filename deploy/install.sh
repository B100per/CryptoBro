#!/usr/bin/env bash
# Install or update the collector on a Debian/Ubuntu VPS. Run as root.
#   curl -fsSL https://raw.githubusercontent.com/B100per/CryptoBro/main/deploy/install.sh | bash
set -euo pipefail

REPO=https://github.com/B100per/CryptoBro.git
DIR=/opt/cryptobro
SVC_USER=cryptobro

[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }

if ! command -v git >/dev/null || ! command -v python3 >/dev/null; then
  apt-get update && apt-get install -y git python3
fi
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --home "$DIR" --shell /usr/sbin/nologin "$SVC_USER"

if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone "$REPO" "$DIR"; fi
chown -R "$SVC_USER:$SVC_USER" "$DIR"

# Backfill before the service starts: two writers on one sqlite file is a lock fight.
systemctl stop cryptobro 2>/dev/null || true
sudo -u "$SVC_USER" python3 "$DIR/collector.py" --backfill

[ -f /etc/cryptobro.env ] || { touch /etc/cryptobro.env; chmod 600 /etc/cryptobro.env; }
install -m 644 "$DIR/deploy/cryptobro.service" /etc/systemd/system/cryptobro.service
install -m 644 "$DIR/deploy/retention.service" /etc/systemd/system/retention.service
install -m 644 "$DIR/deploy/retention.timer" /etc/systemd/system/retention.timer
systemctl daemon-reload
systemctl enable --now cryptobro
systemctl enable --now retention.timer
sleep 5
systemctl --no-pager status cryptobro | head -12
echo
echo "logs:  journalctl -u cryptobro -f"
echo "check: sudo -u $SVC_USER sqlite3 $DIR/data.db 'select ts, count(*) from positioning group by ts'"
