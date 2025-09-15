#!/usr/bin/env python3
"""
Simple test for filename sanitization improvements.
"""

import re
import unicodedata

def enhanced_sanitize_filename(text, max_length=60):
    """Enhanced filename sanitization with better Windows compatibility."""
    if not text or not isinstance(text, str):
        return "unnamed"

    try:
        # Normalize unicode characters
        text = unicodedata.normalize('NFKD', text)

        # Remove Windows reserved characters
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]', '', text)

        # Replace multiple spaces/dots with single underscore
        text = re.sub(r'[\s\.]+', '_', text)

        # Remove Windows reserved names
        reserved_names = {
            'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5',
            'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 'LPT3', 'LPT4',
            'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
        }
        if text.upper() in reserved_names:
            text = f"file_{text}"

        # Keep only safe ASCII characters
        text = ''.join(c for c in text if c.isascii() and (c.isalnum() or c in '_-.'))

        # Remove leading/trailing dots and underscores
        text = text.strip('._')

        # Ensure not empty
        if not text:
            text = "unnamed"

        # Limit length
        if len(text) > max_length:
            text = text[:max_length].rstrip('._')

        # Final safety check
        if not text or len(text) < 1:
            text = "unnamed"

        return text

    except Exception:
        return "unnamed"

def test_filename_sanitization():
    """Test filename sanitization."""
    print("TESTING FILENAME SANITIZATION")
    print("=" * 50)

    test_cases = [
        ("Normal File.txt", True),
        ("File<with>special:chars.txt", True),
        ("CON.txt", True),
        ("File\\with\\backslashes.txt", True),
        ("File|with|pipes.txt", True),
        ("File?with?questions.txt", True),
        ("File*with*asterisks.txt", True),
        ("Very Long Filename That Exceeds Normal Length Limits.txt", True),
        ("File   with   multiple   spaces.txt", True),
        ("", True),
        ("...", True),
    ]

    passed = 0
    for original, should_pass in test_cases:
        try:
            result = enhanced_sanitize_filename(original)

            is_safe = (
                result and
                len(result) <= 60 and
                not any(c in result for c in '<>:"/\\|?*') and
                result not in ('CON', 'PRN', 'AUX', 'NUL')
            )

            if is_safe == should_pass:
                print(f"PASS: '{original}' -> '{result}'")
                passed += 1
            else:
                print(f"FAIL: '{original}' -> '{result}'")

        except Exception as e:
            print(f"ERROR: '{original}': {e}")

    print(f"\nResults: {passed}/{len(test_cases)} tests passed")
    return passed == len(test_cases)

if __name__ == "__main__":
    success = test_filename_sanitization()
    print("\n" + "=" * 50)
    if success:
        print("SUCCESS: All filename sanitization tests passed!")
    else:
        print("FAILURE: Some tests failed.")