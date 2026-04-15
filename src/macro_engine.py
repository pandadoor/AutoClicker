"""Enhanced Macro Engine — adds Loop/EndLoop, Random delay, improved parsing."""
import time, random, threading
from core_engine import precision_sleep

class MacroEngine:
    """Plays macro scripts with extended command set."""

    def __init__(self):
        self._active = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.repeat_count = 0  # 0 = toggle (infinite)
        self.use_repeat = False
        self.delay_override = None
        self.delay_offset = 0.0
        self.use_delay_offset = False
        self.restrict_hwnd = None
        # Callbacks — set by GUI
        self.do_mouse_move = None      # (x, y, speed)
        self.do_mouse_click = None     # (button,)
        self.do_mouse_click_at = None  # (button, x, y, speed)
        self.do_mouse_down = None      # (button,)
        self.do_mouse_up = None        # (button,)
        self.do_mouse_wheel = None     # (direction, clicks)
        self.do_mouse_drag = None      # (button, speed, x1, y1, x2, y2)
        self.do_key_press = None       # (key,)
        self.do_key_down = None        # (key,)
        self.do_key_up = None          # (key,)
        self.do_type_text = None       # (text, delay)
        self.do_warn = None            # (line_num, msg)
        self.check_restrict = None     # () -> bool
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

    def _run(self, script_text):
        lines = script_text.strip().splitlines()
        times_played = 0
        skip_once = set()

        # Pre-scan for Loop/EndLoop pairs
        loop_map = {}  # endloop_idx -> (start_idx, count)
        loop_stack = []
        for i, line in enumerate(lines):
            stripped = line.strip().lower()
            if stripped.startswith('loop '):
                try:
                    count = int(stripped.split()[1])
                except (ValueError, IndexError):
                    count = 1
                loop_stack.append((i, count))
            elif stripped == 'endloop' and loop_stack:
                start_i, count = loop_stack.pop()
                loop_map[i] = (start_i, count)

        while self._active.is_set():
            if self.use_repeat and times_played >= self.repeat_count:
                break

            # Loop counters for this playthrough
            loop_counters = {}  # endloop_idx -> remaining
            i = 0
            while i < len(lines) and self._active.is_set():
                line = lines[i].strip()
                if not line:
                    i += 1
                    continue

                # Restrict check
                if self.check_restrict and not self.check_restrict():
                    time.sleep(0.001)
                    continue

                low = line.lower()

                try:
                    # Skip-once lines (*)
                    if low.startswith('*'):
                        if i in skip_once:
                            i += 1
                            continue
                        skip_once.add(i)
                        line = line[1:].strip()
                        low = line.lower()

                    # Comment lines (#)
                    if low.startswith('#'):
                        i += 1
                        continue

                    # Loop/EndLoop
                    if low.startswith('loop '):
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

                    # Delay
                    if low.startswith('delay'):
                        parts = low.split()
                        d = self._get_delay(float(parts[1]))
                        if not self._sleep(d):
                            break

                    # Random delay: RandomDelay MIN MAX
                    elif low.startswith('randomdelay'):
                        parts = low.split()
                        mn, mx = float(parts[1]), float(parts[2])
                        d = random.uniform(mn, mx)
                        if not self._sleep(d):
                            break

                    # Keyboard events
                    elif low.startswith('keyboardevent'):
                        ev = line.replace('(', ' ', 1)[:-1].split()
                        key = ev[1] if len(ev) >= 3 else None
                        if key and key.lower() not in self.hotkeys:
                            if len(ev) == 4:
                                full_key = f'{ev[1]} {ev[2]}'
                                action = ev[3]
                            else:
                                full_key = ev[1]
                                action = ev[2]
                            if action == 'down' and self.do_key_down:
                                self.do_key_down(full_key)
                            elif action == 'up' and self.do_key_up:
                                self.do_key_up(full_key)

                    # PressKey
                    elif low.startswith('presskey'):
                        key = line.replace('(', ' ', 1)[:-1].split()[1]
                        if key.lower() not in self.hotkeys and self.do_key_press:
                            self.do_key_press(key)

                    # Type
                    elif low.startswith('type'):
                        text = line.split('(', 1)[1][:-1]
                        parts = low.split()
                        spd = float(parts[1].replace('speed=', ''))
                        if self.do_type_text:
                            self.do_type_text(text, spd)

                    # MoveEvent
                    elif low.startswith('moveevent'):
                        cleaned = low.replace('x=', '').replace('y=', '')
                        parts = cleaned.split()
                        if self.do_mouse_move:
                            self.do_mouse_move(int(parts[1]), int(parts[2]), 0)

                    # Move (manual)
                    elif low.startswith('move') and not low.startswith('moveevent'):
                        cleaned = low.replace('x=', '').replace('y=', '').replace('speed=', '')
                        parts = cleaned.split()
                        if self.do_mouse_move:
                            self.do_mouse_move(int(parts[1]), int(parts[2]), int(parts[3]))

                    # ButtonEvent
                    elif low.startswith('buttonevent'):
                        cleaned = low.replace('type=', '').replace('button=', '')
                        parts = cleaned.split()
                        if parts[1] == 'down' and self.do_mouse_down:
                            self.do_mouse_down(parts[2])
                        elif parts[1] == 'up' and self.do_mouse_up:
                            self.do_mouse_up(parts[2])

                    # Click
                    elif low.startswith('click'):
                        if 'at' in low:
                            cleaned = low.replace('button=', '').replace('x=', '').replace('y=', '').replace('speed=', '')
                            parts = cleaned.split()
                            if self.do_mouse_click_at:
                                self.do_mouse_click_at(parts[1], int(parts[3]), int(parts[4]), int(parts[5]))
                        else:
                            cleaned = low.replace('button=', '')
                            parts = cleaned.split()
                            if self.do_mouse_click:
                                self.do_mouse_click(parts[1])

                    # WheelEvent
                    elif low.startswith('wheelevent'):
                        cleaned = low.replace('delta=', '')
                        parts = cleaned.split()
                        delta = int(parts[1].split('.')[0])
                        if self.do_mouse_wheel:
                            direction = 'down' if delta < 0 else 'up'
                            self.do_mouse_wheel(direction, abs(delta))

                    # Drag
                    elif low.startswith('drag'):
                        cleaned = low.replace('button=', '').replace('x=', '').replace('y=', '').replace('speed=', '')
                        parts = cleaned.split()
                        if self.do_mouse_drag:
                            self.do_mouse_drag(parts[1], int(parts[2]), int(parts[3]), int(parts[4]), int(parts[6]), int(parts[7]))

                except Exception as e:
                    if self.do_warn:
                        self.do_warn(i + 1, str(e))

                i += 1

            times_played += 1

        self._active.clear()
