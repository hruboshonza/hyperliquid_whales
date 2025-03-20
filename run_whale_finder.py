"""
Run the whale finder process to collect and process wallet data.
"""

from main.services.whaleFinder.LoadWalletsDrafts import LoadWalletsDrafts, main as load_wallets
from main.services.whaleFinder.FullAddressSearcher import FullAddressSearcher

def main():
    print("Starting whale finder process...")
    
    # Step 1: Load wallet drafts from leaderboard
    # print("\nStep 1: Loading wallet drafts from leaderboard (30D period)...")
    # load_wallets()
    
    ## Step 2: Process wallets to get full addresses and details
    print("\nStep 2: Processing wallets to get full addresses and details...")
    processor = FullAddressSearcher()
    processor.process_wallets()
    
    ## Print summary
    processed_wallets = processor.get_processed_wallets()
    print(f"\nProcessed {len(processed_wallets)} wallets successfully.")
    

if __name__ == "__main__":
    main() 