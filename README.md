# CAKE QoS — Home Assistant Integration

Control [CAKE](https://www.bufferbloat.net/projects/codel/wiki/Cake/) QoS and [cake-autorate](https://github.com/lynxthecat/cake-autorate) from Home Assistant.

Designed for **OpenWrt routers** running CAKE natively via SQM. Sensors are provided by cake-autorate's built-in [MQTT publisher](https://github.com/lynxthecat/cake-autorate/blob/master/mqtt-publisher.sh) via HA auto-discovery; this integration provides **control entities only** (switch, number, button) via a lightweight HTTP exporter on the router.

---

## Architecture (v0.6.0)

```
Internet / ISP
      │
  eth1 [CAKE upload shaper]
      │
  OpenWrt router
  ├── cake-autorate          ──→ /var/log/cake-autorate.primary.log
  ├── mqtt-publisher.sh      ──→ Mosquitto (HA add-on) ──→ HA MQTT sensors (auto-discovery)
  └── cake-stats-exporter :9101  ──→ HA custom integration (control entities)
      │
  ifb4eth1 [CAKE download shaper]
      │
LAN clients
```

**Monitoring** (rates, latency, load conditions, CPU) comes from MQTT auto-discovery — 13 sensors published by `mqtt-publisher.sh`, zero configuration in HA.

**Control** (start/stop autorate, adjust rates & thresholds, restart) comes from this custom integration, which talks to `cake-stats-exporter` over HTTP.

---

## Requirements

- Home Assistant 2024.1+
- HACS
- **Mosquitto MQTT broker** (HA add-on or external)
- OpenWrt router with:
  - CAKE/SQM enabled (`kmod-sched-cake`, `sqm-scripts`)
  - [cake-autorate](https://github.com/lynxthecat/cake-autorate) installed
  - `mosquitto-client-nossl` (for `mqtt-publisher.sh`)
  - Python 3 (`apk add python3` on OpenWrt 24+)
  - The [cake-stats-exporter](#server-setup) running on the router

---

## MQTT Sensor Setup

cake-autorate includes `mqtt-publisher.sh` which tails the autorate log and publishes metrics via MQTT with HA auto-discovery. No custom integration needed for sensors.

### 1. Install MQTT on your HA instance

Install the **Mosquitto broker** add-on from the HA add-on store, or configure an external MQTT broker.

### 2. Create an HA user for MQTT

Create a local HA user (e.g. `openwrt`) for the MQTT publisher to authenticate with.

### 3. Install mosquitto client on OpenWrt

```sh
apk add mosquitto-client-nossl
```

### 4. Configure mqtt-publisher.sh

Edit your cake-autorate config (`config.primary.sh`):

```sh
MQTT_HOST="192.168.8.5"    # your HA IP
MQTT_PORT="1883"
MQTT_USER="openwrt"
MQTT_PASS="your_password"
```

### 5. Enable mqtt-publisher.sh at boot

```sh
cat > /etc/init.d/mqtt-publisher << 'INITEOF'
#!/bin/sh /etc/rc.common
START=99
USE_PROCD=1
start_service() {
    procd_open_instance
    procd_set_param command /root/cake-autorate/mqtt-publisher.sh
    procd_set_param respawn 3600 5 0
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}
INITEOF
chmod +x /etc/init.d/mqtt-publisher
/etc/init.d/mqtt-publisher enable
/etc/init.d/mqtt-publisher start
```

### MQTT Sensors (auto-discovered)

Once running, these sensors appear automatically in HA:

| Entity | Description | Unit |
|--------|-------------|------|
| DL achieved rate | Download throughput | kbps |
| UL achieved rate | Upload throughput | kbps |
| CAKE DL shaper rate | Applied download shaper | kbps |
| CAKE UL shaper rate | Applied upload shaper | kbps |
| DL delay sum | Download delay measurement | us |
| UL delay sum | Upload delay measurement | us |
| DL OWD delta | Download OWD delta | us |
| UL OWD delta | Upload OWD delta | us |
| DL load condition | Download load state | — |
| UL load condition | Upload load state | — |
| CPU core 0–N | Per-core CPU usage | % |

> **Tip:** MQTT rates are in kbps. Use HA template sensors to convert to Mbit/s:
> ```yaml
> {{ (states('sensor.cake_autorate_primary_cake_dl_shaper_rate') | float / 1000) | round(1) }}
> ```

---

## Server Setup (Control Exporter)

The HTTP exporter lives in [`server/`](server/). It provides the control API used by this integration's switch, number, and button entities.

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

### Control API

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

## Entities (Control Only)

> **Note:** Monitoring sensors (rates, latency, load, CPU) are provided by MQTT auto-discovery — see [MQTT Sensor Setup](#mqtt-sensor-setup) above. This integration provides control entities only.

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

- Control poll interval: 30 seconds (DataUpdateCoordinator) — only fetches service state and config for control entities
- MQTT sensors update in real-time (every ~2 seconds from mqtt-publisher.sh)
- Static rates are persisted to `/root/cake-stats/static-rates.json` on the router (overlay filesystem — survives reboot, lost on sysupgrade)
- `apply-cake.sh` uses `tc qdisc replace` — safe to run while traffic is flowing
- Service control uses procd (`/etc/init.d/cake-autorate`) — no systemd on OpenWrt

## Changelog

### v0.6.0

- **Breaking:** Removed all 17 sensor entities — replaced by MQTT auto-discovery via cake-autorate's `mqtt-publisher.sh`
- Removed options flow (scan_interval no longer configurable)
- Hardcoded poll interval to 30s (control entities only)
- Updated strings: "CAKE bridge" → "router"

### v0.5.1

- Configurable poll interval via options flow (2–60s)

### v0.5.0

- Migrated from LXC cake-bridge to OpenWrt native CAKE
- Fixed partial trailing log line in autorate tail parser

### v0.4.0

- Initial public release with HTTP exporter
