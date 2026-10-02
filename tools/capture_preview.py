"""Capture this app's own window to review layout during development."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from PIL import ImageGrab
from mod_assistant.app import App

root = tk.Tk()
app = App(root)
count = [0]

def capture():
    count[0] += 1
    if app.env is not None and not (app.worker and app.worker.is_alive()):
        root.attributes("-topmost", True)
        root.lift()
        root.update()
        x, y = root.winfo_rootx(), root.winfo_rooty()
        scale = ImageGrab.grab().width / root.winfo_screenwidth()
        picture = ImageGrab.grab(bbox=tuple(round(v * scale) for v in
                                 (x, y, x + root.winfo_width(), y + root.winfo_height())))
        path = Path(__file__).resolve().parents[1] / "Research" / "ui-preview-v2.png"
        picture.save(path)
        root.attributes("-topmost", False)
        print(path, picture.size)
        app.close()
    elif count[0] > 300:
        print("UI preview timed out")
        app.close()
    else:
        root.after(100, capture)

root.after(100, capture)
root.mainloop()
