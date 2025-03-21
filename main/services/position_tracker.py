"""
Track positions for a specific coin across whale wallets and save state hourly.
"""

from typing import Dict, List, Optional
import json
import os
from datetime import datetime, timedelta
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants
import sys
import asyncio
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from constants import *

class PositionTracker:
    """
    Track positions for a specific coin across whale wallets and save state hourly.
    """
    
    def __init__(self, coin: str = "BTC"):
        """
        Initialize the PositionTracker.
        
        Args:
            coin (str): The coin to track positions for (default: "BTC")
        """
        self.info = Info(hl_constants.MAINNET_API_URL)
        self.coin = coin
        self.state_file = os.path.join('resources', f'positions_{coin.lower()}.json')
        self.whale_wallets_file = os.path.join('resources', 'activeWhales.json')
        self.last_state = self.load_last_state()
        
    def load_last_state(self) -> Optional[Dict]:
        """Load the last saved state from file."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            return None
        except Exception as e:
            print(f"Error loading last state: {e}")
            return None
            
    def save_state(self, state: Dict):
        """Save current state to file."""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=4)
        except Exception as e:
            print(f"Error saving state: {e}")
            
    def load_whale_wallets(self) -> List[str]:
        """Load whale wallet addresses from JSON file."""
        try:
            if os.path.exists(self.whale_wallets_file):
                with open(self.whale_wallets_file, 'r') as f:
                    data = json.load(f)
                    return [wallet['fullAddress'] for wallet in data['wallets']]
            print(f"No whale wallets file found at {self.whale_wallets_file}")
            return []
        except Exception as e:
            print(f"Error loading whale wallets: {e}")
            return []
            
    def get_position(self, address: str) -> Optional[Dict]:
        """
        Get current position for a specific coin and wallet.
        
        Args:
            address (str): Wallet address to check
            
        Returns:
            Optional[Dict]: Position information if found, None otherwise
        """
        try:
            user_state = self.info.user_state(address)
            print(f"\nDebug - User state for {address}:")
            print(f"Type: {type(user_state)}")
            if isinstance(user_state, dict):
                print(f"Keys: {user_state.keys()}")
                if 'assetPositions' in user_state:
                    print(f"Asset positions: {user_state['assetPositions']}")
            
            if isinstance(user_state, dict) and 'assetPositions' in user_state:
                for pos in user_state['assetPositions']:
                    print(f"Checking position: {pos}")
                    if pos.get('position', {}).get('coin') == self.coin:
                        coins = float(pos.get('position', {}).get('coins', 0))
                        if coins != 0:
                            return {
                                'address': address,
                                'size': coins,
                                'entry_price': float(pos.get('position', {}).get('entryPx', 0)),
                                'mark_price': float(pos.get('position', {}).get('markPx', 0)),
                                'unrealized_pnl': float(pos.get('position', {}).get('unrealizedPnl', 0)),
                                'position_value': abs(coins * float(pos.get('position', {}).get('markPx', 0))),
                                'leverage': pos.get('position', {}).get('leverage', {'type': 'unknown', 'value': 0}),
                                'timestamp': datetime.now().isoformat()
                            }
            return None
        except Exception as e:
            print(f"Error getting position for {address}: {e}")
            return None
            
    def compare_positions(self, current_positions: List[Dict]) -> Dict:
        """
        Compare current positions with last saved state.
        
        Args:
            current_positions (List[Dict]): List of current positions
            
        Returns:
            Dict: Changes detected (closed, increased, decreased, new positions)
        """
        if not self.last_state:
            return {
                'new_positions': current_positions,
                'closed_positions': [],
                'increased_positions': [],
                'decreased_positions': []
            }
            
        last_positions = self.last_state.get('positions', [])
        last_positions_dict = {pos['address']: pos for pos in last_positions}
        current_positions_dict = {pos['address']: pos for pos in current_positions}
        
        changes = {
            'new_positions': [],
            'closed_positions': [],
            'increased_positions': [],
            'decreased_positions': []
        }
        
        # Find new and modified positions
        for address, current_pos in current_positions_dict.items():
            if address not in last_positions_dict:
                changes['new_positions'].append(current_pos)
            else:
                last_pos = last_positions_dict[address]
                if abs(current_pos['size']) > abs(last_pos['size']):
                    changes['increased_positions'].append(current_pos)
                elif abs(current_pos['size']) < abs(last_pos['size']):
                    changes['decreased_positions'].append(current_pos)
                    
        # Find closed positions
        for address, last_pos in last_positions_dict.items():
            if address not in current_positions_dict:
                changes['closed_positions'].append(last_pos)
                
        return changes
        
    def format_position(self, pos: Dict) -> str:
        """Format a position for display."""
        try:
            direction = "Long" if pos['size'] > 0 else "Short"
            leverage_type = pos['leverage']['type']
            leverage_value = pos['leverage']['value']
            leverage_str = f"{leverage_type.capitalize()} {leverage_value}x"
            
            return (
                f"{pos['address'][:8]}... | "
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
            
    def track_positions(self):
        """Track positions for all whale wallets and save state."""
        print(f"\nTracking {self.coin} positions for whale wallets...")
        print("=" * 120)
        
        # Load whale wallets
        whale_wallets = self.load_whale_wallets()
        if not whale_wallets:
            print("No whale wallets found to track")
            return
            
        # Get current positions
        current_positions = []
        for address in whale_wallets:
            position = self.get_position(address)
            if position:
                current_positions.append(position)
                
        # Compare with last state
        changes = self.compare_positions(current_positions)
        
        # Display changes
        if changes['new_positions']:
            print(f"\nNew {self.coin} Positions:")
            print("=" * 120)
            print("Address    | Side   | Size         | Entry Price | Mark Price  | Pos. Value   | UPnL        | Leverage")
            print("-" * 120)
            for pos in changes['new_positions']:
                print(self.format_position(pos))
                
        if changes['closed_positions']:
            print(f"\nClosed {self.coin} Positions:")
            print("=" * 120)
            print("Address    | Side   | Size         | Entry Price | Mark Price  | Pos. Value   | UPnL        | Leverage")
            print("-" * 120)
            for pos in changes['closed_positions']:
                print(self.format_position(pos))
                
        if changes['increased_positions']:
            print(f"\nIncreased {self.coin} Positions:")
            print("=" * 120)
            print("Address    | Side   | Size         | Entry Price | Mark Price  | Pos. Value   | UPnL        | Leverage")
            print("-" * 120)
            for pos in changes['increased_positions']:
                print(self.format_position(pos))
                
        if changes['decreased_positions']:
            print(f"\nDecreased {self.coin} Positions:")
            print("=" * 120)
            print("Address    | Side   | Size         | Entry Price | Mark Price  | Pos. Value   | UPnL        | Leverage")
            print("-" * 120)
            for pos in changes['decreased_positions']:
                print(self.format_position(pos))
                
        # Save current state
        current_state = {
            'timestamp': datetime.now().isoformat(),
            'coin': self.coin,
            'positions': current_positions,
            'changes': changes
        }
        self.save_state(current_state)
        self.last_state = current_state
        
        print("\nState saved successfully")
        print("=" * 120) 