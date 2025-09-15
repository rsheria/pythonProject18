#!/usr/bin/env python3
"""Simple syntax check for crash protection."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all files can be imported without syntax errors."""
    try:
        print("Testing crash protection imports...")
        from utils.crash_protection import safe_execute
        print("SUCCESS: crash_protection imported")

        print("Testing core selenium_bot import...")
        from core.selenium_bot import ForumBotSelenium
        print("SUCCESS: selenium_bot imported")

        print("Testing uploady handler import...")
        from uploaders.uploady_upload_handler import UploadyUploadHandler
        print("SUCCESS: uploady_upload_handler imported")

        print("Testing rapidgator handler import...")
        from uploaders.rapidgator_upload_handler import RapidgatorUploadHandler
        print("SUCCESS: rapidgator_upload_handler imported")

        print("\n" + "="*40)
        print("ALL SYNTAX CHECKS PASSED!")
        print("Upload handlers are ready for testing.")
        print("="*40)

    except SyntaxError as e:
        print(f"SYNTAX ERROR: {e}")
        print(f"File: {e.filename}")
        print(f"Line: {e.lineno}")
        return False
    except Exception as e:
        print(f"IMPORT ERROR: {e}")
        return False

    return True

if __name__ == "__main__":
    success = test_imports()
    sys.exit(0 if success else 1)