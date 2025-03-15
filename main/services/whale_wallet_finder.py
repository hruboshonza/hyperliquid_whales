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
    """ !!!!!!!!!!!!!! It gets just a first page, because of leaderboard automatic redirection on first page.... Cannot be used!!!!!!!!!!!!!!!!"""
    
    # Whale detection thresholds
    MIN_ACCOUNT_VALUE = 300000  # Minimum account value in USD
    MIN_30D_VOLUME = 100000     # Minimum 30d trading volume in USD
    MIN_ROI = 10                # Minimum ROI percentage (0 means we track all ROIs)
    
    # Webpage URL
    LEADERBOARD_URL = "https://app.hyperliquid.xyz/leaderboard"
    
    def __init__(self):
        """Initialize the WhaleWalletFinder."""
        self.info = Info(hl_constants.MAINNET_API_URL)
        self.driver = None
        self.current_page = 1
        self.setup_driver()
        
    def setup_driver(self):
        """Set up the Chrome driver with appropriate options."""
        try:
            chrome_options = Options()
            # Disable headless mode temporarily for debugging
            # chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--remote-debugging-port=9222")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-infobars")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=chrome_options
            )
            
            # Set shorter page load timeout
            self.driver.set_page_load_timeout(15)
            self.driver.implicitly_wait(5)  # Set implicit wait for finding elements
            
            # Navigate to the page and wait for specific elements
            self.driver.get(self.LEADERBOARD_URL)
            self.wait_for_page_load()  # Use our custom wait instead of sleep
            
        except Exception as e:
            print(f"Error setting up driver: {e}")
            if self.driver:
                self.driver.quit()
            raise
            
    def wait_for_table(self):
        """Wait for table to be present and return it."""
        wait = WebDriverWait(self.driver, 10)
        table = wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        
        # Wait for table to have data and verify first row has a valid rank
        def table_has_valid_data(driver):
            try:
                rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
                if len(rows) == 0:
                    return False
                rank = rows[0].find_element(By.CSS_SELECTOR, "td:first-child").text.strip()
                return bool(rank and rank.isdigit())
            except:
                return False
        
        wait.until(table_has_valid_data)
        return table
        
    def wait_for_page_load(self):
        """Wait for page to load by checking for key elements."""
        try:
            wait = WebDriverWait(self.driver, 8)  # Reduced from 10 to 8 seconds
            # Wait for table and first row in a single condition
            wait.until(lambda d: (
                d.find_element(By.TAG_NAME, "table").is_displayed() and 
                len(d.find_elements(By.CSS_SELECTOR, "tbody tr")) > 0
            ))
            return True
        except Exception as e:
            print(f"Error waiting for page load: {e}")
            return False
            
    def get_leaderboard_data(self) -> List[Dict]:
        """Get current leaderboard data by scraping the webpage."""
        try:
            whale_data = []
            processed_count = 0
            max_retries = 3
            
            # Wait for table and get fresh reference to rows
            table = self.wait_for_table()
            rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
            total_rows = len(rows)
            
            # Get the expected first rank for this page
            expected_first_rank = (self.current_page - 1) * 10 + 1
            print(f"Found {total_rows} traders on page {self.current_page} (expecting ranks {expected_first_rank}-{expected_first_rank + 9})")
            
            while processed_count < total_rows:
                try:
                    # Get current row with retry mechanism
                    retry_count = 0
                    row = None
                    cells = None
                    
                    while retry_count < max_retries:
                        try:
                            table = self.wait_for_table()
                            # Verify we're still on the correct page
                            first_rank = table.find_element(By.CSS_SELECTOR, "tbody tr td:first-child").text.strip()
                            if int(first_rank) != expected_first_rank:
                                print(f"Wrong page detected (rank {first_rank}, expected {expected_first_rank})")
                                # Navigate directly to the correct page
                                self.driver.get(f"{self.LEADERBOARD_URL}?page={self.current_page}")
                                if not self.wait_for_page_load():
                                    retry_count += 1
                                    continue
                                table = self.wait_for_table()
                            
                            rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
                            row = rows[processed_count]
                            cells = row.find_elements(By.TAG_NAME, "td")
                            break
                        except Exception as e:
                            print(f"Retry {retry_count + 1} getting row {processed_count + 1}: {e}")
                            retry_count += 1
                            time.sleep(1)
                            self.driver.refresh()
                            if not self.wait_for_page_load():
                                continue
                    
                    if not cells or len(cells) < 6:
                        processed_count += 1
                        continue
                    
                    try:
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
                        roi = float(roi_parts[0]) if roi_parts else 0
                        
                        # Only process if ROI is positive, volume meets minimum, and account value meets minimum
                        if roi > self.MIN_ROI and volume >= self.MIN_30D_VOLUME and account_value >= self.MIN_ACCOUNT_VALUE:
                            # Store the current URL to return to the correct page
                            current_page_url = self.driver.current_url
                            
                            # Click on the trader to get to their page using JavaScript
                            self.driver.execute_script("arguments[0].click();", trader_cell)
                            
                            # Wait for URL to change and page to load
                            wait = WebDriverWait(self.driver, 10)
                            wait.until(lambda driver: self.LEADERBOARD_URL not in driver.current_url)
                            
                            # Get the current URL which contains the full address
                            trader_url = self.driver.current_url
                            full_address = trader_url.split("/")[-1]  # Get the last part of the URL
                            
                            print(f"Processing trader {processed_count + 1} (rank {expected_first_rank + processed_count}): {full_address}")
                            whale_data.append({
                                'address': full_address,
                                'account_value': account_value_text,
                                'volume_30d': volume,
                                'roi_30d': roi
                            })
                            
                            # Return directly to the correct page URL
                            self.driver.get(current_page_url)
                            if not self.wait_for_page_load():
                                # If waiting fails, try refreshing
                                self.driver.get(f"{self.LEADERBOARD_URL}?page={self.current_page}")
                                self.wait_for_page_load()
                            
                    except Exception as e:
                        print(f"Error processing trader data for row {processed_count + 1}: {e}")
                    
                    processed_count += 1
                    
                except Exception as e:
                    print(f"Error processing row {processed_count + 1}: {e}")
                    processed_count += 1
                    continue
            
            return whale_data
            
        except Exception as e:
            print(f"Error getting leaderboard data: {e}")
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
            
            # Try to find the Next button using JavaScript with debugging
            script = """
            const elements = document.querySelectorAll('.sc-jSUZER.jlrncQ');
            const results = [];
            for (const el of elements) {
                const svg = el.querySelector('svg');
                if (svg) {
                    results.push({
                        viewBox: svg.getAttribute('viewBox'),
                        width: svg.getAttribute('width'),
                        height: svg.getAttribute('height'),
                        innerHTML: svg.innerHTML,
                        parentClasses: el.getAttribute('class'),
                        parentStyle: el.getAttribute('style')
                    });
                }
            }
            return results;
            """
            svg_elements = self.driver.execute_script(script)
            
            print("\nFound SVG elements:")
            for idx, svg in enumerate(svg_elements):
                print(f"\nSVG {idx + 1}:")
                for key, value in svg.items():
                    print(f"{key}: {value}")
            
            # Now try to find the Next button by looking for the SVG with the right attributes
            script = """
            const elements = document.querySelectorAll('.sc-jSUZER.jlrncQ');
            for (const el of elements) {
                const svg = el.querySelector('svg');
                if (svg && svg.getAttribute('width') === '18' && svg.getAttribute('height') === '18') {
                    return el;
                }
            }
            return null;
            """
            next_button = self.driver.execute_script(script)
            
            if not next_button:
                print("\nCould not find Next button")
                return False
                
            print("\nFound Next button")
            
            # Print button state before click
            print("\nButton state before click:")
            print(f"Location: {next_button.location}")
            print(f"Classes: {next_button.get_attribute('class')}")
            print(f"Style: {next_button.get_attribute('style')}")
            
            # Scroll the button into view and click
            self.driver.execute_script("arguments[0].scrollIntoView(true);", next_button)
            time.sleep(1)  # Wait for scroll
            
            # Click using JavaScript
            self.driver.execute_script("arguments[0].click();", next_button)
            print("JavaScript click executed")
            
            time.sleep(2)  # Wait for click to take effect
            
            # Print current URL after click
            print(f"\nURL after click: {self.driver.current_url}")
            
            # Wait for new table and verify data
            try:
                time.sleep(2)  # Additional wait for data to load
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
    
    try:
        while True:
            print(f"\nProcessing page {finder.current_page}...")
            # Get leaderboard data for current page
            page_data = finder.get_leaderboard_data()
            
            if not page_data:
                print("No data found on current page.")
                finder.cleanup()  # Only cleanup if we truly have no data
                break
                
            # Add data from this page
            all_whale_data.extend(page_data)
            
            # Try to move to next page
            if finder.move_to_next_page():
                next_page_data = finder.get_leaderboard_data()
                print("\nNext page data collected successfully.")
            else:
                print("Could not move to next page. Stopping search.")
                finder.cleanup()  # Only cleanup if we can't move to next page
                break
        
        # Display results
        finder.display_whale_data(all_whale_data)
        
        # Save to file if we found any data
        if all_whale_data:
            output_file = os.path.join('resources', 'leaderboard_wallets.json')
            finder.save_whale_wallets(all_whale_data, output_file)
            
    except Exception as e:
        print(f"Error in main: {e}")
        finder.cleanup()  # Cleanup on error

if __name__ == "__main__":
    main()
