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
import bme_mapper as _bme_mapper_mod   # truy cập biến toàn cục góc
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

class EMA:
    def __init__(self, alpha: float):
        self.alpha = alpha; self._val = None
    def update(self, x: float) -> float:
        self._val = x if self._val is None \
                    else self.alpha * x + (1 - self.alpha) * self._val
        return self._val
    def reset(self): self._val = None


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


class TremorDetector:
    """Short-Time Variance — cửa sổ 1 giây (50 mẫu @ 50Hz)."""
    WINDOW    = 50
    THRESHOLD = 4.0   # °²
    def __init__(self):
        self._pb = deque(maxlen=self.WINDOW)
        self._rb = deque(maxlen=self.WINDOW)
        self.tremor = False; self.variance = 0.0
    def update(self, pitch: float, roll: float) -> bool:
        self._pb.append(pitch); self._rb.append(roll)
        if len(self._pb) == self.WINDOW:
            mp = sum(self._pb) / self.WINDOW; mr = sum(self._rb) / self.WINDOW
            vp = sum((v-mp)**2 for v in self._pb) / self.WINDOW
            vr = sum((v-mr)**2 for v in self._rb) / self.WINDOW
            self.variance = max(vp, vr)
            self.tremor   = self.variance > self.THRESHOLD
        return self.tremor


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
butter_pitch = Butterworth2(fc=5.0, fs=FS)
butter_roll  = Butterworth2(fc=5.0, fs=FS)

zscore_fsr_l = ZScoreFilter(window=20, k=2.5)
zscore_fsr_r = ZScoreFilter(window=20, k=2.5)
butter_fsr_l = Butterworth1(fc=3.0, fs=FS)
butter_fsr_r = Butterworth1(fc=3.0, fs=FS)

ema_jx       = EMA(alpha=0.5)
ema_jy       = EMA(alpha=0.5)

tremor_det   = TremorDetector()
pkt_quality  = PacketQualityMonitor(expected=1.0 / FS)


def reset_all_filters() -> None:
    for f in [hampel_pitch, hampel_roll, butter_pitch, butter_roll,
              zscore_fsr_l, zscore_fsr_r, butter_fsr_l, butter_fsr_r,
              ema_jx, ema_jy]:
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
            "b1_dur":      int(parts[3]),      # B1 duration ms (0/N/65535)
            "b2_dur":      int(parts[4]),      # B2 duration ms (0/N/65535)
            "grip":        int(parts[5]),      # FSR402 hysteresis bit (0/1)
            "pitch":       float(parts[6]),
            "roll":        float(parts[7]),
            "fsr_l_kg":    float(parts[8]),    # FSR406 tay trái (kg, Fatigue)
            "fsr_r_kg":    float(parts[9]),    # FSR402 tay phải (kg, action)
            "vib_active":  int(parts[10]),
            "servo_angle": int(parts[11]),
            # Flight stick (firmware v6.1) — D4/D6/D11/D8/D13/D10
            "fs_up":       int(parts[12]),
            "fs_down":     int(parts[13]),
            "fs_left":     int(parts[14]),
            "fs_right":    int(parts[15]),
            "fs_trigger":  int(parts[16]),
            "fs_thumb":    int(parts[17]),
        }
    except (ValueError, IndexError):
        return None


# ════════════════════════════════════════════════════════════
#  FILTER PIPELINE
#  Raw dict → CleanedInput (giao diện với bme_mapper)
# ════════════════════════════════════════════════════════════

def run_filter_pipeline(raw: dict) -> tuple:
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
    # IMU: Hampel spike reject → Butterworth 5Hz
    p  = butter_pitch.update(hampel_pitch.update(raw["pitch"]))
    r  = butter_roll.update (hampel_roll.update (raw["roll"]))

    # FSR: firmware v6.0 gửi kg (đã qua SMA-15 + IIR + conductance model)
    # Python chỉ cần EMA nhẹ thêm để giảm jitter truyền thông
    fl_kg = max(0.0, butter_fsr_l.update(zscore_fsr_l.update(raw["fsr_l_kg"])))
    fr_kg = max(0.0, butter_fsr_r.update(zscore_fsr_r.update(raw["fsr_r_kg"])))

    # Joystick: EMA α=0.5
    jx = int(ema_jx.update(float(raw["jx"])))
    jy = int(ema_jy.update(float(raw["jy"])))

    tremor = tremor_det.update(p, r)

    # Quy đổi kg → % để log/dashboard dùng (dùng 0.2kg = 100% làm span mặc định)
    FSR_KG_SPAN = 0.2
    fsr_r_pct = round(min(fr_kg / FSR_KG_SPAN * 100.0, 100.0), 1)
    fsr_l_pct = round(min(fl_kg / FSR_KG_SPAN * 100.0, 100.0), 1)

    cleaned = CleanedInput(
        jx      = jx,
        jy      = jy,
        b1_dur  = raw["b1_dur"],
        b2_dur  = raw["b2_dur"],
        pitch   = round(p, 2),
        roll    = round(r, 2),
        yaw     = round(raw.get("yaw", 0.0), 2),   # yaw pass-through (firmware tính từ Madgwick)
        fsr_r_kg = round(fr_kg, 4),  # kg tay phải → mapper dùng grip detect
        fsr_l_kg = round(fl_kg, 4),  # kg tay trái → Fatigue only
        fsr_r    = fsr_r_pct,        # % tay phải (log/dashboard)
        fsr_l    = fsr_l_pct,        # % tay trái (log/dashboard)
        grip    = bool(raw["grip"]),  # hysteresis bit từ firmware
        tremor  = tremor,
        # Flight stick microswitch (firmware v6.1) — pass-through, đã debounce
        fs_up      = bool(raw["fs_up"]),
        fs_down    = bool(raw["fs_down"]),
        fs_left    = bool(raw["fs_left"]),
        fs_right   = bool(raw["fs_right"]),
        fs_trigger = bool(raw["fs_trigger"]),
        fs_thumb   = bool(raw["fs_thumb"]),
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
                s = serial.Serial(info.device, BAUD_RATE, timeout=2)
                time.sleep(1.8); s.reset_input_buffer()
                for _ in range(15):
                    if HANDSHAKE_MSG in s.readline():
                        print("✅  BME_READY!"); return s
                s.close(); print("không phải BME.")
            except (serial.SerialException, OSError): print("lỗi.")
        time.sleep(2)
    raise RuntimeError(
        "\n❌ Không tìm thấy Arduino!\n"
        "   Kiểm tra: USB cắm | Driver CH340/CP2102 | Firmware v5.0"
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

    # stdin non-blocking để nhận lệnh runtime (z = reset zero)
    import msvcrt

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

                # ── TẦNG 2: Điều khiển game ────────────────────
                mapper.process(cleaned)

                # ── Terminal: IMU 3 trục + flight stick compact ─
                # Đọc biến toàn cục qua module reference để đảm bảo
                # luôn lấy giá trị mới nhất (không bị stale binding)
                if row_count % 10 == 0:
                    m = _bme_mapper_mod
                    fs_disp = (
                        f"U={'█' if raw['fs_up']      else '░'}"
                        f"D={'█' if raw['fs_down']    else '░'}"
                        f"L={'█' if raw['fs_left']    else '░'}"
                        f"R={'█' if raw['fs_right']   else '░'}"
                        f" TRG={'█' if raw['fs_trigger'] else '░'}"
                        f" THB={'█' if raw['fs_thumb']   else '░'}"
                    )
                    print(
                        f"\r  P={m.g_pitch:+6.1f}° R={m.g_roll:+6.1f}° Y={m.g_yaw:+6.1f}°"
                        f"  FS:{fs_disp}"
                        f"  JX={cleaned.jx:+4d} JY={cleaned.jy:+4d}"
                        f"  FSR_R={cleaned.fsr_r:4.0f}%"
                        f"  [{mapper.mode_label}]"
                        + (" ⚠TREMOR" if cleaned.tremor else "        "),
                        end="", flush=True,
                    )

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