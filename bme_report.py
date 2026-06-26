# ============================================================
#  BME SESSION REPORT — Báo cáo Y sinh 7 tham số
#  Đọc CSV thô từ bme_controller.py → Tính toán → Xuất PDF
#
#  Thư viện: pandas, matplotlib (đều có sẵn, không cần cài thêm)
#  Dùng: generate_report(csv_path, patient_name, session_no)
# ============================================================

import os
import math
import pandas as pd
import matplotlib
matplotlib.use("Agg")                     # Không cần màn hình GUI
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch
from datetime import datetime

# ── Màu sắc hệ thống ──────────────────────────────────────────
C_PRIMARY   = "#1A3A5C"   # Xanh navy — tiêu đề
C_ACCENT    = "#2E86AB"   # Xanh nhạt — đường vẽ chính
C_GOOD      = "#27AE60"   # Xanh lá  — chỉ số tốt
C_WARN      = "#E67E22"   # Cam      — cảnh báo
C_BAD       = "#C0392B"   # Đỏ       — ngưỡng nguy hiểm
C_BG        = "#F7F9FC"   # Nền nhạt
C_GRID      = "#DDE3EC"   # Màu lưới

# ── DEADZONE để phân biệt "đang vận động" vs "đứng yên" ──────
DEADZONE_ANGLE = 5.0    # độ
DEADZONE_JOY   = 20     # giá trị joystick (-100..+100)


# ═══════════════════════════════════════════════════════════════
#  TÍNH TOÁN 7 THAM SỐ Y SINH
# ═══════════════════════════════════════════════════════════════

def compute_metrics(df: pd.DataFrame) -> dict:
    """Tính các tham số phục hồi chức năng (Đã chuẩn hóa động học)."""
    dt = 0.02 # Tần số 50Hz
    total_secs = len(df) * dt
    DEADZONE_JOY = 20

    # 1. SỬA LỖI THIÊN VỊ TAY PHẢI (Tính theo vận tốc cử động)
    pitch_vel = df["Pitch"].diff().abs()
    roll_vel = df["Roll"].diff().abs()
    right_mask = (pitch_vel > 0.5) | (roll_vel > 0.5)

    # 2. CẬP NHẬT TAY TRÁI (Bao gồm Joystick và Nút bóp FSR)
    # Grip là bit 0/1 từ firmware v6.1 (không còn là % nữa)
    left_mask = (df["JX"].abs() > DEADZONE_JOY) | (df["JY"].abs() > DEADZONE_JOY) | (df["Grip"] > 0)

    # 3. THỜI GIAN HOẠT ĐỘNG CHUNG
    active_mask = right_mask | left_mask
    active_secs = active_mask.sum() * dt

    # 4. TỶ LỆ CÂN BẰNG
    left_ticks  = left_mask.sum()
    right_ticks = right_mask.sum()
    total_ticks = left_ticks + right_ticks
    
    if total_ticks > 0:
        left_ratio  = (left_ticks / total_ticks) * 100
        right_ratio = (right_ticks / total_ticks) * 100
    else:
        left_ratio, right_ratio = 0.0, 0.0

    # 5. CÁC THAM SỐ KHÁC
    pitch_min, pitch_max = df["Pitch"].min(), df["Pitch"].max()
    roll_min,  roll_max  = df["Roll"].min(),  df["Roll"].max()

    tremor_pitch = df["Pitch"].rolling(100).std().dropna().mean() if len(df)>100 else 0
    tremor_roll  = df["Roll"].rolling(100).std().dropna().mean() if len(df)>100 else 0
    tremor_index = max(tremor_pitch, tremor_roll)

    # Fatigue: So sánh 20% đầu vs 20% cuối
    chunk = max(1, int(len(df) * 0.2))
    df_early = df.iloc[:chunk]
    df_late  = df.iloc[-chunk:]
    early_rom = (df_early["Pitch"].max() - df_early["Pitch"].min()) + (df_early["Roll"].max() - df_early["Roll"].min())
    late_rom  = (df_late["Pitch"].max() - df_late["Pitch"].min()) + (df_late["Roll"].max() - df_late["Roll"].min())
    fatigue_pct = (late_rom / early_rom * 100) if early_rom > 0 else 100.0

    # 6. FSR TAY TRÁI — lực bóp tĩnh (Mathiowetz et al., Bohannon 2006)
    # FSR_L_KG: lực cầm nhẹ liên tục trong setup này (~0.05–0.5 kg)
    if "FSR_L_KG" in df.columns:
        fsr_l = pd.to_numeric(df["FSR_L_KG"], errors="coerce").fillna(0.0)
        fsr_l_mean_kg = round(float(fsr_l.mean()), 4)
        fsr_l_peak_kg = round(float(fsr_l.max()), 4)
    else:
        fsr_l_mean_kg = 0.0
        fsr_l_peak_kg = 0.0

    return {
        # ── 7 tham số chính ──────────────────────────────────
        "rom_pitch":      round(pitch_max - pitch_min, 1),
        "rom_roll":       round(roll_max  - roll_min,  1),
        "tremor_index":   round(tremor_index, 2),
        "fsr_l_mean_kg":  fsr_l_mean_kg,   # lực bóp trung bình tay liệt
        "fsr_l_peak_kg":  fsr_l_peak_kg,   # lực bóp đỉnh tay liệt
        "left_ratio":     round(left_ratio, 1),
        "fatigue_pct":    round(fatigue_pct, 1),
        # ── Phụ (dùng bởi dashboard / trang 2 PDF) ───────────
        "right_ratio":    round(right_ratio, 1),
        "active_secs":    round(active_secs, 1),
        "rest_secs":      round(total_secs - active_secs, 1),
        "active_ratio":   round(active_secs / total_secs * 100 if total_secs > 0 else 0, 1),
        "task_duration":  round(total_secs, 1),
        "pitch_min":      round(pitch_min, 1),
        "pitch_max":      round(pitch_max, 1),
        "roll_min":       round(roll_min,  1),
        "roll_max":       round(roll_max,  1),
        "tremor_pitch":   round(tremor_pitch, 2),
        "tremor_roll":    round(tremor_roll,  2),
        "early_rom":      round(early_rom, 1),
        "late_rom":       round(late_rom,  1),
    }


# ═══════════════════════════════════════════════════════════════
#  VẼ PDF — 3 trang
# ═══════════════════════════════════════════════════════════════

def _color_for(value, good_thresh, warn_thresh, higher_is_better=True):
    """Trả về màu theo ngưỡng."""
    if higher_is_better:
        if value >= good_thresh: return C_GOOD
        if value >= warn_thresh: return C_WARN
        return C_BAD
    else:
        if value <= good_thresh: return C_GOOD
        if value <= warn_thresh: return C_WARN
        return C_BAD


def _header(ax, title, subtitle=""):
    """Vẽ tiêu đề section."""
    ax.set_facecolor(C_PRIMARY)
    ax.text(0.02, 0.5, title, transform=ax.transAxes,
            color="white", fontsize=13, fontweight="bold",
            va="center")
    if subtitle:
        ax.text(0.98, 0.5, subtitle, transform=ax.transAxes,
                color="#AAC4E0", fontsize=9, va="center", ha="right")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.axis("off")


def _metric_box(ax, label, value, unit, color, note=""):
    """Vẽ ô hiển thị một chỉ số."""
    ax.set_facecolor("white")
    ax.add_patch(FancyBboxPatch((0.05, 0.08), 0.90, 0.84,
        boxstyle="round,pad=0.02", linewidth=1.5,
        edgecolor=color, facecolor=C_BG))
    ax.text(0.5, 0.75, label, transform=ax.transAxes,
            color=C_PRIMARY, fontsize=9, ha="center", fontweight="bold")
    ax.text(0.5, 0.42, f"{value}", transform=ax.transAxes,
            color=color, fontsize=22, ha="center", fontweight="bold")
    ax.text(0.5, 0.18, unit, transform=ax.transAxes,
            color="#666", fontsize=8, ha="center")
    if note:
        ax.text(0.5, 0.04, note, transform=ax.transAxes,
                color="#999", fontsize=7, ha="center")
    ax.axis("off")


# ── TRANG 1: Tóm tắt & 7 tham số ─────────────────────────────
def _page1(pdf, m, patient_name, session_no, session_date):
    fig = plt.figure(figsize=(8.27, 11.69), facecolor=C_BG)  # A4
    gs  = gridspec.GridSpec(
        6, 4, figure=fig,
        hspace=0.55, wspace=0.4,
        top=0.94, bottom=0.04, left=0.06, right=0.96
    )

    # ── Banner ────────────────────────────────────────────────
    ax_banner = fig.add_subplot(gs[0, :])
    ax_banner.set_facecolor(C_PRIMARY)
    ax_banner.text(0.5, 0.72,
        "BME REHABILITATION SESSION REPORT",
        transform=ax_banner.transAxes, color="white",
        fontsize=16, fontweight="bold", ha="center")
    ax_banner.text(0.5, 0.25,
        f"Bệnh nhân: {patient_name}   |   Phiên số: {session_no}   |   Ngày: {session_date}",
        transform=ax_banner.transAxes, color="#AAC4E0",
        fontsize=9, ha="center")
    ax_banner.axis("off")

    # ── Tóm tắt nhanh (row 1) ─────────────────────────────────
    ax_h1 = fig.add_subplot(gs[1, :])
    _header(ax_h1, ">>  TỔNG QUAN PHIÊN TẬP", "")

    summary_ax = [fig.add_subplot(gs[2, i]) for i in range(4)]

    dur_m = int(m["task_duration"] // 60)
    dur_s = int(m["task_duration"] % 60)
    _metric_box(summary_ax[0], "Thời gian phiên", f"{dur_m}:{dur_s:02d}", "phút:giây",
                C_ACCENT)
    _metric_box(summary_ax[1], "Tay yếu đóng góp", f"{m['left_ratio']}%",
                "bilateral ratio",
                _color_for(m["left_ratio"], 40, 25))
    _metric_box(summary_ax[2], "Lực bóp đỉnh", f"{m['fsr_l_peak_kg']:.3f}", "kg (tay yếu)",
                _color_for(m["fsr_l_peak_kg"], 0.20, 0.10))
    fatigue_c = _color_for(m["fatigue_pct"], 75, 50)
    _metric_box(summary_ax[3], "Chỉ số mỏi cơ", f"{m['fatigue_pct']}%",
                "hiệu suất cuối/đầu", fatigue_c,
                "⚠ Mỏi" if m["fatigue_pct"] < 50 else "✓ Ổn")

    # ── 7 tham số chi tiết (rows 3–5) ─────────────────────────
    ax_h2 = fig.add_subplot(gs[3, :2])
    _header(ax_h2, "1 & 2  Biên độ vận động (aROM)")
    ax_h3 = fig.add_subplot(gs[3, 2:])
    _header(ax_h3, "3  Độ run (Tremor Index)")

    rom_axes    = [fig.add_subplot(gs[4, i]) for i in range(2)]
    tremor_axes = [fig.add_subplot(gs[4, i]) for i in range(2, 4)]

    _metric_box(rom_axes[0], "ROM Pitch (Gập/Ngửa)",
                f"{m['rom_pitch']}°", f"[{m['pitch_min']}° → {m['pitch_max']}°]",
                _color_for(m["rom_pitch"], 30, 15))
    _metric_box(rom_axes[1], "ROM Roll (Nghiêng)",
                f"{m['rom_roll']}°", f"[{m['roll_min']}° → {m['roll_max']}°]",
                _color_for(m["rom_roll"], 20, 10))
    _metric_box(tremor_axes[0], "Tremor Pitch",
                str(m["tremor_pitch"]), "std (°)",
                _color_for(m["tremor_pitch"], 3, 6, higher_is_better=False),
                "Thấp = tốt")
    _metric_box(tremor_axes[1], "Tremor Roll",
                str(m["tremor_roll"]), "std (°)",
                _color_for(m["tremor_roll"], 3, 6, higher_is_better=False),
                "Thấp = tốt")

    # Row 5: Tham số 4 & 5 — Lực bóp tay yếu | 6 & 7 — Bilateral + Fatigue
    ax_h4 = fig.add_subplot(gs[5, :2])
    _header(ax_h4, "4 & 5  Lực bóp tay yếu (FSR_L)", "Mathiowetz et al. | Bohannon 2006")
    ax_h5 = fig.add_subplot(gs[5, 2:])
    _header(ax_h5, "6 & 7  Bilateral + Fatigue")

    ax_h4.text(0.38, 0.5,
               f"TB: {m['fsr_l_mean_kg']:.3f} kg   Đỉnh: {m['fsr_l_peak_kg']:.3f} kg",
               transform=ax_h4.transAxes, color="white",
               fontsize=11, va="center", fontweight="bold")
    ax_h5.text(0.3, 0.5,
               f"Tay yếu: {m['left_ratio']}%   Mỏi: {m['fatigue_pct']}%",
               transform=ax_h5.transAxes, color="white",
               fontsize=11, va="center", fontweight="bold")

    plt.suptitle("", y=0)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── TRANG 2: Đồ thị kinematic ─────────────────────────────────
def _page2(pdf, df, m):
    fig = plt.figure(figsize=(8.27, 11.69), facecolor=C_BG)
    gs  = gridspec.GridSpec(5, 2, figure=fig,
        hspace=0.55, wspace=0.4,
        top=0.94, bottom=0.06, left=0.08, right=0.96)

    t = df.index * 0.02   # thời gian (giây)

    def _style(ax, title, ylabel):
        ax.set_facecolor("white")
        ax.set_title(title, color=C_PRIMARY, fontsize=10, fontweight="bold", pad=6)
        ax.set_xlabel("Thời gian (s)", fontsize=8, color="#555")
        ax.set_ylabel(ylabel, fontsize=8, color="#555")
        ax.grid(True, color=C_GRID, linewidth=0.5)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=7)

    # Banner trang
    ax_b = fig.add_subplot(gs[0, :])
    ax_b.set_facecolor(C_PRIMARY)
    ax_b.text(0.5, 0.5, "ĐỒ THỊ KINEMATIC — Pitch / Roll / Grip / Joystick",
              transform=ax_b.transAxes, color="white",
              fontsize=12, ha="center", va="center", fontweight="bold")
    ax_b.axis("off")

    # 1. Pitch theo thời gian
    ax1 = fig.add_subplot(gs[1, :])
    ax1.plot(t, df["Pitch"], color=C_ACCENT, linewidth=0.6, label="Pitch")
    ax1.axhline(0, color="#aaa", linewidth=0.5, linestyle="--")
    ax1.fill_between(t, df["Pitch"], alpha=0.12, color=C_ACCENT)
    _style(ax1, "1 · Góc Pitch — Gập/Ngửa cổ tay (Tay Phải)", "Góc (°)")
    ax1.legend(fontsize=8)

    # 2. Roll theo thời gian
    ax2 = fig.add_subplot(gs[2, :])
    ax2.plot(t, df["Roll"], color="#E07B54", linewidth=0.6, label="Roll")
    ax2.axhline(0, color="#aaa", linewidth=0.5, linestyle="--")
    ax2.fill_between(t, df["Roll"], alpha=0.12, color="#E07B54")
    _style(ax2, "2 · Góc Roll — Nghiêng cổ tay (Tay Phải)", "Góc (°)")
    ax2.legend(fontsize=8)

    # 3. Grip events
    ax3 = fig.add_subplot(gs[3, 0])
    ax3.fill_between(t, df["Grip"], step="post", color=C_ACCENT, alpha=0.7)
    ax3.set_ylim(-0.1, 1.4)
    ax3.set_yticks([0, 1]); ax3.set_yticklabels(["Nhả", "Bóp"])
    _style(ax3, "4 · Grip (Bóp tay phải)", "Trạng thái")

    # 4. Joystick X & Y
    ax4 = fig.add_subplot(gs[3, 1])
    ax4.plot(t, df["JX"], color=C_ACCENT,  linewidth=0.5, label="JX (Trái/Phải)", alpha=0.8)
    ax4.plot(t, df["JY"], color="#E07B54", linewidth=0.5, label="JY (Tiến/Lùi)",  alpha=0.8)
    ax4.axhline(0, color="#aaa", linewidth=0.5, linestyle="--")
    _style(ax4, "Joystick (Tay Trái)", "Giá trị (-100..+100)")
    ax4.legend(fontsize=7)

    # 5. Button 1 & 2
    ax5 = fig.add_subplot(gs[4, :])
    # B1/B2 là cột 0/1 đã tạo từ B1_Dur/B2_Dur trong generate_report()
    ax5.fill_between(t, df["B1"],  step="post", color=C_ACCENT,  alpha=0.6, label="B1 (Space/Nhảy)")
    ax5.fill_between(t, df["B2"],  step="post", color="#E07B54", alpha=0.6, label="B2 (Hotbar/Inv)")
    ax5.set_ylim(-0.1, 1.6)
    ax5.set_yticks([0, 1]); ax5.set_yticklabels(["Nhả", "Bấm"])
    _style(ax5, "Nút Bấm (Tay Trái)", "Trạng thái")
    ax5.legend(fontsize=8, loc="upper right")

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── TRANG 3: Đồ thị tham số 5, 6, 7 ──────────────────────────
def _page3(pdf, df, m):
    fig = plt.figure(figsize=(8.27, 11.69), facecolor=C_BG)
    gs  = gridspec.GridSpec(4, 2, figure=fig,
        hspace=0.6, wspace=0.45,
        top=0.94, bottom=0.06, left=0.08, right=0.96)

    def _style(ax, title):
        ax.set_facecolor("white")
        ax.set_title(title, color=C_PRIMARY, fontsize=10, fontweight="bold", pad=6)
        ax.grid(True, color=C_GRID, linewidth=0.5)
        ax.spines[["top","right"]].set_visible(False)
        ax.tick_params(labelsize=8)

    # Banner
    ax_b = fig.add_subplot(gs[0, :])
    ax_b.set_facecolor(C_PRIMARY)
    ax_b.text(0.5, 0.5,
              "PHÂN TÍCH CHUYÊN SÂU — Lực bóp tay yếu / Bilateral / Mỏi cơ",
              transform=ax_b.transAxes, color="white",
              fontsize=12, ha="center", va="center", fontweight="bold")
    ax_b.axis("off")

    t = df.index * 0.02

    # ── 4 & 5. FSR_L theo thời gian ───────────────────────────
    ax45 = fig.add_subplot(gs[1, :])
    if "FSR_L_KG" in df.columns:
        fsr_l_series = pd.to_numeric(df["FSR_L_KG"], errors="coerce").fillna(0.0)
        ax45.plot(t, fsr_l_series, color=C_ACCENT, linewidth=0.8,
                  label="FSR_L (kg)", alpha=0.9)
        ax45.axhline(0.10, color=C_WARN, linewidth=0.8, linestyle="--",
                     label="Ngưỡng TB tốt (0.10 kg)")
        ax45.axhline(0.20, color=C_GOOD, linewidth=0.8, linestyle="--",
                     label="Ngưỡng đỉnh tốt (0.20 kg)")
        ax45.axhline(m["fsr_l_mean_kg"], color=C_PRIMARY, linewidth=1.0,
                     linestyle=":", label=f"TB phiên: {m['fsr_l_mean_kg']:.3f} kg")
        ax45.set_ylabel("Lực (kg)", fontsize=8)
        ax45.set_xlabel("Thời gian (s)", fontsize=8)
    else:
        ax45.text(0.5, 0.5, "Không có dữ liệu FSR_L_KG trong CSV",
                  transform=ax45.transAxes, ha="center", color=C_WARN)
    ax45.legend(fontsize=7, loc="upper right")
    _style(ax45, f"4 & 5 · Lực bóp tay yếu — TB: {m['fsr_l_mean_kg']:.3f} kg  "
                 f"Đỉnh: {m['fsr_l_peak_kg']:.3f} kg  "
                 f"({'✓ Tốt' if m['fsr_l_peak_kg'] >= 0.20 else '⚠ Yếu' if m['fsr_l_peak_kg'] >= 0.10 else '✗ Rất yếu'})")

    # ── 6. Bilateral — Horizontal bar ─────────────────────────
    ax6 = fig.add_subplot(gs[2, 0])
    categories = ["Tay Trái (liệt)\nFlight Stick", "Tay Phải (lành)\nMPU6050"]
    values     = [m["left_ratio"], m["right_ratio"]]
    bar_colors = [C_ACCENT, "#E07B54"]
    bars = ax6.barh(categories, values, color=bar_colors,
                    height=0.5, edgecolor="white")
    for bar, val in zip(bars, values):
        ax6.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                 f"{val:.1f}%", va="center", fontsize=9, color=C_PRIMARY)
    ax6.set_xlim(0, 115)
    ax6.set_xlabel("% thao tác", fontsize=8)
    ax6.axvline(40, color=C_GOOD,  linewidth=0.8, linestyle="--")
    ax6.text(40, 1.55, "≥40% tốt", fontsize=7, color=C_GOOD, ha="center")
    _style(ax6, "6 · Phân bổ hai tay (Bilateral)")

    # ── 7. Fatigue — ROM theo thời gian (cửa sổ 30s) ─────────
    ax7 = fig.add_subplot(gs[2, 1])
    window_30s  = int(30 / 0.02)
    pitch_max_s = df["Pitch"].abs().rolling(window_30s).max().dropna()
    roll_max_s  = df["Roll"].abs().rolling(window_30s).max().dropna()
    t_win = pitch_max_s.index * 0.02
    ax7.plot(t_win, pitch_max_s, color=C_ACCENT,  linewidth=1, label="Pitch max")
    ax7.plot(t_win, roll_max_s,  color="#E07B54", linewidth=1, label="Roll max", alpha=0.8)
    t_max = len(df) * 0.02
    ax7.axvspan(max(0, t_max - 300), t_max, alpha=0.07, color=C_BAD)
    ax7.set_xlabel("Thời gian (s)", fontsize=8)
    ax7.set_ylabel("Biên độ tối đa (°)", fontsize=8)
    ax7.legend(fontsize=7)
    _style(ax7, f"7 · Fatigue: {m['fatigue_pct']:.0f}%  "
                f"({'✓ Ổn' if m['fatigue_pct'] >= 75 else '⚠ Cần nghỉ' if m['fatigue_pct'] >= 50 else '✗ Mỏi nặng'})")

    # ── Chú thích ngưỡng lâm sàng ─────────────────────────────
    ax_note = fig.add_subplot(gs[3, :])
    ax_note.set_facecolor(C_BG)
    ax_note.axis("off")
    note_text = (
        "Ngưỡng lâm sàng tham khảo (Mathiowetz et al., Bohannon 2006, Desrosiers 1995):\n"
        "aROM Pitch ≥ 30° = Tốt  |  Tremor < 3° std = Kiểm soát tốt  |  "
        "FSR_L mean ≥ 0.10 kg = Tốt  |  FSR_L peak ≥ 0.20 kg = Tốt\n"
        "Bilateral: Tay yếu đóng góp ≥ 40% = Tốt  |  Fatigue ≥ 75% = Trong ngưỡng an toàn  |  < 50% = Cần nghỉ ngơi\n"
        "Báo cáo này chỉ mang tính hỗ trợ — Kết luận lâm sàng cần bác sĩ phụ trách xác nhận."
    )
    ax_note.text(0.5, 0.75, note_text, transform=ax_note.transAxes,
                 fontsize=7.5, ha="center", va="top", color="#555",
                 linespacing=1.8,
                 bbox=dict(boxstyle="round,pad=0.4", facecolor="#EEF2F7",
                           edgecolor=C_GRID, linewidth=0.8))

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════
#  HÀM CHÍNH — generate_report()
# ═══════════════════════════════════════════════════════════════

def generate_report(csv_path: str,
                    patient_name: str = "Bệnh nhân",
                    session_no: int   = 1) -> str:
    """
    Đọc file CSV → tính 7 tham số → xuất PDF 3 trang.
    Trả về đường dẫn file PDF đã tạo.
    """
    # Load dữ liệu
    df = pd.read_csv(csv_path)

    # CSV v6.1 dùng B1_Dur / B2_Dur thay vì B1 / B2
    # Tạo cột B1/B2 (0/1) từ B1_Dur/B2_Dur để tương thích code vẽ đồ thị
    if "B1_Dur" in df.columns and "B1" not in df.columns:
        df["B1"] = (df["B1_Dur"] > 0).astype(int)
    if "B2_Dur" in df.columns and "B2" not in df.columns:
        df["B2"] = (df["B2_Dur"] > 0).astype(int)

    required = ["Timestamp", "JX", "JY", "B1", "B2", "Grip", "Pitch", "Roll"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"CSV thiếu cột: {col}")

    # Ép kiểu
    for col in ["JX", "JY", "B1", "B2", "Grip"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    for col in ["Pitch", "Roll"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(float)
    df = df.reset_index(drop=True)

    # Tính metrics
    m = compute_metrics(df)

    # Tạo thư mục output
    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(csv_path)),
        "..", "PDF_Reports"
    )
    os.makedirs(out_dir, exist_ok=True)

    # Tên file PDF
    session_date = datetime.now().strftime("%Y-%m-%d")
    base_name    = os.path.splitext(os.path.basename(csv_path))[0]
    pdf_filename = f"Report_{base_name}.pdf"
    pdf_path     = os.path.join(out_dir, pdf_filename)

    # Vẽ PDF 3 trang
    with PdfPages(pdf_path) as pdf:
        # Metadata PDF
        d = pdf.infodict()
        d["Title"]   = f"BME Rehab Report — {patient_name}"
        d["Author"]  = "BME Rehabilitation System"
        d["Subject"] = "Session Report"

        _page1(pdf, m, patient_name, session_no, session_date)
        _page2(pdf, df, m)
        _page3(pdf, df, m)

    print(f"[BME Report] Đã xuất: {os.path.abspath(pdf_path)}")
    return os.path.abspath(pdf_path)


# ── Chạy thẳng để test ────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Dùng: python bme_report.py <path/to/session.csv> [TênBệnhNhân] [SốPhiên]")
        sys.exit(1)
    csv_file = sys.argv[1]
    pname    = sys.argv[2] if len(sys.argv) > 2 else "Bệnh nhân"
    sno      = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    result   = generate_report(csv_file, pname, sno)
    print(f"PDF: {result}")