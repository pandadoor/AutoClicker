"""Core engine for AutoClicker&Macro - Performance & Power Overhaul
Replaces busy-wait loops with threading.Event, adds CPS counter,
JSON settings, high-precision timers, and multi-point clicking.
"""
import json, os, time, threading, random, ctypes

# --- High-precision Windows timer ---
try:
    winmm = ctypes.windll.winmm
    winmm.timeBeginPeriod(1)
except Exception:
    pass

# ============================================================
# SETTINGS ENGINE (JSON, replaces fragile pickle)
# ============================================================
SETTINGS_FILE = 'ACM.json'
SETTINGS_PKL = 'ACM.pkl'

DEFAULTS = {
    "simple": False,
    "themeColor": "green",
    "appearanceMode": "System",
    "clickerHotkey": "F6",
    "macroRecordHotkey": "F7",
    "macroStopHotkey": "F8",
    "macroPlayHotkey": "F9",
    "onTop": True,
    "showMousePosition": True,
    "superClicker": False,
    "mouseTimer": False,
    "windowX": None,
    "windowY": None,
    "saveClickerSettings": False,
    "savedClickerState": {},
    "profiles": {},
    "activeProfile": "Default",
    "scheduledDelay": 0,
    "scheduledStop": 0,
}

def load_settings():
    """Load settings from JSON. Auto-migrates from pickle if needed."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
            return {**DEFAULTS, **saved}
        except (json.JSONDecodeError, IOError):
            return dict(DEFAULTS)
    elif os.path.exists(SETTINGS_PKL):
        try:
            import pickle
            with open(SETTINGS_PKL, 'rb') as f:
                vals = pickle.load(f)
            keys = ["simple","themeColor","appearanceMode","clickerHotkey",
                     "macroRecordHotkey","macroStopHotkey","macroPlayHotkey",
                     "onTop","showMousePosition","superClicker","mouseTimer"]
            migrated = dict(DEFAULTS)
            for i, k in enumerate(keys):
                if i < len(vals):
                    migrated[k] = vals[i]
            save_settings(migrated)
            return migrated
        except Exception:
            return dict(DEFAULTS)
    else:
        s = dict(DEFAULTS)
        save_settings(s)
        return s

def save_settings(settings):
    """Save settings to JSON atomically."""
    tmp = SETTINGS_FILE + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(settings, f, indent=2)
        if os.path.exists(SETTINGS_FILE):
            os.remove(SETTINGS_FILE)
        os.rename(tmp, SETTINGS_FILE)
    except IOError:
        pass

# ============================================================
# CPS COUNTER
# ============================================================
class CPSCounter:
    """Tracks clicks per second with a rolling 1-second window."""
    def __init__(self):
        self._times = []
        self._lock = threading.Lock()
        self._total = 0

    def record_click(self):
        now = time.perf_counter()
        with self._lock:
            self._times.append(now)
            self._total += 1

    @property
    def cps(self):
        now = time.perf_counter()
        with self._lock:
            self._times = [t for t in self._times if now - t < 1.0]
            return len(self._times)

    @property
    def total(self):
        return self._total

    def reset(self):
        with self._lock:
            self._times.clear()
            self._total = 0

# ============================================================
# EFFICIENT CLICK ENGINE (replaces busy-wait polling)
# ============================================================
class ClickEngine:
    """High-performance auto-clicker using threading.Event instead of busy-wait."""

    def __init__(self):
        self._active = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.cps_counter = CPSCounter()
        # Click config
        self.delay_ms = 1
        self.click_offset_ms = 0
        self.mouse_offset_x = 0
        self.mouse_offset_y = 0
        self.custom_position = False
        self.position_x = 0
        self.position_y = 0
        self.use_interval_offset = False
        self.use_mouse_offset = False
        self.button = 'Left'
        self.click_type = 1  # 1=single, 2=double, 3=triple
        self.hold_duration = 0
        self.alternating = False
        self.repeating = False
        self.repeat_count = 1
        self.ghost_click = False
        self.super_mode = False
        # Multi-point clicking
        self.multi_points = []  # [(x,y), ...]
        self._multi_index = 0
        # Scheduling
        self.scheduled_delay = 0
        self.scheduled_stop = 0
        # Callbacks
        self.on_click = None  # function(button) to perform click
        self.on_status = None  # function(text) for status updates
        # Internal
        self._current_times = 0

    @property
    def is_clicking(self):
        return self._active.is_set()

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        self._current_times = 0
        self.cps_counter.reset()
        self._active.set()

    def stop(self):
        self._active.clear()

    def shutdown(self):
        self._stop.set()
        self._active.set()  # wake thread so it can exit

    def _run(self):
        while not self._stop.is_set():
            # Efficient wait — ZERO CPU until signaled
            self._active.wait()
            if self._stop.is_set():
                break

            # Scheduled start delay
            if self.scheduled_delay > 0:
                if self.on_status:
                    self.on_status(f'Starting in {self.scheduled_delay}s...')
                self._active.wait(timeout=self.scheduled_delay)
                if not self._active.is_set():
                    continue

            start_time = time.perf_counter()

            while self._active.is_set():
                # Scheduled stop
                if self.scheduled_stop > 0:
                    elapsed = time.perf_counter() - start_time
                    if elapsed >= self.scheduled_stop:
                        self.stop()
                        break

                # Repeat limit
                if self.repeating and self._current_times >= self.repeat_count:
                    self.stop()
                    break

                # Perform click
                if self.on_click:
                    btn = self.button
                    # Multi-point cycling
                    if self.multi_points:
                        pt = self.multi_points[self._multi_index % len(self.multi_points)]
                        self._multi_index += 1
                        self.on_click(btn, position=pt)
                    else:
                        self.on_click(btn, position=None)
                    self.cps_counter.record_click()
                    self._current_times += 1

                    # Alternating button
                    if self.alternating:
                        self.button = 'Left' if self.button == 'Right' else 'Right'

                # Calculate delay with optional offset
                delay = self.delay_ms
                if self.use_interval_offset and self.click_offset_ms > 0:
                    delay += random.uniform(-self.click_offset_ms, self.click_offset_ms)
                delay = max(0, delay)

                # High-precision sleep
                if delay > 0:
                    if delay > 1000:
                        # For long delays, use Event.wait (interruptible)
                        if not self._active.wait(timeout=0):
                            break
                        deadline = time.perf_counter() + delay * 0.001
                        while time.perf_counter() < deadline:
                            if not self._active.is_set():
                                break
                            remaining = deadline - time.perf_counter()
                            if remaining > 0.05:
                                time.sleep(0.01)
                            elif remaining > 0:
                                time.sleep(0.0001)
                    else:
                        time.sleep(delay * 0.001)

# ============================================================
# PROFILE SYSTEM
# ============================================================
class ProfileManager:
    """Save/load entire click configurations as named profiles."""

    def __init__(self, settings):
        self.settings = settings
        if 'profiles' not in self.settings:
            self.settings['profiles'] = {}

    def save_profile(self, name, config):
        self.settings['profiles'][name] = config
        self.settings['activeProfile'] = name
        save_settings(self.settings)

    def load_profile(self, name):
        return self.settings['profiles'].get(name, {})

    def delete_profile(self, name):
        self.settings['profiles'].pop(name, None)
        save_settings(self.settings)

    def list_profiles(self):
        return list(self.settings['profiles'].keys())
