from functools import lru_cache
from pymongo import MongoClient
import certifi
from config.settings import settings

DB_NAME = "whofy"


@lru_cache
def get_client() -> MongoClient:
    uri = settings.mongodb_uri
    if not uri:
        raise RuntimeError("MONGODB_URI environment variable is not set")
    return MongoClient(uri, tlsCAFile=certifi.where())


def get_db():
    return get_client()[DB_NAME]
