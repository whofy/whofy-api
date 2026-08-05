from dotenv import load_dotenv
load_dotenv()

from listings.run_scrapper import run_ingestion

if __name__ == "__main__":
    run_ingestion()
