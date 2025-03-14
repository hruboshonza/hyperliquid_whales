"""
Monitor active trades and positions for whale wallets on Hyperliquid.
"""

from typing import Dict, List, Set
from datetime import datetime
import json
import os
from collections import defaultdict
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from constants import *

class WhaleTradeMonitor:
    """
    Monitor and analyze trades of whale wallets on Hyperliquid.
    """
    
    def __init__(self):
        """Initialize the WhaleTradeMonitor."""
        self.info = Info(hl_constants.MAINNET_API_URL)
        self.whale_addresses = self.load_whale_addresses()
        
    def load_whale_addresses(self) -> Set[str]:
        """Load whale addresses from JSON file."""
        try:
            if os.path.exists(WHALE_WALLETS_FILE):
                with open(WHALE_WALLETS_FILE, 'r') as f:
                    data = json.load(f)
                    addresses = {wallet['address'].lower() for wallet in data['wallets']}
                print(f"Loaded {len(addresses)} whale addresses from {WHALE_WALLETS_FILE}")
                return addresses
            print(f"No whale addresses file found at {WHALE_WALLETS_FILE}")
            return set()
        except Exception as e:
            print(f"Error loading whale addresses: {e}")
            return set()

    def get_recent_trades(self, address: str) -> List[Dict]:
        """
        Get recent trades for a wallet within specified days.
        
        Args:
            address (str): Wallet address to check
            
        Returns:
            List[Dict]: List of trades
        """
        try:
            # Calculate time range (in milliseconds)
            current_time = int(datetime.now().timestamp() * 1000)
            start_time = current_time - (LOOKBACK_DAYS * 24 * 3600 * 1000)
            
            # Get trades
            trades = self.info.user_fills_by_time(address, start_time)
            return trades or []
            
        except Exception:
            return []

    def get_open_positions(self, address: str) -> List[Dict]:
        """
        Get current open positions for a wallet.
        
        Args:
            address (str): Wallet address to check
            
        Returns:
            List[Dict]: List of open positions
        """
        try:
            user_state = self.info.user_state(address)
            if user_state and 'assetPositions' in user_state:
                # Filter for non-zero positions
                positions = []
                for pos in user_state['assetPositions']:
                    if float(pos['position']['coins']) != 0:
                        positions.append({
                            'market': pos['position']['coin'],
                            'size': float(pos['position']['coins']),
                            'entry_price': float(pos['position']['entryPx']),
                            'mark_price': float(pos['position']['markPx']),
                            'unrealized_pnl': float(pos['position']['unrealizedPnl']),
                            'position_value': abs(float(pos['position']['coins']) * float(pos['position']['markPx'])),
                            'leverage': pos['position']['leverage']
                        })
                return positions
            return []
            
        except Exception:
            return []

    def determine_position_action(self, trade: Dict) -> str:
        """Determine if trade is opening, closing, or modifying a position."""
        try:
            start_pos = float(trade.get('startPosition', 0))
            size = float(trade.get('sz', 0))
            side = trade.get('side', '')
            
            # Convert size to signed value based on side
            signed_size = size if side == "B" else -size
            
            # If starting from zero, it's a new position
            if start_pos == 0:
                return "Open"
            
            # If crossing zero, it's closing
            if (start_pos > 0 and start_pos + signed_size <= 0) or \
               (start_pos < 0 and start_pos + signed_size >= 0):
                return "Close"
            
            # If moving towards zero, it's reducing
            if (start_pos > 0 and signed_size < 0) or \
               (start_pos < 0 and signed_size > 0):
                return "Reduce"
            
            # If moving away from zero, it's adding
            return "Add"
            
        except Exception:
            return "Unknown"

    def format_trade(self, trade: Dict) -> str:
        """Format a single trade for display."""
        try:
            market = trade.get('coin', 'Unknown')
            size = float(trade.get('sz', 0))
            price = float(trade.get('px', 0))
            side = trade.get('side', 'Unknown')
            direction = "Long" if side == "B" else "Short"
            time = datetime.fromtimestamp(int(trade.get('time', 0)) / 1000)
            pnl = float(trade.get('closedPnl', 0))
            value = abs(size * price)
            action = self.determine_position_action(trade)
            
            return (
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} | "
                f"{market:<8} | "
                f"{direction:<6} | "
                f"{action:<7} | "
                f"{size:>12.4f} | "
                f"${price:>10.2f} | "
                f"${value:>12.2f} | "
                f"${pnl:>10.2f}"
            )
        except Exception as e:
            return f"Error formatting trade: {e}"

    def format_position(self, pos: Dict) -> str:
        """Format a single position for display."""
        try:
            leverage_type = pos['leverage']['type']
            leverage_value = pos['leverage']['value']
            direction = "Long" if pos['size'] > 0 else "Short"
            leverage_str = f"{leverage_type.capitalize()} {leverage_value}x"
            
            return (
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

    def display_whale_activity(self, address: str):
        """
        Display recent activity for a whale wallet.
        
        Args:
            address (str): Wallet address to check
        """
        print(f"\nAnalyzing whale wallet: {address}")
        print("=" * 120)
        
        # Get and filter trades
        trades = self.get_recent_trades(address)
        if trades:
            # Filter trades by minimum value
            large_trades = [
                trade for trade in trades 
                if abs(float(trade.get('sz', 0)) * float(trade.get('px', 0))) >= MIN_TRADE_VALUE
            ]
            
            if large_trades:
                print(f"\nLarge Trades (>${MIN_TRADE_VALUE:,.2f}) in last {LOOKBACK_DAYS} {'day' if LOOKBACK_DAYS == 1 else 'days'}:")
                print("=" * 120)
                print("Timestamp            | Market   | Side   | Action  | Size         | Entry Price | Trade Value  | PnL")
                print("-" * 120)
                
                # Sort all trades by time (most recent first)
                sorted_trades = sorted(large_trades, key=lambda x: int(x.get('time', 0)), reverse=True)
                
                total_value = 0
                total_pnl = 0
                
                # Display trades
                for trade in sorted_trades:
                    print(self.format_trade(trade))
                    total_value += abs(float(trade.get('sz', 0)) * float(trade.get('px', 0)))
                    total_pnl += float(trade.get('closedPnl', 0))
                
                print("-" * 120)
                print(f"Total Large Trade Value: ${total_value:,.2f}")
                print(f"Total Realized PnL: ${total_pnl:,.2f}")
            else:
                print(f"\nNo trades larger than ${MIN_TRADE_VALUE:,.2f} in the last {LOOKBACK_DAYS} {'day' if LOOKBACK_DAYS == 1 else 'days'}")
        else:
            print(f"\nNo trades in the last {LOOKBACK_DAYS} {'day' if LOOKBACK_DAYS == 1 else 'days'}")
        
        # Get positions and group by coin
        positions = self.get_open_positions(address)
        if positions:
            print("\nCurrent Open Positions:")
            print("=" * 120)
            print("Market   | Side   | Size         | Entry Price | Mark Price  | Pos. Value   | UPnL        | Leverage")
            print("-" * 120)
            
            # Sort positions by value
            sorted_positions = sorted(positions, key=lambda x: abs(x['position_value']), reverse=True)
            
            total_position_value = 0
            total_unrealized_pnl = 0
            
            for pos in sorted_positions:
                print(f"{pos['market']:<8} | {self.format_position(pos)}")
                total_position_value += abs(pos['position_value'])
                total_unrealized_pnl += pos['unrealized_pnl']
            
            print("-" * 120)
            print(f"Total Position Value: ${total_position_value:,.2f}")
            print(f"Total Unrealized PnL: ${total_unrealized_pnl:,.2f}")
        else:
            print("\nNo open positions")
        
        print("=" * 120)

def main():
    # Initialize monitor
    monitor = WhaleTradeMonitor()
    
    if not monitor.whale_addresses:
        print("No whale addresses found to monitor!")
        return
    
    print(f"\nMonitoring whale wallet activity for the past {LOOKBACK_DAYS} {'day' if LOOKBACK_DAYS == 1 else 'days'}...")
    
    # Check each whale wallet
    for address in sorted(monitor.whale_addresses):
        monitor.display_whale_activity(address)
        from time import sleep
        sleep(1)  # Rate limiting

if __name__ == "__main__":
    main() 