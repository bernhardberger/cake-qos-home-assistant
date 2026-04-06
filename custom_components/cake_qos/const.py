"""Constants for the CAKE QoS integration."""

DOMAIN = "cake_qos"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_HOST = "192.168.8.1"
DEFAULT_PORT = 9101
DEFAULT_SCAN_INTERVAL = 5   # seconds — configurable via options flow (2–60s)
MIN_SCAN_INTERVAL = 2
MAX_SCAN_INTERVAL = 60
