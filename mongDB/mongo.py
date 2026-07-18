import os
from functools import lru_cache
from pymongo import MongoClient

DB_NAME = "whofy"


@lru_cache
def get_client() -> MongoClient:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI environment variable is not set")
    return MongoClient(uri)


def get_db():
    return get_client()[DB_NAME]
