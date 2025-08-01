import os
from pathlib import Path


def _strip_quotes(value: str) -> str:
    """Remove surrounding single or double quotes from value."""
    if not isinstance(value, str):
        return value
    v = value.strip()
    if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
        return v[1:-1]
    return v

def load_dotenv(dotenv_path=None):
    """Simplistic dotenv loader used for tests."""
    path_str = dotenv_path or find_dotenv()
    if not path_str:
        return
    path = Path(path_str)
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = line.split('=', 1)
            os.environ.setdefault(key, _strip_quotes(val))


def dotenv_values(path):
    """Return key=value mapping from the dotenv file."""
    path = Path(path)
    if not path.exists():
        return {}
    data = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = line.split('=', 1)
            data[key] = _strip_quotes(val)
    return data


def find_dotenv():
    """Locate .env in current directory or parents."""
    for directory in [Path.cwd(), *Path.cwd().parents]:
        candidate = directory / '.env'
        if candidate.exists():
            return str(candidate)
    return ''


def set_key(env_file, key, value):
    """Set or update a key=value pair in env_file."""
    path = Path(env_file)
    lines = []
    if path.exists():
        with open(path) as f:
            for line in f:
                if line.startswith(f'{key}='):
                    lines.append(f'{key}={value}\n')
                else:
                    lines.append(line)
    else:
        lines.append(f'{key}={value}\n')
    if not any(l.startswith(f'{key}=') for l in lines):
        lines.append(f'{key}={value}\n')
    with open(path, 'w') as f:
        f.writelines(lines)
    return True