#!/usr/bin/env python3
"""
This script is used as a one-shot job inside an Azure Container Instance.
It measures the response time for a given URL and prints the time in milliseconds.
"""

import sys
import time
import argparse
import requests

def measure_response_time(url):
    """
    Measures the response time (in milliseconds) for a GET request to the given URL.
    """
    try:
        start_time = time.monotonic()
        response = requests.get(url, timeout=30)  # Increase timeout as required
        # Ensure a successful response; otherwise, report error
        response.raise_for_status()
        end_time = time.monotonic()
        elapsed_time_ms = (end_time - start_time) * 1000
        return elapsed_time_ms
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return None

def main():
    parser = argparse.ArgumentParser(description="Measure webpage response time")
    parser.add_argument('--url', required=True, help="Target URL to measure response time for")
    args = parser.parse_args()

    elapsed_ms = measure_response_time(args.url)
    if elapsed_ms is not None:
        # Output a plain floating point value for parsing.
        print(elapsed_ms)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()