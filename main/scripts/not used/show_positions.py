"""
Script to show positions for multiple coins across whale wallets.
"""

import sys
import os

# Add the project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from main.services.position_tracker import PositionTracker

def main():
    """Main function to show positions for multiple coins."""
    # Initialize position trackers for different coins
    trackers = {
        "BTC": PositionTracker(coin="BTC"),
        "ETH": PositionTracker(coin="ETH"),
        "SOL": PositionTracker(coin="SOL")
    }
    
    print("Fetching positions for all whale wallets...")
    print("=" * 120)
    
    # Load whale wallets
    whale_wallets = trackers["BTC"].load_whale_wallets()
    if not whale_wallets:
        print("No whale wallets found to track")
        return
        
    # Get and display positions for each coin
    for coin, tracker in trackers.items():
        print(f"\n{coin} Positions:")
        print("=" * 120)
        print("Address    | Side   | Size         | Entry Price | Mark Price  | Pos. Value   | UPnL        | Leverage")
        print("-" * 120)
        
        # Get current positions
        current_positions = []
        for address in whale_wallets:
            position = tracker.get_position(address)
            if position:
                current_positions.append(position)
                print(tracker.format_position(position))
                
        if not current_positions:
            print(f"No open {coin} positions found")
            
        print("=" * 120)

if __name__ == "__main__":
    main() 