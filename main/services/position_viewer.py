"""
This module provides functionality to view open positions on Hyperliquid exchange.
It demonstrates how to connect to the Hyperliquid API and fetch position information
for specific wallet addresses.
"""

from typing import Dict, List
import asyncio
from datetime import datetime
from hyperliquid.info import Info
from hyperliquid.utils import constants
from pprint import pprint
from main.services.whale_wallet_finder import WhaleWalletFinder
from constants import WhaleConfig

# Constants

class PositionViewer:
    """
    A class for viewing open positions on Hyperliquid exchange.
    
    This class provides methods to:
    - Connect to Hyperliquid API
    - Fetch user positions
    - Display position information in a formatted way
    """
    
    def __init__(self, use_testnet: bool = False):
        # Initialize connection to testnet or mainnet
        api_url = constants.TESTNET_API_URL if use_testnet else constants.MAINNET_API_URL
        self.info = Info(api_url)
        self.whale_finder = WhaleWalletFinder(min_account_value=WhaleConfig.MIN_ACCOUNT_VALUE_USD, use_testnet=use_testnet)
    
    async def get_markets(self) -> Dict:
        """
        Fetch all available markets.
        
        Returns:
            Dict: Information about available markets
        """
        try:
            response = self.info.meta()
            if isinstance(response, dict):
                return response
            return await response
        except Exception as e:
            print(f"Error fetching markets: {e}")
            return None

    async def get_user_positions(self, wallet_address: str) -> Dict:
        """
        Fetch all open positions for a given wallet address.
        
        Args:
            wallet_address (str): The wallet address to check positions for
            
        Returns:
            Dict: Position information including token, entry price, and mark price
        """
        try:
            response = self.info.user_state(wallet_address)
            if isinstance(response, dict):
                return response
            return await response
        except Exception as e:
            print(f"Error fetching positions: {e}")
            return None
    
    def display_positions(self, positions: Dict):
        """
        Display position information in a readable format.
        
        Args:
            positions (Dict): Position information from the API
        """
        if not positions or 'assetPositions' not in positions:
            print("No positions found")
            return
        
        # Check if account value meets minimum threshold
        if 'marginSummary' in positions:
            account_value = float(positions['marginSummary']['accountValue'])
            if account_value < WhaleConfig.MIN_ACCOUNT_VALUE_USD:
                print(f"Account value (${account_value:,.2f}) is below minimum threshold (${WhaleConfig.MIN_ACCOUNT_VALUE_USD:,.2f})")
                return
            
        print("\nOpen Positions:")
        print("-" * 80)
        print(f"{'Token':<10} {'Size':<15} {'Entry Price':<15} {'Mark Price':<15} {'Unrealized PnL':<15}")
        print("-" * 80)
        
        for position in positions['assetPositions']:
            if float(position['position']['coins']) != 0:  # Only show non-zero positions
                token = position['position']['coin']
                size = float(position['position']['coins'])
                entry_price = float(position['position']['entryPx'])
                mark_price = float(position['position']['markPx'])
                upnl = float(position['position']['unrealizedPnl'])
                
                print(f"{token:<10} {size:<15.4f} {entry_price:<15.2f} {mark_price:<15.2f} {upnl:<15.2f}")
        
        # Print margin summary
        if 'marginSummary' in positions:
            margin = positions['marginSummary']
            print("\nMargin Summary:")
            print("-" * 80)
            print(f"Account Value: ${float(margin['accountValue']):,.2f}")
            print(f"Total Margin Used: ${float(margin['totalMarginUsed']):,.2f}")
            print(f"Total Position Value: ${float(margin['totalNtlPos']):,.2f}")
            print(f"Total Raw USD: ${float(margin['totalRawUsd']):,.2f}")
            if 'withdrawable' in positions:
                print(f"Withdrawable: ${float(positions['withdrawable']):,.2f}")

async def main():
    viewer = PositionViewer(use_testnet=False)  # Using mainnet
    print(f"Connecting to Hyperliquid Mainnet and fetching positions (min account value: ${WhaleConfig.MIN_ACCOUNT_VALUE_USD:,.2f})...")
    
    # First, let's print all available markets
    markets = await viewer.get_markets()
    if markets:
        print("\nAvailable markets:")
        for market in markets['universe']:
            print(f"- {market['name']}")
    
    # Get whale positions using WhaleWalletFinder
    print("\nFetching whale wallet positions...")
    whale_positions = await viewer.whale_finder.get_whale_positions()
    
    if whale_positions:
        print(f"\nFound {len(whale_positions)} whale wallets with positions:")
        for whale in whale_positions:
            viewer.whale_finder.display_whale_info(whale)
    else:
        print("\nNo whale wallets found with positions above the threshold")

if __name__ == "__main__":
    asyncio.run(main()) 