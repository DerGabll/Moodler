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

# --- CONFIG ---
load_dotenv(override=True)
SCREENSHOT_PATH = r"C:\Users\hudi\Pictures\Screenshots\*"
PROMPT_TEXT = "Welche der Antwortmöglichkeiten sind richtig (Es können mehrere richtig sein, aber es kann auch nur 1 sein). Antworte kurz"
client = OpenAI()

# --- STATE ---
state = {
    "screenshot_path": None,
    "screenshot_loaded": False,
    "response_text": None,
    "response_shown": False,
    "sending": False
}

# --- UI SETUP ---
root = tk.Tk()
root.overrideredirect(True)  # no border/title
root.attributes("-topmost", True)  # always on top
root.configure(bg="black")  # black background for color-key transparency
root.geometry("300x40+10+10")

label = tk.Label(
    root,
    text="Waiting to read screenshot. Press R to load.",
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

# --- Screenshot helpers ---
def get_latest_screenshot():
    files = glob.glob(SCREENSHOT_PATH)
    if not files:
        return None
    return max(files, key=os.path.getctime)

def load_screenshot():
    path = get_latest_screenshot()
    if not path:
        update_label("⚠️ No screenshots found. Press R to retry.")
        return False
    state["screenshot_path"] = path
    state["screenshot_loaded"] = True
    update_label(f"Screenshot: {os.path.basename(path)}\nPress Enter to send.")
    return True

# --- OpenAI request (background thread) ---
def send_to_openai_and_update_ui():
    state["sending"] = True
    update_label("Processing... (sending to ChatGPT)")
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
        update_label(f"{result_text}\n\n(Press Enter to continue)")
    except Exception as e:
        update_label(f"❌ Error: {e}\nPress Enter to continue.")
        state["response_text"] = None
        state["response_shown"] = True
    finally:
        state["sending"] = False

# --- Hotkey callbacks ---
def on_r_pressed():
    if state["sending"]:
        return
    state["screenshot_loaded"] = False
    state["response_shown"] = False
    state["response_text"] = None
    update_label("Reading latest screenshot...")
    load_screenshot()

def on_enter_pressed():
    if state["screenshot_loaded"] and not state["sending"] and not state["response_shown"]:
        threading.Thread(target=send_to_openai_and_update_ui, daemon=True).start()
        return
    if state["response_shown"] and not state["sending"]:
        state.update({
            "screenshot_path": None,
            "screenshot_loaded": False,
            "response_text": None,
            "response_shown": False
        })
        update_label("Waiting to read screenshot. Press R to load.")

# --- Register global hotkeys ---
try:
    keyboard.add_hotkey("ctrl+r", on_r_pressed)
    keyboard.add_hotkey("ctrl+enter", on_enter_pressed)
    keyboard.add_hotkey("ctrl+q", lambda: (keyboard.unhook_all_hotkeys(), root.destroy()))
except Exception as e:
    update_label(f"Keyboard hook error: {e}\nRun as admin if needed.")

# --- Start ---
update_label("Waiting to read screenshot. Press R to load.")

try:
    root.mainloop()
finally:
    try:
        keyboard.unhook_all_hotkeys()
    except Exception:
        pass
