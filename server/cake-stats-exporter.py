#!/usr/bin/env python3
"""CAKE QoS stats exporter — lightweight HTTP JSON API.

Serves CAKE qdisc stats and cake-autorate state as JSON,
and accepts POST commands to control autorate and static rates.

Endpoints:
    GET  /stats           — full stats (tc + autorate + service state + static rates)
    GET  /health          — liveness check
    GET  /config          — current autorate config values
    GET  /cake/rates      — persisted static CAKE rate settings
    POST /autorate/start  — start cake-autorate service
    POST /autorate/stop   — stop cake-autorate service
    POST /autorate/restart — restart cake-autorate service
    POST /config          — update autorate config (JSON body)
    POST /cake/rates      — set static CAKE rates (dl_rate_mbit, ul_rate_mbit)

Configuration via environment variables (all optional):
    CAKE_LISTEN_ADDR      — bind address (default: 0.0.0.0)
    CAKE_LISTEN_PORT      — bind port (default: 9101)
    CAKE_AUTORATE_LOG     — path to cake-autorate log
                            (default: /var/log/cake-autorate.primary.log)
    CAKE_AUTORATE_CONFIG  — path to cake-autorate config
                            (default: /root/cake-autorate/config.primary.sh)
    CAKE_APPLY_SCRIPT     — path to apply-cake.sh
                            (default: /usr/local/bin/apply-cake.sh)
    CAKE_STATIC_RATES     — path to persisted static rates JSON
                            (default: /root/cake-stats/static-rates.json)
    CAKE_SERVICE_INIT     — path to init.d/service script for cake-autorate
                            (default: /etc/init.d/cake-autorate)
"""

import json
import os
import re
import subprocess
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# -- Configuration (env-var overrides for portability) --

AUTORATE_LOG = Path(os.environ.get(
    "CAKE_AUTORATE_LOG", "/var/log/cake-autorate.primary.log"
))
AUTORATE_CONFIG = Path(os.environ.get(
    "CAKE_AUTORATE_CONFIG", "/root/cake-autorate/config.primary.sh"
))
APPLY_CAKE_SCRIPT = Path(os.environ.get(
    "CAKE_APPLY_SCRIPT", "/usr/local/bin/apply-cake.sh"
))
STATIC_RATES_FILE = Path(os.environ.get(
    "CAKE_STATIC_RATES", "/root/cake-stats/static-rates.json"
))
AUTORATE_SERVICE_INIT = os.environ.get(
    "CAKE_SERVICE_INIT", "/etc/init.d/cake-autorate"
)
LISTEN_ADDR = os.environ.get("CAKE_LISTEN_ADDR", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("CAKE_LISTEN_PORT", "9101"))

# Static rate limits (Mbit/s)
STATIC_DL_RANGE = (10, 600)
STATIC_UL_RANGE = (5, 200)
STATIC_DL_DEFAULT = 400
STATIC_UL_DEFAULT = 80

# Config keys we allow changing, with validation ranges (kbps or ms)
TUNABLE_CONFIG = {
    "base_dl_shaper_rate_kbps":   (50000, 500000),
    "max_dl_shaper_rate_kbps":    (50000, 600000),
    "min_dl_shaper_rate_kbps":    (10000, 200000),
    "base_ul_shaper_rate_kbps":   (10000, 150000),
    "max_ul_shaper_rate_kbps":    (10000, 200000),
    "min_ul_shaper_rate_kbps":    (5000, 100000),
    "dl_owd_delta_delay_thr_ms":  (10, 200),
    "ul_owd_delta_delay_thr_ms":  (10, 200),
    "bufferbloat_detection_thr":  (1, 10),
}


# -- tc qdisc parsing --

def get_cake_qdiscs() -> dict:
    """Parse tc -s -j qdisc show for CAKE stats."""
    try:
        result = subprocess.run(
            ["tc", "-s", "-j", "qdisc", "show"],
            capture_output=True, text=True, timeout=5,
        )
        qdiscs = json.loads(result.stdout)
    except Exception:
        return {"error": "failed to read tc stats"}

    out = {}
    for q in qdiscs:
        if q.get("kind") != "cake":
            continue
        opts = q.get("options", {})
        tin = q.get("tins", [{}])[0]

        label = "upload" if not opts.get("ingress", False) else "download"
        out[label] = {
            "interface": q.get("dev", "unknown"),
            "bandwidth_bps": opts.get("bandwidth", 0) * 8,  # tc returns bytes/sec
            "bandwidth_mbit": round(opts.get("bandwidth", 0) * 8 / 1_000_000, 2),
            "capacity_estimate_mbit": round(q.get("capacity_estimate", 0) / 1_000_000, 2),
            "total_bytes": q.get("bytes", 0),
            "total_packets": q.get("packets", 0),
            "drops": q.get("drops", 0),
            "overlimits": q.get("overlimits", 0),
            "memory_used": q.get("memory_used", 0),
            "memory_limit": q.get("memory_limit", 0),
            "backlog": q.get("backlog", 0),
            "qlen": q.get("qlen", 0),
            "tin": {
                "target_us": tin.get("target_us", 0),
                "peak_delay_us": tin.get("peak_delay_us", 0),
                "avg_delay_us": tin.get("avg_delay_us", 0),
                "base_delay_us": tin.get("base_delay_us", 0),
                "sparse_flows": tin.get("sparse_flows", 0),
                "bulk_flows": tin.get("bulk_flows", 0),
                "unresponsive_flows": tin.get("unresponsive_flows", 0),
                "ecn_mark": tin.get("ecn_mark", 0),
                "ack_drops": tin.get("ack_drops", 0),
            },
        }
    return out


# -- cake-autorate log parsing --

def get_autorate_state() -> dict:
    """Parse the latest SUMMARY and LOAD lines from cake-autorate log."""
    if not AUTORATE_LOG.exists():
        return {"error": "autorate log not found"}

    last_summary = None
    last_load = None

    try:
        with open(AUTORATE_LOG, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4096))
            tail = f.read().decode("utf-8", errors="replace")
    except Exception:
        return {"error": "failed to read autorate log"}

    # Discard any partial trailing line — log is written multiple times/sec
    # so the tail chunk almost always ends mid-line, and keeping the partial
    # line as `last_summary` causes the len(parts) >= 13 check to fail.
    newline_pos = tail.rfind("\n")
    if newline_pos != -1:
        tail = tail[:newline_pos]

    for line in tail.splitlines():
        if line.startswith("SUMMARY;"):
            last_summary = line
        elif line.startswith("LOAD;"):
            last_load = line

    out = {}

    if last_summary:
        parts = [p.strip() for p in last_summary.split(";")]
        if len(parts) >= 13:
            out["timestamp"] = parts[1]
            out["dl_achieved_kbps"] = _int(parts[3])
            out["ul_achieved_kbps"] = _int(parts[4])
            out["dl_avg_latency_delta_us"] = _int(parts[7])
            out["ul_avg_latency_delta_us"] = _int(parts[8])
            out["dl_load_condition"] = parts[9]
            out["ul_load_condition"] = parts[10]
            out["cake_dl_rate_kbps"] = _int(parts[11])
            out["cake_ul_rate_kbps"] = _int(parts[12])
            out["cake_dl_rate_mbit"] = round(_int(parts[11]) / 1000, 2)
            out["cake_ul_rate_mbit"] = round(_int(parts[12]) / 1000, 2)
            out["dl_achieved_mbit"] = round(_int(parts[3]) / 1000, 2)
            out["ul_achieved_mbit"] = round(_int(parts[4]) / 1000, 2)

    if last_load:
        parts = [p.strip() for p in last_load.split(";")]
        if len(parts) >= 8:
            out["load_dl_achieved_kbps"] = _int(parts[4])
            out["load_ul_achieved_kbps"] = _int(parts[5])

    return out


# -- autorate service control (procd / init.d) --

def get_service_state() -> dict:
    """Get cake-autorate service state via init.d script.

    Uses pgrep to check running state (procd status exit code is unreliable),
    and init.d 'enabled' for boot persistence.
    """
    # Running check: look for launcher.sh process
    try:
        result = subprocess.run(
            ["pgrep", "-f", "launcher.sh"],
            capture_output=True, text=True, timeout=5,
        )
        active = "active" if result.returncode == 0 else "inactive"
    except Exception:
        active = "unknown"

    # Enabled check: init.d enabled exits 0 if enabled, non-zero if not
    try:
        result = subprocess.run(
            [AUTORATE_SERVICE_INIT, "enabled"],
            capture_output=True, text=True, timeout=5,
        )
        enabled = "enabled" if result.returncode == 0 else "disabled"
    except Exception:
        enabled = "unknown"

    return {"active": active, "enabled": enabled}


def service_action(action: str) -> dict:
    """Start/stop/restart cake-autorate via init.d."""
    if action not in ("start", "stop", "restart"):
        return {"error": f"invalid action: {action}"}
    try:
        result = subprocess.run(
            [AUTORATE_SERVICE_INIT, action],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip() or result.stdout.strip(), "returncode": result.returncode}
        return {"status": "ok", "action": action}
    except Exception as e:
        return {"error": str(e)}


# -- autorate config management --

def read_config() -> dict:
    """Read current tunable values from autorate config."""
    if not AUTORATE_CONFIG.exists():
        return {"error": "config file not found"}

    text = AUTORATE_CONFIG.read_text()
    values = {}
    for key in TUNABLE_CONFIG:
        m = re.search(rf"^{key}=(.+?)(?:\s*#.*)?$", text, re.MULTILINE)
        if m:
            raw = m.group(1).strip()
            try:
                values[key] = float(raw) if "." in raw else int(raw)
            except ValueError:
                values[key] = raw
    return values


def update_config(changes: dict) -> dict:
    """Update autorate config file with validated changes."""
    if not AUTORATE_CONFIG.exists():
        return {"error": "config file not found"}

    errors = {}
    valid = {}
    for key, val in changes.items():
        if key not in TUNABLE_CONFIG:
            errors[key] = f"unknown config key"
            continue
        lo, hi = TUNABLE_CONFIG[key]
        try:
            num = float(val)
        except (ValueError, TypeError):
            errors[key] = f"not a number"
            continue
        if not (lo <= num <= hi):
            errors[key] = f"out of range [{lo}, {hi}]"
            continue
        valid[key] = val

    if errors:
        return {"error": "validation failed", "details": errors}
    if not valid:
        return {"error": "no valid changes"}

    text = AUTORATE_CONFIG.read_text()
    applied = {}
    for key, val in valid.items():
        # Format: preserve .0 for float fields (delay thresholds)
        if key.endswith("_ms"):
            formatted = f"{float(val)}"
        else:
            formatted = str(int(val))
        pattern = rf"^({key}=)(.+?)(\s*#.*)?$"
        replacement = rf"\g<1>{formatted}\g<3>"
        new_text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
        if count > 0:
            text = new_text
            applied[key] = formatted

    AUTORATE_CONFIG.write_text(text)
    return {"status": "ok", "applied": applied, "note": "restart autorate to apply"}


# -- static CAKE rate control --

def read_static_rates() -> dict:
    """Read persisted static rate settings (not the live tc bandwidth)."""
    if STATIC_RATES_FILE.exists():
        try:
            return json.loads(STATIC_RATES_FILE.read_text())
        except Exception:
            pass
    return {"dl_rate_mbit": STATIC_DL_DEFAULT, "ul_rate_mbit": STATIC_UL_DEFAULT}


def _save_static_rates(dl_mbit: int, ul_mbit: int) -> None:
    """Persist static rate settings to disk."""
    STATIC_RATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATIC_RATES_FILE.write_text(json.dumps(
        {"dl_rate_mbit": dl_mbit, "ul_rate_mbit": ul_mbit}
    ))


def set_static_rates(dl_mbit: float, ul_mbit: float) -> dict:
    """Set static CAKE rates via apply-cake.sh (tc qdisc replace).

    Only meaningful when autorate is stopped — autorate will override
    these on its next cycle if it's running.
    """
    if not APPLY_CAKE_SCRIPT.exists():
        return {"error": "apply-cake.sh not found"}

    lo, hi = STATIC_DL_RANGE
    if not (lo <= dl_mbit <= hi):
        return {"error": f"dl_rate_mbit out of range [{lo}, {hi}]"}
    lo, hi = STATIC_UL_RANGE
    if not (lo <= ul_mbit <= hi):
        return {"error": f"ul_rate_mbit out of range [{lo}, {hi}]"}

    dl_int, ul_int = int(dl_mbit), int(ul_mbit)
    dl_arg = f"{dl_int}mbit"
    ul_arg = f"{ul_int}mbit"

    try:
        result = subprocess.run(
            [str(APPLY_CAKE_SCRIPT), dl_arg, ul_arg],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip(), "returncode": result.returncode}
        _save_static_rates(dl_int, ul_int)
        return {
            "status": "ok",
            "dl_rate_mbit": dl_int,
            "ul_rate_mbit": ul_int,
        }
    except Exception as e:
        return {"error": str(e)}


# -- helpers --

def _int(s: str) -> int:
    try:
        return int(s)
    except (ValueError, TypeError):
        return 0


# -- HTTP server --

def build_stats() -> dict:
    return {
        "cake": get_cake_qdiscs(),
        "autorate": get_autorate_state(),
        "service": get_service_state(),
        "static_rates": read_static_rates(),
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


class StatsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/stats":
            self._json_response(200, build_stats())
        elif self.path == "/health":
            self._json_response(200, {"status": "ok"})
        elif self.path == "/config":
            self._json_response(200, read_config())
        elif self.path == "/cake/rates":
            self._json_response(200, read_static_rates())
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/autorate/start":
            self._json_response(200, service_action("start"))
        elif self.path == "/autorate/stop":
            self._json_response(200, service_action("stop"))
        elif self.path == "/autorate/restart":
            self._json_response(200, service_action("restart"))
        elif self.path == "/config":
            body = self._read_body()
            if body is None:
                return
            result = update_config(body)
            code = 200 if result.get("status") == "ok" else 400
            self._json_response(code, result)
        elif self.path == "/cake/rates":
            body = self._read_body()
            if body is None:
                return
            dl = body.get("dl_rate_mbit")
            ul = body.get("ul_rate_mbit")
            if dl is None or ul is None:
                self._json_response(400, {"error": "dl_rate_mbit and ul_rate_mbit required"})
                return
            try:
                dl, ul = float(dl), float(ul)
            except (ValueError, TypeError):
                self._json_response(400, {"error": "dl_rate_mbit and ul_rate_mbit must be numbers"})
                return
            result = set_static_rates(dl, ul)
            code = 200 if result.get("status") == "ok" else 400
            self._json_response(code, result)
        else:
            self._json_response(404, {"error": "not found"})

    def _read_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self._json_response(400, {"error": "empty body"})
            return None
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError) as e:
            self._json_response(400, {"error": f"invalid JSON: {e}"})
            return None

    def _json_response(self, code: int, data: dict):
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def main():
    server = HTTPServer((LISTEN_ADDR, LISTEN_PORT), StatsHandler)
    print(f"cake-stats-exporter listening on {LISTEN_ADDR}:{LISTEN_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()


if __name__ == "__main__":
    main()
