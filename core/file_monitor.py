import hashlib
import logging
import os


class FileMonitor:
    def __init__(self):
        self.file_sizes = {}
        self.file_hashes = {}

    def verify_file_integrity(self, file_path: str) -> bool:
        """
        Verify file integrity by checking size and hash.

        Args:
            file_path (str): Path to file to verify

        Returns:
            bool: True if file is valid, False otherwise
        """
        try:
            if not os.path.exists(file_path):
                logging.error(f"File not found: {file_path}")
                return False

            # Get current file size
            current_size = os.path.getsize(file_path)

            # If we have a previous size, compare
            if file_path in self.file_sizes:
                if current_size != self.file_sizes[file_path]:
                    logging.error(f"File size mismatch for {file_path}")
                    return False

            # Calculate MD5 hash
            current_hash = self.calculate_file_hash(file_path)
            if file_path in self.file_hashes:
                if current_hash != self.file_hashes[file_path]:
                    logging.error(f"File hash mismatch for {file_path}")
                    return False

            # Store current values
            self.file_sizes[file_path] = current_size
            self.file_hashes[file_path] = current_hash

            return True

        except Exception as e:
            logging.error(f"Error verifying file {file_path}: {str(e)}")
            return False

    @staticmethod
    def calculate_file_hash(file_path: str, chunk_size: int = 8192) -> str:
        """Calculate MD5 hash of file."""
        md5 = hashlib.md5()
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(chunk_size), b''):
                    md5.update(chunk)
            return md5.hexdigest()
        except Exception as e:
            logging.error(f"Error calculating hash for {file_path}: {str(e)}")
            return ''