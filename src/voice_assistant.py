"""
Jim — Interactive Voice Assistant for NavTools
=================================================
Uses Google Speech Recognition (accurate with Indian accent)
and Windows SAPI5 for speech output.

Flow:
  1. User says "wake up Jim"
  2. Jim responds: "What can I help you with today?"
  3. User speaks their command (e.g., "search for Python tutorials")
  4. Jim executes and confirms vocally
  5. Jim goes back to idle, waiting for "wake up Jim" again

Supports:
  - App launching (browser, calculator, notepad, etc.)
  - Browser search ("search for ...")
  - File Explorer search ("find file ...")
  - Tab navigation (next tab, previous tab, close tab, new tab)
  - Page navigation (go back, go forward, refresh)
  - Scrolling (scroll up/down, page up/down, go to top/bottom)
  - Link clicking ("click link", "open link")
  - Window management (close, minimize, maximize, switch window)
  - System controls (volume, screenshot, lock)

Usage (standalone):
  python -m src.voice_assistant
  python -m src.voice_assistant --no-attention

Group No. 7 | 8th Semester Major Project
"""

import argparse
import json
import os
import subprocess
import threading
import time
import urllib.parse

# pythoncom and win32com are loaded lazily inside speak() to avoid
# crashing the module if pywin32 is not installed.
import speech_recognition as sr

from src.utils import setup_logger, PROJECT_ROOT, DATA_DIR
from src.attention_state import attention

logger = setup_logger("jim")


# ──────────────────────────────────────────────
# TEXT-TO-SPEECH (Kokoro ONNX & Windows SAPI5)
# ──────────────────────────────────────────────

try:
    import sounddevice as sd
    from kokoro_onnx import Kokoro
    
    kokoro_model_path = os.path.join(PROJECT_ROOT, "models", "kokoro", "kokoro-v1.0.onnx")
    kokoro_voices_path = os.path.join(PROJECT_ROOT, "models", "kokoro", "voices-v1.0.bin")
    
    if os.path.exists(kokoro_model_path) and os.path.exists(kokoro_voices_path):
        _kokoro_tts = Kokoro(kokoro_model_path, kokoro_voices_path)
        logger.info("Kokoro TTS initialized successfully.")
    else:
        _kokoro_tts = None
        logger.warning("Kokoro TTS model files not found. Falling back to SAPI5.")
except ImportError:
    _kokoro_tts = None
    logger.warning("kokoro_onnx or sounddevice not installed. Falling back to SAPI5.")
except Exception as e:
    _kokoro_tts = None
    logger.error(f"Error initializing Kokoro TTS: {e}")

_speak_lock = threading.Lock()

def speak(text: str):
    """Speak text using Kokoro TTS (high quality) or fallback to Windows SAPI5."""
    logger.info(f"  [Jim]: \"{text}\"")
    
    with _speak_lock:
        if _kokoro_tts is not None:
            try:
                # Use a clear American Male voice by default
                samples, sample_rate = _kokoro_tts.create(text, voice="am_michael", speed=1.0, lang="en-us")
                sd.play(samples, sample_rate)
                sd.wait()
                return
            except Exception as e:
                logger.error(f"Kokoro TTS generation failed, falling back to SAPI5: {e}")
                # Fallthrough to SAPI5...

        # Try direct COM first for 0ms start latency fallback
        try:
            import pythoncom
            import win32com.client
            try:
                pythoncom.CoInitialize()
            except Exception:
                pass # Already initialized in this thread
            
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            voice.Speak(text)
            return
        except ImportError:
            logger.debug("pywin32 not installed, skipping direct SAPI5 COM speech.")
        except Exception as e:
            logger.debug(f"Direct SAPI5 COM speech failed, falling back to PowerShell: {e}")

        # Fallback to PowerShell subprocess
        safe = text.replace("'", "''")
        cmd = (
            f"powershell -Command \""
            f"Add-Type -AssemblyName System.Speech; "
            f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Rate = 1; "
            f"$s.Speak('{safe}')\""
        )
        try:
            subprocess.run(cmd, shell=True, timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.error(f"  TTS error: {e}")


# ──────────────────────────────────────────────
# STATIC COMMAND DEFINITIONS
# ──────────────────────────────────────────────

VOICE_COMMANDS = {
    # ── App Launches — Browsers & Web ──
    "open browser":        ("launch", "start https://www.google.com", "Opening web browser"),
    "open chrome":         ("launch", "start chrome", "Opening Chrome"),
    "open google":         ("launch", "start https://www.google.com", "Opening Google"),
    "open youtube":        ("launch", "start https://www.youtube.com", "Opening YouTube"),
    "open edge":           ("launch", "start msedge", "Opening Microsoft Edge"),
    "open firefox":        ("launch", "start firefox", "Opening Firefox"),

    # ── App Launches — Windows Built-in ──
    "open calculator":     ("launch", "calc", "Opening calculator"),
    "open notepad":        ("launch", "notepad", "Opening notepad"),
    "open settings":       ("launch", "start ms-settings:", "Opening settings"),
    "open windows settings":("launch", "start ms-settings:", "Opening Windows Settings"),
    "open file explorer":  ("launch", "explorer", "Opening file explorer"),
    "open explorer":       ("launch", "explorer", "Opening file explorer"),
    "open my computer":    ("launch", "explorer ::{20D04FE0-3AEA-1069-A2D8-08002B30309D}", "Opening My Computer"),
    "open this pc":        ("launch", "explorer ::{20D04FE0-3AEA-1069-A2D8-08002B30309D}", "Opening This PC"),
    "open recycle bin":    ("launch", "explorer ::{645FF040-5081-101B-9F08-00AA002F954E}", "Opening Recycle Bin"),
    "open control panel":  ("launch", "control", "Opening Control Panel"),
    "open task manager":   ("launch", "taskmgr", "Opening Task Manager"),
    "open camera":         ("launch", "start microsoft.windows.camera:", "Opening camera"),
    "open terminal":       ("launch", "wt", "Opening terminal"),
    "open command prompt": ("launch", "cmd", "Opening Command Prompt"),
    "open powershell":     ("launch", "powershell", "Opening PowerShell"),
    "open paint":          ("launch", "mspaint", "Opening paint"),
    "open snipping tool":  ("launch", "snippingtool", "Opening Snipping Tool"),
    "open clock":          ("launch", "start ms-clock:", "Opening clock"),
    "open alarms":         ("launch", "start ms-clock:", "Opening alarms"),
    "open calendar":       ("launch", "start outlookcal:", "Opening calendar"),
    "open maps":           ("launch", "start bingmaps:", "Opening maps"),
    "open weather":        ("launch", "start bingweather:", "Opening weather"),
    "open store":          ("launch", "start ms-windows-store:", "Opening Microsoft Store"),
    "open microsoft store":("launch", "start ms-windows-store:", "Opening Microsoft Store"),
    "open mail":           ("launch", "start outlookmail:", "Opening mail"),
    "open photos":         ("launch", "start ms-photos:", "Opening Photos"),
    "open music":          ("launch", "start mswindowsmusic:", "Opening music player"),
    "open videos":         ("launch", "start mswindowsvideo:", "Opening video player"),
    "open sticky notes":   ("launch", "start ms-stickynotes:", "Opening Sticky Notes"),
    "open voice recorder": ("launch", "start ms-soundrecorder:", "Opening Voice Recorder"),
    "open recorder":       ("launch", "start ms-soundrecorder:", "Opening Voice Recorder"),
    "open magnifier":      ("launch", "magnify", "Opening Magnifier"),
    "open narrator":       ("launch", "narrator", "Opening Narrator"),
    "open device manager": ("launch", "devmgmt.msc", "Opening Device Manager"),
    "open disk management":("launch", "diskmgmt.msc", "Opening Disk Management"),
    "open system info":    ("launch", "msinfo32", "Opening System Information"),
    "open remote desktop": ("launch", "mstsc", "Opening Remote Desktop"),

    # ── App Launches — Microsoft Office ──
    "open word":           ("launch", "start winword", "Opening Microsoft Word"),
    "open excel":          ("launch", "start excel", "Opening Microsoft Excel"),
    "open powerpoint":     ("launch", "start powerpnt", "Opening PowerPoint"),
    "open outlook":        ("launch", "start outlook", "Opening Outlook"),
    "open teams":          ("launch", "start msteams:", "Opening Microsoft Teams"),
    "open onenote":        ("launch", "start onenote:", "Opening OneNote"),

    # ── App Launches — Third Party (Start Menu search) ──
    "open steam":          ("start_menu", "Steam", "Opening Steam"),
    "open discord":        ("start_menu", "Discord", "Opening Discord"),
    "open spotify":        ("start_menu", "Spotify", "Opening Spotify"),
    "open telegram":       ("start_menu", "Telegram", "Opening Telegram"),
    "open whatsapp":       ("start_menu", "WhatsApp", "Opening WhatsApp"),
    "open zoom":           ("start_menu", "Zoom", "Opening Zoom"),
    "open nvidia":         ("start_menu", "NVIDIA", "Opening NVIDIA App"),
    "open nvidia app":     ("start_menu", "NVIDIA", "Opening NVIDIA App"),
    "open geforce":        ("start_menu", "GeForce", "Opening GeForce Experience"),
    "open obs":            ("start_menu", "OBS", "Opening OBS Studio"),
    "open vlc":            ("start_menu", "VLC", "Opening VLC"),
    "open vs code":        ("start_menu", "Visual Studio Code", "Opening VS Code"),
    "open visual studio":  ("start_menu", "Visual Studio", "Opening Visual Studio"),
    "open photoshop":      ("start_menu", "Photoshop", "Opening Photoshop"),
    "open premiere":       ("start_menu", "Premiere", "Opening Premiere Pro"),
    "open blender":        ("start_menu", "Blender", "Opening Blender"),
    "open unity":          ("start_menu", "Unity", "Opening Unity"),
    "open epic games":     ("start_menu", "Epic Games", "Opening Epic Games"),
    "open brave":          ("start_menu", "Brave", "Opening Brave Browser"),
    "open opera":          ("start_menu", "Opera", "Opening Opera"),

    # ── App Launches — Folders ──
    "open downloads":      ("launch", "explorer Downloads", "Opening downloads folder"),
    "open documents":      ("launch", "explorer Documents", "Opening documents folder"),
    "open desktop":        ("launch", "explorer Desktop", "Opening desktop folder"),
    "open pictures":       ("launch", "explorer Pictures", "Opening pictures folder"),

    # ── Tab Navigation ──
    "next tab":            ("hotkey", "ctrl+tab", "Switching to next tab"),
    "previous tab":        ("hotkey", "ctrl+shift+tab", "Switching to previous tab"),
    "close tab":           ("hotkey", "ctrl+w", "Closing tab"),
    "close current tab":   ("hotkey", "ctrl+w", "Closing current tab"),
    "close this tab":      ("hotkey", "ctrl+w", "Closing this tab"),
    "new tab":             ("hotkey", "ctrl+t", "Opening new tab"),
    "open new tab":        ("hotkey", "ctrl+t", "Opening new tab"),
    "open a new tab":      ("hotkey", "ctrl+t", "Opening new tab"),
    "reopen tab":          ("hotkey", "ctrl+shift+t", "Reopening last closed tab"),

    # ── Page Navigation ──
    "go back":             ("hotkey", "alt+left", "Going back"),
    "go forward":          ("hotkey", "alt+right", "Going forward"),
    "refresh":             ("hotkey", "F5", "Refreshing page"),
    "refresh page":        ("hotkey", "F5", "Refreshing page"),
    "reload":              ("hotkey", "F5", "Reloading page"),
    "reload page":         ("hotkey", "F5", "Reloading page"),
    "go home":             ("hotkey", "alt+home", "Going to home page"),
    "address bar":         ("hotkey", "ctrl+l", "Focusing address bar"),
    "focus address bar":   ("hotkey", "ctrl+l", "Focusing address bar"),

    # ── Scrolling ──
    "scroll up":           ("scroll", "up_3", "Scrolling up"),
    "scroll down":         ("scroll", "down_3", "Scrolling down"),
    "scroll up more":      ("scroll", "up_10", "Scrolling up more"),
    "scroll down more":    ("scroll", "down_10", "Scrolling down more"),
    "scroll left":         ("scroll", "left_3", "Scrolling left"),
    "scroll right":        ("scroll", "right_3", "Scrolling right"),
    "page up":             ("hotkey", "pageup", "Page up"),
    "page down":           ("hotkey", "pagedown", "Page down"),
    "go to top":           ("hotkey", "ctrl+home", "Going to top of page"),
    "go to bottom":        ("hotkey", "ctrl+end", "Going to bottom of page"),
    "top of page":         ("hotkey", "ctrl+home", "Going to top of page"),
    "bottom of page":      ("hotkey", "ctrl+end", "Going to bottom of page"),

    # ── Click / Mouse ──
    "click":               ("mouse_click", "left", "Clicking"),
    "click here":          ("mouse_click", "left", "Clicking here"),
    "click link":          ("mouse_click", "left", "Clicking link"),
    "click the link":      ("mouse_click", "left", "Clicking the link"),
    "click that":          ("mouse_click", "left", "Clicking"),
    "click on that":       ("mouse_click", "left", "Clicking"),
    "right click":         ("mouse_click", "right", "Right clicking"),
    "double click":        ("mouse_click", "double", "Double clicking"),
    "open link":           ("mouse_click", "left", "Opening link"),
    "open the link":       ("mouse_click", "left", "Opening the link"),
    "open link in new tab": ("hotkey", "ctrl+enter", "Opening link in new tab"),
    # Positional link/result clicking (works on Google search results)
    "click first link":     ("click_nth_link", "1", "Clicking the first link"),
    "click the first link":  ("click_nth_link", "1", "Clicking the first link"),
    "click first result":   ("click_nth_link", "1", "Clicking the first result"),
    "click the first result":("click_nth_link", "1", "Clicking the first result"),
    "open first link":      ("click_nth_link", "1", "Opening the first link"),
    "open first result":    ("click_nth_link", "1", "Opening the first result"),
    "open the first link":  ("click_nth_link", "1", "Opening the first link"),
    "click second link":    ("click_nth_link", "2", "Clicking the second link"),
    "click the second link": ("click_nth_link", "2", "Clicking the second link"),
    "click second result":  ("click_nth_link", "2", "Clicking the second result"),
    "click the second result":("click_nth_link", "2", "Clicking the second result"),
    "open second link":     ("click_nth_link", "2", "Opening the second link"),
    "open the second link": ("click_nth_link", "2", "Opening the second link"),
    "click third link":     ("click_nth_link", "3", "Clicking the third link"),
    "click the third link":  ("click_nth_link", "3", "Clicking the third link"),
    "click third result":   ("click_nth_link", "3", "Clicking the third result"),
    "open third link":      ("click_nth_link", "3", "Opening the third link"),
    "click fourth link":    ("click_nth_link", "4", "Clicking the fourth link"),
    "click the fourth link": ("click_nth_link", "4", "Clicking the fourth link"),
    "click fourth result":  ("click_nth_link", "4", "Clicking the fourth result"),
    "open fourth link":     ("click_nth_link", "4", "Opening the fourth link"),
    "click fifth link":     ("click_nth_link", "5", "Clicking the fifth link"),
    "click the fifth link":  ("click_nth_link", "5", "Clicking the fifth link"),
    "click fifth result":   ("click_nth_link", "5", "Clicking the fifth result"),
    "open fifth link":      ("click_nth_link", "5", "Opening the fifth link"),
    "click last link":      ("click_nth_link", "-1", "Clicking the last link"),
    "click the last link":   ("click_nth_link", "-1", "Clicking the last link"),
    "click last result":    ("click_nth_link", "-1", "Clicking the last result"),
    "open last link":       ("click_nth_link", "-1", "Opening the last link"),
    "open the last link":   ("click_nth_link", "-1", "Opening the last link"),
    "next link":            ("hotkey", "tab", "Moving to next link"),
    "previous link":        ("hotkey", "shift+tab", "Moving to previous link"),

    # ── File Selection (in File Explorer) ──
    "open first file":      ("select_nth_file", "1_open", "Opening the first file"),
    "open the first file":  ("select_nth_file", "1_open", "Opening the first file"),
    "open second file":     ("select_nth_file", "2_open", "Opening the second file"),
    "open the second file": ("select_nth_file", "2_open", "Opening the second file"),
    "open third file":      ("select_nth_file", "3_open", "Opening the third file"),
    "open the third file":  ("select_nth_file", "3_open", "Opening the third file"),
    "open fourth file":     ("select_nth_file", "4_open", "Opening the fourth file"),
    "open the fourth file": ("select_nth_file", "4_open", "Opening the fourth file"),
    "open fifth file":      ("select_nth_file", "5_open", "Opening the fifth file"),
    "open the fifth file":  ("select_nth_file", "5_open", "Opening the fifth file"),
    "open last file":       ("select_nth_file", "-1_open", "Opening the last file"),
    "open the last file":   ("select_nth_file", "-1_open", "Opening the last file"),
    "select first file":    ("select_nth_file", "1_select", "Selecting the first file"),
    "select the first file": ("select_nth_file", "1_select", "Selecting the first file"),
    "select second file":   ("select_nth_file", "2_select", "Selecting the second file"),
    "select the second file":("select_nth_file", "2_select", "Selecting the second file"),
    "select third file":    ("select_nth_file", "3_select", "Selecting the third file"),
    "select last file":     ("select_nth_file", "-1_select", "Selecting the last file"),
    "open next file":       ("select_nth_file", "next_open", "Opening the next file"),
    "open previous file":   ("select_nth_file", "prev_open", "Opening the previous file"),
    "next file":            ("select_nth_file", "next_select", "Selecting next file"),
    "previous file":        ("select_nth_file", "prev_select", "Selecting previous file"),

    # ── File Operations (on selected file in Explorer) ──
    "open selected file":   ("hotkey", "enter", "Opening selected file"),
    "open this file":       ("hotkey", "enter", "Opening this file"),
    "open it":              ("hotkey", "enter", "Opening it"),
    "properties":           ("hotkey", "alt+enter", "Showing properties"),
    "file properties":      ("hotkey", "alt+enter", "Showing file properties"),
    "show properties":      ("hotkey", "alt+enter", "Showing properties"),
    "delete file":          ("hotkey", "delete", "Deleting file"),
    "delete this":          ("hotkey", "delete", "Deleting"),
    "delete":               ("hotkey", "delete", "Deleting"),
    "permanent delete":     ("hotkey", "shift+delete", "Permanently deleting"),
    "rename file":          ("hotkey", "F2", "Renaming file"),
    "rename":               ("hotkey", "F2", "Ready to rename"),
    "rename this":          ("hotkey", "F2", "Ready to rename"),
    "copy file":            ("hotkey", "ctrl+c", "Copied file"),
    "cut file":             ("hotkey", "ctrl+x", "Cut file"),
    "paste file":           ("hotkey", "ctrl+v", "Pasting"),
    "new folder":           ("hotkey", "ctrl+shift+n", "Creating new folder"),
    "create folder":        ("hotkey", "ctrl+shift+n", "Creating new folder"),

    # ── Close / Dismiss / Cancel ──
    "close properties":     ("hotkey", "escape", "Closing properties"),
    "close dialog":         ("hotkey", "escape", "Closing dialog"),
    "close popup":          ("hotkey", "escape", "Closing popup"),
    "close menu":           ("hotkey", "escape", "Closing menu"),
    "close this":           ("hotkey", "alt+F4", "Closing this"),
    "close it":             ("hotkey", "escape", "Closing it"),
    "dismiss":              ("hotkey", "escape", "Dismissed"),
    "cancel":               ("hotkey", "escape", "Cancelled"),
    "escape":               ("hotkey", "escape", "Escape"),
    "go back":              ("hotkey", "alt+left", "Going back"),
    "press ok":             ("hotkey", "enter", "Pressing OK"),
    "ok":                   ("hotkey", "enter", "OK"),
    "confirm":              ("hotkey", "enter", "Confirmed"),
    "press yes":            ("hotkey", "alt+y", "Pressing Yes"),
    "yes":                  ("hotkey", "alt+y", "Yes"),
    "press no":             ("hotkey", "alt+n", "Pressing No"),
    "no":                   ("hotkey", "alt+n", "No"),

    # ── Find on Page ──
    "find on page":        ("hotkey", "ctrl+f", "Opening find on page"),
    "find":                ("hotkey", "ctrl+f", "Opening find on page"),

    # ── Window Management ──
    "close window":        ("hotkey", "alt+F4", "Closing window"),
    "close this":          ("hotkey", "alt+F4", "Closing window"),
    "close this window":   ("hotkey", "alt+F4", "Closing window"),
    "minimize":            ("hotkey", "win+down", "Minimizing window"),
    "minimize window":     ("hotkey", "win+down", "Minimizing"),
    "maximize":            ("hotkey", "win+up", "Maximizing window"),
    "maximize window":     ("hotkey", "win+up", "Maximizing"),
    "switch window":       ("hotkey", "alt+tab", "Switching window"),
    "switch app":          ("hotkey", "alt+tab", "Switching app"),
    "show desktop":        ("hotkey", "win+d", "Showing desktop"),
    "snap left":           ("hotkey", "win+left", "Snapping window left"),
    "snap right":          ("hotkey", "win+right", "Snapping window right"),
    "full screen":         ("hotkey", "F11", "Toggling full screen"),

    # ── System ──
    "take screenshot":     ("hotkey", "win+shift+s", "Taking screenshot"),
    "screenshot":          ("hotkey", "win+shift+s", "Taking screenshot"),
    "lock screen":         ("hotkey", "win+l", "Locking screen"),
    "volume up":           ("hotkey", "volumeup", "Volume up"),
    "volume down":         ("hotkey", "volumedown", "Volume down"),
    "mute":                ("hotkey", "volumemute", "Toggling mute"),
    "play pause":          ("hotkey", "playpause", "Play or pause"),
    "copy":                ("hotkey", "ctrl+c", "Copied"),
    "paste":               ("hotkey", "ctrl+v", "Pasted"),
    "undo":                ("hotkey", "ctrl+z", "Undo"),
    "redo":                ("hotkey", "ctrl+y", "Redo"),
    "select all":          ("hotkey", "ctrl+a", "Selected all"),

    # ── Global Media Controls (work in any app via Windows media keys) ──
    "play":                ("hotkey", "playpause",  "Playing"),
    "pause":               ("hotkey", "playpause",  "Pausing"),
    "play pause":          ("hotkey", "playpause",  "Toggling playback"),
    "play or pause":       ("hotkey", "playpause",  "Toggling playback"),
    "toggle playback":     ("hotkey", "playpause",  "Toggling playback"),
    "next song":           ("hotkey", "nexttrack",  "Next track"),
    "next track":          ("hotkey", "nexttrack",  "Next track"),
    "previous song":       ("hotkey", "prevtrack",  "Previous track"),
    "previous track":      ("hotkey", "prevtrack",  "Previous track"),
    "skip song":           ("hotkey", "nexttrack",  "Skipping to next song"),
    "skip track":          ("hotkey", "nexttrack",  "Skipping track"),
    "go back song":        ("hotkey", "prevtrack",  "Going back one track"),

    # ── YouTube Music (focuses YT Music tab, uses its keyboard shortcuts) ──
    "play music":              ("yt_music", "play_pause", "Toggling music playback"),
    "pause music":             ("yt_music", "play_pause", "Pausing music"),
    "resume music":            ("yt_music", "play_pause", "Resuming music"),
    "play youtube music":      ("yt_music", "play_pause", "Toggling YouTube Music"),
    "pause youtube music":     ("yt_music", "play_pause", "Pausing YouTube Music"),
    "play the music":          ("yt_music", "play_pause", "Toggling YouTube Music"),
    "pause the music":         ("yt_music", "play_pause", "Pausing the music"),
    "start music":             ("yt_music", "play_pause", "Starting music"),
    "stop music":              ("yt_music", "play_pause", "Stopping music"),
    "next music":              ("yt_music", "next",       "Next song on YouTube Music"),
    "next on youtube music":   ("yt_music", "next",       "Next song on YouTube Music"),
    "previous music":          ("yt_music", "prev",       "Previous song on YouTube Music"),
    "previous on youtube music":("yt_music", "prev",      "Previous song on YouTube Music"),
    "mute music":              ("yt_music", "mute",       "Muting music"),
    "unmute music":            ("yt_music", "mute",       "Unmuting music"),
    "like this song":          ("yt_music", "like",       "Liking this song"),
    "dislike this song":       ("yt_music", "dislike",    "Disliking this song"),
    "shuffle music":           ("yt_music", "shuffle",    "Toggling shuffle"),
    "shuffle on":              ("yt_music", "shuffle",    "Toggling shuffle"),
    "volume up music":         ("yt_music", "vol_up",     "Increasing music volume"),
    "volume down music":       ("yt_music", "vol_down",   "Decreasing music volume"),
    "open youtube music":      ("launch",   "start https://music.youtube.com", "Opening YouTube Music"),

    # ── NavTools UI ──
    "go right":            ("nav", "right", "Moving right"),
    "move right":          ("nav", "right", "Moving right"),
    "next":                ("nav", "right", "Next"),
    "go left":             ("nav", "left", "Moving left"),
    "move left":           ("nav", "left", "Moving left"),
    "previous":            ("nav", "left", "Previous"),
    "select":              ("nav", "select", "Selecting"),
    "enter":               ("nav", "select", "Entering"),

    # ── Assistant ──
    "what can you do":     ("help", None, None),
    "help":                ("help", None, None),
    "help me":             ("help", None, None),
    "stop listening":      ("sleep", None, "Going to sleep. Say wake up Jim when you need me."),
    "go to sleep":         ("sleep", None, "Going to sleep. Say wake up Jim when you need me."),
    "sleep":               ("sleep", None, "Going to sleep. Say wake up Jim when you need me."),
    "close the assistant": ("stop_assistant", None, "Shutting down. Goodbye!"),
    "stop the assistant":  ("stop_assistant", None, "Shutting down. Goodbye!"),
    "turn off the assistant":("stop_assistant", None, "Shutting down. Goodbye!"),
    "turn off assistant":  ("stop_assistant", None, "Shutting down. Goodbye!"),
    "off the assistant":   ("stop_assistant", None, "Shutting down. Goodbye!"),
    "close assistant":     ("stop_assistant", None, "Shutting down. Goodbye!"),
    "stop assistant":      ("stop_assistant", None, "Shutting down. Goodbye!"),
    "exit application":    ("stop_assistant", None, "Shutting down. Goodbye!"),
    "quit application":    ("stop_assistant", None, "Shutting down. Goodbye!"),

    # ── Dynamic Launchers ──
    "launch eye tracking":    ("launch_gaze", None, "Launching gaze tracking mechanism"),
    "launch eye cursor":      ("launch_gaze", None, "Launching gaze tracking mechanism"),
    "start eye tracking":     ("launch_gaze", None, "Launching gaze tracking mechanism"),
    "start eye cursor":       ("launch_gaze", None, "Launching gaze tracking mechanism"),
    "stop eye tracking":      ("stop_gaze", None, "Stopping gaze tracking mechanism"),
    "stop eye cursor":        ("stop_gaze", None, "Stopping gaze tracking mechanism"),
    "close eye tracking":     ("stop_gaze", None, "Stopping gaze tracking mechanism"),
    "close eye cursor":       ("stop_gaze", None, "Stopping gaze tracking mechanism"),

    # ── UI Commands ──
    "open assistant settings": ("ui_command", "open_settings", "Opening settings panel"),
    "open settings":           ("ui_command", "open_settings", "Opening settings panel"),
    "close assistant settings":("ui_command", "close_settings", "Closing settings panel"),
    "close settings":          ("ui_command", "close_settings", "Closing settings panel"),
    "hide settings":           ("ui_command", "close_settings", "Closing settings panel"),
}

# Dynamic command prefixes — these extract a query from the speech
# Order matters: more specific prefixes must come BEFORE general ones
DYNAMIC_PREFIXES = [
    ("do a calculation of",   "calculate"),
    ("calculate",             "calculate"),
    ("do calculation of",      "calculate"),
    ("search in explorer for", "find_file"),
    ("search in file explorer for", "find_file"),
    ("search in explorer",    "find_file"),
    ("search in file explorer","find_file"),
    ("find file",             "find_file"),
    ("find folder",           "find_file"),
    ("search file",           "find_file"),
    ("search files for",      "find_file"),
    ("google search for",     "search_google"),
    ("google search",         "search_google"),
    ("google",                "search_google"),
    ("search for",            "search_smart"),
    ("search",                "search_smart"),
    ("look up",               "search_smart"),
    ("open file",             "open_file"),
    ("open folder",           "open_folder"),
    ("open website",          "open_url"),
    ("go to website",         "open_url"),
    ("go to",                 "open_url"),
    ("type",                  "type_text"),
    ("play ",                 "play_music"),
    ("close ",                "close_app"),
    ("stop ",                 "close_app"),
    ("terminate ",            "close_app"),
    ("exit ",                 "close_app"),
    ("open ",                 "open_app"),
]

# Suffixes that specify WHERE to search (stripped from query)
SEARCH_TARGET_SUFFIXES = [
    ("in file explorer",  "explorer"),
    ("in explorer",       "explorer"),
    ("in files",          "explorer"),
    ("in folders",        "explorer"),
    ("on youtube music",  "youtube_music"),
    ("in youtube music",  "youtube_music"),
    ("on youtube",        "youtube"),
    ("in browser",        "google"),
    ("in chrome",         "google"),
    ("in google",         "google"),
    ("on google",         "google"),
    ("on chrome",         "google"),
    ("on browser",        "google"),
    ("on the web",        "google"),
    ("online",            "google"),
]


# ──────────────────────────────────────────────
# WAKE PHRASE DETECTION
# ──────────────────────────────────────────────

WAKE_PHRASES = [
    # Primary wake phrases
    "wake up jim", "wake up gym", "wake up gem",
    "wake up tim", "wake up him", "wake up team",
    "wakeup jim", "wake of jim",
    # "hey jim" / "hi jim" variants
    "hey jim", "hey gym", "hey gem", "hey tim",
    "hi jim", "hi gym", "hi gem", "hi tim",
    "a jim", "a gym",
    # "wakey wakey" / "wakey wakey jim" variants
    "wakey wakey jim", "wakey wakey gym", "wakey wakey gem", "wakey wakey",
    # "wake up" alone (no name needed)
    "wake up",
    # Name only
    "jim", "gym", "gem", "tim",
    # Observed Google Speech mishears (Indian English accent)
    # Google often hears "jim" as "hygiene" / "jeans" / "jean" / "gene"
    "hygiene", "hey hygiene", "wake up hygiene", "hi hygiene",
    "jeans", "hey jeans", "wake up jeans",
    "jean", "hey jean", "wake up jean",
    "gene", "hey gene", "wake up gene",
    "gin", "hey gin", "wake up gin",
    "dim", "hey dim",
    "him", "hey him",
    "vim", "hey vim",
    # Compound mishears
    "breakup gym", "break up gym", "breakup jim",
    "makeup gym", "make up gym",
    "because gym", "because jim",
    "waking gym", "waking jim",
]

STATE_IDLE      = "idle"
STATE_LISTENING = "listening"
STATE_SLEEPING  = "sleeping"


def _contains_wake(text: str) -> bool:
    """Check if any wake phrase variant appears in the text."""
    text = text.lower().strip()
    for phrase in WAKE_PHRASES:
        if phrase in text:
            return True
    # Fuzzy: "jim"/"gym" near "wake"/"hey"/"up"/"hi"/"wakey"
    words = set(text.split())
    primary = {"jim", "gym", "gem", "tim"}
    secondary = {"wake", "woke", "up", "hey", "hi", "wakey"}
    return bool(words & primary) and bool(words & secondary)


def _strip_wake(text: str) -> str:
    """Remove the wake phrase from text and return the remainder."""
    text = text.lower().strip()
    for phrase in WAKE_PHRASES:
        if phrase in text:
            return text.split(phrase, 1)[-1].strip()
    return text


# ──────────────────────────────────────────────
# JIM VOICE ASSISTANT
# ──────────────────────────────────────────────

class VoiceAssistant(threading.Thread):
    """
    Interactive voice assistant named Jim.
    Uses Google Speech Recognition (en-IN) + Windows SAPI5 TTS.
    """

    def __init__(self, require_attention=True, ui_callback=None, state_callback=None, **kwargs):
        super().__init__(daemon=True, name="VoiceAssistant")
        self.require_attention = require_attention
        self.ui_callback = ui_callback
        self.state_callback = state_callback
        self._running = False
        self._state = STATE_IDLE
        self.gaze_tracker = None

        # Speech recognizer
        self._recognizer = sr.Recognizer()
        self._recognizer.energy_threshold = 400
        self._recognizer.dynamic_energy_threshold = False
        self._recognizer.pause_threshold = 0.8

    def _listen(self, mic, timeout=5, phrase_time_limit=6) -> str:
        """Listen to microphone and return transcribed text."""
        try:
            logger.info("  (listening...)")
            audio = self._recognizer.listen(
                mic, timeout=timeout,
                phrase_time_limit=phrase_time_limit
            )
            audio_len = len(audio.get_raw_data())
            logger.info(f"  (got {audio_len/32000:.1f}s audio, recognizing...)")

            try:
                text = self._recognizer.recognize_google(audio, language="en-IN")
                logger.info(f"  >>> YOU SAID: \"{text}\"")
                return text.lower().strip()
            except sr.UnknownValueError:
                logger.info("  (could not understand)")
                return ""
            except sr.RequestError as e:
                logger.info(f"  (Google error: {e})")
                return ""

        except sr.WaitTimeoutError:
            return ""
        except Exception as e:
            logger.error(f"  Listen error: {type(e).__name__}: {e}")
            return ""

    def set_state(self, new_state: str):
        self._state = new_state
        if self.state_callback:
            self.state_callback(new_state)

    def run(self):
        self._running = True
        self.set_state(STATE_IDLE)

        # Greeting BEFORE opening mic
        if self.state_callback: self.state_callback("speaking")
        speak("Jim assistant is online. Say wake up Jim or hey Jim to activate me.")
        if self.state_callback: self.state_callback(STATE_IDLE)

        # ── Open Microphone ─────────────────────────────────────────
        logger.info("  Opening microphone...")
        try:
            mics = sr.Microphone.list_microphone_names()
            logger.info(f"  Available microphones ({len(mics)}):")
            for i, name in enumerate(mics):
                logger.info(f"    [{i}] {name}")
        except Exception as e:
            logger.warning(f"  Could not list microphones: {e}")

        mic = None
        mic_source = None
        try:
            mic = sr.Microphone()
            mic_source = mic.__enter__()
            logger.info("  Microphone opened successfully.")
            # Quick ambient noise adjustment so the recogniser calibrates
            logger.info("  Adjusting for ambient noise (1s)...")
            self._recognizer.adjust_for_ambient_noise(mic_source, duration=1)
            logger.info(f"  Energy threshold set to {self._recognizer.energy_threshold:.0f}")
        except OSError as e:
            logger.error(f"  MICROPHONE ERROR: {e}")
            logger.error("  No audio input device found or device is busy.")
            logger.error("  Check that a microphone is connected and not in use by another app.")
            if self.state_callback: self.state_callback("idle")
            return
        except Exception as e:
            logger.error(f"  Failed to open microphone: {type(e).__name__}: {e}")
            if self.state_callback: self.state_callback("idle")
            return

        logger.info("=" * 55)
        logger.info("  Jim Voice Assistant -- READY")
        logger.info("  Say \"wake up Jim\" to activate")
        logger.info("=" * 55)

        try:
            while self._running:
                # Attention gate
                if self.require_attention and not attention.is_attentive:
                    time.sleep(0.5)
                    continue

                # Listen for audio
                try:
                    text = self._listen(mic_source, timeout=3, phrase_time_limit=5)
                except Exception as e:
                    logger.error(f"  Listen cycle error: {type(e).__name__}: {e}")
                    time.sleep(1)
                    continue

                if not text:
                    continue

                # ── SLEEPING ──
                if self._state == STATE_SLEEPING:
                    if _contains_wake(text):
                        self.set_state(STATE_IDLE)
                        logger.info("  Jim woke up from sleep")
                    else:
                        continue

                # ── IDLE: waiting for wake phrase ──
                if self._state == STATE_IDLE:
                    if _contains_wake(text):
                        after_wake = _strip_wake(text)
                        if after_wake and len(after_wake) > 2:
                            if self.state_callback: self.state_callback("speaking")
                            speak("What can I help you with today?")
                            self.set_state(STATE_IDLE)
                            self._process_command(after_wake)
                        else:
                            self.set_state(STATE_LISTENING)
                            if self.state_callback: self.state_callback("speaking")
                            speak("What can I help you with today?")
                            if self.state_callback: self.state_callback(STATE_LISTENING)
                            cmd = self._listen(mic_source, timeout=8, phrase_time_limit=8)
                            if cmd:
                                logger.info(f"  >>> COMMAND: \"{cmd}\"")
                                self._process_command(cmd)
                            else:
                                if self.state_callback: self.state_callback("speaking")
                                speak("I didn't catch that. Say hey Jim to try again.")
                            self.set_state(STATE_IDLE)
                    continue

        except KeyboardInterrupt:
            pass
        finally:
            if mic is not None:
                try:
                    mic.__exit__(None, None, None)
                except Exception:
                    pass
            if self.state_callback: self.state_callback("speaking")
            speak("Jim signing off. Goodbye.")
            logger.info("Jim assistant stopped")

    def stop(self):
        self._running = False

    def _process_command(self, text: str):
        """Find the best matching command and execute it."""
        # 1. Exact static match first
        if text in VOICE_COMMANDS:
            action_type, arg, response = VOICE_COMMANDS[text]
            self._execute(action_type, arg, response)
            return

        # 2. Check dynamic prefix commands (search, find, type, go to)
        for prefix, action in DYNAMIC_PREFIXES:
            if text.startswith(prefix):
                query = text[len(prefix):].strip()
                if query:
                    self._execute_dynamic(action, query)
                    return

        # 3. Fuzzy: longest matching phrase contained in text
        best_match = None
        best_len = 0
        for phrase, (action_type, arg, response) in VOICE_COMMANDS.items():
            if phrase in text and len(phrase) > best_len:
                best_match = (action_type, arg, response)
                best_len = len(phrase)

        if best_match:
            self._execute(best_match[0], best_match[1], best_match[2])
        else:
            logger.info(f"  No command matched: \"{text}\"")
            speak(f"Sorry, I didn't understand that. Say help to see what I can do.")

    def _execute_dynamic(self, action: str, query: str):
        """Execute dynamic commands that take a query parameter."""
        import pyautogui
        
        if self.state_callback: self.state_callback("speaking")

        if action == "search_smart":
            # Smart search: detect target app from suffix
            target = "current"  # default: search in current window
            for suffix, t in SEARCH_TARGET_SUFFIXES:
                if query.endswith(suffix):
                    query = query[:-len(suffix)].strip()
                    target = t
                    break

            if target == "google":
                speak(f"Searching Google for {query}")
                encoded = urllib.parse.quote_plus(query)
                url = f"https://www.google.com/search?q={encoded}"
                try:
                    subprocess.Popen(f"start {url}", shell=True)
                except Exception as e:
                    logger.error(f"Search failed: {e}")

            elif target == "explorer":
                speak(f"Searching files for {query}")
                try:
                    subprocess.Popen(
                        f'explorer /root,"search-ms:query={query}"',
                        shell=True
                    )
                except Exception as e:
                    logger.error(f"File search failed: {e}")

            elif target == "youtube_music":
                speak(f"Searching YouTube Music for {query}")
                encoded = urllib.parse.quote_plus(query)
                url = f"https://music.youtube.com/search?q={encoded}"
                try:
                    subprocess.Popen(f"start {url}", shell=True)
                except Exception as e:
                    logger.error(f"YouTube Music search failed: {e}")
                    
            elif target == "youtube":
                speak(f"Searching YouTube for {query}")
                encoded = urllib.parse.quote_plus(query)
                url = f"https://www.youtube.com/results?search_query={encoded}"
                try:
                    subprocess.Popen(f"start {url}", shell=True)
                except Exception as e:
                    logger.error(f"YouTube search failed: {e}")

            else:
                # Search in currently active window using Ctrl+E
                # (works in File Explorer, Chrome, Edge, and many apps)
                speak(f"Searching for {query}")
                pyautogui.hotkey('ctrl', 'e')
                time.sleep(0.5)
                # Clear any existing text and type the query
                pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.1)
                # Use clipboard to paste (supports all characters)
                try:
                    subprocess.run(
                        ['powershell', '-Command',
                         f"Set-Clipboard -Value '{query.replace(chr(39), chr(39)+chr(39))}'"],
                        timeout=5, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    pyautogui.hotkey('ctrl', 'v')
                    time.sleep(0.3)
                    pyautogui.press('enter')
                except Exception as e:
                    logger.error(f"Search typing failed: {e}")

        elif action == "search_google":
            speak(f"Searching Google for {query}")
            encoded = urllib.parse.quote_plus(query)
            url = f"https://www.google.com/search?q={encoded}"
            try:
                subprocess.Popen(f"start {url}", shell=True)
            except Exception as e:
                logger.error(f"Search failed: {e}")

        elif action == "play_music":
            is_yt_music = True
            if query.endswith("on youtube music"):
                query = query[:-16].strip()
            elif query.endswith("on youtube"):
                query = query[:-10].strip()
                is_yt_music = False

            speak(f"Playing {query}")
            try:
                import urllib.request
                import urllib.parse
                import re
                
                query_string = urllib.parse.urlencode({"search_query": query})
                html_content = urllib.request.urlopen("https://www.youtube.com/results?" + query_string)
                search_results = re.findall(r'watch\?v=([a-zA-Z0-9_-]{11})', html_content.read().decode())
                
                if search_results:
                    video_id = search_results[0]
                    if is_yt_music:
                        url = f"https://music.youtube.com/watch?v={video_id}"
                    else:
                        url = f"https://www.youtube.com/watch?v={video_id}"
                    subprocess.Popen(f"start {url}", shell=True)
                else:
                    speak("I couldn't find that song.")
            except Exception as e:
                logger.error(f"Music play failed: {e}")
                speak("I encountered an error trying to play the music.")

        elif action == "find_file":
            speak(f"Searching files for {query}")
            try:
                subprocess.Popen(f'explorer /root,"search-ms:query={query}"', shell=True)
            except Exception as e:
                logger.error(f"File search failed: {e}")

        elif action == "open_file":
            speak(f"Opening file {query}")
            # Use Windows search to find and open the file
            try:
                subprocess.Popen(f'explorer /root,"search-ms:query={query}"', shell=True)
            except Exception as e:
                logger.error(f"Open file failed: {e}")

        elif action == "open_folder":
            speak(f"Opening folder {query}")
            try:
                subprocess.Popen(f'explorer /root,"search-ms:query={query}&crumb=kind:folder"', shell=True)
            except Exception as e:
                logger.error(f"Open folder failed: {e}")

        elif action == "open_url":
            site = query.strip().replace(" ", "")
            if not site.startswith("http"):
                site = f"https://www.{site}.com"
            speak(f"Opening {query}")
            try:
                subprocess.Popen(f"start {site}", shell=True)
            except Exception as e:
                logger.error(f"URL open failed: {e}")

        elif action == "type_text":
            speak(f"Typing {query}")
            pyautogui.typewrite(query, interval=0.03)

        elif action == "calculate":
            # Clean expression
            expr = query.lower()
            on_calc = False
            if "on calculator" in expr:
                expr = expr.replace("on calculator", "").strip()
                on_calc = True
            elif "in calculator" in expr:
                expr = expr.replace("in calculator", "").strip()
                on_calc = True

            # Word replacements for spoken math operators
            word_map = {
                "plus": "+", "and": "+",
                "minus": "-", "subtract": "-",
                "times": "*", "multiplied by": "*", "multiply": "*", "into": "*", "x": "*",
                "divided by": "/", "divide": "/", "by": "/"
            }
            for word, op in word_map.items():
                expr = expr.replace(word, op)

            # Filter safe characters for evaluation
            safe_chars = set("0123456789+-*/(). ")
            expr_cleaned = "".join(c for c in expr if c in safe_chars).strip()

            try:
                if expr_cleaned:
                    # Evaluate mathematical expression safely
                    result = eval(expr_cleaned, {"__builtins__": None}, {})
                    if isinstance(result, float) and result.is_integer():
                        result = int(result)
                    
                    spoken_expr = expr_cleaned.replace("*", " times ").replace("/", " divided by ")
                    speak(f"The result of {spoken_expr} is {result}")
                    
                    if on_calc:
                        # Focus existing calculator window if open; do not spawn a new window if one exists.
                        import pygetwindow as gw
                        calc_win = None
                        try:
                            # Walk through all windows to find any containing "calculator" (case-insensitive) in title
                            for win in gw.getAllWindows():
                                if "calculator" in win.title.lower():
                                    calc_win = win
                                    break
                        except Exception as win_err:
                            logger.warning(f"Could not search windows with pygetwindow: {win_err}")

                        if calc_win:
                            try:
                                calc_win.restore()
                                calc_win.activate()
                                time.sleep(0.3)  # Wait for window focus shift
                                logger.info(f"✓ Focused existing calculator window: '{calc_win.title}'")
                            except Exception as focus_err:
                                logger.warning(f"Could not focus existing calculator: {focus_err}. Spawning a new one.")
                                subprocess.Popen("calc", shell=True)
                                time.sleep(0.8)
                        else:
                            subprocess.Popen("calc", shell=True)
                            time.sleep(0.8) # Wait for it to focus

                        pyautogui.write(f"{expr_cleaned}=", interval=0.05)
                else:
                    speak("Sorry, I could not extract a valid mathematical expression.")
            except Exception as e:
                logger.error(f"Calculation error: {e}")
                speak("Sorry, I had trouble calculating that. Make sure it is a valid mathematical equation.")

        elif action == "close_app":
            app_name = query.lower().strip()
            
            # Common application process mappings on Windows
            app_process_map = {
                "calculator": ["CalculatorApp.exe", "calc.exe"],
                "notepad": ["notepad.exe"],
                "browser": ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"],
                "chrome": ["chrome.exe"],
                "edge": ["msedge.exe"],
                "firefox": ["firefox.exe"],
                "brave": ["brave.exe"],
                "opera": ["opera.exe"],
                "word": ["winword.exe"],
                "excel": ["excel.exe"],
                "powerpoint": ["powerpnt.exe"],
                "outlook": ["outlook.exe"],
                "onenote": ["onenote.exe"],
                "teams": ["teams.exe", "msteams.exe"],
                "steam": ["steam.exe"],
                "discord": ["discord.exe"],
                "spotify": ["spotify.exe"],
                "telegram": ["telegram.exe"],
                "whatsapp": ["whatsapp.exe"],
                "zoom": ["zoom.exe"],
                "nvidia": ["nvcontainer.exe", "nvidia app.exe"],
                "obs": ["obs64.exe", "obs.exe"],
                "vlc": ["vlc.exe"],
                "vs code": ["code.exe"],
                "code": ["code.exe"],
                "visual studio": ["devenv.exe"],
                "photoshop": ["photoshop.exe"],
                "premiere": ["premiere.exe"],
                "blender": ["blender.exe"],
                "unity": ["unity.exe"],
                "epic games": ["epicgameslauncher.exe"],
                "terminal": ["windowsterminal.exe", "wt.exe"],
                "command prompt": ["cmd.exe"],
                "powershell": ["powershell.exe"],
                "paint": ["mspaint.exe"],
                "snipping tool": ["snippingtool.exe"],
                "settings": ["systemsettings.exe"],
                "explorer": ["explorer.exe"],
                "file explorer": ["explorer.exe"],
            }

            speak(f"Closing {query}")

            # 1. First, search and close via window title using pygetwindow
            import pygetwindow as gw
            closed_via_window = False
            try:
                for win in gw.getAllWindows():
                    if app_name in win.title.lower():
                        win.close()
                        closed_via_window = True
                        logger.info(f"✓ Closed window gracefully via pygetwindow: '{win.title}'")
            except Exception as e:
                logger.warning(f"Could not close window gracefully: {e}")

            # 2. Also taskkill matching processes to be thorough
            executables = app_process_map.get(app_name, [f"{app_name}.exe"])
            
            # Protection guard: never close explorer.exe unless explicitly stated as "explorer" or "file explorer"
            if "explorer" in app_name and app_name not in ["explorer", "file explorer"]:
                pass
            else:
                for exe in executables:
                    if exe.lower() == "explorer.exe":
                        continue
                    try:
                        subprocess.run(f"taskkill /f /im {exe}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass

        elif action == "open_app":
            app_name = query.strip()
            speak(f"Opening {app_name}")
            import pyautogui
            try:
                pyautogui.press('win')
                time.sleep(0.8)
                pyautogui.write(app_name, interval=0.03)
                time.sleep(1.0)
                pyautogui.press('enter')
            except Exception as e:
                logger.error(f"Failed to dynamically open application via Start Menu search: {e}")

    def _execute(self, action_type: str, arg: str, response: str):
        """Execute a predefined action."""
        import pyautogui
        
        if action_type == "ui_command":
            if self.ui_callback:
                speak(response)
                self.ui_callback(arg)
            else:
                speak("UI callback is not registered.")
            return

        if action_type == "launch":
            speak(response)
            try:
                subprocess.Popen(arg, shell=True)
            except Exception as e:
                logger.error(f"Launch failed: {e}")
                speak("Sorry, I couldn't open that application.")

        elif action_type == "hotkey":
            speak(response)
            keys = arg.split("+")
            try:
                pyautogui.hotkey(*keys)
            except Exception as e:
                logger.error(f"Hotkey failed: {e}")

        elif action_type == "mouse_click":
            speak(response)
            if arg == "left":
                pyautogui.click()
            elif arg == "right":
                pyautogui.rightClick()
            elif arg == "double":
                pyautogui.doubleClick()

        elif action_type == "click_nth_link":
            speak(response)
            n = int(arg)
            # Click the nth search result by calculated screen position.
            # Google search results have a predictable layout:
            #   - Results start at ~22% from top of screen
            #   - Each result block is ~10% of screen height
            #   - Titles are at ~35% from left edge
            screen_w, screen_h = pyautogui.size()

            if n == -1:
                # "Last link" — click near the bottom of visible results
                x = int(screen_w * 0.35)
                y = int(screen_h * 0.80)
            else:
                x = int(screen_w * 0.35)
                y_start = int(screen_h * 0.22)
                y_step = int(screen_h * 0.10)
                y = y_start + (n - 1) * y_step

            logger.info(f"  Clicking at ({x}, {y}) for result #{n}")
            pyautogui.click(x, y)

        elif action_type == "start_menu":
            # Open apps via Windows Start Menu search
            speak(response)
            pyautogui.press('win')
            time.sleep(0.8)
            pyautogui.write(arg, interval=0.03)
            time.sleep(1.0)
            pyautogui.press('enter')

        elif action_type == "select_nth_file":
            speak(response)
            # Parse arg: "N_action" where action is "open" or "select"
            parts = arg.split('_')
            pos = parts[0]      # "1", "2", "-1", "next", "prev"
            action = parts[1]   # "open" or "select"

            # Focus the file list using F6 (cycles panes in Explorer)
            pyautogui.press('F6')
            time.sleep(0.3)
            pyautogui.press('F6')
            time.sleep(0.3)

            if pos == "next":
                pyautogui.press('down')
            elif pos == "prev":
                pyautogui.press('up')
            elif pos == "-1":
                pyautogui.press('end')
            else:
                n = int(pos)
                pyautogui.press('home')
                time.sleep(0.2)
                for _ in range(n - 1):
                    pyautogui.press('down')
                    time.sleep(0.1)

            time.sleep(0.3)

            if action == "open":
                pyautogui.press('enter')
                time.sleep(0.3)
                pyautogui.press('enter')  # Double enter to be sure

        elif action_type == "scroll":
            speak(response)
            parts = arg.split("_")
            direction = parts[0]
            amount = int(parts[1]) if len(parts) > 1 else 3
            if direction == "up":
                pyautogui.scroll(amount)
            elif direction == "down":
                pyautogui.scroll(-amount)
            elif direction == "left":
                pyautogui.hscroll(-amount)
            elif direction == "right":
                pyautogui.hscroll(amount)

        elif action_type == "nav":
            import urllib.request
            import urllib.error
            speak(response)
            url = f"http://localhost:7891/{arg}"
            try:
                with urllib.request.urlopen(url, timeout=0.5):
                    pass
            except urllib.error.URLError:
                pass

        elif action_type == "help":
            speak(
                "I'm Jim, your voice assistant. Here's what I can do. "
                "Say open followed by an app name, like open browser or open calculator. "
                "Say search for, followed by what you want, to search Google. "
                "Say find file or open file, to search in file explorer. "
                "Say go to, followed by a website name, like go to youtube. "
                "I can navigate tabs with next tab, previous tab, close tab, new tab. "
                "I can scroll up, scroll down, page up, page down, go to top or bottom. "
                "I can go back, go forward, refresh the page. "
                "Say click or click here to click at the cursor position. "
                "Say click first link, click second link to click links on a page. "
                "I can also take screenshots, switch windows, and control volume. "
                "Say go to sleep to pause me. Say hey Jim or wake up to activate me again."
            )

        elif action_type == "sleep":
            speak(response)
            self._state = STATE_SLEEPING
            logger.info("  Jim entering sleep mode")

        elif action_type == "stop_assistant":
            speak(response)
            if self.ui_callback:
                self.ui_callback("exit_app")
            self.stop()

        elif action_type == "yt_music":
            """Focus the YouTube Music browser tab and send the appropriate shortcut."""
            import pygetwindow as gw

            # YouTube Music shortcuts:
            #   k / Space = play/pause   Shift+N = next   Shift+P = prev
            #   m = mute   Up/Down = volume   Shift+L = like   Shift+D = dislike
            shortcut_map = {
                "play_pause": ("k",),
                "next":       ("shift", "n"),
                "prev":       ("shift", "p"),
                "mute":       ("m",),
                "vol_up":     ("up",),
                "vol_down":   ("down",),
                "like":       ("shift", "l"),
                "dislike":    ("shift", "d"),
                "shuffle":    ("shift", "s"),
            }

            # Find a browser window whose title contains YouTube Music
            yt_win = None
            try:
                for win in gw.getAllWindows():
                    title = win.title.lower()
                    if "youtube music" in title or "music.youtube" in title:
                        yt_win = win
                        break
            except Exception as e:
                logger.warning(f"  pygetwindow search failed: {e}")

            if yt_win is None:
                speak("I couldn't find YouTube Music. Opening it now.")
                try:
                    subprocess.Popen("start https://music.youtube.com", shell=True)
                except Exception:
                    pass
                return

            # Activate the window
            try:
                yt_win.restore()
                yt_win.activate()
                time.sleep(0.4)   # let the OS finish focusing
            except Exception as e:
                logger.warning(f"  Could not activate YouTube Music window: {e}")

            speak(response)
            keys = shortcut_map.get(arg)
            if keys:
                try:
                    if len(keys) == 1:
                        pyautogui.press(keys[0])
                    else:
                        pyautogui.hotkey(*keys)
                    logger.info(f"  YouTube Music: sent {keys}")
                except Exception as e:
                    logger.error(f"  YouTube Music hotkey error: {e}")
            else:
                logger.warning(f"  Unknown yt_music action: {arg}")

        elif action_type == "launch_gaze":
            # Check if active gaze tracker thread already exists
            if self.gaze_tracker and self.gaze_tracker.is_alive():
                speak("Gaze tracking is already active.")
            else:
                speak(response)
                def run_gaze():
                    try:
                        from src.gaze_tracker import GazeTracker
                        tracker = GazeTracker(camera_id=0, smoothing=0.85, show_preview=True, gain=1.6)
                        tracker.start()
                        self.gaze_tracker = tracker
                    except Exception as err:
                        logger.error(f"Gaze Tracker launch failed: {err}")
                
                t = threading.Thread(target=run_gaze, daemon=True, name="GazeTrackerVoice")
                t.start()
                logger.info("  ✅ Dynamic Launcher: Gaze Tracker spawned via voice!")

        elif action_type == "stop_gaze":
            # Check if gaze tracker instance exists and is running
            if self.gaze_tracker and self.gaze_tracker.is_alive():
                speak(response)
                try:
                    self.gaze_tracker.stop()
                except Exception as err:
                    logger.error(f"Failed to stop gaze tracking: {err}")
            else:
                speak("Gaze tracking is not running.")


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Jim -- Interactive Voice Assistant"
    )
    parser.add_argument("--no-attention", action="store_true",
                        help="Disable attention gating (always listen)")
    args = parser.parse_args()

    assistant = VoiceAssistant(
        require_attention=not args.no_attention,
    )
    assistant.start()

    logger.info("Jim assistant running. Press Ctrl+C to stop.")
    try:
        while assistant.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        assistant.stop()
        logger.info("Stopped.")


if __name__ == "__main__":
    main()
