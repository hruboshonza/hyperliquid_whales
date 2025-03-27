#!/usr/bin/env python3
"""
Script to analyze recently opened positions (last 15 minutes) across all whale wallets.
Shows a summary of newly opened long and short positions for each asset.
Excludes TWAP orders to focus on direct position openings.
Only tracks positions > $100,000 in value.
"""

import os
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import concurrent.futures
from collections import defaultdict
from dataclasses import dataclass
from tabulate import tabulate
import requests
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.position_tracker import PositionTracker
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants

@dataclass
class RecentAssetPosition:
    """Data class to hold recent position information for an asset."""
    asset: str = ""  # Default empty string
    new_long_count: int = 0
    new_short_count: int = 0
    closed_long_count: int = 0
    closed_short_count: int = 0
    total_new_long_size: float = 0.0
    total_new_short_size: float = 0.0
    total_closed_long_size: float = 0.0
    total_closed_short_size: float = 0.0
    total_new_long_value: float = 0.0
    total_new_short_value: float = 0.0
    total_closed_long_value: float = 0.0
    total_closed_short_value: float = 0.0
    whale_addresses: List[str] = None  # List of whale addresses that opened positions

    def __post_init__(self):
        self.whale_addresses = []

class RecentWhalePositionAnalyzer:
    """Analyze recently opened positions across all whale wallets."""
    
    def __init__(self):
        """Initialize the analyzer."""
        self.asset_positions = defaultdict(lambda: RecentAssetPosition(asset=""))
        self.processed_wallets = 0
        self.wallets_with_new_positions = 0
        self.MAX_WORKERS = 10  # Increased to 10 workers
        self.info = Info(hl_constants.MAINNET_API_URL)
        self.cutoff_time = datetime.now() - timedelta(minutes=15)
        self.session = requests.Session()
        self.lock = threading.Lock()  # Fixed: Using threading.Lock instead of concurrent.futures.Lock
        
    def make_request_with_retry(self, url: str, payload: dict, max_retries: int = 3) -> Optional[dict]:
        """Make a request with exponential backoff retry logic."""
        base_delay = 1  # Reduced base delay
        max_delay = 16  # Reduced max delay
        
        for attempt in range(max_retries):
            try:
                response = self.session.post(url, json=payload, headers={"Content-Type": "application/json"})
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:  # Rate limit
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.5), max_delay)
                    print(f"Rate limited. Waiting {delay:.1f} seconds before retry {attempt + 1}/{max_retries}")
                    time.sleep(delay)
                else:
                    print(f"Error response: {response.status_code} - {response.text}")
                    return None
                    
            except Exception as e:
                print(f"Request error: {str(e)}")
                if attempt < max_retries - 1:
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.5), max_delay)
                    time.sleep(delay)
                else:
                    return None
                    
        return None
        
    def get_recent_positions(self, whale_address: str) -> List[Dict]:
        """
        Get recently opened and closed positions for a whale address using the userFillsByTime endpoint.
        Excludes TWAP orders to focus on direct position openings and closings.
        Only tracks positions > $100,000 in value.
        """
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
                
                if abs(position_value) < 100000:  # Changed from 50000 to 100000
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
            
            time.sleep(0.5 + random.uniform(0, 0.5))  # Reduced delay
                
            return recent_positions
            
        except Exception as e:
            print(f"Error getting positions for {whale_address}: {str(e)}")
            return []
            
    def process_whale(self, whale_address: str) -> Dict:
        """Process a single whale's recent positions."""
        try:
            positions = self.get_recent_positions(whale_address)
            
            if not positions:
                return {}
                
            asset_positions = defaultdict(lambda: {
                'long': 0, 'short': 0,
                'closed_long': 0, 'closed_short': 0,
                'long_size': 0, 'short_size': 0,
                'closed_long_size': 0, 'closed_short_size': 0,
                'long_value': 0, 'short_value': 0,
                'closed_long_value': 0, 'closed_short_value': 0,
                'whale_addresses': []
            })
            
            MIN_POSITION_VALUE = 100000  # Changed from 50000 to 100000
            
            # Debug counters
            total_positions = 0
            filtered_positions = 0
            
            for position in positions:
                total_positions += 1
                asset = position['coin']
                size = position['size']
                value = position['position_value']
                
                if abs(value) < MIN_POSITION_VALUE:
                    continue
                    
                filtered_positions += 1
                    
                if position['is_long']:
                    if position['is_open']:
                        asset_positions[asset]['long'] += 1
                        asset_positions[asset]['long_size'] += size
                        asset_positions[asset]['long_value'] += value
                    else:
                        asset_positions[asset]['closed_long'] += 1
                        asset_positions[asset]['closed_long_size'] += size
                        asset_positions[asset]['closed_long_value'] += value
                else:
                    if position['is_open']:
                        asset_positions[asset]['short'] += 1
                        asset_positions[asset]['short_size'] += abs(size)
                        asset_positions[asset]['short_value'] += value
                    else:
                        asset_positions[asset]['closed_short'] += 1
                        asset_positions[asset]['closed_short_size'] += abs(size)
                        asset_positions[asset]['closed_short_value'] += value
                    
                if whale_address not in asset_positions[asset]['whale_addresses']:
                    asset_positions[asset]['whale_addresses'].append(whale_address)
            
            # Print debug information for this whale
            print(f"\nWhale {whale_address}:")
            print(f"Total positions found: {total_positions}")
            print(f"Positions after value filter: {filtered_positions}")
            for asset, pos in asset_positions.items():
                if pos['short'] > 0 or pos['long'] > 0:
                    print(f"  {asset}: {pos['short']} new shorts, {pos['long']} new longs")
                    
            return asset_positions
            
        except Exception as e:
            print(f"Error processing whale {whale_address}: {str(e)}")
            return {}
            
    def update_asset_positions(self, asset_positions: Dict):
        """Update the global asset positions with new data."""
        with self.lock:  # Use lock for thread safety
            for asset, positions in asset_positions.items():
                self.asset_positions[asset].new_long_count += positions['long']
                self.asset_positions[asset].new_short_count += positions['short']
                self.asset_positions[asset].closed_long_count += positions['closed_long']
                self.asset_positions[asset].closed_short_count += positions['closed_short']
                self.asset_positions[asset].total_new_long_size += positions['long_size']
                self.asset_positions[asset].total_new_short_size += positions['short_size']
                self.asset_positions[asset].total_closed_long_size += positions['closed_long_size']
                self.asset_positions[asset].total_closed_short_size += positions['closed_short_size']
                self.asset_positions[asset].total_new_long_value += positions['long_value']
                self.asset_positions[asset].total_new_short_value += positions['short_value']
                self.asset_positions[asset].total_closed_long_value += positions['closed_long_value']
                self.asset_positions[asset].total_closed_short_value += positions['closed_short_value']
                self.asset_positions[asset].whale_addresses.extend(positions['whale_addresses'])
            
    def display_top_positions(self):
        """Display top 10 most longed and shorted assets by new position value."""
        # Sort assets by new long value
        sorted_longs = sorted(
            self.asset_positions.items(),
            key=lambda x: x[1].total_new_long_value,
            reverse=True
        )[:10]
        
        # Sort assets by new short value
        sorted_shorts = sorted(
            self.asset_positions.items(),
            key=lambda x: x[1].total_new_short_value,
            reverse=True
        )[:10]
        
        print("\nTop 10 Most Longed Assets (New Positions in Last 15 Minutes, >$100k, Excluding TWAPs)")
        print("=" * 100)
        long_data = [[asset, f"${pos.total_new_long_value:,.2f}", 
                     f"{pos.total_new_long_size:,.2f}", pos.new_long_count,
                     pos.closed_long_count, len(set(pos.whale_addresses))] 
                     for asset, pos in sorted_longs]
        print(tabulate(long_data, 
                      headers=['Asset', 'Total New Long Value', 'Total New Long Size', 
                              'New Positions', 'Closed Positions', 'Number of Whales'],
                      tablefmt='grid'))
        
        print("\nTop 10 Most Shorted Assets (New Positions in Last 15 Minutes, >$100k, Excluding TWAPs)")
        print("=" * 100)
        short_data = [[asset, f"${pos.total_new_short_value:,.2f}", 
                      f"{pos.total_new_short_size:,.2f}", pos.new_short_count,
                      pos.closed_short_count, len(set(pos.whale_addresses))] 
                      for asset, pos in sorted_shorts]
        print(tabulate(short_data, 
                      headers=['Asset', 'Total New Short Value', 'Total New Short Size', 
                              'New Positions', 'Closed Positions', 'Number of Whales'],
                      tablefmt='grid'))
        
        # Calculate total new and closed positions
        total_new_long_positions = sum(pos.new_long_count for _, pos in self.asset_positions.items())
        total_new_short_positions = sum(pos.new_short_count for _, pos in self.asset_positions.items())
        total_closed_long_positions = sum(pos.closed_long_count for _, pos in self.asset_positions.items())
        total_closed_short_positions = sum(pos.closed_short_count for _, pos in self.asset_positions.items())
        
        print("\nPosition Summary:")
        print(f"Total New Long Positions: {total_new_long_positions}")
        print(f"Total New Short Positions: {total_new_short_positions}")
        print(f"Total Closed Long Positions: {total_closed_long_positions}")
        print(f"Total Closed Short Positions: {total_closed_short_positions}")

    def analyze_positions(self):
        """Analyze all whale positions using parallel processing."""
        start_time = datetime.now()
        
        # Get the correct path to activeWhales.json
        json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                'resources', 'activeWhales.json')
        
        with open(json_path, 'r') as f:
            active_whales = json.load(f)
            
        whale_addresses = [whale['fullAddress'] for whale in active_whales['wallets']]
        
        print(f"\nProcessing {len(whale_addresses)} whale addresses...")
        print(f"Analyzing positions opened in the last 15 minutes (since {self.cutoff_time})")
        print("Note: Only counting positions > $100,000 in value")
        print("Note: Excluding TWAP orders to focus on direct position openings")
        print("Note: Position values are calculated from fill data (entry price * size)")
        
        # Process whales in parallel
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            future_to_whale = {
                executor.submit(self.process_whale, address): address 
                for address in whale_addresses
            }
            
            for future in as_completed(future_to_whale):
                address = future_to_whale[future]
                try:
                    asset_positions = future.result()
                    if asset_positions:
                        self.update_asset_positions(asset_positions)
                        self.wallets_with_new_positions += 1
                    self.processed_wallets += 1
                except Exception as e:
                    print(f"Error processing whale {address}: {str(e)}")
        
        print("\n")  # New line after progress bar
        
        # Display results
        self.display_results()
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"\nSummary:")
        print(f"Total wallets processed: {self.processed_wallets}")
        print(f"Wallets with new positions: {self.wallets_with_new_positions}")
        print(f"Total assets with new positions: {len(self.asset_positions)}")
        print(f"Processing time: {duration:.2f} seconds")

    def display_results(self):
        """Display the analysis results."""
        # Prepare data for display
        table_data = []
        total_new_long_value = 0
        total_new_short_value = 0
        total_closed_long_value = 0
        total_closed_short_value = 0
        
        for asset, positions in sorted(self.asset_positions.items()):
            if positions.new_long_count > 0 or positions.new_short_count > 0 or \
               positions.closed_long_count > 0 or positions.closed_short_count > 0:
                table_data.append([
                    asset,
                    positions.new_long_count,
                    positions.new_short_count,
                    positions.closed_long_count,
                    positions.closed_short_count,
                    f"{positions.total_new_long_size:,.2f}",
                    f"{positions.total_new_short_size:,.2f}",
                    f"{positions.total_closed_long_size:,.2f}",
                    f"{positions.total_closed_short_size:,.2f}",
                    f"${positions.total_new_long_value:,.2f}",
                    f"${positions.total_new_short_value:,.2f}",
                    f"${positions.total_closed_long_value:,.2f}",
                    f"${positions.total_closed_short_value:,.2f}"
                ])
                total_new_long_value += positions.total_new_long_value
                total_new_short_value += positions.total_new_short_value
                total_closed_long_value += positions.total_closed_long_value
                total_closed_short_value += positions.total_closed_short_value
        
        # Display results
        print("\nWhale Position Analysis (Positions > $100,000 in Last 15 Minutes, Excluding TWAPs)")
        print("=" * 140)
        print(tabulate(table_data, 
                      headers=['Asset', 'New Long', 'New Short', 'Closed Long', 'Closed Short',
                              'New Long Size', 'New Short Size', 'Closed Long Size', 'Closed Short Size',
                              'New Long Value', 'New Short Value', 'Closed Long Value', 'Closed Short Value'],
                      tablefmt='grid'))
        
        # Display top positions
        self.display_top_positions()
        
        print(f"\nSummary:")
        print(f"Total new long value: ${total_new_long_value:,.2f}")
        print(f"Total new short value: ${total_new_short_value:,.2f}")
        print(f"Total closed long value: ${total_closed_long_value:,.2f}")
        print(f"Total closed short value: ${total_closed_short_value:,.2f}")

def main():
    analyzer = RecentWhalePositionAnalyzer()
    analyzer.analyze_positions()

if __name__ == "__main__":
    main() 