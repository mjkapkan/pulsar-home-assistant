"""Constants for the Pulsar integration."""

DOMAIN = "sun_driven_pulsar"

DEFAULT_URL = "https://pulsar.sun-driven.com"

CONF_URL = "url"
CONF_PAIRING_CODE = "pairing_code"
CONF_API_KEY = "api_key"
CONF_INSTALLATION_ID = "installation_id"

# Entity domains Pulsar can switch with turn_on / turn_off.
SWITCHABLE_DOMAINS = ("switch", "light", "fan", "input_boolean")

# Used until Pulsar's first reply says otherwise.
DEFAULT_HEARTBEAT_INTERVAL_S = 5
DEFAULT_FAILSAFE_AFTER_S = 900
DEFAULT_FAILSAFE_STATE = "on"
# Never poll faster than this, whatever the server asks for.
MIN_HEARTBEAT_INTERVAL_S = 5
# After switching something, report back this soon instead of waiting for
# the next heartbeat, so the Pulsar app confirms the change quickly.
REPORT_AFTER_SWITCH_S = 1.0

# A watched sensor (report_on_change) triggers a heartbeat at most this often.
MIN_REPORT_INTERVAL_S = 1.0

STORAGE_VERSION = 1
# Results kept for the next heartbeat if Pulsar is unreachable for a while.
MAX_PENDING_RESULTS = 200
# What one heartbeat reports at most (Pulsar's limits).
MAX_ENTITIES = 1000
MAX_METERS = 200
MAX_WATCHED = 50
