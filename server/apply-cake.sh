#!/bin/bash
# /usr/local/bin/apply-cake.sh — OpenWrt native CAKE
#
# Applies CAKE qdiscs to the WAN interface and its IFB device.
# Called by cake-autorate for rate changes, or manually for static rates.
#
# Download shaping: IFB device egress (ifb4<WAN_IFACE>, ingress redirected)
#   - dual-dsthost: fairness per destination IP (each LAN device gets fair share)
# Upload shaping: WAN interface egress (toward the modem/ISP)
#   - dual-srchost: fairness per source IP (each LAN device gets fair share)
#
# Initial rates are conservative. cake-autorate will adjust dynamically.
#
# Environment:
#   CAKE_WAN_IFACE   — WAN interface name (default: eth1)

set -euo pipefail

DL_RATE="${1:-400mbit}"
UL_RATE="${2:-80mbit}"
WAN_IFACE="${CAKE_WAN_IFACE:-eth1}"
IFB_IFACE="ifb4${WAN_IFACE}"

# Upload: WAN egress (toward modem/ISP)
tc qdisc replace dev "${WAN_IFACE}" root cake \
    bandwidth "${UL_RATE}" \
    besteffort \
    wash \
    nat \
    dual-srchost \
    egress

# Download: IFB egress (ingress traffic redirected here by SQM)
tc qdisc replace dev "${IFB_IFACE}" root cake \
    bandwidth "${DL_RATE}" \
    besteffort \
    wash \
    nat \
    dual-dsthost \
    ingress

logger -t cake-stats "CAKE applied: WAN=${WAN_IFACE} IFB=${IFB_IFACE} DL=${DL_RATE} UL=${UL_RATE}"
