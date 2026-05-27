"""
Gaze Tracker — Eye tracking cursor + attention detection
=========================================================
Uses MediaPipe FaceLandmarker (Tasks API) to:
  1. Track iris position and map it to the Windows OS mouse cursor.
  2. Detect whether the user is looking at the screen (attention gating).

Runs as a daemon thread so it can be imported by the launcher.

Usage (standalone):
  python -m src.gaze_tracker
  python -m src.gaze_tracker --camera 0 --smoothing 0.15 --preview

Group No. 7 | 8th Semester Major Project
"""

import argparse
import os
import threading
import time
import urllib.request

import cv2
import numpy as np
import pyautogui
pyautogui.FAILSAFE = False

from src.utils import setup_logger, DATA_DIR
from src.attention_state import attention

logger = setup_logger("gaze_tracker")

# Prevent pyautogui fail-safe from triggering when cursor hits corner
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

# ──────────────────────────────────────────────
# MODEL MANAGEMENT
# ──────────────────────────────────────────────

MODEL_PATH = DATA_DIR / "face_landmarker.task"
MODEL_URL  = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"


def ensure_model():
    """Download the FaceLandmarker model if missing."""
    if MODEL_PATH.exists():
        return str(MODEL_PATH)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("  Downloading FaceLandmarker model (~5MB)...")
    urllib.request.urlretrieve(MODEL_URL, str(MODEL_PATH))
    logger.info(f"  ✓ Model saved to {MODEL_PATH}")
    return str(MODEL_PATH)


# ──────────────────────────────────────────────
# IRIS LANDMARK INDICES (478 mesh + 10 iris = 478..487)
# ──────────────────────────────────────────────

# Left eye corners + iris center
L_EYE_OUTER  = 33
L_EYE_INNER  = 133
L_IRIS_CENTER = 468

# Right eye corners + iris center
R_EYE_OUTER  = 362
R_EYE_INNER  = 263
R_IRIS_CENTER = 473

# Eye open/close landmarks (top/bottom eyelid)
L_EYE_TOP = 159
L_EYE_BOT = 145
R_EYE_TOP = 386
R_EYE_BOT = 374

# Additional left/right eye vertical landmarks for per-eye EAR
L_EYE_TOP2 = 158
L_EYE_BOT2 = 153
R_EYE_TOP2 = 385
R_EYE_BOT2 = 380

# Head pose landmarks
NOSE_TIP         = 1
CHIN             = 152
LEFT_EYE_CORNER  = 33
RIGHT_EYE_CORNER = 263
LEFT_MOUTH       = 61
RIGHT_MOUTH      = 291


class GazeTracker(threading.Thread):
    """
    Webcam-based gaze tracking thread using MediaPipe Tasks API.

    Parameters
    ----------
    camera_id : int
        OpenCV camera index (default 0).
    smoothing : float
        EMA smoothing factor (0 = no smoothing, 1 = infinite smoothing).
    show_preview : bool
        If True, shows a small debug preview window.
    """

    def __init__(self, camera_id=0, smoothing=0.15, show_preview=False, gain=1.6):
        super().__init__(daemon=True, name="GazeTracker")
        self.camera_id = camera_id
        self.smoothing = smoothing
        self.show_preview = show_preview
        self.gain = gain
        self._running = False

        # Smoothed cursor position
        self._sx = 0.5
        self._sy = 0.5

        # Screen dimensions
        screen_w, screen_h = pyautogui.size()
        attention.set_screen_size(screen_w, screen_h)
        self._sw = screen_w
        self._sh = screen_h
        logger.info(f"  Screen: {screen_w}×{screen_h}")

        # Calibration boundaries (initialized dynamically on first frame)
        self._cal_xmin = None
        self._cal_xmax = None
        self._cal_ymin = None
        self._cal_ymax = None

        # ── Click-gesture state ──
        # EAR thresholds (with hysteresis gap to prevent chatter)
        self._EAR_CLOSED = 0.085   # EAR below this → eye counts as closed (easier to trigger)
        self._EAR_OPEN   = 0.130   # EAR above this → eye counts as open (easier to re-arm)

        # Frame-count thresholds (at ~30 fps)
        self._MIN_CLOSED_FRAMES = 3  # Eye must be closed this many consecutive frames to confirm
        self._MIN_OPEN_FRAMES   = 6  # Eye must be open this many consecutive frames before wink fires

        # Per-eye consecutive-frame counters
        self._l_closed_frames = 0
        self._r_closed_frames = 0
        self._l_open_frames   = 10   # Start "confirmed open"
        self._r_open_frames   = 10

        # Wink: fire once per gesture (reset when eye re-opens)
        self._l_wink_armed = True   # True → allowed to fire next wink
        self._r_wink_armed = True

        # Wink candidate tracking to prevent normal blinks from triggering false winks
        self._l_wink_candidate = False
        self._r_wink_candidate = False

        # Cooldown between any click events
        self._click_cooldown = 0.8
        self._last_click_t   = 0.0

        # Double-blink: track COMPLETE blink cycles (close + fully reopen)
        self._blink_cycle_times  = []   # Timestamp of each completed blink cycle
        self._both_confirmed_closed = False
        self._eyes_reopened_after_blink = True  # Must reopen fully between counted blinks
        self._DOUBLE_BLINK_WINDOW = 1.2  # Max seconds between two blink cycles

        # Running min/max EAR bounds for dynamic calibration
        self._l_ear_max = 0.20
        self._l_ear_min = 0.05
        self._r_ear_max = 0.20
        self._r_ear_min = 0.05

        # Consecutive frames both eyes are closed (for attention gating)
        self._eyes_closed_consecutive_frames = 0

        # ── Cursor freeze during gestures ──
        self._gesture_active = False  # True when a blink/wink is in progress → cursor frozen

        # ── Sustained wink hold-click (drag) state ──
        self._HOLD_THRESHOLD_FRAMES = 18  # ~0.6s at 30fps: wink longer than this = hold/drag
        self._is_holding = False           # True when mouse button is held down (drag mode)
        self._l_wink_closed_count = 0      # How many frames left eye has been closed in current wink
        self._r_wink_closed_count = 0      # How many frames right eye has been closed in current wink

    def run(self):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import (
            FaceLandmarker,
            FaceLandmarkerOptions,
            RunningMode,
        )

        self._running = True

        # Ensure model is downloaded
        model_path = ensure_model()

        # Configure FaceLandmarker
        options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )

        landmarker = FaceLandmarker.create_from_options(options)

        cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)
        if not cap.isOpened():
            logger.error(f"Cannot open camera {self.camera_id}")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)

        logger.info("✓ Camera opened — gaze tracking active")

        frame_ts = 0
        while self._running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            frame = cv2.flip(frame, 1)  # Mirror
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Convert to MediaPipe Image
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            frame_ts += 33  # ~30fps in milliseconds

            result = landmarker.detect_for_video(mp_image, frame_ts)

            if result.face_landmarks and len(result.face_landmarks) > 0:
                lm = result.face_landmarks[0]  # List of NormalizedLandmark

                # Check if we have iris landmarks (need >= 478)
                if len(lm) < 478:
                    attention.is_attentive = False
                    continue

                # Update dynamic EAR thresholds first
                self._update_dynamic_thresholds(lm)

                # ── Attention: check if eyes are open ──
                eyes_open = self._check_eyes_open(lm)
 
                # ── Attention: check head pose ──
                looking_at_screen = self._check_head_pose(lm, frame.shape)
 
                # ── Attention: estimate distance in meters ──
                dx = lm[LEFT_EYE_CORNER].x - lm[RIGHT_EYE_CORNER].x
                dy = lm[LEFT_EYE_CORNER].y - lm[RIGHT_EYE_CORNER].y
                d_norm = np.sqrt(dx**2 + dy**2)
                # Calibrated for wide-angle webcams (FOV ~78deg): D = 0.06 / d_norm
                distance_meters = 0.06 / (d_norm + 1e-6)
                in_range = distance_meters <= 1.50
 
                is_attentive = eyes_open and looking_at_screen and in_range
                attention.is_attentive = is_attentive
 
                # ── Wink / double-blink click detection (always active when face visible) ──
                self._detect_clicks(lm)
 
                # ── Calculate gaze from iris position ──
                # Freeze cursor when a blink/wink gesture is in progress
                # to prevent iris landmark jitter from dragging the cursor
                if is_attentive and not self._gesture_active:
                    gx, gy = self._calc_gaze(lm)
                    self._update_cursor(gx, gy)
                else:
                    # Log diagnostics every 15 frames (approx 0.5s) to avoid spamming
                    if not hasattr(self, '_diag_counter'):
                        self._diag_counter = 0
                    self._diag_counter += 1
                    if self._diag_counter % 15 == 0:
                        reasons = []
                        if not eyes_open: reasons.append("Eyes Closed (sustained)")
                        if not looking_at_screen: 
                            yaw = getattr(self, '_last_yaw', 0.0)
                            pitch = getattr(self, '_last_pitch', 0.0)
                            reasons.append(f"Head Turned Away (Yaw: {yaw:.1f}°, Pitch: {pitch:.1f}°)")
                        if not in_range: reasons.append(f"Too Far ({distance_meters:.2f}m > 1.50m)")
                        logger.info(f"Tracking paused: {', '.join(reasons)}")
 
                if self.show_preview:
                    # Draw distance details on frame
                    color = (0, 255, 0) if in_range else (0, 0, 255)
                    status_text = "ACTIVE" if in_range else "OUT OF RANGE (>1.50m)"
                    cv2.putText(frame, f"Dist: {distance_meters:.2f}m ({status_text})", 
                                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                    self._draw_debug(frame, lm, is_attentive)

            else:
                attention.is_attentive = False

            if self.show_preview:
                cv2.imshow("Gaze Tracker", frame)
                if cv2.waitKey(1) & 0xFF == 27:  # ESC
                    break

        landmarker.close()
        cap.release()
        if self.show_preview:
            cv2.destroyAllWindows()
        logger.info("Gaze tracker stopped")

    def stop(self):
        self._running = False

    # ── Internal methods ──────────────────────────

    def _per_eye_ear(self, lm):
        """Return (left_EAR, right_EAR) using per-eye vertical span / horizontal span."""
        def ear(top1, bot1, top2, bot2, outer, inner):
            v1 = abs(lm[top1].y - lm[bot1].y)
            v2 = abs(lm[top2].y - lm[bot2].y)
            h  = abs(lm[outer].x - lm[inner].x)
            return (v1 + v2) / (2.0 * h + 1e-6)

        l_ear = ear(L_EYE_TOP, L_EYE_BOT, L_EYE_TOP2, L_EYE_BOT2, L_EYE_OUTER, L_EYE_INNER)
        r_ear = ear(R_EYE_TOP, R_EYE_BOT, R_EYE_TOP2, R_EYE_BOT2, R_EYE_OUTER, R_EYE_INNER)
        return l_ear, r_ear

    def _update_dynamic_thresholds(self, lm):
        """Update running min/max EAR bounds and calculate dynamic thresholds."""
        l_ear, r_ear = self._per_eye_ear(lm)

        # Update running bounds for left eye
        if l_ear > self._l_ear_max:
            self._l_ear_max = min(0.40, l_ear)
        else:
            self._l_ear_max = max(0.10, self._l_ear_max - (self._l_ear_max - l_ear) * 0.0002)

        if l_ear < self._l_ear_min:
            self._l_ear_min = max(0.03, l_ear)
        else:
            self._l_ear_min = min(0.12, self._l_ear_min + (l_ear - self._l_ear_min) * 0.0002)

        # Update running bounds for right eye
        if r_ear > self._r_ear_max:
            self._r_ear_max = min(0.40, r_ear)
        else:
            self._r_ear_max = max(0.10, self._r_ear_max - (self._r_ear_max - r_ear) * 0.0002)

        if r_ear < self._r_ear_min:
            self._r_ear_min = max(0.03, r_ear)
        else:
            self._r_ear_min = min(0.12, self._r_ear_min + (r_ear - self._r_ear_min) * 0.0002)

        # Compute dynamic thresholds
        l_ear_range = self._l_ear_max - self._l_ear_min
        self._l_closed_thresh = self._l_ear_min + l_ear_range * 0.35
        self._l_open_thresh   = self._l_ear_min + l_ear_range * 0.60

        r_ear_range = self._r_ear_max - self._r_ear_min
        self._r_closed_thresh = self._r_ear_min + r_ear_range * 0.35
        self._r_open_thresh   = self._r_ear_min + r_ear_range * 0.60

    def _detect_clicks(self, lm):
        """Detect wink / double-blink gestures and fire mouse clicks.

        Uses frame-count hysteresis so noisy, partial, or brief eye movements
        cannot trigger false positives.

        Gesture definitions:
          Left wink (short)   – left eye closed briefly while right stays open
                                → left click fires once the left eye REOPENS
          Right wink (short)  – right eye closed briefly while left stays open
                                → left click fires once the right eye REOPENS
          Sustained wink      – one eye closed ≥ HOLD_THRESHOLD_FRAMES while other stays open
                                → mouse-down (drag); mouse-up on reopen (drop)
          Double blink        – two complete blink cycles (close+reopen+close+reopen)
                                 both eyes, within DOUBLE_BLINK_WINDOW seconds
                                → double click

        Cursor is frozen (self._gesture_active = True) whenever any eye is
        confirmed-closed to prevent iris landmark jitter from moving the cursor.
        """
        now = time.time()
        l_ear, r_ear = self._per_eye_ear(lm)

        # ── Update per-eye frame counters with hysteresis ──
        if l_ear < self._l_closed_thresh:
            self._l_closed_frames += 1
            self._l_open_frames    = 0
        elif l_ear > self._l_open_thresh:
            self._l_open_frames    += 1
            self._l_closed_frames   = 0
        # In the hysteresis zone: keep existing counts unchanged

        if r_ear < self._r_closed_thresh:
            self._r_closed_frames += 1
            self._r_open_frames    = 0
        elif r_ear > self._r_open_thresh:
            self._r_open_frames    += 1
            self._r_closed_frames   = 0

        # Confirmed states
        l_confirmed_closed = self._l_closed_frames >= self._MIN_CLOSED_FRAMES
        r_confirmed_closed = self._r_closed_frames >= self._MIN_CLOSED_FRAMES
        l_confirmed_open   = self._l_open_frames   >= self._MIN_OPEN_FRAMES
        r_confirmed_open   = self._r_open_frames   >= self._MIN_OPEN_FRAMES
        both_confirmed_closed = l_confirmed_closed and r_confirmed_closed

        # ── Freeze cursor whenever any eye is closing (prevents drift) ──
        any_eye_closing = l_confirmed_closed or r_confirmed_closed
        if any_eye_closing:
            self._gesture_active = True
        elif l_confirmed_open and r_confirmed_open:
            # Only unfreeze when BOTH eyes are confirmed back open
            self._gesture_active = False

        # Clear wink candidates if both eyes are closed (blink in progress)
        both_closed = l_ear < self._l_closed_thresh and r_ear < self._r_closed_thresh
        if both_closed:
            self._l_wink_candidate = False
            self._r_wink_candidate = False
            self._l_wink_closed_count = 0
            self._r_wink_closed_count = 0

        # ── Double-blink: count complete blink CYCLES (close → reopen) ──
        if both_confirmed_closed and not self._both_confirmed_closed:
            # Falling edge: both eyes just became confirmed-closed
            self._both_confirmed_closed     = True
            self._eyes_reopened_after_blink = False   # Must fully reopen before next count

        if not both_confirmed_closed and self._both_confirmed_closed:
            # Rising edge: eyes coming back open
            if l_confirmed_open and r_confirmed_open:
                # Full blink cycle complete
                self._both_confirmed_closed     = False
                self._eyes_reopened_after_blink = True
                self._blink_cycle_times.append(now)
                # Prune old cycles outside the window
                self._blink_cycle_times = [
                    t for t in self._blink_cycle_times
                    if now - t <= self._DOUBLE_BLINK_WINDOW
                ]
                if (len(self._blink_cycle_times) >= 2
                        and now - self._last_click_t >= self._click_cooldown):
                    logger.info(f"  [Click] Double blink → double click")
                    pyautogui.doubleClick(_pause=False)
                    self._last_click_t      = now
                    self._blink_cycle_times = []

        # ── Wink detection (only when it is NOT a full blink) ──
        if not both_closed:
            # Left wink candidate: left confirmed-closed, right eye open
            if l_confirmed_closed and r_ear > self._r_open_thresh:
                self._l_wink_candidate = True
                self._l_wink_closed_count += 1

                # Sustained wink → hold-click (drag) when threshold is reached
                if (self._l_wink_closed_count == self._HOLD_THRESHOLD_FRAMES
                        and not self._is_holding):
                    logger.info(f"  [Hold] Left wink sustained → mouse down (drag)")
                    pyautogui.mouseDown(button='left', _pause=False)
                    self._is_holding = True
                    self._last_click_t = now
            else:
                # Left eye not in wink state — reset its closed counter
                if not l_confirmed_closed:
                    self._l_wink_closed_count = 0

            # Right wink candidate: right confirmed-closed, left eye open
            if r_confirmed_closed and l_ear > self._l_open_thresh:
                self._r_wink_candidate = True
                self._r_wink_closed_count += 1

                # Sustained wink → hold-click (drag) when threshold is reached
                if (self._r_wink_closed_count == self._HOLD_THRESHOLD_FRAMES
                        and not self._is_holding):
                    logger.info(f"  [Hold] Right wink sustained → mouse down (drag)")
                    pyautogui.mouseDown(button='left', _pause=False)
                    self._is_holding = True
                    self._last_click_t = now
            else:
                # Right eye not in wink state — reset its closed counter
                if not r_confirmed_closed:
                    self._r_wink_closed_count = 0

        # ── Handle eye reopen: either release hold or fire regular click ──
        if l_ear > self._l_open_thresh:
            if self._l_wink_candidate:
                if self._is_holding:
                    # Sustained wink release → mouse up (drop)
                    logger.info(f"  [Release] Left eye reopened → mouse up (drop)")
                    pyautogui.mouseUp(button='left', _pause=False)
                    self._is_holding = False
                    self._last_click_t = now
                elif self._l_wink_armed and now - self._last_click_t >= self._click_cooldown:
                    # Short wink release → regular left click
                    logger.info(f"  [Click] Left wink release (L_EAR={l_ear:.3f}, R_EAR={r_ear:.3f}) → left click")
                    pyautogui.click(button='left', _pause=False)
                    self._last_click_t = now
                    self._l_wink_armed = False
                self._l_wink_candidate = False
                self._l_wink_closed_count = 0

        if r_ear > self._r_open_thresh:
            if self._r_wink_candidate:
                if self._is_holding:
                    # Sustained wink release → mouse up (drop)
                    logger.info(f"  [Release] Right eye reopened → mouse up (drop)")
                    pyautogui.mouseUp(button='left', _pause=False)
                    self._is_holding = False
                    self._last_click_t = now
                elif self._r_wink_armed and now - self._last_click_t >= self._click_cooldown:
                    # Short wink release → regular left click
                    logger.info(f"  [Click] Right wink release (L_EAR={l_ear:.3f}, R_EAR={r_ear:.3f}) → left click")
                    pyautogui.click(button='left', _pause=False)
                    self._last_click_t = now
                    self._r_wink_armed = False
                self._r_wink_candidate = False
                self._r_wink_closed_count = 0

        # Re-arm winks once eye has fully reopened (confirmed-open)
        if l_confirmed_open:
            self._l_wink_armed = True
        if r_confirmed_open:
            self._r_wink_armed = True

    def _check_eyes_open(self, lm) -> bool:
        """Check Eye Aspect Ratio (EAR) — closed eyes = not attentive.

        Uses dynamic thresholds and temporal filtering to prevent brief blinks
        or downward gaze shifts from pausing the cursor.
        """
        l_ear, r_ear = self._per_eye_ear(lm)
        avg_ear = (l_ear + r_ear) / 2.0

        # Open threshold is average of the dynamic open thresholds
        avg_open_thresh = (self._l_open_thresh + self._r_open_thresh) / 2.0
        # Gating threshold: slightly lower than open to prevent flickers
        gating_thresh = max(0.06, min(0.09, avg_open_thresh * 0.85))

        if avg_ear < gating_thresh:
            self._eyes_closed_consecutive_frames += 1
        else:
            self._eyes_closed_consecutive_frames = 0

        # Require 15 consecutive frames (~0.5s) of closed eyes to count as not open
        return self._eyes_closed_consecutive_frames < 15

    def _check_head_pose(self, lm, img_shape) -> bool:
        """Check if head is facing roughly toward the camera."""
        h, w, _ = img_shape

        # 3D model points (generic face proportions)
        model_points = np.array([
            (0.0,  0.0,  0.0),       # Nose tip
            (0.0, -330.0, -65.0),     # Chin
            (-225.0, 170.0, -135.0),  # Left eye corner
            (225.0, 170.0, -135.0),   # Right eye corner
            (-150.0, -150.0, -125.0), # Left mouth
            (150.0, -150.0, -125.0),  # Right mouth
        ], dtype=np.float64)

        # 2D image points from landmarks
        indices = [NOSE_TIP, CHIN, LEFT_EYE_CORNER, RIGHT_EYE_CORNER,
                   LEFT_MOUTH, RIGHT_MOUTH]
        image_points = np.array([
            (lm[i].x * w, lm[i].y * h) for i in indices
        ], dtype=np.float64)

        # Camera matrix approximation
        focal_length = w
        center = (w / 2, h / 2)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1],
        ], dtype=np.float64)
        dist_coeffs = np.zeros((4, 1))

        _, rotation_vec, _ = cv2.solvePnP(
            model_points, image_points, camera_matrix, dist_coeffs
        )
        rmat, _ = cv2.Rodrigues(rotation_vec)
        angles, _, _, _, _, _ = cv2.RQDecomp3x3(rmat)

        yaw = angles[1]
        pitch = angles[0]
 
        # Calculate yaw and pitch error considering symmetry around 0 or 180 degrees
        yaw_error = min(abs(yaw), 180.0 - abs(yaw))
        pitch_error = min(abs(pitch), 180.0 - abs(pitch))

        # Log angles in diagnostics
        self._last_yaw = yaw_error
        self._last_pitch = pitch_error

        # Within ±50° yaw_error and ±50° pitch_error → looking at screen
        return yaw_error < 50 and pitch_error < 50

    def _calc_gaze(self, lm) -> tuple:
        """Calculate normalised gaze position (0..1) from iris landmarks."""
        # Use absolute iris center positions in the image to avoid reverse head-coupling!
        # When you turn your head left but keep your eyes on the screen, the relative eye 
        # ratio goes right, which moves the cursor the wrong way. Absolute position fixes this.
        gx = (lm[L_IRIS_CENTER].x + lm[R_IRIS_CENTER].x) / 2.0
        gy = (lm[L_IRIS_CENTER].y + lm[R_IRIS_CENTER].y) / 2.0

        if self._cal_xmin is None:
            # Initialize very tight bounds around the user's initial resting position
            self._cal_xmin = gx - 0.015
            self._cal_xmax = gx + 0.015
            self._cal_ymin = gy - 0.02
            self._cal_ymax = gy + 0.02

        # Auto-calibrate boundaries (Expand quickly, shrink extremely slowly)
        if gx < self._cal_xmin: self._cal_xmin = gx
        elif gx > self._cal_xmin: self._cal_xmin += (gx - self._cal_xmin) * 0.0001
        
        if gx > self._cal_xmax: self._cal_xmax = gx
        elif gx < self._cal_xmax: self._cal_xmax -= (self._cal_xmax - gx) * 0.0001

        if gy < self._cal_ymin: self._cal_ymin = gy
        elif gy > self._cal_ymin: self._cal_ymin += (gy - self._cal_ymin) * 0.0001

        if gy > self._cal_ymax: self._cal_ymax = gy
        elif gy < self._cal_ymax: self._cal_ymax -= (self._cal_ymax - gy) * 0.0001

        x_range = self._cal_xmax - self._cal_xmin
        y_range = self._cal_ymax - self._cal_ymin

        nx = (gx - self._cal_xmin) / (x_range + 1e-6)
        ny = (gy - self._cal_ymin) / (y_range + 1e-6)
 
        # Apply a sensitivity gain (amplify movement from the center)
        nx = 0.5 + (nx - 0.5) * self.gain
        ny = 0.5 + (ny - 0.5) * self.gain

        return float(np.clip(nx, 0, 1)), float(np.clip(ny, 0, 1))

    def _update_cursor(self, gx: float, gy: float):
        """Apply velocity-weighted adaptive EMA smoothing and move the OS cursor."""
        # Calculate horizontal and vertical velocity (distance from current cursor)
        dist = np.sqrt((gx - self._sx)**2 + (gy - self._sy)**2)
 
        # Adaptive smoothing (snaps instantly for large shifts, wiggles 0% for steady gaze)
        base_alpha = self.smoothing  # e.g., 0.85
        # Map dist: 0.0 (steady) -> alpha=0.85, >=0.10 (fast shift) -> alpha=0.30
        alpha = base_alpha - (base_alpha - 0.30) * np.clip(dist / 0.10, 0, 1)
 
        self._sx = self._sx * alpha + gx * (1 - alpha)
        self._sy = self._sy * alpha + gy * (1 - alpha)
 
        px = int(self._sx * self._sw)
        py = int(self._sy * self._sh)

        attention.set_gaze(self._sx, self._sy)

        try:
            pyautogui.moveTo(px, py, _pause=False)
        except Exception as e:
            logger.error(f"PyAutoGUI error: {e}")

    def _draw_debug(self, frame, lm, is_attentive):
        """Draw debug overlay on the preview window."""
        h, w, _ = frame.shape

        # Draw iris positions
        for idx in [L_IRIS_CENTER, R_IRIS_CENTER]:
            if idx < len(lm):
                cx = int(lm[idx].x * w)
                cy = int(lm[idx].y * h)
                cv2.circle(frame, (cx, cy), 3, (0, 255, 0), -1)

        # Attention indicator
        color = (0, 255, 0) if is_attentive else (0, 0, 255)
        label = "ATTENTIVE" if is_attentive else "LOOKING AWAY"
        cv2.putText(frame, label, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        # Cursor position
        sx, sy = attention.get_gaze_screen()
        cv2.putText(frame, f"Cursor: ({sx}, {sy})", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)


# ──────────────────────────────────────────────
# ENTRY POINT (standalone)
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Gaze Tracker — Eye tracking cursor")
    parser.add_argument("--camera", type=int, default=0,
                        help="Camera index (default: 0)")
    parser.add_argument("--smoothing", type=float, default=0.85,
                        help="EMA smoothing factor (default: 0.85)")
    parser.add_argument("--gain", type=float, default=1.6,
                        help="Gaze sensitivity multiplier (default: 1.6)")
    parser.add_argument("--preview", action="store_true",
                        help="Show debug preview window")
    args = parser.parse_args()

    tracker = GazeTracker(
        camera_id=args.camera,
        smoothing=args.smoothing,
        show_preview=args.preview,
        gain=args.gain
    )
    tracker.start()

    logger.info("Gaze tracker running. Press Ctrl+C to stop.")
    try:
        while tracker.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        tracker.stop()
        logger.info("Stopped.")


if __name__ == "__main__":
    main()
