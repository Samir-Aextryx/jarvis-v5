"""Content-free error diagnostics with exact source location."""
import logging
import sys
import traceback

def report_failure(context):
    error = sys.exc_info()[1]
    frames = traceback.extract_tb(error.__traceback__) if error else []
    location = f"{frames[-1].filename}:{frames[-1].lineno}" if frames else "unknown"
    logging.getLogger("jarvis.errors").warning("%s failed: %s at %s", context, type(error).__name__, location)
