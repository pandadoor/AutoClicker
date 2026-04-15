"""Core engine for AutoClicker&Macro v3 — ZERO-LATENCY Edition
Absolute precision: busy-spin timing, direct win32 input, lock-free CPS.
"""
import json, os, time, threading, random, ctypes, collections

# ── High-precision Windows timer ─────────────────────────────
try:
    _winmm = ctypes.windll.winmm
    _winmm.timeBeginPeriod(1)
except Exception:
    pass

# ── Boost process priority to HIGH ───────────────────────────
try:
    import ctypes.wintypes
    _k32 = ctypes.windll.kernel32
    _k32.SetPriorityClass(_k32.GetCurrentProcess(), 0x00000080)  # HIGH_PRIORITY_CLASS
except Exception:
    pass

# ── Direct Win32 mouse input (bypasses AutoIt COM overhead) ──
try:
    _user32 = ctypes.windll.user32

    MOUSEEVENTF_MOVE       = 0x0001
    MOUSEEVENTF_LEFTDOWN   = 0x0002
    MOUSEEVENTF_LEFTUP     = 0x0004
    MOUSEEVENTF_RIGHTDOWN  = 0x0008
    MOUSEEVENTF_RIGHTUP    = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP   = 0x0040
    MOUSEEVENTF_ABSOLUTE   = 0x8000

    _BUTTON_DOWN = {'left': MOUSEEVENTF_LEFTDOWN, 'right': MOUSEEVENTF_RIGHTDOWN, 'middle': MOUSEEVENTF_MIDDLEDOWN}
    _BUTTON_UP   = {'left': MOUSEEVENTF_LEFTUP,   'right': MOUSEEVENTF_RIGHTUP,   'middle': MOUSEEVENTF_MIDDLEUP}

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    def _get_cursor_pos():
        pt = POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def _set_cursor_pos(x, y):
        _user32.SetCursorPos(int(x), int(y))

    def _mouse_click_direct(button='left', count=1):
        """Click using mouse_event — ~0.01ms per call vs ~0.5ms via AutoIt COM."""
        b = button.lower()
        down = _BUTTON_DOWN.get(b, MOUSEEVENTF_LEFTDOWN)
        up = _BUTTON_UP.get(b, MOUSEEVENTF_LEFTUP)
        for _ in range(count):
            _user32.mouse_event(down, 0, 0, 0, 0)
            _user32.mouse_event(up, 0, 0, 0, 0)

    def _mouse_down_direct(button='left'):
        b = button.lower()
        _user32.mouse_event(_BUTTON_DOWN.get(b, MOUSEEVENTF_LEFTDOWN), 0, 0, 0, 0)

    def _mouse_up_direct(button='left'):
        b = button.lower()
        _user32.mouse_event(_BUTTON_UP.get(b, MOUSEEVENTF_LEFTUP), 0, 0, 0, 0)

    HAS_DIRECT_INPUT = True
except Exception:
    HAS_DIRECT_INPUT = False

# ══════════════════════════════════════════════════════════════
# SETTINGS ENGINE (JSON, replaces fragile pickle)
# ══════════════════════════════════════════════════════════════
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
    "directInput": True,
}

def load_settings():
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
    tmp = SETTINGS_FILE + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(settings, f, indent=2)
        if os.path.exists(SETTINGS_FILE):
            os.remove(SETTINGS_FILE)
        os.rename(tmp, SETTINGS_FILE)
    except IOError:
        pass

# ══════════════════════════════════════════════════════════════
# CPS COUNTER — Lock-free using deque
# ══════════════════════════════════════════════════════════════
class CPSCounter:
    """Lock-free CPS tracking. deque is thread-safe for append/popleft in CPython."""

    __slots__ = ('_times', '_total')

    def __init__(self):
        self._times = collections.deque()
        self._total = 0

    def record_click(self):
        self._times.append(time.perf_counter())
        self._total += 1

    @property
    def cps(self):
        now = time.perf_counter()
        cutoff = now - 1.0
        while self._times and self._times[0] < cutoff:
            self._times.popleft()
        return len(self._times)

    @property
    def total(self):
        return self._total

    def reset(self):
        self._times.clear()
        self._total = 0

# ══════════════════════════════════════════════════════════════
# PRECISION SLEEP — Hybrid busy-spin for sub-ms accuracy
# ══════════════════════════════════════════════════════════════
def precision_sleep(seconds, cancel_event=None):
    """Sleep with sub-millisecond accuracy.
    Strategy:
    - >50ms: use time.sleep for bulk, busy-spin last 2ms
    - 2-50ms: time.sleep down to 2ms remaining, then spin
    - <2ms: pure busy-spin (perf_counter loop)
    Returns False if cancelled.
    """
    if seconds <= 0:
        return True
    deadline = time.perf_counter() + seconds
    # Coarse sleep phase: yield CPU if >2ms remain
    if seconds > 0.002:
        coarse_end = deadline - 0.002
        while time.perf_counter() < coarse_end:
            if cancel_event and not cancel_event.is_set():
                return False
            time.sleep(0.001)
    # Busy-spin phase: precise final approach
    while time.perf_counter() < deadline:
        if cancel_event and not cancel_event.is_set():
            return False
    return True

# ══════════════════════════════════════════════════════════════
# CLICK ENGINE — Zero-latency, direct input, busy-spin timing
# ══════════════════════════════════════════════════════════════
class ClickEngine:
    """Absolute precision auto-clicker with direct Win32 input."""

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
        self.click_type = 1
        self.hold_duration = 0
        self.alternating = False
        self.repeating = False
        self.repeat_count = 1
        self.ghost_click = False
        self.super_mode = False
        self.use_direct_input = True
        # Multi-point clicking
        self.multi_points = []
        self._multi_index = 0
        # Scheduling
        self.scheduled_delay = 0
        self.scheduled_stop = 0
        # Callbacks (fallback when direct input unavailable)
        self.on_click = None
        self.on_status = None
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
        self._multi_index = 0
        self.cps_counter.reset()
        self._active.set()

    def stop(self):
        self._active.clear()

    def shutdown(self):
        self._stop.set()
        self._active.set()

    def _boost_thread_priority(self):
        """Set this thread to THREAD_PRIORITY_HIGHEST for minimal scheduling jitter."""
        try:
            handle = _k32.GetCurrentThread()
            _k32.SetThreadPriority(handle, 2)  # THREAD_PRIORITY_HIGHEST
        except Exception:
            pass

    def _do_click(self, button, position=None):
        """Execute click with minimal overhead."""
        use_direct = self.use_direct_input and HAS_DIRECT_INPUT

        # Move to position if needed
        if position:
            if use_direct:
                _set_cursor_pos(position[0], position[1])
            elif self.on_click:
                pass  # on_click handles movement
        elif self.custom_position and not self.ghost_click:
            if use_direct:
                _set_cursor_pos(self.position_x, self.position_y)

        # Mouse offset
        if self.use_mouse_offset:
            xoff = random.uniform(-self.mouse_offset_x, self.mouse_offset_x)
            yoff = random.uniform(-self.mouse_offset_y, self.mouse_offset_y)
            if use_direct:
                cx, cy = _get_cursor_pos()
                _set_cursor_pos(int(cx + xoff), int(cy + yoff))

        # Click
        if use_direct:
            b = button.lower() if isinstance(button, str) else 'left'
            if self.hold_duration > 0:
                _mouse_down_direct(b)
                precision_sleep(self.hold_duration, self._active)
                _mouse_up_direct(b)
            else:
                _mouse_click_direct(b, self.click_type)
        elif self.on_click:
            self.on_click(button, position=position)

        self.cps_counter.record_click()
        self._current_times += 1

    def _run(self):
        self._boost_thread_priority()

        while not self._stop.is_set():
            self._active.wait()
            if self._stop.is_set():
                break

            # Scheduled start delay
            if self.scheduled_delay > 0:
                if self.on_status:
                    self.on_status(f'Starting in {self.scheduled_delay}s...')
                if not precision_sleep(self.scheduled_delay, self._active):
                    continue

            start_time = time.perf_counter()
            _perf = time.perf_counter  # local reference for speed

            while self._active.is_set():
                # Scheduled stop
                if self.scheduled_stop > 0:
                    if _perf() - start_time >= self.scheduled_stop:
                        self.stop()
                        break

                # Repeat limit
                if self.repeating and self._current_times >= self.repeat_count:
                    self.stop()
                    break

                # Click
                btn = self.button
                if self.multi_points:
                    pt = self.multi_points[self._multi_index % len(self.multi_points)]
                    self._multi_index += 1
                    self._do_click(btn, position=pt)
                else:
                    self._do_click(btn, position=None)

                # Alternating button
                if self.alternating:
                    self.button = 'Left' if self.button == 'Right' else 'Right'

                # Delay
                delay_s = self.delay_ms * 0.001
                if self.use_interval_offset and self.click_offset_ms > 0:
                    delay_s += random.uniform(-self.click_offset_ms, self.click_offset_ms) * 0.001
                delay_s = max(0.0, delay_s)

                if delay_s > 0:
                    if not precision_sleep(delay_s, self._active):
                        break

# ══════════════════════════════════════════════════════════════
# PROFILE SYSTEM
# ══════════════════════════════════════════════════════════════
class ProfileManager:
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
