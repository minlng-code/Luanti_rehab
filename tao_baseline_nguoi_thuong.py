"""
================================================================================
TÊN FILE   : tao_baseline_nguoi_thuong.py
MÔ TẢ      : Công cụ Thu thập Dữ liệu Baseline - Hệ thống Phục hồi Chức năng Đột quỵ Tay
TÁC GIẢ    : Biomedical Software Engineering Tool
PHIÊN BẢN  : 2.1 (EMA + Physiological Tremor + Key Debounce Fix)
TẦN SỐ     : 50 Hz (20ms/frame)

MÔ TẢ THUẬT TOÁN:
    Sử dụng EMA (Exponential Moving Average) để mô phỏng đường cong co cơ học
    (Muscle Contraction Curve) kết hợp White Noise để tái tạo vi rung sinh lý (Tremor).

FIX v2.1 — VẤN ĐỀ OS KEY AUTO-REPEAT:
    Khi giữ phím W, Windows/macOS phát liên tục:
        KeyPress → KeyRelease → KeyPress → KeyRelease → ... (≈30 lần/giây)
    Code cũ đặt key_w = False ngay khi nhận KeyRelease → EMA bị kéo về 0
    liên tục, không bao giờ vượt qua 3-4% thay vì 95%.

    Giải pháp: DEBOUNCE TIMER 50ms
        KeyRelease → đặt timer after(50ms) → set_key_false()
        KeyPress   → nếu timer đang chờ → hủy timer (after_cancel)
        Kết quả: auto-repeat "nhả giả" bị lọc sạch. Chỉ nhả thật
        (không có KeyPress trong 50ms tiếp theo) mới set False.

FIX v2.1 — XỬ LÝ BỘ GÕ TIẾNG VIỆT (UNIKEY/VIETKEY):
    Code cũ dùng event.char → bị dịch thành 'ư', 'â'... khi bật IME.
    Fix: dùng event.keysym (mã phím cứng, bỏ qua layer IME).
    Đã áp dụng từ v2.0, giữ nguyên trong v2.1.
================================================================================
"""

import tkinter as tk
from tkinter import ttk, font
import csv
import os
import time
import math
import random
from datetime import datetime

# ============================================================
# CẤU HÌNH TOÀN CỤC (Global Configuration)
# ============================================================

SAMPLE_RATE_HZ  = 50          # Tần số lấy mẫu: 50 Hz
LOOP_INTERVAL_MS = 1000 // SAMPLE_RATE_HZ  # 20ms mỗi vòng lặp

OUTPUT_DIR = os.path.join("Patient_Records", "Raw_CSV")

# ---- EMA Alpha (Hệ số làm mượt Trung bình trượt hàm mũ) ----
# Công thức EMA: signal_ema = alpha * target + (1 - alpha) * signal_ema
# Alpha nhỏ → hội tụ chậm (cơ bắp co/duỗi chậm hơn)
# Alpha lớn → hội tụ nhanh (phản hồi tức thì hơn)
ALPHA_GRIP        = 0.12   # Cơ gấp ngón tay (Flexor digitorum) - co chậm, có quán tính
ALPHA_JOYSTICK    = 0.18   # Cơ cổ tay (Wrist extensors) - phản hồi nhanh hơn
ALPHA_ANGLE_DECAY = 0.08   # Hệ số kéo góc về 0 khi nghỉ (wrist resting posture)

# ---- Tham số Nhiễu Trắng (White Noise / Physiological Tremor) ----
# Tay người bình thường luôn có vi rung 4-12 Hz (Physiological tremor)
# Mô phỏng bằng Gaussian white noise có biên độ nhỏ
TREMOR_GRIP_AMP   = 1.2    # Biên độ rung Grip (% điểm)
TREMOR_JOY_AMP    = 0.8    # Biên độ rung Joystick (đơn vị)
TREMOR_ANGLE_AMP  = 0.4    # Biên độ rung góc (độ)

# ---- Ngưỡng tín hiệu ----
GRIP_MAX          = 100.0
JOYSTICK_MAX      = 100.0
ANGLE_MAX         = 90.0

# ---- Bước nhảy mục tiêu khi nhấn phím WASD ----
JOYSTICK_TARGET   = 95.0   # Không đặt 100 để EMA có khoảng hội tụ tự nhiên

# ============================================================
# TIỆN ÍCH
# ============================================================

def clamp(value, lo, hi):
    """Kẹp giá trị trong đoạn [lo, hi]."""
    return max(lo, min(hi, value))

def white_noise(amplitude):
    """
    Tạo nhiễu trắng Gaussian (Physiological Tremor Simulation).
    Tay người bình thường dao động ±1-2% do hoạt động thần kinh cơ không đồng bộ.
    random.gauss(0, 1) cho phân phối chuẩn với σ=1, nhân với biên độ mong muốn.
    """
    return random.gauss(0, 1) * amplitude

# ============================================================
# LỚP TRẠNG THÁI CẢM BIẾN (Sensor State Machine)
# ============================================================

class SensorState:
    """
    Lưu trạng thái hiện tại và tính toán EMA + Tremor cho tất cả kênh cảm biến.

    NGUYÊN LÝ EMA (Exponential Moving Average):
    ─────────────────────────────────────────────
    Thay vì nhảy tức thời từ 0 → 100 (tín hiệu bậc thang - step function),
    EMA tạo ra đường cong tiệm cận (asymptotic curve) giống đường co cơ thực:

        S(t) = α × Target(t) + (1 − α) × S(t−1)

    Trong đó:
        S(t)      = Giá trị tín hiệu tại thời điểm t (giá trị xuất ra CSV)
        α (alpha) = Hệ số học (0 < α < 1), kiểm soát tốc độ hội tụ
        Target(t) = Giá trị mục tiêu tức thời (0 hoặc MAX khi nhấn/nhả)

    Ý nghĩa sinh lý:
        - α thấp  → cơ yếu / chậm (bệnh nhân sau đột quỵ)
        - α cao   → cơ khỏe / nhanh (người bình thường)
        - (1−α)   → "quán tính cơ" - cơ bắp nhớ trạng thái trước đó

    SAU KHI EMA, cộng thêm White Noise để tái tạo vi rung sinh lý (Tremor):
        Output = S(t) + N(0, σ_tremor)
    """

    def __init__(self):
        # ---- Giá trị EMA hiện tại (tín hiệu đã làm mượt) ----
        self.ema_grip  = 0.0   # Lực bóp (0-100%)
        self.ema_jx    = 0.0   # Joystick X (−100 đến 100)
        self.ema_jy    = 0.0   # Joystick Y (−100 đến 100)
        self.ema_pitch = 0.0   # Góc ngửa/cúi cổ tay (−90 đến 90°)
        self.ema_roll  = 0.0   # Góc nghiêng cổ tay (−90 đến 90°)

        # ---- Trạng thái nút nhấn (raw input) ----
        self.grip_pressed = False  # Chuột trái đang nhấn
        self.key_w = False
        self.key_s = False
        self.key_a = False
        self.key_d = False
        self.btn_b1 = 0    # Phím Q
        self.btn_b2 = 0    # Phím E

        # ---- Tọa độ chuột (dùng để tính góc) ----
        self.mouse_x = 0
        self.mouse_y = 0

        # ---- Kích thước canvas (cần để chuẩn hóa) ----
        self.canvas_w = 1
        self.canvas_h = 1

    # ----------------------------------------------------------
    # TÍNH TOÁN GÓC TỪ VỊ TRÍ CHUỘT
    # ----------------------------------------------------------
    def compute_target_angles(self):
        """
        Chuyển đổi tọa độ chuột → góc mục tiêu.
        Góc = (vị trí / kích thước canvas) × 2 × 90° − 90°
        Cho khoảng [-90, 90] tuyến tính theo vị trí chuột.
        """
        cx = self.canvas_w / 2.0
        cy = self.canvas_h / 2.0
        if cx == 0 or cy == 0:
            return 0.0, 0.0
        target_pitch = clamp((self.mouse_y - cy) / cy * (-ANGLE_MAX), -ANGLE_MAX, ANGLE_MAX)
        target_roll  = clamp((self.mouse_x - cx) / cx * ANGLE_MAX,  -ANGLE_MAX, ANGLE_MAX)
        return target_pitch, target_roll

    # ----------------------------------------------------------
    # CẬP NHẬT EMA MỖI FRAME (Gọi mỗi 20ms)
    # ----------------------------------------------------------
    def update(self):
        """
        Cập nhật tất cả kênh EMA theo thuật toán Muscle Ramp-up.
        Được gọi mỗi 20ms (50 Hz).
        """

        # === 1. GRIP - Lực bóp tay (Flexor Digitorum Simulation) ===
        # Target: 95% khi nhấn (để EMA tiệm cận 100 tự nhiên), 0 khi nhả
        grip_target = GRIP_MAX * 0.95 if self.grip_pressed else 0.0
        self.ema_grip = ALPHA_GRIP * grip_target + (1 - ALPHA_GRIP) * self.ema_grip

        # === 2. JOYSTICK - Cơ cổ tay (Wrist Extensor/Flexor Simulation) ===
        # Tính target JX (Trục ngang: A=-100, D=+100)
        jx_target = 0.0
        if self.key_d: jx_target += JOYSTICK_TARGET
        if self.key_a: jx_target -= JOYSTICK_TARGET

        # Tính target JY (Trục dọc: W=+100, S=-100)
        jy_target = 0.0
        if self.key_w: jy_target += JOYSTICK_TARGET
        if self.key_s: jy_target -= JOYSTICK_TARGET

        self.ema_jx = ALPHA_JOYSTICK * jx_target + (1 - ALPHA_JOYSTICK) * self.ema_jx
        self.ema_jy = ALPHA_JOYSTICK * jy_target + (1 - ALPHA_JOYSTICK) * self.ema_jy

        # === 3. GÓC PITCH & ROLL - Cổ tay (Wrist Resting Posture Decay) ===
        # Khi chuột đứng yên, góc tự nhiên kéo về 0 (neutral wrist posture)
        target_pitch, target_roll = self.compute_target_angles()

        # Nếu chuột di chuyển → hội tụ về góc mục tiêu
        # Khi "nghỉ" (target gần 0) → decay về 0 với alpha nhỏ hơn
        self.ema_pitch = ALPHA_ANGLE_DECAY * target_pitch + (1 - ALPHA_ANGLE_DECAY) * self.ema_pitch
        self.ema_roll  = ALPHA_ANGLE_DECAY * target_roll  + (1 - ALPHA_ANGLE_DECAY) * self.ema_roll

    # ----------------------------------------------------------
    # LẤY GIÁ TRỊ XUẤT RA (EMA + Tremor)
    # ----------------------------------------------------------
    def get_output(self):
        """
        Trả về tuple (JX, JY, B1, B2, Grip, Pitch, Roll) đã qua EMA + White Noise.

        NHIỄU SINH LÝ (Physiological Tremor):
            Người bình thường có vi rung 4-12 Hz do:
            - Motor neuron firing không đồng bộ
            - Cơ chế feedback tủy sống (spinal reflex)
            - Dao động huyết áp và nhịp tim
            Mô phỏng bằng Gaussian noise với σ nhỏ.
        """
        grip  = clamp(self.ema_grip  + white_noise(TREMOR_GRIP_AMP),  0, GRIP_MAX)
        jx    = clamp(self.ema_jx    + white_noise(TREMOR_JOY_AMP),   -JOYSTICK_MAX, JOYSTICK_MAX)
        jy    = clamp(self.ema_jy    + white_noise(TREMOR_JOY_AMP),   -JOYSTICK_MAX, JOYSTICK_MAX)
        pitch = clamp(self.ema_pitch + white_noise(TREMOR_ANGLE_AMP), -ANGLE_MAX, ANGLE_MAX)
        roll  = clamp(self.ema_roll  + white_noise(TREMOR_ANGLE_AMP), -ANGLE_MAX, ANGLE_MAX)

        return jx, jy, self.btn_b1, self.btn_b2, grip, pitch, roll


# ============================================================
# ỨNG DỤNG CHÍNH
# ============================================================

class StrokeRehabCollector:
    """
    Giao diện thu thập dữ liệu baseline với visualizer thời gian thực.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("🏥  Stroke Rehab – Normative Baseline Collector  |  50 Hz")
        self.root.configure(bg="#0d1117")
        self.root.resizable(False, False)

        self.sensor = SensorState()
        self.recording = False
        self.csv_writer = None
        self.csv_file   = None
        self.session_path = ""
        self.sample_count = 0
        self.start_time   = None

        # Lịch sử tín hiệu để vẽ waveform (giữ 200 mẫu = 4 giây)
        self.HISTORY = 200
        self.hist_grip  = [0.0] * self.HISTORY
        self.hist_jx    = [0.0] * self.HISTORY
        self.hist_jy    = [0.0] * self.HISTORY
        self.hist_pitch = [0.0] * self.HISTORY
        self.hist_roll  = [0.0] * self.HISTORY

        self._build_ui()
        self._bind_events()
        self._loop()

        print("=" * 65)
        print("  ✅  STROKE REHAB DATA COLLECTOR  |  v2.1 EMA + Tremor + Debounce")
        print("=" * 65)
        print(f"  Tần số mẫu  : {SAMPLE_RATE_HZ} Hz  ({LOOP_INTERVAL_MS} ms/frame)")
        print(f"  Alpha Grip  : {ALPHA_GRIP}  |  Alpha JOY: {ALPHA_JOYSTICK}")
        print(f"  Tremor Noise: Grip±{TREMOR_GRIP_AMP}  JOY±{TREMOR_JOY_AMP}  Angle±{TREMOR_ANGLE_AMP}")
        print(f"  Key Debounce: 50ms  (lọc OS auto-repeat, tương thích Unikey)")
        print(f"  Thư mục CSV : {OUTPUT_DIR}/")
        print("-" * 65)
        print("  ĐIỀU KHIỂN:")
        print("    Chuột      → Di chuyển để thay đổi Pitch/Roll (cổ tay phải)")
        print("    Chuột Trái → Giữ để tăng Grip (lực bóp tay phải)")
        print("    W/A/S/D    → Joystick Y+/X-/Y-/X+  (cần gạt tay trái)")
        print("    Q / E      → Nút B1 / B2")
        print("    SPACE      → Bắt đầu / Dừng ghi")
        print("    ESC        → Thoát")
        print("-" * 65)
        print("  LƯU Ý: Unikey/Vietkey không ảnh hưởng — dùng keysym (mã phím cứng)")
        print("=" * 65)

    # ----------------------------------------------------------
    # XÂY DỰNG GIAO DIỆN
    # ----------------------------------------------------------
    def _build_ui(self):
        DARK   = "#0d1117"
        PANEL  = "#161b22"
        BORDER = "#30363d"
        GREEN  = "#3fb950"
        CYAN   = "#58a6ff"
        ORANGE = "#f78166"
        YELLOW = "#e3b341"
        WHITE  = "#e6edf3"
        MUTED  = "#8b949e"

        self.colors = dict(dark=DARK, panel=PANEL, border=BORDER,
                           green=GREEN, cyan=CYAN, orange=ORANGE,
                           yellow=YELLOW, white=WHITE, muted=MUTED)

        # ── Header ──────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=DARK)
        hdr.pack(fill="x", padx=16, pady=(14, 4))

        tk.Label(hdr, text="⚕", font=("Segoe UI Emoji", 20), bg=DARK, fg=GREEN).pack(side="left")
        tk.Label(hdr, text="  Stroke Rehab | Normative Baseline Collector",
                 font=("Consolas", 13, "bold"), bg=DARK, fg=WHITE).pack(side="left")

        self.lbl_status = tk.Label(hdr, text="● STANDBY", font=("Consolas", 11, "bold"),
                                   bg=DARK, fg=MUTED)
        self.lbl_status.pack(side="right", padx=8)

        # ── Separator ────────────────────────────────────────────
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", padx=16)

        # ── Canvas (vẽ waveform + crosshair) ────────────────────
        body = tk.Frame(self.root, bg=DARK)
        body.pack(fill="both", expand=True, padx=16, pady=8)

        self.canvas_w_px = 700
        self.canvas_h_px = 320

        self.canvas = tk.Canvas(body, width=self.canvas_w_px, height=self.canvas_h_px,
                                bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(side="left")

        self.sensor.canvas_w = self.canvas_w_px
        self.sensor.canvas_h = self.canvas_h_px

        # ── Panel thông số bên phải ──────────────────────────────
        right = tk.Frame(body, bg=DARK, width=200)
        right.pack(side="left", fill="y", padx=(12, 0))
        right.pack_propagate(False)

        def make_meter(parent, label, color):
            f = tk.Frame(parent, bg=PANEL, relief="flat", bd=0)
            f.pack(fill="x", pady=4)
            tk.Frame(f, bg=color, width=3, height=52).pack(side="left")
            inner = tk.Frame(f, bg=PANEL)
            inner.pack(side="left", padx=8, pady=6)
            tk.Label(inner, text=label, font=("Consolas", 9), bg=PANEL, fg=MUTED).pack(anchor="w")
            val = tk.Label(inner, text="0.00", font=("Consolas", 18, "bold"), bg=PANEL, fg=color)
            val.pack(anchor="w")
            bar_bg = tk.Frame(f, bg=BORDER, width=6, height=40)
            bar_bg.pack(side="right", padx=6, pady=6)
            bar_fg = tk.Frame(bar_bg, bg=color, width=6, height=0)
            bar_fg.place(x=0, rely=1.0, anchor="sw", width=6, height=0)
            return val, bar_fg

        self.meter_grip,  self.bar_grip  = make_meter(right, "GRIP  (%)",      GREEN)
        self.meter_jx,    self.bar_jx    = make_meter(right, "JX  (Joystick)", CYAN)
        self.meter_jy,    self.bar_jy    = make_meter(right, "JY  (Joystick)", CYAN)
        self.meter_pitch, self.bar_pitch = make_meter(right, "PITCH  (°)",     ORANGE)
        self.meter_roll,  self.bar_roll  = make_meter(right, "ROLL   (°)",     YELLOW)

        # B1 / B2 indicators
        btn_row = tk.Frame(right, bg=DARK)
        btn_row.pack(fill="x", pady=6)
        self.ind_b1 = tk.Label(btn_row, text=" B1 (Q) ", font=("Consolas", 10, "bold"),
                                bg=PANEL, fg=MUTED, relief="flat", padx=4)
        self.ind_b1.pack(side="left", expand=True, fill="x", padx=2)
        self.ind_b2 = tk.Label(btn_row, text=" B2 (E) ", font=("Consolas", 10, "bold"),
                                bg=PANEL, fg=MUTED, relief="flat", padx=4)
        self.ind_b2.pack(side="left", expand=True, fill="x", padx=2)

        # ── Footer / Controls ────────────────────────────────────
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", padx=16)
        foot = tk.Frame(self.root, bg=DARK)
        foot.pack(fill="x", padx=16, pady=10)

        self.btn_record = tk.Button(
            foot, text="▶  BẮT ĐẦU GHI  (SPACE)", font=("Consolas", 11, "bold"),
            bg=GREEN, fg=DARK, activebackground="#2ea043", activeforeground=DARK,
            bd=0, padx=20, pady=8, cursor="hand2", command=self._toggle_recording
        )
        self.btn_record.pack(side="left")

        self.lbl_info = tk.Label(foot, text="Nhấn SPACE hoặc nút trên để bắt đầu ghi",
                                  font=("Consolas", 9), bg=DARK, fg=MUTED)
        self.lbl_info.pack(side="left", padx=14)

        self.lbl_samples = tk.Label(foot, text="Mẫu: 0  |  0.0s",
                                     font=("Consolas", 9, "bold"), bg=DARK, fg=CYAN)
        self.lbl_samples.pack(side="right")

    # ----------------------------------------------------------
    # BIND SỰ KIỆN BÀN PHÍM & CHUỘT
    # ----------------------------------------------------------
    def _bind_events(self):
        self.root.bind("<Motion>",         self._on_mouse_move)
        self.root.bind("<ButtonPress-1>",  self._on_mouse_press)
        self.root.bind("<ButtonRelease-1>",self._on_mouse_release)
        self.root.bind("<KeyPress>",       self._on_key_press)
        self.root.bind("<KeyRelease>",     self._on_key_release)
        self.root.bind("<space>",          lambda e: self._toggle_recording())
        self.root.bind("<Escape>",         lambda e: self._quit())
        self.root.focus_set()

        # ── DEBOUNCE TIMERS ────────────────────────────────────
        # Mỗi phím WASD có 1 timer ID riêng.
        # Khi KeyRelease → lên lịch set_False sau 50ms.
        # Khi KeyPress ngay sau đó (auto-repeat) → hủy timer.
        # → Chỉ nhả THẬT (không có KeyPress trong 50ms) mới set False.
        self._debounce_ids: dict[str, str | None] = {
            "w": None, "a": None, "s": None, "d": None
        }
        # Thời gian debounce (ms) — đủ lớn hơn khoảng auto-repeat (~33ms)
        self._DEBOUNCE_MS = 50

    # ── KEY SETTERS (dùng nội bộ bởi debounce) ────────────────

    _KEY_MAP = {
        "w": "key_w", "s": "key_s",
        "a": "key_a", "d": "key_d",
    }

    def _set_key(self, k: str, state: bool) -> None:
        """Đặt trực tiếp trạng thái phím trong SensorState."""
        attr = self._KEY_MAP.get(k)
        if attr:
            setattr(self.sensor, attr, state)

    def _schedule_key_release(self, k: str) -> None:
        """
        Lên lịch set key_X = False sau DEBOUNCE_MS ms.
        Nếu đã có timer đang chờ → hủy trước, tạo lại.
        """
        # Hủy timer cũ nếu còn tồn tại
        old = self._debounce_ids.get(k)
        if old is not None:
            try:
                self.root.after_cancel(old)
            except Exception:
                pass
        # Lên lịch timer mới
        self._debounce_ids[k] = self.root.after(
            self._DEBOUNCE_MS,
            lambda key=k: self._fire_key_release(key)
        )

    def _fire_key_release(self, k: str) -> None:
        """Callback thực sự set key = False. Chỉ chạy nếu không bị cancel."""
        self._debounce_ids[k] = None
        self._set_key(k, False)

    # ── CHUỘT ─────────────────────────────────────────────────

    def _on_mouse_move(self, event):
        """Lấy vị trí chuột trong canvas để tính góc Pitch/Roll."""
        cx = self.canvas.winfo_rootx()
        cy = self.canvas.winfo_rooty()
        self.sensor.mouse_x = clamp(event.x_root - cx, 0, self.canvas_w_px)
        self.sensor.mouse_y = clamp(event.y_root - cy, 0, self.canvas_h_px)

    def _on_mouse_press(self, event):
        self.sensor.grip_pressed = True

    def _on_mouse_release(self, event):
        self.sensor.grip_pressed = False

    # ── SỰ KIỆN PHÍM ──────────────────────────────────────────

    def _on_key_press(self, event):
        """
        KeyPress: đặt key = True VÀ hủy bất kỳ timer debounce đang chờ.
        Hủy timer = loại bỏ "lệnh nhả giả" do OS auto-repeat gây ra.
        Dùng event.keysym (mã phím cứng) → bỏ qua Unikey/Vietkey.
        """
        k = event.keysym.lower()

        # WASD: set True + cancel pending release timer
        if k in self._KEY_MAP:
            # Hủy timer đang chờ (nếu có) — đây là auto-repeat, không phải nhả thật
            old = self._debounce_ids.get(k)
            if old is not None:
                try:
                    self.root.after_cancel(old)
                except Exception:
                    pass
                self._debounce_ids[k] = None
            self._set_key(k, True)

        # Nút phụ — không cần debounce (không có auto-repeat vấn đề)
        elif k == "q":
            self.sensor.btn_b1 = 1
        elif k == "e":
            self.sensor.btn_b2 = 1

    def _on_key_release(self, event):
        """
        KeyRelease: KHÔNG set False ngay — đặt debounce timer 50ms.
        Nếu trong 50ms có KeyPress tiếp theo (auto-repeat của OS)
        → timer bị hủy → key vẫn = True → EMA tiếp tục hội tụ.
        Nếu không có KeyPress → 50ms sau set False (nhả thật).
        """
        k = event.keysym.lower()

        if k in self._KEY_MAP:
            self._schedule_key_release(k)
        elif k == "q":
            self.sensor.btn_b1 = 0
        elif k == "e":
            self.sensor.btn_b2 = 0

    # ----------------------------------------------------------
    # GHI CSV
    # ----------------------------------------------------------
    def _toggle_recording(self):
        if not self.recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Session_NguoiBinhThuong_{ts}.csv"
        self.session_path = os.path.join(OUTPUT_DIR, filename)

        self.csv_file   = open(self.session_path, "w", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(["Timestamp", "JX", "JY", "B1", "B2", "Grip", "Pitch", "Roll"])

        self.recording    = True
        self.sample_count = 0
        self.start_time   = time.time()

        self.btn_record.config(text="⏹  DỪNG GHI  (SPACE)", bg="#f78166")
        self.lbl_status.config(text="● REC", fg="#f78166")
        self.lbl_info.config(text=f"Đang ghi → {os.path.basename(self.session_path)}")

        print(f"\n  🔴  BẮT ĐẦU GHI  →  {self.session_path}")

    def _stop_recording(self):
        self.recording = False
        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None

        elapsed = time.time() - self.start_time if self.start_time else 0
        self.btn_record.config(text="▶  BẮT ĐẦU GHI  (SPACE)", bg=self.colors["green"])
        self.lbl_status.config(text="● STANDBY", fg=self.colors["muted"])
        self.lbl_info.config(text="Nhấn SPACE hoặc nút trên để bắt đầu ghi")

        print(f"\n  ✅  LƯU THÀNH CÔNG  →  {self.session_path}")
        print(f"      Tổng mẫu : {self.sample_count:,}  |  Thời gian: {elapsed:.1f}s")
        print(f"      Tốc độ   : {self.sample_count/elapsed:.1f} Hz thực tế" if elapsed > 0 else "")

    # ----------------------------------------------------------
    # VÒNG LẶP CHÍNH (50 Hz)
    # ----------------------------------------------------------
    def _loop(self):
        # 1. Cập nhật EMA cho tất cả kênh
        self.sensor.update()

        # 2. Lấy giá trị đầu ra (EMA + Tremor noise)
        jx, jy, b1, b2, grip, pitch, roll = self.sensor.get_output()

        # 3. Cập nhật lịch sử waveform
        self.hist_grip.append(grip);  self.hist_grip.pop(0)
        self.hist_jx.append(jx);     self.hist_jx.pop(0)
        self.hist_jy.append(jy);     self.hist_jy.pop(0)
        self.hist_pitch.append(pitch);self.hist_pitch.pop(0)
        self.hist_roll.append(roll);  self.hist_roll.pop(0)

        # 4. Ghi CSV nếu đang recording
        if self.recording and self.csv_writer:
            ts = time.time()
            self.csv_writer.writerow([
                f"{ts:.6f}",
                f"{jx:.3f}", f"{jy:.3f}",
                b1, b2,
                f"{grip:.3f}",
                f"{pitch:.3f}", f"{roll:.3f}"
            ])
            self.sample_count += 1

            if self.start_time:
                elapsed = time.time() - self.start_time
                self.lbl_samples.config(
                    text=f"Mẫu: {self.sample_count:,}  |  {elapsed:.1f}s"
                )

        # 5. Vẽ lại UI
        self._draw_canvas(jx, jy, grip, pitch, roll)
        self._update_meters(grip, jx, jy, pitch, roll, b1, b2)

        # 6. Lên lịch frame tiếp theo
        self.root.after(LOOP_INTERVAL_MS, self._loop)

    # ----------------------------------------------------------
    # VẼ WAVEFORM & CROSSHAIR
    # ----------------------------------------------------------
    def _draw_canvas(self, jx, jy, grip, pitch, roll):
        c  = self.canvas
        W  = self.canvas_w_px
        H  = self.canvas_h_px
        C  = self.colors
        c.delete("all")

        # ── Lưới nền ──────────────────────────────────────────
        for i in range(0, W, 50):
            c.create_line(i, 0, i, H, fill="#1f2937", width=1)
        for i in range(0, H, 40):
            c.create_line(0, i, W, i, fill="#1f2937", width=1)

        # ── Đường zero ──────────────────────────────────────────
        c.create_line(0, H//2, W, H//2, fill="#30363d", dash=(4, 4), width=1)

        # ── Vẽ waveform ──────────────────────────────────────────
        def draw_wave(history, lo, hi, color, offset_y=0, height_ratio=0.18):
            """Vẽ 1 kênh tín hiệu dưới dạng đường liên tục."""
            zone_h = H * height_ratio
            cy_line = H * offset_y + zone_h / 2
            pts = []
            for i, v in enumerate(history):
                x = int(i / (self.HISTORY - 1) * W)
                norm = (v - lo) / (hi - lo)   # [0, 1]
                y = int(cy_line + (0.5 - norm) * zone_h)
                pts.extend([x, y])
            if len(pts) >= 4:
                c.create_line(*pts, fill=color, width=1, smooth=True)

        # 5 kênh, chia đều chiều cao canvas
        draw_wave(self.hist_grip,  0,    100,  C["green"],  offset_y=0.05, height_ratio=0.18)
        draw_wave(self.hist_jx,   -100,  100,  C["cyan"],   offset_y=0.25, height_ratio=0.18)
        draw_wave(self.hist_jy,   -100,  100,  "#7ee8fa",   offset_y=0.45, height_ratio=0.18)
        draw_wave(self.hist_pitch,-90,    90,  C["orange"], offset_y=0.62, height_ratio=0.18)
        draw_wave(self.hist_roll, -90,    90,  C["yellow"], offset_y=0.80, height_ratio=0.18)

        # ── Nhãn kênh ─────────────────────────────────────────
        labels = [
            ("GRIP",  C["green"],  0.05),
            ("JX",    C["cyan"],   0.25),
            ("JY",    "#7ee8fa",   0.45),
            ("PITCH", C["orange"], 0.62),
            ("ROLL",  C["yellow"], 0.80),
        ]
        for name, color, oy in labels:
            c.create_text(6, int(H * oy) + 4, text=name, fill=color,
                          font=("Consolas", 8, "bold"), anchor="nw")

        # ── Crosshair cổ tay (Pitch/Roll visualizer) ──────────
        cx = int((roll  / ANGLE_MAX + 1) / 2 * W)
        cy = int((pitch / ANGLE_MAX + 1) / 2 * H)
        r  = 18
        c.create_oval(cx-r, cy-r, cx+r, cy+r, outline=C["orange"], width=2)
        c.create_line(cx-r-6, cy, cx+r+6, cy, fill=C["orange"], width=1)
        c.create_line(cx, cy-r-6, cx, cy+r+6, fill=C["orange"], width=1)
        c.create_text(cx, cy - r - 8, text=f"P:{pitch:+.1f}° R:{roll:+.1f}°",
                      fill=C["orange"], font=("Consolas", 8))

        # ── Chỉ báo REC ───────────────────────────────────────
        if self.recording:
            elapsed = time.time() - self.start_time if self.start_time else 0
            c.create_oval(W-16, 6, W-6, 16, fill="#f78166", outline="")
            c.create_text(W-22, 11, text=f"REC {elapsed:.1f}s",
                          fill="#f78166", font=("Consolas", 8, "bold"), anchor="e")

    # ----------------------------------------------------------
    # CẬP NHẬT ĐỒNG HỒ ĐO BÊN PHẢI
    # ----------------------------------------------------------
    def _update_meters(self, grip, jx, jy, pitch, roll, b1, b2):
        def set_bar(bar, val, lo, hi):
            ratio = (val - lo) / (hi - lo)
            h = int(clamp(ratio, 0, 1) * 40)
            bar.place(x=0, rely=1.0, anchor="sw", width=6, height=h)

        self.meter_grip.config( text=f"{grip:6.1f}")
        self.meter_jx.config(   text=f"{jx:+7.1f}")
        self.meter_jy.config(   text=f"{jy:+7.1f}")
        self.meter_pitch.config(text=f"{pitch:+6.1f}")
        self.meter_roll.config( text=f"{roll:+6.1f}")

        set_bar(self.bar_grip,  grip,  0,   100)
        set_bar(self.bar_jx,    jx,   -100, 100)
        set_bar(self.bar_jy,    jy,   -100, 100)
        set_bar(self.bar_pitch, pitch, -90,  90)
        set_bar(self.bar_roll,  roll,  -90,  90)

        C = self.colors
        self.ind_b1.config(bg=C["green"] if b1 else C["panel"],
                            fg=C["dark"]  if b1 else C["muted"])
        self.ind_b2.config(bg=C["cyan"]  if b2 else C["panel"],
                            fg=C["dark"]  if b2 else C["muted"])

    # ----------------------------------------------------------
    # THOÁT
    # ----------------------------------------------------------
    def _quit(self):
        if self.recording:
            self._stop_recording()
        # Hủy tất cả debounce timer còn đang chờ
        for k, tid in self._debounce_ids.items():
            if tid is not None:
                try:
                    self.root.after_cancel(tid)
                except Exception:
                    pass
        print("\n  👋  Đã thoát chương trình. Cảm ơn!\n")
        self.root.destroy()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    root = tk.Tk()
    app  = StrokeRehabCollector(root)
    root.mainloop()