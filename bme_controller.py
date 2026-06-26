# ================================================================
#  bme_controller.py — Lớp Y Sinh (Biosignal Layer)
#  BME Rehabilitation System v6.1
#
#  TRÁCH NHIỆM:
#    • Giao tiếp phần cứng: tìm COM port, handshake Arduino
#    • Đọc + parse packet từ cảm biến (50 Hz)
#    • Lọc tín hiệu: Hampel, Butterworth, Z-score, EMA
#    • Phát hiện tremor (Short-time Variance)
#    • Theo dõi chất lượng luồng dữ liệu
#    • Lưu CSV (21 cột: thêm FS_UP/DOWN/LEFT/RIGHT/TRIGGER/THUMB)
#    • Gọi bme_mapper.process() để thực thi điều khiển game
#    • Gọi bme_report để xuất báo cáo PDF
#
#  PACKET FORMAT (firmware v6.1, 18 trường):
#    D,JX,JY,B1_DUR,B2_DUR,GRIP,PITCH,ROLL,FSR_L,FSR_R,VIB,SERVO,
#    FS_UP,FS_DOWN,FS_LEFT,FS_RIGHT,FS_TRIGGER,FS_THUMB
#    B1_DUR / B2_DUR: 0=không bấm, N=giữ Nms, 65535=vừa nhả
#    FS_*           : 0/1 — trạng thái flight stick (đã debounce)
# ================================================================

import serial
import serial.tools.list_ports
import time
import os
import csv
import sys
import json
import subprocess
from collections import deque
from datetime    import datetime
from pathlib     import Path

import bme_report
import bme_mapper  as _bme_mapper_mod   # truy cập biến toàn cục góc
from bme_mapper import BMEMapper, MapperConfig, CleanedInput, get_angle_display, reset_angle_zero

# ════════════════════════════════════════════════════════════
#  CẤU HÌNH
# ════════════════════════════════════════════════════════════

BAUD_RATE        = 115200
HANDSHAKE_MSG    = b"BME_READY"
COM_SCAN_TIMEOUT = 30

PATIENT_NAME = os.environ.get("BME_PATIENT",  "Benh_Nhan")
SESSION_NO   = int(os.environ.get("BME_SESSION", "1"))

BASE_DIR   = Path(sys.executable if getattr(sys, "frozen", False) else __file__).parent
CSV_DIR    = BASE_DIR / "Patient_Records" / "Raw_CSV"
PDF_DIR    = BASE_DIR / "Patient_Records" / "PDF_Reports"
CALIB_FILE = BASE_DIR / "bme_calib_cache.json"

FS = 50.0  # Hz — phải khớp SEND_INTERVAL_MS=20 ms trên Arduino

# ════════════════════════════════════════════════════════════
#  MÔ HÌNH VẬT LÝ FSR — mirror từ firmware v5.0
#  Tính Newton để ghi CSV và hiển thị live trên console
# ════════════════════════════════════════════════════════════

# FSR402 (tay trái): y = 0.0036x + 0.0069  (calib thực nghiệm)
FSR402_R0       = 10000.0
FSR402_A_SLOPE  = 0.0036
FSR402_B_INTCPT = 0.0069

# FSR406 (tay phải): y = 0.0037x + 0.0045  (calib thực nghiệm)
FSR406_R0       = 10000.0
FSR406_A_SLOPE  = 0.0037
FSR406_B_INTCPT = 0.0045

GRAVITY         = 9.81
FSR_FMAX_DEFAULT = 20.0   # Newton — dùng nếu chưa calib span


def pct_to_newton(pct: float, fmax_n: float = FSR_FMAX_DEFAULT) -> float:
    """
    Chuyển FSR% → Newton.
    pct    : 0-100% (từ firmware pipeline)
    fmax_n : lực span đã calib (mặc định 20N)
    """
    return round(max(0.0, pct / 100.0 * fmax_n), 3)


# ════════════════════════════════════════════════════════════
#  CSV HEADER
# ════════════════════════════════════════════════════════════

CSV_HEADER = [
    "Timestamp",
    "JX", "JY",
    "B1_Dur", "B2_Dur",                    # duration ms (0/N/65535)
    "Grip",
    "Pitch", "Roll",
    "FSR_L_KG", "FSR_R_KG",               # lực thực tế (kg) trực tiếp từ firmware
    "FSR_L_Newton", "FSR_R_Newton",        # lực thực tế (N) = kg × 9.81
    "Fatigue_Live_KG",                     # FSR_L trung bình gần nhất (kg)
    "Vib_Active", "Servo_Angle",
    "Tremor_Flag", "Tremor_Var",
    "UI_Mode",
    # Flight stick (firmware v6.1)
    "FS_Up", "FS_Down", "FS_Left", "FS_Right", "FS_Trigger", "FS_Thumb",
]

# ════════════════════════════════════════════════════════════
#  BỘ LỌC TÍN HIỆU
# ════════════════════════════════════════════════════════════

class AdaptiveEMA:
    """Bộ lọc trung bình lũy thừa thích nghi: Mượt khi đứng yên, mở biên độ khi quét mạnh."""
    def __init__(self, alpha_min: float = 0.15, alpha_max: float = 0.75, threshold: float = 8.0):
        self.alpha_min = alpha_min  # Độ mịn tối đa khi đứng yên/cử động nhẹ
        self.alpha_max = alpha_max  # Độ mở biên độ tối đa khi quét góc nhanh (giúp đi hết biên độ)
        self.threshold = threshold  # Ngưỡng góc (độ) để kích hoạt mở biên độ
        self._val = None

    def update(self, x: float) -> float:
        if self._val is None:
            self._val = x
            return self._val
        
        # Tính độ lệch giữa góc thô mới và góc đã lọc cũ
        diff = abs(x - self._val)
        
        # Hàm tính alpha thích nghi tuyến tính dựa trên độ lệch
        if diff < 1.0:
            alpha = self.alpha_min
        elif diff > self.threshold:
            alpha = self.alpha_max
        else:
            # Nội suy tuyến tính alpha từ alpha_min đến alpha_max
            alpha = self.alpha_min + (self.alpha_max - self.alpha_min) * ((diff - 1.0) / (self.threshold - 1.0))
            
        self._val = alpha * x + (1.0 - alpha) * self._val
        return self._val

    def reset(self): 
        self._val = None


class Butterworth2:
    """Biquad IIR Butterworth low-pass bậc 2. Pitch/Roll: fc=5Hz @ 50Hz."""
    def __init__(self, fc: float, fs: float):
        import math
        wc     = 2.0 * math.pi * fc / fs
        Q      = 0.7071067811865476
        alpha  = math.sin(wc) / (2.0 * Q)
        a0     = 1.0 + alpha
        self.b0 = (1 - math.cos(wc)) / 2 / a0
        self.b1 = (1 - math.cos(wc))     / a0
        self.b2 = (1 - math.cos(wc)) / 2 / a0
        self.a1 = -2 * math.cos(wc)      / a0
        self.a2 = (1 - alpha)            / a0
        self.w1 = self.w2 = 0.0
    def update(self, x: float) -> float:
        y       = self.b0 * x + self.w1
        self.w1 = self.b1 * x - self.a1 * y + self.w2
        self.w2 = self.b2 * x - self.a2 * y
        return y
    def reset(self): self.w1 = self.w2 = 0.0


class Butterworth1:
    """IIR Butterworth bậc 1. FSR: fc=3Hz @ 50Hz."""
    def __init__(self, fc: float, fs: float):
        import math
        K       = math.tan(math.pi * fc / fs)
        self.b0 =  K / (1 + K)
        self.b1 =  K / (1 + K)
        self.a1 = (K - 1) / (1 + K)
        self._x1 = self._y1 = 0.0
    def update(self, x: float) -> float:
        y = self.b0*x + self.b1*self._x1 - self.a1*self._y1
        self._x1 = x; self._y1 = y
        return y
    def reset(self): self._x1 = self._y1 = 0.0


class HampelFilter:
    """Hampel identifier — loại spike bằng MAD. Chạy trước Butterworth."""
    def __init__(self, window: int = 7, k: float = 3.0):
        self.buf = deque(maxlen=window); self.k = k; self.count = 0
    def update(self, x: float) -> float:
        self.buf.append(x)
        if len(self.buf) < 3: return x
        s   = sorted(self.buf)
        med = s[len(s) // 2]
        mad = sorted(abs(v - med) for v in self.buf)[len(self.buf) // 2]
        sigma = 1.4826 * mad
        if sigma > 1e-6 and abs(x - med) > self.k * sigma:
            self.count += 1; return med
        return x
    def reset(self): self.buf.clear(); self.count = 0


class ZScoreFilter:
    """Z-score spike rejection cho FSR."""
    def __init__(self, window: int = 20, k: float = 2.5):
        self.buf = deque(maxlen=window); self.k = k; self.count = 0
    def update(self, x: float) -> float:
        if len(self.buf) >= 3:
            mean = sum(self.buf) / len(self.buf)
            std  = (sum((v - mean)**2 for v in self.buf) / len(self.buf)) ** 0.5
            if std > 0.5 and abs(x - mean) > self.k * std:
                self.count += 1; self.buf.append(mean); return mean
        self.buf.append(x); return x
    def reset(self): self.buf.clear(); self.count = 0


class _BandpassBiquad:
    """RBJ bandpass (0 dB đỉnh) bậc 2. Cô lập 1 dải tần quanh f0."""
    def __init__(self, f0: float, fs: float, Q: float = 1.2):
        import math
        w0 = 2.0 * math.pi * f0 / fs
        alpha = math.sin(w0) / (2.0 * Q)
        cw    = math.cos(w0)
        a0 = 1.0 + alpha
        self.b0 =  alpha / a0
        self.b2 = -alpha / a0
        self.a1 = -2.0 * cw / a0
        self.a2 = (1.0 - alpha) / a0
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0
    def update(self, x: float) -> float:
        y = self.b0 * x + self.b2 * self.x2 - self.a1 * self.y1 - self.a2 * self.y2
        self.x2 = self.x1; self.x1 = x; self.y2 = self.y1; self.y1 = y
        return y
    def reset(self): self.x1 = self.x2 = self.y1 = self.y2 = 0.0


class TremorDetector:
    """
    Phát hiện run BẰNG NĂNG LƯỢNG DẢI TREMOR (3-8 Hz), không phải variance thô.

    Vì sao đổi: bản cũ tính variance trên góc đã lọc → bắt nhầm cử động chậm
    chủ ý thành run (báo nhầm 53% trong phiên thực). Run bệnh lý nằm ở 3-8 Hz,
    còn vận động chủ ý < 2 Hz. Ở đây tín hiệu được lọc thông dải quanh 5 Hz
    (cascade 3 tầng cho dốc đứng) rồi mới đo variance → cử động chậm bị loại,
    chỉ còn năng lượng run thật.

    THRESHOLD (deg² trong dải) cần hiệu chỉnh với bệnh nhân run thật.
    Thấp hơn = nhạy hơn. 0.30 là mặc định cân bằng từ mô phỏng.
    """
    WINDOW    = 60       # ~1.2-1.4 s tùy Fs thực
    THRESHOLD = 0.30     # deg² năng lượng trong dải 3-8 Hz
    CENTER_HZ = 5.0
    N_STAGE   = 3        # số tầng bandpass nối tiếp (dốc đứng để loại cử động chậm)

    def __init__(self):
        self._pb = deque(maxlen=self.WINDOW)
        self._rb = deque(maxlen=self.WINDOW)
        self._bp_p = [_BandpassBiquad(self.CENTER_HZ, FS) for _ in range(self.N_STAGE)]
        self._bp_r = [_BandpassBiquad(self.CENTER_HZ, FS) for _ in range(self.N_STAGE)]
        self.tremor = False; self.variance = 0.0

    def _filt(self, x: float, chain: list) -> float:
        for b in chain: x = b.update(x)
        return x

    def update(self, pitch: float, roll: float) -> bool:
        bp = self._filt(pitch, self._bp_p)
        br = self._filt(roll,  self._bp_r)
        self._pb.append(bp); self._rb.append(br)
        if len(self._pb) == self.WINDOW:
            mp = sum(self._pb) / self.WINDOW; mr = sum(self._rb) / self.WINDOW
            vp = sum((v-mp)**2 for v in self._pb) / self.WINDOW
            vr = sum((v-mr)**2 for v in self._rb) / self.WINDOW
            self.variance = max(vp, vr)
            self.tremor   = self.variance > self.THRESHOLD
        return self.tremor

    def reset(self):
        self._pb.clear(); self._rb.clear()
        for b in self._bp_p: b.reset()
        for b in self._bp_r: b.reset()
        self.tremor = False; self.variance = 0.0


class GimbalGuard:
    """
    Chặn cú LẬT pitch khi roll gần vùng kỳ dị Euler (±90°).

    Phân tích phiên thực: 1.2% frame pitch vọt qua ±90° (lên tới ±177°) đúng
    lúc |roll|≈77°. Đó là ảo ảnh toán học của góc Euler, không phải cổ tay
    thật gập tới đó → sinh giật dọc khi quay ngang. Khi rơi vào vùng này,
    giữ pitch ở giá trị tốt gần nhất thay vì để cú lật lọt vào mapper.

    Đây chỉ là giảm nhẹ phía Python. Trị tận gốc phải dùng quaternion ở firmware.
    """
    def __init__(self, roll_lim: float = 65.0, pitch_lim: float = 80.0):
        self.roll_lim = roll_lim
        self.pitch_lim = pitch_lim
        self._prev = None
        self.count = 0
    def update(self, pitch: float, roll: float) -> float:
        if abs(roll) > self.roll_lim and abs(pitch) > self.pitch_lim:
            self.count += 1
            return self._prev if self._prev is not None else 0.0
        self._prev = pitch
        return pitch
    def reset(self):
        self._prev = None; self.count = 0


class PacketQualityMonitor:
    """Tỷ lệ lỗi, jitter, dropout."""
    WINDOW = 200
    def __init__(self, expected: float = 0.020):
        self.expected = expected; self.ok = 0; self.error = 0
        self.dropouts = 0; self._last_t = None
        self._intervals = deque(maxlen=self.WINDOW)
    def record_ok(self):
        now = time.monotonic(); self.ok += 1
        if self._last_t is not None:
            dt = now - self._last_t; self._intervals.append(dt)
            if dt > self.expected * 3: self.dropouts += 1
        self._last_t = now
    def record_error(self): self.error += 1
    @property
    def error_rate(self) -> float:
        t = self.ok + self.error; return self.error / t if t else 0.0
    @property
    def jitter_ms(self) -> float:
        if len(self._intervals) < 2: return 0.0
        m = sum(self._intervals) / len(self._intervals)
        return (sum((v-m)**2 for v in self._intervals) / len(self._intervals))**0.5 * 1000
    def status(self) -> str:
        return (f"err={self.error_rate*100:.1f}%  "
                f"jitter={self.jitter_ms:.1f}ms  "
                f"dropout={self.dropouts}")


# ════════════════════════════════════════════════════════════
#  KHỞI TẠO BỘ LỌC
# ════════════════════════════════════════════════════════════

hampel_pitch = HampelFilter(window=7, k=3.0)
hampel_roll  = HampelFilter(window=7, k=3.0)

# Hạ fc từ 5.0Hz xuống 2.5Hz giúp triệt tiêu triệt để các sóng nhiễu giật giật
butter_pitch = Butterworth2(fc=8.0, fs=FS)  # 2Hz→8Hz: giảm lag, mapper EMA lo phần mượt
butter_roll  = Butterworth2(fc=8.0, fs=FS)

# Bổ sung EMA cho góc để làm mượt sâu đường đi con trỏ (Smoothness Layer)
# AdaptiveEMA pitch/roll đã bỏ — Butterworth fc=8Hz + EMA mapper là đủ
# ema_pitch_smooth / ema_roll_smooth không còn dùng

zscore_fsr_l = ZScoreFilter(window=20, k=6.0)
zscore_fsr_r = ZScoreFilter(window=20, k=4.0)
butter_fsr_l = Butterworth1(fc=3.0, fs=FS)
butter_fsr_r = Butterworth1(fc=3.0, fs=FS)

# ── FSR auto-zero baseline ──────────────────────────────────────────────
# 60 frame đầu @ 50Hz (~1.2s) đo giá trị tĩnh, lấy Q1 (quartile dưới)
# để loại spike nhiễu. Sau warm-up, trừ offset này khỏi mọi đọc FSR.
_fsr_l_baseline: float = 0.0
_fsr_r_baseline: float = 0.0
_fsr_baseline_buf_l: list = []
_fsr_baseline_buf_r: list = []
_FSR_BASELINE_FRAMES = 60

ema_jx       = AdaptiveEMA(alpha_min=0.4, alpha_max=1.0, threshold=40.0)
ema_jy       = AdaptiveEMA(alpha_min=0.4, alpha_max=1.0, threshold=40.0)

tremor_det   = TremorDetector()
pkt_quality  = PacketQualityMonitor(expected=1.0 / FS)

# Chặn lật pitch ở vùng kỳ dị Euler (giảm giật dọc khi quay ngang)
gimbal_guard = GimbalGuard(roll_lim=65.0, pitch_lim=80.0)


def reset_all_filters() -> None:
    for f in [hampel_pitch, hampel_roll, butter_pitch, butter_roll,
              zscore_fsr_l, zscore_fsr_r, butter_fsr_l, butter_fsr_r,
              ema_jx, ema_jy, tremor_det, gimbal_guard]:
        f.reset()


# ════════════════════════════════════════════════════════════
#  PARSE PACKET — firmware v6.1
#  Format: D,JX,JY,B1_DUR,B2_DUR,GRIP,PITCH,ROLL,FSR_L,FSR_R,VIB,SERVO,
#          FS_UP,FS_DOWN,FS_LEFT,FS_RIGHT,FS_TRIGGER,FS_THUMB
# ════════════════════════════════════════════════════════════

def parse_packet(line: str) -> dict | None:
    """
    Parse packet 18 trường firmware v6.1.
    B1_DUR / B2_DUR : 0 = không bấm, N = đang giữ Nms, 65535 = vừa nhả.
    FS_*            : 0/1 — trạng thái flight stick (debounced).
    """
    parts = line.strip().split(",")
    if len(parts) != 18 or parts[0] != "D":
        return None
    try:
        return {
            "jx":          int(parts[1]),
            "jy":          int(parts[2]),
            "b1_dur":      int(parts[3]),      
            "b2_dur":      int(parts[4]),      
            "grip":        int(parts[5]) == 1,      
            "pitch":       float(parts[6]),
            "roll":        float(parts[7]),
            "fsr_l_kg":    float(parts[8]),    
            "fsr_r_kg":    float(parts[9]),    
            "vib_active":  int(parts[10]),
            "servo_angle": int(parts[11]),
            # SỬA LẠI ĐÚNG THỨ TỰ INDEX TỪ 12 ĐẾN 17 CỦA FIRMWARE v6.1:
            "fs_up":       int(parts[16]) == 1,  # firmware: [12]=fs_up
            "fs_down":     int(parts[15]) == 1,  # firmware: [13]=fs_down
            "fs_left":     int(parts[13]) == 1,  # firmware: [14]=fs_left
            "fs_right":    int(parts[12]) == 1,  # firmware: [15]=fs_right
            "fs_trigger":  int(parts[14]) == 1,  # firmware: [16]=fs_trigger
            "fs_thumb":    int(parts[17]) == 1,  # firmware: [17]=fs_thumb
        }
    except (ValueError, IndexError):
        return None


# ════════════════════════════════════════════════════════════
#  FILTER PIPELINE
#  Raw dict → CleanedInput (giao diện với bme_mapper)
# ════════════════════════════════════════════════════════════

def run_filter_pipeline(raw: dict) -> tuple:
    global _fsr_l_baseline, _fsr_r_baseline, _fsr_baseline_buf_l, _fsr_baseline_buf_r
    """
    Returns: (CleanedInput, fsr_l_filtered, fsr_r_filtered)
    fsr_l/r_filtered: float đã lọc — dùng để ghi CSV và tính Newton.

    Pipeline:
      Pitch/Roll : Hampel → Butterworth 5Hz
      FSR_L/R   : Z-score → Butterworth 3Hz
      Joystick  : EMA α=0.5
      B1/B2 dur : pass-through (firmware đã debounce hardware)
      Tremor    : Short-time variance
    """
    # --- SWAP PATCH: Vá lỗi cắm nhầm chân phần cứng ---
    # Ép kiểu lại vì JY đang mang giá trị ADC của FSR, còn FSR đang mang giá trị Joystick
    temp_jy_val = float(raw["jy"])
    temp_fsr_val = int(raw["fsr_r_kg"]) 
    
    raw["fsr_r_kg"] = temp_jy_val
    raw["jy"] = temp_fsr_val
    # 0. CHẶN LẬT GIMBAL: bỏ cú pitch vọt khi roll gần ±90° (giảm giật dọc).
    #    Áp trên góc THÔ, trước mọi bộ lọc, để cú lật không kịp lọt vào pipeline.
    pitch_raw = gimbal_guard.update(raw["pitch"], raw["roll"])
    # Kẹp biên sinh lý — cổ tay không thể pitch quá ±100°; chặn nốt ảo ảnh sót lại.
    pitch_raw = max(-100.0, min(100.0, pitch_raw))

    # 1. Đi qua bộ lọc thô ban đầu (Hampel + Butterworth).
    #    Giữ riêng đầu ra Hampel (chưa bị Butterworth 2 Hz cắt) để phát hiện run,
    #    vì run nằm ở 3-8 Hz — nếu lấy tín hiệu sau Butterworth 2 Hz thì mất sạch run.
    hp = hampel_pitch.update(pitch_raw)
    hr = hampel_roll.update(raw["roll"])
    p_filtered = butter_pitch.update(hp)
    r_filtered = butter_roll.update(hr)

    ANG_DEADZONE = 0.2  
    
    if abs(p_filtered) < ANG_DEADZONE:
        p = 0.0
    else:
        # Làm mượt điểm gãy của dốc để di chuyển không bị khựng giật
        p = (p_filtered - ANG_DEADZONE) if p_filtered > 0 else (p_filtered + ANG_DEADZONE)

    if abs(r_filtered) < ANG_DEADZONE:
        r = 0.0
    else:
        r = (r_filtered - ANG_DEADZONE) if r_filtered > 0 else (r_filtered + ANG_DEADZONE)
    
    # 2. Ép mượt bằng bộ lọc EMA (hoặc AdaptiveEMA nếu bạn đã đổi)
    # Dùng thẳng p_filtered / r_filtered — Butterworth 8Hz đủ mượt
    # mapper EMA 0.25 lo phần triệt spike còn sót
    p = p_filtered
    r = r_filtered

    # --- Các đoạn code FSR và Joystick phía dưới giữ nguyên của bạn ---
    # ── FSR pipeline với auto-zero baseline ──────────────────────────
    # Đo 60 frame đầu khi chưa bóp → tính offset tĩnh → trừ ra mỗi frame
    _raw_fl = raw["fsr_l_kg"]
    _raw_fr = raw["fsr_r_kg"]
    if len(_fsr_baseline_buf_l) < _FSR_BASELINE_FRAMES:
        _fsr_baseline_buf_l.append(_raw_fl)
        _fsr_baseline_buf_r.append(_raw_fr)
        if len(_fsr_baseline_buf_l) == _FSR_BASELINE_FRAMES:
            _fsr_l_baseline = sorted(_fsr_baseline_buf_l)[_FSR_BASELINE_FRAMES // 4]  # Q1, không dùng mean
            _fsr_r_baseline = sorted(_fsr_baseline_buf_r)[_FSR_BASELINE_FRAMES // 4]
    # 1. Bỏ ZScoreFilter, chỉ dùng Butterworth để giữ lại tín hiệu bóp/giữ liên tục
    fl_kg = max(0.0, butter_fsr_l.update(raw["fsr_l_kg"]))
    
    # Sửa luôn cho FSR_R để khắc phục một phần lỗi số 4
    fr_kg = max(0.0, butter_fsr_r.update(raw["fsr_r_kg"]))
    fr_kg_raw = max(0.0, raw["fsr_r_kg"])
    jx = int(ema_jx.update(float(raw["jx"])))
    jy = int(ema_jy.update(float(raw["jy"])))
    # Phát hiện run từ tín hiệu sau Hampel (hp/hr) — còn nguyên dải 3-8 Hz.
    # KHÔNG dùng p/r đã làm mượt vì Butterworth 2 Hz đã xóa sạch dải run.
    tremor = tremor_det.update(hp, hr)

    # ── FSR SPAN riêng cho từng tay ──────────────────────────────
    # FSR_L (FSR406, Fatigue): span 1.2kg = full bóp sau khi sửa slope firmware
    # FSR_R (FSR402, Game):    span 2.0kg = bóp chơi game
    FSR_L_KG_SPAN = 0.7   # kg — đo thực tế max bóp = ~0.7kg (tăng lên 1.2 nếu đã flash firmware mới)
    FSR_R_KG_SPAN = 0.5   # kg — FSR402 range chơi game

    fsr_r_pct = round(min(fr_kg / FSR_R_KG_SPAN * 100.0, 100.0), 1)
    fsr_l_pct = round(min(fl_kg / FSR_L_KG_SPAN * 100.0, 100.0), 1)

    cleaned = CleanedInput(
        jx      = jx, jy = jy, b1_dur = raw["b1_dur"], b2_dur = raw["b2_dur"],
        pitch   = round(p, 2),
        roll    = round(r, 2),
        yaw     = round(raw.get("yaw", 0.0), 2),
        fsr_r_kg = round(raw["fsr_r_kg"], 4), fsr_l_kg = round(raw["fsr_l_kg"], 4),
        fsr_r    = round(min(raw["fsr_r_kg"] / FSR_R_KG_SPAN * 100.0, 100.0), 1),
        fsr_l    = round(min(raw["fsr_l_kg"] / FSR_L_KG_SPAN * 100.0, 100.0), 1),
        grip = bool(raw["grip"]), tremor = tremor,
        fs_up = bool(raw["fs_up"]), fs_down = bool(raw["fs_down"]),
        fs_left = bool(raw["fs_left"]), fs_right = bool(raw["fs_right"]),
        fs_trigger = bool(raw["fs_trigger"]), fs_thumb = bool(raw["fs_thumb"]),
    )
    return cleaned, fl_kg, fr_kg

# ════════════════════════════════════════════════════════════
#  AUTO-DETECT COM PORT
# ════════════════════════════════════════════════════════════

def find_arduino(timeout: int = 30) -> serial.Serial:
    print("=" * 60)
    print("  BME REHABILITATION CONTROLLER v6.1")
    print(f"  Bệnh nhân : {PATIENT_NAME}  |  Phiên : {SESSION_NO}")
    print("=" * 60)
    print(f"\n🔍 Tìm Arduino Mega 2560 Pro (timeout={timeout}s)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            print("   Chưa thấy COM. Cắm USB chưa?"); time.sleep(2); continue
        for info in ports:
            try:
                print(f"   Thử {info.device} ({info.description[:38]})...",
                      end=" ", flush=True)
                s = serial.Serial(info.device, BAUD_RATE, timeout=3)
                # Đọc TRONG lúc chờ — không reset_input_buffer() vì
                # BME_READY có thể đến bất cứ lúc nào trong ~3s boot
                found = False
                deadline_boot = time.time() + 5.0
                while time.time() < deadline_boot:
                    line = s.readline()
                    if line:
                        print(f"\n     >> {line.decode('utf-8','ignore').strip()}", flush=True)
                    if HANDSHAKE_MSG in line:
                        found = True; break
                if found:
                    print("✅  BME_READY!"); return s
                s.close(); print("không phải BME.")
            except (serial.SerialException, OSError): print("lỗi.")
        time.sleep(2)
    raise RuntimeError(
        "\n❌ Không tìm thấy Arduino!\n"
        "   Kiểm tra: USB cắm | Driver CH340/CP2102 | Firmware v6.1"
    )


# ════════════════════════════════════════════════════════════
#  TIỆN ÍCH
# ════════════════════════════════════════════════════════════

def _send(ser: serial.Serial, cmd: str) -> None:
    try: ser.write((cmd + "\n").encode("utf-8"))
    except Exception: pass


def _drain(ser: serial.Serial, secs: float = 3.0) -> None:
    deadline = time.time() + secs
    while time.time() < deadline:
        raw = ser.readline()
        if raw: print("  ", raw.decode("utf-8", errors="ignore").strip())


def _wait_keyword(ser: serial.Serial, keyword: str, timeout: float = 30.0):
    lines, t_end = [], time.time() + timeout
    while time.time() < t_end:
        raw = ser.readline()
        if not raw: continue
        line = raw.decode("utf-8", errors="ignore").strip()
        if line:
            print(f"  [FW] {line[6:] if line.startswith('CALIB:') else line}")
            lines.append(line)
            if keyword in line: return lines
    return lines


# ════════════════════════════════════════════════════════════
#  CALIBRATION WIZARD
# ════════════════════════════════════════════════════════════

def run_calibration_wizard(ser: serial.Serial) -> None:
    print("\n╔══════════════════════════════════════════════╗")
    print("║   BME CALIBRATION WIZARD v6.0                ║")
    print("╚══════════════════════════════════════════════╝")

    print("\nBƯỚC 1/3 — ZERO")
    print("  • Joystick nghỉ giữa  • Không chạm FSR  • MPU nằm phẳng")
    input("\n  ▶  Sẵn sàng → ENTER...")
    ser.reset_input_buffer()
    _send(ser, "CALIB_ZERO")
    lines = _wait_keyword(ser, "ZERO_DONE", timeout=30)
    if any("ZERO_DONE" in l for l in lines):
        print("  ✅ Zero OK — reset bộ lọc Python-side")
        reset_all_filters()
    else:
        print("  ⚠️  ZERO_DONE không nhận. Tiếp tục...")

    print("\nBƯỚC 2/3 — SPAN")
    print("  • Dùng thiết bị đo lực chuẩn đã chứng nhận")
    while True:
        try:
            sl = float(input("  Lực chuẩn FSR_LEFT  (Newton): "))
            sr = float(input("  Lực chuẩn FSR_RIGHT (Newton): "))
            if sl > 0 and sr > 0: break
        except ValueError: print("  Nhập số thực > 0")
    input("  ▶  Áp lực + di joystick full range (5s) → ENTER...")
    _send(ser, f"CALIB_SPAN,{sl:.2f},{sr:.2f}")
    lines = _wait_keyword(ser, "SPAN_DONE", timeout=20)
    if any("WARN" in l for l in lines):
        print("  ⚠️  Cảnh báo firmware!")
        if input("  Vẫn lưu? (y/N): ").strip().lower() != "y": return

    print("\nBƯỚC 3/3 — LƯU")
    _send(ser, "CALIB_STATUS"); _drain(ser, 4)
    if input("  Sai số <5% → lưu EEPROM? (Y/n): ").strip().lower() == "n":
        print("  Hủy."); return
    _send(ser, "CALIB_SAVE"); _wait_keyword(ser, "COMPLETE", 5)
    try:
        CALIB_FILE.write_text(json.dumps({
            "calibrated_at": datetime.now().isoformat(),
            "fsr_l_span_n": sl, "fsr_r_span_n": sr,
        }, indent=2))
        print(f"  📝 Log: {CALIB_FILE}")
    except Exception: pass
    print("  ✅ Saved.")


# ════════════════════════════════════════════════════════════
#  BÁO CÁO PDF
# ════════════════════════════════════════════════════════════

def create_report(csv_path: str) -> None:
    print("\n📊 Tạo báo cáo PDF...")
    try:
        pdf = bme_report.generate_report(csv_path,
                                         patient_name=PATIENT_NAME,
                                         session_no=SESSION_NO)
        print(f"✅ {pdf}")
        try: os.startfile(os.path.abspath(pdf))
        except Exception: subprocess.Popen(["start", str(pdf)], shell=True)
    except Exception as e:
        print(f"⚠️  Báo cáo thất bại: {e}")


# ════════════════════════════════════════════════════════════
#  HIỂN THỊ JOYSTICK MAP (ANSI multi-line)
# ════════════════════════════════════════════════════════════

_JOY_RANGE      = 512   # half-range khớp firmware (JX/JY: -512..+512)
_GRID_SIZE      = 9     # kích thước lưới — lẻ, đủ lớn để thấy chuyển động
_display_lines  = 0     # số dòng đã in lần trước (dùng để xoá)

# Bật Virtual Terminal Processing trên Windows để ANSI escape hoạt động
try:
    import ctypes
    _k32 = ctypes.windll.kernel32                          # type: ignore[attr-defined]
    _hout = _k32.GetStdHandle(-11)                         # STD_OUTPUT_HANDLE
    _mode = ctypes.c_ulong()
    _k32.GetConsoleMode(_hout, ctypes.byref(_mode))
    _k32.SetConsoleMode(_hout, _mode.value | 0x0004)       # ENABLE_VIRTUAL_TERMINAL_PROCESSING
except Exception:
    pass   # Linux/Mac — không cần


def _btn(active: bool) -> str:
    """Trả về ký tự ASCII an toàn cho trạng thái nút (tránh lỗi font Windows)."""
    return "[X]" if active else "[ ]"


def _joy_multiline(jx: int, jy: int,
                   pitch: float, roll: float, yaw: float,
                   fs_up: bool, fs_down: bool, fs_left: bool, fs_right: bool,
                   fs_trigger: bool, fs_thumb: bool,
                   fsr_r: float, fsr_l: float,
                   fsr_r_kg: float, fsr_l_kg: float,
                   mode_label: str, tremor: bool,
                   trigger_count: int = 0) -> str:
    """
    Vẽ joystick map 9x9 + thông số IMU / FS sang phải.
    trigger_count: số lần đã nhấn trigger (1-9), 0 = chưa nhấn.
    """
    G   = _GRID_SIZE
    mid = G // 2   # = 4 với G=9

    # ── XỬ LÝ ƯU TIÊN HIỂN THỊ CON TRỎ ─────────────────────────
    disp_jx = jx
    disp_jy = jy

    # Nếu có thao tác trên cần gạt Digital, ép ghi đè trục Analog để vẽ UI
    if fs_left or fs_right or fs_up or fs_down:
        disp_jx = 0
        disp_jy = 0
        if fs_left:  disp_jx = -_JOY_RANGE
        if fs_right: disp_jx = _JOY_RANGE
        if fs_up:    disp_jy = _JOY_RANGE
        if fs_down:  disp_jy = -_JOY_RANGE

    # ── Tính vị trí con trỏ ──────────────────────────────────
    # Map JX/JY (-JOY_RANGE … +JOY_RANGE) → index 0 … G-1
    # Dùng round() để tránh lệch 1 ô khi giá trị = 0
    jx_c  = max(-_JOY_RANGE, min(_JOY_RANGE, disp_jx))
    jy_c  = max(-_JOY_RANGE, min(_JOY_RANGE, disp_jy))
    c_dot = round((jx_c  + _JOY_RANGE) / (2.0 * _JOY_RANGE) * (G - 1))
    r_dot = round((jy_c + _JOY_RANGE) / (2.0 * _JOY_RANGE) * (G - 1))
    c_dot = max(0, min(G - 1, c_dot))
    r_dot = max(0, min(G - 1, r_dot))

    # ── Thông tin bên phải (9 dòng khớp G=9 hàng lưới) ─────────────
    # Hiển thị trigger_count: 0 = chưa nhấn, 1-9 = số lần đã nhấn
    trg_display = (f"[X] -> key:{trigger_count}" if fs_trigger
                   else f"[ ] last:{trigger_count if trigger_count else '-'}")
    thumb_display = "[X] -> JUMP" if fs_thumb else "[ ]"

    info = [
        f"  P={pitch:+6.1f} deg",
        f"  R={roll:+6.1f} deg",
        f"  Y={yaw:+6.1f} deg",
        f"  FSR_R={fsr_r:4.0f}% {fsr_r_kg:.3f}kg",
        f"  FSR_L={fsr_l:4.0f}% {fsr_l_kg:.3f}kg",
        f"  [{mode_label}]" + ("  !TREMOR" if tremor else ""),
        f"  UP={_btn(fs_up)}  DN={_btn(fs_down)}",
        f"  L={_btn(fs_left)}  R={_btn(fs_right)}",
        f"  TRG={trg_display}",
    ]

    lines = []
    lines.append(f"  +---JOYSTICK MAP---+")
    for r in range(G):
        row_str = "  |"
        for c in range(G):
            if r == r_dot and c == c_dot:
                row_str += "O"          # con trỏ joystick
            elif r == mid and c == mid:
                row_str += "+"          # tâm
            elif r == mid and c != mid:
                row_str += "-"          # trục ngang
            elif c == mid and r != mid:
                row_str += "|"          # trục dọc
            else:
                row_str += " "
        row_str += "|"
        row_str += info[r] if r < len(info) else ""
        lines.append(row_str)
        
    # Border bawah — hiển thị giá trị disp_jx/jy để dễ debug trạng thái giả lập
    lines.append(f"  +------------------+  JX={disp_jx:+4d} JY={disp_jy:+4d}  THB={thumb_display}")
    return "\n".join(lines)


def _redraw_joy(text: str) -> None:
    """
    Xoá block lần trước rồi in block mới tại chỗ.
    Dùng ANSI \033[nF (move cursor up n lines) + \033[J (erase below).
    Đã bật VTP ở trên nên hoạt động trên Windows 10+ cmd/PowerShell/WT.
    """
    global _display_lines
    line_count = text.count("\n") + 1
    if _display_lines > 0:
        sys.stdout.write(f"\033[{_display_lines}F\033[J")  # lên n dòng + xoá xuống
    sys.stdout.write(text + "\n")
    sys.stdout.flush()
    _display_lines = line_count


# ════════════════════════════════════════════════════════════
#  VÒNG LẶP CHÍNH
# ════════════════════════════════════════════════════════════

def run(ser: serial.Serial) -> None:
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = CSV_DIR / f"Session_{PATIENT_NAME}_{ts}.csv"

    # Mapper với haptic callback — đây là cầu nối duy nhất về hardware
    mapper = BMEMapper(
        config    = MapperConfig(),
        haptic_fn = lambda pwm: _send(ser, f"VIB,{pwm}"),
    )

    print(f"\n💾 CSV → {csv_path}")
    print("  [MAPPING]  B1 tap=Jump  B1 hold=Sneak")
    print("  [MAPPING]  B2 tap=Hotbar  B2 hold(500ms)=Inventory")
    print("  [MAPPING]  FSR_R tap=RMB  FSR_R hold=LMB(đào)")
    print("  [MAPPING]  FSR_L = Fatigue monitor ONLY")
    print("  [IMU]      Air Mouse mode — tay thẳng=chuột đứng, nghiêng=chuột chạy")
    print("  [IMU]      Gõ 'z' + Enter trong terminal này để reset zero góc MPU")

    # Drain 2 giây đầu — bỏ qua packet rác khi Arduino vừa reset
    # (B2 có thể bị floating/rung khi cắm USB → tránh vào UI MODE tự động)
    print("  ⏳ Chờ 2s để cảm biến ổn định...", end=" ", flush=True)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        ser.readline()   # đọc và bỏ, không xử lý
    ser.reset_input_buffer()
    print("OK")

    print("✅ Sẵn sàng! Ctrl+C để kết thúc.\n")

    row_count   = 0
    error_count = 0
    last_status = time.time()

    # ── BỘ ĐẾM TRIGGER → HIỂN THỊ UI ──────────────────────────────
    # Dùng chỉ để hiển thị trên joystick map, không gửi phím trực tiếp.
    # Mapper._handle_fs_trigger() tự xử lý việc gửi phím số 1-9.
    _trigger_count = 0   # 0 = chưa nhấn lần nào trong phiên
    _prev_fs_trigger = False  # theo dõi rising-edge chỉ để cập nhật _trigger_count

    # stdin non-blocking để nhận lệnh runtime (z = reset zero)
    import msvcrt
    import pydirectinput
    pydirectinput.PAUSE = 0

    def _check_stdin_cmd():
        """Đọc lệnh từ terminal không blocking. Trả về chuỗi nếu có, None nếu không."""
        buf = []
        while msvcrt.kbhit():
            ch = msvcrt.getwche()
            if ch in ('\r', '\n'):
                return ''.join(buf).strip().lower()
            buf.append(ch)
        return None

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)

        try:
            while True:
                # Kiểm tra lệnh runtime từ terminal
                cmd = _check_stdin_cmd()
                if cmd == 'z':
                    _send(ser, "ANGLE_ZERO")
                    reset_angle_zero(mapper=mapper)
                    print("\n  ✅ Zero reset! Giữ tay thẳng.")

                if ser.in_waiting > 100:  # Nếu bộ đệm dồn ứ quá 100 ký tự (đang bị trễ)
                    ser.reset_input_buffer()  # Xóa sạch đống gói dữ liệu cũ bị tắc đi

                raw_bytes = ser.readline()
                if not raw_bytes: continue
                try: line = raw_bytes.decode("utf-8", errors="ignore")
                except Exception: continue

                stripped = line.strip()
                if not stripped.startswith("D,"):
                    if stripped.startswith("CALIB:"):
                        print(f"\n[FW] {stripped[6:]}")
                    continue

                raw = parse_packet(stripped)
                if raw is None:
                    error_count += 1; pkt_quality.record_error()
                    if error_count > 50:
                        print("⚠️  Nhiều gói lỗi"); error_count = 0
                    continue
                error_count = 0; pkt_quality.record_ok()

                # ── TẦNG 1: Lọc tín hiệu ──────────────────────
                cleaned, fsr_l_out, fsr_r_out = run_filter_pipeline(raw)
                
                # KHÔNG đặt deadzone cứng ở đây — mapper._handle_imu() dùng
                # DELTA_DZONE trên delta/frame (0.5°/frame) — mịn hơn, không giật.

                # ── TẦNG 2: Điều khiển game ────────────────────
                # NOTE: Toàn bộ phím WASD, Jump, Sneak, Trigger, Thumb
                # đều được xử lý trong mapper.process() bên dưới thông qua
                # _WinKeyboard (SendInput) — không gửi thủ công ở đây nữa
                # để tránh xung đột pydirectinput vs SendInput gây mất Jump/Sneak.
                mapper.process(cleaned)

                # Cập nhật bộ đếm trigger chỉ để hiển thị trên joystick map
                if cleaned.fs_trigger and not _prev_fs_trigger:
                    _trigger_count = (_trigger_count % 9) + 1
                _prev_fs_trigger = cleaned.fs_trigger

                # ── Terminal: IMU 3 trục + joystick map + flight stick ─
                # Đọc biến toàn cục qua module reference để đảm bảo
                # luôn lấy giá trị mới nhất (không bị stale binding)
                if row_count % 30 == 0:
                    m = _bme_mapper_mod
                    display_text = _joy_multiline(
                        jx             = cleaned.jx,
                        jy             = cleaned.jy,
                        pitch          = m.g_pitch,
                        roll           = m.g_roll,
                        yaw            = m.g_yaw,
                        fs_up          = bool(raw["fs_up"]),
                        fs_down        = bool(raw["fs_down"]),
                        fs_left        = bool(raw["fs_left"]),
                        fs_right       = bool(raw["fs_right"]),
                        fs_trigger     = bool(raw["fs_trigger"]),
                        fs_thumb       = bool(raw["fs_thumb"]),
                        fsr_r          = cleaned.fsr_r,
                        fsr_l          = cleaned.fsr_l,
                        fsr_r_kg       = cleaned.fsr_r_kg,
                        fsr_l_kg       = cleaned.fsr_l_kg,
                        mode_label     = mapper.mode_label,
                        tremor         = cleaned.tremor,
                        trigger_count  = _trigger_count,
                    )
                    _redraw_joy(display_text)

                # ── TẦNG 3: Tính Newton từ kg ──────────────────
                fsr_l_n      = round(fsr_l_out * GRAVITY, 4)   # N = kg × 9.81
                fsr_r_n      = round(fsr_r_out * GRAVITY, 4)
                fatigue_live = round(mapper.fatigue_recent, 4)  # kg trung bình gần nhất

                # ── TẦNG 4: Ghi CSV ────────────────────────────
                writer.writerow([
                    round(time.time(), 3),
                    cleaned.jx,       cleaned.jy,
                    cleaned.b1_dur,   cleaned.b2_dur,
                    int(cleaned.grip),
                    cleaned.pitch,    cleaned.roll,
                    round(fsr_l_out, 4), round(fsr_r_out, 4),   # kg
                    fsr_l_n,             fsr_r_n,                # Newton
                    fatigue_live,
                    raw["vib_active"], raw["servo_angle"],
                    int(cleaned.tremor), round(tremor_det.variance, 2),
                    int(mapper.state.ui_mode),
                    # Flight stick raw bits (firmware v6.1)
                    raw["fs_up"], raw["fs_down"], raw["fs_left"], raw["fs_right"],
                    raw["fs_trigger"], raw["fs_thumb"],
                ])
                row_count += 1
                if row_count % 250 == 0:
                    f.flush()

                # Quality report mỗi 30 giây
                if time.time() - last_status > 30:
                    last_status = time.time()
                    print(
                        f"\n  [QUALITY] {pkt_quality.status()}"
                        f" | Hampel P={hampel_pitch.count} R={hampel_roll.count}"
                    )

        except KeyboardInterrupt:
            print("\n\n🛑 Kết thúc phiên.")
        except serial.SerialException as e:
            print(f"\n❌ Mất kết nối: {e}")
        finally:
            mapper.release_all()
            ser.close()

    print(f"  Tổng: {row_count} mẫu ({row_count*0.02:.1f}s)")
    print(f"  Quality: {pkt_quality.status()}")
    if row_count > 50: create_report(str(csv_path))
    else: print("⚠️  Phiên quá ngắn.")


# ════════════════════════════════════════════════════════════
#  STARTUP MENU
# ════════════════════════════════════════════════════════════

def startup_menu(ser: serial.Serial) -> None:
    print("\n┌──────────────────────────────────────────────┐")
    print("│  1. Bắt đầu phiên tập ngay                   │")
    print("│  2. Calibration Wizard                       │")
    print("│  3. Xem Calibration hiện tại                 │")
    print("│  4. Xem FILTER_STATUS                        │")
    print("│  5. Load Calibration từ EEPROM               │")
    print("│  6. Bật/tắt FSR Raw debug (FSR_RAW)          │")
    print("│  7. Căn zero góc MPU (ANGLE_ZERO)            │")
    print("│  8. Xem góc MPU hiện tại (ANGLE_STATUS)      │")
    print("│  9. [DEBUG] Xem raw packet 5 giây            │")
    print("└──────────────────────────────────────────────┘")
    choice = input("  Chọn [1]: ").strip() or "1"

    if choice == "2":
        run_calibration_wizard(ser)
        if input("\nBắt đầu phiên? (Y/n): ").strip().lower() != "n": run(ser)
    elif choice == "3":
        _send(ser, "CALIB_STATUS"); _drain(ser, 4)
        input("\nEnter..."); startup_menu(ser)
    elif choice == "4":
        _send(ser, "FILTER_STATUS"); _drain(ser, 4)
        input("\nEnter..."); startup_menu(ser)
    elif choice == "5":
        _send(ser, "CALIB_LOAD"); _drain(ser, 4)
        input("\nEnter..."); run(ser)
    elif choice == "6":
        _send(ser, "FSR_RAW"); _drain(ser, 2)
        input("\nEnter..."); startup_menu(ser)
    elif choice == "7":
        # Gửi lệnh xuống firmware để reset Madgwick, đồng thời reset Python-side zero
        _send(ser, "ANGLE_ZERO"); _drain(ser, 2)
        reset_angle_zero()  # reset Python biến toàn cục
        print("  ✅ Góc MPU đã reset về 0. Giữ cổ tay thẳng trước khi bắt đầu.")
        input("\nEnter..."); startup_menu(ser)
    elif choice == "8":
        _send(ser, "ANGLE_STATUS"); _drain(ser, 3)
        print(f"  Python-side: {get_angle_display()}")
        input("\nEnter..."); startup_menu(ser)
    elif choice == "9":
        # ── DEBUG: In raw packet 5 giây để kiểm tra FSR firmware + parser ──
        print("\n  [DEBUG] Raw packet từ Arduino (5 giây) — Ctrl+C để dừng sớm")
        print("  Định dạng: D,JX,JY,B1,B2,GRIP,PITCH,ROLL,FSR_L,FSR_R,VIB,SERVO,UP,DN,L,R,TRG,THB")
        print("  " + "="*100)
        print("  Index:    [0][1][2][3][4][5]   [6]   [7]   [8]      [9]      [10] [11]  [12][13][14][15][16][17]")
        print("  " + "="*100)
        print("  ✓ Nếu FSR_L/R=0.000 mà bóp → cảm biến/dây/firmware sai")
        print("  ✓ Nếu FSR_L/R có giá trị → Python filter có thể loại nó\n")
        ser.reset_input_buffer()
        deadline = time.time() + 5.0
        count = 0
        fsr_stats = {"l_min": 999, "l_max": -999, "r_min": 999, "r_max": -999}
        try:
            while time.time() < deadline:
                raw_bytes = ser.readline()
                if not raw_bytes:
                    continue
                line = raw_bytes.decode("utf-8", errors="ignore").strip()
                if not line.startswith("D,"):
                    if line:
                        print(f"  [NON-D] {line[:70]}")
                    continue
                parts = line.split(",")
                count += 1
                
                # Parse từng field để dễ debug
                try:
                    fsr_l_raw = float(parts[8]) if len(parts) > 8 else 0.0
                    fsr_r_raw = float(parts[9]) if len(parts) > 9 else 0.0
                    fsr_stats["l_min"] = min(fsr_stats["l_min"], fsr_l_raw)
                    fsr_stats["l_max"] = max(fsr_stats["l_max"], fsr_l_raw)
                    fsr_stats["r_min"] = min(fsr_stats["r_min"], fsr_r_raw)
                    fsr_stats["r_max"] = max(fsr_stats["r_max"], fsr_r_raw)
                except ValueError:
                    pass
                
                if count % 10 == 1:  # In 1 packet mỗi 10 (tránh flood)
                    fsr_l_raw = parts[8] if len(parts) > 8 else "?"
                    fsr_r_raw = parts[9] if len(parts) > 9 else "?"
                    grip_raw  = parts[5] if len(parts) > 5 else "?"
                    p_raw     = parts[6] if len(parts) > 6 else "?"
                    r_raw     = parts[7] if len(parts) > 7 else "?"
                    print(f"  #{count:04d} | FSR_L={fsr_l_raw:>8s}  FSR_R={fsr_r_raw:>8s}  GRIP={grip_raw} | P={p_raw:>7s} R={r_raw:>7s}")
        except KeyboardInterrupt:
            pass
        print(f"\n  ━━━ TỰA KẾT ━━━")
        print(f"  Tổng packets: {count}")
        if fsr_stats["l_max"] > -999:
            print(f"  FSR_L range: {fsr_stats['l_min']:.3f} → {fsr_stats['l_max']:.3f} kg")
            print(f"  FSR_R range: {fsr_stats['r_min']:.3f} → {fsr_stats['r_max']:.3f} kg")
        print(f"\n  ➤ Nếu L_max & R_max đều = 0.000 → firmware không gửi FSR (kiểm tra dây/cảm biến)")
        print(f"  ➤ Nếu L_max & R_max > 0 mà Python vẫn show 0% → lỗi filter pipeline (check deadzone)")
        input("\nEnter..."); startup_menu(ser)
    else:
        run(ser)


# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        ser = find_arduino(timeout=COM_SCAN_TIMEOUT)
        startup_menu(ser)
    except RuntimeError as e:
        print(e); input("\nNhấn Enter..."); sys.exit(1)
    except Exception as e:
        print(f"\n❌ {e}")
        import traceback; traceback.print_exc()
        input("\nNhấn Enter..."); sys.exit(1)