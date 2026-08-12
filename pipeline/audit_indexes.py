"""
Utility script to audit MongoDB collection indexes, showing index sizes and usage stats.
Run this script to identify unused or large indexes that could be removed to improve write performance.
"""
from listings.shared.storage import get_client, DB_NAME, JOBS_COLLECTION
import pprint
import pymongo

def audit():
    client = get_client()
    db = client[DB_NAME]
    indexes = list(db[JOBS_COLLECTION].list_indexes())
    
    print("--- Current Indexes ---")
    for idx in indexes:
        print(f"Name: {idx['name']}")
        print(f"Key: {idx['key']}")
        if "unique" in idx:
            print(f"Unique: {idx['unique']}")
        if "weights" in idx:
            print(f"Weights: {idx['weights']}")
        print("-" * 20)

if __name__ == "__main__":
    audit()
