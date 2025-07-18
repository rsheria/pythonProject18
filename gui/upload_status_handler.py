import hashlib
import logging
import os
import time

from PyQt5.QtCore import QMutex, QMutexLocker


class UploadStatusHandler:
    def __init__(self, bot=None):
        """Initialize the Upload Status Handler.

        Args:
            bot: Optional bot instance for handling uploads
        """
        self.bot = bot
        self._upload_states = {}  # Track upload states
        self.upload_locks = {}  # Thread-safe locks per file
        self._active_uploads = set()  # Currently active uploads
        self._completed_uploads = set()  # Successfully completed uploads
        self._file_progress = {}  # Track individual file progress

    def set_bot(self, bot):
        """Set the bot instance after initialization if needed."""
        self.bot = bot

    def upload_file(self, file_path, thread_id, category_name, progress_callback=None):
        """
        Enhanced upload handling with status tracking and verification.

        Args:
            file_path: Path to file to upload
            thread_id: Associated thread ID
            category_name: Category name
            progress_callback: Optional callback for progress updates

        Returns:
            dict: Upload result containing URLs and status
        """
        try:
            # Generate unique upload key
            upload_key = self._generate_upload_key(file_path, thread_id)

            # Check if already uploading
            if upload_key in self._active_uploads:
                logging.info(f"Upload already in progress for {file_path}")
                return self._get_upload_state(upload_key)

            # Check if already completed
            if upload_key in self._completed_uploads:
                logging.info(f"File already uploaded: {file_path}")
                return self._get_upload_state(upload_key)

            # Initialize upload state
            self._upload_states[upload_key] = {
                'status': 'initializing',
                'progress': 0,
                'urls': [],
                'error': None,
                'timestamp': time.time()
            }
            self._active_uploads.add(upload_key)

            # Verify bot is available
            if not self.bot:
                raise Exception("Bot instance not available")

            # Verify and refresh token if needed
            if not self.bot.validate_and_refresh_upload_token():
                raise Exception("Failed to obtain valid upload token")

            # Initialize upload session
            upload_result = self._initiate_upload(file_path, upload_key, progress_callback)
            if not upload_result:
                raise Exception("Failed to initialize upload")

            # Process upload result
            self._process_upload_result(upload_key, upload_result)

            return self._get_upload_state(upload_key)

        except Exception as e:
            self._handle_upload_error(upload_key, str(e))
            return self._get_upload_state(upload_key)

    def _initiate_upload(self, file_path, upload_key, progress_callback):
        """Handle the upload initialization and process."""
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")

            file_size = os.path.getsize(file_path)
            if file_size == 0:
                raise ValueError("File is empty")

            # Update state
            self._update_state(upload_key, 'uploading', progress=0)

            # Create progress tracking wrapper
            def progress_wrapper(current, total):
                progress = int((current / total) * 100)
                self._update_state(upload_key, 'uploading', progress=progress)
                if progress_callback:
                    progress_callback(current, total)

            # Perform upload
            return self.bot.initiate_upload_session(file_path, progress_callback=progress_wrapper)

        except Exception as e:
            logging.error(f"Upload initialization error: {str(e)}")
            raise

    def _process_upload_result(self, upload_key, result):
        """Process the upload result and update state."""
        try:
            if isinstance(result, dict):
                urls = result.get('uploaded_urls', [])
                mega_url = result.get('mega_url')

                if urls or mega_url:
                    self._update_state(upload_key, 'completed',
                                       progress=100,
                                       urls=urls,
                                       mega_url=mega_url)
                    self._completed_uploads.add(upload_key)
                else:
                    raise Exception("No URLs in upload result")
            else:
                raise Exception("Invalid upload result format")

        except Exception as e:
            self._handle_upload_error(upload_key, str(e))

    def _update_state(self, upload_key, status, **kwargs):
        """Update the state for an upload."""
        if upload_key in self._upload_states:
            self._upload_states[upload_key].update(
                status=status,
                timestamp=time.time(),
                **kwargs
            )

    def _handle_upload_error(self, upload_key, error_msg):
        """Handle upload errors."""
        if upload_key:
            self._update_state(upload_key, 'error', error=error_msg)
            self._active_uploads.discard(upload_key)
        logging.error(f"Upload error: {error_msg}")

    def _get_upload_state(self, upload_key):
        """Get the current state of an upload."""
        return self._upload_states.get(upload_key, {
            'status': 'unknown',
            'progress': 0,
            'urls': [],
            'error': None
        })

    def _generate_upload_key(self, file_path, thread_id):
        """Generate a unique key for tracking uploads."""
        return f"{thread_id}:{hashlib.md5(file_path.encode()).hexdigest()}"

    def cleanup_old_states(self, max_age_hours=24):
        """Clean up old upload states."""
        current_time = time.time()
        expired_keys = []

        for key, state in self._upload_states.items():
            if state.get('timestamp', 0) < current_time - (max_age_hours * 3600):
                expired_keys.append(key)

        for key in expired_keys:
            self._upload_states.pop(key, None)
            self._completed_uploads.discard(key)
            self._active_uploads.discard(key)