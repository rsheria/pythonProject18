import time
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QDate, pyqtSignal

from uploaders.rapidgator_upload_handler import RapidgatorUploadHandler
from PyQt5.QtWidgets import (
    QWidget, QGroupBox, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QAbstractItemView, QCheckBox, QFileDialog, QMessageBox,
    QDialog, QRadioButton, QButtonGroup, QDateEdit, QSpinBox,
    QComboBox, QDialogButtonBox, QLabel, QScrollArea
)
import os
import logging
from core.user_manager import get_user_manager

class SettingsWidget(QWidget):
    # Signal emitted when download directory changes
    download_directory_changed = pyqtSignal(str)
    # Signal emitted when hosts list is updated
    hosts_updated = pyqtSignal(list)
    # Signal emitted when Rapidgator backup option toggled
    use_backup_rg_changed = pyqtSignal(bool)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.user_manager = get_user_manager()
        
        # Load user-specific settings or use config defaults
        if self.user_manager.get_current_user():
            # Load date filters from user settings
            date_filters = self.user_manager.get_user_setting(
                'date_filters',
                [{'type': 'relative', 'value': 3, 'unit': 'days'}]
            )
            # Handle case where date_filters might be stored as string (JSON)
            if isinstance(date_filters, str):
                try:
                    import json
                    date_filters = json.loads(date_filters)
                except (json.JSONDecodeError, ValueError):
                    logging.warning("⚠️ Invalid date_filters format, using default")
                    date_filters = [{'type': 'relative', 'value': 3, 'unit': 'days'}]
            # Ensure it's a list of dictionaries
            if not isinstance(date_filters, list) or not all(isinstance(df, dict) for df in date_filters):
                logging.warning("⚠️ Invalid date_filters structure, using default")
                date_filters = [{'type': 'relative', 'value': 3, 'unit': 'days'}]
            self.date_filters = list(date_filters)
        else:
            self.date_filters = list(
                self.config.get('date_filters', [{'type': 'relative', 'value': 3, 'unit': 'days'}])
            )

        
        self.init_ui()
        
        # Load date filters into list widget after UI is initialized
        if hasattr(self, 'date_filters_list'):
            self._load_date_filters_into_list()
        
        # Load generic settings without user-specific data until login
        self.load_settings(initial=True)

    def init_ui(self):
        # === الحاوية الرئيسية ==================================================
        root_layout = QVBoxLayout(self)

        # Scroll‑area حتى لا يتمدّد النموذج بلا حدود
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root_layout.addWidget(scroll)

        scroll_content = QWidget()
        scroll.setWidget(scroll_content)
        sc_layout = QVBoxLayout(scroll_content)  # كل عناصر الإعدادات هنا

        # عنوان
        header = QLabel("Settings")
        header.setStyleSheet("font-size:16px;font-weight:bold;margin-bottom:10px;")
        sc_layout.addWidget(header)

        # ------------------------------------------------------------------
        # 1) Download Settings
        dl_group = QGroupBox("Download Settings")
        dl_layout = QHBoxLayout(dl_group)
        self.download_edit = QLineEdit()
        dl_layout.addWidget(self.download_edit)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self.browse_download)
        dl_layout.addWidget(browse_btn)
        sc_layout.addWidget(dl_group)

        # Katfile API
        dl_layout.addWidget(QLabel("Katfile API Key:"))
        self.katfile_api_key_input = QLineEdit()
        self.katfile_api_key_input.setPlaceholderText("Enter Katfile API Key")
        dl_layout.addWidget(self.katfile_api_key_input)

        # Rapidgator credentials + token
        rg_group = QGroupBox("Rapidgator")
        rg_layout = QVBoxLayout(rg_group)

        # Credentials row
        cred_row = QHBoxLayout()
        cred_row.addWidget(QLabel("Email/Username:"))
        self.rg_user_edit = QLineEdit()
        self.rg_user_edit.setPlaceholderText("john@example.com")
        cred_row.addWidget(self.rg_user_edit)

        cred_row.addWidget(QLabel("Password:"))
        self.rg_pass_edit = QLineEdit()
        self.rg_pass_edit.setEchoMode(QLineEdit.Password)
        cred_row.addWidget(self.rg_pass_edit)

        cred_row.addWidget(QLabel("2FA:"))
        self.rg_code_edit = QLineEdit()
        self.rg_code_edit.setPlaceholderText("Optional")
        self.rg_code_edit.setMaximumWidth(70)
        cred_row.addWidget(self.rg_code_edit)

        rg_layout.addLayout(cred_row)

        # API Token row
        token_row = QHBoxLayout()
        token_row.addWidget(QLabel("API Token:"))
        self.rapidgator_token_input = QLineEdit()
        self.rapidgator_token_input.setEchoMode(QLineEdit.Password)
        self.rapidgator_token_input.setPlaceholderText("Leave blank to auto‑generate")
        self.rapidgator_token_input.textChanged.connect(self._on_rapidgator_token_changed)
        token_row.addWidget(self.rapidgator_token_input, 1)

        self.validate_token_btn = QPushButton("Validate")
        self.validate_token_btn.clicked.connect(self._validate_rapidgator_token)
        token_row.addWidget(self.validate_token_btn)
        rg_layout.addLayout(token_row)

        self.rapidgator_status_label = QLabel()
        self.rapidgator_status_label.setVisible(False)
        rg_layout.addWidget(self.rapidgator_status_label)
        # Checkbox to enable Rapidgator backup uploads
        self.use_backup_rg_checkbox = QCheckBox("Use Rapidgator backup uploads")
        rg_layout.addWidget(self.use_backup_rg_checkbox)

        # Emit signal when checkbox toggled
        self.use_backup_rg_checkbox.toggled.connect(
            lambda checked: self.use_backup_rg_changed.emit(bool(checked))
        )

        sc_layout.addWidget(rg_group)

        # ------------------------------------------------------------------
        # 2) Upload Hosts
        upl_group = QGroupBox("Upload Hosts")
        upl_layout = QVBoxLayout(upl_group)
        self.hosts_list = QListWidget()
        self.hosts_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.hosts_list.itemChanged.connect(self._on_host_item_changed)
        upl_layout.addWidget(self.hosts_list)

        add_row = QHBoxLayout()
        self.new_host_edit = QLineEdit()
        add_row.addWidget(self.new_host_edit)
        add_btn = QPushButton("Add Host")
        add_btn.clicked.connect(self.add_new_host)
        add_row.addWidget(add_btn)
        del_btn = QPushButton("Delete Selected")
        del_btn.clicked.connect(self.delete_selected_host)
        add_row.addWidget(del_btn)
        upl_layout.addLayout(add_row)
        sc_layout.addWidget(upl_group)

        # — Date Filters —
        df_group = QGroupBox("Date Filters")
        df_layout = QVBoxLayout(df_group)
        self.date_filters_list = QListWidget()
        self.date_filters_list.setSelectionMode(QAbstractItemView.SingleSelection)
        df_layout.addWidget(self.date_filters_list)
        btn_row = QHBoxLayout()
        self.add_df_btn = QPushButton("Add Range")
        self.remove_df_btn = QPushButton("Remove Selected")
        btn_row.addWidget(self.add_df_btn)
        btn_row.addWidget(self.remove_df_btn)
        df_layout.addLayout(btn_row)
        sc_layout.addWidget(df_group)

        # — Page Range (NEW) —
        pr_group = QGroupBox("Page Range")
        pr_layout = QHBoxLayout(pr_group)
        pr_layout.addWidget(QLabel("From"))
        self.page_from_spin = QSpinBox()
        self.page_from_spin.setMinimum(1)
        self.page_from_spin.setValue(1)
        pr_layout.addWidget(self.page_from_spin)
        pr_layout.addWidget(QLabel("To"))
        self.page_to_spin = QSpinBox()
        self.page_to_spin.setMinimum(1)
        self.page_to_spin.setValue(1)
        pr_layout.addWidget(self.page_to_spin)
        sc_layout.addWidget(pr_group)

        # — Download Hosts Priority —
        priority_group = QGroupBox("Download Hosts Priority")
        priority_layout = QVBoxLayout(priority_group)
        priority_layout.addWidget(QLabel("Drag and drop to reorder priority:"))
        self.priority_list = QListWidget()
        self.priority_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.priority_list.setDefaultDropAction(Qt.MoveAction)
        priority_layout.addWidget(self.priority_list)
        priority_buttons = QHBoxLayout()
        reset_priority_btn = QPushButton("Reset to Defaults")
        reset_priority_btn.clicked.connect(self.reset_priority_to_defaults)
        priority_buttons.addWidget(reset_priority_btn)
        priority_buttons.addStretch()
        priority_layout.addLayout(priority_buttons)
        sc_layout.addWidget(priority_group)

        # — Save / Reset Buttons —
        btn_box = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_settings)
        reset_btn = QPushButton("Reset Defaults")
        reset_btn.clicked.connect(self.reset_defaults)
        btn_box.addStretch()
        btn_box.addWidget(reset_btn)
        btn_box.addWidget(save_btn)
        sc_layout.addLayout(btn_box)

        # wire up date-filter buttons
        self.add_df_btn.clicked.connect(self.open_add_date_filter_dialog)
        self.remove_df_btn.clicked.connect(self.remove_selected_date_filter)

        self.load_settings()

    def _load_date_filters_into_list(self):
        """اعرض الـ date_filters الحالية في QListWidget"""
        self.date_filters_list.clear()
        for df in self.date_filters:
            try:
                # Ensure df is a dictionary
                if not isinstance(df, dict):
                    logging.warning(f"⚠️ Skipping invalid date filter: {df} (not a dictionary)")
                    continue
                    
                if df.get('type') == 'fixed':
                    text = f"{df.get('from', 'N/A')} → {df.get('to', 'N/A')}"
                else:
                    text = f"Last {df.get('value', 'N/A')} {df.get('unit', 'N/A')}"
                self.date_filters_list.addItem(text)
            except Exception as e:
                logging.error(f"❌ Error loading date filter {df}: {e}")
                continue

    def open_add_date_filter_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Add Date Range")
        v = QVBoxLayout(dlg)

        # اختيار النوع
        fixed_rb = QRadioButton("Fixed Range")
        relative_rb = QRadioButton("Relative Range")
        fixed_rb.setChecked(True)
        grp = QButtonGroup(dlg)
        grp.addButton(fixed_rb)
        grp.addButton(relative_rb)
        v.addWidget(fixed_rb)
        v.addWidget(relative_rb)

        # Fixed widgets
        fixed_widget = QWidget()
        fh = QHBoxLayout(fixed_widget)
        self.from_date = QDateEdit(QDate.currentDate())
        self.from_date.setCalendarPopup(True)
        self.to_date   = QDateEdit(QDate.currentDate())
        self.to_date.setCalendarPopup(True)
        fh.addWidget(self.from_date)
        fh.addWidget(self.to_date)
        v.addWidget(fixed_widget)

        # Relative widgets
        relative_widget = QWidget()
        rh = QHBoxLayout(relative_widget)
        self.rel_value = QSpinBox()
        self.rel_value.setRange(1, 365)
        self.rel_unit  = QComboBox()
        self.rel_unit.addItems(["days","weeks","months"])
        rh.addWidget(self.rel_value)
        rh.addWidget(self.rel_unit)
        v.addWidget(relative_widget)

        # فقط أظهر المناسب
        def update_visibility():
            fixed_widget.setVisible(fixed_rb.isChecked())
            relative_widget.setVisible(relative_rb.isChecked())
        fixed_rb.toggled.connect(update_visibility)
        update_visibility()

        # OK / Cancel
        bb = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)

        if dlg.exec_() == QDialog.Accepted:
            if fixed_rb.isChecked():
                df = {
                    'type':'fixed',
                    'from': self.from_date.date().toString("yyyy-MM-dd"),
                    'to':   self.to_date.date().toString("yyyy-MM-dd")
                }
            else:
                df = {
                    'type':'relative',
                    'value': self.rel_value.value(),
                    'unit': self.rel_unit.currentText()
                }
            self.date_filters.append(df)
            self._load_date_filters_into_list()

    def remove_selected_date_filter(self):
        row = self.date_filters_list.currentRow()
        if row>=0:
            self.date_filters.pop(row)
            self._load_date_filters_into_list()

    def get_date_filters(self) -> list:
        """Return display strings for date filters (for UI display)"""
        return [self.date_filters_list.item(i).text() for i in range(self.date_filters_list.count())]
    
    def get_actual_date_filters(self) -> list:
        """Convert date filters to actual filter strings that the bot can use"""
        from datetime import date, timedelta
        import json
        actual_filters = []
        
        # Ensure date_filters is a list
        if not isinstance(self.date_filters, list):
            if isinstance(self.date_filters, str):
                try:
                    self.date_filters = json.loads(self.date_filters)
                    if not isinstance(self.date_filters, list):
                        self.date_filters = [{'type': 'relative', 'value': 3, 'unit': 'days'}]
                        logging.warning("⚠️ Converted date_filters to default: not a list")
                except (json.JSONDecodeError, ValueError):
                    self.date_filters = [{'type': 'relative', 'value': 3, 'unit': 'days'}]
                    logging.warning("⚠️ Reset date_filters to default: invalid JSON")
            else:
                self.date_filters = [{'type': 'relative', 'value': 3, 'unit': 'days'}]
                logging.warning("⚠️ Reset date_filters to default: not a list")
        
        for df in self.date_filters:
            # Skip if not a dictionary
            if not isinstance(df, dict):
                logging.warning(f"⚠️ Skipping invalid date filter (not a dict): {df}")
                continue
                
            try:
                if df.get('type') == 'fixed':
                    # Convert fixed dates to German format: dd.mm.yyyy
                    from_date = df.get('from')
                    to_date = df.get('to')
                    
                    if not from_date or not to_date:
                        logging.warning("⚠️ Skipping invalid fixed date filter: missing 'from' or 'to'")
                        continue
                        
                    # Convert to German format if it's a single day
                    if from_date == to_date:
                        # Single day: convert yyyy-MM-dd to dd.mm.yyyy
                        try:
                            year, month, day = from_date.split('-')
                            actual_filters.append(f"{day}.{month}.{year}")
                        except (ValueError, AttributeError):
                            logging.warning(f"⚠️ Invalid date format: {from_date}")
                            continue
                    else:
                        # Range: convert both dates
                        try:
                            from_parts = from_date.split('-')
                            to_parts = to_date.split('-')
                            if len(from_parts) == 3 and len(to_parts) == 3:
                                from_day, from_month, from_year = from_parts[2], from_parts[1], from_parts[0]
                                to_day, to_month, to_year = to_parts[2], to_parts[1], to_parts[0]
                                actual_filters.append(f"{from_day}.{from_month}.{from_year}→{to_day}.{to_month}.{to_year}")
                        except (ValueError, IndexError, AttributeError) as e:
                            logging.warning(f"⚠️ Error processing date range {from_date} - {to_date}: {e}")
                            continue
                            
                elif df.get('type') == 'relative':
                    # Convert relative dates to actual date list
                    value = df.get('value', 3)  # Default to 3 days if not specified
                    unit = df.get('unit', 'days')
                    
                    if unit == 'days':
                        # Use the build_date_filter_list function
                        from workers.megathreads_worker import build_date_filter_list
                        try:
                            relative_filters = build_date_filter_list(value)
                            actual_filters.extend(relative_filters)
                        except Exception as e:
                            logging.warning(f"⚠️ Error building date filter list: {str(e)}")
                elif unit == 'weeks':
                    days = value * 7
                    from workers.megathreads_worker import build_date_filter_list
                    weekly_filters = build_date_filter_list(days)
                    actual_filters.extend(weekly_filters)
                elif unit == 'months':
                    days = value * 30  # Approximate month as 30 days
                    from workers.megathreads_worker import build_date_filter_list
                    monthly_filters = build_date_filter_list(days)
                    actual_filters.extend(monthly_filters)
                else:
                    logging.warning(f"⚠️ Unsupported relative unit: {unit}")
                        
            except Exception as e:
                logging.warning(f"⚠️ Error processing date filter {df}: {str(e)}")
                continue
                
        # If no valid filters were found, use default
        if not actual_filters:
            logging.warning("⚠️ No valid date filters found, using default (last 3 days)")
            from workers.megathreads_worker import build_date_filter_list
            actual_filters = build_date_filter_list(3)
            
        return actual_filters

    def get_page_range(self) -> tuple:
        return (self.page_from_spin.value(), self.page_to_spin.value())

    def browse_download(self):
        start = self.config.get('download_dir', os.getcwd())
        directory = QFileDialog.getExistingDirectory(self, "Select Download Directory", start)
        if directory:
            self.download_edit.setText(directory)

    def _refresh_hosts_list(self):
        self.hosts_list.clear()
        for host in self.config.get('upload_hosts', []):
            item = QListWidgetItem(host)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.hosts_list.addItem(item)
    def _on_host_item_changed(self, _):
        """Emit hosts_updated when a host checkbox is toggled."""
        current_hosts = [
            self.hosts_list.item(i).text().strip()
            for i in range(self.hosts_list.count())
            if self.hosts_list.item(i).checkState() == Qt.Checked
        ]
        self.hosts_updated.emit(current_hosts)
    def delete_selected_host(self):
        """Delete the selected host from the list"""
        row = self.hosts_list.currentRow()
        if row >= 0:
            self.hosts_list.takeItem(row)
            # Emit signal with current hosts
            current_hosts = [self.hosts_list.item(i).text() for i in range(self.hosts_list.count())]
            self.hosts_updated.emit(current_hosts)
            logging.info(f"Host deleted. Current hosts: {current_hosts}")

    def add_new_host(self):
        host = self.new_host_edit.text().strip()
        if not host:
            return
        for i in range(self.hosts_list.count()):
            if self.hosts_list.item(i).text() == host:
                QMessageBox.warning(self, "Warning", f"Host '{host}' already exists.")
                return
        item = QListWidgetItem(host)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        self.hosts_list.addItem(item)
        self.new_host_edit.clear()
        # Emit signal with current hosts
        current_hosts = [self.hosts_list.item(i).text() for i in range(self.hosts_list.count())]
        self.hosts_updated.emit(current_hosts)
        logging.info(f"Host added. Current hosts: {current_hosts}")

    def reset_defaults(self):
        """Reset all settings to their default values."""
        try:
            # Reset download directory
            self.download_edit.setText(self.config.get('download_dir', ''))

            # Reset hosts list
            self.hosts_list.clear()
            
            # Reset API keys
            self.katfile_api_key_input.clear()
            self.rapidgator_token_input.clear()
            
            # Reset page range
            self.page_from_spin.setValue(1)
            self.page_to_spin.setValue(5)
            
            # Reset date filters
            self.date_filters = [{'type': 'relative', 'value': 3, 'unit': 'days'}]
            self._load_date_filters_into_list()
            # Reset Rapidgator backup option
            self.use_backup_rg_checkbox.setChecked(False)
            
            # Reset priority settings
            self.reset_priority_to_defaults()
            
            logging.info("🔄 Settings widget reset to defaults")
            QMessageBox.information(self, "Success", "Settings have been reset to default values.")
            
        except Exception as e:
            logging.error(f"Error resetting settings: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to reset settings: {e}")

    def load_settings(self, initial: bool = False):
        """Load settings from user manager and populate UI elements.

        Args:
            initial: If True, ignore any remembered user and treat as no user
                logged in. This keeps user-specific fields blank until the user
                explicitly logs in.
        """
        try:
            # Check if UI elements still exist
            if not hasattr(self, 'download_edit') or not self.download_edit:
                logging.warning("UI elements not initialized yet, skipping settings load")
                return
            # Default to global config in case any errors occur before we
            # determine the appropriate settings source
            settings_source = self.config
            source_name = "global config (no user)"

            # If user is logged in and this isn't an initial load, use user
            # settings. Otherwise use config for most values but leave
            # user-specific sections like upload hosts blank.
            if self.user_manager.get_current_user() and not initial:
                settings_source = self.user_manager.get_all_user_settings()
                source_name = f"user '{self.user_manager.get_current_user()}'"

            
            # Safely set UI elements with existence checks
            try:
                # Download Directory
                download_dir = settings_source.get('download_dir', '')
                if hasattr(self, 'download_edit') and self.download_edit:
                    self.download_edit.setText(download_dir)
                
                # Upload Hosts
                if hasattr(self, 'hosts_list') and self.hosts_list:
                    if self.user_manager.get_current_user() and not initial:
                        upload_hosts = settings_source.get('upload_hosts', [])
                    else:
                        upload_hosts = []  # hide until user logs in
                    self.hosts_list.clear()
                    for host in upload_hosts:
                        item = QListWidgetItem(host)
                        item.setFlags(
                            item.flags()
                            | Qt.ItemIsEditable
                            | Qt.ItemIsUserCheckable
                        )
                        item.setCheckState(Qt.Checked)
                        self.hosts_list.addItem(item)

                # Page range
                page_from = settings_source.get('page_from', 1)
                page_to = settings_source.get('page_to', 5)
                # Ensure values are integers for setValue
                try:
                    page_from = int(page_from)
                    page_to = int(page_to)
                except (ValueError, TypeError):
                    page_from = 1
                    page_to = 5
                
                # Set page range spin boxes
                if hasattr(self, 'page_from_spin') and self.page_from_spin:
                    self.page_from_spin.setValue(page_from)
                if hasattr(self, 'page_to_spin') and self.page_to_spin:
                    self.page_to_spin.setValue(page_to)
                
                # Load API Keys
                if hasattr(self, 'katfile_api_key_input') and self.katfile_api_key_input:
                    self.katfile_api_key_input.setText(settings_source.get('katfile_api_key', ''))
                
                # Load Rapidgator token
                rapidgator_token = settings_source.get('rapidgator_api_token', '')
                if hasattr(self, 'rapidgator_token_input') and self.rapidgator_token_input:
                    self.rapidgator_token_input.setText(rapidgator_token)
                    # Enable validate button if token exists
                    if hasattr(self, 'validate_token_btn') and self.validate_token_btn:
                        self.validate_token_btn.setEnabled(bool(rapidgator_token))
                # Rapidgator backup option
                if hasattr(self, 'use_backup_rg_checkbox') and self.use_backup_rg_checkbox:
                    self.use_backup_rg_checkbox.setChecked(settings_source.get('use_backup_rg', False))
                
                # Update the bot's Rapidgator token if parent has bot attribute
                if (hasattr(self, 'parent') and self.parent() and 
                    hasattr(self.parent(), 'bot') and hasattr(self.parent().bot, 'rapidgator_token')):
                    
                    self.parent().bot.rapidgator_token = rapidgator_token
                    logging.info("✅ Loaded Rapidgator token into bot instance")
                    
                    # Also update the token file for the current user if token exists
                    if rapidgator_token:
                        try:
                            # Calculate expiry time (30 days from now)
                            expiry_time = int(time.time()) + (30 * 24 * 60 * 60)
                            
                            # Update bot's token and expiry
                            self.parent().bot.rapidgator_token = rapidgator_token
                            self.parent().bot.rapidgator_token_expiry = expiry_time
                            
                            # Save the token to the appropriate file
                            self.parent().bot.save_token('download')
                            logging.info("✅ Saved Rapidgator token to user's token file")
                        except Exception as e:
                            logging.error(f"Error saving Rapidgator token: {e}", exc_info=True)
                
                # Load priority settings
                if hasattr(self, 'load_priority_settings'):
                    self.load_priority_settings()
                
                logging.info(f"✅ Settings loaded successfully from {source_name}.")
                
            except RuntimeError as re:
                # Handle case where C++ object has been deleted
                if 'wrapped C/C++ object' in str(re):
                    logging.warning("UI objects no longer available, skipping settings update")
                    return
                raise  # Re-raise if it's a different error
                
        except Exception as e:
            logging.error(f"❌ Error loading settings: {e}", exc_info=True)
            # Only show message box if UI is still available
            if hasattr(self, 'isVisible') and self.isVisible():
                QMessageBox.critical(self, "Error", f"Failed to load settings: {e}")

    def _on_rapidgator_token_changed(self, text):
        """Handle changes to the Rapidgator token input"""
        # Enable validate button when there's text, disable when empty
        self.validate_token_btn.setEnabled(bool(text.strip()))
        
        # Clear status when typing
        self.rapidgator_status_label.clear()
        self.rapidgator_status_label.setVisible(False)

    def _validate_rapidgator_token(self):
        """Validate the Rapidgator API token or credentials"""
        token = self.rapidgator_token_input.text().strip()
        username = self.rg_user_edit.text().strip()
        password = self.rg_pass_edit.text().strip()
        twofa = self.rg_code_edit.text().strip() or None
        
        if not token and not (username and password):
            self.rapidgator_status_label.setText("Please enter token or username/password")
            self.rapidgator_status_label.setStyleSheet("color: red;")
            return
            
        self.validate_token_btn.setEnabled(False)
        self.validate_token_btn.setText("Validating...")
        self.rapidgator_status_label.setVisible(True)
        
        try:
            # Create a temporary upload handler to validate the token/credentials
            if token:
                # If token is provided, validate it directly
                handler = RapidgatorUploadHandler(
                    filepath=Path("dummy.txt"),  # Dummy path for validation
                    username=username or "dummy",
                    password=password or "dummy",
                    token=token,
                    twofa_code=twofa
                )
                is_valid = handler.is_token_valid()
            else:
                # If no token but have username/password, try to get a new token
                handler = RapidgatorUploadHandler(
                    filepath=Path("dummy.txt"),  # Dummy path for validation
                    username=username,
                    password=password,
                    token="",  # Empty to force new token generation
                    twofa_code=twofa
                )
                is_valid = handler.is_token_valid()
                if is_valid and hasattr(handler, 'token') and handler.token:
                    # Update the token field with the new token
                    self.rapidgator_token_input.setText(handler.token)
                    token = handler.token
            
            if is_valid:
                self.rapidgator_status_label.setText("✅ Token is valid")
                self.rapidgator_status_label.setStyleSheet("color: green;")
                
                # Save the token immediately if validation succeeds
                if hasattr(self.parent(), 'bot') and hasattr(self.parent().bot, 'rapidgator_token'):
                    self.parent().bot.rapidgator_token = token
                    # Calculate expiry time (30 days from now)
                    expiry_time = int(time.time()) + (30 * 24 * 60 * 60)
                    self.parent().bot.rapidgator_token_expiry = expiry_time
                    self.parent().bot.save_token('download')
                    
                    # Update token in all active handlers if they exist
                    if hasattr(self.parent().bot, 'upload_worker') and hasattr(self.parent().bot.upload_worker, 'handlers'):
                        if 'rapidgator' in self.parent().bot.upload_worker.handlers:
                            self.parent().bot.upload_worker.handlers['rapidgator'].set_token(token)
                    
                    logging.info("✅ Validated and saved Rapidgator token")
            else:
                self.rapidgator_status_label.setText("❌ Invalid credentials or token")
                self.rapidgator_status_label.setStyleSheet("color: red;")
                
        except Exception as e:
            logging.error(f"Error validating Rapidgator token: {e}", exc_info=True)
            self.rapidgator_status_label.setText(f"❌ Error: {str(e)}")
            self.rapidgator_status_label.setStyleSheet("color: red;")
            
        finally:
            self.validate_token_btn.setEnabled(True)
            self.validate_token_btn.setText("Validate")

    def save_settings(self):
        """Save current settings to user manager and update config."""
        try:
            # Get values from UI
            new_download_dir = self.download_edit.text().strip()
            new_hosts = []
            for i in range(self.hosts_list.count()):
                item = self.hosts_list.item(i)
                host = item.text().strip()
                if host and item.checkState() == Qt.Checked:
                    new_hosts.append(host)

            new_from = self.page_from_spin.value()
            new_to = self.page_to_spin.value()
            new_api_key = self.katfile_api_key_input.text().strip()
            
            # Get Rapidgator credentials
            rg_user = self.rg_user_edit.text().strip()
            rg_pass = self.rg_pass_edit.text().strip()
            rg_code = self.rg_code_edit.text().strip()
            new_rapidgator_token = self.rapidgator_token_input.text().strip()
            
            # Validate page range
            if new_from > new_to:
                QMessageBox.warning(self, "Invalid Range", "'From' page cannot be greater than 'To' page.")
                return
            
            # Get current priority order from UI
            current_priority = self.get_current_priority()
            
            # Prepare settings dictionary
            new_settings = {
                'download_dir': new_download_dir,
                'upload_hosts': new_hosts,
                'date_filters': list(self.date_filters),
                'page_from': new_from,
                'page_to': new_to,
                'katfile_api_key': new_api_key,
                'rapidgator_user': rg_user,
                'rapidgator_pass': rg_pass,
                'rapidgator_2fa': rg_code,
                'rapidgator_api_token': new_rapidgator_token,
                'download_hosts_priority': current_priority,
                'use_backup_rg': self.use_backup_rg_checkbox.isChecked()
            }
            
            # Update the bot's Rapidgator token if parent has bot attribute and token has changed
            if (hasattr(self.parent(), 'bot') and 
                hasattr(self.parent().bot, 'rapidgator_token') and 
                self.parent().bot.rapidgator_token != new_rapidgator_token):
                
                self.parent().bot.rapidgator_token = new_rapidgator_token
                
                # If we have a new token, save it with expiration
                if new_rapidgator_token:
                    try:
                        # Calculate expiry time (30 days from now)
                        expiry_time = int(time.time()) + (30 * 24 * 60 * 60)
                        
                        # Update bot's token and expiry
                        self.parent().bot.rapidgator_token = new_rapidgator_token
                        self.parent().bot.rapidgator_token_expiry = expiry_time
                        
                        # Save the token to the appropriate file
                        self.parent().bot.save_token('download')
                        logging.info("✅ Saved Rapidgator token to user's token file")
                    except Exception as e:
                        logging.error(f"Error saving Rapidgator token: {e}", exc_info=True)
            
            # Save to user manager if logged in, otherwise to config
            if self.user_manager.get_current_user():
                # Save all settings to user settings
                for key, value in new_settings.items():
                    self.user_manager.set_user_setting(key, value)
                logging.info("✅ Settings saved to user settings")
            else:
                # Save to config if not logged in
                for key, value in new_settings.items():
                    self.config[key] = value
                logging.info("✅ Settings saved to config")

            # Emit updated hosts list so the main window can react immediately
            self.hosts_updated.emit(new_hosts)
            # Emit backup RG state
            self.use_backup_rg_changed.emit(self.use_backup_rg_checkbox.isChecked())

            # Show success message
            QMessageBox.information(self, "Success", "Settings saved successfully!")
            
        except Exception as e:
            logging.error(f"Error saving settings: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")
    
    def load_priority_settings(self):
        """Load download hosts priority from settings and populate UI"""
        default_priority = [
            'rapidgator.net',      # Premium #1
            'katfile.com',         # Premium #2  
            'nitroflare.com',      # Premium/Fast
            'ddownload.com',       # Fast/Free
            'mega.nz',             # Free/Fast
            'xup.in',              # New hosts
            'f2h.io',
            'filepv.com',
            'filespayouts.com',
            'uploady.io'
        ]
        
        try:
            if self.user_manager.get_current_user():
                priority = self.user_manager.get_user_setting('download_hosts_priority', default_priority)
                if not isinstance(priority, list) or not priority:
                    priority = default_priority
            else:
                priority = default_priority
            
            # Clear and populate list
            self.priority_list.clear()
            for i, host in enumerate(priority, 1):
                item = QListWidgetItem(f"{i}. {host}")
                item.setData(Qt.UserRole, host)
                self.priority_list.addItem(item)
                
        except Exception as e:
            logging.error(f"Error loading priority settings: {e}")
            self.reset_priority_to_defaults()
    
    def reset_priority_to_defaults(self):
        """Reset download hosts priority to defaults"""
        default_priority = [
            'rapidgator.net',      # Premium #1
            'katfile.com',         # Premium #2  
            'nitroflare.com',      # Premium/Fast
            'ddownload.com',       # Fast/Free
            'mega.nz',             # Free/Fast
            'xup.in',              # New hosts
            'f2h.io',
            'filepv.com',
            'filespayouts.com',
            'uploady.io'
        ]
        
        self.priority_list.clear()
        for i, host in enumerate(default_priority, 1):
            item = QListWidgetItem(f"{i}. {host}")
            item.setData(Qt.UserRole, host)
            self.priority_list.addItem(item)
        
        logging.info("🔄 Download hosts priority reset to defaults")
    
    def get_current_priority(self):
        """Get current priority order from UI"""
        priority = []
        for i in range(self.priority_list.count()):
            item = self.priority_list.item(i)
            host = item.data(Qt.UserRole)
            priority.append(host)
        return priority
