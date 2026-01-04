#!/usr/bin/env python3
"""
Screenshot -> OpenAI helper (refactored & cleaned)
Features:
 - Mouse-controlled UI with small, unobtrusive buttons
 - DPI-aware invisible selection window (Tkinter)
 - Saves API key to config directory (cross-platform)
 - Sends screenshot to OpenAI Chat Completions API with vision support
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional, Tuple

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
PROMPT_TEXT = (
    "Welche Antwortmöglichkeiten, glaubst du, sind richtig? "
    "Die Antwortmöglichkeiten sind mit Buchstaben geordnet. Schreibe in deiner Antwort "
    "nur Buchstaben mit einem Leerzeichen getrennt und nur Buchstaben, die die richtige Lösung beinhalten. "
    "Die Antwort sollte gut durchgedacht sein."
)
MODEL_NAME = "gpt-5"  # Using GPT-5 which supports vision
TEMP_SCREENSHOT_NAME = "moodler_screenshot.png"
# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# -----------------------
# Utilities
# -----------------------
def appdata_config_path() -> Path:
    """Return path to config file (cross-platform)."""
    if os.name == "nt":  # Windows
        appdata = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        config_dir = Path(appdata) / APP_NAME
    else:  # Linux/macOS
        xdg_config = os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        config_dir = Path(xdg_config) / APP_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


def load_api_key() -> Optional[str]:
    cfg = appdata_config_path()
    if not cfg.exists():
        return None
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        return data.get("api_key")
    except Exception:
        logging.exception("Failed to read config file")
        return None


def save_api_key(api_key: str) -> bool:
    cfg = appdata_config_path()
    try:
        cfg.write_text(json.dumps({"api_key": api_key}), encoding="utf-8")
        return True
    except Exception:
        logging.exception("Failed to save API key")
        return False


def delete_saved_api_key() -> bool:
    cfg = appdata_config_path()
    try:
        if cfg.exists():
            cfg.unlink()
        return True
    except Exception:
        logging.exception("Failed to delete config file")
        return False


def looks_like_api_key(k: Optional[str]) -> bool:
    return bool(k and k.startswith("sk-") and len(k) >= 10)


# -----------------------
# DPI / Process Awareness
# -----------------------
def ensure_process_dpi_awareness() -> None:
    """Try to set process DPI awareness for better high-DPI behavior on Windows."""
    if os.name != "nt" or ctypes is None:
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
    except Exception:
        logging.exception("Failed to set process DPI awareness")


def get_system_scale_factor(hwnd: Optional[int] = None) -> float:
    """Return DPI scale factor (1.0 = 100%, 1.25 = 125%, etc)."""
    # On Linux, Tkinter handles scaling automatically, so return 1.0
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
        self._win.attributes("-fullscreen", True)
        self._win.attributes("-alpha", 0.01)
        self._win.configure(bg="black")
        self._win.attributes("-topmost", True)
        self._win.update_idletasks()

        # Determine DPI scale for this window
        self._hwnd = None
        try:
            self._hwnd = self._win.winfo_id()
        except Exception:
            pass
        self.scale_factor = get_system_scale_factor(self._hwnd)

        # Canvas to catch mouse events
        self._canvas = tk.Canvas(self._win, highlightthickness=0, cursor="arrow")
        self._canvas.pack(fill="both", expand=True)

        self._start = None
        self._final_coords = None

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._win.bind("<Escape>", self._cancel)

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
        self._destroy()

    def _destroy(self):
        try:
            self._win.destroy()
        except Exception:
            pass

    def _keep_on_top(self):
        try:
            if not self._win.winfo_exists():
                return
            # Windows-specific: use win32 to bring to top
            if os.name == "nt" and win32gui and win32con:
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
            else:
                # Linux: use Tkinter attributes
                self._win.attributes("-topmost", True)
            self._win.after(50, self._keep_on_top)
        except Exception:
            pass


# -----------------------
# Main application UI + logic
# -----------------------
class ScreenshotApp:
    def __init__(self):
        ensure_process_dpi_awareness()
        self.temp_path = Path(os.getenv("TEMP", "/tmp")) / TEMP_SCREENSHOT_NAME
        self.username = getpass.getuser()
        self.state = {
            "screenshot_path": None,
            "screenshot_loaded": False,
            "response_text": None,
            "response_shown": False,
            "sending": False,
            "selecting_area": False,
        }
        # Tk root
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        # Use a unique color for transparency (will be made transparent)
        self.transparent_color = "#010101"  # Almost black, unique for transparency
        self.root.configure(bg=self.transparent_color)
        # small toolbar in top-left - minimal size
        self.root.geometry("200x25+5+5")
        self.hw = self.root.winfo_id()

        # Create a frame for buttons with transparent background
        self._button_frame = tk.Frame(self.root, bg=self.transparent_color)
        self._button_frame.pack(fill="both", expand=True, padx=1, pady=1)

        # Status label (very small, dark, transparent background)
        self._status_label = tk.Label(
            self._button_frame,
            text="Ready",
            fg="#2a2a2a",  # Dark gray, visible on transparent
            bg=self.transparent_color,
            font=("Arial", 7),
            anchor="w",
        )
        self._status_label.pack(side="left", padx=2)

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

        self._btn_screenshot = tk.Button(
            self._button_frame,
            text="📷",
            command=self.start_area_selection,
            **button_style,
        )
        self._btn_screenshot.pack(side="left", padx=1)

        self._btn_send = tk.Button(
            self._button_frame,
            text="➤",
            command=self.send_current_screenshot,
            **button_style,
        )
        self._btn_send.pack(side="left", padx=1)

        self._btn_reset = tk.Button(
            self._button_frame,
            text="↻",
            command=self.reset_api_key,
            **button_style,
        )
        self._btn_reset.pack(side="left", padx=1)

        self._btn_quit = tk.Button(
            self._button_frame,
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
        if os.name == "nt" and win32gui and win32con and win32api:
            # Windows: use color key transparency
            try:
                exstyle = win32gui.GetWindowLong(self.hw, win32con.GWL_EXSTYLE)
                exstyle |= win32con.WS_EX_LAYERED
                win32gui.SetWindowLong(self.hw, win32con.GWL_EXSTYLE, exstyle)
                # Make the transparent color transparent
                color_key = win32api.RGB(1, 1, 1)  # #010101
                win32gui.SetLayeredWindowAttributes(self.hw, color_key, 0, win32con.LWA_COLORKEY)
            except Exception:
                logging.exception("Failed to apply transparency on Windows")
        else:
            # Linux: Use a compositor-friendly approach
            # Try to set the window to support transparency through the compositor
            try:
                # Set window attributes that compositors recognize for transparency
                # The transparent color (#010101) will be handled by the compositor
                # if it supports per-pixel transparency
                self.root.attributes("-alpha", 0.99)  # Slight transparency hint
                # Some compositors will make the specific color transparent
                # This works best with compositors like picom, compton, or KWin
            except Exception:
                # If alpha doesn't work, try without it - compositor may handle color key
                try:
                    self.root.attributes("-alpha", 1.0)
                except Exception:
                    logging.exception("Failed to apply transparency on Linux")

    def _apply_window_exstyle(self):
        """Attempt to set extended window styles so the toolbar is non-activating and transparent color-keyed."""
        # Windows-specific window styling
        if os.name == "nt" and win32gui and win32con and win32api:
            try:
                exstyle = win32gui.GetWindowLong(self.hw, win32con.GWL_EXSTYLE)
                exstyle |= win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOOLWINDOW
                # custom NOACTIVATE constant used previously: 0x08000000
                exstyle |= 0x08000000
                win32gui.SetWindowLong(self.hw, win32con.GWL_EXSTYLE, exstyle)
                color_key = win32api.RGB(0, 0, 0)
                win32gui.SetLayeredWindowAttributes(self.hw, color_key, 0, win32con.LWA_COLORKEY)
            except Exception:
                logging.exception("Failed to set extended window styles for toolbar")
        # On Linux, just keep it topmost
        # ensure it stays topmost occasionally
        self.root.after(2000, self._keep_always_on_top)

    def _keep_always_on_top(self):
        try:
            if os.name == "nt" and win32gui and win32con:
                win32gui.SetWindowPos(
                    self.hw,
                    win32con.HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                )
            else:
                # On Linux, use Tkinter's attributes
                self.root.attributes("-topmost", True)
        except Exception:
            pass
        self.root.after(2000, self._keep_always_on_top)

    def _update_status(self, text: str):
        """Update the status label text."""
        def do_update():
            self._status_label.config(text=text[:30])  # Limit length
            # Update button states
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
        except Exception:
            logging.exception("Failed to create OpenAI client")
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

    # ---------- Screenshot flow ----------
    def start_area_selection(self):
        if self.state["selecting_area"] or self.state["sending"]:
            return
        # Reset state if we have a result shown
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
            if os.name == "nt" and win32api:
                sw_logical = win32api.GetSystemMetrics(0)
                sh_logical = win32api.GetSystemMetrics(1)
                scale = get_system_scale_factor()
                screen_w = int(round(sw_logical * scale))
                screen_h = int(round(sh_logical * scale))
            else:
                # Linux: use Tkinter to get screen size
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

    def _send_to_openai_thread(self):
        self.state["sending"] = True
        self._update_status("Processing...")
        try:
            with open(self.state["screenshot_path"], "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            # Use correct OpenAI Chat Completions API with vision support
            response = self.client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": PROMPT_TEXT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64}"},
                            },
                        ],
                    }
                ],
                max_tokens=300,
            )
            # Extract response text
            result_text = response.choices[0].message.content.strip()
            self.state["response_text"] = result_text
            self.state["response_shown"] = True
            # Show result in status (truncated if too long)
            display_text = result_text[:25] + "..." if len(result_text) > 25 else result_text
            self._update_status(display_text)
            # Also show in a small popup that auto-closes
            self._show_result_popup(result_text)
        except Exception as ex:
            logging.exception("OpenAI request failed")
            self.state["response_text"] = None
            self.state["response_shown"] = True
            error_msg = str(ex)[:25]
            self._update_status(f"Error: {error_msg}")
        finally:
            self.state["sending"] = False

    def _show_result_popup(self, text: str):
        """Show result in a small, unobtrusive popup window."""
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg="#1a1a1a")
        
        # Position near the main window
        popup.geometry("250x60+5+35")
        
        label = tk.Label(
            popup,
            text=text,
            fg="#4a4a4a",  # Slightly more visible than main UI
            bg="#1a1a1a",
            font=("Arial", 8),
            wraplength=240,
            justify="left",
        )
        label.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Auto-close after 5 seconds
        popup.after(5000, popup.destroy)
        
        # Also allow clicking to close
        popup.bind("<Button-1>", lambda e: popup.destroy())
        label.bind("<Button-1>", lambda e: popup.destroy())

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
# Entry point
# -----------------------
if __name__ == "__main__":
    app = ScreenshotApp()
    app.run()