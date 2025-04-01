#!/usr/bin/env python3
"""
Script to analyze open positions across all whale wallets.
Shows a summary of long and short positions for each asset.
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, List, Optional
import concurrent.futures
from collections import defaultdict
from dataclasses import dataclass
from tabulate import tabulate

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.position_tracker import PositionTracker
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants
from config import (
    MAX_WORKERS, ERROR_MESSAGES, SUCCESS_MESSAGES,
    DEBUG_MODE, TABLE_FORMAT, ADDRESS_DISPLAY_LENGTH
)

@dataclass
class AssetPosition:
    """Data class to hold position information for an asset."""
    asset: str = ""  # Default empty string
    long_count: int = 0
    short_count: int = 0
    total_long_size: float = 0.0
    total_short_size: float = 0.0
    total_long_value: float = 0.0
    total_short_value: float = 0.0

class WhalePositionAnalyzer:
    """Analyze positions across all whale wallets."""
    
    def __init__(self):
        """Initialize the analyzer."""
        self.asset_positions = defaultdict(lambda: AssetPosition(asset=""))  # Initialize with empty asset name
        self.processed_wallets = 0
        self.wallets_with_positions = 0
        self.MAX_WORKERS = MAX_WORKERS  # Number of concurrent workers
        self.info = Info(hl_constants.MAINNET_API_URL)
        
    def get_all_positions(self, whale_address: str) -> List[Dict]:
        """
        Get all open positions for a whale address.
        
        Args:
            whale_address (str): The whale address to get positions for
            
        Returns:
            List[Dict]: List of all open positions
        """
        all_positions = []
        
        try:
            user_state = self.info.user_state(whale_address)
            
            if isinstance(user_state, dict) and 'assetPositions' in user_state:
                for pos in user_state['assetPositions']:
                    position_data = pos.get('position', {})
                    coin = position_data.get('coin')
                    size = float(position_data.get('szi', 0))
                    
                    if size != 0:  # Only include non-zero positions
                        entry_price = float(position_data.get('entryPx', 0))
                        mark_price = float(position_data.get('markPx', 0))
                        position_value = float(position_data.get('positionValue', 0))
                        unrealized_pnl = float(position_data.get('unrealizedPnl', 0))
                        
                        position = {
                            'coin': coin,
                            'size': size,
                            'entry_price': entry_price,
                            'mark_price': mark_price,
                            'unrealized_pnl': unrealized_pnl,
                            'position_value': position_value,
                            'leverage': position_data.get('leverage', {'type': 'unknown', 'value': 0}),
                            'timestamp': datetime.now().isoformat()
                        }
                        all_positions.append(position)
                        
            return all_positions
            
        except Exception as e:
            print(f"Error getting positions for {whale_address}: {str(e)}")
            return []
            
    def process_whale(self, whale_address: str) -> Dict:
        """Process a single whale's positions."""
        try:
            positions = self.get_all_positions(whale_address)
            
            if not positions:
                return {}
                
            # Aggregate positions by asset
            asset_positions = defaultdict(lambda: {'long': 0, 'short': 0, 
                                                 'long_size': 0, 'short_size': 0,
                                                 'long_value': 0, 'short_value': 0})
            
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
                    
            return asset_positions
            
        except Exception as e:
            print(f"Error processing whale {whale_address}: {str(e)}")
            return {}
            
    def update_asset_positions(self, asset_positions: Dict):
        """Update the global asset positions with new data."""
        for asset, positions in asset_positions.items():
            self.asset_positions[asset].long_count += positions['long']
            self.asset_positions[asset].short_count += positions['short']
            self.asset_positions[asset].total_long_size += positions['long_size']
            self.asset_positions[asset].total_short_size += positions['short_size']
            self.asset_positions[asset].total_long_value += positions['long_value']
            self.asset_positions[asset].total_short_value += positions['short_value']
            
    def display_top_positions(self):
        """Display top 10 most longed and shorted assets by position value."""
        # Sort assets by long value
        sorted_longs = sorted(
            self.asset_positions.items(),
            key=lambda x: x[1].total_long_value,
            reverse=True
        )[:10]
        
        # Sort assets by short value
        sorted_shorts = sorted(
            self.asset_positions.items(),
            key=lambda x: x[1].total_short_value,
            reverse=True
        )[:10]
        
        print("\nTop 10 Most Longed Assets (by position value)")
        print("=" * 80)
        long_data = [[asset, f"${pos.total_long_value:,.2f}", 
                     f"{pos.total_long_size:,.2f}", pos.long_count] 
                     for asset, pos in sorted_longs]
        print(tabulate(long_data, 
                      headers=['Asset', 'Total Long Value', 'Total Long Size', 'Number of Positions'],
                      tablefmt='grid'))
        
        print("\nTop 10 Most Shorted Assets (by position value)")
        print("=" * 80)
        short_data = [[asset, f"${pos.total_short_value:,.2f}", 
                      f"{pos.total_short_size:,.2f}", pos.short_count] 
                      for asset, pos in sorted_shorts]
        print(tabulate(short_data, 
                      headers=['Asset', 'Total Short Value', 'Total Short Size', 'Number of Positions'],
                      tablefmt='grid'))
        
    def analyze_positions(self):
        """Analyze all whale positions using parallel processing."""
        start_time = datetime.now()
        
        # Read active whales from JSON file
        with open('resources/activeWhales.json', 'r') as f:
            active_whales = json.load(f)
            
        whale_addresses = [whale['fullAddress'] for whale in active_whales['wallets']]
        
        print(f"\nProcessing {len(whale_addresses)} whale addresses...")
        print("Note: Only counting positions > $100,000 in value")
        
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
                        self.wallets_with_positions += 1
                    self.processed_wallets += 1
                except Exception as e:
                    print(f"Error processing whale {address}: {str(e)}")
                    
        # Prepare data for display
        table_data = []
        total_long_value = 0
        total_short_value = 0
        
        for asset, positions in sorted(self.asset_positions.items()):
            if positions.long_count > 0 or positions.short_count > 0:
                table_data.append([
                    asset,
                    positions.long_count,
                    positions.short_count,
                    f"{positions.total_long_size:,.2f}",
                    f"{positions.total_short_size:,.2f}",
                    f"${positions.total_long_value:,.2f}",
                    f"${positions.total_short_value:,.2f}"
                ])
                total_long_value += positions.total_long_value
                total_short_value += positions.total_short_value
                
        # Display results
        print("\nWhale Position Analysis (Positions > $100,000)")
        print("=" * 100)
        print(tabulate(table_data, 
                      headers=['Asset', 'Long Count', 'Short Count', 
                              'Total Long Size', 'Total Short Size',
                              'Total Long Value', 'Total Short Value'],
                      tablefmt='grid'))
        
        # Display top positions
        self.display_top_positions()
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"\nSummary:")
        print(f"Total wallets processed: {self.processed_wallets}")
        print(f"Wallets with positions: {self.wallets_with_positions}")
        print(f"Total assets with positions: {len(table_data)}")
        print(f"Total long value: ${total_long_value:,.2f}")
        print(f"Total short value: ${total_short_value:,.2f}")
        print(f"Processing time: {duration:.2f} seconds")

def main():
    analyzer = WhalePositionAnalyzer()
    analyzer.analyze_positions()

if __name__ == "__main__":
    main() 