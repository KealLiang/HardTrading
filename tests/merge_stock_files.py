#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import os
import re
from collections import defaultdict

import pandas as pd

# 合并./data/astocks下的重复code的股票文件

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler('stock_files_merge_log.txt', mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()


def get_stock_code(filename):
    """Extract stock code from filename."""
    match = re.match(r'(\d{6})_.*\.csv', filename)
    return match.group(1) if match else None


def count_data_rows(filepath):
    """Count the number of data rows in a CSV file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return sum(1 for _ in f) - 1  # Subtract header if exists
    except Exception as e:
        logger.error(f"Error counting rows in {filepath}: {e}")
        return 0


def merge_stock_files():
    """
    Merge duplicate stock files in data/astocks directory.
    Files with the same stock code are merged, keeping the one with more data as the target.
    """
    stock_dir = os.path.join('..', 'data', 'astocks')

    # Check if directory exists
    if not os.path.exists(stock_dir):
        logger.error(f"Directory {stock_dir} does not exist!")
        return

    # Get all CSV files in the directory
    all_files = [f for f in os.listdir(stock_dir) if f.lower().endswith('.csv')]
    logger.info(f"Found {len(all_files)} CSV files in {stock_dir}")

    # Group files by stock code
    stock_files = defaultdict(list)
    for filename in all_files:
        stock_code = get_stock_code(filename)
        if stock_code:
            stock_files[stock_code].append(filename)

    # Find duplicates (stocks with more than one file)
    duplicates = {code: files for code, files in stock_files.items() if len(files) > 1}
    logger.info(f"Found {len(duplicates)} stocks with duplicate files")

    # Statistics counters
    merged_count = 0
    deleted_count = 0

    # Process each group of duplicate files
    for stock_code, filenames in duplicates.items():
        logger.info(f"Processing stock code: {stock_code}, found {len(filenames)} files")

        # Find file with most data to use as target
        file_sizes = [(f, count_data_rows(os.path.join(stock_dir, f))) for f in filenames]
        target_file, max_rows = max(file_sizes, key=lambda x: x[1])
        logger.info(f"  Target file: {target_file} with {max_rows} rows")

        # Read all files data into DataFrames
        all_data = []
        for filename in filenames:
            filepath = os.path.join(stock_dir, filename)
            try:
                # Read CSV without header since we'll set column names manually
                df = pd.read_csv(filepath, header=None)
                if not df.empty:
                    all_data.append(df)
                    logger.info(f"  Successfully read {len(df)} rows from {filename}")
                else:
                    logger.warning(f"  Empty file: {filename}")
            except Exception as e:
                logger.error(f"  Error reading {filename}: {e}")

        if not all_data:
            logger.warning(f"  No valid data found for stock {stock_code}, skipping")
            continue

        # Combine all data
        combined_df = pd.concat(all_data, ignore_index=True)

        # Set column names if needed (assuming standard format)
        if combined_df.shape[1] >= 12:  # Check if we have at least the expected columns
            combined_df.columns = [
                                      'date', 'code', 'open', 'close', 'high', 'low',
                                      'volume', 'amount', 'amplitude', 'pct_change', 'change', 'turnover'
                                  ][:combined_df.shape[1]]  # Only use as many column names as we have columns

        # Remove duplicates based on date
        if 'date' in combined_df.columns:
            before_dedup = len(combined_df)
            combined_df = combined_df.drop_duplicates(subset=['date'], keep='first')
            after_dedup = len(combined_df)
            if before_dedup > after_dedup:
                logger.info(f"  Removed {before_dedup - after_dedup} duplicate rows")

        # Sort by date ascending
        if 'date' in combined_df.columns:
            try:
                combined_df['date'] = pd.to_datetime(combined_df['date'])
                combined_df = combined_df.sort_values('date')
                combined_df['date'] = combined_df['date'].dt.strftime('%Y-%m-%d')
            except Exception as e:
                logger.warning(f"  Could not parse dates for sorting: {e}")

        # Save merged data to target file
        output_path = os.path.join(stock_dir, target_file)
        try:
            combined_df.to_csv(output_path, index=False, header=False)
            logger.info(f"  Saved merged data with {len(combined_df)} rows to {target_file}")
            merged_count += 1
        except Exception as e:
            logger.error(f"  Error saving merged data to {target_file}: {e}")
            continue

        # Delete the source files (except the target)
        for filename in filenames:
            if filename != target_file:
                try:
                    os.remove(os.path.join(stock_dir, filename))
                    logger.info(f"  Deleted merged source file: {filename}")
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"  Error deleting {filename}: {e}")

    # Summary
    logger.info(f"Merge operation completed:")
    logger.info(f"- Found {len(duplicates)} stocks with duplicate files")
    logger.info(f"- Successfully merged {merged_count} stocks")
    logger.info(f"- Deleted {deleted_count} redundant files")
    logger.info(f"See stock_files_merge_log.txt for detailed log")


if __name__ == "__main__":
    logger.info("Starting stock files merge process")
    merge_stock_files()
    logger.info("Stock files merge process completed")
