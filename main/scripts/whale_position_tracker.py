#!/usr/bin/env python3
"""
Script to track individual whale positions with detailed timing and price information.
Shows exact entry points, position sizes, and mark prices for whale trades.
Excludes TWAP orders to focus on direct position openings.
Only tracks positions > $100,000 in value.
"""

import os
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import concurrent.futures
from dataclasses import dataclass
from tabulate import tabulate
import requests
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import atexit

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.position_tracker import PositionTracker
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants
from config import (
    TIME_PERIOD_HOURS, MIN_POSITION_VALUE, DEBUG_MODE,
    MAX_RETRIES, BASE_DELAY, MAX_DELAY, RATE_LIMIT_DELAY,
    MAX_WORKERS, POSITION_TYPES, ACTION_TYPES, ORDER_TYPES,
    ERROR_MESSAGES, SUCCESS_MESSAGES, TABLE_FORMAT
)

@dataclass
class WhalePosition:
    """Data class to hold detailed position information."""
    whale_address: str
    asset: str
    position_type: str  # "Long" or "Short"
    action: str  # "Open" or "Close"
    size: float
    mark_price: float
    position_value: float
    timestamp: datetime
    
    def __str__(self):
        return (f"{self.asset} {self.action} {self.position_type}: "
                f"${self.position_value:,.2f} @ ${self.mark_price:,.2f} "
                f"Size: {self.size:,.2f} "
                f"Time: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")

class WhalePositionTracker:
    """Track individual whale positions with detailed information."""
    
    def __init__(self):
        """Initialize the tracker."""
        self.positions = []
        self.processed_wallets = 0
        self.active_wallets = 0
        self.MAX_WORKERS = MAX_WORKERS
        self.info = Info(hl_constants.MAINNET_API_URL)
        
        # Use actual current time instead of rounding
        self.reference_time = datetime.now()
        self.cutoff_time = self.reference_time - timedelta(hours=TIME_PERIOD_HOURS)
        
        print(f"\nTracking Window:")
        print(f"Reference time: {self.reference_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Cutoff time: {self.cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Analysis period: {TIME_PERIOD_HOURS} hours\n")
        
        self.session = requests.Session()
        self.lock = threading.Lock()
        atexit.register(self.cleanup)
        
    def cleanup(self):
        """Clean up resources and close connections."""
        try:
            if hasattr(self, 'session'):
                self.session.close()
            if hasattr(self, 'info'):
                self.info.close()
        except Exception as e:
            print(f"Error during cleanup: {e}")
            
    def make_request_with_retry(self, url: str, payload: dict, max_retries: int = MAX_RETRIES) -> Optional[dict]:
        """Make a request with exponential backoff retry logic."""
        for attempt in range(max_retries):
            try:
                response = self.session.post(url, json=payload, headers={"Content-Type": "application/json"})
                
                if response.status_code == 200:
                    time.sleep(RATE_LIMIT_DELAY)  # Rate limiting prevention
                    return response.json()
                elif response.status_code == 429:  # Rate limit
                    delay = min(BASE_DELAY * (2 ** attempt) + random.uniform(0, 1), MAX_DELAY)
                    print(f"\rProgress: {self.processed_wallets}/{len(whale_addresses)} wallets processed", end="")
                    time.sleep(delay)
                else:
                    print(ERROR_MESSAGES["API_ERROR"].format(f"{response.status_code} - {response.text}"))
                    if attempt < max_retries - 1:
                        time.sleep(BASE_DELAY)
                    return None
                    
            except Exception as e:
                print(ERROR_MESSAGES["API_ERROR"].format(str(e)))
                if attempt < max_retries - 1:
                    delay = min(BASE_DELAY * (2 ** attempt) + random.uniform(0, 1), MAX_DELAY)
                    time.sleep(delay)
                else:
                    return None
                    
        return None
        
    def get_whale_positions(self, whale_address: str) -> List[WhalePosition]:
        """Get all positions for a whale address within the time window."""
        positions = []
        
        try:
            current_time = int(self.reference_time.timestamp() * 1000)
            cutoff_time = int(self.cutoff_time.timestamp() * 1000)
            
            if DEBUG_MODE:
                print(f"\nFetching positions for {whale_address}")
                print(f"Time window: {self.cutoff_time} to {self.reference_time}")
            
            url = f"{hl_constants.MAINNET_API_URL}/info"
            payload = {
                "type": "userFillsByTime",
                "user": whale_address,
                "startTime": cutoff_time,
                "endTime": current_time,
                "aggregateByTime": False
            }
            
            fills = self.make_request_with_retry(url, payload)
            if not fills:
                return positions
                
            # Track unique trades
            unique_trades = {}
            
            for fill in fills:
                if fill.get('orderType', '').lower() == 'twap':
                    continue
                    
                fill_time = fill.get('time')
                if not (cutoff_time <= fill_time <= current_time):
                    continue
                    
                coin = fill.get('coin')
                dir_str = fill.get('dir', '')
                size = float(fill.get('sz', 0))
                price = float(fill.get('px', 0))
                position_value = size * price
                
                if abs(position_value) < MIN_POSITION_VALUE:
                    continue
                    
                # Determine position type and action
                is_long = dir_str == 'Open Long' or dir_str == 'Close Short'
                position_type = 'Long' if is_long else 'Short'
                action = 'Open' if dir_str.startswith('Open') else 'Close'
                
                # Create unique identifier for the trade
                trade_key = f"{whale_address}_{coin}_{position_type}_{action}_{size}_{price}_{fill_time}"
                
                if trade_key not in unique_trades:
                    position = WhalePosition(
                        whale_address=whale_address,
                        asset=coin,
                        position_type=position_type,
                        action=action,
                        size=size,
                        mark_price=price,
                        position_value=position_value,
                        timestamp=datetime.fromtimestamp(fill_time/1000)
                    )
                    unique_trades[trade_key] = position
            
            positions = list(unique_trades.values())
            positions.sort(key=lambda x: x.timestamp)  # Sort by timestamp
            
            if DEBUG_MODE and positions:
                print(f"\nFound {len(positions)} positions for {whale_address}")
                for pos in positions:
                    print(str(pos))
            
            return positions
            
        except Exception as e:
            print(f"Error getting positions for {whale_address}: {str(e)}")
            return positions
            
    def process_whale(self, whale_address: str):
        """Process positions for a single whale."""
        positions = self.get_whale_positions(whale_address)
        if positions:
            with self.lock:
                self.positions.extend(positions)
                self.active_wallets += 1
        self.processed_wallets += 1
        
    def display_positions(self):
        """Display all tracked positions sorted by timestamp."""
        # Sort positions by timestamp
        sorted_positions = sorted(self.positions, key=lambda x: x.timestamp, reverse=True)
        
        # Prepare data for tabulate
        table_data = [
            [
                pos.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                pos.asset,
                f"{pos.action} {pos.position_type}",
                f"${pos.position_value:,.2f}",
                f"${pos.mark_price:,.2f}",
                f"{pos.size:,.2f}",
                pos.whale_address[:8] + "..."  # Show first 8 chars of address
            ]
            for pos in sorted_positions
        ]
        
        print("\nDetailed Whale Positions:")
        print("=" * 120)
        print(tabulate(
            table_data,
            headers=['Timestamp', 'Asset', 'Position', 'Value', 'Mark Price', 'Size', 'Whale'],
            tablefmt='grid'
        ))
        
        # Calculate detailed statistics
        total_value = sum(pos.position_value for pos in self.positions)
        
        # Open positions
        open_longs = [p for p in self.positions if p.action == 'Open' and p.position_type == 'Long']
        open_shorts = [p for p in self.positions if p.action == 'Open' and p.position_type == 'Short']
        open_long_value = sum(p.position_value for p in open_longs)
        open_short_value = sum(p.position_value for p in open_shorts)
        
        # Closed positions
        closed_longs = [p for p in self.positions if p.action == 'Close' and p.position_type == 'Long']
        closed_shorts = [p for p in self.positions if p.action == 'Close' and p.position_type == 'Short']
        closed_long_value = sum(p.position_value for p in closed_longs)
        closed_short_value = sum(p.position_value for p in closed_shorts)
        
        # Asset-specific statistics
        assets = set(pos.asset for pos in self.positions)
        asset_stats = []
        for asset in assets:
            asset_positions = [p for p in self.positions if p.asset == asset]
            asset_open_longs = sum(1 for p in asset_positions if p.action == 'Open' and p.position_type == 'Long')
            asset_open_shorts = sum(1 for p in asset_positions if p.action == 'Open' and p.position_type == 'Short')
            asset_closed_longs = sum(1 for p in asset_positions if p.action == 'Close' and p.position_type == 'Long')
            asset_closed_shorts = sum(1 for p in asset_positions if p.action == 'Close' and p.position_type == 'Short')
            asset_stats.append([
                asset,
                asset_open_longs,
                asset_open_shorts,
                asset_closed_longs,
                asset_closed_shorts,
                len(asset_positions)
            ])
        
        # Display position value summary
        print("\nPosition Value Summary:")
        print("=" * 60)
        print(f"Total Open Long Value:    ${open_long_value:,.2f}")
        print(f"Total Open Short Value:   ${open_short_value:,.2f}")
        print(f"Total Closed Long Value:  ${closed_long_value:,.2f}")
        print(f"Total Closed Short Value: ${closed_short_value:,.2f}")
        print(f"Total Position Value:     ${total_value:,.2f}")
        
        # Display position count summary
        print("\nPosition Count Summary:")
        print("=" * 60)
        print(f"Open Long Positions:    {len(open_longs)}")
        print(f"Open Short Positions:   {len(open_shorts)}")
        print(f"Closed Long Positions:  {len(closed_longs)}")
        print(f"Closed Short Positions: {len(closed_shorts)}")
        print(f"Total Positions:        {len(self.positions)}")
        
        # Display asset-specific summary
        print("\nAsset-Specific Summary:")
        print("=" * 100)
        print(tabulate(
            sorted(asset_stats, key=lambda x: x[5], reverse=True),
            headers=['Asset', 'Open Longs', 'Open Shorts', 'Closed Longs', 'Closed Shorts', 'Total Positions'],
            tablefmt='grid'
        ))
        
        # Display general statistics
        print(f"\nGeneral Statistics:")
        print("=" * 60)
        print(f"Active Wallets:         {self.active_wallets}")
        print(f"Total Wallets Analyzed: {self.processed_wallets}")
        print(f"Average Position Value: ${total_value/len(self.positions):,.2f}" if self.positions else "No positions found")
        
    def track_positions(self):
        """Track all whale positions using parallel processing."""
        start_time = datetime.now()
        
        # Get whale addresses from JSON file
        json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                'resources', 'activeWhales.json')
        
        with open(json_path, 'r') as f:
            active_whales = json.load(f)
            
        whale_addresses = [whale['fullAddress'] for whale in active_whales['wallets']]
        
        print(f"Processing {len(whale_addresses)} whale addresses...")
        print(f"Tracking positions in the last {TIME_PERIOD_HOURS} hours")
        print(f"Minimum position value: ${MIN_POSITION_VALUE:,}")
        
        # Process whales in parallel
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            future_to_whale = {
                executor.submit(self.process_whale, address): address 
                for address in whale_addresses
            }
            
            completed = 0
            for future in as_completed(future_to_whale):
                completed += 1
                print(f"\rProgress: {completed}/{len(whale_addresses)} wallets processed", end="")
                if completed % 5 == 0:
                    time.sleep(1)  # Rate limiting
                    
        print("\n")  # New line after progress
        
        # Display results
        self.display_positions()
        
        # Display processing time
        duration = (datetime.now() - start_time).total_seconds()
        print(f"\nProcessing time: {duration:.2f} seconds")

def main():
    try:
        tracker = WhalePositionTracker()
        tracker.track_positions()
    except KeyboardInterrupt:
        print("\nScript interrupted by user. Cleaning up...")
    except Exception as e:
        print(f"\nError during execution: {e}")
    finally:
        # Cleanup will be handled by atexit handler
        pass

if __name__ == "__main__":
    main() 