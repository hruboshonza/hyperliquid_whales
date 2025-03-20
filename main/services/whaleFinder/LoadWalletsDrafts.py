"""
Dynamic pagination handler for Hyperliquid leaderboard with 30D period data.
"""

from typing import Dict, List, Optional
import time
import json
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException

class LoadWalletsDrafts:
    """Handle dynamic pagination of Hyperliquid leaderboard data for 30D period."""
    
    LEADERBOARD_URL = "https://app.hyperliquid.xyz/leaderboard"
    DATA_SAVE_FILE = "resources/leaderboard_draft_data.json"
    # Maximum number of wallets to process before stopping
    MAX_WALLETS_TO_PROCESS = 2000
    
    # Whale filter criteria
    MIN_ACCOUNT_VALUE = 300000   # $300k minimum account value
    MIN_ROI = 10                 # 10% minimum ROI
    MIN_VOLUME = 500000         # $1M minimum volume -> to volume je mozna az moc vysoke, snizim na priste na 500k... Vzalo mi to ted jen 67 walletek
    
    def __init__(self):
        """Initialize the pagination handler."""
        self.driver = None
        self.current_page = 1
        self.total_wallets_processed = 0
        self.setup_driver()
        
    def setup_driver(self):
        """Set up the Chrome driver with appropriate options."""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            
            # Remove problematic options
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            
            print("Setting up Chrome WebDriver...")
            self.driver = webdriver.Chrome(
                options=chrome_options
            )
            
            # Set page load timeout
            self.driver.set_page_load_timeout(30)
            
            print("Navigating to leaderboard URL...")
            # Navigate to the page
            self.driver.get(self.LEADERBOARD_URL)
            time.sleep(5)  # Increased wait time for initial page load
            
            print("Setting up 30D period...")
            # Switch to 30D period
            self._switch_to_30d_period()
            
        except Exception as e:
            print(f"Error setting up driver: {e}")
            if self.driver:
                self.driver.quit()
            raise

    def _switch_to_30d_period(self):
        """Switch the leaderboard to 30D period."""
        try:
            # Wait for the period selector to be present
            wait = WebDriverWait(self.driver, 10)
            period_selector = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "button[aria-haspopup='listbox']"))
            )
            
            # Click the period selector
            period_selector.click()
            time.sleep(1)
            
            # Find and click the 30D option
            period_options = self.driver.find_elements(By.CSS_SELECTOR, "li[role='option']")
            for option in period_options:
                if "30D" in option.text:
                    option.click()
                    time.sleep(2)  # Wait for data to reload
                    print("Successfully switched to 30D period")
                    return
                    
            print("Could not find 30D period option")
            
        except Exception as e:
            print(f"Error switching to 30D period: {e}")

    def wait_for_table(self):
        """Wait for table to be present and return it."""
        wait = WebDriverWait(self.driver, 10)
        table = wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        time.sleep(2)  # Wait for data to load
        return table
    
    def get_current_page_data(self) -> List[Dict]:
        """Get data from the current page."""
        try:
            print(f"\nFetching data from page {self.current_page}...")
            
            # Wait for table and get header
            table = self.wait_for_table()
            header = table.find_element(By.TAG_NAME, "thead")
            
            # Print header
            print("\n{:<5} {:<15} {:<20} {:<20} {:<15} {:<20}".format(
                "Rank", "Trader", "Account Value", "Volume (30D)", "ROI (30D)", "PnL (30D)"
            ))
            print("-" * 95)
            
            # Get all rows
            rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
            page_data = []
            
            for idx, row in enumerate(rows, 1):
                # Check if we've reached the processing limit
                if self.total_wallets_processed >= self.MAX_WALLETS_TO_PROCESS:
                    print(f"\nReached maximum number of wallets to process ({self.MAX_WALLETS_TO_PROCESS})")
                    return page_data

                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) >= 6:
                        # Extract data from cells
                        rank = cells[0].text.strip()
                        trader = cells[1].text.strip()
                        account_value = cells[2].text.strip()
                        volume = cells[3].text.strip()
                        roi = cells[4].text.strip()
                        pnl = cells[5].text.strip()
                        
                        # Print in table format
                        print("{:<5} {:<15} {:<20} {:<20} {:<15} {:<20}".format(
                            rank, trader, account_value, volume, roi, pnl
                        ))
                        
                        # Store data
                        trader_data = {
                            'rank': rank,
                            'trader': trader,
                            'account_value': account_value,
                            'volume_30d': volume,
                            'roi_30d': roi,
                            'pnl_30d': pnl
                        }
                        page_data.append(trader_data)
                        self.total_wallets_processed += 1
                        
                except Exception as e:
                    print(f"Error processing trader {idx} on page {self.current_page}: {e}")
                    continue
            
            print("-" * 95)
            return page_data
            
        except Exception as e:
            print(f"Error getting page {self.current_page} data: {e}")
            return []
    
    def move_to_next_page(self) -> bool:
        """Move to the next page if available."""
        try:
            print("\nAttempting to find and click the Next button...")
            
            # First get the current table for staleness check
            current_table = self.wait_for_table()
            
            # Get current first rank for comparison
            old_first_rank = current_table.find_element(By.CSS_SELECTOR, "tbody tr td:first-child").text.strip()
            print(f"Current first rank: {old_first_rank}")
            
            # Try to find the Next button using specific SVG attributes
            script = """
            const nextButton = Array.from(document.querySelectorAll('.sc-jSUZER.jlrncQ')).find(el => {
                const svg = el.querySelector('svg');
                return svg && 
                       svg.getAttribute('width') === '18' && 
                       svg.getAttribute('height') === '18' &&
                       svg.getAttribute('viewBox') === '0 0 24 24' &&
                       svg.innerHTML.includes('M8.59 16.34l4.58-4.59');
            });
            return nextButton;
            """
            next_button = self.driver.execute_script(script)
            
            if not next_button:
                print("\nCould not find Next button - likely reached the last page")
                return False
                
            print("\nFound Next button")
            
            # Click using JavaScript immediately
            self.driver.execute_script("arguments[0].click();", next_button)
            print("JavaScript click executed")
            
            # Wait for new table and verify data
            try:
                time.sleep(1)  # Wait for data to load
                new_table = self.wait_for_table()
                first_row = new_table.find_element(By.CSS_SELECTOR, "tbody tr")
                new_rank = first_row.find_element(By.CSS_SELECTOR, "td:first-child").text.strip()
                
                print(f"New first rank: {new_rank}")
                
                # Verify rank increased
                try:
                    old_rank_num = int(old_first_rank)
                    new_rank_num = int(new_rank)
                    if new_rank_num > old_rank_num:
                        self.current_page += 1
                        print(f"Successfully moved to page {self.current_page}")
                        return True
                except ValueError:
                    print("Could not compare ranks numerically")
                    return False
                    
                print("Page data does not show progression in ranks")
                return False
                
            except Exception as e:
                print(f"Error verifying new page data: {e}")
                return False
            
        except Exception as e:
            print(f"Error moving to next page: {e}")
            return False
    
    def cleanup(self):
        """Clean up resources."""
        if self.driver:
            self.driver.quit()
            self.driver = None

def save_to_json(data: List[Dict], filename: str = LoadWalletsDrafts.DATA_SAVE_FILE):
    """Save the collected data to a JSON file."""
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        def parse_number(value: str) -> float:
            """Parse number string handling both US and EU formats."""
            try:
                # Remove currency symbol and spaces
                clean_value = value.replace('$', '').replace(' ', '')
                
                # Handle percentage
                if '%' in clean_value:
                    clean_value = clean_value.replace('%', '')
                
                # If comma is used as decimal separator (EU format)
                if ',' in clean_value and '.' not in clean_value:
                    clean_value = clean_value.replace(',', '.')
                # If both comma and period exist, assume comma is thousand separator
                elif ',' in clean_value and '.' in clean_value:
                    clean_value = clean_value.replace(',', '')
                
                return float(clean_value)
            except ValueError as e:
                print(f"Error parsing number '{value}': {e}")
                return 0.0
        
        # Extract only the required fields and filter based on criteria
        processed_data = []
        whales_count = 0
        for entry in data:
            try:
                # Convert values using the new parser
                account_value = parse_number(entry['account_value'])
                roi = parse_number(entry['roi_30d'])
                volume = parse_number(entry['volume_30d'])
                
                # Debug print for values
                print(f"\nProcessing wallet {entry['trader']}:")
                print(f"Account Value: ${account_value:,.2f}")
                print(f"ROI: {roi:.2f}%")
                print(f"Volume: ${volume:,.2f}")
                
                # Check if meets whale criteria
                if account_value >= LoadWalletsDrafts.MIN_ACCOUNT_VALUE and \
                   roi >= LoadWalletsDrafts.MIN_ROI and \
                   volume >= LoadWalletsDrafts.MIN_VOLUME:
                    processed_entry = {
                        'trader': entry['trader'],
                        'account_value': entry['account_value'],
                        'pnl_30d': entry['pnl_30d'],
                        'roi_30d': entry['roi_30d'],
                        'volume_30d': entry['volume_30d'],
                        'is_whale': True
                    }
                    processed_data.append(processed_entry)
                    whales_count += 1
                    print(f"✅ Wallet {entry['trader']} meets criteria!")
                else:
                    print(f"❌ Wallet {entry['trader']} does not meet criteria:")
                    if account_value < LoadWalletsDrafts.MIN_ACCOUNT_VALUE:
                        print(f"   Account value ${account_value:,.2f} < ${LoadWalletsDrafts.MIN_ACCOUNT_VALUE:,.2f}")
                    if roi < LoadWalletsDrafts.MIN_ROI:
                        print(f"   ROI {roi:.2f}% < {LoadWalletsDrafts.MIN_ROI}%")
                    if volume < LoadWalletsDrafts.MIN_VOLUME:
                        print(f"   Volume ${volume:,.2f} < ${LoadWalletsDrafts.MIN_VOLUME:,.2f}")

            except Exception as e:
                print(f"Error processing entry {entry}: {e}")
                continue
            
        with open(filename, 'w') as f:
            json.dump(processed_data, f, indent=4)
        print(f"\nData successfully saved to {filename}")
        
        # Print summary of whales found
        print(f"✅ Found {whales_count} active whales out of {len(data)} total traders")
        
    except Exception as e:
        print(f"Error saving data to JSON: {e}")

def main(max_pages: int = 10000):
    """Main function to run the leaderboard data collection."""
    pagination = LoadWalletsDrafts()
    all_data = []
    
    try:
        current_page = 1
        while current_page <= max_pages:
            page_data = pagination.get_current_page_data()
            if page_data:
                all_data.extend(page_data)
                
                # Check if we've reached the processing limit
                if pagination.total_wallets_processed >= pagination.MAX_WALLETS_TO_PROCESS:
                    print(f"\nReached maximum number of wallets to process ({pagination.MAX_WALLETS_TO_PROCESS})")
                    break
                
                if not pagination.move_to_next_page():
                    print("\nReached the last page or encountered an error")
                    break
                    
                current_page += 1
            else:
                print("\nNo data found on current page")
                break
                
    except Exception as e:
        print(f"Error in main process: {e}")
        
    finally:
        pagination.cleanup()
        
    if all_data:
        save_to_json(all_data)
        print(f"\nTotal traders processed: {len(all_data)}")
    else:
        print("\nNo data was collected")

if __name__ == "__main__":
    main() 