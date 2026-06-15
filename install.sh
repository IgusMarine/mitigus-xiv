#!/bin/sh
# ---------------------------------------------------------------------------
# One-time installer. Run as root on the Linux box:
#
#   sudo sh scripts/install.sh
#
# Installs Python deps, brings base routing up, and registers two systemd units:
#   weave-netbase.service  base routing at every boot
#   weave-box.service      the web control panel
# ---------------------------------------------------------------------------
set -e

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON_BIN:-python3}"
PORT="${WEAVE_PORT:-8080}"

if [ "$(id -u)" != "0" ]; then
  echo "Please run as root:  sudo sh scripts/install.sh" >&2
  exit 1
fi

echo "[1/4] Installing Python dependencies..."
"$PY" -m pip install --break-system-packages -r "$HERE/requirements.txt" \
  || "$PY" -m pip install -r "$HERE/requirements.txt"

echo "[2/4] Bringing base routing up now..."
sh "$HERE/scripts/netbase-up.sh" || echo "  (skipped; fix the interface and re-run netbase-up.sh)"

echo "[3/4] Registering systemd units..."
cat > /etc/systemd/system/weave-netbase.service <<EOF
[Unit]
Description=Weave Box base routing (MASQUERADE + ip_forward)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/sh $HERE/scripts/netbase-up.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sed "s|__HERE__|$HERE|g; s|__PY__|$PY|g" "$HERE/systemd/weave-box.service" \
  > /etc/systemd/system/weave-box.service

systemctl daemon-reload
systemctl enable --now weave-netbase.service
systemctl enable --now weave-box.service

echo "[4/4] Done."
IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')"
echo ""
echo "  Panel:  http://${IP:-<this-box-ip>}:${PORT}"
echo "  Logs :  journalctl -u weave-box -f"
