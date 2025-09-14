# workers/worker_thread.py

import time
import logging
from PyQt5.QtCore import QThread, pyqtSignal
from threading import Lock

from models.operation_status import OperationStatus, OpStage, OpType

class WorkerThread(QThread):
    """
    يتابع المواضيع (threads) في فئة معيّنة:
    - في وضع 'Track Once' ينفّذ مرة واحدة.
    - في وضع 'Keep Tracking' يكرّر العملية كل 60 ثانية حتى تُلغى.
    """
    update_threads = pyqtSignal(str, dict)  # category_name, new_threads (final batch)
    thread_discovered = pyqtSignal(str, str, dict)  # category_name, thread_id, thread_data (live discovery)
    finished = pyqtSignal(str)             # category_name when done
    progress_update = pyqtSignal(object)   # OperationStatus

    def __init__(self, bot, bot_lock, category_manager,
                 category_name, date_filters, page_from, page_to, mode):
        super().__init__()
        self.bot             = bot
        self.bot_lock        = bot_lock
        self.category_manager= category_manager
        self.category_name   = category_name
        # **الجديد**: قائمة نطاقات التاريخ
        self.date_filters    = date_filters or []
        self.page_from       = page_from
        self.page_to         = page_to
        self.mode            = mode
        self.section         = "Tracking"

        self.is_paused       = False
        self.is_cancelled    = False
        self._is_running     = True  # إضافة الـ attribute المفقود
        self.control_lock    = Lock()
        self.live_thread_count = 0  # Track threads discovered live

    def run(self):
        """Main thread loop for monitoring the category."""
        logging.info(f"🚀 Starting WorkerThread for category '{self.category_name}'")

        # Notify UI that this category has been queued - emit RUNNING immediately to trigger UI creation
        try:
            # Emit RUNNING status immediately with 0% to create the operation in UI
            self.progress_update.emit(
                OperationStatus(
                    section=self.section,
                    item=self.category_name,
                    op_type=OpType.POST,
                    stage=OpStage.RUNNING,
                    progress=0,
                    message="Initializing tracking..."
                )
            )
            # Small delay to ensure UI processes it
            import time
            time.sleep(0.1)
        except Exception as e:
            logging.error(f"Failed to emit initial progress update: {e}")
        
        # WORKER STATE RESET: Ensure clean start state
        logging.info(f" Resetting worker state for '{self.category_name}'")
        try:
            self._is_running = True
            self.is_cancelled = False
            self.is_paused = False
            logging.info(f" Worker state reset complete for '{self.category_name}'")
        except Exception as reset_error:
            logging.warning(f" Worker state reset failed for '{self.category_name}': {reset_error}")
        
        try:
            while True:
                # Check if thread should stop or is cancelled
                with self.control_lock:
                    if not self._is_running or self.is_cancelled:
                        logging.info(f"🛑 WorkerThread for '{self.category_name}' received stop signal")
                        break
                
                # Handle pause with frequent stop checks
                while self.is_paused:
                    with self.control_lock:
                        if not self._is_running or self.is_cancelled:
                            logging.info(f"🛑 WorkerThread for '{self.category_name}' cancelled during pause")
                            return
                    time.sleep(0.1)  # Check every 100ms during pause
                    
                # Choose tracking method based on mode
                try:
                    if self.mode == 'Track Once':
                        self.track_once()
                        break  # Exit after one tracking cycle
                    elif self.mode == 'Keep Tracking':
                        self.keep_tracking()
                    else:
                        break  # Unknown mode, exit
                except Exception as e:
                    logging.error(f"❌ Error in tracking for '{self.category_name}': {e}")
                    # Check if we should continue or stop on error
                    with self.control_lock:
                        if not self._is_running or self.is_cancelled:
                            break
                    # Continue tracking after error if not stopped
                
                # For 'Track Once' mode, exit after one iteration
                if self.mode == 'Track Once':
                    logging.info(f"✅ Track Once completed for '{self.category_name}', exiting loop")
                    break

                # For 'Keep Tracking' mode, sleep with frequent stop checks
                if self.mode == 'Keep Tracking':
                    # Check stop condition again before sleep
                    with self.control_lock:
                        if not self._is_running or self.is_cancelled:
                            logging.info(f"🛑 WorkerThread for '{self.category_name}' stopping after tracking cycle")
                            break
                            
                    # Sleep between tracking cycles, checking stop condition frequently
                    sleep_duration = 60.0  # 60 seconds between cycles
                    while sleep_duration > 0:
                        # Check stop condition more frequently during sleep
                        with self.control_lock:
                            if not self._is_running or self.is_cancelled:
                                logging.info(f"🛑 WorkerThread for '{self.category_name}' interrupted during sleep")
                                return
                        
                        sleep_time = min(0.5, sleep_duration)  # Sleep in 0.5-second chunks for responsiveness
                        time.sleep(sleep_time)
                        sleep_duration -= sleep_time
            
        except Exception as e:
            logging.error(f"❌ Fatal error in WorkerThread '{self.category_name}': {e}", exc_info=True)
        finally:
            logging.info(f"✅ WorkerThread for '{self.category_name}' finished")
            self.finished.emit(self.category_name)

    def navigate_to_category(self, page_from, page_to):
        base_url = self.category_manager.get_category_url(self.category_name)
        if not base_url:
            raise Exception(f"Category URL not found for {self.category_name}")

        # Convert date_filters list into comma-separated string
        if isinstance(self.date_filters, list):
            df_param = ",".join(self.date_filters)
        else:
            df_param = self.date_filters or ""

        # Check if thread should stop before making bot call
        with self.control_lock:
            if not self._is_running or self.is_cancelled:
                logging.info(f"🛑 WorkerThread for '{self.category_name}' stopping, aborting navigation")
                return []

        lock_acquired = False
        threads = {}

        try:
            logging.info(f"🔒 Attempting to acquire bot_lock for '{self.category_name}'")
            lock_acquired = self.bot_lock.tryLock(10000)
            if not lock_acquired:
                logging.error(
                    f"❌ Failed to acquire bot_lock within 10 seconds for '{self.category_name}' - aborting"
                )
                self.progress_update.emit(
                    OperationStatus(
                        section=self.section,
                        item=self.category_name,
                        op_type=OpType.POST,
                        stage=OpStage.ERROR,
                        message="driver busy",
                    )
                )
                return {}

            logging.info(f"✅ Successfully acquired bot_lock for '{self.category_name}'")

            total_pages = page_to - page_from + 1
            for idx, page in enumerate(range(page_from, page_to + 1), 1):
                with self.control_lock:
                    if not self._is_running or self.is_cancelled:
                        logging.info(
                            f"🛑 WorkerThread for '{self.category_name}' stopping after acquiring bot lock"
                        )
                        break
                try:
                    # Keep track of discovered threads for progress updates
                    discovered_count = [0]  # Use list to allow modification in nested function

                    # Create live discovery callback for instant process threads display
                    def live_discovery_callback(thread_id, thread_data):
                        # Only emit for live UI updates, don't count here to avoid double counting
                        self.thread_discovered.emit(self.category_name, thread_id, thread_data)

                        # Track discovered count for progress updates
                        discovered_count[0] += 1

                        # Update progress every few threads
                        if discovered_count[0] % 3 == 0 or discovered_count[0] == 1:
                            progress_percent = min(20 + int(discovered_count[0] * 60 / 100), 85)
                            self.progress_update.emit(
                                OperationStatus(
                                    section=self.section,
                                    item=self.category_name,
                                    op_type=OpType.POST,
                                    stage=OpStage.RUNNING,
                                    message=f"Found {discovered_count[0]} threads...",
                                    progress=progress_percent,
                                )
                            )

                    success = self.bot.navigate_to_url(
                        base_url,
                        df_param,
                        page,
                        page,
                        thread_discovery_callback=live_discovery_callback
                    )
                    if success:
                        threads.update(self.bot.extracted_threads.copy())
                except Exception as e:
                    logging.error(
                        f"Exception during navigating to URL: {e}", exc_info=True
                    )
                    self.progress_update.emit(
                        OperationStatus(
                            section=self.section,
                            item=self.category_name,
                            op_type=OpType.POST,
                            stage=OpStage.ERROR,
                            message=str(e)[:80],
                        )
                    )
                    return {}
                self.progress_update.emit(
                    OperationStatus(
                        section=self.section,
                        item=self.category_name,
                        op_type=OpType.POST,
                        stage=OpStage.RUNNING,
                        message=f"Scanning p {idx}/{total_pages}",
                        progress=int(idx * 100 / total_pages),
                    )
                )
        finally:
            if lock_acquired:
                try:
                    self.bot_lock.unlock()
                    logging.info(f"🔓 Released bot_lock for '{self.category_name}'")
                except Exception as unlock_error:
                    logging.warning(
                        f"⚠️ Failed to release bot_lock for '{self.category_name}': {unlock_error}"
                    )

        return threads

    def track_once(self):
        logging.info(f"🔍 WorkerThread: Starting track_once for '{self.category_name}'")
        
        # Check if we're already paused or cancelled to prevent redundant execution
        if hasattr(self, 'is_paused') and self.is_paused:
            logging.info(f"⏸️ Tracking paused for '{self.category_name}', skipping track_once")
            return
        if hasattr(self, 'is_cancelled') and self.is_cancelled:
            logging.info(f"❌ Tracking cancelled for '{self.category_name}', skipping track_once")
            return
        
        # 🆘 PRE-TRACKING WEBDRIVER CHECK: Verify WebDriver is responsive
        logging.info(f"🆘 Checking WebDriver responsiveness for '{self.category_name}'")
        
        # ⏱️ TIMEOUT PROTECTION: Set max time for WebDriver check
        import signal
        
        def timeout_handler(signum, frame):
            raise TimeoutError(f"WebDriver check timed out for '{self.category_name}'")
        
        try:
            # Set 30-second timeout for WebDriver operations
            signal.signal(signal.SIGALRM, timeout_handler) if hasattr(signal, 'SIGALRM') else None
            signal.alarm(30) if hasattr(signal, 'alarm') else None
            
            if hasattr(self.bot, 'driver') and self.bot.driver:
                # Quick responsiveness test
                current_url = self.bot.driver.current_url
                if current_url:
                    logging.info(f"✅ WebDriver responsive for '{self.category_name}' (at: {current_url[:50]}...)")
                else:
                    logging.warning(f"⚠️ WebDriver returned empty URL for '{self.category_name}' - may be stuck")
            else:
                logging.error(f"❌ WebDriver not available for '{self.category_name}' - cannot proceed")
                return
                
        except TimeoutError as timeout_error:
            logging.error(f"⏱️ WebDriver check timed out for '{self.category_name}': {timeout_error}")
            logging.warning(f"⚠️ Skipping tracking cycle due to WebDriver timeout for '{self.category_name}'")
            return
        except Exception as driver_error:
            logging.error(f"❌ WebDriver health check failed for '{self.category_name}': {driver_error}")
            logging.warning(f"⚠️ Skipping tracking cycle due to WebDriver issues for '{self.category_name}'")
            return
        finally:
            # Always clear the alarm
            if hasattr(signal, 'alarm'):
                signal.alarm(0)
        
        logging.info(
            f"🌐 Navigating to category '{self.category_name}' with filters: {self.date_filters}, pages: {self.page_from}-{self.page_to}"
        )

        # Update progress with actual tracking status
        self.progress_update.emit(
            OperationStatus(
                section=self.section,
                item=self.category_name,
                op_type=OpType.POST,
                stage=OpStage.RUNNING,
                message=f"Scanning pages {self.page_from}-{self.page_to}...",
                progress=10,
            )
        )

        new_threads = self.navigate_to_category(self.page_from, self.page_to)

        if new_threads:
            logging.info(
                f"✅ Found {len(new_threads)} new threads for '{self.category_name}'"
            )
            # Update main tracking progress with final thread count
            self.progress_update.emit(
                OperationStatus(
                    section=self.section,
                    item=self.category_name,
                    op_type=OpType.POST,
                    stage=OpStage.RUNNING,
                    message=f"Found {len(new_threads)} threads, finalizing...",
                    progress=90,
                )
            )
            # Count actual threads discovered (not doubled)
            self.live_thread_count = len(new_threads)
            logging.info(f"📊 Actual thread count for '{self.category_name}': {self.live_thread_count}")
            self.update_threads.emit(self.category_name, new_threads)
        else:
            logging.info(
                f"ℹ️ No new threads found for '{self.category_name}'"
            )
            self.live_thread_count = 0

        # FORCE COMPLETION STATUS - MUST SHOW FINISHED!
        summary = f"COMPLETED: {self.live_thread_count} threads tracked" if self.live_thread_count > 0 else "COMPLETED: No new threads"

        # Send completion status multiple times to ensure UI gets it
        for _ in range(3):
            self.progress_update.emit(
                OperationStatus(
                    section=self.section,
                    item=self.category_name,
                    op_type=OpType.POST,
                    stage=OpStage.FINISHED,
                    message=summary,
                    progress=100,
                )
            )
            import time
            time.sleep(0.05)  # Small delay to ensure UI processes it

    def keep_tracking(self):
        logging.info(f"WorkerThread: Keep tracking '{self.category_name}'.")
        new_threads = self.navigate_to_category(1, 1)
        if new_threads:
            # Update main tracking progress with final thread count
            self.progress_update.emit(
                OperationStatus(
                    section=self.section,
                    item=self.category_name,
                    op_type=OpType.POST,
                    stage=OpStage.RUNNING,
                    message=f"Found {len(new_threads)} threads, finalizing...",
                    progress=90,
                )
            )
            # Count actual threads discovered (not doubled)
            self.live_thread_count = len(new_threads)
            logging.info(f"📊 Actual thread count for '{self.category_name}': {self.live_thread_count}")
            self.update_threads.emit(self.category_name, new_threads)
        else:
            self.live_thread_count = 0
        # FORCE COMPLETION STATUS - MUST SHOW FINISHED!
        summary = f"COMPLETED: {self.live_thread_count} threads tracked" if self.live_thread_count > 0 else "COMPLETED: No new threads"

        # Send completion status multiple times to ensure UI gets it
        for _ in range(3):
            self.progress_update.emit(
                OperationStatus(
                    section=self.section,
                    item=self.category_name,
                    op_type=OpType.POST,
                    stage=OpStage.FINISHED,
                    message=summary,
                    progress=100,
                )
            )
            import time
            time.sleep(0.05)  # Small delay to ensure UI processes it

    def stop(self):
        """لإيقاف الحلقة في وضع Keep Tracking."""
        logging.info(f"⛔ Stopping WorkerThread for '{self.category_name}'")
        
        # Set cancellation flags
        with self.control_lock:
            self._is_running = False
            self.is_cancelled = True
        
        # If thread is not running, we're done
        if not self.isRunning():
            logging.info(f"✅ WorkerThread for '{self.category_name}' was not running")
            return
        
        logging.info(f"⏰ Waiting for WorkerThread '{self.category_name}' to finish gracefully...")
        
        # First attempt: Wait for graceful shutdown (increased timeout)
        if self.wait(5000):  # Wait max 5 seconds for graceful shutdown
            logging.info(f"✅ WorkerThread for '{self.category_name}' stopped gracefully")
            return
        
        # Second attempt: Send quit signal and wait (increased timeout)
        logging.warning(f"⚠️ WorkerThread '{self.category_name}' didn't stop gracefully, sending quit signal")
        self.quit()
        
        if self.wait(3000):  # Wait another 3 seconds for quit signal
            logging.info(f"✅ WorkerThread for '{self.category_name}' stopped after quit signal")
            return
        
        # 🔧 SAFER APPROACH: Don't force unlock - let Qt handle mutex cleanup naturally
        logging.warning(f"⚠️ Skipping manual bot_lock unlock to prevent crashes for '{self.category_name}'")
        # Note: Qt will automatically clean up mutex when thread terminates
        # Manual unlock attempts can cause access violations in force termination scenarios
        
        # Third attempt: Force termination
        logging.warning(f"🔨 Force terminating WorkerThread '{self.category_name}'")
        try:
            self.terminate()
            if self.wait(1000):  # Give 1 second for termination
                logging.info(f"✅ WorkerThread for '{self.category_name}' force terminated successfully")
            else:
                logging.error(f"❌ Failed to terminate WorkerThread '{self.category_name}'")
        except Exception as e:
            logging.error(f"❌ Error during force termination of '{self.category_name}': {e}")
        
        # 🧹 FINAL CLEANUP: Clear all references to prevent memory leaks
        try:
            self._is_running = False
            self.is_cancelled = True
            self.is_paused = False
            
            # Clear bot reference to prevent hanging connections
            if hasattr(self, 'bot'):
                self.bot = None
                
            logging.info(f"🧹 Completed resource cleanup for WorkerThread '{self.category_name}'")
        except Exception as cleanup_error:
            logging.warning(f"⚠️ Resource cleanup warning for '{self.category_name}': {cleanup_error}")
        
        logging.info(f"🏁 Stop procedure completed for WorkerThread '{self.category_name}'")
    
    def pause(self):
        """إيقاف مؤقت للمراقبة"""
        with self.control_lock:
            self.is_paused = True
            logging.info(f"⏸️ Paused WorkerThread for '{self.category_name}'")
    
    def resume(self):
        """استئناف المراقبة"""
        with self.control_lock:
            self.is_paused = False
            logging.info(f"▶️ Resumed WorkerThread for '{self.category_name}'")



class MegaThreadsWorkerThread(QThread):
    """
    يتابع "الميجاتريدز" بنفس المنطق لكن مع قواعد خاصة باختيار الإصدارات.
    """
    update_megathreads = pyqtSignal(str, dict)  # category_name, new_versions
    finished          = pyqtSignal(str)
    progress_update   = pyqtSignal(object)

    def __init__(self, bot, bot_lock, category_manager,
                 category_name, date_filters, mode,
                 gui, page_from=1, page_to=1):
        super().__init__()
        self.bot              = bot
        self.bot_lock         = bot_lock
        self.category_manager = category_manager
        self.category_name    = category_name
        self.date_filters      = date_filters
        self.mode             = mode
        self.gui              = gui
        self.page_from        = page_from
        self.page_to          = page_to
        self._is_running      = True
        self.is_paused        = False
        self.is_cancelled     = False
        self.control_lock     = Lock()
        self.section          = "Megathreads"

    def run(self):
        try:
            self.progress_update.emit(
                OperationStatus(
                    section=self.section,
                    item=self.category_name,
                    op_type=OpType.POST,
                    stage=OpStage.QUEUED,
                    progress=0,
                )
            )
            while self._is_running and not self.is_cancelled:
                if self.mode == 'Track Once':
                    self.track_once()
                    break

                if self.mode == 'Keep Tracking':
                    if not self.is_paused:
                        self.keep_tracking()

                    # Sleep in small chunks so we can react quickly to stop requests
                    for _ in range(60):  # 60 seconds total
                        if not self._is_running or self.is_cancelled:
                            break
                        self.msleep(1000)
                else:
                    break
        except Exception as e:
            logging.error(
                f"Exception in MegaThreadsWorkerThread('{self.category_name}'): {e}",
                exc_info=True,
            )
        finally:
            logging.info(
                f"🔄 MegaThreadsWorkerThread for '{self.category_name}' finished"
            )
            self.finished.emit(self.category_name)

    def track_once(self):
        logging.info(
            f"MegaThreadsWorkerThread: Tracking once for '{self.category_name}'."
        )

        lock_acquired = False
        try:
            logging.info(
                f"🔒 Attempting to acquire bot_lock for megathreads '{self.category_name}'"
            )
            lock_acquired = self.bot_lock.tryLock(10000)
            if not lock_acquired:
                logging.error(
                    f"❌ Failed to acquire bot_lock for megathreads '{self.category_name}'"
                )
                self.progress_update.emit(
                    OperationStatus(
                        section=self.section,
                        item=self.category_name,
                        op_type=OpType.POST,
                        stage=OpStage.ERROR,
                        message="driver busy",
                    )
                )
                return

            # 🔍 HEALTH CHECK: Verify WebDriver is responsive before navigation
            logging.info(
                f"🔍 Checking WebDriver health before megathreads tracking '{self.category_name}'"
            )
            try:
                current_url = (
                    self.bot.driver.current_url
                    if hasattr(self.bot, 'driver') and self.bot.driver
                    else None
                )
                if current_url:
                    logging.info(
                        f"✅ WebDriver is responsive for megathreads '{self.category_name}' (current URL: {current_url[:50]}...)"
                    )
                else:
                    logging.warning(
                        f"⚠️ WebDriver may not be initialized for megathreads '{self.category_name}'"
                    )
            except Exception as driver_check_error:
                logging.error(
                    f"❌ WebDriver health check failed for megathreads '{self.category_name}': {driver_check_error}"
                )

            url = self.category_manager.get_category_url(self.category_name)
            if not url:
                logging.warning(
                    f"No URL for megathreads '{self.category_name}'"
                )
                return
            total_pages = self.page_to - self.page_from + 1
            all_versions = {}
            for idx, page in enumerate(
                range(self.page_from, self.page_to + 1), 1
            ):
                try:
                    new_versions = self.bot.navigate_to_megathread_category(
                        url, self.date_filters, page, page
                    )
                    if isinstance(new_versions, dict):
                        all_versions.update(new_versions)
                except Exception as e:
                    logging.error(
                        f"Error in navigate_to_megathread_category: {e}",
                        exc_info=True,
                    )
                    self.progress_update.emit(
                        OperationStatus(
                            section=self.section,
                            item=self.category_name,
                            op_type=OpType.POST,
                            stage=OpStage.ERROR,
                            message=str(e)[:80],
                        )
                    )
                    return
                self.progress_update.emit(
                    OperationStatus(
                        section=self.section,
                        item=self.category_name,
                        op_type=OpType.POST,
                        stage=OpStage.RUNNING,
                        message=f"Scanning p {idx}/{total_pages}",
                        progress=int(idx * 100 / total_pages),
                    )
                )
            if all_versions:
                for title, info in all_versions.items():
                    label = f"{self.category_name} — {info.get('version_title', title)}"
                    url = info.get("thread_url", "")
                    self.progress_update.emit(
                        OperationStatus(
                            section=self.section,
                            item=label,
                            op_type=OpType.POST,
                            stage=OpStage.RUNNING,
                            message="Found",
                            progress=0,
                        )
                    )
                    self.progress_update.emit(
                        OperationStatus(
                            section=self.section,
                            item=label,
                            op_type=OpType.POST,
                            stage=OpStage.FINISHED,
                            message="Done",
                            progress=100,
                            final_url=url,
                        )
                    )
                self.update_megathreads.emit(self.category_name, all_versions)
                summary = f"{len(all_versions)} new / 0 updated / 0 skipped"
            else:
                summary = "0 new / 0 updated / 0 skipped"
            self.progress_update.emit(
                OperationStatus(
                    section=self.section,
                    item=self.category_name,
                    op_type=OpType.POST,
                    stage=OpStage.FINISHED,
                    message=summary,
                    progress=100,
                )
            )
        finally:
            if lock_acquired:
                try:
                    self.bot_lock.unlock()
                    logging.info(
                        f"🔓 Released bot_lock for megathreads '{self.category_name}'"
                    )
                except Exception as unlock_error:
                    logging.warning(
                        f"⚠️ Failed to release bot_lock for megathreads '{self.category_name}': {unlock_error}"
                    )

    def keep_tracking(self):
        logging.info(
            f"MegaThreadsWorkerThread: Keep tracking '{self.category_name}'."
        )

        lock_acquired = False
        try:
            logging.info(
                f"🔒 Attempting to acquire bot_lock for megathreads '{self.category_name}'"
            )
            lock_acquired = self.bot_lock.tryLock(10000)
            if not lock_acquired:
                logging.error(
                    f"❌ Failed to acquire bot_lock for megathreads '{self.category_name}'"
                )
                self.progress_update.emit(
                    OperationStatus(
                        section=self.section,
                        item=self.category_name,
                        op_type=OpType.POST,
                        stage=OpStage.ERROR,
                        message="driver busy",
                    )
                )
                return

            key = f"Megathreads_{self.category_name}"
            existing = self.gui.megathreads_process_threads.get(key, {})
            if not isinstance(existing, dict):
                existing = {}
            try:
                updates = self.bot.check_megathreads_for_updates(existing)
            except Exception as e:
                logging.error(
                    f"Error in check_megathreads_for_updates: {e}",
                    exc_info=True,
                )
                self.progress_update.emit(
                    OperationStatus(
                        section=self.section,
                        item=self.category_name,
                        op_type=OpType.POST,
                        stage=OpStage.ERROR,
                        message=str(e)[:80],
                    )
                )
                return
            if isinstance(updates, dict) and updates:
                for title, info in updates.items():
                    label = f"{self.category_name} — {info.get('version_title', title)}"
                    url = info.get("thread_url", "")
                    self.progress_update.emit(
                        OperationStatus(
                            section=self.section,
                            item=label,
                            op_type=OpType.POST,
                            stage=OpStage.RUNNING,
                            message="Found",
                            progress=0,
                        )
                    )
                    self.progress_update.emit(
                        OperationStatus(
                            section=self.section,
                            item=label,
                            op_type=OpType.POST,
                            stage=OpStage.FINISHED,
                            message="Done",
                            progress=100,
                            final_url=url,
                        )
                    )
                self.update_megathreads.emit(self.category_name, updates)
                summary = f"{len(updates)} new / 0 updated / 0 skipped"
            else:
                summary = "0 new / 0 updated / 0 skipped"
            self.progress_update.emit(
                OperationStatus(
                    section=self.section,
                    item=self.category_name,
                    op_type=OpType.POST,
                    stage=OpStage.FINISHED,
                    message=summary,
                    progress=100,
                )
            )
        finally:
            if lock_acquired:
                try:
                    self.bot_lock.unlock()
                    logging.info(
                        f"🔓 Released bot_lock for megathreads '{self.category_name}'"
                    )
                except Exception as unlock_error:
                    logging.warning(
                        f"⚠️ Failed to release bot_lock for megathreads '{self.category_name}': {unlock_error}"
                    )

    def stop(self):
        """لإيقاف الحلقة في وضع Keep Tracking."""
        logging.info(
            f"⛔ Stopping MegaThreadsWorkerThread for '{self.category_name}'"
        )

        with self.control_lock:
            self.is_cancelled = True
            self._is_running = False

        self.quit()
        if not self.wait(3000):
            logging.warning(
                f"⚠️ MegaThreadsWorkerThread '{self.category_name}' did not stop after quit, terminating"
            )
            self.terminate()
            self.wait(1000)

        try:
            self.bot_lock.unlock()
            logging.info(
                f"🔓 Released bot_lock for megathreads '{self.category_name}' during stop"
            )
        except Exception:
            pass

        logging.info(
            f"🏁 Stop procedure completed for MegaThreadsWorkerThread '{self.category_name}'"
        )
    
    def pause(self):
        """إيقاف مؤقت للمراقبة"""
        with self.control_lock:
            self.is_paused = True
            logging.info(f"⏸️ Paused MegaThreadsWorkerThread for '{self.category_name}'")
    
    def resume(self):
        """استئناف المراقبة"""
        with self.control_lock:
            self.is_paused = False
            logging.info(f"▶️ Resumed MegaThreadsWorkerThread for '{self.category_name}'")
