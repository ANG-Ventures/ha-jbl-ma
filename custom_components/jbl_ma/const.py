DOMAIN = "jbl_ma"
DEFAULT_PORT = 50000
DEFAULT_SCAN_INTERVAL = 30
# The MA7100's Ethernet link bounces for ~25 s at a time (switch port link down/up). Keep the last good
# status this long after the last successful poll instead of going unavailable: covers two missed polls.
STALE_GRACE_SECONDS = 90
# Commands retry the TCP connect this many times with backoff, so a command sent mid-bounce still lands.
COMMAND_CONNECT_ATTEMPTS = 4
CONF_PORT = "port"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SOURCES = "sources"
DEFAULT_SOURCES = ["HDMI1", "HDMI2", "HDMI3", "HDMI4", "HDMI5", "HDMI6", "HDMI7", "Coax", "Optical", "Analog1", "Analog2", "Phono", "Bluetooth", "Network"]
