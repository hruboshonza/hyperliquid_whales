#!/usr/bin/env python3
"""
Script to show all open trades for whale addresses from activeWhales.json.
This script give me all the open positions for a whale address, and it did it really fast!!!
for Cursor AI! Use this thread pool executor
"""

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional
import json
import concurrent.futures
import time
from functools import lru_cache

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.position_tracker import PositionTracker
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants

class WhaleTradeTracker:
    """
    Track and display all open trades for whale addresses.

    """
    
    def __init__(self):
        """
        Initialize the WhaleTradeTracker.
        """
        self.info = Info(hl_constants.MAINNET_API_URL)
        self.processed_wallets = 0
        self.wallets_with_trades = 0
        
    @lru_cache(maxsize=100)
    def get_all_positions(self, whale_address: str) -> List[Dict]:
        """
        Get all open positions for a whale address with caching.
        
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
            
    def format_position(self, pos: Dict) -> str:
        """Format a position for display."""
        try:
            direction = "Long" if pos['size'] > 0 else "Short"
            leverage_type = pos['leverage']['type']
            leverage_value = pos['leverage']['value']
            leverage_str = f"{leverage_type.capitalize()} {leverage_value}x"
            
            return (
                f"{pos['coin']:<8} | "
                f"{direction:<6} | "
                f"{abs(pos['size']):>12.4f} | "
                f"${pos['entry_price']:>10.2f} | "
                f"${pos['mark_price']:>10.2f} | "
                f"${pos['position_value']:>12.2f} | "
                f"${pos['unrealized_pnl']:>10.2f} | "
                f"{leverage_str}"
            )
        except Exception as e:
            return f"Error formatting position: {e}"
            
    def display_trades(self, whale_address: str, whale_data: Dict):
        """Display all open trades for a whale address."""
        self.processed_wallets += 1
        print(f"\nOpen trades for whale address: {whale_address}")
        print("=" * 130)
        
        positions = self.get_all_positions(whale_address)
        
        if not positions:
            print("No open positions found for this address")
            return
            
        self.wallets_with_trades += 1
        print("Coin      | Side   | Size         | Entry Price | Mark Price  | Pos. Value   | UPnL        | Leverage")
        print("-" * 130)
        
        total_value = 0
        total_pnl = 0
        
        # Sort positions by position value (largest first)
        positions.sort(key=lambda x: x['position_value'], reverse=True)
        
        for pos in positions:
            print(self.format_position(pos))
            total_value += pos['position_value']
            total_pnl += pos['unrealized_pnl']
            
        print("-" * 130)
        print(f"Total Position Value: ${total_value:,.2f}")
        print(f"Total Unrealized PnL: ${total_pnl:,.2f}")
        print("=" * 130)
        
        return {
            'address': whale_address,
            'positions': positions,
            'total_position_value': total_value,
            'total_unrealized_pnl': total_pnl,
            'account_value': whale_data['accountValue'],
            'roi': whale_data['roi'],
            'timestamp': datetime.now().isoformat()
        }

def process_whale(tracker: WhaleTradeTracker, whale: Dict) -> Optional[Dict]:
    """Process a single whale's data."""
    try:
        return tracker.display_trades(whale['fullAddress'], whale)
    except Exception as e:
        print(f"Error processing whale {whale['fullAddress']}: {str(e)}")
        return None

def process_all_whales():
    """Process all whale addresses from activeWhales.json and save results."""
    start_time = time.time()
    
    # Read active whales from JSON file
    with open('resources/activeWhales.json', 'r') as f:
        active_whales = json.load(f)
    
    # Create output directory if it doesn't exist
    os.makedirs('resources/whale_trades', exist_ok=True)
    
    # Create a single tracker instance
    tracker = WhaleTradeTracker()
    
    # Process whales concurrently
    all_whale_trades = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_whale = {
            executor.submit(process_whale, tracker, whale): whale 
            for whale in active_whales['wallets']
        }
        
        for future in concurrent.futures.as_completed(future_to_whale):
            whale_data = future.result()
            if whale_data:
                all_whale_trades.append(whale_data)
                
                # Save individual whale data
                output_file = f"resources/whale_trades/{whale_data['address']}.json"
                with open(output_file, 'w') as f:
                    json.dump(whale_data, f, indent=2)
                print(f"Saved individual whale data to {output_file}")
    
    # Save all whale trades to a single file
    output_file = "resources/whale_trades/all_whale_trades.json"
    with open(output_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'whales': all_whale_trades
        }, f, indent=2)
    
    end_time = time.time()
    print(f"\nSaved all whale trades to {output_file}")
    print(f"Total wallets processed: {tracker.processed_wallets}")
    print(f"Wallets with open trades: {tracker.wallets_with_trades}")
    print(f"Total processing time: {end_time - start_time:.2f} seconds")

def main():
    process_all_whales()

if __name__ == "__main__":
    main() 