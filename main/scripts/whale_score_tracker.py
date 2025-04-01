#!/usr/bin/env python3
"""
Script to track new whale positions and calculate scores based on long vs short positions.
Runs every 15 minutes to detect new positions and update scores.
A new position is counted only when a whale opens a position in an asset they didn't have before.
Keeps history for 72 hours.
"""

import os
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, List, Set, Tuple, Optional
import concurrent.futures
from dataclasses import dataclass
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import atexit
import requests
import random

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.position_tracker import PositionTracker
from hyperliquid.info import Info
from hyperliquid.utils import constants as hl_constants
from config import (
    TIME_PERIOD_HOURS, MIN_POSITION_TRACKER_VALUE, DEBUG_MODE,
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
    
    def to_dict(self) -> Dict:
        """Convert snapshot to dictionary for JSON serialization."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'score': self.score,
            'longing_wallets': self.longing_wallets,
            'shorting_wallets': self.shorting_wallets
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ScoreSnapshot':
        """Create snapshot from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data['timestamp']),
            score=data['score'],
            longing_wallets=data['longing_wallets'],
            shorting_wallets=data['shorting_wallets']
        )

class WhaleScoreTracker:
    """Track new whale positions and calculate scores."""
    
    def __init__(self):
        self.info_client = Info(hl_constants.MAINNET_API_URL)  # Initialize with API URL
        self.position_tracker = PositionTracker()
        self.lock = threading.Lock()
        self.previous_positions: Dict[str, Set[str]] = {}  # wallet -> set of assets
        self.score_history: List[ScoreSnapshot] = []
        self.running = True
        self.history_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                       'resources', 'score_history.json')
        self.session = requests.Session()
        
        # Load existing history
        self.load_history()
        
        # Start the tracking thread
        self.tracking_thread = threading.Thread(target=self.run_tracking_loop)
        self.tracking_thread.daemon = True
        self.tracking_thread.start()
        
        # Register cleanup on exit
        atexit.register(self.cleanup)
    
    def save_history(self):
        """Save score history to JSON file."""
        try:
            with self.lock:
                history_data = [snapshot.to_dict() for snapshot in self.score_history]
                with open(self.history_file, 'w') as f:
                    json.dump(history_data, f, indent=2)
                if DEBUG_MODE:
                    print(f"Saved {len(history_data)} snapshots to {self.history_file}")
        except Exception as e:
            print(f"Error saving history: {str(e)}")
            if DEBUG_MODE:
                import traceback
                traceback.print_exc()
    
    def load_history(self):
        """Load score history from JSON file."""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    history_data = json.load(f)
                    self.score_history = [ScoreSnapshot.from_dict(data) for data in history_data]
                    # Remove old entries
                    cutoff_time = datetime.now() - timedelta(hours=72)
                    self.score_history = [s for s in self.score_history if s.timestamp > cutoff_time]
                    if DEBUG_MODE:
                        print(f"Loaded {len(self.score_history)} snapshots from {self.history_file}")
        except Exception as e:
            print(f"Error loading history: {str(e)}")
            if DEBUG_MODE:
                import traceback
                traceback.print_exc()
            self.score_history = []
    
    def make_request_with_retry(self, url: str, payload: dict, max_retries: int = 5) -> Optional[dict]:
        """Make a request with exponential backoff retry logic."""
        base_delay = 2  # Base delay in seconds
        max_delay = 30  # Maximum delay in seconds
        
        for attempt in range(max_retries):
            try:
                response = self.session.post(url, json=payload, headers={"Content-Type": "application/json"})
                
                if response.status_code == 200:
                    # Add a small delay even on successful requests to prevent rate limiting
                    time.sleep(0.5)
                    return response.json()
                elif response.status_code == 429:  # Rate limit
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    print(f"\rRate limit hit, waiting {delay:.1f} seconds...", end="")
                    time.sleep(delay)
                else:
                    print(f"Error response: {response.status_code} - {response.text}")
                    if attempt < max_retries - 1:
                        time.sleep(base_delay)
                    return None
                    
            except Exception as e:
                print(f"\rRequest error: {str(e)}")
                if attempt < max_retries - 1:
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    time.sleep(delay)
                else:
                    return None
                    
        return None

    def process_whale(self, whale_address: str) -> Tuple[Set[str], Dict[str, str]]:
        """Process a single whale's positions.
        
        Returns:
            Tuple containing:
            - Set of current assets
            - Dict mapping new assets to their position type (long/short)
        """
        try:
            # Get current positions with retry logic
            user_state = None
            for attempt in range(3):  # Try up to 3 times
                try:
                    user_state = self.info_client.user_state(whale_address)
                    break
                except Exception as e:
                    if attempt < 2:  # Don't sleep on last attempt
                        delay = 2 ** attempt + random.uniform(0, 1)
                        time.sleep(delay)
                    else:
                        print(f"Failed to get user state for {whale_address}: {str(e)}")
                        user_state = {}
            
            current_assets = set()
            
            if isinstance(user_state, dict) and 'assetPositions' in user_state:
                for pos in user_state['assetPositions']:
                    position_data = pos.get('position', {})
                    coin = position_data.get('coin')
                    size = float(position_data.get('coins', 0))
                    
                    if size != 0:  # Only include non-zero positions
                        mark_price = float(position_data.get('markPx', 0))
                        position_value = abs(size * mark_price)
                        
                        if position_value >= MIN_POSITION_TRACKER_VALUE:
                            current_assets.add(coin)
            
            # Get recent fills to detect new positions
            current_time = int(datetime.now().timestamp() * 1000)
            cutoff_time = int((datetime.now() - timedelta(minutes=15)).timestamp() * 1000)
            
            url = f"{hl_constants.MAINNET_API_URL}/info"
            payload = {
                "type": "userFillsByTime",
                "user": whale_address,
                "startTime": cutoff_time,
                "endTime": current_time,
                "aggregateByTime": False
            }
            
            fills = self.make_request_with_retry(url, payload)
            if not fills:
                return current_assets, {}
                
            new_positions = {}
            
            for fill in fills:
                if fill.get('orderType', '').lower() == 'twap':
                    continue
                    
                coin = fill.get('coin')
                dir_str = fill.get('dir', '')
                size = float(fill.get('sz', 0))
                price = float(fill.get('px', 0))
                position_value = abs(size * price)
                
                if position_value < MIN_POSITION_TRACKER_VALUE:
                    continue
                    
                # Only count new positions (not closes)
                if dir_str.startswith('Open'):
                    position_type = 'long' if dir_str == 'Open Long' else 'short'
                    new_positions[coin] = position_type
            
            if DEBUG_MODE:
                print(f"\nProcessing whale: {whale_address}")
                print(f"Current assets: {current_assets}")
                print(f"New positions: {new_positions}")
                print(f"Fills found: {len(fills)}")
            
            return current_assets, new_positions
            
        except Exception as e:
            print(f"Error processing whale {whale_address}: {str(e)}")
            if DEBUG_MODE:
                import traceback
                traceback.print_exc()
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
        
        # Process whales in batches
        BATCH_SIZE = 5  # Process 5 whales at a time
        BATCH_DELAY = 10  # Wait 10 seconds between batches
        
        for i in range(0, len(whale_addresses), BATCH_SIZE):
            batch = whale_addresses[i:i + BATCH_SIZE]
            print(f"\nProcessing batch {i//BATCH_SIZE + 1} of {(len(whale_addresses) + BATCH_SIZE - 1)//BATCH_SIZE}")
            
            # Process batch in parallel
            with ThreadPoolExecutor(max_workers=min(BATCH_SIZE, MAX_WORKERS)) as executor:
                future_to_whale = {
                    executor.submit(self.process_whale, address): address 
                    for address in batch
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
            
            # Add delay between batches
            if i + BATCH_SIZE < len(whale_addresses):
                print(f"Waiting {BATCH_DELAY} seconds before next batch...")
                time.sleep(BATCH_DELAY)
        
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
                    # Keep only last 72 hours of data
                    cutoff_time = datetime.now() - timedelta(hours=72)
                    self.score_history = [s for s in self.score_history if s.timestamp > cutoff_time]
                    # Save after each update
                    self.save_history()
                
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

    def cleanup(self):
        """Clean up resources on exit."""
        self.running = False
        if self.tracking_thread.is_alive():
            self.tracking_thread.join()
        # Save history one last time before exiting
        self.save_history()
        if hasattr(self, 'session'):
            self.session.close()
        if hasattr(self, 'info_client'):
            self.info_client.close()

if __name__ == "__main__":
    print("Starting Whale Score Tracker with debug mode enabled...")
    DEBUG_MODE = True  # Enable debug mode
    tracker = WhaleScoreTracker()
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        tracker.cleanup() 