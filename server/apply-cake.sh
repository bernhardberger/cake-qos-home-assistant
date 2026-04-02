#!/bin/bash
# /usr/local/bin/apply-cake.sh — CAKE Bridge LXC (edge:102)
# Deployed by playbooks/deploy-cake-bridge.sh
#
# Applies CAKE qdiscs to both bridge interfaces.
# Called by /etc/network/interfaces post-up and by cake-autorate for rate changes.
#
# Download shaping: eth1 egress (toward LAN clients)
#   - dual-dsthost: fairness per destination IP (each LAN device gets fair share)
# Upload shaping: eth0 egress (toward OPNsense/WAN)
#   - dual-srchost: fairness per source IP (each LAN device gets fair share)
#
# Initial rates are conservative. cake-autorate will adjust dynamically.

set -euo pipefail

DL_RATE="${1:-400mbit}"
UL_RATE="${2:-80mbit}"

# Download direction: eth1 egress (LXC → LAN)
tc qdisc replace dev eth1 root cake \
    bandwidth "$DL_RATE" \
    besteffort \
    wash \
    nat \
    dual-dsthost \
    ingress

# Upload direction: eth0 egress (LXC → OPNsense → WAN)
tc qdisc replace dev eth0 root cake \
    bandwidth "$UL_RATE" \
    besteffort \
    wash \
    nat \
    dual-srchost \
    egress

echo "$(date '+%F %T') CAKE applied: DL=${DL_RATE} UL=${UL_RATE}" | logger -t cake-bridge
