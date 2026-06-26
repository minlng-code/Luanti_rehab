# ================================================================
#  bme_mapper.py — Chuyên gia Điều khiển (Input Mapper)
#  BME Rehabilitation System v6.1
#
#  NGUYÊN TẮC THIẾT KẾ:
#    • Không import serial, không biết Arduino tồn tại
#    • Không đọc/ghi file, không CSV, không PDF
#    • Toàn bộ trạng thái gói trong MapperState (dễ reset/test)
#    • FSR_L (tay trái) chỉ đo Fatigue — KHÔNG gửi lệnh game
#
# ════════════════════════════════════════════════════════════════
#  SƠ ĐỒ ĐIỀU KHIỂN — STATE MACHINE
# ════════════════════════════════════════════════════════════════
#
#  ┌─ STATE 1: GAME MODE (mặc định) ──────────────────────────┐
#  │                                                           │
#  │  TAY TRÁI (Gross Motor — vận động thô):                   │
#  │    Joystick X/Y  →  WASD (di chuyển nhân vật)            │
#  │    B1 tap        →  Space (nhảy)                         │
#  │    B1 hold≥300ms →  Shift giữ (sneak/lén đi)             │
#  │    B2 tap        →  Cuộn hotbar (1→2→3→... slots)        │
#  │    B2 hold≥500ms →  [chuyển sang UI MODE]                │
#  │    FSR_L (406)   →  Chỉ đo mỏi cơ, KHÔNG gửi lệnh game  │
#  │                                                           │
#  │  TAY PHẢI (Fine Motor — vận động tinh):                   │
#  │    MPU Pitch     →  Mouse Y (nhìn lên/xuống)             │
#  │    MPU Roll      →  Mouse X (quay trái/phải)             │
#  │    FSR_R tap     →  Click RMB (đặt block / tương tác)    │
#  │    FSR_R hold≥3s →  Giữ LMB (phá block / đào)            │
#  │                                                           │
#  └───────────────────────────────────────────────────────────┘
#
#  ┌─ STATE 2: UI MODE (Inventory/Menu) ──────────────────────┐
#  │  Kích hoạt: B2 hold ≥ 500ms → gửi phím E                │
#  │  Duy trì: tiếp tục giữ B2 (l2_dur > 0)                  │
#  │  Thoát: nhả B2 (sentinel 65535) → gửi phím E            │
#  │                                                           │
#  │  TAY TRÁI:                                                │
#  │    Tiếp tục giữ B2 để duy trì mở bảng đồ                │
#  │    Joystick WASD vẫn hoạt động (cuộn trong list)         │
#  │                                                           │
#  │  TAY PHẢI (chuyển vai trò → Chuột giả lập):              │
#  │    MPU Pitch/Roll → di CON TRỎ CHUỘT trong inventory     │
#  │                     (sensitivity cao, offset từ anchor)   │
#  │    FSR_R tap     → Click LMB (chọn item / craft)         │
#  │    (không phân biệt tap/hold trong UI)                    │
#  └───────────────────────────────────────────────────────────┘
#
#  HOTBAR CYCLING (B2 tap):
#    Mỗi lần tap → gửi phím số tiếp theo: 1 → 2 → 3 → ... → 9 → 1
#    Vòng lặp 9 slots, khớp với Luanti/Minetest hotbar.
#
#  HAPTIC FEEDBACK:
#    Mapper nhận callable haptic_fn(pwm: int) — optional.
#    bme_controller truyền lambda → _send(ser, f"VIB,{pwm}")
# ================================================================

import time
import ctypes
import threading
import ctypes.wintypes
from pynput.mouse import Controller
_pynput_mouse = Controller()
from dataclasses import dataclass, field
from typing import Callable, Optional

import pydirectinput
pydirectinput.PAUSE = 0

# ════════════════════════════════════════════════════════════
#  BIẾN TOÀN CỤC GÓC MPU — điều khiển được từ bên ngoài mapper
#  Các module khác (bme_controller.py, UI, debug tool...) có thể
#  đọc góc hiện tại hoặc gọi reset_angle_zero() để căn lại.
# ════════════════════════════════════════════════════════════

#: Góc pitch/roll/yaw hiện tại sau filter (°) — cập nhật mỗi 20ms
g_pitch: float = 0.0
g_roll:  float = 0.0
g_yaw:   float = 0.0

#: Tốc độ thay đổi góc giữa 2 frame (°/frame) — dùng để hiển thị
g_dpitch: float = 0.0
g_droll:  float = 0.0
g_dyaw:   float = 0.0

#: Di chuyển chuột frame hiện tại (pixel) — 0 nếu dead zone hoặc chưa vượt ngưỡng
g_mouse_dx: int = 0
g_mouse_dy: int = 0

#: Góc tham chiếu "zero" — reset bằng reset_angle_zero()
g_pitch_zero: float = 0.0
g_roll_zero:  float = 0.0
g_yaw_zero:   float = 0.0

#: Góc tương đối so với zero (= g_pitch - g_pitch_zero)
g_pitch_rel: float = 0.0
g_roll_rel:  float = 0.0
g_yaw_rel:   float = 0.0


def update_global_angles(pitch: float, roll: float, yaw: float = 0.0) -> None:
    """
    Gọi bởi BMEMapper._handle_imu() mỗi frame.
    Cập nhật tất cả biến toàn cục góc + tính delta.
    """
    global g_pitch, g_roll, g_yaw
    global g_dpitch, g_droll, g_dyaw
    global g_pitch_rel, g_roll_rel, g_yaw_rel
    g_dpitch   = pitch - g_pitch
    g_droll    = roll  - g_roll
    g_dyaw     = yaw   - g_yaw
    g_pitch    = pitch
    g_roll     = roll
    g_yaw      = yaw
    g_pitch_rel = pitch - g_pitch_zero
    g_roll_rel  = roll  - g_roll_zero
    g_yaw_rel   = yaw   - g_yaw_zero


def reset_angle_zero(pitch: float = None, roll: float = None, yaw: float = None,
                     mapper=None) -> None:
    """
    Đặt vị trí hiện tại làm góc tham chiếu (zero).
    Truyền mapper=instance để reset base Air Mouse trong mapper state cùng lúc.
    """
    global g_pitch_zero, g_roll_zero, g_yaw_zero
    g_pitch_zero = pitch if pitch is not None else g_pitch
    g_roll_zero  = roll  if roll  is not None else g_roll
    g_yaw_zero   = yaw   if yaw   is not None else g_yaw
    # Reset base của Air Mouse trong mapper state để chuột không nhảy
    if mapper is not None:
        mapper.state.imu_prev_pitch = g_pitch_zero
        mapper.state.imu_prev_roll  = g_roll_zero
        mapper.state.imu_prev_yaw   = g_yaw_zero
    print(f"  [ANGLE] Zero reset: P={g_pitch_zero:.2f}°  R={g_roll_zero:.2f}°  Y={g_yaw_zero:.2f}°")


def get_angle_display() -> str:
    """Trả về chuỗi hiển thị 3 trục góc — dùng trong status line console."""
    bar_p = _angle_bar(g_pitch_rel, scale=45.0)
    bar_r = _angle_bar(g_roll_rel,  scale=45.0)
    bar_y = _angle_bar(g_yaw_rel,   scale=90.0)
    return (
        f"P={g_pitch:+6.1f}°[{bar_p}]  "
        f"R={g_roll:+6.1f}°[{bar_r}]  "
        f"Y={g_yaw:+6.1f}°[{bar_y}]  "
        f"ΔP={g_dpitch:+5.2f} ΔR={g_droll:+5.2f} ΔY={g_dyaw:+5.2f}"
    )


def _angle_bar(val: float, scale: float = 45.0, width: int = 9) -> str:
    """Mini ASCII bar: ████░░░░░ cho góc -scale..+scale."""
    half  = width // 2
    pos   = int(round(val / scale * half))
    pos   = max(-half, min(half, pos))
    mid   = half
    bar   = [" "] * width
    bar[mid] = "|"        # tâm
    if pos > 0:
        for i in range(mid + 1, mid + pos + 1): bar[i] = "█"
    elif pos < 0:
        for i in range(mid + pos, mid): bar[i] = "█"
    return "".join(bar)

# ════════════════════════════════════════════════════════════
#  WIN32 INPUT INJECT — SendInput (keyboard + mouse)
#  Không cần focus, không SetForegroundWindow, bypass UIPI.
#  Dùng _pack_=1 để struct khớp đúng layout Windows ABI.
# ════════════════════════════════════════════════════════════

_user32 = ctypes.windll.user32

# Virtual Key codes
_VK = {
    "w": 0x57, "a": 0x41, "s": 0x53, "d": 0x44,
    "e": 0x45, "i": 0x49,
    "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34, "5": 0x35,
    "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "shift": 0x10,
    "space": 0x20,
}

# Scan codes Set 1 — game/Luanti đọc scancode
_SC = {
    "w": 0x11, "a": 0x1E, "s": 0x1F, "d": 0x20,
    "e": 0x12, "i": 0x17,
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A,
    "shift": 0x2A,
    "space": 0x39,
}

KEYEVENTF_KEYUP    = 0x0002
KEYEVENTF_SCANCODE = 0x0008
INPUT_KEYBOARD     = 1
INPUT_MOUSE        = 0

MOUSEEVENTF_MOVE        = 0x0001
MOUSEEVENTF_LEFTDOWN    = 0x0002
MOUSEEVENTF_LEFTUP      = 0x0004
MOUSEEVENTF_RIGHTDOWN   = 0x0008
MOUSEEVENTF_RIGHTUP     = 0x0010
MOUSEEVENTF_MIDDLEDOWN  = 0x0020
MOUSEEVENTF_MIDDLEUP    = 0x0040


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("_",    _INPUT_UNION),
    ]


_extra = ctypes.c_ulong(0)
_extra_ptr = ctypes.pointer(_extra)


def _send_key(vk: int, sc: int, key_up: bool = False) -> None:
    """Inject keystroke — VK + scancode, không cần focus."""
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0)
    inp = _INPUT(type=INPUT_KEYBOARD,
                 _=_INPUT_UNION(ki=_KEYBDINPUT(
                     wVk=vk, wScan=sc, dwFlags=flags,
                     time=0, dwExtraInfo=_extra_ptr)))
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _send_mouse(flags: int, dx: int = 0, dy: int = 0) -> None:
    """Inject mouse event — move hoặc click, không cần focus."""
    inp = _INPUT(type=INPUT_MOUSE,
                 _=_INPUT_UNION(mi=_MOUSEINPUT(
                     dx=dx, dy=dy, mouseData=0, dwFlags=flags,
                     time=0, dwExtraInfo=_extra_ptr)))
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _get_screen_w() -> int:
    return _user32.GetSystemMetrics(0)   # SM_CXSCREEN

def _get_screen_h() -> int:
    return _user32.GetSystemMetrics(1)   # SM_CYSCREEN


class _WinKeyboard:
    """Keyboard inject qua SendInput."""

    def press(self, key) -> None:
        vk, sc = self._resolve(key)
        if sc:
            _send_key(vk, sc, key_up=False)

    def release(self, key) -> None:
        vk, sc = self._resolve(key)
        if sc:
            _send_key(vk, sc, key_up=True)

    def tap(self, key, delay: float = 0.0) -> None:
        """Press + release non-blocking. delay ignored — uses daemon thread."""
        self.press(key)
        _kb_ref = self
        _key_ref = key
        _wait_time = delay if delay > 0 else 0.08
        def _release_later():
            time.sleep(0.03)
            _kb_ref.release(_key_ref)
        threading.Thread(target=_release_later, daemon=True).start()

    @staticmethod
    def _resolve(key) -> tuple:
        if isinstance(key, str):
            k = key.lower()
        else:
            k = getattr(key, "name", str(key)).lower().replace("key.", "")
        return _VK.get(k, 0), _SC.get(k, 0)


# Shim để code cũ dùng Key.shift / Key.space không bị lỗi
class _KeyShim:
    shift = "shift"
    space = "space"

Key = _KeyShim()

# Không dùng pynput mouse nữa — thay bằng _send_mouse()
# _find_target_hwnd chỉ giữ để in thông tin debug
def _find_target_hwnd() -> int:
    hwnd = _user32.FindWindowW(None, "Luanti")
    if not hwnd:
        hwnd = _user32.FindWindowW(None, "Minetest")
    if not hwnd:
        hwnd = _user32.GetForegroundWindow()
    return hwnd

_TARGET_HWND: int = 0


# ────────────────────────────────────────────────────────────
#  CẤU HÌNH
# ────────────────────────────────────────────────────────────

@dataclass
class MapperConfig:

    # ── Joystick ──────────────────────────────────────────────
    joy_threshold:  int   = 20      # % ngưỡng WASD (-100..+100)

    # ── Camera / Cursor sensitivity ───────────────────────────
    camera_sens:    float = 0.6     # SENSITIVITY
    camera_dzone:   float = 2.0     # DEAD_ZONE
    imu_smooth:     float = 0.5    # SMOOTH  
    ui_sens:        float = 2.8     # pixel / độ — UI MODE (nhạy hơn)
    ui_dzone:       float = 3.0     # deadzone nhỏ hơn trong UI

    # ── Chống crosstalk chéo trục (giật lên/xuống khi quay ngang) ──
    cross_suppress:   float = 0.5   # độ mạnh triệt trục phụ (0=tắt, ~2=mạnh)
    dz_release_ratio: float = 0.6   # hysteresis: nhả deadzone khi |góc| < dzone*tỉ_lệ
    imu_out_floor:    float = 0.18  # px/frame — dưới mức này coi như 0 (chống shimmer ±1px)

    # Adaptive khi tremor
    tremor_sens_scale:      float = 0.60
    tremor_dzone_scale:     float = 1.80
    ui_tremor_sens_scale:   float = 0.70
    ui_tremor_dzone_scale:  float = 2.00

    # ── FSR tay phải — tap vs hold ────────────────────────────
    fsr_threshold:       int   = 20    # % ngưỡng "đang bóp"
    fsr_hold_secs:       float = 0.08  # giây chờ tối thiểu trước khi xét tap/hold
    fsr_hold_break_secs: float = 1.0   # giữ ≥ 1s → phá block (LMB hold)

    # ── B1 — jump vs sneak ────────────────────────────────────
    b1_sneak_secs:  float = 0.30    # giữ ≥ này → Shift (sneak)

    # ── B2 — hotbar cycle vs UI mode ──────────────────────────
    b2_ui_secs:     float = 0.50    # giữ ≥ này → vào UI mode
    b2_hotbar_slots: int  = 9       # số slot hotbar (1..9)

    # ── Haptic PWM ────────────────────────────────────────────
    haptic_fsr_hold_start:  int = 180
    haptic_fsr_hold_end:    int =  60
    haptic_fsr_tap_rmc:     int = 120   # tap → RMB (đặt block)
    haptic_fsr_break_start: int = 200   # hold 3s → bắt đầu phá block (mạnh hơn)
    haptic_ui_click:        int = 100
    haptic_b1_jump:         int = 140
    haptic_b1_sneak_on:     int = 100
    haptic_b1_sneak_off:    int =  60
    haptic_b2_hotbar:       int =  80
    haptic_b2_ui_enter:     int = 160
    haptic_b2_ui_exit:      int = 100



# ────────────────────────────────────────────────────────────
#  CLEANED INPUT
# ────────────────────────────────────────────────────────────

@dataclass
class CleanedInput:
    """
    Snapshot một frame đã lọc — bme_controller điền mỗi 20ms.
    """
    jx:      int   = 0      # Joystick X : -100..+100
    jy:      int   = 0      # Joystick Y : -100..+100

    # B1 duration (ms) — firmware v5.0 gửi duration thay vì bit
    #   0     = không bấm
    #   1-N   = đang giữ N ms
    #   65535 = sentinel — vừa nhả
    b1_dur:  int   = 0

    # B2 duration (ms) — tương tự B1
    b2_dur:  int   = 0

    pitch:   float = 0.0    # Góc gập/ngửa cổ tay phải (°)
    roll:    float = 0.0    # Góc nghiêng cổ tay phải (°)
    yaw:     float = 0.0    # Góc xoay ngang cổ tay phải (°)
    fsr_r_kg: float = 0.0   # Lực bóp tay phải FSR402 (kg, từ firmware pipeline)
    fsr_l_kg: float = 0.0   # Lực bóp tay trái FSR406 (kg, chỉ Fatigue)
    fsr_r:    float = 0.0   # % tay phải (dùng log/dashboard)
    fsr_l:    float = 0.0   # % tay trái (dùng log/dashboard)
    grip:    bool   = False  # Grip bit từ firmware (FSR402 hysteresis)
    tremor:  bool   = False  # Tremor flag
    fs_up:      bool = False
    fs_down:    bool = False
    fs_left:    bool = False
    fs_right:   bool = False
    fs_trigger: bool = False   # Trigger (B) → Jump/Sneak
    fs_thumb:   bool = False   # Thumb → Hotbar/Inventory


# ────────────────────────────────────────────────────────────
#  MAPPER STATE
# ────────────────────────────────────────────────────────────

@dataclass
class MapperState:

    # ── Chế độ ────────────────────────────────────────────────
    ui_mode: bool = False   # False = GAME, True = UI/Inventory

    # ── WASD ──────────────────────────────────────────────────
    joy_keys: dict = field(default_factory=lambda: {
        "w": False, "a": False, "s": False, "d": False
    })
    fs_keys: dict = field(default_factory=lambda: {
        "w": False, "a": False, "s": False, "d": False
    })
    fs_trigger_was:   bool  = False
    fs_trigger_t:     float = 0.0
    fs_trigger_armed: bool  = False
    fs_thumb_was:     bool  = False
    fs_thumb_t:       float = 0.0
    fs_thumb_armed:   bool  = False

    # ── FSR tay phải ──────────────────────────────────────────
    fsr_pressed:    bool  = False
    fsr_press_t:    float = 0.0
    fsr_holding:    bool  = False

    # ── B1 jump/sneak ─────────────────────────────────────────
    b1_sneaking:    bool  = False
    b1_sneak_armed: bool  = False
    b1_press_dur:   int   = 0

    # ── B2 hotbar / UI mode ───────────────────────────────────
    b2_ui_armed:    bool  = False   # đã vào UI mode do hold B2
    b2_press_dur:   int   = 0
    hotbar_slot:    int   = 1       # slot hiện tại (1..9)

    # ── UI Mode: anchor góc ───────────────────────────────────
    ui_pitch_anchor: float = 0.0
    ui_roll_anchor:  float = 0.0

    # ── IMU delta tracking (relative mouse mapping) ───────────
    # Lưu góc frame trước để tính delta giống chuột
    imu_prev_pitch: float = 0.0
    imu_prev_roll:  float = 0.0
    imu_prev_yaw:   float = 0.0
    smooth_x: float = 0.0
    smooth_y: float = 0.0

    # ── Fatigue tracking (FSR_L — chỉ đo, không gửi game) ─────
    fsr_l_history: list = field(default_factory=list)   # lưu % gần nhất
    FSR_L_HISTORY_MAX: int = 500   # 10 giây @ 50Hz


# ────────────────────────────────────────────────────────────
#  BME MAPPER
# ────────────────────────────────────────────────────────────

class BMEMapper:
    """
    Chuyên gia Điều khiển — nhận CleanedInput, phát thao tác OS.
    Hoàn toàn độc lập với hardware (không biết serial tồn tại).

    Khởi tạo:
        mapper = BMEMapper()
        mapper = BMEMapper(config=MapperConfig(camera_sens=0.25))
        mapper = BMEMapper(haptic_fn=lambda pwm: send_vib(pwm))

    Mỗi frame (20ms):
        inp = CleanedInput(jx=45, jy=80, pitch=-12.3, ...)
        mapper.process(inp)
    """

    def __init__(
        self,
        config:    Optional[MapperConfig]         = None,
        haptic_fn: Optional[Callable[[int], None]] = None,
    ):
        self.cfg     = config or MapperConfig()
        self.state   = MapperState()
        self._haptic = haptic_fn
        self._kb = _WinKeyboard()
        # mouse dùng _send_mouse() trực tiếp
        # Tìm cửa sổ đích ngay khi khởi động
        global _TARGET_HWND
        _TARGET_HWND = _find_target_hwnd()
        print(f"  [MAPPER] Target window HWND={_TARGET_HWND:#010x}")

    # ── API CÔNG KHAI ─────────────────────────────────────────

    def process(self, inp: CleanedInput) -> None:
        """
        Điểm vào duy nhất — gọi mỗi packet (20ms).
        Thứ tự xử lý quan trọng:
          B2 trước → quyết định ui_mode ảnh hưởng IMU và FSR.
        """
        self._handle_b2(inp)           # 1. B2: hotbar tap / UI mode hold
        self._handle_joystick(inp)     # 2. WASD từ joystick analog
        self._handle_flight_stick(inp) # 3. WASD từ flight stick digital
        self._handle_b1(inp)           # 4. B1: jump tap / sneak hold
        self._handle_imu(inp)          # 5. Camera hoặc UI cursor
        self._handle_fsr_right(inp)    # 6. FSR tay phải: tap/hold → RMB/LMB
        self._record_fatigue(inp)      # 7. FSR tay trái: ghi Fatigue ONLY

    def release_all(self) -> None:
        """Nhả toàn bộ phím/nút. Gọi khi kết thúc phiên."""
        for k, held in self.state.joy_keys.items():
            if held:
                try: self._kb.release(k)
                except Exception: pass
        self.state.joy_keys = {"w":False,"a":False,"s":False,"d":False}

        if self.state.b1_sneaking:
            try: self._kb.release(Key.shift)
            except Exception: pass
            self.state.b1_sneaking    = False
            self.state.b1_sneak_armed = False

        if self.state.fsr_holding:
            try: _send_mouse(MOUSEEVENTF_LEFTUP)
            except Exception: pass
            self.state.fsr_holding = False

        # Thoát UI mode nếu đang mở
        if self.state.ui_mode:
            try: self._kb.tap("e", delay=0.04)
            except Exception: pass
            self.state.ui_mode      = False
            self.state.b2_ui_armed  = False

        try: _send_mouse(MOUSEEVENTF_RIGHTUP)
        except Exception: pass

    @property
    def mode_label(self) -> str:
        parts = []
        if self.state.ui_mode:     parts.append("UI MODE")
        else:                      parts.append("GAME MODE")
        if self.state.b1_sneaking: parts.append("SNEAK")
        return " | ".join(parts)

    @property
    def fatigue_recent(self) -> float:
        """Trung bình FSR_L% trong lịch sử gần nhất (dùng bởi bme_controller)."""
        h = self.state.fsr_l_history
        if not h: return 0.0
        return sum(h) / len(h)

    # ────────────────────────────────────────────────────────
    #  B2 — HOTBAR CYCLE (tap) / UI MODE (hold ≥ 500ms)
    # ────────────────────────────────────────────────────────

    def _handle_b2(self, inp: CleanedInput) -> None:
        """
        B2 trên flight stick tay trái — dual function:

        ┌─ TAP (nhả < b2_ui_secs) ───────────────────────────────┐
        │  Cuộn hotbar: gửi phím số tiếp theo (1→2→...→9→1)      │
        │  Đây là thao tác chọn nhanh vũ khí / công cụ           │
        └────────────────────────────────────────────────────────┘

        ┌─ HOLD (≥ b2_ui_secs = 500ms) ──────────────────────────┐
        │  Vào UI MODE:                                           │
        │    • Gửi phím E (mở inventory Luanti)                  │
        │    • Lưu pitch/roll làm anchor (cursor không nhảy)      │
        │    • Haptic mạnh                                        │
        │  Duy trì: tiếp tục giữ B2 → ui_mode = True             │
        │  Thoát: sentinel 65535 (nhả B2):                        │
        │    • Gửi phím E (đóng inventory)                        │
        │    • Quay về GAME MODE                                   │
        └────────────────────────────────────────────────────────┘
        """
        s    = self.state
        cfg  = self.cfg
        dur  = inp.b2_dur
        SENT = 65535
        ui_ms = int(cfg.b2_ui_secs * 1000)

        if dur == SENT:
            # ── Falling edge ─────────────────────────────────────
            if s.b2_ui_armed:
                # Thoát UI mode
                try: self._kb.tap("e", delay=0.04)
                except Exception: pass
                s.ui_mode     = False
                s.b2_ui_armed = False
                self._haptic_fire(cfg.haptic_b2_ui_exit)
                print("\n  [MAPPER] B2 → GAME MODE (inventory closed)")
            elif s.b2_press_dur < ui_ms:
                # Tap nhanh → cuộn hotbar
                s.hotbar_slot = (s.hotbar_slot % cfg.b2_hotbar_slots) + 1
                try: self._kb.tap(str(s.hotbar_slot), delay=0.03)
                except Exception: pass
                self._haptic_fire(cfg.haptic_b2_hotbar)
                print(f"\n  [MAPPER] B2 tap → Hotbar slot {s.hotbar_slot}")
            s.b2_press_dur = 0

        elif dur > 0:
            # ── Đang giữ ─────────────────────────────────────────
            s.b2_press_dur = dur
            if not s.b2_ui_armed and dur >= ui_ms:
                # Vượt ngưỡng hold → vào UI mode
                s.ui_pitch_anchor = inp.pitch
                s.ui_roll_anchor  = inp.roll
                try: self._kb.tap("e", delay=0.04)
                except Exception: pass
                s.ui_mode     = True
                s.b2_ui_armed = True
                self._haptic_fire(cfg.haptic_b2_ui_enter)
                print(f"\n  [MAPPER] B2 hold → UI MODE "
                      f"(anchor P={inp.pitch:.1f}° R={inp.roll:.1f}°)")

    # ────────────────────────────────────────────────────────
    #  JOYSTICK → WASD
    # ────────────────────────────────────────────────────────

    def _handle_joystick(self, inp: CleanedInput) -> None:
        """
        Joystick tay trái → WASD.
        Hoạt động cả GAME MODE và UI MODE (cuộn danh sách).
        Không cho W+S hoặc A+D đồng thời.
        """
        thr  = self.cfg.joy_threshold
        want = {
            "w": inp.jy >  thr,
            "s": inp.jy < -thr,
            "d": inp.jx >  thr,
            "a": inp.jx < -thr,
        }
        if want["w"] and want["s"]: want["w"] = want["s"] = False
        if want["a"] and want["d"]: want["a"] = want["d"] = False

        for k, should in want.items():
            if should and not self.state.joy_keys[k]:
                self._kb.press(k)
                self.state.joy_keys[k] = True
            elif not should and self.state.joy_keys[k]:
                self._kb.release(k)
                self.state.joy_keys[k] = False

    # ────────────────────────────────────────────────────────
    #  FLIGHT STICK (DIGITAL MICROSWITCH) → WASD
    # ────────────────────────────────────────────────────────

    def _handle_flight_stick(self, inp: CleanedInput) -> None:
        # Chuẩn hóa lại chuẩn theo đúng chức năng tự nhiên của các switch điều hướng:
        #   fs_up=1      → Tiến  → W
        #   fs_down=1    → Lùi   → S
        #   fs_left=1    → Trái  → A
        #   fs_right=1   → Phải  → D
        want = {
            "w": inp.fs_up,
            "a": inp.fs_left,
            "s": inp.fs_down,
            "d": inp.fs_right,
        }
        if want["w"] and want["s"]: want["w"] = want["s"] = False
        if want["a"] and want["d"]: want["a"] = want["d"] = False
        for k, should in want.items():
            was = self.state.fs_keys[k]
            if should and not was:
                try: self._kb.press(k)
                except Exception: pass
                self.state.fs_keys[k] = True
                print(f"  [MAPPER] FS -> {k.upper()} pressed")
            elif not should and was:
                try: self._kb.release(k)
                except Exception: pass
                self.state.fs_keys[k] = False
                print(f"  [MAPPER] FS -> {k.upper()} released")
        self._handle_fs_trigger(inp)
        self._handle_fs_thumb(inp)

    def _handle_fs_trigger(self, inp: CleanedInput) -> None:
        """Trigger vật lý (fs_trigger=1): tap → hotbar 1→9→1, hold 3s → I (inventory Luanti)."""
        s   = self.state
        cfg = self.cfg
        now = time.time()
        pressed = inp.fs_trigger  # Đổi từ inp.fs_left về đúng nút trigger vật lý

        if pressed and not s.fs_trigger_was:
            s.fs_trigger_t     = now
            s.fs_trigger_armed = False
            print("  [MAPPER] TRIGGER pressed")

        if pressed and not s.fs_trigger_armed:
            if (now - s.fs_trigger_t) >= 3.0:
                try: self._kb.tap("i", delay=0.04)
                except Exception: pass
                s.fs_trigger_armed = True
                print("  [MAPPER] TRIGGER hold 3s → I (Inventory)")

        if not pressed and s.fs_trigger_was:
            if not s.fs_trigger_armed:
                s.hotbar_slot = (s.hotbar_slot % cfg.b2_hotbar_slots) + 1
                try: self._kb.tap(str(s.hotbar_slot), delay=0.03)
                except Exception: pass
                print(f"  [MAPPER] TRIGGER tap → Hotbar slot {s.hotbar_slot}")
            s.fs_trigger_armed = False

        s.fs_trigger_was = pressed
        
    def _handle_fs_thumb(self, inp: CleanedInput) -> None:
        """Thumb vật lý (fs_thumb=1): tap → Space (nhảy), hold 3s → Shift (sneak)."""
        s   = self.state
        cfg = self.cfg
        now = time.time()

        if s.ui_mode:
            if s.fs_thumb_armed:
                try: self._kb.release("shift")
                except Exception: pass
                s.fs_thumb_armed = False
            s.fs_thumb_was = inp.fs_thumb
            return

        if inp.fs_thumb and not s.fs_thumb_was:
            s.fs_thumb_t     = now
            s.fs_thumb_armed = False
            print("  [MAPPER] THUMB pressed")

        if inp.fs_thumb and not s.fs_thumb_armed and s.fs_thumb_t > 0:
            if (now - s.fs_thumb_t) >= 2.0:
                try: self._kb.press("shift")
                except Exception: pass
                s.fs_thumb_armed = True
                self._haptic_fire(cfg.haptic_b1_sneak_on)
                print("  [MAPPER] THUMB hold 3s → Sneak ON (Shift)")

        if not inp.fs_thumb and s.fs_thumb_was:
            if s.fs_thumb_armed:
                try: self._kb.release("shift")
                except Exception: pass
                s.fs_thumb_armed = False
                self._haptic_fire(cfg.haptic_b1_sneak_off)
                print("  [MAPPER] THUMB release → Sneak OFF")
            else:
                try: self._kb.tap("space", delay=0.05)
                except Exception: pass
                self._haptic_fire(cfg.haptic_b1_jump)
                print("  [MAPPER] THUMB tap → Jump (Space)")
            s.fs_thumb_t = 0.0

        s.fs_thumb_was = inp.fs_thumb


    def _handle_b1(self, inp: CleanedInput) -> None:
        """
        B1 trên flight stick tay trái:

        ┌─ TAP (nhả < b1_sneak_secs) ─────────────────────────────┐
        │  → Space (nhảy)                                          │
        └──────────────────────────────────────────────────────────┘

        ┌─ HOLD (≥ b1_sneak_secs = 300ms) ───────────────────────┐
        │  → Giữ Shift (sneak / lén đi / tránh ngã)              │
        │  Shift press khi vượt ngưỡng lần đầu                   │
        │  Shift release khi nhả B1 (sentinel)                   │
        └────────────────────────────────────────────────────────┘

        Không hoạt động trong UI MODE (tránh nhảy khi click UI).
        """
        s    = self.state
        cfg  = self.cfg
        dur  = inp.b1_dur
        SENT = 65535
        sneak_ms = int(cfg.b1_sneak_secs * 1000)

        # Trong UI mode: B1 không làm gì (tránh nhảy khi chọn item)
        if s.ui_mode:
            return

        if dur == SENT:
            # Falling edge
            if s.b1_sneak_armed:
                try: self._kb.release(Key.shift)
                except Exception: pass
                s.b1_sneaking    = False
                s.b1_sneak_armed = False
                self._haptic_fire(cfg.haptic_b1_sneak_off)
                print("\n  [MAPPER] B1 → Sneak OFF")
            elif s.b1_press_dur < sneak_ms:
                # Tap → nhảy
                try: self._kb.tap(Key.space, delay=0.04)
                except Exception: pass
                self._haptic_fire(cfg.haptic_b1_jump)
                print("\n  [MAPPER] B1 tap → JUMP")
            s.b1_press_dur = 0

        elif dur > 0:
            s.b1_press_dur = dur
            if not s.b1_sneak_armed and dur >= sneak_ms:
                try: self._kb.press(Key.shift)
                except Exception: pass
                s.b1_sneaking    = True
                s.b1_sneak_armed = True
                self._haptic_fire(cfg.haptic_b1_sneak_on)
                print("\n  [MAPPER] B1 hold → Sneak ON")

    # ────────────────────────────────────────────────────────
    #  IMU → CAMERA (GAME) / CURSOR (UI)
    # ────────────────────────────────────────────────────────

    def _handle_imu(self, inp: CleanedInput) -> None:
            """
            CHẾ ĐỘ VELOCITY THỰC SỰ (như analog joystick):
              • Nghiêng cổ tay = chuột chạy liên tục
              • Nghiêng nhiều  = chạy nhanh
              • Về thẳng (trong deadzone) = dừng hẳn
              • Không giới hạn — chuột chạy khắp màn hình

            CHỐNG DRIFT:
              • Đo bias khi tĩnh (góc không đổi) → lưu làm zero point
              • Trừ zero point khỏi góc hiện tại → góc sạch
              • Bias học liên tục khi tay không di chuyển
            """
            import bme_mapper as _self_mod

            update_global_angles(inp.pitch, inp.roll, inp.yaw)

            s   = self.state
            cfg = self.cfg

            # Khởi tạo state (lazy)
            _defaults = {
                'sub_x': 0.0, 'sub_y': 0.0,
                'smooth_x': 0.0, 'smooth_y': 0.0,
                'imu_warmed': False,
                # Zero point — góc "thẳng tay" hiện tại
                '_zero_pitch': 0.0, '_zero_roll': 0.0,
                # Đếm frame tĩnh để học zero
                '_static_n': 0,
                '_prev_pitch': 0.0, '_prev_roll': 0.0,
                # Hysteresis
                '_dz_active_x': False, '_dz_active_y': False,
            }
            for _a, _v in _defaults.items():
                if not hasattr(s, _a):
                    setattr(s, _a, _v)

            # Frame đầu — seed zero point = góc hiện tại
            if not s.imu_warmed:
                s._zero_pitch = inp.pitch
                s._zero_roll  = inp.roll
                s._prev_pitch = inp.pitch
                s._prev_roll  = inp.roll
                s.imu_prev_pitch = inp.pitch
                s.imu_prev_roll  = inp.roll
                s.imu_prev_yaw   = inp.yaw
                s.imu_warmed = True
                return

            # ── PHÁT HIỆN TĨNH & CẬP NHẬT ZERO POINT ──────────────
            # Khi góc gần như không đổi giữa 2 frame → tay đứng yên
            # → cập nhật zero point từ từ về góc hiện tại
            # Điều này tự động bù drift dài hạn
            dp_frame = abs(inp.pitch - s._prev_pitch)
            dr_frame = abs(inp.roll  - s._prev_roll)
            s._prev_pitch = inp.pitch
            s._prev_roll  = inp.roll

            STATIC_THR = 0.05   # °/frame — drift thực tế 0.12, chuyển động nhỏ nhất ~0.25
            if dp_frame + dr_frame < STATIC_THR:
                s._static_n += 1
            else:
                s._static_n = 0

            # Sau 20 frame tĩnh (~0.4s): kéo zero về góc hiện tại với tốc độ chậm
            # Đây là cốt lõi chống drift — zero tự "đuổi" theo bias MPU
            if s._static_n >= 50:
                ZERO_LR = 0.005 # tốc độ kéo zero — chậm để không ảnh hưởng cử động
                s._zero_pitch += (inp.pitch - s._zero_pitch) * ZERO_LR
                s._zero_roll  += (inp.roll  - s._zero_roll)  * ZERO_LR

            # ── GÓC TƯƠNG ĐỐI SO VỚI ZERO = TỐC ĐỘ CHUỘT ─────────
            # Lật cổ tay trái/phải (roll) → mouse X
            # Gập/ngửa cổ tay (pitch)    → mouse Y
            angle_x =  (inp.roll  - s._zero_roll)
            angle_y = (inp.pitch - s._zero_pitch)  # âm = nhìn lên khi ngửa tay

            # ── DEADZONE với hysteresis ─────────────────────────────
            DZONE = 3.0   # ° — vùng chết quanh zero point
            if s._dz_active_x:
                if abs(angle_x) < DZONE * 0.65:
                    s._dz_active_x = False
            else:
                if abs(angle_x) >= DZONE:
                    s._dz_active_x = True

            if s._dz_active_y:
                if abs(angle_y) < DZONE * 0.65:
                    s._dz_active_y = False
            else:
                if abs(angle_y) >= DZONE:
                    s._dz_active_y = True

            raw_speed_x = 0.0
            raw_speed_y = 0.0

            # ── VELOCITY: góc → tốc độ px/frame ───────────────────
            # Data thực: lật nhanh dR≈2°/frame → góc tuyệt đối lên ±40°
            # Muốn: ±5°  → ~3 px/frame (di chuyển nhẹ)
            #        ±15° → ~15 px/frame (di chuyển vừa)
            #        ±30° → ~35 px/frame (quét nhanh)
            POWER_CURVE     = 1.15
            SENS_MULTIPLIER = 0.15   # px / °^POWER sau deadzone

            if inp.tremor:
                sens = SENS_MULTIPLIER * cfg.tremor_sens_scale
                dzone_eff = DZONE * cfg.tremor_dzone_scale
            else:
                sens = SENS_MULTIPLIER
                dzone_eff = DZONE

            if s._dz_active_x:
                val = max(0.0, abs(angle_x) - dzone_eff)
                raw_speed_x = (val ** POWER_CURVE) * sens * cfg.camera_sens * (1.0 if angle_x > 0 else -1.0)

            if s._dz_active_y:
                val = max(0.0, abs(angle_y) - dzone_eff)
                raw_speed_y = (val ** POWER_CURVE) * sens * cfg.camera_sens * (1.0 if angle_y > 0 else -1.0)

            # ── EMA làm mượt ────────────────────────────────────────
            SMOOTH = 0.30
            s.smooth_x = s.smooth_x * SMOOTH + raw_speed_x * (1.0 - SMOOTH)
            s.smooth_y = s.smooth_y * SMOOTH + raw_speed_y * (1.0 - SMOOTH)

            # Khi tĩnh → xả smooth và sub-pixel nhanh
            if not s._dz_active_x and not s._dz_active_y:
                s.smooth_x *= 0.4
                s.smooth_y *= 0.4
                s.sub_x    *= 0.4
                s.sub_y    *= 0.4

            raw_x = s.smooth_x
            raw_y = s.smooth_y

            # Ngưỡng sàn output
            FLOOR = cfg.imu_out_floor
            if abs(raw_x) < FLOOR: raw_x = 0.0
            if abs(raw_y) < FLOOR: raw_y = 0.0

            # Sub-pixel accumulator
            total_x = s.sub_x + raw_x
            total_y = s.sub_y + raw_y
            
            move_x = int(total_x)
            move_y = int(total_y)
            
            # Lưu lại phần dư lẻ (sub-pixel) cho frame tiếp theo
            s.sub_x = total_x - move_x
            s.sub_y = total_y - move_y

            s.imu_prev_roll  = inp.roll
            s.imu_prev_pitch = inp.pitch
            s.imu_prev_yaw   = inp.yaw
            _self_mod.g_mouse_dx = move_x
            _self_mod.g_mouse_dy = move_y

            if move_x != 0 or move_y != 0:
                _send_mouse(MOUSEEVENTF_MOVE, dx=move_x, dy=move_y)

    # ────────────────────────────────────────────────────────
    #  FSR TAY PHẢI → TAP / HOLD (GAME) | CLICK (UI)
    # ────────────────────────────────────────────────────────

    def _handle_fsr_right(self, inp: CleanedInput) -> None:
            """
            FSR tay phải — Tap = Click Trái (Đánh), Hold = Giữ Chuột Trái (Phá)
            """
            s   = self.state
            cfg = self.cfg
            now = time.monotonic()

            # ── 1. ĐIỀU CHỈNH ĐỘ NHẠY LỰC BÓP TẠI ĐÂY ──
            # Mức 0.05 kg (50 gram) là rất nhẹ. 
            # Nếu bạn thấy chạm nhẹ nó đã tự click, hãy tăng lên 0.15 hoặc 0.2
            TRIGGER_THRESHOLD = 0.05 
            
            pressed = (inp.fsr_r_kg >= TRIGGER_THRESHOLD) or inp.grip

            if not hasattr(s, '_fsr_r_last_printed'):
                s._fsr_r_last_printed = 0.0
            if inp.fsr_r_kg > 0.03 and abs(inp.fsr_r_kg - s._fsr_r_last_printed) >= 0.03:
                print(f"🤚 [FSR_R Tay Cầm] Lực bóp: {inp.fsr_r_kg:.2f} kg ({inp.fsr_r:.0f}%)")
                s._fsr_r_last_printed = inp.fsr_r_kg
            elif inp.fsr_r_kg <= 0.03 and s._fsr_r_last_printed > 0.03:
                print("🤚 [FSR_R Tay Cầm] Thả tay")
                s._fsr_r_last_printed = 0.0

            if s.ui_mode:
                if pressed and not s.fsr_pressed:
                    _send_mouse(MOUSEEVENTF_LEFTDOWN)
                    threading.Thread(target=lambda: (time.sleep(0.05), _send_mouse(MOUSEEVENTF_LEFTUP)), daemon=True).start()
                    self._haptic_fire(cfg.haptic_ui_click)
                    print("\n🖱️ [FSR UI] Click trái chuột trong Menu/Inventory")
            else:
                if pressed and not s.fsr_pressed:
                    s.fsr_press_t = now
                    s.fsr_holding = False
                    print(f"\n📥 [FSR] Bắt đầu bóp (Lực: {inp.fsr_r_kg:.2f} kg)...")

                elif pressed and s.fsr_pressed:
                    if not s.fsr_holding:
                        elapsed = now - s.fsr_press_t
                        if elapsed >= cfg.fsr_hold_break_secs: 
                            _send_mouse(MOUSEEVENTF_LEFTDOWN)
                            s.fsr_holding = True
                            self._haptic_fire(cfg.haptic_fsr_break_start)
                            print(f"\n🔥 [FSR] Đã giữ >= {cfg.fsr_hold_break_secs}s -> ĐANG PHÁ BLOCK (Giữ Chuột Trái)...")

                elif not pressed and s.fsr_pressed:
                    if s.fsr_holding:
                        _send_mouse(MOUSEEVENTF_LEFTUP)
                        s.fsr_holding = False
                        self._haptic_fire(cfg.haptic_fsr_hold_end)
                        print("\n🛑 [FSR] Nhả tay -> Dừng phá block (Nhả Chuột Trái).")
                    else:
                        # ĐÃ ĐỔI SANG CHUỘT TRÁI (LEFTDOWN / LEFTUP) CHO THAO TÁC TAP
                        _send_mouse(MOUSEEVENTF_LEFTDOWN)
                        threading.Thread(target=lambda: (time.sleep(0.05), _send_mouse(MOUSEEVENTF_LEFTUP)), daemon=True).start()
                        self._haptic_fire(cfg.haptic_fsr_tap_rmc)
                        print(f"\n⚡ [FSR] Thả nhanh -> ĐÁNH (Click Chuột Trái).")

            s.fsr_pressed = pressed

    # ────────────────────────────────────────────────────────
    #  FSR TAY TRÁI — FATIGUE MONITOR ONLY
    # ────────────────────────────────────────────────────────

    def _record_fatigue(self, inp: CleanedInput) -> None:
        """
        FSR_L (FSR406, tay trái) — đặt ở thân máy để đo Static Grip Force.

        KHÔNG gửi bất kỳ lệnh nào vào game.
        Chỉ ghi vào lịch sử để bme_controller tính Fatigue Index:
          Fatigue% = trung_bình_late / trung_bình_early × 100

        Lý do: khi cầm nắm flight stick liên tục, lực kẹp tĩnh
        sẽ giảm dần cuối phiên do mỏi cơ — chỉ số quan trọng
        đặc biệt với bệnh nhân đột quỵ tay trái.
        """
        s = self.state
        # Lưu kg để tính Fatigue Index
        s.fsr_l_history.append(inp.fsr_l_kg)

        # FIX: Chỉ in khi lực thay đổi đáng kể (≥0.05kg so với lần in trước)
        # Tránh spam terminal 50Hz làm nghẽn ANSI redraw joystick map
        if not hasattr(s, '_fsr_l_last_printed'):
            s._fsr_l_last_printed = 0.0
        if inp.fsr_l_kg > 0.05 and abs(inp.fsr_l_kg - s._fsr_l_last_printed) >= 0.05:
            print(f"💪 [FSR_L Tay Trái] Lực bóp: {inp.fsr_l_kg:.2f} kg")
            s._fsr_l_last_printed = inp.fsr_l_kg
        elif inp.fsr_l_kg <= 0.05 and s._fsr_l_last_printed > 0.05:
            print(f"💪 [FSR_L Tay Trái] Thả tay")
            s._fsr_l_last_printed = 0.0

        if len(s.fsr_l_history) > s.FSR_L_HISTORY_MAX:
            s.fsr_l_history.pop(0)

    # ── HAPTIC ────────────────────────────────────────────────

    def _haptic_fire(self, strength: int) -> None:
        if self._haptic is not None:
            try: self._haptic(strength)
            except Exception: pass