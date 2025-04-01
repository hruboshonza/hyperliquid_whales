"""
Configuration file for the Hyperliquid Whales project.
Contains all constants, API endpoints, and project settings.
"""

# API Configuration
MAINNET_API_URL = "https://api.hyperliquid.xyz"
TESTNET_API_URL = "https://api.testnet.hyperliquid.xyz"

# Time and Analysis Settings
TIME_PERIOD_HOURS = 2  # Time period to analyze in hours
MIN_POSITION_VALUE = 100000  # Minimum position value to track in USD

# Debug and Logging
DEBUG_MODE = False  # Set to True to see detailed debug messages
LOG_LEVEL = "INFO"  # Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

# Rate Limiting and Request Settings
MAX_RETRIES = 5
BASE_DELAY = 2  # Base delay for exponential backoff
MAX_DELAY = 30  # Maximum delay for exponential backoff
REQUEST_TIMEOUT = 30  # Request timeout in seconds
RATE_LIMIT_DELAY = 0.5  # Delay between requests to prevent rate limiting

# Threading and Processing
MAX_WORKERS = 5  # Maximum number of concurrent workers
BATCH_SIZE = 100  # Number of items to process in each batch

# File Paths
RESOURCES_DIR = "resources"
ACTIVE_WHALES_FILE = "activeWhales.json"

# Position Tracking Settings
EXCLUDE_TWAP_ORDERS = True  # Whether to exclude TWAP orders from tracking
POSITION_SORT_ORDER = "desc"  # Sort order for positions (asc/desc)

# Display Settings
ADDRESS_DISPLAY_LENGTH = 8  # Number of characters to display for wallet addresses
TABLE_FORMAT = "grid"  # Format for tabulated output

# Dependencies and Versions
REQUIRED_PACKAGES = {
    "requests": ">=2.31.0",
    "tabulate": ">=0.9.0",
    "python-dateutil": ">=2.8.2",
    "typing": ">=3.7.4.3",
    "dataclasses": ">=0.6",
    "concurrent-futures": ">=3.0.5",
    "websocket-client": ">=1.5.1",
    "argparse": ">=1.4.0",
    "functools": ">=0.1.0"
}

# Position Types
POSITION_TYPES = {
    "LONG": "Long",
    "SHORT": "Short"
}

# Action Types
ACTION_TYPES = {
    "OPEN": "Open",
    "CLOSE": "Close"
}

# Order Types
ORDER_TYPES = {
    "TWAP": "TWAP",
    "MARKET": "Market",
    "LIMIT": "Limit"
}

# Error Messages
ERROR_MESSAGES = {
    "API_ERROR": "API request failed: {}",
    "RATE_LIMIT": "Rate limit exceeded. Waiting {} seconds before retry",
    "INVALID_RESPONSE": "Invalid response from API: {}",
    "FILE_NOT_FOUND": "Required file not found: {}",
    "INVALID_DATA": "Invalid data format: {}"
}

# Success Messages
SUCCESS_MESSAGES = {
    "PROCESSING_COMPLETE": "Processing completed successfully",
    "POSITIONS_FOUND": "Found {} positions for wallet {}",
    "FILE_LOADED": "Successfully loaded {}"
} 