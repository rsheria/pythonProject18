import os
import re
import json
from pathlib import Path
from dotenv import load_dotenv, dotenv_values, find_dotenv, set_key

# ————————— Module-level: load .env first —————————

dotenv_path = Path(find_dotenv())
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)

# data folder for logs, json, pkl, …
DATA_DIR = os.getenv('DATA_DIR', 'data')
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
        if s.lower() in ('true', 'false'):
            return s.lower() == 'true'
        if ',' in s:
            return [item.strip() for item in s.split(',') if item.strip()]
        return s

    config = { key.lower(): _parse(val) for key, val in raw.items() }
    config.setdefault('data_dir', DATA_DIR)
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
            # simple CSV, no quotes
            val_str = ','.join(str(x) for x in val)
        else:
            val_str = str(val)

        # set or update the .env entry (uppercased key)
        set_key(str(env_file), key.upper(), val_str)
