#!/usr/bin/env python3
"""
Screenshot -> OpenAI helper (refactored & cleaned)
Features:
 - Mouse-controlled UI with small, unobtrusive buttons
 - DPI-aware invisible selection window (Tkinter)
 - Saves API key to config directory (cross-platform)
 - Sends screenshot to OpenAI Chat Completions API with vision support
"""

from app import MoodlerApp
import base64
import concurrent.futures
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Optional, Tuple

try:
    import pyperclip
except ImportError:
    pyperclip = None
    print("WARNING: pyperclip not available. Clipboard functionality will be disabled.", flush=True)

import getpass
import tkinter as tk
from tkinter import messagebox, simpledialog

from PIL import ImageGrab

# Windows-only imports (wrapped in try/except so module can import on other platforms, but script expects Windows)
try:
    import ctypes
    import win32api
    import win32con
    import win32gui
except Exception:
    ctypes = None
    win32api = None
    win32con = None
    win32gui = None

# OpenAI client; expects `openai` package or OpenAI Python client that exposes OpenAI
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # will raise later if missing

# -----------------------
# Configuration / Constants
# -----------------------
APP_NAME = "Moodler"
PROMPT_MULTIPLE_CHOICE = (
    "Welche Antwortmöglichkeiten, glaubst du, sind richtig? "
    "Die Antwortmöglichkeiten sind mit Buchstaben geordnet. Schreibe in deiner Antwort "
    "nur Buchstaben mit einem Leerzeichen getrennt und nur Buchstaben, die die richtige Lösung beinhalten. "
    "Die Antwort sollte gut durchgedacht sein."
)
PROMPT_TRUE_FALSE = (
    "Ist diese Aussage richtig oder falsch? Antworte nur mit 'true' oder 'false'. "
    "Keine weiteren Erklärungen, nur das Wort 'true' oder 'false'."
)
PROMPT_OPEN_ENDED = (
    "Beantworte diese Frage klar, kurz und auf Deutsch. "
    "Die Antwort sollte präzise und verständlich sein. "
    "Keine langen Erklärungen, nur die direkte Antwort."
)
QUESTION_TYPE_DETECTION_PROMPT = (
    "Analysiere dieses Bild und bestimme den Fragetyp. "
    "Antworte NUR mit einem der folgenden Wörter: 'multiple_choice', 'true_false', 'open_ended', 'no_question', oder 'incomplete_question'. "
    "Keine weiteren Erklärungen.\n\n"
    "Kriterien:\n"
    "- 'multiple_choice': Es gibt mehrere Antwortmöglichkeiten mit Buchstaben (a, b, c, d, etc.) UND die Frage ist vollständig sichtbar\n"
    "- 'true_false': Es ist eine Ja/Nein oder Richtig/Falsch Frage UND die Frage ist vollständig sichtbar\n"
    "- 'open_ended': Es ist eine offene Frage ohne vorgegebene Antwortmöglichkeiten UND die Frage ist vollständig sichtbar\n"
    "- 'no_question': Es ist keine Frage im Bild sichtbar oder das Bild enthält keine Frage\n"
    "- 'incomplete_question': Die Frage ist abgeschnitten, unvollständig oder nicht vollständig lesbar"
)
MODEL_NAME = "gpt-5.2"
AVAILABLE_MODELS = ["gpt-5.2", "gpt-4.1", "gpt-4o", "gpt-4.1-mini", "gpt-4o-mini"]
TEMP_SCREENSHOT_NAME = "moodler_screenshot.png"
# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# -----------------------
# Utilities
# -----------------------
def appdata_config_path() -> Path:
    """Return path to config file (Windows-only)."""
    appdata = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    config_dir = Path(appdata) / APP_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


def load_config() -> dict:
    """Load configuration from file."""
    cfg = appdata_config_path()
    if not cfg.exists():
        return {}
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        return data
    except Exception as ex:
        logging.exception("Failed to read config file")
        print(f"ERROR: Failed to read config file: {ex}", flush=True)
        return {}


def save_config(config: dict) -> bool:
    """Save configuration to file."""
    cfg = appdata_config_path()
    try:
        cfg.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return True
    except Exception as ex:
        logging.exception("Failed to save config")
        print(f"ERROR: Failed to save config: {ex}", flush=True)
        return False


def load_api_key() -> Optional[str]:
    """Load API key from config file."""
    data = load_config()
    return data.get("api_key")


def save_api_key(api_key: str) -> bool:
    """Save API key to config file."""
    data = load_config()
    data["api_key"] = api_key
    return save_config(data)


def load_model_name() -> str:
    """Load model name from config file, or return default."""
    data = load_config()
    model = data.get("model_name", MODEL_NAME)
    # Validate that the model is in the available list
    if model not in AVAILABLE_MODELS:
        return MODEL_NAME
    return model


def save_model_name(model_name: str) -> bool:
    """Save model name to config file."""
    if model_name not in AVAILABLE_MODELS:
        return False
    data = load_config()
    data["model_name"] = model_name
    return save_config(data)


def delete_saved_api_key() -> bool:
    cfg = appdata_config_path()
    try:
        if cfg.exists():
            cfg.unlink()
        return True
    except Exception as ex:
        logging.exception("Failed to delete config file")
        print(f"ERROR: Failed to delete config file: {ex}", flush=True)
        return False


def looks_like_api_key(k: Optional[str]) -> bool:
    return bool(k and k.startswith("sk-") and len(k) >= 10)


# -----------------------
# DPI / Process Awareness
# -----------------------
def ensure_process_dpi_awareness() -> None:
    """Try to set process DPI awareness for better high-DPI behavior on Windows."""
    if ctypes is None:
        return
    try:
        # Windows 8.1+ API
        try:
            shcore = ctypes.windll.shcore
            PROCESS_PER_MONITOR_DPI_AWARE = 2
            shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
            logging.debug("SetProcessDpiAwareness called")
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                logging.debug("SetProcessDPIAware fallback called")
            except Exception:
                pass

        # newer API
        try:
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
            ctypes.windll.user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            logging.debug("SetProcessDpiAwarenessContext called")
        except Exception:
            pass
    except Exception as ex:
        logging.exception("Failed to set process DPI awareness")
        print(f"ERROR: Failed to set process DPI awareness: {ex}", flush=True)


def get_system_scale_factor(hwnd: Optional[int] = None) -> float:
    """Return DPI scale factor (1.0 = 100%, 1.25 = 125%, etc)."""
    # On Windows, this would need proper DPI detection
    return 1.0


# -----------------------
# UI / Selection
# -----------------------
class InvisibleScreenshotSelector:
    """A nearly-invisible fullscreen Tk window that lets the user click-drag to select an area."""

    def __init__(self, master: tk.Tk, on_complete):
        """
        on_complete: callback(final_coords: Tuple[int,int,int,int]) where coords are physical pixels
        """
        self._master = master
        self._on_complete = on_complete
        # Create a fullscreen top-level window that is nearly invisible
        self._win = tk.Toplevel(master)
        # Hide from taskbar immediately before showing
        self._win.withdraw()
        self._win.attributes("-fullscreen", True)
        # Use black background
        self._win.configure(bg="black")
        self._win.attributes("-topmost", True)
        # Use very low alpha so it's barely visible but still interactive (not 0 to allow clicks)
        self._win.attributes("-alpha", 0.01)
        # Remove window decorations to help hide from taskbar
        self._win.overrideredirect(True)
        self._win.update_idletasks()
        
        # Hide from taskbar immediately after window creation
        self._hide_from_taskbar()
        
        # Show the window after hiding from taskbar
        self._win.deiconify()
        # Focus the window so it can receive keyboard events
        self._win.focus_force()

        # Determine DPI scale for this window
        self._hwnd = None
        try:
            self._hwnd = self._win.winfo_id()
        except Exception:
            pass
        self.scale_factor = get_system_scale_factor(self._hwnd)

        # Canvas to catch mouse events
        self._canvas = tk.Canvas(self._win, highlightthickness=0, bg="black")
        self._canvas.pack(fill="both", expand=True)
        # Make sure canvas can receive focus for keyboard events
        self._canvas.focus_set()

        self._start = None
        self._final_coords = None

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        # Bind escape key to both window and canvas
        self._win.bind("<Escape>", self._cancel)
        self._canvas.bind("<Escape>", self._cancel)
        self._win.bind("<KeyPress-Escape>", self._cancel)

        # Update to ensure window is fully created, then hide from taskbar again (redundant but ensures it sticks)
        self._win.update_idletasks()
        # Hide from taskbar again after window is fully shown
        self._master.after(10, self._hide_from_taskbar)

        # make sure selector stays on top
        self._keep_on_top()

    def _on_press(self, event):
        self._start = (event.x_root, event.y_root)

    def _on_drag(self, event):
        # optional: draw rectangle preview (omitted intentionally to keep near-invisible)
        pass

    def _on_release(self, event):
        if not self._start:
            self._cancel()
            return
        x1, y1 = self._start
        x2, y2 = event.x_root, event.y_root

        # enforce minimum size
        if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
            self._cancel()
            return

        # convert logical (DIP) coordinates to physical pixels
        x1p = int(round(min(x1, x2) * self.scale_factor))
        y1p = int(round(min(y1, y2) * self.scale_factor))
        x2p = int(round(max(x1, x2) * self.scale_factor))
        y2p = int(round(max(y1, y2) * self.scale_factor))

        self._final_coords = (x1p, y1p, x2p, y2p)
        self._win.withdraw()
        # give a small delay so the window is not in the screenshot
        self._master.after(150, lambda: self._complete())

    def _complete(self):
        if self._final_coords:
            self._on_complete(self._final_coords)
        self._destroy()

    def _cancel(self, event=None):
        self._final_coords = None
        # Call the callback with None to properly reset state
        self._on_complete(None)
        self._destroy()

    def _destroy(self):
        try:
            self._win.destroy()
        except Exception:
            pass

    def _hide_from_taskbar(self):
        """Hide the selector window from the taskbar."""
        if win32gui and win32con:
            try:
                # Get hwnd again in case it wasn't available earlier
                hwnd = self._win.winfo_id()
                if not hwnd:
                    return
                
                # Get current extended window style
                exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                
                # Remove WS_EX_APPWINDOW if present (forces taskbar entry)
                exstyle &= ~win32con.WS_EX_APPWINDOW
                
                # Add WS_EX_TOOLWINDOW to hide from taskbar
                # This makes Windows treat it as a tool window, which doesn't appear in taskbar
                exstyle |= win32con.WS_EX_TOOLWINDOW
                
                # Apply the new extended style
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, exstyle)
                
                # Force window update to apply changes
                win32gui.SetWindowPos(
                    hwnd,
                    win32con.HWND_TOP,
                    0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED
                )
            except Exception as ex:
                logging.exception("Failed to hide selector from taskbar")
                print(f"ERROR: Failed to hide selector from taskbar: {ex}", flush=True)

    def _keep_on_top(self):
        try:
            if not self._win.winfo_exists():
                return
            # Windows-specific: use win32 to bring to top
            if win32gui and win32con:
                hwnd = self._win.winfo_id()
                try:
                    win32gui.BringWindowToTop(hwnd)
                    win32gui.SetWindowPos(
                        hwnd,
                        win32con.HWND_TOPMOST,
                        0,
                        0,
                        0,
                        0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
                    )
                except Exception:
                    pass
            self._win.after(50, self._keep_on_top)
        except Exception:
            pass


# -----------------------
# Main application UI + logic
# -----------------------
class ScreenshotApp:
    def __init__(self):
        ensure_process_dpi_awareness()
        self.temp_path = Path(os.getenv("TEMP", str(Path.home() / "AppData" / "Local" / "Temp"))) / TEMP_SCREENSHOT_NAME
        self.username = getpass.getuser()
        self.state = {
            "screenshot_path": None,
            "screenshot_loaded": False,
            "response_text": None,
            "response_shown": False,
            "sending": False,
            "selecting_area": False,
            "multiplier": 1,  # 1x, 2x, 3x, or 4x
        }
        # Load saved model name
        self.model_name = load_model_name()
        print(f"DEBUG: Loaded model on startup: {self.model_name}", flush=True)
        # Tk root
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        # Use a unique color for transparency (will be made transparent)
        self.transparent_color = "#010101"  # Almost black, unique for transparency
        self.root.configure(bg=self.transparent_color)
        # small toolbar in top-left - minimal size (2 rows: status + buttons)
        self.root.geometry("200x50+5+5")
        self.hw = self.root.winfo_id()

        # Create a frame for buttons with transparent background
        self._button_frame = tk.Frame(self.root, bg=self.transparent_color, height=50)
        self._button_frame.pack(fill="x", expand=False, padx=1, pady=1)
        self._button_frame.pack_propagate(False)  # Prevent frame from resizing based on content
        
        # Use grid layout - status in row 0, buttons in row 1
        self._button_frame.columnconfigure(0, weight=1)  # Text area expands
        self._button_frame.rowconfigure(0, weight=0, minsize=25)  # Status row
        self._button_frame.rowconfigure(1, weight=0, minsize=25)  # Buttons row

        # Status label (very small, dark, transparent background) - in row 0
        self._status_label = tk.Label(
            self._button_frame,
            text="Ready",
            fg="#2a2a2a",  # Dark gray, visible on transparent
            bg=self.transparent_color,
            font=("Arial", 7),
            anchor="w",
            justify="left",
            height=1,  # Fixed height - single line
        )
        self._status_label.grid(row=0, column=0, sticky="ew", padx=2)

        # Buttons frame - in row 1, left-aligned
        buttons_container = tk.Frame(self._button_frame, bg=self.transparent_color)
        buttons_container.grid(row=1, column=0, sticky="w", padx=1)
        # Store reference for later use
        self._buttons_container = buttons_container

        # Buttons - very small and dark, with semi-transparent backgrounds
        button_style = {
            "bg": "#2a2a2a",  # Dark gray, visible on transparent
            "fg": "#4a4a4a",  # Lighter gray for text/symbols
            "activebackground": "#3a3a3a",
            "activeforeground": "#5a5a5a",
            "relief": "flat",
            "borderwidth": 0,
            "font": ("Arial", 6),
            "padx": 3,
            "pady": 1,
        }

        # Multiplier button - cycles through 1x, 2x, 3x, 4x
        self._btn_multiplier = tk.Button(
            buttons_container,
            text="1x",
            command=self._cycle_multiplier,
            **button_style,
        )
        self._btn_multiplier.pack(side="left", padx=1)

        self._btn_screenshot = tk.Button(
            buttons_container,
            text="📷",
            command=self.start_area_selection,
            **button_style,
        )
        self._btn_screenshot.pack(side="left", padx=1)

        self._btn_send = tk.Button(
            buttons_container,
            text="➤",
            command=self.send_current_screenshot,
            **button_style,
        )
        self._btn_send.pack(side="left", padx=1)

        self._btn_settings = tk.Button(
            buttons_container,
            text="⚙",
            command=self.open_settings,
            **button_style,
        )
        self._btn_settings.pack(side="left", padx=1)

        self._btn_reset = tk.Button(
            buttons_container,
            text="↻",
            command=self.reset_api_key,
            **button_style,
        )
        self._btn_reset.pack(side="left", padx=1)

        self._btn_quit = tk.Button(
            buttons_container,
            text="✕",
            command=self._cleanup_and_quit,
            **button_style,
        )
        self._btn_quit.pack(side="left", padx=1)

        self.root.update_idletasks()

        # Apply transparency
        self._apply_transparency()

        # Try to make the toolbar non-activating / click-through where possible
        self._apply_window_exstyle()

        # OpenAI client will be created after providing API key
        self.client = None

        # Initial status
        self._update_status("Ready")

    # ---------- Window helpers ----------
    def _apply_transparency(self):
        """Apply transparency to the window background."""
        if win32gui and win32con and win32api:
            # Windows: use color key transparency
            try:
                exstyle = win32gui.GetWindowLong(self.hw, win32con.GWL_EXSTYLE)
                exstyle |= win32con.WS_EX_LAYERED
                win32gui.SetWindowLong(self.hw, win32con.GWL_EXSTYLE, exstyle)
                # Make the transparent color transparent
                color_key = win32api.RGB(1, 1, 1)  # #010101
                win32gui.SetLayeredWindowAttributes(self.hw, color_key, 0, win32con.LWA_COLORKEY)
            except Exception as ex:
                logging.exception("Failed to apply transparency on Windows")
                print(f"ERROR: Failed to apply transparency on Windows: {ex}", flush=True)

    def _apply_window_exstyle(self):
        """Set extended window styles for the toolbar with transparent background (but clickable)."""
        # Windows-specific window styling
        if win32gui and win32con and win32api:
            try:
                exstyle = win32gui.GetWindowLong(self.hw, win32con.GWL_EXSTYLE)
                # Use WS_EX_LAYERED for transparency, but NOT WS_EX_TRANSPARENT (which makes clicks pass through)
                # Use WS_EX_TOOLWINDOW to prevent taskbar entry
                exstyle |= win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW
                # custom NOACTIVATE constant: 0x08000000
                exstyle |= 0x08000000
                win32gui.SetWindowLong(self.hw, win32con.GWL_EXSTYLE, exstyle)
                # Use the same color key as in _apply_transparency
                color_key = win32api.RGB(1, 1, 1)  # #010101
                win32gui.SetLayeredWindowAttributes(self.hw, color_key, 0, win32con.LWA_COLORKEY)
            except Exception as ex:
                logging.exception("Failed to set extended window styles for toolbar")
                print(f"ERROR: Failed to set extended window styles for toolbar: {ex}", flush=True)
        # Ensure it stays topmost occasionally
        self.root.after(2000, self._keep_always_on_top)

    def _keep_always_on_top(self):
        try:
            if win32gui and win32con:
                win32gui.SetWindowPos(
                    self.hw,
                    win32con.HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                )
        except Exception:
            pass
        self.root.after(2000, self._keep_always_on_top)

    def _update_status(self, text: str, is_response: bool = False):
        """Update the status label text."""
        print(f"DEBUG: _update_status called with text='{text}', is_response={is_response}", flush=True)
        def do_update():
            print(f"DEBUG: do_update executing, is_response={is_response}, text='{text}', text bool: {bool(text)}", flush=True)
            if is_response and text:
                # Calculate width needed (no need to account for buttons, they're on separate line)
                text_width = min(max(len(text) * 6 + 20, 200), 600)  # Min 200px, max 600px
                # Don't use wraplength - keep text on single line to prevent vertical expansion
                # Update label with text and font BEFORE changing geometry
                self._status_label.config(
                    text=text, 
                    font=("Arial", 10), 
                    fg="#2a2a2a",
                    wraplength=0,  # No wrapping - single line only
                    anchor="w",
                    justify="left",
                    height=1  # Fixed height - single line
                )
                # Force label update
                self._status_label.update_idletasks()
                # Then expand window to fit more text (buttons are on separate line, so no constraint)
                # Height is 50px for two rows (status + buttons)
                self.root.geometry(f"{text_width}x50+5+5")
                # Ensure the button frame doesn't expand vertically
                self._button_frame.config(height=50)
                # Force window update to ensure text is visible and buttons stay in place
                self.root.update_idletasks()
            else:
                # Normal status with smaller font - no truncation needed since buttons are on separate line
                self._status_label.config(
                    text=text if text else "Ready", 
                    font=("Arial", 7), 
                    fg="#2a2a2a",
                    wraplength=0,  # No wrapping for short text
                    anchor="w"
                )
                # Reset to default size (50px height for two rows)
                self.root.geometry("200x50+5+5")
                self.root.update_idletasks()
            # Update button states - allow screenshot button even after response is shown
            self._btn_send.config(state="normal" if self.state["screenshot_loaded"] and not self.state["sending"] else "disabled")
            self._btn_screenshot.config(state="normal" if not self.state["selecting_area"] and not self.state["sending"] else "disabled")
        self.root.after(0, do_update)

    # ---------- API key handling ----------
    def ensure_client(self) -> bool:
        """Ensure we have a valid OpenAI client. Shows dialogs when needed."""
        api_key = load_api_key()
        if not looks_like_api_key(api_key):
            # prompt user for key via a simple hidden Tk root
            tmp = tk.Tk()
            tmp.withdraw()
            while True:
                api_key = simpledialog.askstring(
                    "OpenAI API Key Required",
                    "Enter your OpenAI API key (starts with sk-...):",
                    show="*",
                    parent=tmp,
                )
                if api_key is None:
                    messagebox.showerror("Error", "API key is required to use this application.", parent=tmp)
                    tmp.destroy()
                    return False
                if looks_like_api_key(api_key):
                    if not save_api_key(api_key):
                        messagebox.showwarning("Warning", "Failed to save API key locally.", parent=tmp)
                    break
                else:
                    messagebox.showerror("Invalid API Key", "API key must start with 'sk-' and be valid. Please try again.", parent=tmp)
            tmp.destroy()

        # create client
        if OpenAI is None:
            messagebox.showerror("Missing dependency", "OpenAI Python client not available. Install `openai` or the official client.", parent=self.root)
            return False
        try:
            self.client = OpenAI(api_key=api_key)
            return True
        except Exception as ex:
            logging.exception("Failed to create OpenAI client")
            print(f"ERROR: Failed to create OpenAI client: {ex}", flush=True)
            messagebox.showerror("OpenAI Error", "Failed to create OpenAI client. Check API key.", parent=self.root)
            return False

    def reset_api_key(self):
        """Reset (delete) saved API key and exit so user can restart."""
        if self.state["sending"] or self.state["selecting_area"]:
            return
        tmp = tk.Tk()
        tmp.withdraw()
        if messagebox.askyesno("Reset API Key", "Do you want to reset the saved API key? The application will close and you'll need to restart it.", parent=tmp):
            if delete_saved_api_key():
                messagebox.showinfo("Success", "API key reset. The application will now close.", parent=tmp)
                tmp.destroy()
                self._cleanup_and_quit()
            else:
                messagebox.showerror("Error", "Failed to reset API key.", parent=tmp)
                tmp.destroy()
        else:
            tmp.destroy()

    def open_settings(self):
        """Open settings dialog."""
        if self.state["sending"] or self.state["selecting_area"]:
            return
        
        # Create settings window
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Settings")
        settings_window.geometry("300x150")
        settings_window.attributes("-topmost", True)
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        # Center the window
        settings_window.update_idletasks()
        x = (settings_window.winfo_screenwidth() // 2) - (settings_window.winfo_width() // 2)
        y = (settings_window.winfo_screenheight() // 2) - (settings_window.winfo_height() // 2)
        settings_window.geometry(f"+{x}+{y}")
        
        # Model selection
        tk.Label(settings_window, text="GPT Model:", font=("Arial", 9)).pack(pady=10)
        
        model_var = tk.StringVar(value=self.model_name)
        model_dropdown = tk.OptionMenu(settings_window, model_var, *AVAILABLE_MODELS)
        model_dropdown.pack(pady=5)
        model_dropdown.config(width=20)
        
        # Buttons
        button_frame = tk.Frame(settings_window)
        button_frame.pack(pady=20)
        
        def save_settings():
            new_model = model_var.get()
            if new_model != self.model_name:
                if save_model_name(new_model):
                    self.model_name = new_model
                    print(f"DEBUG: Model changed to: {self.model_name}", flush=True)
                    messagebox.showinfo("Settings", f"Model changed to {new_model}.", parent=settings_window)
                else:
                    messagebox.showerror("Error", "Failed to save model setting.", parent=settings_window)
            else:
                print(f"DEBUG: Model unchanged: {self.model_name}", flush=True)
            settings_window.destroy()
        
        tk.Button(button_frame, text="Save", command=save_settings, width=10).pack(side="left", padx=5)
        tk.Button(button_frame, text="Cancel", command=settings_window.destroy, width=10).pack(side="left", padx=5)

    # ---------- Multiplier handling ----------
    def _cycle_multiplier(self):
        """Cycle through multiplier options: 1x -> 2x -> 3x -> 4x -> 1x"""
        self.state["multiplier"] = (self.state["multiplier"] % 4) + 1
        self._btn_multiplier.config(text=f"{self.state['multiplier']}x")
        print(f"DEBUG: Multiplier changed to {self.state['multiplier']}x", flush=True)

    # ---------- Screenshot flow ----------
    def start_area_selection(self):
        if self.state["selecting_area"] or self.state["sending"]:
            return
        # Reset state if we have a result shown (allows new screenshot after getting answer)
        if self.state["response_shown"]:
            self._reset_state()
        self.state["selecting_area"] = True
        self._update_status("Select area...")
        # create the selector after a short delay so UI updates
        self.root.after(50, lambda: InvisibleScreenshotSelector(self.root, self._on_selection_complete))

    def _on_selection_complete(self, final_coords: Optional[Tuple[int, int, int, int]]):
        self.state["selecting_area"] = False
        if not final_coords:
            self._update_status("Ready")
            return
        x1, y1, x2, y2 = final_coords
        # ensure clamping to screen size (best-effort)
        try:
            if win32api:
                sw_logical = win32api.GetSystemMetrics(0)
                sh_logical = win32api.GetSystemMetrics(1)
                scale = get_system_scale_factor()
                screen_w = int(round(sw_logical * scale))
                screen_h = int(round(sh_logical * scale))
            else:
                screen_w = self.root.winfo_screenwidth()
                screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = x2 + 10, y2 + 10

        # clamp coords
        x1 = max(0, min(x1, screen_w - 1))
        y1 = max(0, min(y1, screen_h - 1))
        x2 = max(0, min(x2, screen_w))
        y2 = max(0, min(y2, screen_h))
        if x2 <= x1:
            x2 = x1 + 10
        if y2 <= y1:
            y2 = y1 + 10

        # Take the screenshot (Pillow)
        try:
            im = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            im.save(self.temp_path)
            self.state["screenshot_path"] = str(self.temp_path)
            self.state["screenshot_loaded"] = True
            width, height = abs(x2 - x1), abs(y2 - y1)
            self._update_status(f"Ready ({width}x{height})")
        except Exception as ex:
            logging.exception("Screenshot failed")
            print(f"ERROR: Screenshot failed: {ex}", flush=True)
            self.state["screenshot_loaded"] = False
            self._update_status(f"Error: {str(ex)[:20]}")

    # ---------- OpenAI sending ----------
    def send_current_screenshot(self):
        if self.state["sending"] or self.state["selecting_area"]:
            return
        if not self.state["screenshot_loaded"] or not self.state.get("screenshot_path"):
            self._update_status("No screenshot")
            return

        if not self.ensure_client():
            return

        # run the request in a background thread
        thread = threading.Thread(target=self._send_to_openai_thread, daemon=True)
        thread.start()

    def _detect_question_type(self, b64: str) -> str:
        """Detect the type of question: multiple_choice, true_false, or open_ended."""
        try:
            print(f"DEBUG: Detecting question type using model: {self.model_name}", flush=True)
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": QUESTION_TYPE_DETECTION_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64}"},
                            },
                        ],
                    }
                ],
            )
            content = response.choices[0].message.content
            if content:
                detected_type = str(content).strip().lower()
                if detected_type in ["multiple_choice", "true_false", "open_ended", "no_question", "incomplete_question"]:
                    print(f"DEBUG: Detected question type: {detected_type}", flush=True)
                    return detected_type
            # Default to multiple_choice if detection fails
            print("DEBUG: Question type detection failed, defaulting to multiple_choice", flush=True)
            return "multiple_choice"
        except Exception as ex:
            print(f"DEBUG: Question type detection error: {ex}, defaulting to multiple_choice", flush=True)
            return "multiple_choice"

    def _is_valid_answer(self, text: str, question_type: str) -> bool:
        """Check if the response is a valid answer format based on question type."""
        if not text:
            return False
        text_stripped = text.strip()
        text_lower = text_stripped.lower()
        
        if question_type == "multiple_choice":
            # Check if it's just letters (a-z) and spaces, max 30 chars
            if len(text_stripped) > 30:
                return False
            pattern = r'^[a-zA-Z](?:\s+[a-zA-Z])*$'
            return bool(re.match(pattern, text_stripped))
        elif question_type == "true_false":
            # Must be exactly "true" or "false" (case-insensitive)
            return text_lower in ["true", "false"]
        elif question_type == "open_ended":
            # Open-ended answers can be longer, but should be reasonable (max 500 chars)
            return len(text_stripped) <= 500 and len(text_stripped) > 0
        return False

    def _send_single_request(self, b64: str, question_type: str) -> Optional[str]:
        """Send a single request to OpenAI and return the response text."""
        try:
            # Select appropriate prompt based on question type
            if question_type == "multiple_choice":
                prompt = PROMPT_MULTIPLE_CHOICE
            elif question_type == "true_false":
                prompt = PROMPT_TRUE_FALSE
            elif question_type == "open_ended":
                prompt = PROMPT_OPEN_ENDED
            else:
                prompt = PROMPT_MULTIPLE_CHOICE  # Default fallback
            
            print(f"DEBUG: Sending single request using model: {self.model_name} (question_type: {question_type})", flush=True)
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64}"},
                            },
                        ],
                    }
                ],
            )
            content = response.choices[0].message.content
            if content is None:
                return None
            text = str(content).strip()
            # Validate that it's a valid answer format
            if not self._is_valid_answer(text, question_type):
                print(f"DEBUG: Response is not a valid answer format for {question_type}: {repr(text)}", flush=True)
                return "no answer"
            # Normalize true/false to lowercase for consistency
            if question_type == "true_false":
                text = text.lower()
            return text
        except Exception as ex:
            print(f"DEBUG: Single request failed: {ex}", flush=True)
            return None

    def _compare_answers(self, answers: list[str], question_type: str) -> str:
        """Use LLM to compare multiple answers and determine the correct one."""
        if not answers:
            return "No answers to compare"
        
        # If all answers are the same, return that answer
        if len(set([a.lower() for a in answers])) == 1:
            return answers[0]
        
        if question_type == "open_ended":
            # For open-ended, combine the best parts or give the most comprehensive answer
            comparison_prompt = (
                "Ich habe mehrere Antworten auf dieselbe Frage. Analysiere sie und erstelle eine "
                "klare, kurze und präzise Antwort auf Deutsch, die die besten Teile aller Antworten kombiniert "
                "oder die beste Antwort auswählt.\n\n"
                "Antworten:\n"
            )
            for i, answer in enumerate(answers, 1):
                comparison_prompt += f"{i}. {answer}\n"
            comparison_prompt += (
                "\nGib eine klare, kurze Antwort auf Deutsch, die die Frage am besten beantwortet."
            )
        else:
            # For multiple choice or true/false
            comparison_prompt = (
                "I have multiple answers to the same question. Please analyze them and determine which answer(s) are correct.\n\n"
                "Answers:\n"
            )
            for i, answer in enumerate(answers, 1):
                comparison_prompt += f"{i}. {answer}\n"
            if question_type == "true_false":
                comparison_prompt += "\nPlease answer with only 'true' or 'false'."
            else:
                comparison_prompt += (
                    "\nPlease provide the correct answer(s). If multiple answers are correct, "
                    "provide all of them. Format your response the same way as the original answers."
                )
        
        try:
            print(f"DEBUG: Comparing answers using model: {self.model_name}", flush=True)
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "user",
                        "content": comparison_prompt,
                    }
                ],
            )
            content = response.choices[0].message.content
            if content is None:
                return answers[0]  # Fallback to first answer
            result = str(content).strip()
            # Validate the result
            if self._is_valid_answer(result, question_type):
                return result
            else:
                # If validation fails, return the most common answer or first answer
                return answers[0]
        except Exception as ex:
            print(f"DEBUG: Comparison request failed: {ex}", flush=True)
            return answers[0]  # Fallback to first answer

    def _send_to_openai_thread(self):
        print("DEBUG: _send_to_openai_thread started", flush=True)
        print(f"DEBUG: Using model: {self.model_name}", flush=True)
        self.state["sending"] = True
        multiplier = self.state["multiplier"]
        self._update_status(f"Processing ({multiplier}x)...")
        try:
            print(f"DEBUG: Opening screenshot: {self.state['screenshot_path']}", flush=True)
            with open(self.state["screenshot_path"], "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            print(f"DEBUG: Image encoded, length: {len(b64)}", flush=True)
            print(f"DEBUG: Multiplier: {multiplier}x", flush=True)
            
            # First, detect the question type
            self._update_status("Detecting question type...")
            question_type = self._detect_question_type(b64)
            print(f"DEBUG: Question type detected: {question_type}", flush=True)
            
            # Handle no_question and incomplete_question cases
            if question_type == "no_question":
                result_text = "no question"
                self.state["response_text"] = result_text
                self.state["response_shown"] = True
                self._update_status(result_text, is_response=True)
                return
            elif question_type == "incomplete_question":
                result_text = "no answer"
                self.state["response_text"] = result_text
                self.state["response_shown"] = True
                self._update_status(result_text, is_response=True)
                return
            
            if multiplier == 1:
                # Single request - normal behavior
                result_text = self._send_single_request(b64, question_type)
                if result_text is None:
                    result_text = "no answer"
                    print("DEBUG: Single request returned None", flush=True)
                else:
                    print(f"DEBUG: Single request result: {repr(result_text)}", flush=True)
            else:
                # Multiple requests - send in parallel
                print(f"DEBUG: Sending {multiplier} parallel requests", flush=True)
                answers = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=multiplier) as executor:
                    futures = [executor.submit(self._send_single_request, b64, question_type) for _ in range(multiplier)]
                    for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
                        answer = future.result()
                        if answer:
                            answers.append(answer)
                            print(f"DEBUG: Request {i}/{multiplier} completed: {repr(answer)}", flush=True)
                        else:
                            print(f"DEBUG: Request {i}/{multiplier} returned None", flush=True)
                
                print(f"DEBUG: Received {len(answers)} answers: {answers}", flush=True)
                
                # Filter out "no answer" responses
                valid_answers = [a for a in answers if a != "no answer"]
                
                if not valid_answers:
                    result_text = "no answer"
                elif len(valid_answers) == 1:
                    result_text = valid_answers[0]
                else:
                    # Check if all answers are the same (case-insensitive for true/false)
                    if question_type == "true_false":
                        unique_answers = set([a.lower() for a in valid_answers])
                    else:
                        unique_answers = set(valid_answers)
                    
                    if len(unique_answers) == 1:
                        # All answers are the same, just use that answer
                        result_text = valid_answers[0]
                        print(f"DEBUG: All answers are the same: {repr(result_text)}", flush=True)
                    else:
                        # Answers differ, send to comparison LLM
                        print(f"DEBUG: Answers differ ({unique_answers}), sending to comparison LLM", flush=True)
                        result_text = self._compare_answers(valid_answers, question_type)
                        print(f"DEBUG: Comparison result: {repr(result_text)}", flush=True)
            
            # Handle open-ended questions specially
            if question_type == "open_ended" and result_text != "no answer":
                # Copy to clipboard
                if pyperclip:
                    try:
                        pyperclip.copy(result_text)
                        print(f"DEBUG: Answer copied to clipboard: {repr(result_text)}", flush=True)
                        display_text = "answer copied"
                    except Exception as ex:
                        print(f"DEBUG: Failed to copy to clipboard: {ex}", flush=True)
                        display_text = result_text
                else:
                    display_text = result_text
            else:
                display_text = result_text
            
            self.state["response_text"] = result_text
            self.state["response_shown"] = True
            print(f"DEBUG: Calling _update_status with text='{display_text}', is_response=True", flush=True)
            # Show result in status with larger font
            self._update_status(display_text, is_response=True)
            print("DEBUG: _update_status called", flush=True)
        except Exception as ex:
            logging.exception("OpenAI request failed")
            print(f"ERROR: OpenAI request failed: {ex}", flush=True)
            self.state["response_text"] = None
            self.state["response_shown"] = True
            error_msg = str(ex)[:25]
            self._update_status(f"Error: {error_msg}")
        finally:
            self.state["sending"] = False

    def _reset_state(self):
        """Reset UI state after showing result."""
        self.state.update(
            {
                "screenshot_path": None,
                "screenshot_loaded": False,
                "response_text": None,
                "response_shown": False,
                "sending": False,
            }
        )
        self._update_status("Ready")

    def _cleanup_and_quit(self):
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass
        # exit process
        os._exit(0)

    # ---------- Run ----------
    def run(self):
        self.root.mainloop()


# -----------------------
# Single instance check
# -----------------------
def check_single_instance():
    """Check if another instance is already running. Returns True if this is the only instance."""
    if ctypes is None:
        # If we can't use Windows API, skip the check (shouldn't happen on Windows)
        return True
    
    mutex_name = f"Global\\{APP_NAME}_SingleInstance"
    try:
        # Try to create a named mutex
        mutex = ctypes.windll.kernel32.CreateMutexW(
            None,  # Default security attributes
            True,  # Initial owner
            mutex_name
        )
        
        # Check if the mutex already existed (error code 183 = ERROR_ALREADY_EXISTS)
        last_error = ctypes.windll.kernel32.GetLastError()
        if last_error == 183:  # ERROR_ALREADY_EXISTS
            print(f"Another instance of {APP_NAME} is already running.", flush=True)
            return False
        
        return True
    except Exception as ex:
        print(f"WARNING: Could not create mutex for single instance check: {ex}", flush=True)
        # If mutex creation fails, allow the app to run anyway
        return True

# -----------------------
# Entry point
# -----------------------
if __name__ == "__main__":
    # Check if another instance is already running
    if not check_single_instance():
        # Another instance is running, exit silently
        os._exit(0)
    
    app = ScreenshotApp()
    app.run()