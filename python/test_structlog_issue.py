#!/usr/bin/env python3
"""Test script to reproduce the structlog issue on Python 3.13."""

import logging
import sys
import tempfile
import os
from pathlib import Path
from src.symphony.observability.log_file import setup_logging
import structlog

def test_console_logging():
    print("\n=== Testing Console Logging ===")

    # Setup logging without file output
    setup_logging(level=logging.INFO)

    # Get a logger and try to log some messages
    logger = structlog.get_logger("test.console")

    print("Testing log messages...")

    # Test different types of log messages
    logger.info("Console info message", key="value")
    logger.warning("Console warning message", count=42)
    logger.error("Console error message", error="sample error")

    # Try to trigger the specific error mentioned in the issue
    print("Testing with exception...")
    try:
        raise ValueError("Console test exception")
    except ValueError:
        logger.exception("Console exception message")

    print("Console logging test completed!")

def test_file_logging():
    print("\n=== Testing File Logging ===")

    # Create a temporary directory for logs
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Using temporary log directory: {temp_dir}")

        # Setup logging with file output
        setup_logging(logs_root=temp_dir, level=logging.INFO)

        # Get a logger and try to log some messages
        logger = structlog.get_logger("test.file")

        print("Testing log messages with file output...")

        # Test different types of log messages
        logger.info("File info message", key="value")
        logger.warning("File warning message", count=42)
        logger.error("File error message", error="sample error")

        # Try to trigger the specific error mentioned in the issue
        print("Testing with exception...")
        try:
            raise ValueError("File test exception")
        except ValueError:
            logger.exception("File exception message")

        # Check that the log file was created and contains content
        log_file = Path(temp_dir) / "symphony.log"
        if log_file.exists():
            print(f"Log file created successfully: {log_file}")
            with open(log_file, 'r') as f:
                content = f.read()
                print(f"Log file contains {len(content)} characters")
                # Print first few lines to verify JSON format
                lines = content.strip().split('\n')
                print(f"First log line: {lines[0][:100]}...")
        else:
            print("ERROR: Log file was not created!")

    print("File logging test completed!")

def main():
    print(f"Python version: {sys.version}")

    # Test console logging
    test_console_logging()

    # Test file logging
    test_file_logging()

    print("\n=== All tests completed! ===")

if __name__ == "__main__":
    main()