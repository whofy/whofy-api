from dotenv import load_dotenv
load_dotenv()

from pymongo import UpdateOne

from mongDB.mongo import get_db
from sources.shared.enrich import detect_experience, detect_work_type, extract_required_skills


def main():
    db = get_db()
    collection = db.jobs

    operations = []
    for doc in collection.find({}, {"title": 1, "location": 1, "description": 1}):
        title = doc.get("title", "")
        location = doc.get("location", "Not specified")
        description = doc.get("description", "")
        operations.append(
            UpdateOne(
                {"_id": doc["_id"]},
                {"$set": {
                    "work_type": detect_work_type(title, location, description),
                    "experience_level": detect_experience(title, description),
                    "required_skills": extract_required_skills(title, description),
                }},
            )
        )

    if not operations:
        print("No jobs found to backfill.")
        return

    result = collection.bulk_write(operations, ordered=False)
    print(f"Backfilled {result.modified_count} of {len(operations)} jobs.")


if __name__ == "__main__":
    main()
