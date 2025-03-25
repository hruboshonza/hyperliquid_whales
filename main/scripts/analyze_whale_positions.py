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
        self.MAX_WORKERS = 10  # Number of concurrent workers
        
    def process_whale_file(self, file_path: str) -> Dict:
        """Process a single whale's position file."""
        try:
            with open(file_path, 'r') as f:
                whale_data = json.load(f)
                
            if not whale_data.get('positions'):
                return {}
                
            # Aggregate positions by asset
            asset_positions = defaultdict(lambda: {'long': 0, 'short': 0, 
                                                 'long_size': 0, 'short_size': 0,
                                                 'long_value': 0, 'short_value': 0})
            
            MIN_POSITION_VALUE = 100000  # Minimum position value to count
            
            for position in whale_data['positions']:
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
            print(f"Error processing file {file_path}: {str(e)}")
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
            
    def analyze_positions(self):
        """Analyze all whale positions using parallel processing."""
        start_time = datetime.now()
        
        # Get list of all whale position files
        whale_trades_dir = "resources/whale_trades"
        if not os.path.exists(whale_trades_dir):
            print(f"Error: Directory {whale_trades_dir} not found")
            return
            
        position_files = [f for f in os.listdir(whale_trades_dir) 
                         if f.endswith('.json') and f != 'all_whale_trades.json']
        
        print(f"\nProcessing {len(position_files)} whale position files...")
        print("Note: Only counting positions > $100,000 in value")
        
        # Process files in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            future_to_file = {
                executor.submit(self.process_whale_file, 
                              os.path.join(whale_trades_dir, file)): file 
                for file in position_files
            }
            
            for future in concurrent.futures.as_completed(future_to_file):
                file = future_to_file[future]
                try:
                    asset_positions = future.result()
                    if asset_positions:
                        self.update_asset_positions(asset_positions)
                        self.wallets_with_positions += 1
                    self.processed_wallets += 1
                except Exception as e:
                    print(f"Error processing {file}: {str(e)}")
                    
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