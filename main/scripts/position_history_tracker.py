#!/usr/bin/env python3
"""
Script to track position changes hourly for specified assets.
Stores historical data about long/short positions and wallet counts.
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import threading
from dataclasses import dataclass
import requests
import random
from collections import defaultdict

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants
from config import (
    MAX_RETRIES, BASE_DELAY, MAX_DELAY, RATE_LIMIT_DELAY,
    ERROR_MESSAGES, SUCCESS_MESSAGES, DEBUG_MODE
)

@dataclass
class AssetSnapshot:
    """Data class to hold position snapshot for an asset."""
    timestamp: datetime
    long_wallets: int
    short_wallets: int
    total_long_value: float
    total_short_value: float
    total_long_size: float
    total_short_size: float
    new_long_positions: int
    new_short_positions: int
    closed_long_positions: int
    closed_short_positions: int

class PositionHistoryTracker:
    """Tracks position changes hourly for specified assets."""
    
    def __init__(self, assets: List[str], history_file: str = "position_history.json"):
        """Initialize the tracker."""
        self.assets = [asset.upper() for asset in assets]
        self.history_file = history_file
        self.info = Info(hl_constants.MAINNET_API_URL)
        self.session = requests.Session()
        self.cutoff_time = datetime.now() - timedelta(hours=1)
        self.history: Dict[str, List[AssetSnapshot]] = defaultdict(list)
        self.load_history()
        
    def load_history(self):
        """Load historical data from file if it exists."""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    for asset, snapshots in data.items():
                        self.history[asset] = [
                            AssetSnapshot(
                                timestamp=datetime.fromisoformat(s['timestamp']),
                                long_wallets=s['long_wallets'],
                                short_wallets=s['short_wallets'],
                                total_long_value=s['total_long_value'],
                                total_short_value=s['total_short_value'],
                                total_long_size=s['total_long_size'],
                                total_short_size=s['total_short_size'],
                                new_long_positions=s['new_long_positions'],
                                new_short_positions=s['new_short_positions'],
                                closed_long_positions=s['closed_long_positions'],
                                closed_short_positions=s['closed_short_positions']
                            )
                            for s in snapshots
                        ]
        except Exception as e:
            print(f"Error loading history: {e}")
            
    def save_history(self):
        """Save historical data to file."""
        try:
            data = {
                asset: [
                    {
                        'timestamp': s.timestamp.isoformat(),
                        'long_wallets': s.long_wallets,
                        'short_wallets': s.short_wallets,
                        'total_long_value': s.total_long_value,
                        'total_short_value': s.total_short_value,
                        'total_long_size': s.total_long_size,
                        'total_short_size': s.total_short_size,
                        'new_long_positions': s.new_long_positions,
                        'new_short_positions': s.new_short_positions,
                        'closed_long_positions': s.closed_long_positions,
                        'closed_short_positions': s.closed_short_positions
                    }
                    for s in snapshots
                ]
                for asset, snapshots in self.history.items()
            }
            with open(self.history_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving history: {e}")
            
    def make_request_with_retry(self, url: str, payload: dict, max_retries: int = MAX_RETRIES) -> Optional[dict]:
        """Make a request with exponential backoff retry logic."""
        for attempt in range(max_retries):
            try:
                response = self.session.post(url, json=payload, headers={"Content-Type": "application/json"})
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:  # Rate limit
                    delay = min(BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5), MAX_DELAY)
                    print(f"\rProgress: {self.processed_wallets}/{len(whale_addresses)} wallets processed", end="")
                    time.sleep(delay)
                else:
                    print(ERROR_MESSAGES["API_ERROR"].format(f"{response.status_code} - {response.text}"))
                    return None
                    
            except Exception as e:
                print(ERROR_MESSAGES["API_ERROR"].format(str(e)))
                if attempt < max_retries - 1:
                    delay = min(BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5), MAX_DELAY)
                    time.sleep(delay)
                else:
                    return None
                    
        return None
        
    def get_recent_positions(self, whale_address: str) -> List[Dict]:
        """Get recently opened and closed positions for a whale address."""
        recent_positions = []
        
        try:
            current_time = int(datetime.now().timestamp() * 1000)
            cutoff_time = int(self.cutoff_time.timestamp() * 1000)
            
            url = f"{hl_constants.MAINNET_API_URL}/info"
            payload = {
                "type": "userFillsByTime",
                "user": whale_address,
                "startTime": cutoff_time,
                "endTime": current_time,
                "aggregateByTime": True
            }
            
            fills = self.make_request_with_retry(url, payload)
            if not fills:
                return []
            
            for fill in fills:
                if fill.get('orderType', '').lower() == 'twap':
                    continue
                    
                coin = fill.get('coin')
                dir_str = fill.get('dir', '')
                
                size = float(fill.get('sz', 0))
                price = float(fill.get('px', 0))
                position_value = size * price
                
                if abs(position_value) < 100000:  # Skip small positions
                    continue
                
                is_long = dir_str == 'Open Long' or dir_str == 'Close Short'
                is_short = dir_str == 'Open Short' or dir_str == 'Close Long'
                
                if is_long or is_short:
                    recent_positions.append({
                        'coin': coin,
                        'size': size if is_long else -size,
                        'entry_price': price,
                        'position_value': position_value,
                        'timestamp': fill.get('time'),
                        'is_open': dir_str.startswith('Open'),
                        'is_long': is_long
                    })
            
            time.sleep(0.5 + random.uniform(0, 0.5))  # Rate limiting
                
            return recent_positions
            
        except Exception as e:
            print(f"Error getting positions for {whale_address}: {str(e)}")
            return []
            
    def get_current_positions(self, whale_address: str) -> List[Dict]:
        """Get current positions for a whale address."""
        try:
            user_state = self.info.user_state(whale_address)
            positions = []
            
            if not isinstance(user_state, dict) or 'assetPositions' not in user_state:
                return positions
                
            for pos in user_state['assetPositions']:
                position_data = pos.get('position', {})
                coin = position_data.get('coin')
                
                if coin not in self.assets:  # Skip positions for other assets
                    continue
                    
                size = float(position_data.get('szi', 0))
                if size == 0:  # Skip zero-size positions
                    continue
                    
                entry_price = float(position_data.get('entryPx', 0))
                position_value = abs(size * entry_price)
                
                # Skip positions smaller than $100,000
                if position_value < 100000:
                    continue
                    
                positions.append({
                    'coin': coin,
                    'size': size,
                    'entry_price': entry_price,
                    'position_value': position_value
                })
            
            return positions
        except Exception as e:
            print(f"Error getting current positions for {whale_address}: {str(e)}")
            return []
            
    def analyze_asset(self, asset: str, whale_addresses: List[str]) -> AssetSnapshot:
        """Analyze positions for a specific asset."""
        long_wallets = set()
        short_wallets = set()
        total_long_value = 0
        total_short_value = 0
        total_long_size = 0
        total_short_size = 0
        new_long_positions = 0
        new_short_positions = 0
        closed_long_positions = 0
        closed_short_positions = 0
        
        for whale_address in whale_addresses:
            # Get current positions
            current_positions = self.get_current_positions(whale_address)
            for pos in current_positions:
                if pos['coin'] == asset:
                    if pos['size'] > 0:
                        long_wallets.add(whale_address)
                        total_long_value += pos['position_value']
                        total_long_size += pos['size']
                    else:
                        short_wallets.add(whale_address)
                        total_short_value += pos['position_value']
                        total_short_size += abs(pos['size'])
            
            # Get recent position changes
            recent_positions = self.get_recent_positions(whale_address)
            for pos in recent_positions:
                if pos['coin'] == asset:
                    if pos['is_long']:
                        if pos['is_open']:
                            new_long_positions += 1
                        else:
                            closed_long_positions += 1
                    else:
                        if pos['is_open']:
                            new_short_positions += 1
                        else:
                            closed_short_positions += 1
            
            time.sleep(0.1)  # Rate limiting
            
        return AssetSnapshot(
            timestamp=datetime.now(),
            long_wallets=len(long_wallets),
            short_wallets=len(short_wallets),
            total_long_value=total_long_value,
            total_short_value=total_short_value,
            total_long_size=total_long_size,
            total_short_size=total_short_size,
            new_long_positions=new_long_positions,
            new_short_positions=new_short_positions,
            closed_long_positions=closed_long_positions,
            closed_short_positions=closed_short_positions
        )
        
    def take_snapshot(self):
        """Take a snapshot of current positions for all assets."""
        try:
            # Get whale addresses from activeWhales.json
            json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                    'resources', 'activeWhales.json')
            
            with open(json_path, 'r') as f:
                active_whales = json.load(f)
                
            whale_addresses = [whale['fullAddress'] for whale in active_whales['wallets']]
            
            print(f"\nTaking snapshot at {datetime.now()}")
            print(f"Processing {len(whale_addresses)} whale addresses...")
            
            # Analyze each asset
            for asset in self.assets:
                print(f"\nAnalyzing {asset}...")
                snapshot = self.analyze_asset(asset, whale_addresses)
                self.history[asset].append(snapshot)
                
                # Keep only last 24 snapshots (24 hours)
                if len(self.history[asset]) > 24:
                    self.history[asset] = self.history[asset][-24:]
                
                # Print summary
                print(f"Long wallets: {snapshot.long_wallets}")
                print(f"Short wallets: {snapshot.short_wallets}")
                print(f"Total long value: ${snapshot.total_long_value:,.2f}")
                print(f"Total short value: ${snapshot.total_short_value:,.2f}")
                print(f"New long positions: {snapshot.new_long_positions}")
                print(f"New short positions: {snapshot.new_short_positions}")
                print(f"Closed long positions: {snapshot.closed_long_positions}")
                print(f"Closed short positions: {snapshot.closed_short_positions}")
            
            # Save history to file
            self.save_history()
            
        except Exception as e:
            print(f"Error taking snapshot: {e}")
            
    def run_continuously(self, interval_hours: float = 1.0):
        """Run the tracker continuously with specified interval."""
        while True:
            self.take_snapshot()
            time.sleep(interval_hours * 3600)  # Convert hours to seconds

def main():
    # Initialize tracker with BTC, ETH, and SOL
    tracker = PositionHistoryTracker(['BTC', 'ETH', 'SOL'])
    
    # Take initial snapshot
    tracker.take_snapshot()
    
    # Run continuously
    tracker.run_continuously()

if __name__ == "__main__":
    main() 