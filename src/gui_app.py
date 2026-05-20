"""
BCI NavTools — Control Center
==============================
Neural Interface Dashboard for Voice Assistant and Gaze Tracking.
Features a floating Orb and a voice-activated Settings Dashboard.

Usage:
  python -m src.gui_app

Group No. 7 | 8th Semester Major Project
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import queue
import logging
import time
import sys
import os

# ── Neural Interface Design System ─────────────────
BG       = "#081425"    # Deep Navy
CARD     = "#111c2d"    # Surface low
CARD2    = "#152031"    # Surface container
TERMINAL = "#040e1f"    # Surface lowest (terminal)
ACCENT   = "#00f5c8"    # Primary Cyan-Green
SUCCESS  = "#a3e635"    # Terminal Green
DANGER   = "#ffb4ab"    # Error Red
TEXT     = "#d8e3fb"    # On Surface (White/Ice)
DIM      = "#84948d"    # Outline/Variant

FONT_UI  = ("Segoe UI", 10)
FONT_SM  = ("Segoe UI", 9)
FONT_LG  = ("Segoe UI", 13, "bold")
FONT_H   = ("Segoe UI", 18, "bold")
MONO     = ("Consolas", 10)
MONO_SM  = ("Consolas", 9)


# ── Queue-based log handler ───────────────────────
class QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        msg = self.format(record)
        self.q.put(msg)


# ── LED canvas widget ─────────────────────────────
class LED(tk.Canvas):
    def __init__(self, parent, size=12, **kw):
        bg_color = kw.pop("bg", CARD)
        super().__init__(parent, width=size, height=size,
                         bg=bg_color, highlightthickness=0, **kw)
        self._size = size
        self._circle = self.create_oval(1, 1, size-1, size-1, fill=DIM, outline="")

    def set(self, color):
        self.itemconfig(self._circle, fill=color)


# ── Nav Button ────────────────────────────────────
class NavButton(tk.Button):
    def __init__(self, parent, text, command, **kwargs):
        super().__init__(parent, text=text, command=command,
                         font=FONT_LG, bg=BG, fg=DIM, bd=0, anchor="w",
                         activebackground=CARD2, activeforeground=TEXT,
                         cursor="hand2", padx=20, pady=12, **kwargs)
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
        self._is_active = False

    def on_enter(self, e):
        if not self._is_active:
            self.config(bg=CARD)

    def on_leave(self, e):
        if not self._is_active:
            self.config(bg=BG)

    def set_active(self, active: bool):
        self._is_active = active
        if active:
            self.config(bg=CARD2, fg=ACCENT)
        else:
            self.config(bg=BG, fg=DIM)


# ── Main App ──────────────────────────────────────
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        
        # 1. Setup the Floating Orb (Root Window)
        self._build_orb()

        # 2. Setup the Dashboard (Toplevel Window)
        self.dashboard = tk.Toplevel(self.root)
        self.dashboard.title("BCI NavTools — Control Center")
        self.dashboard.configure(bg=BG)
        self.dashboard.geometry("900x750")
        self.dashboard.minsize(800, 600)
        self.dashboard.protocol("WM_DELETE_WINDOW", self.dashboard.withdraw)
        
        # Hide dashboard on startup
        self.dashboard.withdraw()

        self.log_q: queue.Queue = queue.Queue()
        self._install_log_handler()

        # Module state
        self._va_thread = None
        self._va: object = None
        self._gaze_thread: object = None

        self._build_dashboard_ui()
        self._poll_logs()

        # Auto-start voice assistant on launch
        self.root.after(500, self._start_va)

    # ── Orb Builder ───────────────────────────────
    def _build_orb(self):
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        
        # Remove rectangular border by setting background as transparent color
        self.root.wm_attributes("-transparentcolor", BG)
        
        # Make the orb itself slightly transparent
        self.root.wm_attributes("-alpha", 0.90)
        
        # Position orb in top-right corner
        screen_w = self.root.winfo_screenwidth()
        x = screen_w - 150
        y = 50
        self.root.geometry(f"100x100+{x}+{y}")
        self.root.configure(bg=BG)

        self.orb_canvas = tk.Canvas(self.root, width=100, height=100, bg=BG, highlightthickness=0)
        self.orb_canvas.pack()

        # Draw glowing orb ring
        self.orb_canvas.create_oval(10, 10, 90, 90, fill="", outline=ACCENT, width=3)
        try:
            self.orb_logo_img = tk.PhotoImage(file=os.path.join(os.path.dirname(__file__), "orb_logo.png"))
            self.orb_label = self.orb_canvas.create_image(50, 50, image=self.orb_logo_img, anchor="center")
        except Exception:
            self.orb_label = self.orb_canvas.create_text(50, 50, text="🎙️", font=("Segoe UI", 24), fill=ACCENT)

        # Draggable logic
        self.orb_canvas.bind("<ButtonPress-1>", self._start_move)
        self.orb_canvas.bind("<B1-Motion>", self._on_move)
        
        # Double click to OPEN dashboard instead of closing
        self.orb_canvas.bind("<Double-Button-1>", lambda e: self._handle_ui_command("open_settings"))
        # Right click to close app
        self.orb_canvas.bind("<Button-3>", lambda e: self.on_close())

        self._drag_data = {"x": 0, "y": 0}

    def _start_move(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _on_move(self, event):
        x = self.root.winfo_x() - self._drag_data["x"] + event.x
        y = self.root.winfo_y() - self._drag_data["y"] + event.y
        self.root.geometry(f"+{x}+{y}")

    def _update_orb_state(self, state: str):
        # Must be called on main thread
        def _update():
            color = ACCENT
            if state == "listening":
                color = SUCCESS
            elif state == "speaking":
                color = "#fbbf24" # Yellow
            elif state == "idle":
                color = ACCENT
            elif state == "sleeping":
                color = DIM
            
            self.orb_canvas.itemconfig(1, outline=color)
            if self.orb_canvas.type(self.orb_label) == "text":
                self.orb_canvas.itemconfig(self.orb_label, fill=color)
        self.root.after(0, _update)

    # ── Log handler ──────────────────────────────
    def _install_log_handler(self):
        handler = QueueHandler(self.log_q)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(name)-16s | %(message)s",
            datefmt="%H:%M:%S"
        ))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

    def _poll_logs(self):
        try:
            while True:
                msg = self.log_q.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_logs)

    def _append_log(self, msg: str):
        self.log_box.config(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    # ── Voice Command Callback ───────────────────
    def _handle_ui_command(self, cmd: str):
        """Called by VoiceAssistant when user speaks a UI command."""
        if cmd == "open_settings":
            self.root.after(0, self.dashboard.deiconify)
            self.root.after(0, self.dashboard.lift)
        elif cmd == "close_settings":
            self.root.after(0, self.dashboard.withdraw)
        elif cmd == "exit_app":
            self.root.after(0, self.on_close)

    # ── UI building ──────────────────────────────
    def _build_dashboard_ui(self):
        # 1. Header Bar
        hdr = tk.Frame(self.dashboard, bg=BG, pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🧠 BCI NavTools — Control Center",
                 font=FONT_H, bg=BG, fg=TEXT).pack(side="left", padx=24)
        tk.Label(hdr, text="Group No. 7 | 8th Semester",
                 font=FONT_SM, bg=BG, fg=DIM).pack(side="right", padx=24)
        tk.Frame(self.dashboard, bg=ACCENT, height=1).pack(fill="x") # 1px cyan line

        # Main Layout: Left Sidebar + Right Content Stack
        self.main_paned = tk.PanedWindow(self.dashboard, orient="horizontal", bg=BG, bd=0, sashwidth=2)
        self.main_paned.pack(fill="both", expand=True)

        # ── Sidebar ──
        self.sidebar = tk.Frame(self.main_paned, bg=BG, width=220)
        self.sidebar.pack_propagate(False)
        self.main_paned.add(self.sidebar, minsize=200)

        # Nav Buttons
        tk.Label(self.sidebar, text="MODULES", font=MONO_SM, bg=BG, fg=DIM, anchor="w").pack(fill="x", padx=20, pady=(20, 8))
        
        self.nav_va = NavButton(self.sidebar, "🎙️ Voice Assistant", lambda: self._show_page("va"))
        self.nav_va.pack(fill="x")
        
        self.nav_gaze = NavButton(self.sidebar, "👁️ Gaze Tracker", lambda: self._show_page("gaze"))
        self.nav_gaze.pack(fill="x")

        # Hide Dashboard Button
        tk.Frame(self.sidebar, bg=CARD, height=1).pack(fill="x", pady=20)
        NavButton(self.sidebar, "✖ Hide Settings", lambda: self.dashboard.withdraw()).pack(fill="x")

        # Exit App Button
        NavButton(self.sidebar, "⏻ Exit Application", lambda: self.on_close()).pack(fill="x", side="bottom", pady=20)

        # ── Right Side Split: Content (Top) & Terminal (Bottom) ──
        self.right_paned = tk.PanedWindow(self.main_paned, orient="vertical", bg=BG, bd=0, sashwidth=2)
        self.main_paned.add(self.right_paned)

        # Pages Container (Top)
        self.pages_container = tk.Frame(self.right_paned, bg=BG)
        self.right_paned.add(self.pages_container, minsize=250)

        # The Pages
        self.frames = {}
        self.frames["va"] = self._create_va_page(self.pages_container)
        self.frames["gaze"] = self._create_gaze_page(self.pages_container)

        for f in self.frames.values():
            f.grid(row=0, column=0, sticky="nsew")
        self.pages_container.grid_rowconfigure(0, weight=1)
        self.pages_container.grid_columnconfigure(0, weight=1)

        # Terminal (Bottom)
        self.term_frame = tk.Frame(self.right_paned, bg=TERMINAL)
        self.right_paned.add(self.term_frame, minsize=150)

        term_hdr = tk.Frame(self.term_frame, bg=TERMINAL, pady=6)
        term_hdr.pack(fill="x")
        tk.Label(term_hdr, text="📋 LIVE LOG", font=MONO, bg=TERMINAL, fg=DIM).pack(side="left", padx=16)
        tk.Button(term_hdr, text="CLEAR", font=MONO_SM, bg=TERMINAL, fg=DIM,
                  bd=0, activebackground=CARD, activeforeground=TEXT,
                  cursor="hand2", command=self._clear_log).pack(side="right", padx=16)
        
        tk.Frame(self.term_frame, bg=CARD2, height=1).pack(fill="x")

        self.log_box = tk.Text(self.term_frame, font=MONO, bg=TERMINAL, fg=SUCCESS,
                               insertbackground=ACCENT, relief="flat", bd=0,
                               state="disabled", wrap="word", padx=16, pady=10)
        self.log_box.pack(fill="both", expand=True)

        # Show initial page
        self._show_page("va")

    def _show_page(self, page_name):
        self.nav_va.set_active(page_name == "va")
        self.nav_gaze.set_active(page_name == "gaze")
        frame = self.frames[page_name]
        frame.tkraise()

    def _clear_log(self):
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")

    # ── Page Builders ─────────────────────────────
    def _create_va_page(self, parent):
        f = tk.Frame(parent, bg=BG)
        
        card = tk.Frame(f, bg=CARD, highlightbackground=CARD2, highlightthickness=1)
        card.pack(fill="both", expand=False, padx=40, pady=40)

        # Header
        hdr = tk.Frame(card, bg=CARD, pady=20, padx=24)
        hdr.pack(fill="x")
        
        self.led_va = LED(hdr, bg=CARD)
        self.led_va.pack(side="left", padx=(0, 10))
        
        tk.Label(hdr, text="Voice Assistant (Jim)", font=FONT_H, bg=CARD, fg=TEXT).pack(side="left")
        
        self.lbl_status_va = tk.Label(hdr, text="○ STOPPED", font=MONO, bg=CARD, fg=DIM)
        self.lbl_status_va.pack(side="right")

        tk.Frame(card, bg=CARD2, height=1).pack(fill="x")

        # Controls
        ctrls = tk.Frame(card, bg=CARD, pady=24, padx=24)
        ctrls.pack(fill="x")

        tk.Label(ctrls, text="COM PORT", font=MONO_SM, bg=CARD, fg=DIM).grid(row=0, column=0, sticky="w", pady=(0,4))
        self._va_port = tk.StringVar(value="COM7")
        ports = self._list_ports()
        cb = ttk.Combobox(ctrls, textvariable=self._va_port, values=ports, width=15, font=MONO)
        cb.grid(row=1, column=0, sticky="w", padx=(0, 32))

        self._va_attention = tk.BooleanVar(value=False)
        tk.Checkbutton(ctrls, text="Attention Gating", variable=self._va_attention,
                       font=FONT_UI, bg=CARD, fg=TEXT, selectcolor=BG, activebackground=CARD, activeforeground=ACCENT
                       ).grid(row=1, column=1, sticky="w")

        # Buttons
        btns = tk.Frame(card, bg=CARD, pady=24, padx=24)
        btns.pack(fill="x")

        self.btn_va_start = tk.Button(btns, text="▶ START", font=MONO, bg=BG, fg=ACCENT, 
                                      highlightbackground=ACCENT, highlightthickness=1, bd=0,
                                      padx=24, pady=8, cursor="hand2", command=self._start_va)
        self.btn_va_start.pack(side="left", padx=(0, 16))

        self.btn_va_stop = tk.Button(btns, text="■ STOP", font=MONO, bg=BG, fg=DIM, 
                                     highlightbackground=DIM, highlightthickness=1, bd=0, state="disabled",
                                     padx=24, pady=8, cursor="hand2", command=self._stop_va)
        self.btn_va_stop.pack(side="left")

        self._ui_sync_va(False)
        return f

    def _create_gaze_page(self, parent):
        f = tk.Frame(parent, bg=BG)
        
        card = tk.Frame(f, bg=CARD, highlightbackground=CARD2, highlightthickness=1)
        card.pack(fill="both", expand=False, padx=40, pady=40)

        # Header
        hdr = tk.Frame(card, bg=CARD, pady=20, padx=24)
        hdr.pack(fill="x")
        
        self.led_gaze = LED(hdr, bg=CARD)
        self.led_gaze.pack(side="left", padx=(0, 10))
        
        tk.Label(hdr, text="Gaze Tracker", font=FONT_H, bg=CARD, fg=TEXT).pack(side="left")
        
        self.lbl_status_gaze = tk.Label(hdr, text="○ STOPPED", font=MONO, bg=CARD, fg=DIM)
        self.lbl_status_gaze.pack(side="right")

        tk.Frame(card, bg=CARD2, height=1).pack(fill="x")

        # Controls
        ctrls = tk.Frame(card, bg=CARD, pady=24, padx=24)
        ctrls.pack(fill="x")

        tk.Label(ctrls, text="CAMERA", font=MONO_SM, bg=CARD, fg=DIM).grid(row=0, column=0, sticky="w", pady=(0,4))
        self._gaze_cam = tk.IntVar(value=0)
        ttk.Spinbox(ctrls, from_=0, to=5, textvariable=self._gaze_cam, width=8, font=MONO).grid(row=1, column=0, sticky="w", padx=(0, 32))

        tk.Label(ctrls, text="SMOOTHING", font=MONO_SM, bg=CARD, fg=DIM).grid(row=0, column=1, sticky="w", pady=(0,4))
        self._gaze_smooth = tk.DoubleVar(value=0.85)
        ttk.Spinbox(ctrls, from_=0.1, to=0.99, increment=0.05, textvariable=self._gaze_smooth, width=8, font=MONO).grid(row=1, column=1, sticky="w", padx=(0, 32))

        self._gaze_preview = tk.BooleanVar(value=False)
        tk.Checkbutton(ctrls, text="Preview Window", variable=self._gaze_preview,
                       font=FONT_UI, bg=CARD, fg=TEXT, selectcolor=BG, activebackground=CARD, activeforeground=ACCENT
                       ).grid(row=1, column=2, sticky="w")

        # Buttons
        btns = tk.Frame(card, bg=CARD, pady=24, padx=24)
        btns.pack(fill="x")

        self.btn_gaze_start = tk.Button(btns, text="▶ START", font=MONO, bg=BG, fg=ACCENT, 
                                        highlightbackground=ACCENT, highlightthickness=1, bd=0,
                                        padx=24, pady=8, cursor="hand2", command=self._start_gaze)
        self.btn_gaze_start.pack(side="left", padx=(0, 16))

        self.btn_gaze_stop = tk.Button(btns, text="■ STOP", font=MONO, bg=BG, fg=DIM, 
                                       highlightbackground=DIM, highlightthickness=1, bd=0, state="disabled",
                                       padx=24, pady=8, cursor="hand2", command=self._stop_gaze)
        self.btn_gaze_stop.pack(side="left")

        self._ui_sync_gaze(False)
        return f

    # ── UI State Synchronizers ────────────────────
    def _ui_sync_va(self, running: bool):
        if running:
            self.led_va.set(SUCCESS)
            self.lbl_status_va.config(text="● RUNNING", fg=SUCCESS)
            self.btn_va_start.config(state="disabled", fg=DIM, highlightbackground=DIM)
            self.btn_va_stop.config(state="normal", fg=DANGER, highlightbackground=DANGER)
            self._update_orb_state(True)
        else:
            self.led_va.set(DIM)
            self.lbl_status_va.config(text="○ STOPPED", fg=DIM)
            self.btn_va_start.config(state="normal", fg=ACCENT, highlightbackground=ACCENT)
            self.btn_va_stop.config(state="disabled", fg=DIM, highlightbackground=DIM)
            self._update_orb_state(False)

    def _ui_sync_gaze(self, running: bool):
        if running:
            self.led_gaze.set(SUCCESS)
            self.lbl_status_gaze.config(text="● RUNNING", fg=SUCCESS)
            self.btn_gaze_start.config(state="disabled", fg=DIM, highlightbackground=DIM)
            self.btn_gaze_stop.config(state="normal", fg=DANGER, highlightbackground=DANGER)
        else:
            self.led_gaze.set(DIM)
            self.lbl_status_gaze.config(text="○ STOPPED", fg=DIM)
            self.btn_gaze_start.config(state="normal", fg=ACCENT, highlightbackground=ACCENT)
            self.btn_gaze_stop.config(state="disabled", fg=DIM, highlightbackground=DIM)

    # ── Module Runners ────────────────────────────
    def _start_va(self):
        if getattr(self, "_va_running", False):
            return
        
        self._va_running = True
        try:
            from src.voice_assistant import VoiceAssistant
        except Exception as e:
            messagebox.showerror("Import Error", str(e))
            self._va_running = False
            return
            
        port = self._va_port.get().strip() or None
        attention = self._va_attention.get()  # Checkbox value directly maps to require_attention

        def _run():
            try:
                # Pass ui_callback for voice-activated dashboard
                self._va = VoiceAssistant(
                    port=port, 
                    require_attention=attention, 
                    ui_callback=self._handle_ui_command,
                    state_callback=self._update_orb_state
                )
                self.root.after(0, lambda: self._ui_sync_va(True))
                self._va.run()
            except Exception as e:
                logging.getLogger("gui").error(f"Voice Assistant error: {e}")
            finally:
                self._va_running = False
                self.root.after(0, lambda: self._ui_sync_va(False))

        self._va_thread = threading.Thread(target=_run, daemon=True, name="VA")
        self._va_thread.start()

    def _stop_va(self):
        if self._va:
            self._va.stop()
        self._va_running = False
        self._ui_sync_va(False)

    def _start_gaze(self):
        if getattr(self, "_gaze_running", False):
            return
            
        self._gaze_running = True
        try:
            from src.gaze_tracker import GazeTracker
        except Exception as e:
            messagebox.showerror("Import Error", str(e))
            self._gaze_running = False
            return

        def _run():
            try:
                self._gaze_thread = GazeTracker(
                    camera_id=self._gaze_cam.get(),
                    smoothing=self._gaze_smooth.get(),
                    show_preview=self._gaze_preview.get(),
                )
                self.root.after(0, lambda: self._ui_sync_gaze(True))
                self._gaze_thread.start()
                self._gaze_thread.join()
            except Exception as e:
                logging.getLogger("gui").error(f"Gaze Tracker error: {e}")
            finally:
                self._gaze_running = False
                self.root.after(0, lambda: self._ui_sync_gaze(False))

        threading.Thread(target=_run, daemon=True, name="GazeStarter").start()

    def _stop_gaze(self):
        if self._gaze_thread:
            self._gaze_thread.stop()
        self._gaze_running = False
        self._ui_sync_gaze(False)

    # ── Helpers ───────────────────────────────────
    def _list_ports(self):
        try:
            import serial.tools.list_ports
            return [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            return ["COM7"]

    def on_close(self):
        self._stop_va()
        self._stop_gaze()
        self.root.destroy()


# ── Entry point ───────────────────────────────────
def main():
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)

    try:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=CARD2, background=CARD2,
                        foreground=TEXT, selectbackground=CARD, arrowcolor=ACCENT, borderwidth=0)
        style.configure("TSpinbox", fieldbackground=CARD2, background=CARD2,
                        foreground=TEXT, arrowcolor=ACCENT, borderwidth=0)
    except Exception:
        pass

    root.mainloop()


if __name__ == "__main__":
    main()
