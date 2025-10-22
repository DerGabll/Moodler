import os
import glob
import base64
import threading
import tkinter as tk
from tkinter import simpledialog, messagebox
import win32gui
import win32con
import win32api
import keyboard
from PIL import ImageGrab
from openai import OpenAI
import json
import getpass

def ensure_process_dpi_awareness():
    try:
        import ctypes
        # Try SetProcessDpiAwareness (Windows 8.1+)
        try:
            shcore = ctypes.windll.shcore
            PROCESS_PER_MONITOR_DPI_AWARE = 2
            shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
        except Exception:
            # Fallback to older API
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        # Also try SetProcessDpiAwarenessContext (Windows 10+)
        try:
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
            ctypes.windll.user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        except Exception:
            pass
    except Exception:
        pass

# call it early, before creating any top-level windows
ensure_process_dpi_awareness()

# --- CONFIG ---
username = getpass.getuser()
TEMP_SCREENSHOT_PATH = os.path.join(os.environ['TEMP'], "snip_capture.png")

PROMPT_TEXT = """
Welche Antwortmöglichkeiten, glaubst du, sind richtig? Die Antwortmöglichkeiten sind mit Buchstaben geordnet. Schreibe in deiner Antwort nur Buchstaben mit einem Leerzeichen getrennt und nur Buchstaben, die die richtige Lösung beinhalten. Die Antwort sollte gut durchgedacht sein.
"""   

# --- API Key Management ---
def get_config_path():
    """Get path for config file in user's appdata directory"""
    appdata_path = os.getenv('APPDATA')
    config_dir = os.path.join(appdata_path, "ScreenshotAI")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "config.json")

def load_saved_api_key():
    """Load API key from config file"""
    config_path = get_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                return config.get('api_key')
        except:
            return None
    return None

def save_api_key(api_key):
    """Save API key to config file"""
    config_path = get_config_path()
    config = {'api_key': api_key}
    try:
        with open(config_path, 'w') as f:
            json.dump(config, f)
        return True
    except:
        return False

def is_valid_api_key(api_key):
    """Check if API key looks valid (starts with sk- and has reasonable length)"""
    if not api_key:
        return False
    if not api_key.startswith('sk-'):
        return False
    if len(api_key) < 10:
        return False
    return True

def get_api_key():
    """Get API key from saved config or user input"""
    saved_api_key = load_saved_api_key()
    if saved_api_key and is_valid_api_key(saved_api_key):
        return saved_api_key
    
    root = tk.Tk()
    root.withdraw()
    
    while True:
        api_key = simpledialog.askstring(
            "OpenAI API Key Required", 
            "Enter your OpenAI API key (starts with sk-...):",
            show='*'
        )
        
        if not api_key:
            messagebox.showerror("Error", "API key is required to use this application.")
            root.destroy()
            return None
        
        if is_valid_api_key(api_key):
            if save_api_key(api_key):
                messagebox.showinfo("Success", "API key saved successfully!")
            break
        else:
            messagebox.showerror("Invalid API Key", "API key must start with 'sk-' and be valid. Please try again.")
    
    root.destroy()
    return api_key

# Initialize OpenAI client
api_key = get_api_key()
if not api_key:
    exit()

client = OpenAI(api_key=api_key)

# --- STATE ---
state = {
    "screenshot_path": None,
    "screenshot_loaded": False,
    "response_text": None,
    "response_shown": False,
    "sending": False,
    "selecting_area": False
}

# --- UI SETUP ---
root = tk.Tk()
root.overrideredirect(True)
root.attributes("-topmost", True)
root.configure(bg="black")
root.geometry("300x40+10+10")

label = tk.Label(
    root,
    text="(ALT+T) screenshot | (ALT+ENTER) send | (ALT+R) reset API key",
    fg="lime",
    bg="black",
    font=("Consolas", 12),
    justify="left",
    anchor="w"
)
label.pack(fill="both", expand=True, padx=4, pady=2)
root.update_idletasks()

# --- Make window click-through, non-activating, and color-key transparent ---
hwnd = root.winfo_id()

def keep_always_on_top():
    try:
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOPMOST,
            0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
        )
    except Exception:
        pass
    root.after(2000, keep_always_on_top)

root.after(0, keep_always_on_top)

WS_EX_LAYERED = win32con.WS_EX_LAYERED
WS_EX_TRANSPARENT = win32con.WS_EX_TRANSPARENT
WS_EX_TOOLWINDOW = win32con.WS_EX_TOOLWINDOW
WS_EX_NOACTIVATE = 0x08000000

exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
exstyle |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, exstyle)

COLOR_KEY = win32api.RGB(0, 0, 0)
win32gui.SetLayeredWindowAttributes(hwnd, COLOR_KEY, 0, win32con.LWA_COLORKEY)

# --- Helper to update label ---
def update_label(text: str):
    def do_update():
        label.config(text=text)
        root.update_idletasks()
        w = label.winfo_reqwidth() + 8
        h = label.winfo_reqheight() + 4
        max_w = 800
        if w > max_w:
            w = max_w
            label.config(wraplength=max_w - 10)
        root.geometry(f"{w}x{h}+10+10")
    root.after(0, do_update)

# --- Reset API Key ---
def reset_api_key():
    """Allow user to reset the saved API key"""
    if state["sending"] or state["selecting_area"]:
        return
        
    temp_root = tk.Tk()
    temp_root.withdraw()
    
    result = messagebox.askyesno(
        "Reset API Key",
        "Do you want to reset the saved API key? The application will close and you'll need to restart it."
    )
    
    if result:
        config_path = get_config_path()
        try:
            if os.path.exists(config_path):
                os.remove(config_path)
            messagebox.showinfo("Success", "API key reset. The application will now close.")
            temp_root.destroy()
            keyboard.unhook_all_hotkeys()
            root.quit()
            root.destroy()
            exit(0)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to reset API key: {e}")
            temp_root.destroy()
    else:
        temp_root.destroy()

# --- Invisible Screenshot Selector ---
# --- Invisible Screenshot Selector (DPI-corrected) ---
class InvisibleScreenshotSelector:
    def __init__(self):
        self.selector = tk.Toplevel(root)
        self.selector.attributes("-fullscreen", True)
        self.selector.attributes("-alpha", 0.01)  # Nearly invisible
        self.selector.configure(bg="black")
        self.selector.attributes("-topmost", True)

        # Make sure window exists and get its hwnd
        self.selector.update_idletasks()
        selector_hwnd = self.selector.winfo_id()

        # Get DPI scaling factor for this window (returns 1.0, 1.25, 1.5, etc.)
        self.scale_factor = self.get_system_scale_factor(selector_hwnd)
        try:
            print(f"[DEBUG] Selector scale factor detected: {self.scale_factor}")
        except Exception:
            pass

        # Make window truly topmost
        try:
            exstyle = win32gui.GetWindowLong(selector_hwnd, win32con.GWL_EXSTYLE)
            exstyle |= win32con.WS_EX_TOPMOST
            win32gui.SetWindowLong(selector_hwnd, win32con.GWL_EXSTYLE, exstyle)
        except Exception:
            pass

        try:
            win32gui.SetWindowPos(
                selector_hwnd,
                win32con.HWND_TOPMOST,
                0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
            )
        except Exception:
            pass

        self.canvas = tk.Canvas(self.selector, highlightthickness=0, bg="black", cursor="arrow")
        self.canvas.pack(fill="both", expand=True)

        self.start_x = None
        self.start_y = None

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.selector.bind("<Escape>", self.cancel)

        self.keep_selector_on_top()

    def get_system_scale_factor(self, hwnd):
        """Return DPI scale factor for the window (1.0, 1.25, 1.5...)."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32

            # Prefer GetDpiForWindow (Windows 10+)
            try:
                dpi = user32.GetDpiForWindow(hwnd)
                if dpi and dpi > 0:
                    return dpi / 96.0
            except Exception:
                pass

            # Fallback to GetDpiForSystem
            try:
                dpi = user32.GetDpiForSystem()
                if dpi and dpi > 0:
                    return dpi / 96.0
            except Exception:
                pass

            # Fallback to GetDeviceCaps
            try:
                hdc = user32.GetDC(0)
                LOGPIXELSX = 88
                dpi = gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
                user32.ReleaseDC(0, hdc)
                if dpi and dpi > 0:
                    return dpi / 96.0
            except Exception:
                pass
        except Exception:
            pass
        return 1.0

    def on_press(self, event):
        # event.x_root / event.y_root are logical (DIP) coords
        self.start_x = event.x_root
        self.start_y = event.y_root

    def on_drag(self, event):
        pass

    def on_release(self, event):
        end_x, end_y = event.x_root, event.y_root

        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)

        if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
            self.cancel()
            return

        # IMPORTANT: Convert logical coords → physical pixels by MULTIPLYING by scale_factor
        x1_phys = int(round(x1 * self.scale_factor))
        y1_phys = int(round(y1 * self.scale_factor))
        x2_phys = int(round(x2 * self.scale_factor))
        y2_phys = int(round(y2 * self.scale_factor))

        self.final_coords = (x1_phys, y1_phys, x2_phys, y2_phys)

        self.selector.withdraw()
        root.after(200, self.take_screenshot)

    def take_screenshot(self):
        x1, y1, x2, y2 = self.final_coords

        # Get logical screen metrics and convert to physical pixels too
        try:
            screen_width_logical = win32api.GetSystemMetrics(0)
            screen_height_logical = win32api.GetSystemMetrics(1)
            screen_width = int(round(screen_width_logical * self.scale_factor))
            screen_height = int(round(screen_height_logical * self.scale_factor))
        except Exception:
            screen_width = x2 + 10
            screen_height = y2 + 10

        # Clamp
        x1 = max(0, min(x1, screen_width - 1))
        y1 = max(0, min(y1, screen_height - 1))
        x2 = max(0, min(x2, screen_width))
        y2 = max(0, min(y2, screen_height))

        if x2 <= x1:
            x2 = x1 + 10
        if y2 <= y1:
            y2 = y1 + 10

        try:
            screenshot = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            screenshot.save(TEMP_SCREENSHOT_PATH)

            state["screenshot_path"] = TEMP_SCREENSHOT_PATH
            state["screenshot_loaded"] = True
            state["selecting_area"] = False
            width = abs(x2 - x1)
            height = abs(y2 - y1)
            update_label(f"Screenshot ready ({width}x{height})\n(ALT+T) screenshot | (ALT+ENTER) send | (ALT+R) reset API key")
        except Exception as e:
            update_label(f"Screenshot error: {str(e)}\n(ALT+T) to try again")
            state["selecting_area"] = False

        try:
            self.selector.destroy()
        except Exception:
            pass

    def cancel(self, event=None):
        try:
            self.selector.destroy()
        except Exception:
            pass
        state["selecting_area"] = False
        update_label("(ALT+T) screenshot | (ALT+ENTER) send | (ALT+R) reset API key")

    def keep_selector_on_top(self):
        try:
            if not self.selector.winfo_exists():
                return
            selector_hwnd = self.selector.winfo_id()
            win32gui.BringWindowToTop(selector_hwnd)
            try:
                win32gui.SetForegroundWindow(selector_hwnd)
            except Exception:
                pass
            win32gui.SetWindowPos(
                selector_hwnd,
                win32con.HWND_TOPMOST,
                0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
                win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW
            )
            self.selector.after(50, self.keep_selector_on_top)
        except:
            pass


# --- Start area selection ---
def start_area_selection():
    if state["selecting_area"] or state["sending"] or state["response_shown"]:
        return
    
    state["selecting_area"] = True
    update_label("Click and drag to select area (ESC to cancel)")
    
    root.after(100, lambda: InvisibleScreenshotSelector())

# --- OpenAI request (background thread) ---
def send_to_openai_and_update_ui():
    state["sending"] = True
    update_label("Bitte warten...")
    try:
        with open(state["screenshot_path"], "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
        response = client.responses.create(
            model="gpt-5",
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": PROMPT_TEXT},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{img_b64}"}
                ]
            }],
        )
        result_text = response.output_text.strip() if hasattr(response, "output_text") else str(response)
        state["response_text"] = result_text
        state["response_shown"] = True
        update_label(f"{result_text}\n\n(ALT+ENTER) continue")
    except Exception as e:
        update_label(f"❌ Error: {str(e)}\n(ALT+ENTER) continue")
        state["response_text"] = None
        state["response_shown"] = True
    finally:
        state["sending"] = False

# --- Hotkey callbacks ---
def on_enter_pressed():
    if state["sending"] or state["selecting_area"]:
        return
        
    if state["screenshot_loaded"] and not state["response_shown"]:
        threading.Thread(target=send_to_openai_and_update_ui, daemon=True).start()
        return
    if state["response_shown"]:
        state.update({
            "screenshot_path": None,
            "screenshot_loaded": False,
            "response_text": None,
            "response_shown": False,
            "sending": False
        })
        update_label("(ALT+T) screenshot | (ALT+ENTER) send | (ALT+R) reset API key")

# --- Register global hotkeys ---
try:
    keyboard.add_hotkey("alt+t", start_area_selection)
    keyboard.add_hotkey("alt+enter", on_enter_pressed)
    keyboard.add_hotkey("alt+r", reset_api_key)
    keyboard.add_hotkey("alt+q", lambda: (keyboard.unhook_all_hotkeys(), root.destroy()))
except Exception as e:
    update_label(f"Keyboard hook error: {e}\nRun as admin if needed.")

# --- Start ---
update_label("(ALT+T) screenshot | (ALT+ENTER) send | (ALT+R) reset API key")

try:
    root.mainloop()
finally:
    try:
        keyboard.unhook_all_hotkeys()
    except Exception:
        pass