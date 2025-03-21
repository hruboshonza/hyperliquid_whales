#!/usr/bin/env python3
"""
Script to show all open trades for a specific whale address.
"""

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional
import json

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.position_tracker import PositionTracker
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants

class WhaleTradeTracker:
    """
    Track and display all open trades for a specific whale address.
    """
    
    def __init__(self, whale_address: str):
        """
        Initialize the WhaleTradeTracker.
        
        Args:
            whale_address (str): The whale address to track trades for
        """
        self.info = Info(hl_constants.MAINNET_API_URL)
        self.whale_address = whale_address
        
    def get_all_positions(self) -> List[Dict]:
        """
        Get all open positions for the whale address.
        
        Returns:
            List[Dict]: List of all open positions
        """
        all_positions = []
        
        try:
            print(f"\nFetching user state for address: {self.whale_address}")
            user_state = self.info.user_state(self.whale_address)
            
            if isinstance(user_state, dict):
                if 'assetPositions' in user_state:
                    print(f"\nFound {len(user_state['assetPositions'])} asset positions")
                    for pos in user_state['assetPositions']:
                        position_data = pos.get('position', {})
                        coin = position_data.get('coin')
                        size = float(position_data.get('szi', 0))
                        
                        if size != 0:  # Only include non-zero positions
                            entry_price = float(position_data.get('entryPx', 0))
                            mark_price = float(position_data.get('markPx', 0))  # Get mark price from position data
                            position_value = float(position_data.get('positionValue', 0))  # Keep original position value
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
                else:
                    print("\nNo 'assetPositions' found in user state")
            else:
                print(f"\nUser state is not a dictionary: {type(user_state)}")
                        
            return all_positions
            
        except Exception as e:
            print(f"\nError getting positions for {self.whale_address}: {str(e)}")
            import traceback
            print("\nFull traceback:")
            print(traceback.format_exc())
            return []
            
    def format_position(self, pos: Dict) -> str:
        """Format a position for display."""
        try:
            direction = "Long" if pos['size'] > 0 else "Short"
            leverage_type = pos['leverage']['type']
            leverage_value = pos['leverage']['value']
            leverage_str = f"{leverage_type.capitalize()} {leverage_value}x"
            
            return (
                f"{pos['coin']:<8} | "  # Increased width for longer coin names
                f"{direction:<6} | "
                f"{abs(pos['size']):>12.4f} | "
                f"${pos['entry_price']:>10.2f} | "
                f"${pos['mark_price']:>10.2f} | "
                f"${pos['position_value']:>12.2f} | "
                f"${pos['unrealized_pnl']:>10.2f} | "
                f"{leverage_str}"  # Added width for leverage
            )
        except Exception as e:
            return f"Error formatting position: {e}"
            
    def display_trades(self):
        """Display all open trades for the whale address."""
        print(f"\nOpen trades for whale address: {self.whale_address}")
        print("=" * 130)  # Increased width for longer coin names
        
        positions = self.get_all_positions()
        
        if not positions:
            print("No open positions found for this address")
            return
            
        print("Coin      | Side   | Size         | Entry Price | Mark Price  | Pos. Value   | UPnL        | Leverage")
        print("-" * 130)  # Increased width for longer coin names
        
        total_value = 0
        total_pnl = 0
        
        # Sort positions by position value (largest first)
        positions.sort(key=lambda x: x['position_value'], reverse=True)
        
        for pos in positions:
            print(self.format_position(pos))
            total_value += pos['position_value']
            total_pnl += pos['unrealized_pnl']
            
        print("-" * 130)  # Increased width for longer coin names
        print(f"Total Position Value: ${total_value:,.2f}")
        print(f"Total Unrealized PnL: ${total_pnl:,.2f}")
        print("=" * 130)  # Increased width for longer coin names

def main():
    # Example whale address
    whale_address = "0x8cc94dc843e1ea7a19805e0cca43001123512b6a"
    
    tracker = WhaleTradeTracker(whale_address)
    tracker.display_trades()

if __name__ == "__main__":
    main() 