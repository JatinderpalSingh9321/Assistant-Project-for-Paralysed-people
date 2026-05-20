"""
BCI NavTools — Control Center
==============================
Unified Tkinter GUI for the BCI assistive control system.

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

# ── Colours (Neural Interface Design System) ──────
BG       = "#081425"  # Deep space navy
CARD     = "#111c2d"  # Surface container low
CARD2    = "#152031"  # Surface container
BORDER   = "#1f2a3c"  # Surface container high (for borders)
ACCENT   = "#00f5c8"  # Primary Cyan-Green (active states)
ACCENT2  = "#006b56"  # Inverse primary
SUCCESS  = "#a3e635"  # Terminal green
DANGER   = "#ffb4ab"  # Error red
WARNING  = "#ffdad6"  # On-error container
TEXT     = "#d8e3fb"  # On-surface
DIM      = "#b9cac3"  # On-surface variant
FONT     = ("Inter", 10)
FONT_SM  = ("Inter", 9)
FONT_LG  = ("Inter", 13, "bold")
FONT_H   = ("Inter", 16, "bold")
MONO     = ("JetBrains Mono", 9)


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
    def __init__(self, parent, size=14, **kw):
        super().__init__(parent, width=size, height=size,
                         bg=CARD, highlightthickness=0, **kw)
        self._size = size
        self._circle = self.create_oval(2, 2, size-2, size-2, fill=DANGER, outline="")

    def set(self, color):
        self.itemconfig(self._circle, fill=color)


# ── Module card ───────────────────────────────────
class ModuleCard(tk.Frame):
    def __init__(self, parent, title, icon, on_start, on_stop, controls=None):
        super().__init__(parent, bg=CARD, bd=0, pady=0)
        self.columnconfigure(0, weight=1)

        # Header row
        hdr = tk.Frame(self, bg=CARD)
        hdr.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
        hdr.columnconfigure(1, weight=1)

        self.led = LED(hdr)
        self.led.grid(row=0, column=0, padx=(0, 8))

        tk.Label(hdr, text=f"{icon}  {title}", font=FONT_LG,
                 bg=CARD, fg=TEXT).grid(row=0, column=1, sticky="w")

        self.status_lbl = tk.Label(hdr, text="Stopped", font=FONT_SM,
                                   bg=CARD, fg=DIM)
        self.status_lbl.grid(row=0, column=2, padx=(8, 0))

        # Controls row
        ctrl_frame = tk.Frame(self, bg=CARD)
        ctrl_frame.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 4))

        if controls:
            controls(ctrl_frame)

        # Buttons
        btn_frame = tk.Frame(self, bg=CARD)
        btn_frame.grid(row=2, column=0, sticky="ew", padx=18, pady=(4, 14))

        self.btn_start = tk.Button(btn_frame, text="▶  Start",
                                   font=FONT, bg=ACCENT, fg=TEXT,
                                   activebackground="#6d28d9", activeforeground=TEXT,
                                   relief="flat", padx=16, pady=6,
                                   cursor="hand2", command=on_start)
        self.btn_start.pack(side="left", padx=(0, 8))

        self.btn_stop = tk.Button(btn_frame, text="■  Stop",
                                  font=FONT, bg=CARD2, fg=DIM,
                                  activebackground=DANGER, activeforeground=TEXT,
                                  relief="flat", padx=16, pady=6,
                                  cursor="hand2", state="disabled", command=on_stop)
        self.btn_stop.pack(side="left")

        # Separator
        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.grid(row=3, column=0, sticky="ew")

    def set_running(self, running: bool):
        if running:
            self.led.set(SUCCESS)
            self.status_lbl.config(text="Running", fg=SUCCESS)
            self.btn_start.config(state="disabled", bg=CARD2, fg=DIM)
            self.btn_stop.config(state="normal", bg=DANGER, fg=TEXT)
        else:
            self.led.set(DANGER)
            self.status_lbl.config(text="Stopped", fg=DIM)
            self.btn_start.config(state="normal", bg=ACCENT, fg=TEXT)
            self.btn_stop.config(state="disabled", bg=CARD2, fg=DIM)


# ── Main App ──────────────────────────────────────
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("BCI NavTools — Control Center")
        self.root.configure(bg=BG)
        self.root.geometry("780x820")
        self.root.minsize(680, 680)
        self.root.resizable(True, True)

        self.log_q: queue.Queue = queue.Queue()
        self._install_log_handler()

        # Module state
        self._va_thread = None
        self._va: object = None
        self._gaze_thread: object = None
        self._eog_thread = None

        self._build_ui()
        self._poll_logs()

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

    # ── UI building ──────────────────────────────
    def _build_ui(self):
        # Title bar
        title_bar = tk.Frame(self.root, bg=CARD, pady=14)
        title_bar.pack(fill="x")
        tk.Label(title_bar, text="🧠  BCI NavTools — Control Center",
                 font=FONT_H, bg=CARD, fg=TEXT).pack(side="left", padx=22)
        tk.Label(title_bar, text="Group No. 7 | 8th Semester",
                 font=FONT_SM, bg=CARD, fg=DIM).pack(side="right", padx=22)

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        # Scrollable module area
        canvas_frame = tk.Frame(self.root, bg=BG)
        canvas_frame.pack(fill="both", expand=False)

        self._modules_canvas = tk.Canvas(canvas_frame, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical",
                                 command=self._modules_canvas.yview)
        self._modules_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._modules_canvas.pack(side="left", fill="both", expand=True)

        self._inner = tk.Frame(self._modules_canvas, bg=BG)
        self._canvas_win = self._modules_canvas.create_window(
            (0, 0), window=self._inner, anchor="nw")

        self._inner.bind("<Configure>", self._on_inner_configure)
        self._modules_canvas.bind("<Configure>", self._on_canvas_configure)

        # Module cards
        self._build_voice_card()
        self._build_gaze_card()
        self._build_eog_card()

        # Force canvas to fit ~3 cards
        self._modules_canvas.config(height=480)

        # Log area
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")
        log_header = tk.Frame(self.root, bg=CARD, pady=8)
        log_header.pack(fill="x")
        tk.Label(log_header, text="📋  Live Log", font=("Segoe UI", 11, "bold"),
                 bg=CARD, fg=TEXT).pack(side="left", padx=16)
        tk.Button(log_header, text="Clear", font=FONT_SM, bg=CARD2, fg=DIM,
                  relief="flat", padx=10, pady=3, cursor="hand2",
                  command=self._clear_log).pack(side="right", padx=12)

        self.log_box = tk.Text(self.root, font=MONO, bg="#040e1f", fg=SUCCESS,
                               insertbackground=ACCENT, relief="flat",
                               state="disabled", wrap="word", padx=10, pady=8)
        self.log_box.pack(fill="both", expand=True, padx=0, pady=0)

    def _on_inner_configure(self, event):
        self._modules_canvas.configure(
            scrollregion=self._modules_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._modules_canvas.itemconfig(self._canvas_win, width=event.width)

    def _clear_log(self):
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")

    # ── Voice Assistant card ──────────────────────
    def _build_voice_card(self):
        def controls(f):
            # COM port row
            tk.Label(f, text="COM Port:", font=FONT_SM, bg=CARD, fg=DIM
                     ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
            self._va_port = tk.StringVar(value="COM7")
            ports = self._list_ports()
            cb = ttk.Combobox(f, textvariable=self._va_port, values=ports,
                              width=10, font=FONT_SM, state="readonly" if ports else "normal")
            cb.grid(row=0, column=1, sticky="w", padx=(0, 16))

            # attention gate
            self._va_attention = tk.BooleanVar(value=False)
            tk.Checkbutton(f, text="Require attention gating", variable=self._va_attention,
                           font=FONT_SM, bg=CARD, fg=DIM,
                           selectcolor=CARD2, activebackground=CARD,
                           activeforeground=TEXT).grid(row=0, column=2, sticky="w")

        self._va_card = ModuleCard(
            self._inner, "Voice Assistant (Jim)", "🎙️",
            on_start=self._start_va, on_stop=self._stop_va,
            controls=controls
        )
        self._va_card.pack(fill="x", padx=16, pady=(14, 0))

    def _start_va(self):
        try:
            from src.voice_assistant import VoiceAssistant
        except Exception as e:
            messagebox.showerror("Import Error", str(e))
            return
        port = self._va_port.get().strip() or None
        attention = not self._va_attention.get()  # flag means "no attention required"

        def _run():
            try:
                self._va = VoiceAssistant(port=port, require_attention=attention)
                self.root.after(0, lambda: self._va_card.set_running(True))
                self._va.run()
            except Exception as e:
                logging.getLogger("gui").error(f"Voice Assistant error: {e}")
            finally:
                self.root.after(0, lambda: self._va_card.set_running(False))

        self._va_thread = threading.Thread(target=_run, daemon=True, name="VA")
        self._va_thread.start()

    def _stop_va(self):
        if self._va:
            self._va.stop()
        self._va_card.set_running(False)

    # ── Gaze Tracker card ─────────────────────────
    def _build_gaze_card(self):
        def controls(f):
            tk.Label(f, text="Camera:", font=FONT_SM, bg=CARD, fg=DIM
                     ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
            self._gaze_cam = tk.IntVar(value=0)
            ttk.Spinbox(f, from_=0, to=5, textvariable=self._gaze_cam,
                        width=5, font=FONT_SM).grid(row=0, column=1, sticky="w", padx=(0, 16))

            tk.Label(f, text="Smoothing:", font=FONT_SM, bg=CARD, fg=DIM
                     ).grid(row=0, column=2, sticky="w", padx=(0, 8))
            self._gaze_smooth = tk.DoubleVar(value=0.85)
            ttk.Spinbox(f, from_=0.1, to=0.99, increment=0.05,
                        textvariable=self._gaze_smooth,
                        width=6, font=FONT_SM).grid(row=0, column=3, sticky="w", padx=(0, 16))

            self._gaze_preview = tk.BooleanVar(value=False)
            tk.Checkbutton(f, text="Preview window", variable=self._gaze_preview,
                           font=FONT_SM, bg=CARD, fg=DIM,
                           selectcolor=CARD2, activebackground=CARD,
                           activeforeground=TEXT).grid(row=0, column=4, sticky="w")

        self._gaze_card = ModuleCard(
            self._inner, "Gaze Tracker", "👁️",
            on_start=self._start_gaze, on_stop=self._stop_gaze,
            controls=controls
        )
        self._gaze_card.pack(fill="x", padx=16, pady=(8, 0))

    def _start_gaze(self):
        try:
            from src.gaze_tracker import GazeTracker
        except Exception as e:
            messagebox.showerror("Import Error", str(e))
            return

        def _run():
            try:
                self._gaze_thread = GazeTracker(
                    camera_id=self._gaze_cam.get(),
                    smoothing=self._gaze_smooth.get(),
                    show_preview=self._gaze_preview.get(),
                )
                self.root.after(0, lambda: self._gaze_card.set_running(True))
                self._gaze_thread.start()
                self._gaze_thread.join()
            except Exception as e:
                logging.getLogger("gui").error(f"Gaze Tracker error: {e}")
            finally:
                self.root.after(0, lambda: self._gaze_card.set_running(False))

        threading.Thread(target=_run, daemon=True, name="GazeStarter").start()

    def _stop_gaze(self):
        if self._gaze_thread:
            self._gaze_thread.stop()
        self._gaze_card.set_running(False)

    # ── EOG card ─────────────────────────────────
    def _build_eog_card(self):
        def controls(f):
            tk.Label(f, text="COM Port:", font=FONT_SM, bg=CARD, fg=DIM
                     ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
            self._eog_port = tk.StringVar(value="COM7")
            ports = self._list_ports()
            ttk.Combobox(f, textvariable=self._eog_port, values=ports,
                         width=10, font=FONT_SM,
                         state="readonly" if ports else "normal"
                         ).grid(row=0, column=1, sticky="w", padx=(0, 16))

            tk.Label(f, text="Mode:", font=FONT_SM, bg=CARD, fg=DIM
                     ).grid(row=0, column=2, sticky="w", padx=(0, 8))
            self._eog_mode = tk.StringVar(value="mouse")
            ttk.Combobox(f, textvariable=self._eog_mode, values=["mouse", "navtools"],
                         width=10, font=FONT_SM, state="readonly"
                         ).grid(row=0, column=3, sticky="w", padx=(0, 16))

            tk.Label(f, text="Sensitivity:", font=FONT_SM, bg=CARD, fg=DIM
                     ).grid(row=0, column=4, sticky="w", padx=(0, 8))
            self._eog_sens = tk.DoubleVar(value=2.5)
            ttk.Spinbox(f, from_=0.5, to=10.0, increment=0.5,
                        textvariable=self._eog_sens,
                        width=6, font=FONT_SM).grid(row=0, column=5, sticky="w")

        self._eog_card = ModuleCard(
            self._inner, "EOG Blink Control", "⚡",
            on_start=self._start_eog, on_stop=self._stop_eog,
            controls=controls
        )
        self._eog_card.pack(fill="x", padx=16, pady=(8, 14))

    def _start_eog(self):
        try:
            from src import navtools_eog_control as eog
        except Exception as e:
            messagebox.showerror("Import Error", str(e))
            return
        port = self._eog_port.get().strip()
        mode = self._eog_mode.get()
        sens = self._eog_sens.get()

        # Reset global flag
        eog._running = True

        def _run():
            try:
                self.root.after(0, lambda: self._eog_card.set_running(True))
                eog.run(port=port, sensitivity=sens, mode=mode,
                        debug=False, require_attention=False)
            except Exception as e:
                logging.getLogger("gui").error(f"EOG error: {e}")
            finally:
                self.root.after(0, lambda: self._eog_card.set_running(False))

        self._eog_thread = threading.Thread(target=_run, daemon=True, name="EOG")
        self._eog_thread.start()

    def _stop_eog(self):
        try:
            from src import navtools_eog_control as eog
            eog.stop_controller()
        except Exception:
            pass
        self._eog_card.set_running(False)

    # ── Helpers ───────────────────────────────────
    def _list_ports(self):
        try:
            import serial.tools.list_ports
            return [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            return ["COM7"]

    def on_close(self):
        if messagebox.askokcancel("Quit", "Stop all modules and exit?"):
            self._stop_va()
            self._stop_gaze()
            self._stop_eog()
            self.root.destroy()


# ── Entry point ───────────────────────────────────
def main():
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)

    try:
        # Apply modern ttk theme
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=CARD2, background=CARD2,
                        foreground=TEXT, selectbackground=ACCENT,
                        arrowcolor=DIM)
        style.configure("TSpinbox", fieldbackground=CARD2, background=CARD2,
                        foreground=TEXT, arrowcolor=DIM)
    except Exception:
        pass

    root.mainloop()


if __name__ == "__main__":
    main()
