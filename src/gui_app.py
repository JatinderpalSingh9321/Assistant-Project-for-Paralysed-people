"""
BCI NavTools — Control Center
==============================
Neural Interface Dashboard for Voice Assistant and Gaze Tracking.
Features a floating animated HTML Orb (pywebview, main thread) and a
voice-activated Settings Dashboard (Tkinter, background thread).

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
import traceback
from src.attention_state import attention


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


# ── JS API exposed to the orb page ───────────────
class OrbApi:
    """
    pywebview JS API.  The orb page calls these from JavaScript,
    e.g. ``pywebview.api.on_orb_double_click()``.
    """
    def __init__(self):
        self._on_double_click = None
        self._on_right_click = None

    def on_orb_double_click(self):
        if self._on_double_click:
            self._on_double_click()

    def on_orb_right_click(self):
        if self._on_right_click:
            self._on_right_click()


# ── Tkinter Dashboard (runs in its own thread) ───
class Dashboard:
    """
    Settings / control panel built with Tkinter.
    Runs its own Tk mainloop on a background thread.
    """

    def __init__(self, app: "App"):
        self._app = app
        self._root = None
        self._ready = threading.Event()

    # -- public (thread-safe) -------------------------------------------
    def start(self):
        t = threading.Thread(target=self._run, daemon=True, name="TkDashboard")
        t.start()
        self._ready.wait(timeout=5)

    def show(self):
        if self._root:
            self._root.after(0, self._do_show)

    def hide(self):
        if self._root:
            self._root.after(0, self._do_hide)

    def destroy(self):
        if self._root:
            self._root.after(0, self._root.destroy)

    def schedule(self, fn):
        """Run *fn* on the Tk thread."""
        if self._root:
            self._root.after(0, fn)

    # -- internal -------------------------------------------------------
    def _do_show(self):
        self._root.deiconify()
        self._root.attributes("-topmost", True)
        self._root.lift()
        self._root.focus_force()
        self._root.after(200, lambda: self._root.attributes("-topmost", False))

    def _do_hide(self):
        self._root.withdraw()

    def _run(self):
        self._root = tk.Tk()
        self._root.title("BCI NavTools — Control Center")
        self._root.configure(bg=BG)
        self._root.geometry("900x750")
        self._root.minsize(800, 600)
        self._root.protocol("WM_DELETE_WINDOW", self._do_hide)
        self._root.withdraw()

        try:
            style = ttk.Style()
            style.theme_use("clam")
            style.configure("TCombobox", fieldbackground=CARD2, background=CARD2,
                            foreground=TEXT, selectbackground=CARD, arrowcolor=ACCENT, borderwidth=0)
            style.configure("TSpinbox", fieldbackground=CARD2, background=CARD2,
                            foreground=TEXT, arrowcolor=ACCENT, borderwidth=0)
        except Exception:
            pass

        self._build_ui()
        self._poll_logs()

        self._ready.set()

        # Auto-start voice assistant
        self._root.after(500, self._app._start_va)

        self._root.mainloop()

    # ── UI building ──────────────────────────────
    def _build_ui(self):
        root = self._root

        # Header Bar
        hdr = tk.Frame(root, bg=BG, pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🧠 BCI NavTools — Control Center",
                 font=FONT_H, bg=BG, fg=TEXT).pack(side="left", padx=24)
        tk.Label(hdr, text="Group No. 7 | 8th Semester",
                 font=FONT_SM, bg=BG, fg=DIM).pack(side="right", padx=24)
        tk.Frame(root, bg=ACCENT, height=1).pack(fill="x")

        # Main Layout
        self.main_paned = tk.PanedWindow(root, orient="horizontal", bg=BG, bd=0, sashwidth=2)
        self.main_paned.pack(fill="both", expand=True)

        # Sidebar
        sidebar = tk.Frame(self.main_paned, bg=BG, width=220)
        sidebar.pack_propagate(False)
        self.main_paned.add(sidebar, minsize=200)

        tk.Label(sidebar, text="MODULES", font=MONO_SM, bg=BG, fg=DIM, anchor="w").pack(fill="x", padx=20, pady=(20, 8))
        self.nav_va = NavButton(sidebar, "🎙️ Voice Assistant", lambda: self._show_page("va"))
        self.nav_va.pack(fill="x")
        self.nav_gaze = NavButton(sidebar, "👁️ Gaze Tracker", lambda: self._show_page("gaze"))
        self.nav_gaze.pack(fill="x")
        self.nav_gen = NavButton(sidebar, "⚙️ General Settings", lambda: self._show_page("gen"))
        self.nav_gen.pack(fill="x")

        tk.Frame(sidebar, bg=CARD, height=1).pack(fill="x", pady=20)
        NavButton(sidebar, "✖ Hide Settings", lambda: self._do_hide()).pack(fill="x")
        NavButton(sidebar, "⏻ Exit Application", lambda: self._app.on_close()).pack(fill="x", side="bottom", pady=20)

        # Right side
        right_paned = tk.PanedWindow(self.main_paned, orient="vertical", bg=BG, bd=0, sashwidth=2)
        self.main_paned.add(right_paned)

        pages = tk.Frame(right_paned, bg=BG)
        right_paned.add(pages, minsize=250)

        self.frames = {}
        self.frames["va"] = self._create_va_page(pages)
        self.frames["gaze"] = self._create_gaze_page(pages)
        self.frames["gen"] = self._create_gen_page(pages)
        for f in self.frames.values():
            f.grid(row=0, column=0, sticky="nsew")
        pages.grid_rowconfigure(0, weight=1)
        pages.grid_columnconfigure(0, weight=1)

        # Terminal
        term = tk.Frame(right_paned, bg=TERMINAL)
        right_paned.add(term, minsize=150)

        term_hdr = tk.Frame(term, bg=TERMINAL, pady=6)
        term_hdr.pack(fill="x")
        tk.Label(term_hdr, text="📋 LIVE LOG", font=MONO, bg=TERMINAL, fg=DIM).pack(side="left", padx=16)
        tk.Button(term_hdr, text="CLEAR", font=MONO_SM, bg=TERMINAL, fg=DIM,
                  bd=0, activebackground=CARD, activeforeground=TEXT,
                  cursor="hand2", command=self._clear_log).pack(side="right", padx=16)
        tk.Frame(term, bg=CARD2, height=1).pack(fill="x")

        self.log_box = tk.Text(term, font=MONO, bg=TERMINAL, fg=SUCCESS,
                               insertbackground=ACCENT, relief="flat", bd=0,
                               state="disabled", wrap="word", padx=16, pady=10)
        self.log_box.pack(fill="both", expand=True)

        self._show_page("va")

    def _show_page(self, name):
        self.nav_va.set_active(name == "va")
        self.nav_gaze.set_active(name == "gaze")
        self.nav_gen.set_active(name == "gen")
        self.frames[name].tkraise()

    def _clear_log(self):
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")

    def _poll_logs(self):
        try:
            while True:
                msg = self._app.log_q.get_nowait()
                self.log_box.config(state="normal")
                self.log_box.insert("end", msg + "\n")
                self.log_box.see("end")
                self.log_box.config(state="disabled")
        except queue.Empty:
            pass
        self._root.after(100, self._poll_logs)

    # ── Page builders ────────────────────────────
    def _create_va_page(self, parent):
        f = tk.Frame(parent, bg=BG)
        card = tk.Frame(f, bg=CARD, highlightbackground=CARD2, highlightthickness=1)
        card.pack(fill="both", expand=False, padx=40, pady=40)

        hdr = tk.Frame(card, bg=CARD, pady=20, padx=24)
        hdr.pack(fill="x")
        self.led_va = LED(hdr, bg=CARD)
        self.led_va.pack(side="left", padx=(0, 10))
        tk.Label(hdr, text="Voice Assistant (Jim)", font=FONT_H, bg=CARD, fg=TEXT).pack(side="left")
        self.lbl_status_va = tk.Label(hdr, text="○ STOPPED", font=MONO, bg=CARD, fg=DIM)
        self.lbl_status_va.pack(side="right")

        tk.Frame(card, bg=CARD2, height=1).pack(fill="x")

        ctrls = tk.Frame(card, bg=CARD, pady=24, padx=24)
        ctrls.pack(fill="x")
        self._va_attention = tk.BooleanVar(value=False)
        tk.Checkbutton(ctrls, text="Attention Gating", variable=self._va_attention,
                       font=FONT_UI, bg=CARD, fg=TEXT, selectcolor=BG,
                       activebackground=CARD, activeforeground=ACCENT).grid(row=1, column=0, sticky="w")

        btns = tk.Frame(card, bg=CARD, pady=24, padx=24)
        btns.pack(fill="x")
        self.btn_va_start = tk.Button(btns, text="▶ START", font=MONO, bg=BG, fg=ACCENT,
                                      highlightbackground=ACCENT, highlightthickness=1, bd=0,
                                      padx=24, pady=8, cursor="hand2", command=self._app._start_va)
        self.btn_va_start.pack(side="left", padx=(0, 16))
        self.btn_va_stop = tk.Button(btns, text="■ STOP", font=MONO, bg=BG, fg=DIM,
                                     highlightbackground=DIM, highlightthickness=1, bd=0, state="disabled",
                                     padx=24, pady=8, cursor="hand2", command=self._app._stop_va)
        self.btn_va_stop.pack(side="left")

        self.ui_sync_va(False)
        return f

    def _create_gaze_page(self, parent):
        f = tk.Frame(parent, bg=BG)
        card = tk.Frame(f, bg=CARD, highlightbackground=CARD2, highlightthickness=1)
        card.pack(fill="both", expand=False, padx=40, pady=40)

        hdr = tk.Frame(card, bg=CARD, pady=20, padx=24)
        hdr.pack(fill="x")
        self.led_gaze = LED(hdr, bg=CARD)
        self.led_gaze.pack(side="left", padx=(0, 10))
        tk.Label(hdr, text="Gaze Tracker", font=FONT_H, bg=CARD, fg=TEXT).pack(side="left")
        self.lbl_status_gaze = tk.Label(hdr, text="○ STOPPED", font=MONO, bg=CARD, fg=DIM)
        self.lbl_status_gaze.pack(side="right")

        tk.Frame(card, bg=CARD2, height=1).pack(fill="x")

        ctrls = tk.Frame(card, bg=CARD, pady=24, padx=24)
        ctrls.pack(fill="x")
        tk.Label(ctrls, text="CAMERA", font=MONO_SM, bg=CARD, fg=DIM).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._gaze_cam = tk.IntVar(value=0)
        ttk.Spinbox(ctrls, from_=0, to=5, textvariable=self._gaze_cam, width=8, font=MONO).grid(row=1, column=0, sticky="w", padx=(0, 32))
        tk.Label(ctrls, text="SMOOTHING", font=MONO_SM, bg=CARD, fg=DIM).grid(row=0, column=1, sticky="w", pady=(0, 4))
        self._gaze_smooth = tk.DoubleVar(value=0.85)
        ttk.Spinbox(ctrls, from_=0.1, to=0.99, increment=0.05, textvariable=self._gaze_smooth, width=8, font=MONO).grid(row=1, column=1, sticky="w", padx=(0, 32))
        self._gaze_preview = tk.BooleanVar(value=False)
        tk.Checkbutton(ctrls, text="Preview Window", variable=self._gaze_preview,
                       font=FONT_UI, bg=CARD, fg=TEXT, selectcolor=BG,
                       activebackground=CARD, activeforeground=ACCENT).grid(row=1, column=2, sticky="w")

        btns = tk.Frame(card, bg=CARD, pady=24, padx=24)
        btns.pack(fill="x")
        self.btn_gaze_start = tk.Button(btns, text="▶ START", font=MONO, bg=BG, fg=ACCENT,
                                        highlightbackground=ACCENT, highlightthickness=1, bd=0,
                                        padx=24, pady=8, cursor="hand2", command=self._app._start_gaze)
        self.btn_gaze_start.pack(side="left", padx=(0, 16))
        self.btn_gaze_stop = tk.Button(btns, text="■ STOP", font=MONO, bg=BG, fg=DIM,
                                       highlightbackground=DIM, highlightthickness=1, bd=0, state="disabled",
                                       padx=24, pady=8, cursor="hand2", command=self._app._stop_gaze)
        self.btn_gaze_stop.pack(side="left")

        self.ui_sync_gaze(False)
        return f

    def _create_gen_page(self, parent):
        f = tk.Frame(parent, bg=BG)
        card = tk.Frame(f, bg=CARD, highlightbackground=CARD2, highlightthickness=1)
        card.pack(fill="both", expand=False, padx=40, pady=40)

        # Header section
        hdr = tk.Frame(card, bg=CARD, pady=20, padx=24)
        hdr.pack(fill="x")
        self.led_gen = LED(hdr, bg=CARD)
        self.led_gen.pack(side="left", padx=(0, 10))
        self.led_gen.set(ACCENT)
        tk.Label(hdr, text="General Settings", font=FONT_H, bg=CARD, fg=TEXT).pack(side="left")
        
        tk.Frame(card, bg=CARD2, height=1).pack(fill="x")

        # Controls Section
        ctrls = tk.Frame(card, bg=CARD, pady=24, padx=24)
        ctrls.pack(fill="x")

        # Voice Profile Dropdown
        tk.Label(ctrls, text="VOICE PROFILE", font=MONO_SM, bg=CARD, fg=DIM).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._gen_voice = tk.StringVar(value="Soft Female (Zira)")
        
        VOICE_MAP = {
            "Soft Female (Zira)": "zira",
            "Natural Female (Sarah)": "sarah"
        }
        
        def update_voice(*args):
            name = self._gen_voice.get()
            val = VOICE_MAP.get(name, "zira")
            attention.voice_name = val
        self._gen_voice.trace_add("write", update_voice)
        
        voice_cb = ttk.Combobox(ctrls, textvariable=self._gen_voice, values=list(VOICE_MAP.keys()), state="readonly", font=FONT_UI, width=22)
        voice_cb.grid(row=1, column=0, sticky="w", padx=(0, 32), pady=(0, 20))

        # Speaking Speed
        tk.Label(ctrls, text="SPEAKING SPEED", font=MONO_SM, bg=CARD, fg=DIM).grid(row=0, column=1, sticky="w", pady=(0, 4))
        self._gen_speed = tk.DoubleVar(value=1.0)
        
        def update_speed(*args):
            try:
                val = float(self._gen_speed.get())
                val = max(0.5, min(2.0, val))
                attention.voice_speed = val
            except ValueError:
                pass
        self._gen_speed.trace_add("write", update_speed)
        
        speed_sb = ttk.Spinbox(ctrls, from_=0.5, to=2.0, increment=0.1, textvariable=self._gen_speed, width=8, font=MONO)
        speed_sb.grid(row=1, column=1, sticky="w", padx=(0, 32), pady=(0, 20))

        # Microphone Sensitivity
        tk.Label(ctrls, text="MICROPHONE SENSITIVITY", font=MONO_SM, bg=CARD, fg=DIM).grid(row=2, column=0, sticky="w", pady=(0, 4))
        self._gen_mic = tk.IntVar(value=300)
        
        def update_mic(*args):
            try:
                val = int(self._gen_mic.get())
                val = max(50, min(1000, val))
                attention.mic_sensitivity = val
            except ValueError:
                pass
        self._gen_mic.trace_add("write", update_mic)
        
        mic_sb = ttk.Spinbox(ctrls, from_=50, to=1000, increment=50, textvariable=self._gen_mic, width=8, font=MONO)
        mic_sb.grid(row=3, column=0, sticky="w", padx=(0, 32), pady=(0, 20))

        # Info Note
        note_frame = tk.Frame(card, bg=CARD2, padx=16, pady=16)
        note_frame.pack(fill="x", padx=24, pady=(0, 24))
        
        note_icon = tk.Label(note_frame, text="💡", font=FONT_LG, bg=CARD2, fg=ACCENT)
        note_icon.pack(side="left", anchor="n", padx=(0, 8))
        
        note_text = (
            "Voice Profile determines the assistant voice using high-fidelity Kokoro-ONNX "
            "or native Windows SAPI5 engines.\n"
            "Microphone Sensitivity controls voice pick-up (lower threshold is more sensitive "
            "for soft voices; higher reduces background noise)."
        )
        note_lbl = tk.Label(note_frame, text=note_text, font=FONT_SM, bg=CARD2, fg=TEXT, justify="left", wraplength=500)
        note_lbl.pack(side="left", fill="both", expand=True)

        return f

    # ── UI Sync (must be called on Tk thread) ────
    def ui_sync_va(self, running: bool):
        if running:
            self.led_va.set(SUCCESS)
            self.lbl_status_va.config(text="● RUNNING", fg=SUCCESS)
            self.btn_va_start.config(state="disabled", fg=DIM, highlightbackground=DIM)
            self.btn_va_stop.config(state="normal", fg=DANGER, highlightbackground=DANGER)
        else:
            self.led_va.set(DIM)
            self.lbl_status_va.config(text="○ STOPPED", fg=DIM)
            self.btn_va_start.config(state="normal", fg=ACCENT, highlightbackground=ACCENT)
            self.btn_va_stop.config(state="disabled", fg=DIM, highlightbackground=DIM)

    def ui_sync_gaze(self, running: bool):
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


# ══════════════════════════════════════════════════
# Main App Coordinator
# ══════════════════════════════════════════════════
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtCore import QUrl, Qt
import sys

class OrbPage(QWebEnginePage):
    def __init__(self, app_ref, parent=None):
        super().__init__(parent)
        self.app_ref = app_ref

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if message == "ORB_DBLCLICK":
            self.app_ref.dashboard.show()
        elif message == "ORB_RIGHTCLICK":
            self.app_ref.on_close()
        elif message.startswith("ORB_DRAG:"):
            try:
                parts = message.split("ORB_DRAG:")[1].split(",")
                dx, dy = int(parts[0]), int(parts[1])
                w = self.view().window()
                w.move(w.x() + dx, w.y() + dy)
            except Exception:
                pass
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)


class App:
    def __init__(self):
        # Logging
        self.log_q: queue.Queue = queue.Queue()
        handler = QueueHandler(self.log_q)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(name)-16s | %(message)s", datefmt="%H:%M:%S"
        ))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

        # Module state
        self._va_thread = None
        self._va = None
        self._gaze_thread = None

        # ── Dashboard (Tkinter, background thread) ──
        self.dashboard = Dashboard(self)
        self.dashboard.start()

        # ── Orb (PyQt5, main thread) ──
        if not QApplication.instance():
            self.qt_app = QApplication(sys.argv)
        else:
            self.qt_app = QApplication.instance()
            
        self._orb_window = QMainWindow()
        self._orb_window.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self._orb_window.setAttribute(Qt.WA_TranslucentBackground)
        self._orb_window.resize(280, 280)
        
        try:
            import ctypes
            screen_w = ctypes.windll.user32.GetSystemMetrics(0)
            self._orb_window.move(screen_w - 320, 30)
        except Exception:
            pass

        self.webview = QWebEngineView(self._orb_window)
        self.page = OrbPage(self, self.webview)
        self.webview.setPage(self.page)
        self.webview.page().setBackgroundColor(Qt.transparent)
        
        orb_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "orb.html")
        orb_url = "file:///" + orb_path.replace("\\", "/")
        self.webview.setUrl(QUrl(orb_url))
        self.webview.resize(280, 280)
        self._orb_window.setCentralWidget(self.webview)
        
        self.webview.loadFinished.connect(self._on_orb_loaded)

    def _on_orb_loaded(self, ok):
        if not ok: return
        # Inject JavaScript to handle transparency and bridge interactions via console.log
        js = """
        document.body.style.background = 'transparent';
        document.documentElement.style.background = 'transparent';
        
        document.getElementById('orbWrap').addEventListener('dblclick', function(e) {
            e.preventDefault(); e.stopPropagation();
            console.log("ORB_DBLCLICK");
        });
        document.getElementById('orbWrap').addEventListener('contextmenu', function(e) {
            e.preventDefault(); e.stopPropagation();
            console.log("ORB_RIGHTCLICK");
        });
        
        let isDragging = false;
        let startX, startY;
        document.getElementById('orbWrap').addEventListener('mousedown', function(e) {
            if(e.button === 0) { isDragging = true; startX = e.screenX; startY = e.screenY; }
        });
        document.addEventListener('mousemove', function(e) {
            if(isDragging) {
                let dx = e.screenX - startX;
                let dy = e.screenY - startY;
                console.log("ORB_DRAG:" + dx + "," + dy);
                startX = e.screenX; startY = e.screenY;
            }
        });
        document.addEventListener('mouseup', function(e) { isDragging = false; });
        """
        self.webview.page().runJavaScript(js)
        self._update_orb_state("idle")

    def set_orb_state(self, state: str):
        if hasattr(self, 'webview'):
            self.webview.page().runJavaScript(f"setOrbState('{state}')")
            
    def _update_orb_state(self, state):
        """
        Called by VoiceAssistant's state_callback.
        Maps VA state strings to orb animation states.
        """
        state_map = {
            "idle":      "idle",
            "listening": "listening",
            "speaking":  "speaking",
            "sleeping":  "idle",
            True:        "idle",
            False:       "idle",
        }
        orb_state = state_map.get(state, "idle")
        self.set_orb_state(orb_state)
        # Also update the dashboard LED/status if it's alive
        if self.dashboard and self.dashboard._root:
            self.dashboard.schedule(
                lambda: self.dashboard.ui_sync_va(state not in (False, "idle", "sleeping"))
            )

    def _handle_ui_command(self, cmd: str):
        if cmd == "open_settings":
            self.dashboard.show()
        elif cmd == "close_settings":
            self.dashboard.hide()
        elif cmd == "exit_app":
            self.on_close()

    # ── Module runners ───────────────────────────
    def _start_va(self):
        if getattr(self, "_va_running", False):
            return
        self._va_running = True

        try:
            from src.voice_assistant import VoiceAssistant
        except Exception as e:
            logging.getLogger("gui").error(f"VA Import Error: {type(e).__name__}: {e}")
            self._va_running = False
            return

        attention = self.dashboard._va_attention.get()

        def _run():
            try:
                self._va = VoiceAssistant(
                    require_attention=attention,
                    ui_callback=self._handle_ui_command,
                    state_callback=self._update_orb_state,
                )
                self.dashboard.schedule(lambda: self.dashboard.ui_sync_va(True))
                self._update_orb_state("idle")
                self._va.run()
            except Exception as e:
                logging.getLogger("gui").error(
                    f"Voice Assistant error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            finally:
                self._va_running = False
                self.dashboard.schedule(lambda: self.dashboard.ui_sync_va(False))
                self._update_orb_state("idle")

        self._va_thread = threading.Thread(target=_run, daemon=True, name="VA")
        self._va_thread.start()

    def _stop_va(self):
        if self._va:
            self._va.stop()
        self._va_running = False
        self.dashboard.schedule(lambda: self.dashboard.ui_sync_va(False))
        self._update_orb_state("idle")

    def _start_gaze(self):
        if getattr(self, "_gaze_running", False):
            return
        self._gaze_running = True

        try:
            from src.gaze_tracker import GazeTracker
        except Exception as e:
            logging.getLogger("gui").error(f"Gaze Import Error: {e}")
            self._gaze_running = False
            return

        def _run():
            try:
                self._gaze_thread = GazeTracker(
                    camera_id=self.dashboard._gaze_cam.get(),
                    smoothing=self.dashboard._gaze_smooth.get(),
                    show_preview=self.dashboard._gaze_preview.get(),
                )
                self.dashboard.schedule(lambda: self.dashboard.ui_sync_gaze(True))
                self._gaze_thread.start()
                self._gaze_thread.join()
            except Exception as e:
                logging.getLogger("gui").error(f"Gaze Tracker error: {e}")
            finally:
                self._gaze_running = False
                self.dashboard.schedule(lambda: self.dashboard.ui_sync_gaze(False))

        threading.Thread(target=_run, daemon=True, name="GazeStarter").start()

    def _stop_gaze(self):
        if self._gaze_thread:
            self._gaze_thread.stop()
        self._gaze_running = False
        self.dashboard.schedule(lambda: self.dashboard.ui_sync_gaze(False))

    def on_close(self):
        self._stop_va()
        self._stop_gaze()
        self.dashboard.destroy()
        try:
            self._orb_window.close()
            self.qt_app.quit()
        except Exception:
            pass

    def run(self):
        self._orb_window.show()
        self.qt_app.exec_()


# ── Entry point ───────────────────────────────────
def main():
    app = App()
    app.run()


if __name__ == "__main__":
    main()
