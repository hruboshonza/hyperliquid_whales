from main.services.whaleFinder.FullAddressSearcher import WhaleDetailProcess

def main():
    processor = WhaleDetailProcess()
    print("Starting to process whale wallets...")
    processor.process_wallets()
    
    processed_wallets = processor.get_processed_wallets()
    print(f"\nProcessed {len(processed_wallets)} wallets:")
    for wallet in processed_wallets:
        print(f"Address: {wallet['address']}")
        print(f"Account Value: ${wallet['account_value']:,.2f}")
        print(f"PNL: ${wallet['pnl']:,.2f}")
        print("-" * 50)

if __name__ == "__main__":
    main() 