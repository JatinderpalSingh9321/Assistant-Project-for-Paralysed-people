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
import traceback
import math

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
        self._base_text = text
        super().__init__(parent, text="   " + text, command=command,
                         font=FONT_LG, bg=BG, fg=DIM, bd=0, anchor="w",
                         activebackground=CARD2, activeforeground=TEXT,
                         cursor="hand2", padx=20, pady=12, **kwargs)
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
        self._is_active = False

    def on_enter(self, e):
        if not self._is_active:
            self.config(bg=CARD, fg=TEXT)

    def on_leave(self, e):
        if not self._is_active:
            self.config(bg=BG, fg=DIM)

    def set_active(self, active: bool):
        self._is_active = active
        if active:
            self.config(bg=CARD2, fg=ACCENT, text=" ┃ " + self._base_text)
        else:
            self.config(bg=BG, fg=DIM, text="   " + self._base_text)


# ── Action Button ─────────────────────────────────
class ActionButton(tk.Button):
    def __init__(self, parent, text, command, base_fg=ACCENT, **kwargs):
        self._base_fg = base_fg
        super().__init__(parent, text=text, command=command, font=MONO, bg=BG, fg=base_fg,
                         highlightbackground=base_fg, highlightthickness=1, bd=0,
                         padx=24, pady=8, cursor="hand2",
                         activebackground=CARD2, activeforeground=TEXT, **kwargs)
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)

    def on_enter(self, e):
        if str(self["state"]) != "disabled":
            self.config(bg=CARD2, fg=TEXT)

    def on_leave(self, e):
        if str(self["state"]) != "disabled":
            self.config(bg=BG, fg=self._base_fg)


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
        self.root.wm_attributes("-alpha", 0.95)
        
        # Define high-fidelity visual dimensions
        self.orb_size = 130
        self.orb_center = 65
        
        # Position orb in top-right corner
        screen_w = self.root.winfo_screenwidth()
        x = screen_w - (self.orb_size + 50)
        y = 50
        self.root.geometry(f"{self.orb_size}x{self.orb_size}+{x}+{y}")
        self.root.configure(bg=BG)

        self.orb_canvas = tk.Canvas(self.root, width=self.orb_size, height=self.orb_size, bg=BG, highlightthickness=0)
        self.orb_canvas.pack()

        # Try to load static logo image if exists
        self.orb_logo_img = None
        try:
            logo_path = os.path.join(os.path.dirname(__file__), "orb_logo.png")
            if os.path.exists(logo_path):
                self.orb_logo_img = tk.PhotoImage(file=logo_path)
        except Exception:
            pass

        # Draggable logic
        self.orb_canvas.bind("<ButtonPress-1>", self._start_move)
        self.orb_canvas.bind("<B1-Motion>", self._on_move)
        
        # Double click to OPEN dashboard instead of closing
        self.orb_canvas.bind("<Double-Button-1>", lambda e: self._handle_ui_command("open_settings"))
        # Right click to open the sleek floating settings & audio menu
        self.orb_canvas.bind("<Button-3>", self._show_quick_menu)

        self._drag_data = {"x": 0, "y": 0}
        
        # Animation & state variables
        self.orb_state = "sleeping"  # Initial state
        self._animation_time = 0.0
        self.quick_menu = None
        
        # Start the animation rendering loop
        self._animate_orb()

    def _start_move(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _on_move(self, event):
        x = self.root.winfo_x() - self._drag_data["x"] + event.x
        y = self.root.winfo_y() - self._drag_data["y"] + event.y
        self.root.geometry(f"+{x}+{y}")

    def _update_orb_state(self, state):
        # Map boolean/string states to a standard state string
        if state is True:
            target_state = "idle"
        elif state is False:
            target_state = "sleeping"
        elif isinstance(state, str):
            target_state = state.lower()
        else:
            target_state = "sleeping"

        def _update():
            self.orb_state = target_state
        self.root.after(0, _update)

    def _show_quick_menu(self, event):
        # Destroy existing menu if already open
        if hasattr(self, "quick_menu") and self.quick_menu and self.quick_menu.winfo_exists():
            self.quick_menu.destroy()
            self.quick_menu = None
            return
            
        # Position menu to the left of the orb window (width = 200)
        x = self.root.winfo_x() - 215
        y = self.root.winfo_y()
        if x < 10:
            x = self.root.winfo_x() + self.orb_size + 15 # Show to the right if near left screen edge
            
        # Create borderless transient window
        self.quick_menu = tk.Toplevel(self.root)
        self.quick_menu.overrideredirect(True)
        self.quick_menu.wm_attributes("-topmost", True)
        self.quick_menu.geometry(f"200x370+{x}+{y}")
        self.quick_menu.configure(bg="#060c15", highlightbackground="#16253b", highlightthickness=1)
        
        # Apply Windows 11 Native Rounded Corners via DWM API hooks
        try:
            import ctypes
            self.quick_menu.update_idletasks()
            hwnd = self.quick_menu.winfo_id()
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 3  # Slightly rounded corners
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(ctypes.c_int(DWMWCP_ROUND)),
                ctypes.sizeof(ctypes.c_int(DWMWCP_ROUND))
            )
        except Exception:
            pass
        
        # Close menu automatically when focus moves entirely outside this menu
        def on_focus_out(e):
            focused = self.quick_menu.focus_get()
            if focused:
                # Check if focused widget is descendant of self.quick_menu
                parent = focused
                while parent:
                    if parent == self.quick_menu:
                        return  # Focus is still inside the menu structure
                    try:
                        parent = parent.master
                    except AttributeError:
                        break
            self.quick_menu.destroy()
            self.quick_menu = None
            
        self.quick_menu.bind("<FocusOut>", on_focus_out)
        self.quick_menu.focus_set()
        
        # Frame layout inside menu
        container = tk.Frame(self.quick_menu, bg="#060c15", pady=12)
        container.pack(fill="both", expand=True, padx=12)
        
        # Helper to bind dynamic hover states
        def bind_hover(btn, normal_bg, hover_bg, normal_fg, hover_fg):
            btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg, fg=hover_fg))
            btn.bind("<Leave>", lambda e: btn.config(bg=normal_bg, fg=normal_fg))
        
        # 1. Header
        tk.Label(container, text="⚙️ JIM CONTROLS", font=("Segoe UI", 9, "bold"), bg="#060c15", fg=ACCENT).pack(pady=(0, 2))
        tk.Frame(container, bg="#16253b", height=1).pack(fill="x", pady=(2, 8))
        
        # 2. Mic Sensitivity Slider
        # Obtain current sensitivity or default to a mid-point
        current_threshold = 100
        if getattr(self, "_va", None) and hasattr(self._va, "_recognizer"):
            current_threshold = self._va._recognizer.energy_threshold
            
        # Linear scale mapping from 30 (extreme sensitivity at level 10) to 570 (at level 1)
        # Formula: threshold = 630 - v * 60 => v = (630 - threshold) / 60
        initial_val = int((630 - current_threshold) / 60)
        initial_val = max(1, min(10, initial_val))
        
        sens_label = tk.Label(container, text=f"🎤 Mic Sensitivity: {initial_val}", font=("Segoe UI", 8, "bold"), bg="#060c15", fg=TEXT)
        sens_label.pack(anchor="w", pady=(0, 2))
        
        slider_card_sens = tk.Frame(container, bg="#0d172a", padx=6, pady=4, highlightbackground="#16253b", highlightthickness=1)
        slider_card_sens.pack(fill="x", pady=(0, 8))
        
        def on_sens_change(val):
            v = int(float(val))
            sens_label.config(text=f"🎤 Mic Sensitivity: {v}")
            new_thresh = 630 - v * 60
            if getattr(self, "_va", None) and hasattr(self._va, "_recognizer"):
                self._va._recognizer.energy_threshold = new_thresh
                # Force dynamic adjustment to OFF when manually chosen
                self._va._recognizer.dynamic_energy_threshold = False
                logging.getLogger("gui").info(f"Mic sensitivity adjusted manually to level {v} (threshold: {new_thresh}, dynamic: OFF)")
                
        sens_scale = tk.Scale(slider_card_sens, from_=1, to=10, orient="horizontal",
                             bg="#0d172a", fg=TEXT, highlightthickness=0, bd=0,
                             activebackground=ACCENT, troughcolor="#060c15",
                             sliderrelief="flat", sliderlength=14, width=8,
                             showvalue=False, command=on_sens_change)
        sens_scale.set(initial_val)
        sens_scale.pack(fill="x")
        
        # 3. Voice Volume Slider
        try:
            import src.voice_assistant as va
            current_vol = getattr(va, "TTS_VOLUME", 100)
        except Exception:
            current_vol = 100
            
        vol_label = tk.Label(container, text=f"🔊 Voice Volume: {current_vol}%", font=("Segoe UI", 8, "bold"), bg="#060c15", fg=TEXT)
        vol_label.pack(anchor="w", pady=(0, 2))
        
        slider_card_vol = tk.Frame(container, bg="#0d172a", padx=6, pady=4, highlightbackground="#16253b", highlightthickness=1)
        slider_card_vol.pack(fill="x", pady=(0, 8))
        
        def on_vol_change(val):
            v = int(float(val))
            vol_label.config(text=f"🔊 Voice Volume: {v}%")
            try:
                import src.voice_assistant as va
                va.TTS_VOLUME = v
            except Exception:
                pass
                
        vol_scale = tk.Scale(slider_card_vol, from_=0, to=100, orient="horizontal",
                             bg="#0d172a", fg=TEXT, highlightthickness=0, bd=0,
                             activebackground=ACCENT, troughcolor="#060c15",
                             sliderrelief="flat", sliderlength=14, width=8,
                             showvalue=False, command=on_vol_change)
        vol_scale.set(current_vol)
        vol_scale.pack(fill="x")
        
        # 4. Soft Voice Toggle
        tk.Label(container, text="🗣️ Voice Character", font=("Segoe UI", 8), bg="#060c15", fg=DIM).pack(anchor="w", pady=(2, 2))
        
        try:
            import src.voice_assistant as va
            current_gender = getattr(va, "VOICE_GENDER", "female")
        except Exception:
            current_gender = "female"
            
        def toggle_voice():
            try:
                import src.voice_assistant as va
                if va.VOICE_GENDER == "female":
                    va.VOICE_GENDER = "male"
                    btn_voice.config(text="👨 Male (Robust)", fg=DIM, bg="#122035")
                    bind_hover(btn_voice, "#122035", "#1e3556", DIM, TEXT)
                else:
                    va.VOICE_GENDER = "female"
                    btn_voice.config(text="👩 Female (Soft)", fg=ACCENT, bg="#0d242a")
                    bind_hover(btn_voice, "#0d242a", "#12373d", ACCENT, TEXT)
            except Exception:
                pass
                
        voice_text = "👩 Female (Soft)" if current_gender == "female" else "👨 Male (Robust)"
        voice_fg = ACCENT if current_gender == "female" else DIM
        voice_bg = "#0d242a" if current_gender == "female" else "#122035"
        voice_hover = "#12373d" if current_gender == "female" else "#1e3556"
        
        btn_voice = tk.Button(container, text=voice_text, font=("Segoe UI", 9, "bold"),
                               bg=voice_bg, fg=voice_fg, activebackground=voice_hover,
                               activeforeground=TEXT, bd=0, cursor="hand2", pady=5)
        btn_voice.config(command=toggle_voice)
        btn_voice.pack(fill="x", pady=(0, 10))
        bind_hover(btn_voice, voice_bg, voice_hover, voice_fg, TEXT)
        
        # 5. Action Buttons
        btn_dash = tk.Button(container, text="🧠 Open Dashboard", font=("Segoe UI", 9, "bold"),
                             bg="#122035", fg=TEXT, activebackground="#1e3556",
                             activeforeground=ACCENT, bd=0, cursor="hand2", pady=5,
                             command=lambda: [self.quick_menu.destroy(), self._handle_ui_command("open_settings")])
        btn_dash.pack(fill="x", pady=2)
        bind_hover(btn_dash, "#122035", "#1e3556", TEXT, ACCENT)
        
        btn_exit = tk.Button(container, text="⏻ Exit Application", font=("Segoe UI", 9, "bold"),
                             bg="#231218", fg=DANGER, activebackground="#3d1a25",
                             activeforeground=TEXT, bd=0, cursor="hand2", pady=5,
                             command=lambda: [self.quick_menu.destroy(), self.on_close()])
        btn_exit.pack(fill="x", pady=(8, 0))
        bind_hover(btn_exit, "#231218", "#3d1a25", DANGER, TEXT)

    # ── High-Performance Siri Wave Animation Loop ──
    def _animate_orb(self):
        # Prevent animation running if window is destroyed
        if not self.root.winfo_exists():
            return
            
        # Schedule the next frame first to maintain smooth timing (~50 FPS)
        self.root.after(20, self._animate_orb)
        
        # Increment time parameter (phase shift & breathing speed)
        self._animation_time += 0.06
        
        # Clear the canvas for high-performance redrawing
        self.orb_canvas.delete("all")
        
        # 1. Draw glowing aura and glassmorphic backing
        self._draw_orb_background()
        
        # 2. Draw core element (static logo or dynamic vibrating microphone)
        self._draw_orb_core()
        
        # 3. Draw active mathematical voice waves
        self._draw_orb_waves()

    def _draw_orb_background(self):
        state = self.orb_state
        c = self.orb_center
        
        if state == "listening":
            glow_color = "#ff2d55"  # Neon Pink/Red
            breathe_speed = 4.0
            glow_intensity = 0.08
        elif state == "speaking":
            glow_color = "#fbbf24"  # Gold
            breathe_speed = 5.0
            glow_intensity = 0.10
        elif state == "idle":
            glow_color = "#00f5c8"  # Cyan Accent
            breathe_speed = 2.0
            glow_intensity = 0.05
        else:  # sleeping
            glow_color = "#4b6b94"  # Quiet Steel Blue
            breathe_speed = 1.0
            glow_intensity = 0.03
            
        breathe = 1.0 + glow_intensity * math.sin(self._animation_time * breathe_speed)
        
        # Concentric breathing halo
        r_outer = 53 * breathe
        self.orb_canvas.create_oval(
            c - r_outer, c - r_outer, 
            c + r_outer, c + r_outer, 
            fill="#0b1a30", outline=glow_color, width=1.5
        )
        
        # Outer physical glassmorphic bezel
        r_border = 56
        self.orb_canvas.create_oval(
            c - r_border, c - r_border, 
            c + r_border, c + r_border, 
            fill="", outline="#1e2d42", width=1
        )

    def _draw_orb_core(self):
        state = self.orb_state
        c = self.orb_center
        
        if state == "listening":
            color = "#ff2d55"
        elif state == "speaking":
            color = "#fbbf24"
        elif state == "idle":
            color = "#00f5c8"
        else:  # sleeping
            color = "#4b6b94"
            
        if self.orb_logo_img:
            self.orb_canvas.create_image(c, c, image=self.orb_logo_img, anchor="center")
            self.orb_canvas.create_oval(c - 16, c - 16, c + 16, c + 16, fill="", outline=color, width=1.5)
        else:
            # Vibrational microphone jitter
            vibrate = 0.0
            if state == "speaking":
                vibrate = 1.2 * math.sin(self._animation_time * 25.0)
            elif state == "listening":
                vibrate = 0.6 * math.sin(self._animation_time * 18.0)
                
            self._draw_vector_mic(color, vibrate)

    def _draw_vector_mic(self, color, vibrate=0.0):
        dy = vibrate
        c = self.orb_center
        # Sleek vector microphone capsule (scaled)
        self.orb_canvas.create_line(c, c - 16 + dy, c, c - 3 + dy, fill=color, width=10, capstyle="round")
        # Stand cradle
        self.orb_canvas.create_line(c - 9, c - 9 + dy, c - 9, c + dy, c, c + 5 + dy, c + 9, c + dy, c + 9, c - 9 + dy, 
                                    fill=color, width=2, smooth=True, capstyle="round")
        # Stand stem
        self.orb_canvas.create_line(c, c + 5 + dy, c, c + 13 + dy, fill=color, width=2)
        # Base horizontal plate
        self.orb_canvas.create_line(c - 5, c + 13 + dy, c + 5, c + 13 + dy, fill=color, width=2, capstyle="round")

    def _draw_orb_waves(self):
        state = self.orb_state
        
        if state == "sleeping":
            # Very slow, quiet sleep wave
            self._draw_tapered_wave(
                color="#2e4a77", 
                amplitude=2.5, 
                frequency=0.9, 
                phase_offset=self._animation_time * 0.8, 
                time_scale=1.0, 
                width=1.5
            )
        elif state == "idle":
            # Calm cyan wave and a subtle secondary wave
            self._draw_tapered_wave(
                color="#00f5c8", 
                amplitude=4.5, 
                frequency=1.2, 
                phase_offset=self._animation_time * 2.0, 
                time_scale=1.0, 
                width=2.0
            )
            self._draw_tapered_wave(
                color="#0080a8", 
                amplitude=2.5, 
                frequency=1.7, 
                phase_offset=self._animation_time * -1.5 + 3.0, 
                time_scale=1.0, 
                width=1.0
            )
        elif state == "listening":
            # Multi-layered organic Siri waveform
            p1 = self._mic_pulse(offset=0.0)
            p2 = self._mic_pulse(offset=2.0)
            p3 = self._mic_pulse(offset=4.0)
            
            # Magenta (backing wave)
            self._draw_tapered_wave(
                color="#ff2d55", 
                amplitude=16.0 * p1, 
                frequency=1.3, 
                phase_offset=self._animation_time * 3.5, 
                time_scale=1.0, 
                width=3.0
            )
            # Purple (middle wave)
            self._draw_tapered_wave(
                color="#af52de", 
                amplitude=12.0 * p2, 
                frequency=1.9, 
                phase_offset=self._animation_time * -3.0 + 1.5, 
                time_scale=1.0, 
                width=2.5
            )
            # Neon Cyan (front wave)
            self._draw_tapered_wave(
                color="#00f5c8", 
                amplitude=9.0 * p3, 
                frequency=2.4, 
                phase_offset=self._animation_time * 4.5 + 3.0, 
                time_scale=1.0, 
                width=2.0
            )
            # Amber Gold (fine accents)
            self._draw_tapered_wave(
                color="#fbbf24", 
                amplitude=5.0 * ((p1 + p2) * 0.5), 
                frequency=1.6, 
                phase_offset=self._animation_time * 2.5 + 1.0, 
                time_scale=1.0, 
                width=1.5
            )
        elif state == "speaking":
            # Rich high-frequency orange and gold speech ripples
            p = self._speech_pulse()
            
            self._draw_tapered_wave(
                color="#f97316", 
                amplitude=14.0 * p, 
                frequency=2.7, 
                phase_offset=self._animation_time * 7.5, 
                time_scale=1.0, 
                width=2.5
            )
            self._draw_tapered_wave(
                color="#fbbf24", 
                amplitude=10.0 * p, 
                frequency=3.3, 
                phase_offset=self._animation_time * -6.5 + 2.0, 
                time_scale=1.0, 
                width=2.0
            )
            self._draw_tapered_wave(
                color="#00f5c8", 
                amplitude=6.0 * p, 
                frequency=3.8, 
                phase_offset=self._animation_time * 8.5 + 4.0, 
                time_scale=1.0, 
                width=1.5
            )

    def _draw_tapered_wave(self, color, amplitude, frequency, phase_offset, time_scale, width=2.0):
        points = []
        num_points = 48
        c = self.orb_center
        
        start_x = 23
        span_x = 84
        
        for i in range(num_points):
            t_x = i / (num_points - 1)
            x = start_x + t_x * span_x
            
            # Sinusoidal modulation envelope to taper endpoints to 0
            envelope = math.sin(math.pi * t_x) ** 1.5
            
            # Generate sine pattern with time phase shift
            theta = 2.0 * math.pi * frequency * t_x + phase_offset
            y_offset = amplitude * envelope * math.sin(theta)
            
            y = float(c) + y_offset
            points.extend([x, y])
            
        self.orb_canvas.create_line(
            *points, 
            smooth=True, 
            fill=color, 
            width=width, 
            capstyle="round", 
            joinstyle="round"
        )

    def _mic_pulse(self, offset=0.0):
        t = self._animation_time * 1.4 + offset
        raw = math.sin(t) * math.cos(t * 0.55) * 0.5 + 0.5
        return 0.2 + 0.8 * raw

    def _speech_pulse(self):
        t = self._animation_time * 2.6
        raw = math.sin(t) * math.cos(t * 0.4)
        envelope = abs(raw) ** 1.1
        return 0.15 + 0.85 * envelope

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

        self._va_attention = tk.BooleanVar(value=False)
        tk.Checkbutton(ctrls, text="Attention Gating", variable=self._va_attention,
                       font=FONT_UI, bg=CARD, fg=TEXT, selectcolor=BG, activebackground=CARD, activeforeground=ACCENT
                       ).grid(row=1, column=0, sticky="w")

        # Buttons
        btns = tk.Frame(card, bg=CARD, pady=24, padx=24)
        btns.pack(fill="x")

        self.btn_va_start = ActionButton(btns, text="▶ START", base_fg=ACCENT, command=self._start_va)
        self.btn_va_start.pack(side="left", padx=(0, 16))

        self.btn_va_stop = ActionButton(btns, text="■ STOP", base_fg=DIM, state="disabled", command=self._stop_va)
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

        self.btn_gaze_start = ActionButton(btns, text="▶ START", base_fg=ACCENT, command=self._start_gaze)
        self.btn_gaze_start.pack(side="left", padx=(0, 16))

        self.btn_gaze_stop = ActionButton(btns, text="■ STOP", base_fg=DIM, state="disabled", command=self._stop_gaze)
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
            self.btn_va_stop._base_fg = DANGER
            self._update_orb_state(True)
        else:
            self.led_va.set(DIM)
            self.lbl_status_va.config(text="○ STOPPED", fg=DIM)
            self.btn_va_start.config(state="normal", fg=ACCENT, highlightbackground=ACCENT)
            self.btn_va_start._base_fg = ACCENT
            self.btn_va_stop.config(state="disabled", fg=DIM, highlightbackground=DIM)
            self.btn_va_stop._base_fg = DIM
            self._update_orb_state(False)

    def _ui_sync_gaze(self, running: bool):
        if running:
            self.led_gaze.set(SUCCESS)
            self.lbl_status_gaze.config(text="● RUNNING", fg=SUCCESS)
            self.btn_gaze_start.config(state="disabled", fg=DIM, highlightbackground=DIM)
            self.btn_gaze_stop.config(state="normal", fg=DANGER, highlightbackground=DANGER)
            self.btn_gaze_stop._base_fg = DANGER
        else:
            self.led_gaze.set(DIM)
            self.lbl_status_gaze.config(text="○ STOPPED", fg=DIM)
            self.btn_gaze_start.config(state="normal", fg=ACCENT, highlightbackground=ACCENT)
            self.btn_gaze_start._base_fg = ACCENT
            self.btn_gaze_stop.config(state="disabled", fg=DIM, highlightbackground=DIM)
            self.btn_gaze_stop._base_fg = DIM

    # ── Module Runners ────────────────────────────
    def _start_va(self):
        if getattr(self, "_va_running", False):
            return
        
        self._va_running = True
        try:
            from src.voice_assistant import VoiceAssistant
        except Exception as e:
            messagebox.showerror("Import Error",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}")
            self._va_running = False
            return
            
        attention = self._va_attention.get()  # Checkbox value directly maps to require_attention

        def _run():
            try:
                # Pass ui_callback for voice-activated dashboard
                self._va = VoiceAssistant(
                    require_attention=attention, 
                    ui_callback=self._handle_ui_command,
                    state_callback=self._update_orb_state
                )
                self.root.after(0, lambda: self._ui_sync_va(True))
                self._va.run()
            except Exception as e:
                logging.getLogger("gui").error(
                    f"Voice Assistant error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
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



    def on_close(self):
        self._stop_va()
        self._stop_gaze()
        self.root.destroy()


# ── Entry point ───────────────────────────────────
def main():
    # Enable crisp High DPI rendering natively on Windows
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2) # Per-Monitor DPI Aware v2
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1) # System DPI Aware
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

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
