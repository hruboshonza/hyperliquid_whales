#!/usr/bin/env python3
"""
Script to analyze recently opened positions (last 24h) across all whale wallets.
Shows a summary of newly opened long and short positions for each asset.
Excludes TWAP orders to focus on direct position openings.
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
    total_new_long_size: float = 0.0
    total_new_short_size: float = 0.0
    total_new_long_value: float = 0.0
    total_new_short_value: float = 0.0
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
        self.MAX_WORKERS = 3  # Reduced to 3 to avoid rate limiting
        self.info = Info(hl_constants.MAINNET_API_URL)
        self.cutoff_time = datetime.now() - timedelta(hours=24)
        self.session = requests.Session()
        
    def make_request_with_retry(self, url: str, payload: dict, max_retries: int = 3) -> Optional[dict]:
        """Make a request with exponential backoff retry logic."""
        base_delay = 2  # Base delay in seconds
        max_delay = 32  # Maximum delay in seconds
        
        for attempt in range(max_retries):
            try:
                response = self.session.post(url, json=payload, headers={"Content-Type": "application/json"})
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:  # Rate limit
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    print(f"Rate limited. Waiting {delay:.1f} seconds before retry {attempt + 1}/{max_retries}")
                    time.sleep(delay)
                else:
                    print(f"Error response: {response.status_code} - {response.text}")
                    return None
                    
            except Exception as e:
                print(f"Request error: {str(e)}")
                if attempt < max_retries - 1:
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    time.sleep(delay)
                else:
                    return None
                    
        return None
        
    def get_recent_positions(self, whale_address: str) -> List[Dict]:
        """
        Get recently opened positions for a whale address using the userFillsByTime endpoint.
        Excludes TWAP orders to focus on direct position openings.
        
        Args:
            whale_address (str): The whale address to get positions for
            
        Returns:
            List[Dict]: List of recently opened positions
        """
        recent_positions = []
        
        try:
            # Get current timestamp in milliseconds
            current_time = int(datetime.now().timestamp() * 1000)
            cutoff_time = int(self.cutoff_time.timestamp() * 1000)
            
            # Prepare request for userFillsByTime endpoint
            url = f"{hl_constants.MAINNET_API_URL}/info"
            payload = {
                "type": "userFillsByTime",
                "user": whale_address,
                "startTime": cutoff_time,
                "endTime": current_time,
                "aggregateByTime": True
            }
            
            # Make request to get fills with retry logic
            fills = self.make_request_with_retry(url, payload)
            if not fills:
                return []
            
            # Process fills to identify position openings
            for fill in fills:
                # Skip TWAP orders
                if fill.get('orderType', '').lower() == 'twap':
                    continue
                    
                coin = fill.get('coin')
                dir_str = fill.get('dir', '')
                
                # Only consider position openings
                if not dir_str.startswith('Open'):
                    continue
                    
                size = float(fill.get('sz', 0))
                price = float(fill.get('px', 0))
                
                # Calculate position value from the fill data
                position_value = size * price
                
                # Skip if position value is too small
                if abs(position_value) < 100000:
                    continue
                
                recent_positions.append({
                    'coin': coin,
                    'size': size if dir_str == 'Open Long' else -size,
                    'entry_price': price,
                    'position_value': position_value,
                    'timestamp': fill.get('time')
                })
            
            # Add a longer delay between requests
            time.sleep(2 + random.uniform(0, 1))
                
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
                
            # Aggregate positions by asset
            asset_positions = defaultdict(lambda: {
                'long': 0, 'short': 0,
                'long_size': 0, 'short_size': 0,
                'long_value': 0, 'short_value': 0,
                'whale_addresses': []
            })
            
            MIN_POSITION_VALUE = 100000  # Minimum position value to count
            
            for position in positions:
                asset = position['coin']
                size = position['size']
                value = position['position_value']
                
                # Only count positions > $100,000
                if abs(value) < MIN_POSITION_VALUE:
                    continue
                    
                if size > 0:
                    asset_positions[asset]['long'] += 1
                    asset_positions[asset]['long_size'] += size
                    asset_positions[asset]['long_value'] += value
                else:
                    asset_positions[asset]['short'] += 1
                    asset_positions[asset]['short_size'] += abs(size)
                    asset_positions[asset]['short_value'] += value
                    
                # Add whale address to the list if not already present
                if whale_address not in asset_positions[asset]['whale_addresses']:
                    asset_positions[asset]['whale_addresses'].append(whale_address)
                    
            return asset_positions
            
        except Exception as e:
            print(f"Error processing whale {whale_address}: {str(e)}")
            return {}
            
    def update_asset_positions(self, asset_positions: Dict):
        """Update the global asset positions with new data."""
        for asset, positions in asset_positions.items():
            self.asset_positions[asset].new_long_count += positions['long']
            self.asset_positions[asset].new_short_count += positions['short']
            self.asset_positions[asset].total_new_long_size += positions['long_size']
            self.asset_positions[asset].total_new_short_size += positions['short_size']
            self.asset_positions[asset].total_new_long_value += positions['long_value']
            self.asset_positions[asset].total_new_short_value += positions['short_value']
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
        
        print("\nTop 10 Most Longed Assets (New Positions in Last 24h, Excluding TWAPs)")
        print("=" * 80)
        long_data = [[asset, f"${pos.total_new_long_value:,.2f}", 
                     f"{pos.total_new_long_size:,.2f}", pos.new_long_count,
                     len(set(pos.whale_addresses))] 
                     for asset, pos in sorted_longs]
        print(tabulate(long_data, 
                      headers=['Asset', 'Total New Long Value', 'Total New Long Size', 
                              'Number of New Positions', 'Number of Whales'],
                      tablefmt='grid'))
        
        print("\nTop 10 Most Shorted Assets (New Positions in Last 24h, Excluding TWAPs)")
        print("=" * 80)
        short_data = [[asset, f"${pos.total_new_short_value:,.2f}", 
                      f"{pos.total_new_short_size:,.2f}", pos.new_short_count,
                      len(set(pos.whale_addresses))] 
                      for asset, pos in sorted_shorts]
        print(tabulate(short_data, 
                      headers=['Asset', 'Total New Short Value', 'Total New Short Size', 
                              'Number of New Positions', 'Number of Whales'],
                      tablefmt='grid'))
        
    def analyze_positions(self):
        """Analyze all whale positions using parallel processing."""
        start_time = datetime.now()
        
        # Read active whales from JSON file
        with open('resources/activeWhales.json', 'r') as f:
            active_whales = json.load(f)
            
        whale_addresses = [whale['fullAddress'] for whale in active_whales['wallets']]
        
        print(f"\nProcessing {len(whale_addresses)} whale addresses...")
        print(f"Analyzing positions opened in the last 24 hours (since {self.cutoff_time})")
        print("Note: Only counting positions > $100,000 in value")
        print("Note: Excluding TWAP orders to focus on direct position openings")
        print("Note: Position values are calculated from fill data (entry price * size)")
        
        # Process whales in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            future_to_whale = {
                executor.submit(self.process_whale, address): address 
                for address in whale_addresses
            }
            
            for future in concurrent.futures.as_completed(future_to_whale):
                address = future_to_whale[future]
                try:
                    asset_positions = future.result()
                    if asset_positions:
                        self.update_asset_positions(asset_positions)
                        self.wallets_with_new_positions += 1
                    self.processed_wallets += 1
                    print(f"Processed {self.processed_wallets}/{len(whale_addresses)} wallets")
                except Exception as e:
                    print(f"Error processing whale {address}: {str(e)}")
                    
        # Prepare data for display
        table_data = []
        total_new_long_value = 0
        total_new_short_value = 0
        
        for asset, positions in sorted(self.asset_positions.items()):
            if positions.new_long_count > 0 or positions.new_short_count > 0:
                table_data.append([
                    asset,
                    positions.new_long_count,
                    positions.new_short_count,
                    f"{positions.total_new_long_size:,.2f}",
                    f"{positions.total_new_short_size:,.2f}",
                    f"${positions.total_new_long_value:,.2f}",
                    f"${positions.total_new_short_value:,.2f}"
                ])
                total_new_long_value += positions.total_new_long_value
                total_new_short_value += positions.total_new_short_value
                
        # Display results
        print("\nWhale Position Analysis (New Positions > $100,000 in Last 24h, Excluding TWAPs)")
        print("=" * 100)
        print(tabulate(table_data, 
                      headers=['Asset', 'New Long Count', 'New Short Count', 
                              'Total New Long Size', 'Total New Short Size',
                              'Total New Long Value', 'Total New Short Value'],
                      tablefmt='grid'))
        
        # Display top positions
        self.display_top_positions()
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"\nSummary:")
        print(f"Total wallets processed: {self.processed_wallets}")
        print(f"Wallets with new positions: {self.wallets_with_new_positions}")
        print(f"Total assets with new positions: {len(table_data)}")
        print(f"Total new long value: ${total_new_long_value:,.2f}")
        print(f"Total new short value: ${total_new_short_value:,.2f}")
        print(f"Processing time: {duration:.2f} seconds")

def main():
    analyzer = RecentWhalePositionAnalyzer()
    analyzer.analyze_positions()

if __name__ == "__main__":
    main() 