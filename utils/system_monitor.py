"""
System Monitoring and Health Check Module
==========================================

This module provides comprehensive system monitoring, health checks,
and performance analysis for the ForumBot application.

Author: Professional Python Developer
Purpose: Monitor system health and prevent performance issues
"""

import logging
import threading
import time
import psutil
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import json
from datetime import datetime, timedelta
from PyQt5.QtCore import QObject, pyqtSignal, QTimer

from utils.crash_protection import crash_logger, ErrorSeverity


class HealthStatus(Enum):
    """System health status levels."""
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


@dataclass
class SystemMetrics:
    """System performance metrics snapshot."""
    timestamp: float = field(default_factory=time.time)
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_mb: float = 0.0
    disk_usage_percent: float = 0.0
    disk_free_gb: float = 0.0
    process_count: int = 0
    thread_count: int = 0
    open_files: int = 0
    network_connections: int = 0
    uptime_seconds: float = 0.0
    health_status: HealthStatus = HealthStatus.GOOD


@dataclass
class PerformanceAlert:
    """Performance alert data."""
    timestamp: float
    severity: ErrorSeverity
    metric_name: str
    current_value: float
    threshold: float
    message: str
    suggestion: str


class SystemMonitor(QObject):
    """
    Professional System Monitoring Class
    Provides real-time monitoring and alerting for system resources
    """

    # PyQt Signals for GUI integration
    health_status_changed = pyqtSignal(str)  # HealthStatus.value
    performance_alert = pyqtSignal(str, str, str)  # severity, metric, message
    metrics_updated = pyqtSignal(dict)  # SystemMetrics as dict

    def __init__(self, monitoring_interval: float = 30.0):
        """
        Initialize System Monitor

        Args:
            monitoring_interval: Interval in seconds between health checks
        """
        super().__init__()

        self.monitoring_interval = monitoring_interval
        self.is_monitoring = False
        self._monitoring_thread = None
        self._lock = threading.RLock()

        # Performance thresholds
        self.thresholds = {
            'cpu_percent': 85.0,
            'memory_percent': 80.0,
            'disk_usage_percent': 90.0,
            'disk_free_gb_min': 1.0,
            'process_count_max': 200,
            'thread_count_max': 500,
            'open_files_max': 1000,
            'network_connections_max': 100
        }

        # Metrics history (last 100 snapshots)
        self.metrics_history: List[SystemMetrics] = []
        self.max_history = 100

        # Alert history (last 50 alerts)
        self.alerts_history: List[PerformanceAlert] = []
        self.max_alerts = 50

        # Current metrics
        self.current_metrics: Optional[SystemMetrics] = None
        self.last_health_status = HealthStatus.GOOD

        # Process start time for uptime calculation
        self.process_start_time = time.time()

        # Qt Timer for GUI thread safety
        self.qt_timer = QTimer()
        self.qt_timer.timeout.connect(self._update_metrics_safe)

    def start_monitoring(self):
        """Start system monitoring in background thread."""
        with self._lock:
            if self.is_monitoring:
                crash_logger.logger.warning("System monitoring already running")
                return

            self.is_monitoring = True

            # Start monitoring thread
            self._monitoring_thread = threading.Thread(
                target=self._monitoring_loop,
                name="SystemMonitor",
                daemon=True
            )
            self._monitoring_thread.start()

            # Start Qt timer for GUI updates (every 10 seconds)
            self.qt_timer.start(10000)

            crash_logger.logger.info("✅ System monitoring started")

    def stop_monitoring(self):
        """Stop system monitoring gracefully."""
        with self._lock:
            if not self.is_monitoring:
                return

            self.is_monitoring = False

            # Stop Qt timer
            self.qt_timer.stop()

            # Wait for monitoring thread to finish
            if self._monitoring_thread and self._monitoring_thread.is_alive():
                self._monitoring_thread.join(timeout=5.0)
                if self._monitoring_thread.is_alive():
                    crash_logger.logger.warning("Monitoring thread did not stop gracefully")

            crash_logger.logger.info("✅ System monitoring stopped")

    def _monitoring_loop(self):
        """Main monitoring loop running in background thread."""
        crash_logger.logger.info("🔍 System monitoring loop started")

        while self.is_monitoring:
            try:
                # Collect system metrics
                metrics = self._collect_system_metrics()

                # Analyze and store metrics
                with self._lock:
                    self.current_metrics = metrics
                    self._add_metrics_to_history(metrics)

                # Check for performance issues
                alerts = self._analyze_performance(metrics)

                # Process alerts
                for alert in alerts:
                    self._handle_alert(alert)

                # Sleep until next monitoring cycle
                time.sleep(self.monitoring_interval)

            except Exception as e:
                crash_logger.logger.error(f"💥 System monitoring error: {e}")
                time.sleep(5.0)  # Short sleep before retry

        crash_logger.logger.info("🔍 System monitoring loop ended")

    def _collect_system_metrics(self) -> SystemMetrics:
        """Collect comprehensive system metrics."""
        try:
            # Get process info
            process = psutil.Process()

            # Basic system metrics
            cpu_percent = psutil.cpu_percent(interval=1.0)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            # Process-specific metrics
            proc_memory = process.memory_info()
            proc_threads = process.num_threads()

            try:
                proc_open_files = len(process.open_files())
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                proc_open_files = 0

            try:
                proc_connections = len(process.connections())
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                proc_connections = 0

            # Calculate uptime
            uptime = time.time() - self.process_start_time

            # Create metrics snapshot
            metrics = SystemMetrics(
                timestamp=time.time(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_mb=proc_memory.rss / 1024 / 1024,
                disk_usage_percent=(disk.used / disk.total) * 100,
                disk_free_gb=disk.free / (1024 ** 3),
                process_count=len(psutil.pids()),
                thread_count=proc_threads,
                open_files=proc_open_files,
                network_connections=proc_connections,
                uptime_seconds=uptime
            )

            # Determine health status
            metrics.health_status = self._calculate_health_status(metrics)

            return metrics

        except Exception as e:
            crash_logger.logger.error(f"💥 Metrics collection failed: {e}")

            # Return basic fallback metrics
            return SystemMetrics(
                timestamp=time.time(),
                health_status=HealthStatus.WARNING,
                uptime_seconds=time.time() - self.process_start_time
            )

    def _calculate_health_status(self, metrics: SystemMetrics) -> HealthStatus:
        """Calculate overall system health status."""
        critical_issues = 0
        warning_issues = 0

        # Check each metric against thresholds
        if metrics.cpu_percent > self.thresholds['cpu_percent']:
            critical_issues += 1
        elif metrics.cpu_percent > self.thresholds['cpu_percent'] * 0.8:
            warning_issues += 1

        if metrics.memory_percent > self.thresholds['memory_percent']:
            critical_issues += 1
        elif metrics.memory_percent > self.thresholds['memory_percent'] * 0.8:
            warning_issues += 1

        if metrics.disk_usage_percent > self.thresholds['disk_usage_percent']:
            critical_issues += 1
        elif metrics.disk_usage_percent > self.thresholds['disk_usage_percent'] * 0.9:
            warning_issues += 1

        if metrics.disk_free_gb < self.thresholds['disk_free_gb_min']:
            critical_issues += 2  # Disk space is very important

        if metrics.memory_mb > 1000:  # > 1GB memory usage
            warning_issues += 1

        if metrics.memory_mb > 2000:  # > 2GB memory usage
            critical_issues += 1

        # Determine overall status
        if critical_issues >= 3:
            return HealthStatus.EMERGENCY
        elif critical_issues >= 2:
            return HealthStatus.CRITICAL
        elif critical_issues >= 1:
            return HealthStatus.WARNING
        elif warning_issues >= 3:
            return HealthStatus.WARNING
        elif warning_issues >= 1:
            return HealthStatus.GOOD
        else:
            return HealthStatus.EXCELLENT

    def _analyze_performance(self, metrics: SystemMetrics) -> List[PerformanceAlert]:
        """Analyze metrics and generate performance alerts."""
        alerts = []

        # CPU usage alert
        if metrics.cpu_percent > self.thresholds['cpu_percent']:
            alerts.append(PerformanceAlert(
                timestamp=time.time(),
                severity=ErrorSeverity.CRITICAL,
                metric_name="CPU Usage",
                current_value=metrics.cpu_percent,
                threshold=self.thresholds['cpu_percent'],
                message=f"High CPU usage: {metrics.cpu_percent:.1f}%",
                suggestion="Consider reducing concurrent operations or optimizing CPU-intensive tasks"
            ))

        # Memory usage alert
        if metrics.memory_percent > self.thresholds['memory_percent']:
            alerts.append(PerformanceAlert(
                timestamp=time.time(),
                severity=ErrorSeverity.CRITICAL,
                metric_name="Memory Usage",
                current_value=metrics.memory_percent,
                threshold=self.thresholds['memory_percent'],
                message=f"High memory usage: {metrics.memory_percent:.1f}%",
                suggestion="Consider restarting the application or reducing memory-intensive operations"
            ))

        # Application memory usage alert
        if metrics.memory_mb > 1000:
            severity = ErrorSeverity.CRITICAL if metrics.memory_mb > 2000 else ErrorSeverity.HIGH
            alerts.append(PerformanceAlert(
                timestamp=time.time(),
                severity=severity,
                metric_name="App Memory Usage",
                current_value=metrics.memory_mb,
                threshold=1000.0,
                message=f"High application memory usage: {metrics.memory_mb:.1f}MB",
                suggestion="Consider cleaning up resources or restarting the application"
            ))

        # Disk space alert
        if metrics.disk_free_gb < self.thresholds['disk_free_gb_min']:
            alerts.append(PerformanceAlert(
                timestamp=time.time(),
                severity=ErrorSeverity.CRITICAL,
                metric_name="Disk Space",
                current_value=metrics.disk_free_gb,
                threshold=self.thresholds['disk_free_gb_min'],
                message=f"Low disk space: {metrics.disk_free_gb:.1f}GB free",
                suggestion="Clean up temporary files or move files to another drive"
            ))

        return alerts

    def _handle_alert(self, alert: PerformanceAlert):
        """Handle performance alert by logging and emitting signal."""
        # Add to alerts history
        with self._lock:
            self.alerts_history.append(alert)
            if len(self.alerts_history) > self.max_alerts:
                self.alerts_history.pop(0)

        # Log the alert
        if alert.severity == ErrorSeverity.CRITICAL:
            crash_logger.logger.error(f"🚨 PERFORMANCE ALERT: {alert.message} | {alert.suggestion}")
        elif alert.severity == ErrorSeverity.HIGH:
            crash_logger.logger.warning(f"⚠️ PERFORMANCE WARNING: {alert.message} | {alert.suggestion}")
        else:
            crash_logger.logger.info(f"📊 PERFORMANCE INFO: {alert.message} | {alert.suggestion}")

        # Emit Qt signal for GUI
        try:
            self.performance_alert.emit(
                alert.severity.value,
                alert.metric_name,
                f"{alert.message} | {alert.suggestion}"
            )
        except Exception as e:
            crash_logger.logger.error(f"Failed to emit performance alert: {e}")

    def _add_metrics_to_history(self, metrics: SystemMetrics):
        """Add metrics to history with size management."""
        self.metrics_history.append(metrics)
        if len(self.metrics_history) > self.max_history:
            self.metrics_history.pop(0)

        # Check if health status changed
        if metrics.health_status != self.last_health_status:
            self.last_health_status = metrics.health_status
            crash_logger.logger.info(f"🏥 Health status changed to: {metrics.health_status.value}")

            try:
                self.health_status_changed.emit(metrics.health_status.value)
            except Exception as e:
                crash_logger.logger.error(f"Failed to emit health status change: {e}")

    def _update_metrics_safe(self):
        """Thread-safe metrics update for Qt GUI."""
        try:
            with self._lock:
                if self.current_metrics:
                    metrics_dict = {
                        'timestamp': self.current_metrics.timestamp,
                        'cpu_percent': self.current_metrics.cpu_percent,
                        'memory_percent': self.current_metrics.memory_percent,
                        'memory_mb': self.current_metrics.memory_mb,
                        'disk_usage_percent': self.current_metrics.disk_usage_percent,
                        'disk_free_gb': self.current_metrics.disk_free_gb,
                        'process_count': self.current_metrics.process_count,
                        'thread_count': self.current_metrics.thread_count,
                        'open_files': self.current_metrics.open_files,
                        'network_connections': self.current_metrics.network_connections,
                        'uptime_seconds': self.current_metrics.uptime_seconds,
                        'health_status': self.current_metrics.health_status.value
                    }

                    self.metrics_updated.emit(metrics_dict)
        except Exception as e:
            crash_logger.logger.error(f"Failed to update metrics for GUI: {e}")

    def get_current_metrics(self) -> Optional[SystemMetrics]:
        """Get current system metrics thread-safely."""
        with self._lock:
            return self.current_metrics

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get summary of recent metrics."""
        with self._lock:
            if not self.metrics_history:
                return {"status": "No metrics available"}

            recent_metrics = self.metrics_history[-10:]  # Last 10 snapshots

            # Calculate averages
            avg_cpu = sum(m.cpu_percent for m in recent_metrics) / len(recent_metrics)
            avg_memory = sum(m.memory_mb for m in recent_metrics) / len(recent_metrics)
            avg_disk = sum(m.disk_usage_percent for m in recent_metrics) / len(recent_metrics)

            current = self.current_metrics

            return {
                "status": "Available",
                "current_health": current.health_status.value if current else "Unknown",
                "uptime_hours": (current.uptime_seconds / 3600) if current else 0,
                "average_cpu_percent": round(avg_cpu, 1),
                "average_memory_mb": round(avg_memory, 1),
                "average_disk_usage": round(avg_disk, 1),
                "current_memory_mb": current.memory_mb if current else 0,
                "current_threads": current.thread_count if current else 0,
                "total_snapshots": len(self.metrics_history),
                "total_alerts": len(self.alerts_history),
                "recent_alerts": len([a for a in self.alerts_history if time.time() - a.timestamp < 3600])  # Last hour
            }

    def export_metrics(self, filepath: Optional[str] = None) -> str:
        """Export metrics history to JSON file."""
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"system_metrics_{timestamp}.json"

        try:
            export_data = {
                "export_timestamp": time.time(),
                "export_date": datetime.now().isoformat(),
                "summary": self.get_metrics_summary(),
                "metrics_history": [
                    {
                        "timestamp": m.timestamp,
                        "date": datetime.fromtimestamp(m.timestamp).isoformat(),
                        "cpu_percent": m.cpu_percent,
                        "memory_percent": m.memory_percent,
                        "memory_mb": m.memory_mb,
                        "disk_usage_percent": m.disk_usage_percent,
                        "disk_free_gb": m.disk_free_gb,
                        "health_status": m.health_status.value
                    }
                    for m in self.metrics_history
                ],
                "alerts_history": [
                    {
                        "timestamp": a.timestamp,
                        "date": datetime.fromtimestamp(a.timestamp).isoformat(),
                        "severity": a.severity.value,
                        "metric_name": a.metric_name,
                        "current_value": a.current_value,
                        "threshold": a.threshold,
                        "message": a.message,
                        "suggestion": a.suggestion
                    }
                    for a in self.alerts_history
                ]
            }

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)

            crash_logger.logger.info(f"📊 Metrics exported to: {filepath}")
            return filepath

        except Exception as e:
            crash_logger.logger.error(f"Failed to export metrics: {e}")
            return ""


# Global system monitor instance
system_monitor = SystemMonitor()


def start_system_monitoring():
    """Start global system monitoring."""
    system_monitor.start_monitoring()


def stop_system_monitoring():
    """Stop global system monitoring."""
    system_monitor.stop_monitoring()


def get_system_health() -> HealthStatus:
    """Get current system health status."""
    metrics = system_monitor.get_current_metrics()
    return metrics.health_status if metrics else HealthStatus.GOOD


def force_health_check() -> SystemMetrics:
    """Force an immediate health check and return metrics."""
    return system_monitor._collect_system_metrics()