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

# --- CONFIG ---
username = getpass.getuser()
SCREENSHOT_PATH = rf"C:\Users\{username}\Pictures\Screenshots\*"

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
    if len(api_key) < 10:  # Minimum reasonable length for an API key
        return False
    return True

def get_api_key():
    """Get API key from saved config or user input"""
    # First try to load saved API key
    saved_api_key = load_saved_api_key()
    if saved_api_key and is_valid_api_key(saved_api_key):
        return saved_api_key
    
    # If no valid saved key, ask user
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    
    while True:
        api_key = simpledialog.askstring(
            "OpenAI API Key Required", 
            "Enter your OpenAI API key (starts with sk-...):",
            show='*'  # This hides the input (shows asterisks)
        )
        
        if not api_key:
            messagebox.showerror("Error", "API key is required to use this application.")
            root.destroy()
            return None
        
        if is_valid_api_key(api_key):
            # Save the valid API key
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
root.overrideredirect(True)  # no border/title
root.attributes("-topmost", True)  # always on top
root.configure(bg="black")  # black background for color-key transparency
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
            # Properly shutdown the application
            keyboard.unhook_all_hotkeys()
            root.quit()
            root.destroy()
            exit(0)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to reset API key: {e}")
            temp_root.destroy()
    else:
        temp_root.destroy()

# --- Screenshot selection overlay ---
class ScreenshotSelector:
    def __init__(self):
        self.selector = tk.Toplevel(root)
        self.selector.attributes("-fullscreen", True)
        self.selector.attributes("-alpha", 0.3)
        self.selector.configure(bg="black")
        self.selector.attributes("-topmost", True)
        
        self.canvas = tk.Canvas(self.selector, highlightthickness=0, bg="black", cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        
        self.start_x = None
        self.start_y = None
        self.rect = None
        self.crosshairs = []
        
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        
        # Bind escape key to cancel
        self.selector.bind("<Escape>", self.cancel)
        
    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        # Entferne Info-Text wenn Auswahl beginnt
        self.canvas.delete("info")
        
        # Zeichne Rechteck mit sehr gut sichtbarer Umrandung
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="#FF0000",  # Knalliges Rot für maximale Sichtbarkeit
            width=3,           # Dicke Linie
            fill="",           # Keine Füllung
            dash=(10, 5)       # Längere gestrichelte Linie
        )
        
        # Erstelle Kreuzlinien für bessere Orientierung
        self.create_crosshairs(event.x, event.y)
        
        # Größen-Anzeige
        self.size_text = self.canvas.create_text(
            self.start_x, self.start_y - 25,
            text="0 x 0",
            fill="#FF0000",
            font=("Arial", 11, "bold"),
            tags="size"
        )
    
    def create_crosshairs(self, x, y):
        # Entferne alte Kreuzlinien
        for line in self.crosshairs:
            self.canvas.delete(line)
        self.crosshairs = []
        
        # Horizontale Linie über gesamten Bildschirm
        self.crosshairs.append(self.canvas.create_line(
            0, y, self.canvas.winfo_width(), y,
            fill="#FF0000", width=1, dash=(2, 2)
        ))
        
        # Vertikale Linie über gesamten Bildschirm
        self.crosshairs.append(self.canvas.create_line(
            x, 0, x, self.canvas.winfo_height(),
            fill="#FF0000", width=1, dash=(2, 2)
        ))
    
    def on_drag(self, event):
        if self.rect:
            self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)
            
            # Aktualisiere Kreuzlinien
            self.create_crosshairs(event.x, event.y)
            
            # Aktualisiere Größen-Anzeige
            width = abs(event.x - self.start_x)
            height = abs(event.y - self.start_y)
            mid_x = min(self.start_x, event.x) + width/2
            mid_y = min(self.start_y, event.y) - 20
            
            self.canvas.coords(self.size_text, mid_x, mid_y)
            self.canvas.itemconfig(self.size_text, text=f"{width} × {height}")
    
    def on_release(self, event):
        end_x, end_y = event.x, event.y
        
        # Normalize coordinates
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)
        
        # Ensure minimum size
        if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
            self.cancel()
            return
        
        # Hole die DPI-Skalierung
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()
            
            # Hole den primären Monitor Handle
            hMonitor = user32.MonitorFromPoint(ctypes.wintypes.POINT(int(x1), int(y1)), 2)
            
            # Hole die DPI-Skalierung
            shcore = ctypes.windll.shcore
            dpiX = ctypes.c_uint()
            dpiY = ctypes.c_uint()
            shcore.GetDpiForMonitor(hMonitor, 0, ctypes.byref(dpiX), ctypes.byref(dpiY))
            
            scale_factor = dpiX.value / 96.0  # 96 DPI = 100% Skalierung
        except:
            scale_factor = 1.0
        
        # Skaliere die Koordinaten
        x1_scaled = int(x1 * scale_factor)
        y1_scaled = int(y1 * scale_factor)
        x2_scaled = int(x2 * scale_factor)
        y2_scaled = int(y2 * scale_factor)
        
        # Speichere die skalierten Koordinaten
        self.final_coords = (x1_scaled, y1_scaled, x2_scaled, y2_scaled)
        
        # Entferne alle visuellen Elemente
        for line in self.crosshairs:
            self.canvas.delete(line)
        self.crosshairs = []
        if hasattr(self, 'rect'):
            self.canvas.delete(self.rect)
        if hasattr(self, 'size_text'):
            self.canvas.delete(self.size_text)
        
        # Verstecke das Overlay
        self.selector.withdraw()
        
        # Screenshot mit Verzögerung
        root.after(250, self.take_screenshot)

    def take_screenshot(self):
        x1, y1, x2, y2 = self.final_coords
        
        # Screenshot mit den skalierten Koordinaten
        screenshot = ImageGrab.grab(bbox=(x1, y1, x2, y2))
        
        # Save to temporary file
        temp_path = os.path.join(os.environ['TEMP'], "selected_screenshot.png")
        screenshot.save(temp_path)
        
        # Clean up
        self.selector.destroy()
        
        # Update state
        state["screenshot_path"] = temp_path
        state["screenshot_loaded"] = True
        state["selecting_area"] = False
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        update_label(f"Screenshot ready ({width}x{height})\n(ALT+T) screenshot | (ALT+ENTER) send | (ALT+R) reset API key")    
    
    def cancel(self, event=None):
        # Entferne Kreuzlinien
        for line in self.crosshairs:
            self.canvas.delete(line)
        self.crosshairs = []
        
        self.selector.destroy()
        state["selecting_area"] = False
        update_label("(ALT+T) screenshot | (ALT+ENTER) send | (ALT+R) reset API key")

# --- Screenshot helpers ---
def get_latest_screenshot():
    files = glob.glob(SCREENSHOT_PATH)
    if not files:
        return None
    return max(files, key=os.path.getctime)

def start_area_selection():
    # Verhindere Screenshot-Auswahl während des Sendens, bei aktiver Auswahl
    # ODER wenn bereits eine Antwort angezeigt wird
    if state["selecting_area"] or state["sending"] or state["response_shown"]:
        return
    
    state["selecting_area"] = True
    update_label("Select area with mouse (ESC to cancel)")
    
    # Small delay to ensure the UI updates before showing selector
    root.after(100, lambda: ScreenshotSelector())

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
        # Reset for next screenshot
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
    keyboard.add_hotkey("alt+t", start_area_selection)  # Start area selection
    keyboard.add_hotkey("alt+enter", on_enter_pressed)  # Send or continue
    keyboard.add_hotkey("alt+r", reset_api_key)  # Reset API key
    keyboard.add_hotkey("alt+q", lambda: (keyboard.unhook_all_hotkeys(), root.destroy()))  # Quit
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