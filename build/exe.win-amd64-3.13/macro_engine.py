"""Enhanced Macro Engine v3 — Loop/EndLoop, RandomDelay, robust parsing.
All command parsing is isolated into named methods for testability.
"""
import time, random, threading, re
from core_engine import precision_sleep


class MacroEngine:
    """Plays macro scripts with extended command set."""

    def __init__(self):
        self._active = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.repeat_count = 0
        self.use_repeat = False
        self.delay_override = None
        self.delay_offset = 0.0
        self.use_delay_offset = False
        self.restrict_hwnd = None
        # Callbacks — set by GUI before play()
        self.do_mouse_move = None
        self.do_mouse_click = None
        self.do_mouse_click_at = None
        self.do_mouse_down = None
        self.do_mouse_up = None
        self.do_mouse_wheel = None
        self.do_mouse_drag = None
        self.do_key_press = None
        self.do_key_down = None
        self.do_key_up = None
        self.do_type_text = None
        self.do_warn = None
        self.check_restrict = None
        self.hotkeys = set()

    @property
    def is_playing(self):
        return self._active.is_set()

    def play(self, script_text):
        if self._active.is_set():
            return
        self._stop.clear()
        self._active.set()
        self._thread = threading.Thread(
            target=self._run, args=(script_text,), daemon=True
        )
        self._thread.start()

    def stop(self):
        self._active.clear()
        self._stop.set()

    # ── Timing ────────────────────────────────────────────────

    def _sleep(self, seconds):
        if seconds <= 0:
            return True
        return precision_sleep(seconds, self._active)

    def _get_delay(self, base_delay):
        if self.delay_override is not None and self.delay_override > 0:
            d = self.delay_override
        else:
            d = base_delay
        if self.use_delay_offset and self.delay_offset > 0:
            d += random.uniform(-self.delay_offset, self.delay_offset)
        return max(0, d)

    # ── Pre-compiled patterns ─────────────────────────────────

    _RE_DELAY = re.compile(r'^delay\s+([\d.]+)', re.IGNORECASE)
    _RE_RANDOM_DELAY = re.compile(r'^randomdelay\s+([\d.]+)\s+([\d.]+)', re.IGNORECASE)
    _RE_MOVE_EVENT = re.compile(r'^moveevent\s+x=([\d-]+)\s+y=([\d-]+)', re.IGNORECASE)
    _RE_MOVE = re.compile(r'^move\s+x=([\d-]+)\s+y=([\d-]+)\s+speed=(\d+)', re.IGNORECASE)
    _RE_BUTTON_EVENT = re.compile(r'^buttonevent\s+type=(\w+)\s+button=(\w+)', re.IGNORECASE)
    _RE_CLICK_AT = re.compile(r'^click\s+at\s+button=(\w+)\s+x=([\d-]+)\s+y=([\d-]+)\s+speed=(\d+)', re.IGNORECASE)
    _RE_CLICK = re.compile(r'^click\s+button=(\w+)', re.IGNORECASE)
    _RE_WHEEL = re.compile(r'^wheelevent\s+delta=([\d.-]+)', re.IGNORECASE)
    _RE_DRAG = re.compile(r'^drag\s+button=(\w+)\s+speed=(\d+)\s+x=(\d+)\s+y=(\d+)\s+to\s+x=(\d+)\s+y=(\d+)', re.IGNORECASE)
    _RE_KEYBOARD = re.compile(r'^keyboardevent\s+(.+?)\s+(down|up)', re.IGNORECASE)
    _RE_PRESSKEY = re.compile(r'^presskey\s+(.+)', re.IGNORECASE)
    _RE_TYPE = re.compile(r'^type\s+speed=([\d.]+)\s*\((.+)\)', re.IGNORECASE)
    _RE_LOOP = re.compile(r'^loop\s+(\d+)', re.IGNORECASE)
    _RE_WAIT = re.compile(r'^wait\s+([\d.]+)', re.IGNORECASE)
    _RE_SLEEP = re.compile(r'^sleep\s+([\d.]+)', re.IGNORECASE)

    # ── Main execution ────────────────────────────────────────

    def _run(self, script_text):
        lines = script_text.strip().splitlines()
        if not lines:
            self._active.clear()
            return

        times_played = 0
        skip_once = set()

        # Pre-scan for Loop/EndLoop pairs
        loop_map = {}   # endloop_idx -> (start_idx, count)
        loop_stack = []
        for idx, raw in enumerate(lines):
            stripped = raw.strip()
            m = self._RE_LOOP.match(stripped)
            if m:
                loop_stack.append((idx, int(m.group(1))))
            elif stripped.lower() == 'endloop' and loop_stack:
                start_i, count = loop_stack.pop()
                loop_map[idx] = (start_i, count)

        # Warn about unmatched loops
        if loop_stack and self.do_warn:
            for start_i, _ in loop_stack:
                self.do_warn(start_i + 1, 'Loop without matching EndLoop')

        while self._active.is_set():
            if self.use_repeat and times_played >= self.repeat_count:
                break

            loop_counters = {}
            i = 0
            while i < len(lines) and self._active.is_set():
                raw = lines[i].strip()

                # Empty line
                if not raw:
                    i += 1
                    continue

                # Restrict check
                if self.check_restrict and not self.check_restrict():
                    time.sleep(0.001)
                    continue

                try:
                    line = raw

                    # Skip-once prefix (*)
                    if line.startswith('*'):
                        if i in skip_once:
                            i += 1
                            continue
                        skip_once.add(i)
                        line = line[1:].strip()
                        if not line:
                            i += 1
                            continue

                    # Comment (#)
                    if line.startswith('#'):
                        i += 1
                        continue

                    low = line.lower()

                    # ── Loop/EndLoop ──
                    if low.startswith('loop ') and self._RE_LOOP.match(line):
                        i += 1
                        continue

                    if low == 'endloop':
                        if i in loop_map:
                            if i not in loop_counters:
                                loop_counters[i] = loop_map[i][1]
                            loop_counters[i] -= 1
                            if loop_counters[i] > 0:
                                i = loop_map[i][0] + 1
                                continue
                        i += 1
                        continue

                    # ── Delay ──
                    m = self._RE_DELAY.match(line)
                    if m:
                        d = self._get_delay(float(m.group(1)))
                        if not self._sleep(d):
                            break
                        i += 1
                        continue

                    # ── RandomDelay ──
                    m = self._RE_RANDOM_DELAY.match(line)
                    if m:
                        mn, mx = float(m.group(1)), float(m.group(2))
                        d = random.uniform(mn, mx)
                        if not self._sleep(d):
                            break
                        i += 1
                        continue

                    # ── Wait / Sleep (aliases for Delay) ──
                    m = self._RE_WAIT.match(line) or self._RE_SLEEP.match(line)
                    if m:
                        d = self._get_delay(float(m.group(1)))
                        if not self._sleep(d):
                            break
                        i += 1
                        continue

                    # ── MoveEvent ──
                    m = self._RE_MOVE_EVENT.match(line)
                    if m and self.do_mouse_move:
                        self.do_mouse_move(int(m.group(1)), int(m.group(2)), 0)
                        i += 1
                        continue

                    # ── Move (manual with speed) ──
                    m = self._RE_MOVE.match(line)
                    if m and self.do_mouse_move:
                        self.do_mouse_move(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                        i += 1
                        continue

                    # ── ButtonEvent ──
                    m = self._RE_BUTTON_EVENT.match(line)
                    if m:
                        action = m.group(1).lower()
                        button = m.group(2)
                        if action == 'down' and self.do_mouse_down:
                            self.do_mouse_down(button)
                        elif action == 'up' and self.do_mouse_up:
                            self.do_mouse_up(button)
                        i += 1
                        continue

                    # ── Click at position ──
                    m = self._RE_CLICK_AT.match(line)
                    if m and self.do_mouse_click_at:
                        self.do_mouse_click_at(m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)))
                        i += 1
                        continue

                    # ── Click ──
                    m = self._RE_CLICK.match(line)
                    if m and self.do_mouse_click:
                        self.do_mouse_click(m.group(1))
                        i += 1
                        continue

                    # ── WheelEvent ──
                    m = self._RE_WHEEL.match(line)
                    if m and self.do_mouse_wheel:
                        delta = int(float(m.group(1)))
                        direction = 'down' if delta < 0 else 'up'
                        self.do_mouse_wheel(direction, max(1, abs(delta)))
                        i += 1
                        continue

                    # ── Drag ──
                    m = self._RE_DRAG.match(line)
                    if m and self.do_mouse_drag:
                        self.do_mouse_drag(
                            m.group(1), int(m.group(2)),
                            int(m.group(3)), int(m.group(4)),
                            int(m.group(5)), int(m.group(6))
                        )
                        i += 1
                        continue

                    # ── KeyboardEvent ──
                    m = self._RE_KEYBOARD.match(line)
                    if m:
                        key = m.group(1).strip().rstrip(',')
                        action = m.group(2).lower()
                        if key.lower() not in self.hotkeys:
                            if action == 'down' and self.do_key_down:
                                self.do_key_down(key)
                            elif action == 'up' and self.do_key_up:
                                self.do_key_up(key)
                        i += 1
                        continue

                    # ── PressKey ──
                    m = self._RE_PRESSKEY.match(line)
                    if m:
                        key = m.group(1).strip()
                        if key.lower() not in self.hotkeys and self.do_key_press:
                            self.do_key_press(key)
                        i += 1
                        continue

                    # ── Type ──
                    m = self._RE_TYPE.match(line)
                    if m and self.do_type_text:
                        speed = float(m.group(1))
                        text = m.group(2)
                        self.do_type_text(text, speed)
                        i += 1
                        continue

                    # Unknown command — warn but don't crash
                    if self.do_warn:
                        self.do_warn(i + 1, f'Unknown command: {line[:40]}')

                except Exception as e:
                    if self.do_warn:
                        self.do_warn(i + 1, str(e))

                i += 1

            times_played += 1

        self._active.clear()
