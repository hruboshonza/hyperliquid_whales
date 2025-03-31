#!/usr/bin/env python3
"""
Script to analyze recently opened positions (last 24 hours) across all whale wallets.
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
import atexit

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.position_tracker import PositionTracker
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants

# Configuration
TIME_PERIOD_HOURS = 4  # Time period to analyze in hours
MIN_POSITION_VALUE = 100000  # Minimum position value to track in USD
DEBUG_MODE = False  # Set to True to see detailed debug messages

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
    long_whales: set = None  # Set of whale addresses that opened long positions
    short_whales: set = None  # Set of whale addresses that opened short positions
    closed_long_whales: set = None  # Set of whale addresses that closed long positions
    closed_short_whales: set = None  # Set of whale addresses that closed short positions

    def __post_init__(self):
        self.long_whales = set()
        self.short_whales = set()
        self.closed_long_whales = set()
        self.closed_short_whales = set()

class RecentWhalePositionAnalyzer:
    """Analyze recently opened positions across all whale wallets."""
    
    def __init__(self):
        """Initialize the analyzer."""
        self.asset_positions = defaultdict(lambda: RecentAssetPosition(asset=""))
        self.processed_wallets = 0
        self.wallets_with_new_positions = 0
        self.MAX_WORKERS = 5  # Reduced to 5 workers
        self.info = Info(hl_constants.MAINNET_API_URL)
        
        # Round to the nearest hour for consistent time windows
        now = datetime.now()
        self.reference_time = now.replace(minute=0, second=0, microsecond=0)
        if now.minute >= 30:  # Round up if we're past half hour
            self.reference_time = self.reference_time + timedelta(hours=1)
        self.cutoff_time = self.reference_time - timedelta(hours=TIME_PERIOD_HOURS)
        
        print(f"\nTime Window:")
        print(f"Reference time: {self.reference_time.strftime('%Y-%m-%d %H:00:00')}")
        print(f"Cutoff time: {self.cutoff_time.strftime('%Y-%m-%d %H:00:00')}")
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
                self.info.close()  # Close the Hyperliquid Info connection
        except Exception as e:
            print(f"Error during cleanup: {e}")
        
    def make_request_with_retry(self, url: str, payload: dict, max_retries: int = 5) -> Optional[dict]:
        """Make a request with exponential backoff retry logic."""
        base_delay = 2  # Increased base delay
        max_delay = 30  # Increased max delay
        
        for attempt in range(max_retries):
            try:
                response = self.session.post(url, json=payload, headers={"Content-Type": "application/json"})
                
                if response.status_code == 200:
                    # Add a small delay even on successful requests to prevent rate limiting
                    time.sleep(0.5)
                    return response.json()
                elif response.status_code == 429:  # Rate limit
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    print(f"Rate limited. Waiting {delay:.1f} seconds before retry {attempt + 1}/{max_retries}")
                    time.sleep(delay)
                else:
                    print(f"Error response: {response.status_code} - {response.text}")
                    if attempt < max_retries - 1:
                        time.sleep(base_delay)
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
        Get recently opened and closed positions for a whale address using the userFillsByTime endpoint.
        """
        recent_positions = []
        
        try:
            # Use the class's fixed reference time for consistency
            current_time = int(self.reference_time.timestamp() * 1000)
            cutoff_time = int(self.cutoff_time.timestamp() * 1000)
            
            # Debug time window validation
            if DEBUG_MODE:
                print(f"\nTime window for {whale_address}:")
                print(f"Reference time: {self.reference_time}")
                print(f"Cutoff time: {self.cutoff_time}")
                print(f"Window hours: {TIME_PERIOD_HOURS}")
            
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
                return []
            
            # Track unique trades by their characteristics
            unique_trades = {}
            
            for fill in fills:
                if fill.get('orderType', '').lower() == 'twap':
                    continue
                    
                fill_time = fill.get('time')
                # Strict time window check
                if not (cutoff_time <= fill_time <= current_time):
                    if DEBUG_MODE:
                        print(f"Skipping fill outside time window: {datetime.fromtimestamp(fill_time/1000)}")
                    continue
                    
                coin = fill.get('coin')
                dir_str = fill.get('dir', '')
                size = float(fill.get('sz', 0))
                price = float(fill.get('px', 0))
                position_value = size * price
                
                if abs(position_value) < MIN_POSITION_VALUE:
                    continue
                    
                is_long = dir_str == 'Open Long' or dir_str == 'Close Short'
                is_short = dir_str == 'Open Short' or dir_str == 'Close Long'
                is_open = dir_str.startswith('Open')
                
                # Create a unique trade identifier that includes all relevant characteristics
                trade_key = f"{whale_address}_{coin}_{is_long}_{is_open}_{size}_{price}_{fill_time}"
                
                unique_trades[trade_key] = {
                    'coin': coin,
                    'size': size if is_long else -size,
                    'entry_price': price,
                    'position_value': position_value,
                    'timestamp': fill_time,
                    'is_open': is_open,
                    'is_long': is_long
                }
            
            # Convert unique trades to list and sort by timestamp
            recent_positions = list(unique_trades.values())
            recent_positions.sort(key=lambda x: x['timestamp'])
            
            if DEBUG_MODE:
                print(f"\nProcessed data for {whale_address}:")
                print(f"Total fills found: {len(fills)}")
                print(f"Unique positions after filtering: {len(recent_positions)}")
                for pos in recent_positions:
                    print(f"Position: {pos['coin']} - {'Long' if pos['is_long'] else 'Short'} - "
                          f"{'Open' if pos['is_open'] else 'Close'} - ${pos['position_value']:,.2f} - "
                          f"Time: {datetime.fromtimestamp(pos['timestamp']/1000)}")
            
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
                'long_whales': set(),
                'short_whales': set(),
                'closed_long_whales': set(),
                'closed_short_whales': set()
            })
            
            # Debug counters
            total_positions = 0
            filtered_positions = 0
            
            for position in positions:
                total_positions += 1
                asset = position['coin']
                size = position['size']
                value = position['position_value']
                
                if abs(value) < MIN_POSITION_VALUE:  # Filter by minimum position value
                    continue
                    
                filtered_positions += 1
                    
                if position['is_long']:
                    if position['is_open']:
                        asset_positions[asset]['long'] += 1
                        asset_positions[asset]['long_size'] += size
                        asset_positions[asset]['long_value'] += value
                        asset_positions[asset]['long_whales'].add(whale_address)
                    else:
                        asset_positions[asset]['closed_long'] += 1
                        asset_positions[asset]['closed_long_size'] += size
                        asset_positions[asset]['closed_long_value'] += value
                        asset_positions[asset]['closed_long_whales'].add(whale_address)
                else:
                    if position['is_open']:
                        asset_positions[asset]['short'] += 1
                        asset_positions[asset]['short_size'] += abs(size)
                        asset_positions[asset]['short_value'] += value
                        asset_positions[asset]['short_whales'].add(whale_address)
                    else:
                        asset_positions[asset]['closed_short'] += 1
                        asset_positions[asset]['closed_short_size'] += abs(size)
                        asset_positions[asset]['closed_short_value'] += value
                        asset_positions[asset]['closed_short_whales'].add(whale_address)
            
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
                
                # Update whale sets
                self.asset_positions[asset].long_whales.update(positions['long_whales'])
                self.asset_positions[asset].short_whales.update(positions['short_whales'])
                self.asset_positions[asset].closed_long_whales.update(positions['closed_long_whales'])
                self.asset_positions[asset].closed_short_whales.update(positions['closed_short_whales'])
            
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
        
        print(f"\nTop 10 Most Longed Assets (New Positions in Last {TIME_PERIOD_HOURS} Hours, > ${MIN_POSITION_VALUE:,}, Excluding TWAPs)")
        print("=" * 100)
        long_data = [[asset, f"${pos.total_new_long_value:,.2f}", 
                     f"{pos.total_new_long_size:,.2f}", pos.new_long_count,
                     len(pos.long_whales), len(pos.closed_long_whales)] 
                     for asset, pos in sorted_longs]
        print(tabulate(long_data, 
                      headers=['Asset', 'Total New Long Value', 'Total New Long Size', 
                              'New Positions', 'Long Whales', 'Closed Long Whales'],
                      tablefmt='grid'))
        
        print(f"\nTop 10 Most Shorted Assets (New Positions in Last {TIME_PERIOD_HOURS} Hours, > ${MIN_POSITION_VALUE:,}, Excluding TWAPs)")
        print("=" * 100)
        short_data = [[asset, f"${pos.total_new_short_value:,.2f}", 
                      f"{pos.total_new_short_size:,.2f}", pos.new_short_count,
                      len(pos.short_whales), len(pos.closed_short_whales)] 
                      for asset, pos in sorted_shorts]
        print(tabulate(short_data, 
                      headers=['Asset', 'Total New Short Value', 'Total New Short Size', 
                              'New Positions', 'Short Whales', 'Closed Short Whales'],
                      tablefmt='grid'))
        
        # Calculate totals
        total_long_whales = len(set().union(*[pos.long_whales for pos in self.asset_positions.values()]))
        total_short_whales = len(set().union(*[pos.short_whales for pos in self.asset_positions.values()]))
        total_closed_long_whales = len(set().union(*[pos.closed_long_whales for pos in self.asset_positions.values()]))
        total_closed_short_whales = len(set().union(*[pos.closed_short_whales for pos in self.asset_positions.values()]))
        
        print("\nWhale Summary:")
        print(f"Total Long Whales: {total_long_whales}")
        print(f"Total Short Whales: {total_short_whales}")
        print(f"Total Whales Closing Longs: {total_closed_long_whales}")
        print(f"Total Whales Closing Shorts: {total_closed_short_whales}")

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
        print(f"Analyzing positions opened in the last {TIME_PERIOD_HOURS} hours (since {self.cutoff_time})")
        print(f"Note: Only counting positions > ${MIN_POSITION_VALUE:,} in value")
        print("Note: Excluding TWAP orders to focus on direct position openings")
        print("Note: Position values are calculated from fill data (entry price * size)")
        
        # Process whales in parallel with rate limiting
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            future_to_whale = {
                executor.submit(self.process_whale, address): address 
                for address in whale_addresses
            }
            
            completed = 0
            for future in as_completed(future_to_whale):
                address = future_to_whale[future]
                try:
                    asset_positions = future.result()
                    if asset_positions:
                        self.update_asset_positions(asset_positions)
                        self.wallets_with_new_positions += 1
                    self.processed_wallets += 1
                    completed += 1
                    
                    # Print progress
                    print(f"\rProgress: {completed}/{len(whale_addresses)} wallets processed", end="")
                    
                    # Add delay between batches
                    if completed % 5 == 0:
                        time.sleep(1)  # Add delay every 5 wallets
                        
                except Exception as e:
                    print(f"\nError processing whale {address}: {str(e)}")
        
        print("\n")  # New line after progress
        
        # Display results
        self.display_results()
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"\nSummary:")
        print(f"Total wallets processed: {self.processed_wallets}")
        print(f"Wallets with new positions: {self.wallets_with_new_positions}")
        print(f"Wallets with no activity: {self.processed_wallets - self.wallets_with_new_positions}")
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
                    f"${positions.total_closed_short_value:,.2f}",
                    len(positions.long_whales),
                    len(positions.short_whales)
                ])
                total_new_long_value += positions.total_new_long_value
                total_new_short_value += positions.total_new_short_value
                total_closed_long_value += positions.total_closed_long_value
                total_closed_short_value += positions.total_closed_short_value
        
        # Display results
        print(f"\nWhale Position Analysis (Positions > ${MIN_POSITION_VALUE:,} in Last {TIME_PERIOD_HOURS} Hours, Excluding TWAPs)")
        print("=" * 140)
        print(tabulate(table_data, 
                      headers=['Asset', 'New Long', 'New Short', 'Closed Long', 'Closed Short',
                              'New Long Size', 'New Short Size', 'Closed Long Size', 'Closed Short Size',
                              'New Long Value', 'New Short Value', 'Closed Long Value', 'Closed Short Value',
                              'Long Whales', 'Short Whales'],
                      tablefmt='grid'))
        
        # Display top positions
        self.display_top_positions()
        
        print(f"\nValue Summary:")
        print(f"Total new long value: ${total_new_long_value:,.2f}")
        print(f"Total new short value: ${total_new_short_value:,.2f}")
        print(f"Total closed long value: ${total_closed_long_value:,.2f}")
        print(f"Total closed short value: ${total_closed_short_value:,.2f}")

def main():
    try:
        analyzer = RecentWhalePositionAnalyzer()
        analyzer.analyze_positions()
    except KeyboardInterrupt:
        print("\nScript interrupted by user. Cleaning up...")
    except Exception as e:
        print(f"\nError during execution: {e}")
    finally:
        # Cleanup will be handled by atexit handler
        pass

if __name__ == "__main__":
    main() 