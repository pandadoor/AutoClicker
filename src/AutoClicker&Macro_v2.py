""" AutoClicker&Macro — Power & Efficiency Overhaul
 Performance-optimized fork with CPS counter, multi-point clicking,
 JSON settings, profile system, Loop/EndLoop macros, click scheduling.
 Original: https://github.com/Assassin654/AutoClicker  (GPL v2)
"""
import os, sys, time, threading, random, json
from subprocess import Popen, CREATE_NO_WINDOW

# --- Load engine modules ---
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core_engine import (load_settings, save_settings, CPSCounter,
                          ClickEngine, ProfileManager, HAS_DIRECT_INPUT)
from macro_engine import MacroEngine

settings = load_settings()
version = '3.0.0-zero-latency'

if settings.get('simple', False):
    try:
        Popen(['simplifiedClicker.exe', str(version)])
    except FileNotFoundError:
        pass
    os._exit(0)

import autoit, keyboard, mouse
import tkinter
from tkinter import *
import customtkinter
import win32gui, win32ui, win32con
import requests

if not os.path.exists("Macros"):
    os.mkdir('Macros')

cwd = os.getcwd()
pid = os.getpid()

try:
    killSwitch = Popen(['ACM_failsafe.exe', str(pid)])
except FileNotFoundError:
    killSwitch = None

# ============================================================
# GUI SETUP
# ============================================================
root = customtkinter.CTk()
superClicker = settings.get('superClicker', False)
title_base = "AutoClicker & Macro — Zero-Latency Edition"
input_mode = 'DirectInput' if HAS_DIRECT_INPUT else 'AutoIt'
title = f'{title_base} [{input_mode}]'
if superClicker:
    title += ' - SuperMode'
root.title(title)
root.geometry('850x520')
root.attributes('-topmost', settings.get('onTop', True))
root.resizable(False, False)
customtkinter.set_appearance_mode(settings.get('appearanceMode', 'System'))
customtkinter.set_default_color_theme(settings.get('themeColor', 'green'))
try:
    root.iconbitmap('mouse.ico')
except Exception:
    pass

# Restore window position
wx, wy = settings.get('windowX'), settings.get('windowY')
if wx is not None and wy is not None:
    root.geometry(f'+{wx}+{wy}')

# --- State ---
clicking = False
recording = False
playing = False
saving = False
gettingPosition = False
ghostClick = False
restrictingClicker = False
restricingMacro = False
restrictClicker = {}
restrictMacro = {}
control_window = 0
subWindow = None
waiting = 0
pressButton = 'Left'

# --- Engines ---
click_engine = ClickEngine()
cps = click_engine.cps_counter
macro_eng = MacroEngine()
profile_mgr = ProfileManager(settings)

# ============================================================
# HOTKEYS
# ============================================================
clickerHotkey = settings['clickerHotkey']
macroRecordHotkey = settings['macroRecordHotkey']
macroStopHotkey = settings['macroStopHotkey']
macroPlayHotkey = settings['macroPlayHotkey']

def initiate_hotkeys():
    keyboard.unhook_all()
    keyboard.hook_key(clickerHotkey, lambda e: toggle_clicker(str(e)))
    keyboard.hook_key(macroRecordHotkey, lambda e: checkMacro(str(e)))
    keyboard.hook_key(macroStopHotkey, lambda e: stopMacro(str(e)))
    keyboard.hook_key(macroPlayHotkey, lambda e: startMacro(str(e)))

initiate_hotkeys()
macro_eng.hotkeys = {clickerHotkey.lower(), macroRecordHotkey.lower(),
                     macroStopHotkey.lower(), macroPlayHotkey.lower()}

# ============================================================
# INPUT VALIDATION (replaces bare except blocks)
# ============================================================
def safe_int(entry, default=0):
    val = entry.get().strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return None

def safe_float(entry, default=0.0):
    val = entry.get().strip()
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return None

# ============================================================
# AUTOCLICKER LOGIC
# ============================================================
def check():
    """Validate all inputs before starting clicker."""
    global delay, repeats, MouseoffsetX, MouseoffsetY, Clickoffset
    global MousepositionX, MousepositionY, holding
    global restrictClicker, subWindow, restrictingClicker

    mil = safe_int(mil_interval, 0)
    sec = safe_int(sec_interval, 0)
    mn = safe_int(min_interval, 0)
    hr = safe_int(hour_interval, 0)
    for name, val in [('milliseconds', mil), ('seconds', sec), ('minutes', mn), ('hours', hr)]:
        if val is None:
            showWarning.configure(text=f'Warning: Invalid {name}', text_color='red')
            return False

    Clickoffset = safe_int(interval_entry, 50)
    if Clickoffset is None:
        showWarning.configure(text='Warning: Invalid interval offset', text_color='red')
        return False

    MouseoffsetX = safe_int(mouseX_entry, 25)
    MouseoffsetY = safe_int(mouseY_entry, 25)
    if MouseoffsetX is None or MouseoffsetY is None:
        showWarning.configure(text='Warning: Invalid mouse offset', text_color='red')
        return False

    MousepositionX = safe_int(mouseX_position, 0)
    MousepositionY = safe_int(mouseY_position, 0)
    if MousepositionX is None or MousepositionY is None:
        showWarning.configure(text='Warning: Invalid cursor position', text_color='red')
        return False

    rp = safe_int(repeatTimes, 1)
    if rp is None:
        showWarning.configure(text='Warning: Invalid repeat option', text_color='red')
        return False
    repeats = rp

    holding = safe_float(holdDuration, 0)
    if holding is None:
        showWarning.configure(text='Warning: Invalid hold duration', text_color='red')
        return False

    if alternatingBox.get() and mouseButton_entry.get() == 'Middle':
        showWarning.configure(text='Warning: Cannot alternate with middle button', text_color='red')
        return False
    if holding > 0 and mouseType_entry.get() != 'Single':
        showWarning.configure(text=f'Warning: Cannot {mouseType_entry.get()} click with hold', text_color='red')
        return False

    delay = mil + (sec * 1000) + (mn * 60000) + (hr * 3600000)
    if delay < 0:
        showWarning.configure(text='Warning: Delay cannot be negative', text_color='red')
        return False

    # Scheduled delay/stop
    sched_d = safe_float(sched_delay_entry, 0)
    sched_s = safe_float(sched_stop_entry, 0)
    click_engine.scheduled_delay = sched_d if sched_d else 0
    click_engine.scheduled_stop = sched_s if sched_s else 0

    showWarning.configure(text='Warning: None', text_color=('black', 'white'))
    return True

def perform_click_fallback(button, position=None):
    """Fallback click via AutoIt — used only for ghost-click mode."""
    if position:
        autoit.mouse_move(x=position[0], y=position[1], speed=0)

    if click_engine.use_mouse_offset:
        xoff = random.uniform(-click_engine.mouse_offset_x, click_engine.mouse_offset_x)
        yoff = random.uniform(-click_engine.mouse_offset_y, click_engine.mouse_offset_y)
        pos = autoit.mouse_get_pos()
        autoit.mouse_move(x=int(xoff + pos[0]), y=int(yoff + pos[1]), speed=0)

    if click_engine.custom_position and not position and not ghostClick:
        autoit.mouse_move(x=MousepositionX, y=MousepositionY, speed=0)

    if click_engine.hold_duration > 0:
        autoit.mouse_down(button=button)
        time.sleep(click_engine.hold_duration)
        autoit.mouse_up(button=button)
    else:
        autoit.mouse_click(button=button, clicks=click_engine.click_type)

click_engine.on_click = perform_click_fallback

def toggle_clicker(e):
    if 'down' not in e:
        return
    global clicking, pressButton, ghostClick, restrictingClicker

    if recording or saving or gettingPosition:
        return

    pressButton = mouseButton_entry.get()
    restrictingClicker = restrict_windows.get()
    ghostClick = ghostClick_switch.get()

    if not clicking:
        if check() is False:
            return
        # Configure engine
        click_engine.delay_ms = delay
        click_engine.click_offset_ms = Clickoffset
        click_engine.use_direct_input = not ghostClick_switch.get()
        click_engine.use_interval_offset = interval_switch.get()
        click_engine.use_mouse_offset = mouse_switch.get()
        click_engine.mouse_offset_x = MouseoffsetX
        click_engine.mouse_offset_y = MouseoffsetY
        click_engine.button = pressButton
        click_engine.custom_position = position_var.get() == 1
        click_engine.position_x = MousepositionX
        click_engine.position_y = MousepositionY
        click_engine.alternating = alternatingBox.get()
        click_engine.repeating = repeat_var.get() == 1
        click_engine.repeat_count = repeats
        click_engine.hold_duration = holding
        ct = mouseType_entry.get()
        click_engine.click_type = 2 if ct == 'Double' else 3 if ct == 'Triple' else 1

        # Multi-point
        mp_text = multipoint_entry.get('1.0', 'end').strip()
        if mp_text:
            pts = []
            for ln in mp_text.splitlines():
                parts = ln.strip().split(',')
                if len(parts) == 2:
                    try:
                        pts.append((int(parts[0].strip()), int(parts[1].strip())))
                    except ValueError:
                        pass
            click_engine.multi_points = pts
        else:
            click_engine.multi_points = []

        click_engine.start()
        clicking = True
        autoStart.configure(state='disabled')
        autoStop.configure(state='enabled')
        showStatus.configure(text='Status: Clicking')
    else:
        click_engine.stop()
        clicking = False
        autoStart.configure(state='enabled')
        autoStop.configure(state='disabled')
        showStatus.configure(text='Status: Stopped')

# ============================================================
# CPS DISPLAY (efficient — only updates when clicking)
# ============================================================
def update_cps():
    if clicking:
        c = cps.cps
        t = cps.total
        root.title(f'{title} | CPS: {c} | Total: {t}')
        root.after(200, update_cps)
    else:
        root.title(title)

# ============================================================
# MACRO RECORDING — structured events, thread-safe GUI updates
# ============================================================
_recorded_events = []

def _on_mouse_event(event):
    """Store mouse event as structured tuple for reliable parsing."""
    t = time.perf_counter()
    s = str(event)
    if s.startswith('MoveEvent'):
        try:
            parts = s[:-1].strip().split()
            x = parts[0].replace('MoveEvent(', '').replace('x=', '').rstrip(',')
            y = parts[1].replace('y=', '').rstrip(',')
            _recorded_events.append(('move', int(x), int(y), t))
        except (ValueError, IndexError):
            pass
    elif s.startswith('ButtonEvent'):
        try:
            parts = s[:-1].strip().split()
            evt_type = parts[0].split('=')[1].rstrip(',')
            if 'double' in evt_type:
                evt_type = 'down'
            btn = parts[1].replace('button=', '').replace("'", '').rstrip(',').rstrip(')')
            _recorded_events.append(('button', evt_type, btn, t))
        except (ValueError, IndexError):
            pass
    elif s.startswith('WheelEvent'):
        try:
            parts = s[:-1].strip().split()
            delta = parts[0].split('=')[1].rstrip(',')
            _recorded_events.append(('wheel', int(float(delta)), t))
        except (ValueError, IndexError):
            pass

def _on_keyboard_event(event):
    """Store keyboard event as structured tuple."""
    t = time.perf_counter()
    try:
        name = event.name
        etype = event.event_type
        if name and 'unknown' not in name.lower():
            _recorded_events.append(('key', name, etype, t))
    except AttributeError:
        pass

def checkMacro(e):
    global _recorded_events, recording
    if 'down' not in e:
        return
    if clicking or playing or saving or recording:
        return
    doKeyboard = keyboardMacro_switch.get()
    doMouse = MouseMacro_switch.get()
    if not doKeyboard and not doMouse:
        showWarning.configure(text='Warning: Both capture modes disabled', text_color='red')
        return
    showWarning.configure(text='Warning: None', text_color=('black', 'white'))
    showStatus.configure(text='Status: Recording')
    MacroRecord.configure(state='disabled')
    MacroPlay.configure(state='disabled')
    MacroStop.configure(state='enabled')
    macroContent.configure(state='disabled')
    recording = True
    _recorded_events = []
    if doMouse:
        mouse.hook(_on_mouse_event)
    if doKeyboard:
        keyboard.hook(_on_keyboard_event)

def stopMacro(e):
    if 'down' not in e:
        return
    global recording, playing, saving
    if recording:
        recording = False
        MacroStop.configure(text='Stopping', state='disabled')
        showStatus.configure(text='Status: Saving Macro')
        try:
            mouse.unhook(_on_mouse_event)
        except Exception:
            pass
        try:
            keyboard.unhook(_on_keyboard_event)
        except Exception:
            pass
        initiate_hotkeys()
        threading.Thread(target=_save_recorded_macro, daemon=True).start()
    elif playing:
        macro_eng.stop()
        playing = False
        showStatus.configure(text='Status: Stopped')
        MacroRecord.configure(state='enabled')
        MacroPlay.configure(state='enabled')
        MacroStop.configure(state='disabled')
        macroContent.configure(state='normal')

def _save_recorded_macro():
    """Process structured events into macro commands. GUI updates via root.after()."""
    global saving
    saving = True
    result_lines = []
    last_time = 0.0
    last_xy = (None, None)
    skip_keys = {clickerHotkey.lower(), macroPlayHotkey.lower(),
                 macroStopHotkey.lower(), macroRecordHotkey.lower()}

    for ev in _recorded_events:
        try:
            if ev[0] == 'move':
                _, x, y, t = ev
                if (x, y) != last_xy:
                    if last_time:
                        result_lines.append(f'Delay {round(t - last_time, 4)}')
                    last_time = t
                    last_xy = (x, y)
                    result_lines.append(f'MoveEvent x={x} y={y}')

            elif ev[0] == 'button':
                _, evt_type, btn, t = ev
                if last_time:
                    result_lines.append(f'Delay {round(t - last_time, 4)}')
                last_time = t
                result_lines.append(f'ButtonEvent type={evt_type} button={btn}')

            elif ev[0] == 'wheel':
                _, delta, t = ev
                if last_time:
                    result_lines.append(f'Delay {round(t - last_time, 4)}')
                last_time = t
                result_lines.append(f'WheelEvent delta={delta}')

            elif ev[0] == 'key':
                _, name, etype, t = ev
                if name.lower() in skip_keys:
                    continue
                if last_time:
                    result_lines.append(f'Delay {round(t - last_time, 4)}')
                last_time = t
                result_lines.append(f'KeyboardEvent {name} {etype}')

        except Exception:
            continue

    macro_text = '\n'.join(result_lines)
    try:
        with open('Macros/lastMacro.txt', 'w') as f:
            f.write(macro_text)
    except IOError:
        pass

    # Thread-safe GUI update — schedule on main thread
    def _update_gui():
        global saving
        macroContent.configure(state='normal')
        macroContent.delete('0.0', 'end')
        macroContent.insert('0.0', macro_text)
        files = [x.split('.')[0] for x in os.listdir('Macros')]
        MacroFile.configure(values=files)
        showStatus.configure(text='Status: Stopped')
        showWarning.configure(text='Warning: None', text_color=('black', 'white'))
        MacroRecord.configure(state='enabled')
        MacroPlay.configure(state='enabled')
        MacroStop.configure(text=f'Stop ({macroStopHotkey})', state='disabled')
        saving = False

    root.after(0, _update_gui)

def startMacro(e):
    if 'down' not in e:
        return
    global playing
    if playing or saving or recording:
        return

    # Configure macro engine
    rp = safe_int(macroRepeatTimes, 1)
    macro_eng.use_repeat = repeatMacro_var.get() == 1
    macro_eng.repeat_count = rp if rp else 1
    od = safe_float(macroDelayOverrideEntry, 0)
    macro_eng.delay_override = od if overrideMacro_switch.get() and od else None
    macro_eng.use_delay_offset = DelayOffSetMacro_switch.get()
    macro_eng.delay_offset = safe_float(macroDelayOffsetEntry, 0.05) or 0.05

    # Wire callbacks
    macro_eng.do_mouse_move = lambda x, y, s: autoit.mouse_move(x=x, y=y, speed=s)
    macro_eng.do_mouse_click = lambda b: autoit.mouse_click(button=b)
    macro_eng.do_mouse_click_at = lambda b, x, y, s: autoit.mouse_click(button=b, x=x, y=y, speed=s)
    macro_eng.do_mouse_down = lambda b: autoit.mouse_down(button=b)
    macro_eng.do_mouse_up = lambda b: autoit.mouse_up(button=b)
    macro_eng.do_mouse_wheel = lambda d, c: autoit.mouse_wheel(direction=d, clicks=c)
    macro_eng.do_mouse_drag = lambda b, s, x1, y1, x2, y2: autoit.mouse_click_drag(button=b, speed=s, x1=x1, y1=y1, x2=x2, y2=y2)
    macro_eng.do_key_press = lambda k: keyboard.press_and_release(k)
    macro_eng.do_key_down = lambda k: keyboard.press(k)
    macro_eng.do_key_up = lambda k: keyboard.release(k)
    macro_eng.do_type_text = lambda t, d: keyboard.write(text=t, delay=d)
    macro_eng.do_warn = lambda ln, msg: root.after(0, lambda: showWarning.configure(
        text=f'Warning: L{ln}: {msg[:30]}', text_color='orange'))

    playing = True
    showStatus.configure(text='Status: Playing Macro')
    MacroRecord.configure(state='disabled')
    MacroPlay.configure(state='disabled')
    MacroStop.configure(state='enabled')
    macroContent.configure(state='disabled')
    macro_eng.play(macroContent.get('0.0', 'end').rstrip())

    def _watch():
        global playing
        if macro_eng.is_playing:
            root.after(200, _watch)
        else:
            playing = False
            showStatus.configure(text='Status: Stopped')
            MacroRecord.configure(state='enabled')
            MacroPlay.configure(state='enabled')
            MacroStop.configure(state='disabled')
            macroContent.configure(state='normal')
    root.after(200, _watch)

# ============================================================
# FILE OPERATIONS
# ============================================================
def openFile(name):
    macroContent.delete('0.0', 'end')
    try:
        with open(f'Macros/{name}.txt', 'r') as f:
            macroContent.insert('0.0', f.read())
    except FileNotFoundError:
        showWarning.configure(text=f'Warning: {name} not found', text_color='red')

def saveFile():
    fn = MacroFile.get()
    with open(f'Macros/{fn}.txt', 'w') as f:
        f.write(macroContent.get('0.0', 'end'))
    files = [x.split('.')[0] for x in os.listdir('Macros')]
    MacroFile.configure(values=files)

def deleteFile():
    fn = MacroFile.get()
    try:
        os.remove(f'Macros/{fn}.txt')
        files = [x.split('.')[0] for x in os.listdir('Macros')]
        MacroFile.configure(values=files)
        macroContent.delete('0.0', 'end')
    except FileNotFoundError:
        showWarning.configure(text=f'Warning: {fn} not found', text_color='red')

# ============================================================
# SETTINGS HELPERS (consolidated — eliminates 4x duplication)
# ============================================================
def _save_s():
    save_settings(settings)

def change_hotkey(name, current_val, label_widget, button_widgets, disallowed):
    """Generic hotkey changer — replaces 4 duplicate functions."""
    window = customtkinter.CTkToplevel()
    window.title(f'Update {name} Key')
    window.geometry('250x100')
    window.attributes('-topmost', True)
    window.grab_set()
    window.resizable(False, False)
    customtkinter.CTkLabel(master=window, text='Press any key to set hotkey',
                          fg_color='grey', corner_radius=8).place(relx=0.5, rely=0.5, anchor=tkinter.CENTER)
    keyboard.unhook_all()

    def on_key(event):
        key = event.name.upper()
        if key in disallowed:
            showWarning.configure(text='Warning: Key already bound', text_color='red')
            return
        settings[current_val] = key
        _save_s()
        for w, fmt in button_widgets:
            w.configure(text=fmt.format(key))
        window.destroy()
        keyboard.unhook_all()
        initiate_hotkeys()
        # Update macro_eng hotkeys
        macro_eng.hotkeys = {settings['clickerHotkey'].lower(), settings['macroRecordHotkey'].lower(),
                             settings['macroStopHotkey'].lower(), settings['macroPlayHotkey'].lower()}
    keyboard.on_press(on_key)

# ============================================================
# WINDOW LIST
# ============================================================
windows = {}

def get_window_list():
    global windows
    try:
        def handler(hwnd, result):
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd)
                result[t if t else 'Any Window'] = hwnd
        windows = {}
        win32gui.EnumWindows(handler, windows)
        windows_entry.configure(values=list(windows.keys()))
    except Exception:
        showWarning.configure(text='Warning: Error retrieving windows', text_color='red')

def updateWindows(extra):
    global control_window
    control_window = 0
    if ghostClick_switch.get() and settings.get('showMousePosition'):
        for key in windows:
            if key == windows_entry.get():
                control_window = {key: windows[key]}
       # ============================================================
# MOUSE POSITION (optimized to 150ms to save RAM/CPU)
# ============================================================
def applyMousePosition():
    if settings.get('showMousePosition') and root.state() != 'iconic':
        try:
            pos = autoit.mouse_get_pos()
            new_text = f'Mouse: {pos}'
            if showMouse.cget("text") != new_text:
                showMouse.configure(text=new_text)
        except Exception:
            pass
        root.after(150, applyMousePosition)
    else:
        if showMouse.cget("text") != '':
            showMouse.configure(text='')
        root.after(500, applyMousePosition)

# ============================================================
# BUILD GUI (Modern CTkTabview & Grid Layout)
# ============================================================
tabview = customtkinter.CTkTabview(master=root, width=830, height=450)
tabview.pack(padx=10, pady=5, fill="both", expand=True)

clickFrame = tabview.add("Auto Clicker")
macroFrame = tabview.add("Macro")
settingFrame = tabview.add("Settings")

# --- AUTOCLICKER TAB ---
# Row 1: Click Interval
clickInterval = customtkinter.CTkFrame(master=clickFrame)
clickInterval.pack(fill="x", pady=5, padx=5)
customtkinter.CTkLabel(master=clickInterval, text='Click Interval:', font=('', 13, 'bold')).grid(row=0, column=0, padx=10, pady=5, sticky='w')

f_int = customtkinter.CTkFrame(master=clickInterval, fg_color="transparent")
f_int.grid(row=1, column=0, padx=10, pady=5, sticky='w')
customtkinter.CTkLabel(master=f_int, text='ms:').pack(side="left")
mil_interval = customtkinter.CTkEntry(master=f_int, placeholder_text='0', width=60)
mil_interval.pack(side="left", padx=5)
customtkinter.CTkLabel(master=f_int, text='sec:').pack(side="left", padx=(10,0))
sec_interval = customtkinter.CTkEntry(master=f_int, placeholder_text='0', width=60)
sec_interval.pack(side="left", padx=5)
customtkinter.CTkLabel(master=f_int, text='min:').pack(side="left", padx=(10,0))
min_interval = customtkinter.CTkEntry(master=f_int, placeholder_text='0', width=60)
min_interval.pack(side="left", padx=5)
customtkinter.CTkLabel(master=f_int, text='hr:').pack(side="left", padx=(10,0))
hour_interval = customtkinter.CTkEntry(master=f_int, placeholder_text='0', width=60)
hour_interval.pack(side="left", padx=5)

f_sched = customtkinter.CTkFrame(master=clickInterval, fg_color="transparent")
f_sched.grid(row=1, column=1, padx=(40, 10), pady=5, sticky='w')
customtkinter.CTkLabel(master=f_sched, text='Start after(s):').grid(row=0, column=0, padx=5, sticky='e')
sched_delay_entry = customtkinter.CTkEntry(master=f_sched, placeholder_text='0', width=50)
sched_delay_entry.grid(row=0, column=1, padx=5)
customtkinter.CTkLabel(master=f_sched, text='Stop after(s):').grid(row=1, column=0, padx=5, sticky='e')
sched_stop_entry = customtkinter.CTkEntry(master=f_sched, placeholder_text='0', width=50)
sched_stop_entry.grid(row=1, column=1, padx=5)

# Row 2: Offsets
f_row2 = customtkinter.CTkFrame(master=clickFrame, fg_color="transparent")
f_row2.pack(fill="x", pady=5, padx=5)

interval_offset = customtkinter.CTkFrame(master=f_row2)
interval_offset.pack(side="left", fill="x", expand=True, padx=(0, 5))
interval_switch = customtkinter.CTkSwitch(master=interval_offset, text='Interval offset (ms):', font=('', 12, 'bold'))
interval_switch.pack(anchor='w', padx=10, pady=5)
f_io = customtkinter.CTkFrame(master=interval_offset, fg_color="transparent")
f_io.pack(anchor='w', padx=10, pady=5)
customtkinter.CTkLabel(master=f_io, text='ms:').pack(side='left')
interval_entry = customtkinter.CTkEntry(master=f_io, placeholder_text='50', width=70)
interval_entry.pack(side='left', padx=5)

mouse_offset = customtkinter.CTkFrame(master=f_row2)
mouse_offset.pack(side="left", fill="x", expand=True, padx=(5, 0))
mouse_switch = customtkinter.CTkSwitch(master=mouse_offset, text='Mouse offset (px):', font=('', 12, 'bold'))
mouse_switch.pack(anchor='w', padx=10, pady=5)
f_mo = customtkinter.CTkFrame(master=mouse_offset, fg_color="transparent")
f_mo.pack(anchor='w', padx=10, pady=5)
customtkinter.CTkLabel(master=f_mo, text='X:').pack(side='left')
mouseX_entry = customtkinter.CTkEntry(master=f_mo, placeholder_text='25', width=50)
mouseX_entry.pack(side='left', padx=5)
customtkinter.CTkLabel(master=f_mo, text='Y:').pack(side='left', padx=(10,0))
mouseY_entry = customtkinter.CTkEntry(master=f_mo, placeholder_text='25', width=50)
mouseY_entry.pack(side='left', padx=5)

# Row 3: Click Options
clickOption = customtkinter.CTkFrame(master=clickFrame)
clickOption.pack(fill="x", pady=5, padx=5)
customtkinter.CTkLabel(master=clickOption, text='Click Options:', font=('', 13, 'bold')).pack(anchor='w', padx=10, pady=(5,0))
f_co = customtkinter.CTkFrame(master=clickOption, fg_color="transparent")
f_co.pack(fill="x", padx=10, pady=5)
customtkinter.CTkLabel(master=f_co, text='Button:').pack(side='left')
mouseButton_entry = customtkinter.CTkOptionMenu(master=f_co, values=['Left', 'Right', 'Middle'], width=90)
mouseButton_entry.pack(side='left', padx=5)
customtkinter.CTkLabel(master=f_co, text='Type:').pack(side='left', padx=(15,0))
mouseType_entry = customtkinter.CTkOptionMenu(master=f_co, values=['Single', 'Double', 'Triple'], width=90)
mouseType_entry.pack(side='left', padx=5)
customtkinter.CTkLabel(master=f_co, text='Hold(s):').pack(side='left', padx=(15,0))
holdDuration = customtkinter.CTkEntry(master=f_co, placeholder_text='0', width=50)
holdDuration.pack(side='left', padx=5)
alternatingBox = customtkinter.CTkCheckBox(master=f_co, text='Alternating', onvalue=True, offvalue=False)
alternatingBox.pack(side='left', padx=(15,0))

# Row 4: Targeting & Repeat
f_row4 = customtkinter.CTkFrame(master=clickFrame, fg_color="transparent")
f_row4.pack(fill="x", pady=5, padx=5)

cursorPosition = customtkinter.CTkFrame(master=f_row4)
cursorPosition.pack(side="left", fill="both", expand=True, padx=(0, 5))
customtkinter.CTkLabel(master=cursorPosition, text='Cursor Position:', font=('', 13, 'bold')).pack(anchor='w', padx=10, pady=5)
position_var = tkinter.IntVar(value=0)
f_cp1 = customtkinter.CTkFrame(master=cursorPosition, fg_color="transparent")
f_cp1.pack(anchor='w', padx=10)
customtkinter.CTkRadioButton(master=f_cp1, text='Current', variable=position_var, value=0).pack(side='left', pady=2)
f_cp2 = customtkinter.CTkFrame(master=cursorPosition, fg_color="transparent")
f_cp2.pack(anchor='w', padx=10)
customtkinter.CTkRadioButton(master=f_cp2, text='Custom  X:', variable=position_var, value=1).pack(side='left', pady=2)
mouseX_position = customtkinter.CTkEntry(master=f_cp2, placeholder_text='0', width=45)
mouseX_position.pack(side='left', padx=5)
customtkinter.CTkLabel(master=f_cp2, text='Y:').pack(side='left')
mouseY_position = customtkinter.CTkEntry(master=f_cp2, placeholder_text='0', width=45)
mouseY_position.pack(side='left', padx=5)

mpFrame = customtkinter.CTkFrame(master=f_row4)
mpFrame.pack(side="left", fill="both", expand=True, padx=5)
customtkinter.CTkLabel(master=mpFrame, text='Multi-Point (x,y):', font=('', 13, 'bold')).pack(anchor='w', padx=10, pady=5)
multipoint_entry = customtkinter.CTkTextbox(master=mpFrame, width=150, height=50)
multipoint_entry.pack(padx=10, pady=(0,5))

autoController = customtkinter.CTkFrame(master=f_row4)
autoController.pack(side="left", fill="both", expand=True, padx=(5, 0))
customtkinter.CTkLabel(master=autoController, text='Repeat:', font=('', 13, 'bold')).pack(anchor='w', padx=10, pady=5)
repeat_var = tkinter.IntVar(value=0)
customtkinter.CTkRadioButton(master=autoController, text='Toggle', variable=repeat_var, value=0).pack(anchor='w', padx=10, pady=2)
f_rep = customtkinter.CTkFrame(master=autoController, fg_color="transparent")
f_rep.pack(anchor='w', padx=10, pady=2)
customtkinter.CTkRadioButton(master=f_rep, text='Repeat', variable=repeat_var, value=1).pack(side='left')
repeatTimes = customtkinter.CTkEntry(master=f_rep, placeholder_text='1', width=50)
repeatTimes.pack(side='left', padx=5)

# Row 5: Actions
f_actions = customtkinter.CTkFrame(master=clickFrame, fg_color="transparent")
f_actions.pack(pady=10)
autoStart = customtkinter.CTkButton(master=f_actions, text=f'Start ({clickerHotkey})', command=lambda: toggle_clicker('down'), width=150, height=35)
autoStart.pack(side='left', padx=10)
autoStop = customtkinter.CTkButton(master=f_actions, text=f'Stop ({clickerHotkey})', state='disabled', command=lambda: toggle_clicker('down'), width=150, height=35, fg_color="#C0392B", hover_color="#922B21")
autoStop.pack(side='left', padx=10)


# --- MACRO TAB ---
macroOptions = customtkinter.CTkFrame(master=macroFrame)
macroOptions.pack(fill="x", pady=5, padx=5)

f_mco = customtkinter.CTkFrame(master=macroOptions, fg_color="transparent")
f_mco.pack(side='left', fill='both', expand=True, padx=10, pady=5)
customtkinter.CTkLabel(master=f_mco, text='Capture:', font=('', 13, 'bold')).pack(anchor='w')
keyboardMacro_switch = customtkinter.CTkSwitch(master=f_mco, text='Keyboard', variable=customtkinter.BooleanVar(value=True))
keyboardMacro_switch.pack(anchor='w', pady=2)
MouseMacro_switch = customtkinter.CTkSwitch(master=f_mco, text='Mouse', variable=customtkinter.BooleanVar(value=True))
MouseMacro_switch.pack(anchor='w', pady=2)

f_mdo = customtkinter.CTkFrame(master=macroOptions, fg_color="transparent")
f_mdo.pack(side='left', fill='both', expand=True, padx=10, pady=5)
customtkinter.CTkLabel(master=f_mdo, text='Delay Options:', font=('', 13, 'bold')).pack(anchor='w')
f_mdo1 = customtkinter.CTkFrame(master=f_mdo, fg_color="transparent")
f_mdo1.pack(anchor='w', pady=2)
overrideMacro_switch = customtkinter.CTkSwitch(master=f_mdo1, text='Override')
overrideMacro_switch.pack(side='left')
macroDelayOverrideEntry = customtkinter.CTkEntry(master=f_mdo1, placeholder_text='0', width=45, height=23)
macroDelayOverrideEntry.pack(side='left', padx=5)
f_mdo2 = customtkinter.CTkFrame(master=f_mdo, fg_color="transparent")
f_mdo2.pack(anchor='w', pady=2)
DelayOffSetMacro_switch = customtkinter.CTkSwitch(master=f_mdo2, text='Offset')
DelayOffSetMacro_switch.pack(side='left')
macroDelayOffsetEntry = customtkinter.CTkEntry(master=f_mdo2, placeholder_text='.05', width=45, height=23)
macroDelayOffsetEntry.pack(side='left', padx=5)

f_mro = customtkinter.CTkFrame(master=macroOptions, fg_color="transparent")
f_mro.pack(side='left', fill='both', expand=True, padx=10, pady=5)
customtkinter.CTkLabel(master=f_mro, text='Repeat:', font=('', 13, 'bold')).pack(anchor='w')
repeatMacro_var = tkinter.IntVar(value=0)
customtkinter.CTkRadioButton(master=f_mro, text='Toggle', variable=repeatMacro_var, value=0).pack(anchor='w', pady=2)
f_mro1 = customtkinter.CTkFrame(master=f_mro, fg_color="transparent")
f_mro1.pack(anchor='w', pady=2)
customtkinter.CTkRadioButton(master=f_mro1, text='Repeat', variable=repeatMacro_var, value=1).pack(side='left')
macroRepeatTimes = customtkinter.CTkEntry(master=f_mro1, placeholder_text='1', width=50)
macroRepeatTimes.pack(side='left', padx=5)

f_macfile = customtkinter.CTkFrame(master=macroFrame, fg_color="transparent")
f_macfile.pack(fill="x", pady=5, padx=5)
files = os.listdir('Macros')
if not files:
    files = ['Macro 1']
else:
    files = [x.split('.')[0] for x in files]
MacroFile = customtkinter.CTkComboBox(master=f_macfile, width=350, values=files, command=openFile)
MacroFile.pack(side='left', padx=(5,10))
customtkinter.CTkButton(master=f_macfile, text='Save', width=95, command=saveFile).pack(side='left', padx=5)
customtkinter.CTkButton(master=f_macfile, text='Delete', width=95, command=deleteFile, fg_color="#C0392B", hover_color="#922B21").pack(side='left', padx=5)

macroContent = customtkinter.CTkTextbox(master=macroFrame, width=780, height=200)
macroContent.pack(padx=5, pady=5)
if files[0] == 'Macro 1' and not os.path.exists('Macros/Macro 1.txt'):
    macroContent.insert('0.0', 'Macro Contents:\nNew commands: Loop N / EndLoop / RandomDelay MIN MAX\nView help for details')
else:
    try:
        with open(f'Macros/{files[0]}.txt', 'r') as f:
            macroContent.insert('0.0', f.read())
    except FileNotFoundError:
        pass

f_macact = customtkinter.CTkFrame(master=macroFrame, fg_color="transparent")
f_macact.pack(pady=10)
MacroRecord = customtkinter.CTkButton(master=f_macact, text=f'Record ({macroRecordHotkey})', command=lambda: checkMacro('down'), width=140, height=35)
MacroRecord.pack(side='left', padx=10)
MacroStop = customtkinter.CTkButton(master=f_macact, text=f'Stop ({macroStopHotkey})', state='disabled', command=lambda: stopMacro('down'), width=140, height=35, fg_color="#C0392B", hover_color="#922B21")
MacroStop.pack(side='left', padx=10)
MacroPlay = customtkinter.CTkButton(master=f_macact, text=f'Play ({macroPlayHotkey})', command=lambda: startMacro('down'), width=140, height=35)
MacroPlay.pack(side='left', padx=10)


# --- SETTINGS TAB ---
f_settop = customtkinter.CTkFrame(master=settingFrame, fg_color="transparent")
f_settop.pack(fill='both', expand=True, padx=5, pady=5)

hotkeypage = customtkinter.CTkFrame(master=f_settop)
hotkeypage.pack(side='left', fill='both', expand=True, padx=(0,5))
customtkinter.CTkLabel(master=hotkeypage, text='Keybinds:', font=('', 13, 'bold')).pack(anchor='w', padx=10, pady=5)

for i, (label, key_name) in enumerate([
    ('Autoclicker', 'clickerHotkey'), ('Macro Record', 'macroRecordHotkey'),
    ('Macro Stop', 'macroStopHotkey'), ('Macro Play', 'macroPlayHotkey')
]):
    hkf = customtkinter.CTkFrame(master=hotkeypage, fg_color="transparent")
    hkf.pack(fill='x', padx=10, pady=2)
    customtkinter.CTkLabel(master=hkf, text=f'{label} Hotkey:').pack(side='left')
    btn = customtkinter.CTkButton(master=hkf, text=f'({settings[key_name]})', width=60)
    btn.pack(side='right')

customtkinter.CTkLabel(master=hotkeypage, text='Appearance:', font=('', 13, 'bold')).pack(anchor='w', padx=10, pady=(15,5))
f_app = customtkinter.CTkFrame(master=hotkeypage, fg_color="transparent")
f_app.pack(fill='x', padx=10, pady=2)
customtkinter.CTkLabel(master=f_app, text='Mode:').pack(side='left')
customtkinter.CTkOptionMenu(master=f_app, values=['System', 'Dark', 'Light'],
    variable=customtkinter.StringVar(value=settings['appearanceMode']),
    command=lambda v: (customtkinter.set_appearance_mode(v),
                       settings.update({'appearanceMode': v}), _save_s()),
    width=100).pack(side='right')

f_thm = customtkinter.CTkFrame(master=hotkeypage, fg_color="transparent")
f_thm.pack(fill='x', padx=10, pady=2)
customtkinter.CTkLabel(master=f_thm, text='Theme:').pack(side='left')
customtkinter.CTkOptionMenu(master=f_thm, values=['green', 'blue', 'dark-blue'],
    variable=customtkinter.StringVar(value=settings['themeColor']),
    command=lambda v: (settings.update({'themeColor': v}), _save_s(),
        showWarning.configure(text='Warning: Restart needed', text_color='orange')),
    width=100).pack(side='right')

# Profile Section
profileFrame = customtkinter.CTkFrame(master=hotkeypage)
profileFrame.pack(fill='x', padx=10, pady=15)
customtkinter.CTkLabel(master=profileFrame, text='Profiles:', font=('', 13, 'bold')).pack(anchor='w', padx=5, pady=(5,0))
f_prof = customtkinter.CTkFrame(master=profileFrame, fg_color="transparent")
f_prof.pack(fill='x', padx=5, pady=5)
profile_dropdown = customtkinter.CTkOptionMenu(master=f_prof, values=profile_mgr.list_profiles() or ['Default'], width=100)
profile_dropdown.pack(side='left')
customtkinter.CTkButton(master=f_prof, text='Save', width=50,
    command=lambda: profile_mgr.save_profile(profile_dropdown.get(), {
        'delay': mil_interval.get(), 'button': mouseButton_entry.get(),
        'type': mouseType_entry.get()
    })
).pack(side='left', padx=5)
customtkinter.CTkButton(master=f_prof, text='Load', width=50,
    command=lambda: None  # TODO: apply profile
).pack(side='left')

generalsettings = customtkinter.CTkFrame(master=f_settop)
generalsettings.pack(side='left', fill='both', expand=True, padx=(5,0))
customtkinter.CTkLabel(master=generalsettings, text='General Settings:', font=('', 13, 'bold')).pack(anchor='w', padx=10, pady=5)

onTop_switch = customtkinter.CTkSwitch(master=generalsettings, text='Always on top',
    variable=customtkinter.BooleanVar(value=settings['onTop']),
    command=lambda: (root.attributes('-topmost', onTop_switch.get()),
                     settings.update({'onTop': onTop_switch.get()}), _save_s())) # Changed from generalsettings to root for attributes (wait, it was root.attributes)
onTop_switch.pack(anchor='w', padx=10, pady=5)

mouseSetting_switch = customtkinter.CTkSwitch(master=generalsettings, text='Show mouse position',
    variable=customtkinter.BooleanVar(value=settings['showMousePosition']),
    command=lambda: (settings.update({'showMousePosition': mouseSetting_switch.get()}), _save_s()))
mouseSetting_switch.pack(anchor='w', padx=10, pady=5)

superClicker_switch = customtkinter.CTkSwitch(master=generalsettings, text='Superclicker',
    variable=customtkinter.BooleanVar(value=superClicker))
superClicker_switch.pack(anchor='w', padx=10, pady=5)

mouseTimer_switch = customtkinter.CTkSwitch(master=generalsettings, text='Click delay timer',
    variable=customtkinter.BooleanVar(value=settings['mouseTimer']))
mouseTimer_switch.pack(anchor='w', padx=10, pady=5)

ghostClick_switch = customtkinter.CTkSwitch(master=generalsettings, text='Ghost click',
    variable=customtkinter.BooleanVar(value=False))
ghostClick_switch.pack(anchor='w', padx=10, pady=5)

f_winres = customtkinter.CTkFrame(master=generalsettings, fg_color="transparent")
f_winres.pack(anchor='w', padx=10, pady=5)
restrict_windows = customtkinter.CTkSwitch(master=f_winres, text='Restrict to window:',
    variable=customtkinter.BooleanVar(value=False))
restrict_windows.pack(side='left')
customtkinter.CTkButton(master=f_winres, text='Refresh', command=get_window_list,
    height=24, width=65, corner_radius=100).pack(side='left', padx=10)
windows_entry = customtkinter.CTkOptionMenu(master=generalsettings, values=['Any Window'],
    width=280, dynamic_resizing=False, command=updateWindows)
windows_entry.pack(anchor='w', padx=10, pady=5)

changelog = customtkinter.CTkTextbox(master=settingFrame, height=100)
changelog.pack(fill='x', padx=5, pady=(0, 5))
try:
    with open('changelog.txt', 'r') as f:
        changelog.insert('0.0', f.read())
except FileNotFoundError:
    changelog.insert('0.0', 'v3.0.0-zero-latency: Modernized GUI Tabview, Zero-Latency Engine, Direct Win32 inputs, CPS lock-free Counter, Memory Optimized loops')
changelog.configure(state='disabled')


# --- STATUS BAR ---
statusBar = customtkinter.CTkFrame(master=root, height=30, fg_color=("gray90", "gray13"))
statusBar.pack(side="bottom", fill="x")

# Fixed the CTRL+SHIFT+K label since it was lost in the sidebar removal
killSwitchLbl = customtkinter.CTkLabel(master=statusBar, text='[CTRL+SHIFT+K] Kill Switch', font=('', 12, 'bold'), text_color="#C0392B")
killSwitchLbl.pack(side="left", padx=10)

showWarning = customtkinter.CTkLabel(master=statusBar, text='')
showWarning.pack(side="left", padx=20)

showStatus = customtkinter.CTkLabel(master=statusBar, text='Status: Stopped', font=('', 14, 'bold'))
showStatus.pack(side="right", padx=10)

showMouse = customtkinter.CTkLabel(master=statusBar, text='')
showMouse.pack(side="right", padx=20)

# --- INIT ---
applyMousePosition()
get_window_list()
updateWindows(None)
mil_interval.insert(0, '0' if superClicker else '1')

# Save window position on close
def on_close():
    try:
        settings['windowX'] = root.winfo_x()
        settings['windowY'] = root.winfo_y()
        _save_s()
    except Exception:
        pass
    click_engine.shutdown()
    macro_eng.stop()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)

# --- START ---
root.mainloop()

if killSwitch:
    try:
        Popen(['taskkill', '/f', '/t', '/pid', str(killSwitch.pid)], creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass
os._exit(0)
