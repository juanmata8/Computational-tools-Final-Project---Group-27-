"""Run the Canadian Parliament data collection and preprocessing pipeline."""

from canadian_parliament.config import PROCESSED_DATA_DIR, RAW_DATA_DIR
from canadian_parliament.preprocessing import fetch_data, run


if __name__ == "__main__":
    print(f"Raw data directory: {RAW_DATA_DIR}")
    print(f"Processed data directory: {PROCESSED_DATA_DIR}")
    run()

