import sys
import os
import logging

# Configure logging to see debug messages
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Add current directory to path to import local modules
sys.path.insert(0, os.path.abspath('.'))

from core.user_manager import get_user_manager

def test_site_login(site_name):
    print(f"\n--- Testing login for {site_name} ---")
    user_manager = get_user_manager()
    session = user_manager.get_session(site_name)
    if session:
        print(f"Successfully obtained session for {site_name}.")
        # You can add a simple test here to fetch a page to confirm the session is active
        try:
            if site_name == "dddownload":
                test_url = "https://ddownload.com/?op=my_reports&ajax=1"
            elif site_name == "katfile":
                test_url = "https://katfile.com/?op=my_reports&ajax=1"
            else:
                test_url = None

            if test_url:
                resp = session.get(test_url, timeout=10)
                if resp.status_code == 200 and 'login' not in resp.url.lower():
                    print(f"{site_name} session seems active. Status code: {resp.status_code}")
                    print(f"First 200 chars of response: {resp.text[:200]}")
                else:
                    print(f"{site_name} session might not be active. Status code: {resp.status_code}, Redirected to: {resp.url}")
            else:
                print("No test URL for this site.")
        except Exception as e:
            print(f"Error testing {site_name} session: {e}")
    else:
        print(f"Failed to obtain session for {site_name}.")

if __name__ == "__main__":
    # IMPORTANT: Replace with your actual credentials for testing
    # For security, do not hardcode credentials in production code.
    # Use environment variables or a secure configuration management system.
    user_manager_instance = get_user_manager()
    user_manager_instance.users["dddownload"]["username"] = "YOUR_DDDOWNLOAD_USERNAME"
    user_manager_instance.users["dddownload"]["password"] = "YOUR_DDDOWNLOAD_PASSWORD"
    user_manager_instance.users["katfile"]["username"] = "YOUR_KATFILE_USERNAME"
    user_manager_instance.users["katfile"]["password"] = "YOUR_KATFILE_PASSWORD"

    test_site_login("dddownload")
    test_site_login("katfile")