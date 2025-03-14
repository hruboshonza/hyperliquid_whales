"""
Dynamic pagination handler for Hyperliquid leaderboard.
"""

from typing import Dict, List, Optional
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException

class LeaderboardPagination:
    """Handle dynamic pagination of Hyperliquid leaderboard data."""
    
    LEADERBOARD_URL = "https://app.hyperliquid.xyz/leaderboard"
    
    def __init__(self):
        """Initialize the pagination handler."""
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
            
            # Set page load timeout
            self.driver.set_page_load_timeout(30)
            
            # Navigate to the page
            self.driver.get(self.LEADERBOARD_URL)
            time.sleep(5)  # Initial page load
            
            # Print page title and URL for debugging
            print(f"Page title: {self.driver.title}")
            print(f"Current URL: {self.driver.current_url}")
            
            # Try to find pagination elements
            try:
                pagination = self.driver.find_elements(By.CSS_SELECTOR, "nav[aria-label='pagination']")
                if pagination:
                    print("Found pagination element")
                    buttons = pagination[0].find_elements(By.TAG_NAME, "button")
                    print(f"Found {len(buttons)} pagination buttons")
                    for button in buttons:
                        print(f"Button text: {button.text}, aria-label: {button.get_attribute('aria-label')}")
                        print(f"Button classes: {button.get_attribute('class')}")
                        print(f"Button enabled: {button.is_enabled()}")
            except Exception as e:
                print(f"Error checking pagination: {e}")
            
        except Exception as e:
            print(f"Error setting up driver: {e}")
            if self.driver:
                self.driver.quit()
            raise

    def wait_for_table(self):
        """Wait for table to be present and return it."""
        wait = WebDriverWait(self.driver, 30)
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
                "Rank", "Trader", "Account Value", "Volume (7D)", "ROI (7D)", "PnL (7D)"
            ))
            print("-" * 95)
            
            # Get all rows
            rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
            page_data = []
            
            for idx, row in enumerate(rows, 1):
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
                            'volume_7d': volume,
                            'roi_7d': roi,
                            'pnl_7d': pnl
                        }
                        page_data.append(trader_data)
                        
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
    
    def cleanup(self):
        """Clean up resources."""
        if self.driver:
            self.driver.quit()
            self.driver = None

def main():
    pagination = LeaderboardPagination()
    
    try:
        # Get first page data
        first_page_data = pagination.get_current_page_data()
        print("\nFirst page data collected successfully.")
        
        # Move to second page
        if pagination.move_to_next_page():
            second_page_data = pagination.get_current_page_data()
            print("\nSecond page data collected successfully.")
        else:
            print("\nCould not move to second page.")
        
    finally:
        pagination.cleanup()

if __name__ == "__main__":
    main() 