# paths.py
import os
from pathlib import Path

def get_data_folder() -> str:
    # مشروعك structure: project_root/
    project_root = Path(__file__).parent.parent
    data_dir = project_root / "data"
    os.makedirs(data_dir, exist_ok=True)
    return str(data_dir)
