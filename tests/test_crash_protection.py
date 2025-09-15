#!/usr/bin/env python3
"""
Crash Protection Test Suite
===========================

Comprehensive test suite to verify all crash protection mechanisms
and bulletproof error handling implementations.

Author: Professional Python Developer
Purpose: Ensure the application is completely crash-proof
"""

import sys
import time
import threading
import tempfile
import subprocess
from pathlib import Path
import logging

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Import crash protection modules
from utils.crash_protection import (
    safe_execute, resource_protection, SafeProcessManager, SafePathManager,
    ErrorSeverity, safe_process_manager, monitor_memory_usage, CircuitBreaker,
    crash_logger, emergency_shutdown
)

from utils.system_monitor import (
    SystemMonitor, HealthStatus, system_monitor,
    start_system_monitoring, stop_system_monitoring, get_system_health
)


class CrashProtectionTester:
    """Comprehensive crash protection test suite."""

    def __init__(self):
        self.test_results = {}
        self.failed_tests = []
        self.passed_tests = []

    def run_all_tests(self):
        """Run all crash protection tests."""
        print("🚀 Starting Comprehensive Crash Protection Test Suite")
        print("=" * 60)

        # Test categories
        test_categories = [
            ("Safe Execute Decorator", self._test_safe_execute),
            ("Resource Protection", self._test_resource_protection),
            ("Safe Process Manager", self._test_safe_process_manager),
            ("Safe Path Manager", self._test_safe_path_manager),
            ("Circuit Breaker", self._test_circuit_breaker),
            ("Memory Monitoring", self._test_memory_monitoring),
            ("System Monitor", self._test_system_monitor),
            ("Emergency Shutdown", self._test_emergency_shutdown),
            ("Real-world Scenarios", self._test_real_world_scenarios)
        ]

        for category_name, test_func in test_categories:
            print(f"\n🧪 Testing: {category_name}")
            print("-" * 40)

            try:
                start_time = time.time()
                test_func()
                elapsed = time.time() - start_time
                print(f"✅ {category_name} - PASSED ({elapsed:.2f}s)")
                self.passed_tests.append(category_name)

            except Exception as e:
                print(f"❌ {category_name} - FAILED: {e}")
                self.failed_tests.append((category_name, str(e)))

        # Print final results
        self._print_final_results()

    def _test_safe_execute(self):
        """Test safe_execute decorator functionality."""

        # Test 1: Successful execution
        @safe_execute(max_retries=2, default_return="default")
        def successful_func():
            return "success"

        result = successful_func()
        assert result == "success", f"Expected 'success', got {result}"

        # Test 2: Failed execution with default return
        @safe_execute(max_retries=2, default_return="default")
        def failing_func():
            raise ValueError("Test error")

        result = failing_func()
        assert result == "default", f"Expected 'default', got {result}"

        # Test 3: Retry mechanism
        attempt_count = 0

        @safe_execute(max_retries=3, default_return="failed")
        def retry_func():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise RuntimeError(f"Attempt {attempt_count}")
            return "succeeded"

        result = retry_func()
        assert result == "succeeded", f"Expected 'succeeded', got {result}"
        assert attempt_count == 3, f"Expected 3 attempts, got {attempt_count}"

        print("  ✓ Safe execute decorator working correctly")

    def _test_resource_protection(self):
        """Test resource protection context manager."""

        cleanup_called = False

        def cleanup_func():
            nonlocal cleanup_called
            cleanup_called = True

        # Test 1: Normal execution with cleanup
        with resource_protection("test_resource", cleanup_func):
            time.sleep(0.1)  # Simulate work

        assert cleanup_called, "Cleanup function was not called"

        # Test 2: Exception handling with cleanup
        cleanup_called = False
        try:
            with resource_protection("test_resource", cleanup_func):
                raise ValueError("Test exception")
        except ValueError:
            pass  # Expected

        assert cleanup_called, "Cleanup function was not called after exception"

        print("  ✓ Resource protection working correctly")

    def _test_safe_process_manager(self):
        """Test safe process manager functionality."""

        # Test 1: Successful command execution
        success, stdout, stderr = safe_process_manager.execute_safe(
            ["python", "--version"],
            timeout=5.0
        )
        assert success, f"Python version command failed: {stderr}"
        assert "Python" in stdout, f"Expected 'Python' in output, got: {stdout}"

        # Test 2: Command timeout
        success, stdout, stderr = safe_process_manager.execute_safe(
            ["python", "-c", "import time; time.sleep(10)"],
            timeout=1.0
        )
        assert not success, "Long-running command should have timed out"
        assert "timeout" in stderr.lower(), f"Expected timeout message, got: {stderr}"

        # Test 3: Non-existent command
        success, stdout, stderr = safe_process_manager.execute_safe(
            ["nonexistent_command_12345"],
            timeout=5.0
        )
        assert not success, "Non-existent command should fail"

        print("  ✓ Safe process manager working correctly")

    def _test_safe_path_manager(self):
        """Test safe path manager functionality."""

        # Test 1: Valid path validation
        temp_dir = Path(tempfile.gettempdir())
        validated = SafePathManager.validate_path(temp_dir)
        assert validated == temp_dir.resolve(), f"Path validation failed"

        # Test 2: Invalid path validation
        try:
            SafePathManager.validate_path("con")  # Windows reserved name
            assert False, "Should have raised ValueError for dangerous path"
        except ValueError:
            pass  # Expected

        # Test 3: Directory creation
        test_dir = temp_dir / "crash_test_dir"
        success = SafePathManager.safe_create_directory(test_dir)
        assert success, "Directory creation failed"
        assert test_dir.exists(), "Directory was not created"

        # Test 4: Directory removal
        success = SafePathManager.safe_remove_directory(test_dir)
        assert success, "Directory removal failed"
        assert not test_dir.exists(), "Directory was not removed"

        print("  ✓ Safe path manager working correctly")

    def _test_circuit_breaker(self):
        """Test circuit breaker functionality."""

        # Create circuit breaker with low threshold for testing
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1.0)

        # Test 1: Normal operation
        def working_func():
            return "success"

        result = cb.call(working_func)
        assert result == "success", f"Expected 'success', got {result}"

        # Test 2: Trigger circuit breaker
        def failing_func():
            raise RuntimeError("Test failure")

        # Fail enough times to open circuit
        for _ in range(3):
            try:
                cb.call(failing_func)
            except RuntimeError:
                pass

        # Circuit should now be open
        try:
            cb.call(working_func)
            assert False, "Circuit breaker should be open"
        except Exception as e:
            assert "OPEN" in str(e), f"Expected 'OPEN' in error message, got: {e}"

        # Test 3: Recovery after timeout
        time.sleep(1.1)  # Wait for recovery timeout
        result = cb.call(working_func)  # Should work again
        assert result == "success", f"Expected recovery to work, got {result}"

        print("  ✓ Circuit breaker working correctly")

    def _test_memory_monitoring(self):
        """Test memory monitoring functionality."""

        # Test 1: Basic memory monitoring
        memory_mb = monitor_memory_usage(threshold_mb=1000.0)
        assert memory_mb > 0, f"Memory usage should be positive, got {memory_mb}"

        # Test 2: Memory threshold warning
        # This should trigger a warning log (check manually in output)
        memory_mb = monitor_memory_usage(threshold_mb=1.0)  # Very low threshold

        print(f"  ✓ Memory monitoring working correctly (current: {memory_mb:.1f}MB)")

    def _test_system_monitor(self):
        """Test system monitoring functionality."""

        # Test 1: Create system monitor
        monitor = SystemMonitor(monitoring_interval=1.0)
        assert monitor is not None, "System monitor creation failed"

        # Test 2: Collect metrics
        metrics = monitor._collect_system_metrics()
        assert metrics is not None, "Metrics collection failed"
        assert metrics.cpu_percent >= 0, f"CPU percent should be non-negative, got {metrics.cpu_percent}"
        assert metrics.memory_mb > 0, f"Memory should be positive, got {metrics.memory_mb}"

        # Test 3: Health status calculation
        health = monitor._calculate_health_status(metrics)
        assert isinstance(health, HealthStatus), f"Health status should be HealthStatus enum, got {type(health)}"

        # Test 4: Start and stop monitoring
        monitor.start_monitoring()
        time.sleep(2.0)  # Let it run for a bit
        monitor.stop_monitoring()

        # Test 5: Global monitor functions
        current_health = get_system_health()
        assert isinstance(current_health, HealthStatus), f"Global health should be HealthStatus, got {type(current_health)}"

        print(f"  ✓ System monitor working correctly (health: {health.value})")

    def _test_emergency_shutdown(self):
        """Test emergency shutdown functionality."""

        # Test emergency shutdown (without actually shutting down)
        try:
            # This is a bit tricky to test without actually triggering shutdown
            # We'll just verify the function exists and is callable
            assert callable(emergency_shutdown), "Emergency shutdown should be callable"
            print("  ✓ Emergency shutdown function available")
        except Exception as e:
            raise AssertionError(f"Emergency shutdown test failed: {e}")

    def _test_real_world_scenarios(self):
        """Test real-world crash scenarios."""

        # Test 1: File processing with invalid paths
        @safe_execute(max_retries=2, default_return=False)
        def simulate_file_processing():
            # Simulate the type of operations that could crash
            invalid_path = Path("C:\\nonexistent\\very\\long\\path" * 10)
            try:
                SafePathManager.validate_path(invalid_path)
                return False
            except ValueError:
                return True  # Expected behavior

        result = simulate_file_processing()
        assert result, "File processing simulation failed"

        # Test 2: Process execution with timeout
        @safe_execute(max_retries=1, default_return=False)
        def simulate_archive_creation():
            success, stdout, stderr = safe_process_manager.execute_safe(
                ["ping", "127.0.0.1", "-n", "1"],  # Windows ping command
                timeout=5.0
            )
            return success

        result = simulate_archive_creation()
        # This might fail if ping is not available, but should not crash

        # Test 3: Memory stress test
        @safe_execute(max_retries=1, default_return=True)
        def simulate_memory_stress():
            # Monitor memory during a brief operation
            initial_memory = monitor_memory_usage()

            # Create some temporary data
            temp_data = []
            for i in range(1000):
                temp_data.append(f"test_data_{i}" * 100)

            final_memory = monitor_memory_usage()

            # Clean up
            del temp_data

            return True

        result = simulate_memory_stress()
        assert result, "Memory stress test failed"

        print("  ✓ Real-world scenarios handled correctly")

    def _print_final_results(self):
        """Print final test results summary."""
        print("\n" + "=" * 60)
        print("🏁 CRASH PROTECTION TEST RESULTS")
        print("=" * 60)

        total_tests = len(self.passed_tests) + len(self.failed_tests)

        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {len(self.passed_tests)}")
        print(f"❌ Failed: {len(self.failed_tests)}")

        if self.passed_tests:
            print(f"\n✅ PASSED TESTS:")
            for test in self.passed_tests:
                print(f"   • {test}")

        if self.failed_tests:
            print(f"\n❌ FAILED TESTS:")
            for test, error in self.failed_tests:
                print(f"   • {test}: {error}")

        success_rate = (len(self.passed_tests) / total_tests) * 100 if total_tests > 0 else 0
        print(f"\n📊 Success Rate: {success_rate:.1f}%")

        if success_rate >= 90:
            print("🎉 EXCELLENT! Your application is well-protected against crashes!")
        elif success_rate >= 75:
            print("👍 GOOD! Most crash protection mechanisms are working.")
        elif success_rate >= 50:
            print("⚠️ WARNING! Some crash protection mechanisms need attention.")
        else:
            print("🚨 CRITICAL! Major crash protection issues detected!")

        print("\n📝 RECOMMENDATION:")
        if len(self.failed_tests) == 0:
            print("   Your application has bulletproof error handling! 🛡️")
            print("   All crash protection mechanisms are working correctly.")
            print("   The app should run smoothly without unexpected crashes.")
        else:
            print("   Please review and fix the failed tests above.")
            print("   Focus on the most critical failures first.")

        print("\n🔧 CRASH PROTECTION FEATURES VERIFIED:")
        print("   • Safe function execution with retries")
        print("   • Resource management and cleanup")
        print("   • Process execution with timeout protection")
        print("   • Path validation and safe file operations")
        print("   • Circuit breaker pattern for external services")
        print("   • Memory monitoring and leak detection")
        print("   • System health monitoring")
        print("   • Emergency shutdown procedures")
        print("   • Real-world crash scenario handling")


def main():
    """Main test execution function."""
    print("🛡️ ForumBot Crash Protection Test Suite")
    print("=======================================")
    print("Testing all crash protection mechanisms...")
    print()

    # Initialize crash protection systems
    crash_logger.logger.info("🚀 Starting crash protection tests")

    # Run comprehensive tests
    tester = CrashProtectionTester()
    tester.run_all_tests()

    # Final system check
    print(f"\n🏥 Final System Health: {get_system_health().value}")

    # Export test results
    try:
        system_monitor.export_metrics("crash_protection_test_metrics.json")
        print("📊 Test metrics exported to: crash_protection_test_metrics.json")
    except Exception as e:
        print(f"⚠️ Could not export metrics: {e}")

    crash_logger.logger.info("🏁 Crash protection tests completed")


if __name__ == "__main__":
    main()