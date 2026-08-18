"""
Migration script to backfill compound 'fingerprint' strings onto older MongoDB documents.
Run this if the deduplication strategy changes and older records need their fingerprint fields recomputed.
"""
from pymongo import UpdateOne
from listings.shared.storage import get_client, DB_NAME, JOBS_COLLECTION, _fingerprint

def backfill():
    client = get_client()
    collection = client[DB_NAME][JOBS_COLLECTION]
    
    total = collection.count_documents({})
    print(f"Total documents in collection: {total}")
    
    batch_size = 1000
    cursor = collection.find({}, {"source": 1, "source_job_id": 1})
    
    operations = []
    processed = 0
    updated_count = 0
    
    for doc in cursor:
        source = doc.get("source")
        source_job_id = doc.get("source_job_id")
        
        # We need both to create the new fingerprint
        if not source or not source_job_id:
            continue
            
        new_fp = _fingerprint(source, source_job_id)
        
        operations.append(
            UpdateOne({"_id": doc["_id"]}, {"$set": {"fingerprint": new_fp}})
        )
        processed += 1
        
        if len(operations) >= batch_size:
            res = collection.bulk_write(operations, ordered=False)
            updated_count += res.modified_count
            operations = []
            print(f"Processed {processed}/{total} documents...", flush=True)
            
    if operations:
        res = collection.bulk_write(operations, ordered=False)
        updated_count += res.modified_count
        
    print(f"Processed: {processed}")
    print(f"Updated (modified): {updated_count}")
    client.close()

if __name__ == "__main__":
    backfill()
