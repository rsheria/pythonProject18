# mega_upload_handler.py

import os
import logging
from mega import Mega
from dotenv import load_dotenv
import requests


class MegaUploadHandler:
    def __init__(self):
        """
        Initializes the MegaUploadHandler by loading credentials and setting up the Mega client.
        """
        load_dotenv()  # Load environment variables from .env file

        self.username = os.getenv('MEGAUPLOAD_USERNAME')
        self.password = os.getenv('MEGAUPLOAD_PASSWORD')

        if not self.username or not self.password:
            raise ValueError("MegaUpload credentials are missing in the environment variables.")

        self.mega_client = self.initialize_mega_client()

    def initialize_mega_client(self):
        """
        Initializes and logs into the Mega client.

        Returns:
            Mega: An authenticated Mega client instance.
        """
        mega = Mega()
        try:
            m = mega.login(self.username, self.password)
            logging.info("Logged into MegaUpload successfully.")
            return m
        except Exception as e:
            logging.error(f"Failed to log into MegaUpload: {e}")
            raise

    def upload_file(self, file_path, progress_callback=None):
        """
        Uploads a file to MegaUpload and returns the public link.

        Parameters:
            file_path (str): The path to the file to be uploaded.
            progress_callback (callable): Optional callback function to track upload progress.
                                       Takes current and total bytes as parameters.

        Returns:
            str: The public URL of the uploaded file.
        """
        if not self.mega_client:
            logging.error("MegaUpload client is not initialized. Cannot upload.")
            return None

        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")

            total_size = os.path.getsize(file_path)
            
            # Patch the upload method to track progress
            original_post = requests.post
            last_bytes_read = 0

            def post_with_progress(*args, **kwargs):
                nonlocal last_bytes_read
                if 'data' in kwargs:
                    data = kwargs['data']
                    if hasattr(data, 'len'):  # For MultipartEncoderMonitor
                        chunk_size = data.len
                    elif isinstance(data, (str, bytes)):  # For regular data
                        chunk_size = len(data)
                    else:
                        chunk_size = 0
                        
                    if chunk_size > 0:
                        last_bytes_read += chunk_size
                        if progress_callback:
                            progress_callback(last_bytes_read, total_size)
                return original_post(*args, **kwargs)

            # Monkey patch the post method
            requests.post = post_with_progress

            try:
                logging.info(f"Uploading '{file_path}' to MegaUpload...")
                file = self.mega_client.upload(file_path)
                
                # Send final progress update
                if progress_callback:
                    progress_callback(total_size, total_size)
                    
                if file:
                    # Get the file handle and generate public link
                    public_url = self.mega_client.get_upload_link(file)
                    logging.info(f"Uploaded to MegaUpload successfully: {public_url}")
                    return public_url
                else:
                    logging.error("Upload to MegaUpload failed - no file data returned")
                    return None

            finally:
                # Restore original post method
                requests.post = original_post

        except FileNotFoundError as e:
            logging.error(f"File not found error: {e}")
            return None
        except Exception as e:
            logging.error(f"Exception during MegaUpload: {e}", exc_info=True)
            return None
