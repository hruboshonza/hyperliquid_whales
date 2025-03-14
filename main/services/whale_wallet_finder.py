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
    MIN_30D_VOLUME = 100000     # Minimum 30d trading volume in USD
    MIN_ROI = 10                 # Minimum ROI percentage (0 means we track all ROIs)
    
    # Webpage URL
    LEADERBOARD_URL = "https://app.hyperliquid.xyz/leaderboard"
    
    def __init__(self):
        """Initialize the WhaleWalletFinder."""
        self.info = Info(hl_constants.MAINNET_API_URL)
        self.driver = None
        
    def get_leaderboard_data(self) -> List[Dict]:
        """Get current leaderboard data by scraping the webpage."""
        try:
            # Setup Chrome options
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--window-size=1920,1080")
            
            # Initialize the driver if not already initialized
            if not self.driver:
                self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
                self.driver.get(self.LEADERBOARD_URL)
            
            whale_data = []
            processed_count = 0
            
            while processed_count < 10:  # Process top 10 traders
                try:
                    # Wait for table and get fresh reference to rows
                    wait = WebDriverWait(self.driver, 30)
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
                        volume_text = cells[3].text.strip()  # Volume (30D)
                        roi_text = cells[4].text.strip()  # ROI (30D)
                        
                        # Convert volume to float (remove $ and commas)
                        volume = float(volume_text.replace("$", "").replace(",", "")) if volume_text else 0
                        
                        # Convert account value to float (remove $ and commas)
                        account_value = float(account_value_text.replace("$", "").replace(",", "")) if account_value_text else 0
                        
                        # Convert ROI to float (handle comma-formatted numbers)
                        roi_text = roi_text.replace("%", "").strip()  # Remove % sign
                        roi_parts = roi_text.split(",")  # Split at comma
                        roi = float(roi_parts[0]) if roi_parts else 0  # Take only the part before comma
                        
                        # Only process if ROI is positive, volume meets minimum, and account value meets minimum
                        if roi > self.MIN_ROI and volume >= self.MIN_30D_VOLUME and account_value >= self.MIN_ACCOUNT_VALUE:
                            # Click on the trader to get to their page
                            trader_cell.click()
                            time.sleep(2)  # Wait for navigation
                            
                            # Get the current URL which contains the full address
                            current_url = self.driver.current_url
                            full_address = current_url.split("/")[-1]  # Get the last part of the URL
                            
                            print(f"Processing trader {processed_count + 1}: {full_address}")
                            whale_data.append({
                                'address': full_address,
                                'account_value': account_value_text,
                                'volume_30d': volume,
                                'roi_30d': roi
                            })
                            
                            # Go back to the leaderboard
                            self.driver.back()
                            time.sleep(2)  # Wait for navigation back
                    
                    processed_count += 1
                    
                except Exception as e:
                    print(f"Error processing row {processed_count + 1}: {e}")
                    processed_count += 1  # Move to next row even if there's an error
                    self.driver.get(self.LEADERBOARD_URL)  # Refresh the page
                    time.sleep(2)
                    continue
            
            return whale_data
            
        except Exception as e:
            print(f"Error getting leaderboard data: {e}")
            if 'driver' in locals():
                self.driver.quit()
            return []
    
    def save_whale_wallets(self, whale_data: List[Dict], output_file: str):
        """Save whale wallet data to JSON file."""
        try:
            # Create output directory if it doesn't exist
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            # Create new data structure
            data = {
                'wallets': whale_data,
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            # Save to file
            with open(output_file, 'w') as f:
                json.dump(data, f, indent=2)
                
            print(f"Saved {len(whale_data)} traders to {output_file}")
            
        except Exception as e:
            print(f"Error saving data: {e}")
    
    def display_whale_data(self, whale_data: List[Dict]):
        """Display whale wallet data in a formatted table."""
        if not whale_data:
            print("No traders found!")
            return
            
        print("\nTop Traders with Positive ROI and Min Volume:")
        print("=" * 150)
        print(f"{'Address':<42} | {'Account Value':>25} | {'Volume (30D)':>25} | {'ROI (30D)':>25}")
        print("-" * 150)
        
        for whale in whale_data:
            print(
                f"{whale['address']:<42} | "
                f"{whale['account_value']:>25} | "
                f"${whale['volume_30d']:,.2f}".rjust(25) + " | "
                f"{whale['roi_30d']:>25}"
            )
        
        print("=" * 150)


    def cleanup(self):
        """Clean up resources."""
        if self.driver:
            self.driver.quit()
            self.driver = None

def main():
    # Initialize finder
    finder = WhaleWalletFinder()
    all_whale_data = []
    current_page = 1
    
    try:
        while True:
            print(f"\nProcessing page {current_page}...")
            # Get leaderboard data for current page
            page_data = finder.get_leaderboard_data()
            
            if not page_data:
                print("No data found on current page.")
                break
                
            # Add data from this page
            all_whale_data.extend(page_data)
            
            # Check if last trader has ROI < MIN_ROI
            if page_data[-1]['roi_30d'] < finder.MIN_ROI:
                print(f"Found trader with ROI < {finder.MIN_ROI}%. Stopping search.")
                break
            
        # Display results
        finder.display_whale_data(all_whale_data)
        
        # Save to file if we found any data
        if all_whale_data:
            output_file = os.path.join('resources', 'leaderboard_wallets.json')
            finder.save_whale_wallets(all_whale_data, output_file)
            
    finally:
        finder.cleanup()

if __name__ == "__main__":
    main()
