#!/usr/bin/env python3
"""
Script to track new whale positions and calculate scores based on long vs short positions.
Runs every 15 minutes to detect new positions and update scores.
A new position is counted only when a whale opens a position in an asset they didn't have before.
"""

import os
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, List, Set, Tuple
import concurrent.futures
from dataclasses import dataclass
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import atexit

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.position_tracker import PositionTracker
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants
from config import (
    TIME_PERIOD_HOURS, MIN_POSITION_VALUE, DEBUG_MODE,
    MAX_RETRIES, BASE_DELAY, MAX_DELAY, RATE_LIMIT_DELAY,
    MAX_WORKERS
)

@dataclass
class ScoreSnapshot:
    """Data class to hold score information for a specific timestamp."""
    timestamp: datetime
    score: int  # Difference between new longs and new shorts
    longing_wallets: int  # Number of wallets that opened new long positions
    shorting_wallets: int  # Number of wallets that opened new short positions

class WhaleScoreTracker:
    """Track new whale positions and calculate scores."""
    
    def __init__(self):
        self.info_client = Info()
        self.position_tracker = PositionTracker()
        self.lock = threading.Lock()
        self.previous_positions: Dict[str, Set[str]] = {}  # wallet -> set of assets
        self.score_history: List[ScoreSnapshot] = []
        self.running = True
        
        # Start the tracking thread
        self.tracking_thread = threading.Thread(target=self.run_tracking_loop)
        self.tracking_thread.daemon = True
        self.tracking_thread.start()
        
        # Register cleanup on exit
        atexit.register(self.cleanup)
    
    def cleanup(self):
        """Clean up resources on exit."""
        self.running = False
        if self.tracking_thread.is_alive():
            self.tracking_thread.join()
    
    def process_whale(self, whale_address: str) -> Tuple[Set[str], Dict[str, str]]:
        """Process a single whale's positions.
        
        Returns:
            Tuple containing:
            - Set of current assets
            - Dict mapping new assets to their position type (long/short)
        """
        try:
            positions = self.info_client.get_user_positions(whale_address)
            current_assets = set()
            new_positions = {}
            
            for asset, pos in positions.items():
                if abs(pos['position_value']) >= MIN_POSITION_VALUE:
                    current_assets.add(asset)
                    # Check if this is a new position
                    if (whale_address not in self.previous_positions or 
                        asset not in self.previous_positions[whale_address]):
                        position_type = 'long' if pos['size'] > 0 else 'short'
                        new_positions[asset] = position_type
            
            return current_assets, new_positions
            
        except Exception as e:
            print(f"Error processing whale {whale_address}: {str(e)}")
            return set(), {}
    
    def analyze_positions(self) -> ScoreSnapshot:
        """Analyze all whale positions and return a score snapshot."""
        # Get whale addresses from JSON file
        json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                'resources', 'activeWhales.json')
        
        with open(json_path, 'r') as f:
            active_whales = json.load(f)
            
        whale_addresses = [whale['fullAddress'] for whale in active_whales['wallets']]
        
        new_longs = 0
        new_shorts = 0
        longing_wallets = set()
        shorting_wallets = set()
        
        # Process whales in parallel
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_whale = {
                executor.submit(self.process_whale, address): address 
                for address in whale_addresses
            }
            
            for future in concurrent.futures.as_completed(future_to_whale):
                whale_address = future_to_whale[future]
                try:
                    current_assets, new_positions = future.result()
                    
                    # Update previous positions
                    with self.lock:
                        self.previous_positions[whale_address] = current_assets
                    
                    # Count new positions
                    has_new_long = False
                    has_new_short = False
                    for position_type in new_positions.values():
                        if position_type == 'long':
                            new_longs += 1
                            has_new_long = True
                        else:  # short
                            new_shorts += 1
                            has_new_short = True
                    
                    if has_new_long:
                        longing_wallets.add(whale_address)
                    if has_new_short:
                        shorting_wallets.add(whale_address)
                        
                except Exception as e:
                    print(f"Error processing whale {whale_address}: {str(e)}")
        
        # Calculate score (difference between new longs and shorts)
        score = new_longs - new_shorts
        
        # Create and return snapshot
        snapshot = ScoreSnapshot(
            timestamp=datetime.now(),
            score=score,
            longing_wallets=len(longing_wallets),
            shorting_wallets=len(shorting_wallets)
        )
        
        return snapshot
    
    def run_tracking_loop(self):
        """Main tracking loop that runs every 15 minutes."""
        while self.running:
            try:
                snapshot = self.analyze_positions()
                
                with self.lock:
                    self.score_history.append(snapshot)
                    # Keep only last 24 hours of data
                    cutoff_time = datetime.now() - timedelta(hours=24)
                    self.score_history = [s for s in self.score_history if s.timestamp > cutoff_time]
                
                # Print current snapshot
                print(f"\nSnapshot at {snapshot.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"Score (Longs - Shorts): {snapshot.score}")
                print(f"Wallets opening new longs: {snapshot.longing_wallets}")
                print(f"Wallets opening new shorts: {snapshot.shorting_wallets}")
                
                # Sleep for 15 minutes
                time.sleep(15 * 60)
                
            except Exception as e:
                print(f"Error in tracking loop: {str(e)}")
                time.sleep(60)  # Wait a minute before retrying on error

if __name__ == "__main__":
    tracker = WhaleScoreTracker()
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        tracker.cleanup() 