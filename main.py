import os
import glob
import base64
import threading
from dotenv import load_dotenv
from openai import OpenAI
import tkinter as tk
import win32gui
import win32con
import win32api
import keyboard
from PIL import ImageGrab

# --- CONFIG ---
load_dotenv(override=True)
SNEAKY_LAYOUT = True
SCREENSHOT_PATH = r"C:\Users\hudi\Pictures\Screenshots\*"

if not SNEAKY_LAYOUT:
    PROMPT_TEXT = """Welche Antwortmöglichkeiten sind richtig? Es kann eine oder mehrere richtige geben. Antworte kurz mit den richtigen Antworten und gebe 2 Anfangswörter und den Buchstaben jeder Antwort wieder. Ein Layout könnte zum Beispiel sein: " \
    a. Um komplexe
    c. Zur Analyse

    Dies ist nur ein Beispiellayout. Lese dir die Angabe immer genau durch und ignoriere, ob bei einer antwortmöglichkeit richtig oder falsch daneben steht.
    """
else:
    PROMPT_TEXT = """Welche Antwortmöglichkeiten sind richtig? Es kann eine oder mehrere richtige geben. Antworte kurz mit den richtigen Buchstaben jeder Antwort wieder. Ein Layout könnte zum Beispiel sein: " \
    a, c

    Dies ist nur ein Beispiellayout. Lese dir die Angabe immer genau durch und ignoriere, ob bei einer antwortmöglichkeit richtig oder falsch daneben steht.
    """   
client = OpenAI()

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
    text="(ALT+T) screenshot | (ALT+ENTER) send",
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

# --- Screenshot selection overlay ---
class ScreenshotSelector:
    def __init__(self):
        self.selector = tk.Toplevel(root)
        self.selector.attributes("-fullscreen", True)
        self.selector.attributes("-alpha", 0.01)  # Almost completely transparent
        self.selector.configure(bg="black")
        self.selector.attributes("-topmost", True)
        
        self.canvas = tk.Canvas(self.selector, highlightthickness=0, bg="black")
        self.canvas.pack(fill="both", expand=True)
        
        self.start_x = None
        self.start_y = None
        self.rect = None
        
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        
        # Bind escape key to cancel
        self.selector.bind("<Escape>", self.cancel)
        
    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="red", width=2, fill=""
        )
    
    def on_drag(self, event):
        if self.rect:
            self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)
    
    def on_release(self, event):
        end_x, end_y = event.x, event.y
        
        # Normalize coordinates (start should be top-left, end should be bottom-right)
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)
        
        # Ensure minimum size
        if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
            self.cancel()
            return
        
        # Take screenshot of selected area
        screenshot = ImageGrab.grab(bbox=(x1, y1, x2, y2))
        
        # Save to temporary file
        temp_path = os.path.join(os.environ['TEMP'], "selected_screenshot.png")
        screenshot.save(temp_path)
        
        # Clean up
        self.selector.destroy()
        
        # Update state with the selected screenshot
        state["screenshot_path"] = temp_path
        state["screenshot_loaded"] = True
        state["selecting_area"] = False
        update_label(f"Screenshot ready\n(ALT+T) screenshot | (ALT+ENTER) send")
    
    def cancel(self, event=None):
        self.selector.destroy()
        state["selecting_area"] = False
        update_label("(ALT+T) screenshot | (ALT+ENTER) send")

# --- Screenshot helpers ---
def get_latest_screenshot():
    files = glob.glob(SCREENSHOT_PATH)
    if not files:
        return None
    return max(files, key=os.path.getctime)

def start_area_selection():
    if state["selecting_area"] or state["sending"]:
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
            model="gpt-4o",
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
        update_label("(ALT+T) screenshot | (ALT+ENTER) send")

# --- Register global hotkeys ---
try:
    keyboard.add_hotkey("alt+t", start_area_selection)  # Start area selection
    keyboard.add_hotkey("alt+enter", on_enter_pressed)  # Send or continue
    keyboard.add_hotkey("alt+q", lambda: (keyboard.unhook_all_hotkeys(), root.destroy()))  # Quit
except Exception as e:
    update_label(f"Keyboard hook error: {e}\nRun as admin if needed.")

# --- Start ---
update_label("(ALT+T) screenshot | (ALT+ENTER) send")

try:
    root.mainloop()
finally:
    try:
        keyboard.unhook_all_hotkeys()
    except Exception:
        pass