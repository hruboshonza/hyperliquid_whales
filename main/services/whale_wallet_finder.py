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
    MIN_24H_VOLUME = 100000     # Minimum 24h trading volume in USD
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
            
            # Wait for the table to be present and visible
            wait = WebDriverWait(driver, 30)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
            
            # Add a small delay to ensure data is loaded
            time.sleep(5)
            
            # Find all rows in the table body
            rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
            
            whale_data = []
            for row in rows:
                try:
                    # Wait for cells to be present
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) < 6:  # Make sure we have all needed columns
                        continue
                    
                    # Get text content
                    trader_cell = cells[1]
                    account_value_text = cells[2].text.strip()
                    volume_text = cells[5].text.strip()
                    
                    # Convert account value to float for comparison
                    account_value = float(account_value_text.replace("$", "").replace(",", ""))
                    
                    # Only process if account value is > $10M
                    if account_value > 10000000:
                        # Click on the trader address to get full address
                        try:
                            trader_link = trader_cell.find_element(By.TAG_NAME, "a")
                            trader_link.click()
                            time.sleep(1)  # Wait for popup/tooltip
                            
                            # Try to find the full address in the popup/tooltip
                            full_address = wait.until(EC.presence_of_element_located(
                                (By.CSS_SELECTOR, "[data-tooltip-id]")
                            )).get_attribute("data-tooltip-content")
                            
                            if not full_address:
                                full_address = trader_cell.text.strip()
                            
                        except Exception as click_error:
                            print(f"Could not get full address: {click_error}")
                            full_address = trader_cell.text.strip()
                        
                        print(f"Found whale: {full_address}, Account: {account_value_text}, Volume: {volume_text}")
                        whale_data.append({
                            'address': full_address,
                            'account_value': account_value_text,
                            'volume': volume_text
                        })
                            
                except Exception as e:
                    print(f"Error processing row: {e}")
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
            
        print("\nWhale Wallets Found:")
        print("=" * 100)
        print(f"{'Address':<42} | {'Account Value':>25} | {'Volume':>25}")
        print("-" * 100)
        
        for whale in whale_data:
            print(
                f"{whale['address']:<42} | "
                f"{whale['account_value']:>25} | "
                f"{whale['volume']:>25}"
            )
        
        print("=" * 100)
        print(f"Total entries found: {len(whale_data)}")

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
