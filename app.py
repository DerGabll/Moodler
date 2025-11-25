"""Main application class for Moodler."""

import os
import threading
from pathlib import Path
from typing import Optional
import win32con
import win32gui
import win32api
from openai import OpenAI
import logging

import getpass
import keyboard
import tkinter as tk
from tkinter import messagebox, simpledialog

from PIL import ImageGrab

from config import APP_NAME, PROMPT_TEXT, MODEL_NAME, TEMP_SCREENSHOT_NAME, HOTKEYS
from utils import (
    ensure_dpi_awareness, load_api_key, save_api_key, delete_api_key, 
    is_valid_api_key, encode_image_to_base64, get_screen_scale
)
from selector import Screenshot

class MoodlerApp:
    """Main application class."""
    
    def __init__(self):
        ensure_dpi_awareness()
        
        self.temp_path = Path(os.getenv("TEMP", "/tmp")) / TEMP_SCREENSHOT_NAME
        self.username = getpass.getuser()
        self.client = None
        
        self._setup_state()
        self._create_ui()
        self._register_hotkeys()

    def _setup_state(self):
        """Initialize application state."""
        self.state = {
            "screenshot_path": None,
            "screenshot_loaded": False,
            "response_text": None,
            "response_shown": False,
            "sending": False,
            "selecting_area": False,
        }

    def _create_ui(self):
        """Create the main application UI."""
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black")
        self.root.geometry("300x40+10+10")  # Initial small size
        
        self.label = tk.Label(
            self.root,
            text="",  # Start empty
            fg="lime",
            bg="black",
            font=("Consolas", 12),
            justify="left",
            anchor="w",
            wraplength=780,  # Set wraplength from start
        )
        self.label.pack(fill="both", expand=True, padx=8, pady=4)  # Increased padding
        
        self._apply_window_styles()
        
        # Set initial text using update_label to ensure proper sizing
        self._update_label("(ALT+T) screenshot | (ALT+ENTER) send | (ALT+R) reset API key")

    def _apply_window_styles(self):
        """Apply special window styles for transparency and always-on-top."""
        try:
            hwnd = self.root.winfo_id()
            exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            exstyle |= win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOOLWINDOW
            exstyle |= 0x08000000  # NOACTIVATE
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, exstyle)
            
            color_key = win32api.RGB(0, 0, 0)
            win32gui.SetLayeredWindowAttributes(hwnd, color_key, 0, win32con.LWA_COLORKEY)
        except Exception as e:
            logging.warning(f"Could not apply window styles: {e}")

    def _update_label(self, text: str):
        """Update the status label."""
        def update():
            self.label.config(text=text)
            self.root.update_idletasks()
            
            # Force update to get proper dimensions
            self.root.update()
            
            # Auto-resize window to fit content
            width = min(self.label.winfo_reqwidth() + 20, 800)  # Increased padding
            height = self.label.winfo_reqheight() + 10          # Increased padding
            
            if width >= 800:
                self.label.config(wraplength=780)
            
            # Apply the new geometry
            self.root.geometry(f"{width}x{height}+10+10")
            self.root.update_idletasks()
            
        self.root.after(0, update)

    def _register_hotkeys(self):
        """Register global hotkeys."""
        try:
            keyboard.add_hotkey(HOTKEYS["capture"], self._start_screenshot)
            keyboard.add_hotkey(HOTKEYS["send"], self._handle_send)
            keyboard.add_hotkey(HOTKEYS["reset"], self._reset_api_key)
            keyboard.add_hotkey(HOTKEYS["quit"], self._cleanup_quit)
        except Exception as e:
            self._update_label(f"Hotkey error: {e} - Run as admin if needed")

    def _ensure_openai_client(self) -> bool:
        """Ensure OpenAI client is available and configured."""
        api_key = load_api_key()
        
        if is_valid_api_key(api_key):
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=api_key)
                return True
            except Exception as e:
                logging.error(f"OpenAI client error: {e}")
                self._show_error("OpenAI Error", "Failed to create OpenAI client")
                return False

        # Prompt for API key
        return self._prompt_for_api_key()

    def _prompt_for_api_key(self) -> bool:
        """Prompt user for OpenAI API key."""
        temp_root = tk.Tk()
        temp_root.withdraw()
        
        while True:
            api_key = simpledialog.askstring(
                "API Key Required",
                "Enter your OpenAI API key (starts with sk-...):",
                show="*",
                parent=temp_root,
            )
            
            if api_key is None:
                messagebox.showerror("Error", "API key is required", parent=temp_root)
                temp_root.destroy()
                return False
                
            if is_valid_api_key(api_key):
                if save_api_key(api_key):
                    self.client = OpenAI(api_key=api_key)
                    temp_root.destroy()
                    return True
                else:
                    messagebox.showwarning("Warning", "Failed to save API key", parent=temp_root)
            else:
                messagebox.showerror("Invalid Key", "API key must start with 'sk-'", parent=temp_root)
                
        temp_root.destroy()
        return False

    def _start_screenshot(self):
        """Start screenshot area selection."""
        if self.state["selecting_area"] or self.state["sending"]:
            return
            
        self.state["selecting_area"] = True
        self._update_label("Click and drag to select area (ESC to cancel)")
        
        self.root.after(50, lambda: Screenshot(self.root, self._on_selection_complete))

    def _on_selection_complete(self, coords: Optional[tuple]):
        """Handle completed screenshot selection."""
        self.state["selecting_area"] = False
        
        if not coords:
            self._update_label("(ALT+T) screenshot | (ALT+ENTER) send | (ALT+R) reset API key")
            return

        try:
            image = ImageGrab.grab(bbox=coords)
            image.save(self.temp_path)
            
            self.state["screenshot_path"] = str(self.temp_path)
            self.state["screenshot_loaded"] = True
            
            width = abs(coords[2] - coords[0])
            height = abs(coords[3] - coords[1])
            self._update_label(f"Screenshot ready ({width}x{height})")
            
        except Exception as e:
            logging.error(f"Screenshot failed: {e}")
            self.state["screenshot_loaded"] = False
            self._update_label(f"Screenshot error: {e}")

    def _handle_send(self):
        """Handle send hotkey based on current state."""
        if self.state["sending"] or self.state["selecting_area"]:
            return
            
        if self.state["screenshot_loaded"] and not self.state["response_shown"]:
            self._send_screenshot()
        elif self.state["response_shown"]:
            self._reset_state()

    def _send_screenshot(self):
        """Send current screenshot to OpenAI."""
        if not self._ensure_openai_client():
            return
            
        thread = threading.Thread(target=self._process_screenshot, daemon=True)
        thread.start()

    def _process_screenshot(self):
        """Process screenshot in background thread."""
        self.state["sending"] = True
        self._update_label("Bitte warten...")
        
        try:
            image_b64 = encode_image_to_base64(self.state["screenshot_path"])
            
            response = self.client.responses.create(
                model=MODEL_NAME,
                input=[{
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": PROMPT_TEXT},
                        {"type": "input_image", "image_url": f"data:image/png;base64,{image_b64}"},
                    ],
                }],
            )
            
            result_text = getattr(response, "output_text", str(response)).strip()
            self.state["response_text"] = result_text
            self.state["response_shown"] = True
            self._update_label(f"{result_text}\n\n(ALT+ENTER) continue")
            
        except Exception as e:
            logging.error(f"OpenAI request failed: {e}")
            self.state["response_shown"] = True
            self._update_label(f"❌ Error: {e}\n(ALT+ENTER) continue")
        finally:
            self.state["sending"] = False

    def _reset_state(self):
        """Reset application to initial state."""
        self.state.update({
            "screenshot_path": None,
            "screenshot_loaded": False,
            "response_text": None,
            "response_shown": False,
            "sending": False,
        })
        self._update_label("(ALT+T) screenshot | (ALT+ENTER) send | (ALT+R) reset API key")

    def _reset_api_key(self):
        """Reset saved API key."""
        if self.state["sending"] or self.state["selecting_area"]:
            return
            
        temp_root = tk.Tk()
        temp_root.withdraw()
        
        if messagebox.askyesno("Reset API Key", "Reset saved API key? App will close.", parent=temp_root):
            if delete_api_key():
                messagebox.showinfo("Success", "API key reset. App will close.", parent=temp_root)
                temp_root.destroy()
                self._cleanup_quit()
            else:
                messagebox.showerror("Error", "Failed to reset API key", parent=temp_root)
                temp_root.destroy()

    def _show_error(self, title: str, message: str):
        """Show error message dialog."""
        temp_root = tk.Tk()
        temp_root.withdraw()
        messagebox.showerror(title, message, parent=temp_root)
        temp_root.destroy()

    def _cleanup_quit(self):
        """Clean up resources and quit application."""
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
            
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass
            
        os._exit(0)

    def run(self):
        """Run the application."""
        try:
            self.root.mainloop()
        finally:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass