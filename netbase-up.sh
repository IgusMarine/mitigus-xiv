#!/bin/sh
# ---------------------------------------------------------------------------
# Base routing for the Weave Box.
#
# This makes the laptop a working router for the PS5 AT ALL TIMES, so the PS5
# keeps normal internet whether the mitigator is on or off. The mitigator only
# adds its own REDIRECT rules on top when it runs.
#
# install.sh wires this into a systemd unit that runs at every boot. You can
# also run it by hand:   sudo sh scripts/netbase-up.sh   [WAN_INTERFACE]
# ---------------------------------------------------------------------------
set -e

WAN_IF="${1:-$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}')}"
if [ -z "$WAN_IF" ]; then
  echo "Could not auto-detect the network interface. Pass it as the first argument," >&2
  echo "e.g.  sudo sh scripts/netbase-up.sh eth0" >&2
  exit 1
fi

# Route packets between the PS5 and the internet.
sysctl -w net.ipv4.ip_forward=1

# Stop the box from telling the PS5 to bypass it (ICMP redirects break the MITM
# in a one-interface setup).
sysctl -w net.ipv4.conf.all.send_redirects=0
sysctl -w "net.ipv4.conf.${WAN_IF}.send_redirects=0" 2>/dev/null || true

# NAT outbound traffic so replies come back through this box.
if ! iptables -t nat -C POSTROUTING -o "$WAN_IF" -j MASQUERADE 2>/dev/null; then
  iptables -t nat -A POSTROUTING -o "$WAN_IF" -j MASQUERADE
fi

echo "Base routing active on ${WAN_IF}  (ip_forward=1, send_redirects=0, MASQUERADE set)."
