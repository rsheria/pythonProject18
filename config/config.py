import os
import re
import json
from pathlib import Path
from dotenv import load_dotenv, dotenv_values, find_dotenv, set_key
from utils.paths import get_data_folder

# ————————— Module-level: load .env first —————————

_dotenv = find_dotenv()
dotenv_path = Path(_dotenv) if _dotenv else None
if dotenv_path and dotenv_path.is_file():
    load_dotenv(dotenv_path=dotenv_path)

# data folder for logs, json, pkl, …
DATA_DIR = os.getenv('DATA_DIR', get_data_folder())
os.makedirs(DATA_DIR, exist_ok=True)


def load_configuration(env_path: str = None) -> dict:
    """
    Read all variables from .env (or env_path if provided)
    Return a dict with:
      - all keys lowercased
      - values auto-converted to bool, list or str
      - 'data_dir' defaulting to DATA_DIR if missing
    """
    path = Path(env_path) if env_path else Path(find_dotenv())
    if not path.exists():
        raise FileNotFoundError(f".env file not found at {path}")

    raw = dotenv_values(str(path))

    def _parse(v: str):
        if v is None:
            return None
        s = v.strip()
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1]
        # Try to decode JSON structures first (dicts/lists)
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            pass
        if s.lower() in ('true', 'false'):
            return s.lower() == 'true'
        if ',' in s:
            return [item.strip() for item in s.split(',') if item.strip()]
        return s

    config = { key.lower(): _parse(val) for key, val in raw.items() }
    config.setdefault('data_dir', DATA_DIR)
    config.setdefault('single_host_mode', True)
    config.setdefault('auto_replace_container', True)
    return config


def save_configuration(config: dict, env_path: str = None) -> None:
    """
    Persist the given config dict back to the .env file.
    - Bools become 'true'/'false'
    - Lists/Tuples become comma‑separated values
    - Other types become str()
    """
    # 1) locate the .env file
    env_file = Path(env_path) if env_path else Path(find_dotenv())
    if not env_file.exists():
        raise FileNotFoundError(f".env file not found at {env_file}")

    # 2) ensure we have the latest contents loaded (so we don't clobber other keys)
    load_dotenv(env_file)

    # 3) write/update each key
    for key, val in config.items():
        # skip internal-only keys if you want (eg: 'data_dir')
        if key == 'data_dir':
            continue

        # format the value
        if isinstance(val, bool):
            val_str = 'true' if val else 'false'
        elif isinstance(val, (list, tuple)):
            # if the list contains non-primitive types, store as JSON
            if all(isinstance(x, (str, int, float, bool)) for x in val):
                val_str = ','.join(str(x) for x in val)
            else:
                val_str = json.dumps(val)
        elif isinstance(val, dict):
            val_str = json.dumps(val)
        else:
            val_str = str(val)

        # set or update the .env entry (uppercased key)
        set_key(str(env_file), key.upper(), val_str)
