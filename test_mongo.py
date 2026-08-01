from pymongo import MongoClient
import certifi
import os
from dotenv import load_dotenv

load_dotenv()
uri = os.getenv("MONGODB_URI")
try:
    print("Connecting to:", uri)
    client = MongoClient(uri, tlsCAFile=certifi.where(), tlsAllowInvalidCertificates=True, serverSelectionTimeoutMS=5000)
    db = client["whofy"]
    print("Ping:", db.command("ping"))
    print("Jobs count:", db.jobs.count_documents({}))
except Exception as e:
    print("Error:", e)
