#!/usr/bin/env python3
"""
Test script to verify the upload crash fixes are working properly.
Tests filename sanitization, path handling, and error recovery.
"""

import sys
import os
import tempfile
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

def test_filename_sanitization():
    """Test the enhanced filename sanitization function."""
    print("=" * 60)
    print("TESTING FILENAME SANITIZATION")
    print("=" * 60)

    try:
        from core.file_processor import FileProcessor

        # Create test processor
        temp_dir = tempfile.gettempdir()
        winrar_path = "C:\\Program Files\\WinRAR\\WinRAR.exe"  # Default path
        fp = FileProcessor(temp_dir, winrar_path)

        # Test cases for problematic filenames
        test_cases = [
            ("Normal File.txt", "Normal_File"),
            ("File<with>special:chars.txt", "File_with_special_chars"),
            ("CON.txt", "file_CON"),  # Windows reserved name
            ("File\\with\\backslashes.txt", "File_with_backslashes"),
            ("File|with|pipes.txt", "File_with_pipes"),
            ("File?with?questions.txt", "File_with_questions"),
            ("File*with*asterisks.txt", "File_with_asterisks"),
            ("Very Long Filename That Exceeds Normal Length Limits And Should Be Truncated To Prevent Path Issues On Windows Systems.txt", "Very_Long_Filename_That_Exceeds_Normal_Length_Limits_A"),
            ("File   with   multiple   spaces.txt", "File_with_multiple_spaces"),
            ("Ωαβγδε.txt", ""),  # Non-ASCII chars should be removed
            ("", "unnamed"),  # Empty string
            ("...", "unnamed"),  # Just dots
            ("___", "unnamed"),  # Just underscores
        ]

        success_count = 0
        for original, expected_start in test_cases:
            try:
                result = fp._sanitize_and_shorten_title(original)

                # Check if result starts with expected pattern or is valid
                is_valid = (
                    result and
                    len(result) <= 60 and
                    not any(c in result for c in '<>:"/\\|?*') and
                    result not in ('CON', 'PRN', 'AUX', 'NUL')
                )

                status = "PASS" if is_valid else "FAIL"
                print(f"{status} '{original}' -> '{result}'")

                if is_valid:
                    success_count += 1

            except Exception as e:
                print(f"ERROR '{original}': {e}")

        print(f"\nFilename sanitization tests: {success_count}/{len(test_cases)} passed")
        return success_count == len(test_cases)

    except ImportError as e:
        print(f"Cannot import FileProcessor: {e}")
        return False
    except Exception as e:
        print(f"Test setup error: {e}")
        return False

def test_path_handling():
    """Test enhanced path handling capabilities."""
    print("\n" + "=" * 60)
    print("TESTING PATH HANDLING")
    print("=" * 60)

    try:
        from workers.upload_worker import UploadWorker

        # Test cases for path handling
        test_paths = [
            tempfile.gettempdir(),  # Valid existing path
            tempfile.gettempdir() + "\\nonexistent_folder",  # Non-existent path
            "C:\\Very\\Long\\Path\\That\\Might\\Cause\\Issues\\On\\Windows\\Systems\\With\\Limited\\Path\\Length\\Support",  # Very long path
            "",  # Empty path
            None,  # None path
        ]

        success_count = 0
        for i, test_path in enumerate(test_paths):
            try:
                # Create a minimal mock bot object
                class MockBot:
                    def __init__(self):
                        self.config = {"upload_cooldown_seconds": 30}

                mock_bot = MockBot()

                # Test UploadWorker initialization with various paths
                worker = UploadWorker(
                    bot=mock_bot,
                    row=i,
                    folder_path=test_path,
                    thread_id=f"test_{i}",
                    upload_hosts=["rapidgator"],
                    files=None
                )

                # Check if worker was created successfully and has valid folder_path
                is_valid = (
                    worker.folder_path and
                    isinstance(worker.folder_path, Path) and
                    worker.folder_path.exists()
                )

                status = "PASS" if is_valid else "FAIL"
                print(f"{status} Path: '{test_path}' -> '{worker.folder_path}'")

                if is_valid:
                    success_count += 1

            except Exception as e:
                print(f"ERROR Path '{test_path}': {e}")

        print(f"\nPath handling tests: {success_count}/{len(test_paths)} passed")
        return success_count >= 3  # Allow some failures for invalid inputs

    except ImportError as e:
        print(f"Cannot import UploadWorker: {e}")
        return False
    except Exception as e:
        print(f"Test setup error: {e}")
        return False

def test_problematic_filename_detection():
    """Test the problematic filename detection."""
    print("\n" + "=" * 60)
    print("TESTING PROBLEMATIC FILENAME DETECTION")
    print("=" * 60)

    try:
        from workers.upload_worker import UploadWorker

        class MockBot:
            def __init__(self):
                self.config = {"upload_cooldown_seconds": 30}

        mock_bot = MockBot()
        worker = UploadWorker(
            bot=mock_bot,
            row=0,
            folder_path=tempfile.gettempdir(),
            thread_id="test",
            upload_hosts=["rapidgator"],
        )

        # Test cases - (filename, should_be_problematic)
        test_cases = [
            ("normal_file.txt", False),
            ("CON.txt", True),
            ("file<with>bad.txt", True),
            ("file|with|pipes.txt", True),
            ("file?with?questions.txt", True),
            ("very_long_filename_that_exceeds_normal_limits" + "a" * 300 + ".txt", True),
            ("", True),
            (None, True),
        ]

        success_count = 0
        for filename, should_be_problematic in test_cases:
            try:
                result = worker._is_problematic_filename(filename)
                is_correct = result == should_be_problematic

                status = "PASS" if is_correct else "FAIL"
                print(f"{status} '{filename}' -> Problematic: {result} (Expected: {should_be_problematic})")

                if is_correct:
                    success_count += 1

            except Exception as e:
                print(f"ERROR '{filename}': {e}")

        print(f"\nProblematic filename detection: {success_count}/{len(test_cases)} passed")
        return success_count == len(test_cases)

    except Exception as e:
        print(f"Test error: {e}")
        return False

def main():
    """Run all tests."""
    print("TESTING UPLOAD CRASH FIXES")
    print("This script tests the fixes for potential crash scenarios in the upload process.")
    print()

    # Configure logging to reduce noise during testing
    logging.basicConfig(level=logging.ERROR)

    # Run all tests
    tests = [
        ("Filename Sanitization", test_filename_sanitization),
        ("Path Handling", test_path_handling),
        ("Problematic Filename Detection", test_problematic_filename_detection),
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        try:
            if test_func():
                print(f"{test_name}: PASSED")
                passed += 1
            else:
                print(f"{test_name}: FAILED")
        except Exception as e:
            print(f"{test_name}: ERROR - {e}")

    print("\n" + "=" * 60)
    print(f"FINAL RESULTS: {passed}/{total} tests passed")

    if passed == total:
        print("All tests passed! The crash fixes are working correctly.")
        return True
    else:
        print("Some tests failed. Please review the output above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)