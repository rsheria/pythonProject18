import os
import logging
import shutil
import subprocess
import re
import glob
import uuid
import time
import random
from pathlib import Path
from typing import List, Optional, Set
from config.config import DATA_DIR    # ← استيراد DATA_DIR


class FileProcessor:
    def __init__(self, download_dir: str, winrar_path: str):
        """Initialize FileProcessor with necessary paths and settings."""
        # تأكد من وجود DATA_DIR
        os.makedirs(DATA_DIR, exist_ok=True)
        self.download_dir = Path(download_dir)  # Base download directory
        self.winrar_path = Path(winrar_path)

        # Get the actual project path
        self.project_path = Path(__file__).parent
        self.banned_files_dir = self.project_path / "banned_files"

        # Ensure directories exist
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.banned_files_dir.mkdir(parents=True, exist_ok=True)

        # Configure logging
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(os.path.join(DATA_DIR, "file_processor.log")),
                logging.StreamHandler()
            ]
        )
        logging.getLogger(__name__).setLevel(logging.DEBUG)

        # Load banned files from the banned_files directory
        self.banned_files = self._load_banned_files()

        # Track files for cleanup
        self.processed_files: Set[Path] = set()
        self.extracted_paths: Set[Path] = set()

        # Constants
        self.GIGABYTE = 1024 * 1024 * 1024
        self.ARCHIVE_EXTENSIONS = {'.rar', '.zip', '.7z'}

    def process_downloads(
        self,
        thread_dir: Path,
        downloaded_files: List[str],
        thread_title: str,
        password: str | None = None,
    ) -> Optional[List[str]]:
        """
        Process downloaded files and return list of processed file paths.
        1) Move the downloaded files to the thread_dir.
        2) If there's exactly one file or a multi-part scenario => rename final archive with thread_title.
        3) If multiple distinct files => now re-process each one with its original name.
        """
        try:
            # First sanitize & shorten the thread title to avoid Windows path issues
            cleaned_thread_title = self._sanitize_and_shorten_title(thread_title)

            # Make sure the thread directory exists
            thread_dir.mkdir(parents=True, exist_ok=True)

            # Move downloaded files to the thread_dir
            moved_files = self._organize_downloads(downloaded_files, thread_dir)
            if not moved_files:
                logging.error("No files were moved to the thread directory.")
                return None

            # Detect if we have a single item or multiple distinct items
            if self._detect_if_single_item(moved_files):
                # Single item => rename final archived output to cleaned_thread_title
                processed_files = self._process_as_single_item(
                    moved_files, thread_dir, cleaned_thread_title, password
                )
            else:
                # Multiple distinct files => process each with its own original name
                processed_files = self._process_multi_distinct(
                    moved_files, thread_dir, password
                )
            
            # 🧹 Final comprehensive cleanup - keep only processed files
            if processed_files:
                self._final_directory_cleanup(thread_dir, processed_files)
                
            return processed_files

        except Exception as e:
            logging.error(f"Error in process_downloads: {str(e)}")
            return None

    def _sanitize_and_shorten_title(self, text: str, max_length: int = 60) -> str:
        """
        Removes special/invalid path characters, replaces spaces with underscores,
        strips non-printables, and shortens to max_length if needed.
        """
        # Remove invalid characters
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        # Replace spaces with underscores
        text = text.replace(' ', '_')
        # Keep only printable
        text = ''.join(c for c in text if c.isprintable())
        text = text.strip()
        # If too long, truncate
        if len(text) > max_length:
            text = text[:max_length]
        return text

    def _detect_if_single_item(self, moved_files: List[Path]) -> bool:
        """
        Decide if these moved_files represent a "single item" scenario or multiple distinct items.

        A single item scenario might be:
          - Exactly 1 file, or
          - A multi-part .partX.rar, etc., all with the same base name.
        Otherwise, assume multiple distinct items.
        """
        if len(moved_files) == 1:
            # Only 1 file => single item
            return True

        # Check multi-part .partX.rar scenario
        possible_bases = set()
        part_count = 0
        for f in moved_files:
            if f.suffix.lower() == '.rar':
                match = re.search(r'^(.*)\.part\d+\.rar$', f.name, flags=re.IGNORECASE)
                if match:
                    base_name = match.group(1)
                    possible_bases.add(base_name)
                    part_count += 1
                else:
                    return False
            else:
                return False

        # If all are multi-part .rar with the same base, it's a single item
        if part_count == len(moved_files) and len(possible_bases) == 1:
            return True
        return False

    def _process_as_single_item(
        self,
        moved_files: List[Path],
        thread_dir: Path,
        thread_title: str,
        password: str | None = None,
    ) -> List[str]:
        """
        Single item scenario: either 1 file or a multi-part .rar.
        If it's an archive => extract, re-archive with thread_title.
        If non-archive => create .rar with thread_title.
        """
        successful_files = []
        for file_path in moved_files:
            if self._is_archive_file(file_path):
                if file_path in self.processed_files:
                    logging.info(f"Skipping already processed archive: {file_path}")
                    continue
                new_archives = self.handle_archive_file(
                    file_path, thread_dir, thread_title, password
                )
                if new_archives:
                    successful_files.extend(new_archives)
                    self.processed_files.update(Path(arch) for arch in new_archives)
                    logging.info(f"Successfully processed archive: {file_path}")
                else:
                    logging.error(f"Failed to process archive: {file_path}")
            else:
                # Non-archive => compress into RAR named after thread_title
                processed_file = self.handle_other_file(file_path, thread_dir, thread_title)
                if processed_file:
                    successful_files.append(processed_file)
                    self.processed_files.add(Path(processed_file))
        return successful_files

    def _process_multi_distinct(
            self, moved_files: List[Path], thread_dir: Path, password: str | None = None
    ) -> List[str]:
        """
        Multiple distinct files => now we actually process each file with its own original base name.
        - If archive => extract, re-archive with the same base name
        - If non-archive => re-archive with the same base name
        """
        final_files = []
        for file_path in moved_files:
            if self._is_archive_file(file_path):
                # Process it like single item but use the file's original stem
                new_archives = self.handle_archive_file(
                    file_path,
                    thread_dir,
                    file_path.stem,  # final name = original base
                    password,
                )
                final_files.extend(new_archives)
            else:
                # Non-archive => compress into .rar named after the original base
                processed_file = self.handle_other_file(
                    file_path,
                    thread_dir,
                    file_path.stem
                )
                if processed_file:
                    final_files.append(processed_file)
        return final_files

    def handle_archive_file(
        self,
        archive_path: Path,
        download_folder: Path,
        thread_title: str,
        password: str | None = None,
    ) -> List[str]:
        """Handle archive processing with format preservation, splitting,
           and final rename to thread_title for single-item or per-file scenarios."""
        extract_dir = None
        try:
            original_format = archive_path.suffix.lower()
            is_zip = (original_format == '.zip')

            # Check if multi-part .partX.rar
            is_multipart = False
            all_parts = []
            if (not is_zip) and re.search(r'\.part\d+\.rar$', archive_path.name, re.IGNORECASE):
                base_name = re.sub(r'\.part\d+\.rar$', '', archive_path.name, flags=re.IGNORECASE)
                part1_path = download_folder / f"{base_name}.part1.rar"
                if part1_path.exists():
                    archive_path = part1_path
                    is_multipart = True
                    all_parts = sorted(download_folder.glob(f"{base_name}.part*.rar"))
                    logging.info(f"Detected multi-part archive with {len(all_parts)} parts")

            # Create extraction dir with original file name + "_extracted"
            if is_multipart:
                # Use base name from multi-part detection
                original_name = base_name
            else:
                # Use original file stem (without extension)
                original_name = archive_path.stem
            
            extract_dir_name = f"{original_name}_extracted"
            extract_dir = download_folder / extract_dir_name
            if extract_dir.exists():
                self._safely_remove_directory(extract_dir)
            extract_dir.mkdir(exist_ok=True)

            # Extract with retries
            max_retries = 3
            extract_success = False
            for attempt in range(max_retries):
                logging.info(
                    f"Extracting {original_format} archive: {archive_path} (Attempt {attempt + 1})"
                )
                extract_success = self._extract_archive(
                    archive_path, extract_dir, password
                )
                if extract_success:
                    # 📁 Flatten directory structure - move all files to root level
                    self._flatten_extracted_directory(extract_dir)
                    break
                if attempt < max_retries - 1:
                    time.sleep(2)

            if not extract_success:
                raise Exception("Archive extraction failed after all attempts")

            # Modify files (hash) + remove banned
            self._modify_files_for_hash_safely(extract_dir)
            self._remove_banned_files_safely(extract_dir)

            # Summation
            total_size = sum(
                f.stat().st_size
                for f in extract_dir.rglob('*')
                if f.is_file() and f.name.lower() != 'desktop.ini'
            )
            logging.info(f"Total size of extracted files: {total_size / self.GIGABYTE:.2f} GB")

            # Re-archive everything => final name based on thread_title
            unique_id = uuid.uuid4().hex
            temp_suffix = f"_temp_{unique_id}"
            temp_archive_base = download_folder / f"{thread_title}{temp_suffix}"

            success = False
            for attempt in range(max_retries):
                if is_zip:
                    success = self._create_zip_archive(extract_dir, temp_archive_base)
                else:
                    success = self._create_rar_archive(extract_dir, temp_archive_base)
                if success:
                    break
                if attempt < max_retries - 1:
                    time.sleep(2)

            if not success:
                raise Exception("Archive creation failed after all attempts")

            # Gather newly created archives
            new_archives = []
            if is_zip:
                new_archives.extend(
                    glob.glob(str(download_folder / f"{thread_title}{temp_suffix}.z*"))
                )
            else:
                new_archives.extend(
                    glob.glob(str(download_folder / f"{thread_title}{temp_suffix}.part*.rar"))
                )
                if not new_archives:
                    single_rar = download_folder / f"{thread_title}{temp_suffix}.rar"
                    if single_rar.exists():
                        new_archives.append(str(single_rar))

            if not new_archives:
                raise Exception("No temporary archive parts were created")

            # Remove original archive(s)
            if is_multipart and all_parts:
                self._safely_remove_original_archives(archive_path, all_parts)
            else:
                self._safely_remove_original_archives(archive_path, None)

            # Rename the temp ones => remove the _temp_uuid portion
            final_archives = self._safely_rename_archives(new_archives, temp_suffix)

            # Cleanup
            self._safely_remove_directory(extract_dir)

            return final_archives

        except Exception as e:
            logging.error(f"Error processing archive: {str(e)}")
            if extract_dir and extract_dir.exists():
                self._safely_remove_directory(extract_dir)
            return []

    def handle_other_file(
        self,
        file_path: Path,
        target_dir: Path,
        thread_title: str
    ) -> Optional[str]:
        """
        For a single file scenario, re-archive a non-archive file
        into a .rar named after thread_title, then remove the original file.
        (Also used in multi-distinct logic, with thread_title = original filename's stem.)
        """
        try:
            archive_path = target_dir / f"{thread_title}.rar"

            # Add random bytes for hash
            if file_path.stat().st_size >= 10:
                try:
                    with open(file_path, 'ab') as f:
                        f.write(os.urandom(random.randint(1, 32)))
                except Exception as e:
                    logging.warning(f"Could not modify file hash for {file_path}: {str(e)}")

            cmd = [
                str(self.winrar_path),
                'a',
                '-ep1',
                '-m0',
                '-ma5',
                '-rr3p',
                '-y',
                '-x*.ini',
                str(archive_path),
                str(file_path)
            ]

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    if result.returncode in [0, 1]:
                        self._safely_remove_file(file_path)
                        logging.info(f"Created archive {archive_path} and removed original file: {file_path}")
                        return str(archive_path)
                    else:
                        if attempt == max_retries - 1:
                            logging.error(f"WinRAR failed to create archive for {file_path}")
                            logging.error(f"WinRAR Output: {result.stdout}")
                            logging.error(f"WinRAR Errors: {result.stderr}")
                        else:
                            time.sleep(1)
                            continue
                except Exception as e:
                    if attempt == max_retries - 1:
                        logging.error(f"Error creating archive for {file_path}: {str(e)}")
                    else:
                        time.sleep(1)
                        continue
            return None

        except Exception as e:
            logging.error(f"Error handling file {file_path}: {str(e)}")
            return None

    def _flatten_extracted_directory(self, extract_dir: Path) -> None:
        """
        📁 Flatten directory structure: move all files from subdirectories to root level.
        This ensures a clean single-level folder structure after extraction.
        """
        if not extract_dir.exists():
            return
            
        try:
            # Get all files in subdirectories (not in root)
            files_to_move = []
            for item in extract_dir.rglob('*'):
                if item.is_file() and item.parent != extract_dir:
                    files_to_move.append(item)
            
            if not files_to_move:
                logging.debug(f"No nested files found in {extract_dir.name}")
                return
                
            moved_count = 0
            for file_path in files_to_move:
                try:
                    # Create unique name if file already exists in root
                    target_name = file_path.name
                    target_path = extract_dir / target_name
                    
                    counter = 1
                    while target_path.exists():
                        name_parts = file_path.stem, counter, file_path.suffix
                        target_name = f"{name_parts[0]}_{name_parts[1]}{name_parts[2]}"
                        target_path = extract_dir / target_name
                        counter += 1
                    
                    # Move file to root level
                    shutil.move(str(file_path), str(target_path))
                    moved_count += 1
                    logging.debug(f"📦 Moved: {file_path.name} → {target_name}")
                    
                except Exception as e:
                    logging.warning(f"Failed to move file {file_path}: {e}")
                    
            # Remove empty subdirectories
            subdirs = [d for d in extract_dir.rglob('*') if d.is_dir()]
            subdirs.sort(key=lambda x: len(x.parts), reverse=True)  # Deepest first
            
            removed_dirs = 0
            for subdir in subdirs:
                try:
                    if subdir != extract_dir and not any(subdir.iterdir()):
                        subdir.rmdir()
                        removed_dirs += 1
                        logging.debug(f"📋 Removed empty dir: {subdir.name}")
                except OSError:
                    pass  # Directory not empty or permission issues
            
            if moved_count > 0 or removed_dirs > 0:
                logging.info(
                    f"🎉 Flattened {extract_dir.name}: moved {moved_count} files, "
                    f"removed {removed_dirs} empty directories"
                )
                
        except Exception as e:
            logging.error(f"Error flattening directory {extract_dir}: {e}")

    def _extract_archive(
                self, archive_path: Path, extract_dir: Path, password: str | None = None
        ) -> bool:
        """Extract archive using WinRAR with enhanced error handling."""
        try:
            cmd = [
                str(self.winrar_path),
                'x',
                '-y',
                '-o+',
                '-ibck',
            ]
            if password:
                cmd.append(f'-p{password}')
            cmd.extend([
                str(archive_path),
                str(extract_dir),
            ])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode not in [0, 1]:
                logging.error(f"WinRAR extraction failed with code {result.returncode}")
                logging.error(f"WinRAR Output: {result.stdout}")
                logging.error(f"WinRAR Errors: {result.stderr}")
            return (result.returncode in [0, 1])
        except Exception as e:
            logging.error(f"Extraction error: {str(e)}")
            return False

    def _create_rar_archive(self, source_dir: Path, output_base: Path) -> bool:
        """Create a RAR archive with store method, volume=1GB, RAR5 format."""
        try:
            cmd = [
                str(self.winrar_path),
                'a',
                '-v1024m',
                '-m0',
                '-ep1',
                '-r',
                '-y',
                '-rr3p',
                '-ma5',
                '-x*.ini',
                str(output_base) + '.rar',
                str(source_dir / "*")  # Fix: Include contents, not directory itself
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            success = (result.returncode in [0, 1])
            if success:
                # Verify archive presence
                archive_exists = (
                    (output_base.parent / f"{output_base.name}.rar").exists()
                    or list(output_base.parent.glob(f"{output_base.name}.part*.rar"))
                )
                if not archive_exists:
                    logging.error("RAR archive not found after creation.")
                    return False
                return True
            else:
                logging.error(f"WinRAR RAR creation failed code={result.returncode}")
                logging.error(f"WinRAR Output: {result.stdout}")
                logging.error(f"WinRAR Errors: {result.stderr}")
                return False
        except Exception as e:
            logging.error(f"RAR creation error: {str(e)}")
            return False

    def _create_zip_archive(self, source_dir: Path, output_base: Path) -> bool:
        """Create a ZIP archive with store method, volume=1GB."""
        try:
            file_list = [
                f for f in source_dir.rglob('*')
                if f.is_file() and f.name.lower() != 'desktop.ini'
            ]
            if not file_list:
                logging.error("No files to archive after filtering for ZIP.")
                return False

            cmd = [
                str(self.winrar_path),
                'a',
                '-v1024m',
                '-m0',
                '-ep1',
                '-r',
                '-y',
                '-afzip',
                '-x*.ini',
                str(output_base) + '.zip',
                str(source_dir / "*"),  # Fix: Include contents, not directory itself
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            success = (result.returncode in [0, 1])
            if success:
                archive_exists = (
                    (output_base.parent / f"{output_base.name}.zip").exists()
                    or list(output_base.parent.glob(f"{output_base.name}.z*"))
                )
                if not archive_exists:
                    logging.error("ZIP archive not found after creation.")
                    return False
                return True
            else:
                logging.error(f"WinRAR ZIP creation failed code={result.returncode}")
                logging.error(f"WinRAR Output: {result.stdout}")
                logging.error(f"WinRAR Errors: {result.stderr}")
                return False
        except Exception as e:
            logging.error(f"ZIP creation error: {str(e)}")
            return False

    def _modify_files_for_hash_safely(self, folder_path: Path) -> None:
        """Modify files to change their hash while safely handling permissions."""
        try:
            for file_path in folder_path.rglob('*'):
                if not file_path.is_file():
                    continue
                if file_path.name.lower() == 'desktop.ini':
                    continue
                if file_path.stat().st_size < 10:
                    continue

                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        if os.name == 'nt':
                            try:
                                import win32api
                                import win32con
                                win32api.SetFileAttributes(str(file_path), win32con.FILE_ATTRIBUTE_NORMAL)
                            except:
                                pass
                        with open(file_path, 'ab') as f:
                            num_bytes = random.randint(1, 32)
                            f.write(os.urandom(num_bytes))
                        logging.debug(f"Modified hash for file: {file_path}")
                        break
                    except PermissionError:
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
                        else:
                            logging.warning(
                                f"Permission denied modifying hash for {file_path} after {max_retries} attempts"
                            )
                    except Exception as e:
                        logging.warning(f"Error modifying file {file_path}: {str(e)}")
                        break
        except Exception as e:
            logging.error(f"Error in modify_files_for_hash: {str(e)}")

    def _remove_banned_files_safely(self, directory: Path) -> None:
        """Remove banned files with enhanced permission handling."""
        try:
            banned_files_removed = 0
            for file_path in directory.rglob('*'):
                if not file_path.is_file():
                    continue
                filename = file_path.name.lower()
                if filename in self.banned_files:
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            if os.name == 'nt':
                                try:
                                    import win32api
                                    import win32con
                                    win32api.SetFileAttributes(str(file_path), win32con.FILE_ATTRIBUTE_NORMAL)
                                except:
                                    pass
                            try:
                                file_path.unlink()
                            except PermissionError:
                                os.chmod(str(file_path), 0o777)
                                os.remove(str(file_path))
                            banned_files_removed += 1
                            logging.info(f"Removed banned file: {file_path.name}")

                            # Copy to banned_files_dir if not present
                            try:
                                target_path = self.banned_files_dir / file_path.name
                                if not target_path.exists():
                                    shutil.copy2(str(file_path), str(self.banned_files_dir))
                                    logging.info(f"Copied banned file to reference dir: {file_path.name}")
                            except Exception as copy_error:
                                logging.warning(
                                    f"Could not copy banned file to reference directory: {str(copy_error)}"
                                )
                            break
                        except PermissionError:
                            if attempt < max_retries - 1:
                                time.sleep(1)
                                continue
                            else:
                                logging.warning(
                                    f"Failed to remove banned file {file_path} after {max_retries} attempts"
                                )
                        except Exception as e:
                            logging.warning(f"Error removing banned file {file_path}: {str(e)}")
                            break
            if banned_files_removed > 0:
                logging.info(f"Removed {banned_files_removed} banned file(s) from {directory}")
        except Exception as e:
            logging.error(f"Error in remove_banned_files_safely: {str(e)}")

    def _load_banned_files(self) -> Set[str]:
        """Load the list of banned files from the banned_files directory."""
        banned_files = set()
        try:
            if self.banned_files_dir.exists():
                for file_path in self.banned_files_dir.iterdir():
                    if file_path.is_file():
                        banned_files.add(file_path.name.lower())
                logging.info(f"Loaded {len(banned_files)} banned files from {self.banned_files_dir}")
            else:
                logging.warning(f"Banned files directory not found: {self.banned_files_dir}")
        except Exception as e:
            logging.error(f"Error loading banned files: {str(e)}")
        return banned_files

    def update_banned_files(self) -> None:
        """Update the list of banned files from the banned_files directory."""
        try:
            self.banned_files = self._load_banned_files()
            logging.info(f"Updated banned files list. Total banned files: {len(self.banned_files)}")
        except Exception as e:
            logging.error(f"Error updating banned files: {str(e)}")

    def add_banned_file(self, file_path: Path) -> bool:
        """Add a new file to the banned files list and copy it to the banned_files directory."""
        try:
            if file_path.is_file():
                target_path = self.banned_files_dir / file_path.name
                if not target_path.exists():
                    shutil.copy2(str(file_path), str(self.banned_files_dir))
                    self.banned_files.add(file_path.name.lower())
                    logging.info(f"Added new banned file: {file_path.name}")
                    return True
                else:
                    logging.info(f"Banned file already exists: {file_path.name}")
                    return True
        except Exception as e:
            logging.error(f"Error adding banned file {file_path}: {str(e)}")
            return False

    def _safely_remove_original_archives(self, archive_path: Path, part_files: Optional[List[Path]] = None) -> None:
        """Safely remove original archive(s) with retries."""
        max_retries = 3
        delay = 1

        def remove_with_retry(path: Path):
            for attempt in range(max_retries):
                try:
                    if path.exists():
                        if os.name == 'nt':
                            try:
                                import win32api
                                import win32con
                                win32api.SetFileAttributes(str(path), win32con.FILE_ATTRIBUTE_NORMAL)
                            except:
                                pass
                        path.unlink()
                        logging.info(f"Removed original archive: {path}")
                        return True
                except PermissionError:
                    if attempt < max_retries - 1:
                        time.sleep(delay)
                        continue
                    else:
                        logging.error(f"Failed to remove {path} after {max_retries} attempts")
                        return False
                except Exception as e:
                    logging.error(f"Error removing {path}: {str(e)}")
                    return False

        if part_files:
            for p in part_files:
                remove_with_retry(p)
        else:
            remove_with_retry(archive_path)

    def _safely_rename_archives(self, temp_archives: List[str], temp_suffix: str) -> List[str]:
        """Safely rename temporary archives by removing temp_suffix from filename."""
        final_archives = []
        max_retries = 3
        delay = 1

        for temp_archive in temp_archives:
            temp_path = Path(temp_archive)
            final_name = temp_path.name.replace(temp_suffix, "")
            final_path = temp_path.parent / final_name

            for attempt in range(max_retries):
                try:
                    if final_path.exists():
                        try:
                            final_path.unlink()
                        except:
                            backup_path = final_path.with_suffix(final_path.suffix + '.bak')
                            final_path.rename(backup_path)
                    temp_path.rename(final_path)
                    final_archives.append(str(final_path))
                    logging.info(f"Renamed {temp_path} => {final_path}")
                    break
                except PermissionError:
                    if attempt < max_retries - 1:
                        time.sleep(delay)
                        continue
                    else:
                        logging.error(f"Failed to rename {temp_path} after {max_retries} attempts")
                except Exception as e:
                    logging.error(f"Error renaming {temp_path}: {str(e)}")
                    break
        return final_archives

    def _safely_remove_directory(self, directory: Path) -> None:
        """Safely remove directory and contents with retries."""
        if not directory.exists():
            return

        max_retries = 3
        delay = 1

        if os.name == 'nt':
            try:
                for path in directory.rglob('*'):
                    try:
                        import win32api
                        import win32con
                        win32api.SetFileAttributes(str(path), win32con.FILE_ATTRIBUTE_NORMAL)
                    except:
                        continue
            except:
                pass

        for attempt in range(max_retries):
            try:
                shutil.rmtree(directory, ignore_errors=True)
                if not directory.exists():
                    logging.info(f"Successfully removed directory: {directory}")
                    return
            except PermissionError:
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    continue
            except Exception as e:
                logging.error(f"Error removing directory {directory}: {str(e)}")
                return

            if attempt == max_retries - 1 and directory.exists():
                try:
                    for path in directory.rglob('*'):
                        try:
                            if path.is_file():
                                os.chmod(str(path), 0o777)
                                path.unlink()
                            elif path.is_dir():
                                os.chmod(str(path), 0o777)
                                path.rmdir()
                        except:
                            continue
                    if directory.exists():
                        os.chmod(str(directory), 0o777)
                        directory.rmdir()
                except:
                    logging.warning(f"Could not completely remove directory: {directory}")

    def _safely_remove_file(self, file_path: Path) -> bool:
        """Safely remove a file with retries."""
        max_retries = 3
        delay = 1
        for attempt in range(max_retries):
            try:
                if os.name == 'nt':
                    try:
                        import win32api
                        import win32con
                        win32api.SetFileAttributes(str(file_path), win32con.FILE_ATTRIBUTE_NORMAL)
                    except:
                        pass
                if file_path.exists():
                    os.chmod(str(file_path), 0o777)
                    file_path.unlink()
                return True
            except PermissionError:
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    continue
            except Exception as e:
                logging.error(f"Error removing file {file_path}: {str(e)}")
                return False
        logging.warning(f"Failed to remove file {file_path} after {max_retries} attempts")
        return False

    def _organize_downloads(self, files: List[str], target_dir: Path) -> List[Path]:
        """
        Move downloaded files to thread directory with enhanced error handling.
        Returns the new paths of the moved files.
        """
        moved_files = []
        for file in files:
            try:
                src_path = Path(file)
                if src_path.exists():
                    dest_path = target_dir / src_path.name
                    if src_path != dest_path:
                        max_retries = 3
                        for attempt in range(max_retries):
                            try:
                                shutil.move(str(src_path), str(dest_path))
                                logging.debug(f"Moved {src_path.name} to thread directory")
                                break
                            except PermissionError:
                                if attempt < max_retries - 1:
                                    time.sleep(1)
                                    continue
                                else:
                                    logging.error(
                                        f"Failed to move {src_path} after {max_retries} attempts")
                            except Exception as e:
                                logging.error(f"Error moving file {src_path}: {str(e)}")
                                break
                    moved_files.append(dest_path)
            except Exception as e:
                logging.error(f"Error organizing file {file}: {str(e)}")
        return moved_files

    def _final_directory_cleanup(self, thread_dir: Path, processed_files: List[str]) -> None:
        """
        🧹 Comprehensive final cleanup: keep only the processed files.
        Remove all original files, temporary directories, duplicates, and empty folders.
        """
        if not thread_dir.exists() or not processed_files:
            return
            
        try:
            # Convert processed files to Path objects for comparison
            processed_paths = {Path(f).resolve() for f in processed_files}
            logging.info(f"🧹 Starting final cleanup - keeping {len(processed_paths)} processed files")
            
            # Get all items in thread directory  
            all_items = list(thread_dir.rglob('*'))
            
            files_to_remove = []
            dirs_to_remove = []
            
            for item in all_items:
                try:
                    item_resolved = item.resolve()
                    
                    if item.is_file():
                        # Keep only processed files
                        if item_resolved not in processed_paths:
                            files_to_remove.append(item)
                    elif item.is_dir():
                        # Mark directories for cleanup (will be removed if empty)
                        dirs_to_remove.append(item)
                        
                except Exception as e:
                    logging.warning(f"Error resolving path {item}: {e}")
                    continue
            
            # Remove unwanted files
            removed_files = 0
            for file_path in files_to_remove:
                if self._safely_remove_file(file_path):
                    removed_files += 1
                    logging.debug(f"📋 Removed file: {file_path.name}")
            
            # Remove empty directories (sort by depth, deepest first)
            dirs_to_remove.sort(key=lambda x: len(x.parts), reverse=True)
            removed_dirs = 0
            
            for dir_path in dirs_to_remove:
                try:
                    if dir_path.exists() and not any(dir_path.iterdir()):
                        dir_path.rmdir()
                        removed_dirs += 1
                        logging.debug(f"📁 Removed empty directory: {dir_path.name}")
                except OSError:
                    # Directory might not be empty or have permission issues
                    pass
            
            # Final verification - count remaining files
            remaining_files = [f for f in thread_dir.rglob('*') if f.is_file()]
            remaining_dirs = [d for d in thread_dir.rglob('*') if d.is_dir()]
            
            logging.info(
                f"🎉 Cleanup complete! Removed: {removed_files} files, {removed_dirs} directories. "
                f"Remaining: {len(remaining_files)} files, {len(remaining_dirs)} directories"
            )
            
            # Log final directory structure for verification
            if remaining_files:
                file_names = [f.name for f in remaining_files]
                logging.info(f"📁 Final files in {thread_dir.name}: {', '.join(file_names)}")
                
        except Exception as e:
            logging.error(f"Error during final cleanup: {str(e)}", exc_info=True)

    @staticmethod
    def _is_archive_file(file_path: Path) -> bool:
        """Check if file is an archive (rar, zip, 7z)."""
        return file_path.suffix.lower() in {'.rar', '.zip', '.7z'}
