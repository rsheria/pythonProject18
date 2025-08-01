# utils.py

import logging
import re
import unicodedata
import hashlib
def sanitize_filename(filename):
    """
    Sanitizes a filename by replacing or removing invalid characters.

    Parameters:
    - filename (str): The original filename.

    Returns:
    - str: The sanitized filename.
    """
    # Replace spaces with underscores
    orig = filename
    filename = filename.replace(' ', '_')

    # Replace & with 'and'
    filename = filename.replace('&', 'and')

    # Normalize the filename to NFKD form and encode to ASCII bytes, ignoring non-ASCII characters
    filename = unicodedata.normalize('NFKD', filename).encode('ASCII', 'ignore').decode('ASCII')

    # Remove any remaining characters that are not allowed in Windows filenames
    filename = re.sub(r'[^a-zA-Z0-9_\-\.]', '', filename)

    # Fallback to a hash value when nothing remains after sanitization
    if not filename:
        filename = hashlib.md5(orig.encode('utf-8')).hexdigest()

    logging.debug(f"Sanitized filename/category: '{filename}'")

    return filename
