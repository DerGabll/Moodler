"""Utility functions for Moodler application."""

import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

import ctypes

from config import APP_NAME

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

def get_appdata_path() -> Path:
    """Return path to application data directory."""
    appdata = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    config_dir = Path(appdata) / APP_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir

def get_config_path() -> Path:
    """Return path to config file."""
    return get_appdata_path() / "config.json"

def load_api_key() -> Optional[str]:
    """Load API key from config file."""
    config_file = get_config_path()
    if not config_file.exists():
        return None
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("api_key")
    except Exception as e:
        logging.error(f"Failed to read config file: {e}")
        return None

def save_api_key(api_key: str) -> bool:
    """Save API key to config file."""
    try:
        config_file = get_config_path()
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump({"api_key": api_key}, f)
        return True
    except Exception as e:
        logging.error(f"Failed to save API key: {e}")
        return False

def delete_api_key() -> bool:
    """Delete saved API key."""
    try:
        config_file = get_config_path()
        if config_file.exists():
            config_file.unlink()
        return True
    except Exception as e:
        logging.error(f"Failed to delete API key: {e}")
        return False

def is_valid_api_key(api_key: Optional[str]) -> bool:
    """Check if API key looks valid."""
    return bool(api_key and api_key.startswith("sk-") and len(api_key) >= 10)

def ensure_dpi_awareness():
    """Set process DPI awareness for better high-DPI behavior."""
    try:
        # Try Windows 8.1+ API first
        shcore = ctypes.windll.shcore
        PROCESS_PER_MONITOR_DPI_AWARE = 2
        shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
    except Exception:
        try:
            # Fallback to older API
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            logging.warning("Failed to set DPI awareness")

def get_screen_scale(hwnd: Optional[int] = None) -> float:
    """Get system DPI scale factor."""
    try:
        if hwnd:
            # Get DPI for specific window
            dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
            return dpi / 96.0
        else:
            # Get system DPI
            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            ctypes.windll.user32.ReleaseDC(0, hdc)
            return dpi / 96.0
    except Exception:
        return 1.0

def encode_image_to_base64(image_path: str) -> str:
    """Encode image file to base64 string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")