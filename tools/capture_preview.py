"""Capture this app's own window to review layout during development."""
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from PIL import ImageGrab
from mod_assistant import VERSION
from mod_assistant.app import App
from mod_assistant.order_ui import OrderDialog
from mod_assistant.management_ui import ManagementDialog
from mod_assistant.core import atomic_json

root = tk.Tk()
app = App(root)
started = time.monotonic()

def capture():
    if app.env is not None and not (app.worker and app.worker.is_alive()):
        root.attributes("-topmost", True)
        root.lift()
        root.update()
        def snap(window, name):
            window.update()
            x, y = window.winfo_rootx(), window.winfo_rooty()
            scale = ImageGrab.grab().width / root.winfo_screenwidth()
            picture = ImageGrab.grab(bbox=tuple(round(v * scale) for v in
                                     (x, y, x + window.winfo_width(), y + window.winfo_height())))
            path = Path(__file__).resolve().parents[1] / "Research" / name
            picture.save(path)
            print(path, picture.size)
        snap(root, f"ui-preview-v{VERSION}.png")
        config = app.env.game / "config_player.xml"
        original = config.read_bytes()
        dialog = OrderDialog(app)
        dialog.window.attributes("-topmost", True)
        dialog.window.update()
        before = list(dialog.ids)
        if len(before) > 1:
            first, second = dialog.list.bbox(0), dialog.list.bbox(1)
            dialog.list.event_generate("<ButtonPress-1>", x=20, y=first[1] + 5)
            dialog.list.event_generate("<B1-Motion>", x=20, y=second[1] + 5)
            dialog.list.event_generate("<ButtonRelease-1>", x=20, y=second[1] + 5)
            assert dialog.ids[:2] == [before[1], before[0]]
            dialog.move(-1)
            assert dialog.ids == before
        dialog.automatic()
        assert set(dialog.ids) == set(before)
        assert config.read_bytes() == original
        def finish():
            snap(dialog.window, f"ui-order-v{VERSION}.png")
            atomic_json(Path(__file__).resolve().parents[1] / f"Research/ui-order-check-v{VERSION}.json",
                        {"ok": True, "enabled_regular_mods": len(before), "drag_test": len(before) > 1,
                         "automatic_preview": True, "live_configuration_unchanged": True})
            dialog.window.destroy()
            manager=ManagementDialog(app); manager.window.attributes('-topmost',True)
            def finish_manager():
                snap(manager.window,f'ui-manager-v{VERSION}.png'); manager.window.destroy()
                root.attributes("-topmost", False); app.close()
            root.after(400,finish_manager)
        root.after(400, finish)
    elif time.monotonic() - started > 180:
        print("UI preview timed out")
        app.close()
    else:
        root.after(100, capture)

root.after(100, capture)
root.mainloop()
