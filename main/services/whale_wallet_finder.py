"""
Find and track whale wallets from Hyperliquid leaderboard.
"""

from typing import Dict, List, Optional
import json
import os
import time
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants

class WhaleWalletFinder:
    """Find and track whale wallets from Hyperliquid leaderboard."""
    
    # Whale detection thresholds
    MIN_ACCOUNT_VALUE = 300000  # Minimum account value in USD
    MIN_24H_VOLUME = 0     # Minimum 24h trading volume in USD
    MIN_ROI = 0                 # Minimum ROI percentage (0 means we track all ROIs)
    
    # Webpage URL
    LEADERBOARD_URL = "https://app.hyperliquid.xyz/leaderboard"
    
    def __init__(self):
        """Initialize the WhaleWalletFinder."""
        self.info = Info(hl_constants.MAINNET_API_URL)
        
    def get_leaderboard_data(self) -> List[Dict]:
        """Get current leaderboard data by scraping the webpage."""
        try:
            # Setup Chrome options
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--window-size=1920,1080")
            
            # Initialize the driver
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
            driver.get(self.LEADERBOARD_URL)
            
            whale_data = []
            processed_count = 0
            
            while processed_count < 10:  # Process top 10 traders
                try:
                    # Wait for table and get fresh reference to rows
                    wait = WebDriverWait(driver, 30)
                    table = wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
                    time.sleep(2)  # Wait for data to load
                    
                    # Get fresh rows
                    rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
                    if processed_count >= len(rows):
                        break
                        
                    # Get current row
                    row = rows[processed_count]
                    cells = row.find_elements(By.TAG_NAME, "td")
                    
                    if len(cells) >= 6:
                        # Get text content
                        trader_cell = cells[1]
                        account_value_text = cells[2].text.strip()
                        volume_text = cells[5].text.strip()
                        
                        # Click on the trader to get to their page
                        trader_cell.click()
                        time.sleep(2)  # Wait for navigation
                        
                        # Get the current URL which contains the full address
                        current_url = driver.current_url
                        full_address = current_url.split("/")[-1]  # Get the last part of the URL
                        
                        print(f"Processing trader {processed_count + 1}: {full_address}")
                        whale_data.append({
                            'address': full_address,
                            'account_value': account_value_text,
                            'volume': volume_text
                        })
                        
                        # Go back to the leaderboard
                        driver.back()
                        time.sleep(2)  # Wait for navigation back
                    
                    processed_count += 1
                    
                except Exception as e:
                    print(f"Error processing row {processed_count + 1}: {e}")
                    processed_count += 1  # Move to next row even if there's an error
                    driver.get(self.LEADERBOARD_URL)  # Refresh the page
                    time.sleep(2)
                    continue
            
            driver.quit()
            return whale_data
            
        except Exception as e:
            print(f"Error getting leaderboard data: {e}")
            if 'driver' in locals():
                driver.quit()
            return []
    
    def save_whale_wallets(self, whale_data: List[Dict], output_file: str):
        """Save whale wallet data to JSON file."""
        try:
            # Create output directory if it doesn't exist
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            # Load existing data if file exists
            existing_data = {'wallets': [], 'last_updated': ''}
            if os.path.exists(output_file):
                with open(output_file, 'r') as f:
                    existing_data = json.load(f)
            
            # Convert existing wallets to set for quick lookup
            existing_addresses = {w['address'].lower() for w in existing_data['wallets']}
            
            # Add new wallets
            for whale in whale_data:
                if whale['address'].lower() not in existing_addresses:
                    existing_data['wallets'].append({
                        'address': whale['address'],
                        'added_date': datetime.now().strftime('%Y-%m-%d'),
                        'description': f"Whale wallet with ${whale['account_value']:,.2f} account value"
                    })
                    existing_addresses.add(whale['address'].lower())
            
            # Update last updated timestamp
            existing_data['last_updated'] = datetime.now().strftime('%Y-%m-%d')
            
            # Save to file
            with open(output_file, 'w') as f:
                json.dump(existing_data, f, indent=2)
                
            print(f"Saved {len(existing_data['wallets'])} whale wallets to {output_file}")
            
        except Exception as e:
            print(f"Error saving whale wallets: {e}")
    
    def display_whale_data(self, whale_data: List[Dict]):
        """Display whale wallet data in a formatted table."""
        if not whale_data:
            print("No whale wallets found!")
            return
            
        print("\nTop 10 Traders:")
        print("=" * 120)
        print(f"{'Address':<42} | {'Account Value':>25} | {'Volume (7D)':>25}")
        print("-" * 120)
        
        for whale in whale_data:
            print(
                f"{whale['address']:<42} | "
                f"{whale['account_value']:>25} | "
                f"{whale['volume']:>25}"
            )
        
        print("=" * 120)

    def check_specific_wallet(self, address: str) -> Dict:
        """Check stats for a specific wallet address."""
        try:
            # Get user state
            user_state = self.info.user_state(address)
            if not user_state:
                return {}
            
            # Get user fills for last 24h
            current_time = int(datetime.now().timestamp() * 1000)
            start_time = current_time - (24 * 3600 * 1000)  # 24 hours ago
            trades = self.info.user_fills_by_time(address, start_time)
            
            # Calculate metrics
            account_value = float(user_state.get('marginSummary', {}).get('accountValue', 0))
            
            # Calculate 24h volume from trades
            volume_24h = sum(
                abs(float(trade.get('sz', 0)) * float(trade.get('px', 0)))
                for trade in trades if trade
            )
            
            # Calculate ROI from unrealized PnL
            total_pnl = sum(
                float(pos.get('position', {}).get('unrealizedPnl', 0))
                for pos in user_state.get('assetPositions', [])
            )
            roi = (total_pnl / account_value * 100) if account_value > 0 else 0
            
            return {
                'address': address,
                'account_value': account_value,
                'volume_24h': volume_24h,
                'roi_24h': roi
            }
            
        except Exception as e:
            print(f"Error checking wallet {address}: {e}")
            return {}

def main():
    # Initialize finder
    finder = WhaleWalletFinder()
    
    # Get leaderboard data
    print("Fetching data from Hyperliquid leaderboard...")
    leaderboard_data = finder.get_leaderboard_data()
    
    # Display results
    finder.display_whale_data(leaderboard_data)
    
    # Save to file if we found any whales
    if leaderboard_data:
        output_file = os.path.join('resources', 'whale_wallets.json')
        finder.save_whale_wallets(leaderboard_data, output_file)

if __name__ == "__main__":
    main()
