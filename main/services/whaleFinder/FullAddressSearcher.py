"""
Process wallet data to find full addresses and details for 30D period.
Classifies whales as Active (volume > $1M) or Sleeping.
"""

import json
from typing import List, Dict, Optional
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import time
import os

class FullAddressSearcher:
    # Maximum number of wallets to process before stopping
    MAX_WALLETS_TO_PROCESS =2000
    DATA_SAVE_FILE = "resources/activeWhales.json"
    DRAFT_DATA_LOAD_FILE = "resources/leaderboard_draft_data.json"

    def __init__(self):
        self.leaderboard_data = self._load_leaderboard_data()
        self.processed_wallets = []
        self.driver = None
        self.LEADERBOARD_URL = "https://app.hyperliquid.xyz/leaderboard"

    def _load_leaderboard_data(self) -> List[Dict]:
        """Load the leaderboard data from JSON file."""
        try:
            with open(self.DRAFT_DATA_LOAD_FILE, 'r') as file:
                return json.load(file)
        except FileNotFoundError:
            print("Leaderboard data file not found")
            return []
        except json.JSONDecodeError:
            print("Error decoding leaderboard JSON data")
            return []

    def _extract_wallet_prefix(self, wallet_address: str) -> str:
        """Extract the prefix of the wallet address before '...' or return full if custom name."""
        if '...' in wallet_address:
            return wallet_address.split('...')[0]
        return wallet_address  # Return full address/name if it's a custom name

    def _save_wallet_details(self, wallet_details: Dict) -> None:
        """Save processed wallet details to JSON file."""
        try:
            try:
                with open(self.DATA_SAVE_FILE, 'r') as file:
                    existing_data = json.load(file)
            except (FileNotFoundError, json.JSONDecodeError):
                existing_data = {'wallets': []}

            # Check if wallet already exists
            wallet_exists = False
            for wallet in existing_data['wallets']:
                if wallet['fullAddress'] == wallet_details['fullAddress']:
                    wallet.update(wallet_details)
                    wallet_exists = True
                    break

            if not wallet_exists:
                existing_data['wallets'].append(wallet_details)

            # Create directory if it doesn't exist
            os.makedirs('resources', exist_ok=True)

            with open(self.DATA_SAVE_FILE, 'w') as file:
                json.dump(existing_data, file, indent=4)

        except Exception as e:
            print(f"Error saving wallet details: {e}")

    def setup_driver(self):
        """Initialize the webdriver."""
        if not self.driver:
            options = webdriver.ChromeOptions()
            options.add_argument('--headless')  # Run in headless mode
            self.driver = webdriver.Chrome(options=options)
            self.driver.get(self.LEADERBOARD_URL)
            time.sleep(2)  # Wait for page to load
            self._switch_to_30d_period()

    def _switch_to_30d_period(self):
        """Switch the leaderboard to 30D period."""
        try:
            # Wait for the page to load completely
            time.sleep(3)
            
            # Try multiple selectors for the period button
            selectors = [
                "button[aria-haspopup='listbox']",
                "button.MuiButtonBase-root",
                "//button[contains(., '24H') or contains(., '7D') or contains(., '30D')]"
            ]
            
            period_selector = None
            for selector in selectors:
                try:
                    if selector.startswith("//"):
                        period_selector = WebDriverWait(self.driver, 3).until(
                            EC.presence_of_element_located((By.XPATH, selector))
                        )
                    else:
                        period_selector = WebDriverWait(self.driver, 3).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                    if period_selector:
                        break
                except:
                    continue
            
            if not period_selector:
                print("Could not find period selector")
                return
                
            # Click the period selector
            self.driver.execute_script("arguments[0].click();", period_selector)
            time.sleep(2)
            
            # Try different approaches to find and click the 30D option
            try:
                # First try: Look for li elements
                options = self.driver.find_elements(By.CSS_SELECTOR, "li[role='option']")
                for option in options:
                    if "30D" in option.text:
                        self.driver.execute_script("arguments[0].click();", option)
                        time.sleep(1)
                        return
                        
                # Second try: Look for any clickable element with "30D"
                options = self.driver.find_elements(By.XPATH, "//*[contains(text(), '30D')]")
                for option in options:
                    if option.is_displayed():
                        self.driver.execute_script("arguments[0].click();", option)
                        time.sleep(1)
                        return
                        
            except Exception as e:
                print(f"Error clicking 30D option: {e}")
                
            print("Could not find 30D period option")
            
        except Exception as e:
            print(f"Error switching to 30D period: {e}")
            # Try to restart the session
            self.driver.quit()
            self.driver = None
            self.setup_driver()

    def _validate_session(self):
        """Validate current session and restart if invalid."""
        try:
            # Try to interact with the page
            self.driver.find_element(By.CSS_SELECTOR, "input[placeholder='Search by wallet address...']")
            return True
        except:
            print("Session expired, restarting...")
            self.driver.quit()
            self.driver = None
            self.setup_driver()
            return True

    def search_wallet(self, wallet_prefix: str) -> Optional[Dict]:
        """Search for a wallet and return its details if found."""
        try:
            # Validate session before each search
            self._validate_session()
            
            # Always go back to the main leaderboard page first
            self.driver.get(self.LEADERBOARD_URL)
            time.sleep(1)  # Wait for page load
            
            # Find and interact with search input
            search_input = WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='Search by wallet address...']"))
            )
            
            # Clear the search input using JavaScript
            self.driver.execute_script("arguments[0].value = '';", search_input)
            search_input.clear()  # Also use Selenium's clear for good measure
            time.sleep(1)  # Wait after clearing
            
            # Enter new search term
            search_input.send_keys(wallet_prefix)
            search_input.send_keys(Keys.RETURN)
            time.sleep(1)  # Wait for search results
            
            # Find all matching rows
            rows = self.driver.find_elements(By.CSS_SELECTOR, "tbody tr")
            if not rows:
                print("❌ No matches found")
                return None

            print(f"📋 Found {len(rows)} matches")
            
            # Store the current URL before we start processing rows
            current_url = self.driver.current_url

            for row in rows:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) >= 4:  # Make sure we have enough cells
                    try:
                        # Get trader name/address from first column
                        trader = cells[1].text.strip()
                        
                        # Get account value from the second column
                        account_value_text = cells[2].text.strip().replace('$', '').replace(',', '')
                        account_value = float(account_value_text)
                        
                        # Get ROI from the fourth column
                        roi_text = cells[4].text.strip().replace('%', '').replace(',', '.')
                        roi = float(roi_text)
                        
                        # Get volume from the third column
                        volume_text = cells[3].text.strip().replace('$', '').replace(',', '')
                        volume = float(volume_text)
                        
                        # Check if meets minimum requirements
                        if account_value >= 300000 and roi >= 10:
                            # For custom names, check exact match
                            if '...' not in wallet_prefix and wallet_prefix == trader:
                                # Click on the row to get full address
                                self.driver.execute_script("arguments[0].click();", cells[1])
                                time.sleep(1)  # Wait for navigation
                                
                                # Get the full address from URL
                                full_address = self.driver.current_url.split('/')[-1]
                                
                                # Go back to the leaderboard
                                self.driver.get(current_url)
                                time.sleep(1)  # Wait for navigation back
                                
                                return {
                                    'fullAddress': full_address,
                                    'accountValue': account_value,
                                    'roi': roi
                                }
                            # For addresses, check if prefix matches
                            elif '...' in trader and trader.startswith(wallet_prefix):
                                # Click on the row to get full address
                                self.driver.execute_script("arguments[0].click();", cells[1])
                                time.sleep(1)  # Wait for navigation
                                
                                # Get the full address from URL
                                full_address = self.driver.current_url.split('/')[-1]
                                
                                # Go back to the leaderboard
                                self.driver.get(current_url)
                                time.sleep(1)  # Wait for navigation back
                                
                                return {
                                    'fullAddress': full_address,
                                    'accountValue': account_value,
                                    'roi': roi
                                }
                                
                    except (ValueError, IndexError) as e:
                        continue

            print("❌ No matches met criteria")
            return None

        except Exception as e:
            print(f"❌ Error: {str(e)}")
            return None
        finally:
            # Always go back to the main page after search
            try:
                self.driver.get(self.LEADERBOARD_URL)
                time.sleep(2)
            except:
                pass

    def process_wallets(self):
        """Process all wallets from the leaderboard data."""
        try:
            self.setup_driver()
            
            for trader_data in self.leaderboard_data:
                # Check if we've reached the processing limit
                if len(self.processed_wallets) >= self.MAX_WALLETS_TO_PROCESS:
                    print(f"\n✋ Reached limit of {self.MAX_WALLETS_TO_PROCESS} wallets")
                    break
                    
                wallet = trader_data['trader']
                wallet_prefix = self._extract_wallet_prefix(wallet)
                
                print(f"\n📝 Processing: {wallet_prefix}")
                
                # Search for the wallet
                result = self.search_wallet(wallet_prefix)
                
                if result:
                    self._save_wallet_details(result)
                    self.processed_wallets.append(result)
                    print(f"✅ Success: {result['fullAddress']} (${result['accountValue']:,.2f}, ROI: {result['roi']}%)")
                else:
                    print(f"❌ Failed: {wallet_prefix}")

        except Exception as e:
            print(f"❌ Error: {str(e)}")
        finally:
            if self.driver:
                self.driver.quit()
                self.driver = None

    def get_processed_wallets(self) -> List[Dict]:
        """Return the list of processed wallets."""
        return self.processed_wallets 