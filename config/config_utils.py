import os
from dotenv import find_dotenv, set_key

def update_env_variable(key: str, value: str, env_file: str = None) -> bool:
    """
    Sets or updates a key=value in the .env file.
    Returns True if successful, False otherwise.
    """
    env_path = env_file or find_dotenv()
    if not env_path:
        return False
    try:
        set_key(env_path, key, value)
        return True
    except Exception:
        return False

def get_env_variable(key: str, default=None):
    """Safely get an environment variable."""
    return os.getenv(key, default)
