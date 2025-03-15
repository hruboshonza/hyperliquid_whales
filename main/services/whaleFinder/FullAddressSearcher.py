"""
Process wallet data to find full addresses and details for 30D period.
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

class FullAddressSearcher:
    def __init__(self):
        self.leaderboard_data = self._load_leaderboard_data()
        self.processed_wallets = []
        self.driver = None
        self.LEADERBOARD_URL = "https://app.hyperliquid.xyz/leaderboard"

    def _load_leaderboard_data(self) -> List[Dict]:
        """Load the leaderboard data from JSON file."""
        try:
            with open('resources/leaderboard_draft_data.json', 'r') as file:
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
                with open('resources/whale_wallets_detail.json', 'r') as file:
                    existing_data = json.load(file)
            except (FileNotFoundError, json.JSONDecodeError):
                existing_data = {'wallets': []}

            # Check if wallet already exists (checking both full and shortened addresses)
            wallet_exists = False
            for wallet in existing_data['wallets']:
                if (wallet['address'] == wallet_details['address'] or
                    wallet['address'].split('...')[0] == wallet_details['address'].split('...')[0]):
                    wallet.update(wallet_details)
                    wallet_exists = True
                    break

            if not wallet_exists:
                existing_data['wallets'].append(wallet_details)

            # Remove any entries with shortened addresses if we have their full address
            full_addresses = {w['address'] for w in existing_data['wallets'] if '...' not in w['address']}
            existing_data['wallets'] = [
                w for w in existing_data['wallets']
                if '...' not in w['address'] or w['address'].split('...')[0] not in {a[:len(w['address'].split('...')[0])] for a in full_addresses}
            ]

            with open('resources/whale_wallets_detail.json', 'w') as file:
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

    def search_wallet(self, wallet_prefix: str) -> Optional[Dict]:
        """Search for a wallet and return its details if found."""
        try:
            # Find and interact with search input
            search_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='Search by wallet address...']"))
            )
            search_input.clear()
            search_input.send_keys(wallet_prefix)
            search_input.send_keys(Keys.RETURN)
            time.sleep(3)  # Increased wait time for search results

            print(f"Searching for: {wallet_prefix}")
            
            # Find all matching rows
            rows = self.driver.find_elements(By.CSS_SELECTOR, "tbody tr")
            if not rows:
                print("No rows found in search results")
                return None

            print(f"Found {len(rows)} potential matches")

            # If multiple results, find the one with highest PNL
            highest_pnl = float('-inf')
            best_match_data = None
            current_url = self.driver.current_url

            for row in rows:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) >= 4:  # Make sure we have enough cells
                    try:
                        # Get trader name/address from first column
                        trader = cells[1].text.strip()
                        print(f"Checking trader: {trader}")
                        
                        # Get account value from the second column
                        account_value_text = cells[2].text.strip().replace('$', '').replace(',', '')
                        account_value = float(account_value_text)
                        
                        # Get ROI from the fourth column
                        roi_text = cells[4].text.strip().replace('%', '').replace(',', '.')
                        roi = float(roi_text)
                        
                        # Get PNL from the third column
                        pnl_text = cells[3].text.strip().replace('$', '').replace(',', '')
                        pnl = float(pnl_text)
                        
                        print(f"Values found - Account: ${account_value:,.2f}, ROI: {roi}%, PNL: ${pnl:,.2f}")
                        
                        # Check if meets minimum requirements for all traders
                        if account_value >= 300000 and roi >= 10:
                            # For custom names, check exact match
                            if '...' not in wallet_prefix and wallet_prefix == trader:
                                print(f"Found exact match for custom name: {trader}")
                                best_match_data = {
                                    'row': row,
                                    'pnl': pnl,
                                    'account_value': account_value,
                                    'roi': roi,
                                    'name': trader
                                }
                                break  # Exit loop as we found exact match
                            # For addresses, use highest PNL
                            elif pnl > highest_pnl:
                                highest_pnl = pnl
                                best_match_data = {
                                    'row': row,
                                    'pnl': pnl,
                                    'account_value': account_value,
                                    'roi': roi,
                                    'name': trader
                                }
                    except (ValueError, IndexError) as e:
                        print(f"Error parsing row data: {e}")
                        continue

            if best_match_data:
                try:
                    print(f"Best match found: {best_match_data['name']}")
                    # Click on the best match row
                    self.driver.execute_script("arguments[0].click();", best_match_data['row'].find_elements(By.TAG_NAME, "td")[1])
                    time.sleep(2)  # Wait for navigation
                    
                    # Get the full address from URL
                    full_address = self.driver.current_url.split('/')[-1]
                    
                    # Go back to the leaderboard
                    self.driver.get(current_url)
                    time.sleep(2)  # Wait for navigation back
                    
                    return {
                        'address': full_address,
                        'pnl': best_match_data['pnl'],
                        'account_value': best_match_data['account_value'],
                        'roi': best_match_data['roi'],
                        'name': best_match_data['name']
                    }
                except Exception as e:
                    print(f"Error getting full address: {e}")
                    return None

            return None

        except Exception as e:
            print(f"Error searching wallet {wallet_prefix}: {e}")
            return None

    def process_wallets(self):
        """Process all wallets from the leaderboard data."""
        try:
            self.setup_driver()
            
            for trader_data in self.leaderboard_data:
                wallet = trader_data['trader']
                wallet_prefix = self._extract_wallet_prefix(wallet)
                
                print(f"\nProcessing wallet: {wallet_prefix}")
                print(f"Original data: {trader_data}")
                
                # Search for the wallet (including custom names)
                max_retries = 3
                result = None
                rows_found = False
                
                for retry in range(max_retries):
                    result = self.search_wallet(wallet_prefix)
                    if result:  # If we got a valid result
                        wallet_details = {
                            'address': result['address'],
                            'original_address': wallet,
                            'pnl': result['pnl'],
                            'account_value': result['account_value'],
                            'roi': result['roi'],
                            'name': result.get('name', wallet)
                        }
                        print(f"Found wallet with Account Value: ${result['account_value']:,.2f}, ROI: {result['roi']}%")
                        self._save_wallet_details(wallet_details)
                        self.processed_wallets.append(wallet_details)
                        print(f"Successfully processed wallet: {result['address']}")
                        break
                    elif not self.driver.find_elements(By.CSS_SELECTOR, "tbody tr"):
                        # Only retry if no rows found
                        print(f"Retry {retry + 1}/{max_retries} for wallet: {wallet_prefix}")
                        time.sleep(2)
                    else:
                        # Found rows but didn't meet criteria
                        print(f"Found rows but no matching criteria for wallet: {wallet_prefix}")
                        break

                if not result and not self.driver.find_elements(By.CSS_SELECTOR, "tbody tr"):
                    print(f"No search results found for wallet: {wallet_prefix} after {max_retries} retries")

        except Exception as e:
            print(f"Error processing wallets: {e}")
        finally:
            if self.driver:
                self.driver.quit()
                self.driver = None

    def get_processed_wallets(self) -> List[Dict]:
        """Return the list of processed wallets."""
        return self.processed_wallets 