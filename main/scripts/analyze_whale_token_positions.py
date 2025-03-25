#!/usr/bin/env python3
"""
Script to analyze positions for a specific token across all whale wallets.
Shows detailed information about each position including entry price, size, value, and PnL.
"""

import os
import sys
import json
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Union
import concurrent.futures
from collections import defaultdict
from dataclasses import dataclass
from tabulate import tabulate

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.position_tracker import PositionTracker
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants

@dataclass
class TokenPosition:
    """Data class to hold detailed position information for a token."""
    wallet_address: str
    size: float
    entry_price: float
    position_value: float
    unrealized_pnl: float
    leverage: Dict[str, Union[str, float]]

class WhaleTokenAnalyzer:
    """Analyze positions for a specific token across all whale wallets."""
    
    def __init__(self, token: str, whale_addresses: List[str]):
        """Initialize the analyzer."""
        self.token = token.upper()
        self.whale_addresses = whale_addresses
        self.positions: List[TokenPosition] = []
        self.processed_wallets = 0
        self.wallets_with_positions = 0
        self.MAX_WORKERS = 10  # Number of concurrent workers
        self.info = Info(hl_constants.MAINNET_API_URL)
        
    def get_all_positions(self, whale_address: str) -> List[Dict]:
        """Get all open positions for a whale address."""
        try:
            # Get user state which includes positions
            user_state = self.info.user_state(whale_address)
            positions = []
            
            if isinstance(user_state, dict) and 'assetPositions' in user_state:
                for pos in user_state['assetPositions']:
                    position_data = pos.get('position', {})
                    coin = position_data.get('coin')
                    
                    if coin == self.token:  # Only include positions for the specified token
                        size = float(position_data.get('szi', 0))
                        if size != 0:  # Only include non-zero positions
                            entry_price = float(position_data.get('entryPx', 0))
                            unrealized_pnl = float(position_data.get('unrealizedPnl', 0))
                            margin = float(position_data.get('margin', 0))
                            
                            # Calculate position value and leverage
                            position_value = abs(size * entry_price)
                            leverage_value = round(position_value / margin, 2) if margin > 0 else 0
                            
                            positions.append({
                                'coin': coin,
                                'size': size,
                                'entry_price': entry_price,
                                'position_value': position_value,
                                'unrealized_pnl': unrealized_pnl,
                                'leverage': {
                                    'type': 'cross' if margin > 0 else 'unknown',
                                    'value': leverage_value
                                }
                            })
            
            return positions
        except Exception as e:
            print(f"Error getting positions for {whale_address}: {str(e)}")
            return []
            
    def process_whale(self, whale_address: str) -> List[TokenPosition]:
        """Process a single whale's positions for the specified token."""
        try:
            positions = self.get_all_positions(whale_address)
            
            if not positions:
                return []
                
            token_positions = []
            for pos in positions:
                token_positions.append(TokenPosition(
                    wallet_address=whale_address,
                    size=pos['size'],
                    entry_price=pos['entry_price'],
                    position_value=pos['position_value'],
                    unrealized_pnl=pos['unrealized_pnl'],
                    leverage=pos['leverage']
                ))
                
            return token_positions
            
        except Exception as e:
            print(f"Error processing whale {whale_address}: {str(e)}")
            return []
            
    def analyze_positions(self) -> List[TokenPosition]:
        """Analyze all whale positions for the specified token using parallel processing."""
        start_time = datetime.now()
        
        print(f"\nProcessing {len(self.whale_addresses)} whale addresses for {self.token} positions...")
        
        # Process whales in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            future_to_whale = {
                executor.submit(self.process_whale, address): address 
                for address in self.whale_addresses
            }
            
            for future in concurrent.futures.as_completed(future_to_whale):
                address = future_to_whale[future]
                try:
                    token_positions = future.result()
                    if token_positions:
                        self.positions.extend(token_positions)
                        self.wallets_with_positions += 1
                    self.processed_wallets += 1
                except Exception as e:
                    print(f"Error processing whale {address}: {str(e)}")
                    
        # Sort positions by position value (largest first)
        self.positions.sort(key=lambda x: abs(x.position_value), reverse=True)
        return self.positions

def main():
    parser = argparse.ArgumentParser(description='Analyze whale positions for a specific token')
    parser.add_argument('token', help='Token symbol (e.g., BTC, ETH)')
    parser.add_argument('whale_addresses', nargs='+', help='Whale addresses to analyze')
    args = parser.parse_args()
    
    analyzer = WhaleTokenAnalyzer(args.token, args.whale_addresses)
    positions = analyzer.analyze_positions()
    
    # Prepare data for display
    table_data = []
    total_long_value = 0
    total_short_value = 0
    total_long_size = 0
    total_short_size = 0
    total_pnl = 0
    
    for pos in positions:
        direction = "Long" if pos.size > 0 else "Short"
        leverage_str = f"{pos.leverage['type'].capitalize()} {pos.leverage['value']:.2f}x"
        
        table_data.append([
            pos.wallet_address[:8] + "...",  # Truncated address
            direction,
            f"{abs(pos.size):,.4f}",
            f"${pos.entry_price:,.2f}",
            f"${pos.position_value:,.2f}",
            f"${pos.unrealized_pnl:,.2f}",
            leverage_str
        ])
        
        if pos.size > 0:
            total_long_value += pos.position_value
            total_long_size += pos.size
        else:
            total_short_value += pos.position_value
            total_short_size += abs(pos.size)
            
        total_pnl += pos.unrealized_pnl
            
    # Display results
    print(f"\n{args.token} Position Analysis")
    print("=" * 120)
    print(tabulate(table_data, 
                  headers=['Wallet', 'Side', 'Size', 'Entry Price', 'Position Value', 
                          'Unrealized PnL', 'Leverage'],
                  tablefmt='grid'))
    
    # Display summary
    print("\nSummary:")
    print(f"Total wallets processed: {analyzer.processed_wallets}")
    print(f"Wallets with {args.token} positions: {analyzer.wallets_with_positions}")
    print(f"Total long value: ${total_long_value:,.2f}")
    print(f"Total short value: ${total_short_value:,.2f}")
    print(f"Total long size: {total_long_size:,.4f}")
    print(f"Total short size: {total_short_size:,.4f}")
    print(f"Total unrealized PnL: ${total_pnl:,.2f}")
    
    # Calculate and display average prices
    if total_long_size > 0:
        avg_long_price = total_long_value / total_long_size
        print(f"Average long entry price: ${avg_long_price:,.2f}")
        
    if total_short_size > 0:
        avg_short_price = total_short_value / total_short_size
        print(f"Average short entry price: ${avg_short_price:,.2f}")
        
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    print(f"Processing time: {duration:.2f} seconds")

if __name__ == "__main__":
    main() 