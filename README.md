# CAKE QoS — Home Assistant Integration

Monitor and control [CAKE](https://www.bufferbloat.net/projects/codel/wiki/Cake/) QoS with [cake-autorate](https://github.com/lynxthecat/cake-autorate) from Home Assistant.

Designed for **OpenWrt routers** running CAKE natively via SQM. Communicates with a lightweight HTTP exporter (`cake-stats-exporter`) running on the router.

---

## Architecture

```
Internet / ISP
      │
  eth1 [CAKE↑ — upload shaper, egress]
      │
  OpenWrt router  ◄── cake-stats-exporter :9101
      │
  ifb4eth1 [CAKE↓ — download shaper, ingress via IFB]
      │
LAN clients
```

Traffic is shaped at the WAN interface (`eth1` egress for upload) and via an IFB device (`ifb4eth1` egress for download). `cake-autorate` continuously adjusts rates based on measured OWD latency.

---

## Requirements

- Home Assistant 2024.1+
- HACS
- OpenWrt router with:
  - CAKE/SQM enabled (`kmod-sched-cake`, `sqm-scripts`)
  - [cake-autorate](https://github.com/lynxthecat/cake-autorate) installed
  - Python 3 (`apk add python3` on OpenWrt 24+)
  - The [cake-stats-exporter](#server-setup) running on the router

---

## Server Setup

The exporter lives in [`server/`](server/). Deploy it to your OpenWrt router.

### Prerequisites

```sh
# On OpenWrt (requires Python 3 — available in OpenWrt 24+)
apk add python3

# Create persistent state directory
mkdir -p /root/cake-stats
```

### Deploy

```sh
# Copy files to your router
scp server/cake-stats-exporter.py root@192.168.8.1:/usr/local/bin/
scp server/apply-cake.sh root@192.168.8.1:/usr/local/bin/
scp server/cake-stats-exporter.init root@192.168.8.1:/etc/init.d/cake-stats-exporter

# On the router:
chmod +x /usr/local/bin/apply-cake.sh
chmod +x /etc/init.d/cake-stats-exporter

# Enable and start
/etc/init.d/cake-stats-exporter enable
/etc/init.d/cake-stats-exporter start
```

### Configuration

All paths and the listen address can be overridden via `/etc/cake-stats-exporter.conf` (sourced by the init script) or environment variables:

| Variable | Default | Description |
|---|---|---|
| `CAKE_LISTEN_ADDR` | `0.0.0.0` | Bind address |
| `CAKE_LISTEN_PORT` | `9101` | Bind port |
| `CAKE_AUTORATE_LOG` | `/var/log/cake-autorate.primary.log` | cake-autorate log |
| `CAKE_AUTORATE_CONFIG` | `/root/cake-autorate/config.primary.sh` | cake-autorate config |
| `CAKE_APPLY_SCRIPT` | `/usr/local/bin/apply-cake.sh` | Script to apply static rates |
| `CAKE_STATIC_RATES` | `/root/cake-stats/static-rates.json` | Persisted static rates |
| `CAKE_SERVICE_INIT` | `/etc/init.d/cake-autorate` | cake-autorate init.d script |
| `CAKE_WAN_IFACE` | `eth1` | WAN interface (for apply-cake.sh) |

Example `/etc/cake-stats-exporter.conf`:
```sh
CAKE_LISTEN_ADDR="192.168.1.1"
CAKE_WAN_IFACE="eth0"
```

### Non-OpenWrt (systemd)

If you're running on a Linux host with systemd, use the provided `cake-stats-exporter.service` unit instead of the init.d script. Adjust the `CAKE_*` environment variables in the unit to match your paths.

### API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/stats` | Full stats (tc + autorate + service state + static rates) |
| GET | `/health` | Liveness check |
| GET | `/config` | Current autorate config values |
| GET | `/cake/rates` | Persisted static rate settings |
| POST | `/autorate/start` | Start cake-autorate |
| POST | `/autorate/stop` | Stop cake-autorate |
| POST | `/autorate/restart` | Restart cake-autorate |
| POST | `/config` | Update autorate config (JSON body) |
| POST | `/cake/rates` | Set static rates (`dl_rate_mbit`, `ul_rate_mbit`) |

---

## Installation (HACS)

1. Add this repository as a custom HACS integration repository
2. Install **CAKE QoS** from HACS
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration → CAKE QoS**
5. Enter the exporter host (your router IP, e.g. `192.168.8.1`) and port (`9101`)

---

## Entities

### Sensors (17)

| Entity | Description | Unit |
|--------|-------------|------|
| Download shaper rate | Live CAKE bandwidth from `tc` (ground truth) | Mbit/s |
| Upload shaper rate | Live CAKE bandwidth from `tc` (ground truth) | Mbit/s |
| Download achieved | Autorate measured throughput | Mbit/s |
| Upload achieved | Autorate measured throughput | Mbit/s |
| Download load | Load condition (Idle / Low / Waiting / High) | — |
| Upload load | Load condition (Idle / Low / Waiting / High) | — |
| Download delay | CAKE tin avg queue delay | µs |
| Upload delay | CAKE tin avg queue delay | µs |
| Download latency delta | OWD delta from autorate | µs |
| Upload latency delta | OWD delta from autorate | µs |
| Download drops | CAKE drop counter | — |
| Upload drops | CAKE drop counter | — |
| Download sparse flows | CAKE flow count | — |
| Download bulk flows | CAKE flow count | — |
| Download bandwidth | Raw tc bandwidth_mbit (diagnostic) | Mbit/s |
| Upload bandwidth | Raw tc bandwidth_mbit (diagnostic) | Mbit/s |
| Autorate service | Service running state | — |

### Switch (1)

| Entity | Description |
|--------|-------------|
| Autorate | Start/stop cake-autorate. Turning off applies the persisted static rates. |

### Numbers (8)

| Entity | Description | Unit |
|--------|-------------|------|
| Min download rate | Autorate minimum DL boundary | Mbit/s |
| Base download rate | Autorate starting DL rate | Mbit/s |
| Max download rate | Autorate maximum DL boundary | Mbit/s |
| Min upload rate | Autorate minimum UL boundary | Mbit/s |
| Base upload rate | Autorate starting UL rate | Mbit/s |
| Max upload rate | Autorate maximum UL boundary | Mbit/s |
| Download delay threshold | OWD delta that triggers rate reduction | ms |
| Upload delay threshold | OWD delta that triggers rate reduction | ms |

Changing an autorate number entity automatically restarts cake-autorate to apply the new config.

### Static rate numbers (2)

Shown on the dashboard only when autorate is **off**:

| Entity | Description | Unit |
|--------|-------------|------|
| Static download rate | Fixed CAKE DL rate | Mbit/s |
| Static upload rate | Fixed CAKE UL rate | Mbit/s |

### Button (1)

| Entity | Description |
|--------|-------------|
| Restart autorate | Force restart cake-autorate service |

---

## Notes

- Poll interval: 10 seconds (DataUpdateCoordinator)
- Shaper rate sensors read directly from `tc` qdisc stats — not from autorate log — so they always reflect the currently applied rate
- Static rates are persisted to `/root/cake-stats/static-rates.json` on the router (overlay filesystem — survives reboot, lost on sysupgrade)
- `apply-cake.sh` uses `tc qdisc replace` — safe to run while traffic is flowing
- Service control uses procd (`/etc/init.d/cake-autorate`) — no systemd on OpenWrt
