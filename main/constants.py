"""
Constants and configuration values for the Hyperliquid position tracking system.
"""

import os

class WhaleConfig:
    """Configuration for whale wallet detection and tracking."""
    
    # Minimum account value to consider a wallet as a whale (in USD)
    MIN_ACCOUNT_VALUE_USD = 100000
    
    # Minimum trade size to consider when discovering potential whales (in USD)
    MIN_TRADE_SIZE_USD = 10000
    
    # Path to store whale wallet data
    CACHE_FILE_PATH = os.path.join('resources', 'whale_wallets.json')

# File paths
WHALE_WALLETS_FILE = os.path.join('resources', 'whale_wallets.json')

# Trade monitoring settings
MIN_TRADE_VALUE = 10000.0  # Minimum trade value to display (in USD)
LOOKBACK_DAYS = 4  # Number of days to look back for trades 