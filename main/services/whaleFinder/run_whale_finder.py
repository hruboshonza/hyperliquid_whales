"""
Run the whale finder process to collect and process wallet data.
"""

import os
import sys

# Add the project root directory to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, project_root)

from main.services.whaleFinder.LoadWalletsDrafts import LoadWalletsDrafts, save_to_json
from main.services.whaleFinder.FullAddressSearcher import FullAddressSearcher

def main():
    print("Starting whale finder process...")
    
    # Step 1: Load wallet drafts from leaderboard
    print("\nStep 1: Loading wallet drafts from leaderboard (30D period)...")
    loader = LoadWalletsDrafts()
    try:
        loader.setup_driver()
        all_data = []
        while True:
            page_data = loader.get_current_page_data()
            if not page_data:
                break
            all_data.extend(page_data)
            if not loader.move_to_next_page():
                break
        save_to_json(all_data)
    finally:
        loader.cleanup()
    
    # Step 2: Process wallets to get full addresses and details
    print("\nStep 2: Processing wallets to get full addresses and details...")
    processor = FullAddressSearcher()
    processor.process_wallets()
    
    # Print summary
    processed_wallets = processor.get_processed_wallets()
    print(f"\nProcessed {len(processed_wallets)} wallets successfully.")
    

if __name__ == "__main__":
    main() 