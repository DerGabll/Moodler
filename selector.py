"""Screenshot selection functionality."""

import tkinter as tk
from typing import Optional, Tuple, Callable


from utils import get_screen_scale

class Screenshot:
    """Transparent fullscreen window for selecting screenshot area."""
    
    def __init__(self, master: tk.Tk, on_complete: Callable):
        self.master = master
        self.on_complete = on_complete
        
        self._create_window()
        self._setup_bindings()
        
        self.start_coords = None
        self.final_coords = None

    def _create_window(self):
        """Create the transparent selection window."""
        self.window = tk.Toplevel(self.master)
        self.window.attributes("-fullscreen", True)
        self.window.attributes("-alpha", 0.01)  # Nearly invisible
        self.window.attributes("-topmost", True)
        self.window.configure(bg="black")
        
        self.canvas = tk.Canvas(self.window, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        
        # Get DPI scale for coordinate conversion
        self.hwnd = self.window.winfo_id()
        self.scale_factor = get_screen_scale(self.hwnd)

    def _setup_bindings(self):
        """Setup mouse and keyboard bindings."""
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_press)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_release)
        self.window.bind("<Escape>", self._cancel)

    def _on_mouse_press(self, event):
        """Handle mouse button press."""
        self.start_coords = (event.x_root, event.y_root)

    def _on_mouse_drag(self, event):
        """Handle mouse drag (optional: could add visual feedback)."""
        pass

    def _on_mouse_release(self, event):
        """Handle mouse button release."""
        if not self.start_coords:
            self._cancel()
            return
            
        x1, y1 = self.start_coords
        x2, y2 = event.x_root, event.y_root

        # Ensure minimum selection size
        if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
            self._cancel()
            return

        # Convert to physical pixels
        x1p = int(round(min(x1, x2) * self.scale_factor))
        y1p = int(round(min(y1, y2) * self.scale_factor))
        x2p = int(round(max(x1, x2) * self.scale_factor))
        y2p = int(round(max(y1, y2) * self.scale_factor))

        self.final_coords = (x1p, y1p, x2p, y2p)
        self._complete()

    def _complete(self):
        """Complete selection and call callback."""
        self.window.withdraw()
        self.master.after(150, self._finish)

    def _finish(self):
        """Finalize selection."""
        if self.final_coords:
            self.on_complete(self.final_coords)
        self._destroy()

    def _cancel(self, event=None):
        """Cancel selection."""
        self.final_coords = None
        self._destroy()

    def _destroy(self):
        """Clean up the selector window."""
        try:
            self.window.destroy()
        except Exception:
            pass