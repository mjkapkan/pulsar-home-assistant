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
DEFAULT_HEARTBEAT_INTERVAL_S = 60
DEFAULT_FAILSAFE_AFTER_S = 900
DEFAULT_FAILSAFE_STATE = "on"
# Never poll faster than this, whatever the server asks for.
MIN_HEARTBEAT_INTERVAL_S = 10

STORAGE_VERSION = 1
# Results kept for the next heartbeat if Pulsar is unreachable for a while.
MAX_PENDING_RESULTS = 200
