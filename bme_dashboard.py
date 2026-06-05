"""
bme_dashboard.py — BME Rehabilitation Dashboard
Streamlit web app: Xem báo cáo tiến triển bệnh nhân theo nhiều phiên tập.

Cài đặt:
    pip install streamlit plotly pandas

Chạy:
    python -m streamlit run bme_dashboard.py

Hoặc mở từ rehab.bat sau khi thêm lệnh:
    start "" cmd /c "streamlit run bme_dashboard.py"
"""

import os
import glob
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# ── Import bme_report để tái dụng compute_metrics ────────────────────────────
# Tìm bme_report.py trong cùng thư mục
_here = Path(__file__).parent
sys.path.insert(0, str(_here))
try:
    import bme_report
    HAS_REPORT = True
except ImportError:
    HAS_REPORT = False

# ══════════════════════════════════════════════════════════════════════════════
#  CẤU HÌNH
# ══════════════════════════════════════════════════════════════════════════════

BASE_DIR    = _here
CSV_DIR     = BASE_DIR / "Patient_Records" / "Raw_CSV"
PDF_DIR     = BASE_DIR / "Patient_Records" / "PDF_Reports"

# Ngưỡng lâm sàng tham khảo
THRESHOLDS = {
    "rom_pitch":    {"good": 30,  "warn": 15,  "unit": "°",     "higher": True,  "label": "aROM Pitch"},
    "rom_roll":     {"good": 25,  "warn": 12,  "unit": "°",     "higher": True,  "label": "aROM Roll"},
    "tremor_index": {"good": 35.0, "warn": 45.0, "unit": "°std",  "higher": False, "label": "Tremor Index"},
    "grip_rate":    {"good": 10,  "warn": 5,   "unit": "lần/ph","higher": True,  "label": "Grip Rate"},
    "active_ratio": {"good": 60,  "warn": 40,  "unit": "%",     "higher": True,  "label": "Active Ratio"},
    "left_ratio":   {"good": 40,  "warn": 25,  "unit": "%",     "higher": True,  "label": "Tay liệt (%)"},
    "fatigue_pct":  {"good": 75,  "warn": 50,  "unit": "%",     "higher": True,  "label": "Fatigue (ROM giữ được)"},
}

C_GOOD  = "#27AE60"
C_WARN  = "#E67E22"
C_BAD   = "#C0392B"
C_BLUE  = "#2E86AB"
C_NAVY  = "#1A3A5C"

# ══════════════════════════════════════════════════════════════════════════════
#  TIỆN ÍCH
# ══════════════════════════════════════════════════════════════════════════════

def get_all_patients() -> list[str]:
    """Lấy danh sách bệnh nhân từ tên file CSV."""
    if not CSV_DIR.exists():
        return []
    files = glob.glob(str(CSV_DIR / "Session_*.csv"))
    names = set()
    for f in files:
        # Format: Session_{PatientName}_{YYYYMMDD_HHMMSS}.csv
        stem = Path(f).stem  # Session_NguyenVanA_20250420_143000
        parts = stem.split("_")
        if len(parts) >= 3:
            # Ghép lại phần tên (có thể chứa "_")
            name = "_".join(parts[1:-2])
            if name:
                names.add(name)
    return sorted(names)


def get_sessions_for_patient(patient: str) -> list[dict]:
    """
    Trả về list các phiên của bệnh nhân, mỗi phần tử gồm:
    { path, date, session_no (index theo thời gian) }
    """
    pattern = str(CSV_DIR / f"Session_{patient}_*.csv")
    files   = sorted(glob.glob(pattern))
    sessions = []
    for i, f in enumerate(files, start=1):
        stem  = Path(f).stem
        parts = stem.split("_")
        # Parse ngày từ 2 phần cuối: YYYYMMDD, HHMMSS
        try:
            date_str = parts[-2] + parts[-1]
            dt = datetime.strptime(date_str, "%Y%m%d%H%M%S")
        except Exception:
            dt = datetime.fromtimestamp(os.path.getmtime(f))
        sessions.append({"path": f, "date": dt, "session_no": i})
    return sessions


def load_metrics_for_patient(patient: str) -> pd.DataFrame:
    """
    Tải và tính metrics cho toàn bộ phiên của bệnh nhân.
    Trả về DataFrame với mỗi hàng = 1 phiên.
    """
    sessions = get_sessions_for_patient(patient)
    rows = []
    for s in sessions:
        try:
            df = pd.read_csv(s["path"])
            # Ép kiểu
            for col in ["JX", "JY", "B1", "B2", "Grip"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
            for col in ["Pitch", "Roll"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            df = df.reset_index(drop=True)

            if HAS_REPORT:
                m = bme_report.compute_metrics(df)
            else:
                m = _fallback_metrics(df)

            m["session_no"]   = s["session_no"]
            m["date"]         = s["date"]
            m["date_label"]   = s["date"].strftime("%d/%m %H:%M")
            m["csv_path"]     = s["path"]
            m["n_samples"]    = len(df)
            rows.append(m)
        except Exception as e:
            st.warning(f"Bỏ qua phiên {s['path']}: {e}")
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def _fallback_metrics(df: pd.DataFrame) -> dict:
    """Tính metrics với thuật toán chuẩn BME (Khắc phục lỗi Unikey & Thiên vị tay phải)."""
    dt = 0.02 # 50Hz
    total_secs = len(df) * dt
    DEADZONE_JOY = 20

    # 1. TÍNH ACTIVE RATIO BẰNG VẬN TỐC (Để không bị thiên vị tay phải)
    pitch_vel = df['Pitch'].diff().abs()
    roll_vel = df['Roll'].diff().abs()
    
    is_right_active = (pitch_vel > 0.5) | (roll_vel > 0.5)
    right_active_count = is_right_active.sum()

    # Tay trái: Joystick đẩy HOẶC Bóp FSR (Vì FSR đã chuyển sang trái)
    is_left_active = (df['JX'].abs() > DEADZONE_JOY) | (df['JY'].abs() > DEADZONE_JOY) | (df['Grip'] > 20)
    left_active_count = is_left_active.sum()

    active_mask = is_right_active | is_left_active
    active_secs = active_mask.sum() * dt

    # 2. TÍNH TỶ LỆ CÂN BẰNG (Bilateral Ratio)
    total_active_count = left_active_count + right_active_count
    if total_active_count > 0:
        left_ratio = (left_active_count / total_active_count) * 100
        right_ratio = (right_active_count / total_active_count) * 100
    else:
        left_ratio = 0.0
        right_ratio = 0.0

    # 3. TÍNH CÁC THAM SỐ KHÁC
    grip_edges  = (df["Grip"].diff() == 1).sum()
    rom_pitch = df["Pitch"].max() - df["Pitch"].min()
    rom_roll = df["Roll"].max() - df["Roll"].min()
    
    # Chỉ số Mỏi (Fatigue): So sánh 20% đầu vs 20% cuối
    n_20 = int(len(df) * 0.2)
    if n_20 > 0:
        first_20, last_20 = df.iloc[:n_20], df.iloc[-n_20:]
        rom_first = (first_20['Pitch'].max() - first_20['Pitch'].min()) + (first_20['Roll'].max() - first_20['Roll'].min())
        rom_last = (last_20['Pitch'].max() - last_20['Pitch'].min()) + (last_20['Roll'].max() - last_20['Roll'].min())
        fatigue = (rom_last / rom_first * 100) if rom_first > 0 else 100
    else:
        fatigue = 100.0

    return {
        "rom_pitch":    round(rom_pitch, 1),
        "rom_roll":     round(rom_roll, 1),
        "tremor_index": round(df["Pitch"].rolling(50).std().dropna().mean(), 2) if len(df) > 50 else 0.0,
        "grip_count":   int(grip_edges),
        "grip_rate":    round(grip_edges / (total_secs / 60) if total_secs > 0 else 0, 1),
        "active_secs":  round(active_secs, 1),
        "rest_secs":    round(total_secs - active_secs, 1),
        "active_ratio": round(active_secs / total_secs * 100 if total_secs > 0 else 0, 1),
        "left_ratio":   round(left_ratio, 1),
        "right_ratio":  round(right_ratio, 1),
        "fatigue_pct":  round(fatigue, 1),
        "task_duration":round(total_secs, 1),
        "pitch_min":    round(df["Pitch"].min(), 1), 
        "pitch_max":    round(df["Pitch"].max(), 1),
        "roll_min":     round(df["Roll"].min(),  1), 
        "roll_max":     round(df["Roll"].max(),  1),
        "tremor_pitch": 0.0, "tremor_roll": 0.0,
        "early_rom":    0.0, "late_rom":    0.0,
    }


def metric_color(key: str, value: float) -> str:
    t = THRESHOLDS.get(key)
    if not t:
        return C_BLUE
    if t["higher"]:
        return C_GOOD if value >= t["good"] else (C_WARN if value >= t["warn"] else C_BAD)
    else:
        return C_GOOD if value <= t["good"] else (C_WARN if value <= t["warn"] else C_BAD)


def metric_status(key: str, value: float) -> str:
    t = THRESHOLDS.get(key)
    if not t:
        return ""
    if t["higher"]:
        return "✅ Tốt" if value >= t["good"] else ("⚠️ Trung bình" if value >= t["warn"] else "🔴 Cần cải thiện")
    else:
        return "✅ Tốt" if value <= t["good"] else ("⚠️ Trung bình" if value <= t["warn"] else "🔴 Cần chú ý")


# ══════════════════════════════════════════════════════════════════════════════
#  VẼ BIỂU ĐỒ
# ══════════════════════════════════════════════════════════════════════════════

def chart_trend(mdf: pd.DataFrame, key: str) -> go.Figure:
    """Biểu đồ tiến triển một tham số theo các phiên."""
    t    = THRESHOLDS.get(key, {})
    unit = t.get("unit", "")
    name = t.get("label", key)

    colors = [metric_color(key, v) for v in mdf[key]]
    fig = go.Figure()

    # Vùng ngưỡng
    if t:
        g, w = t.get("good"), t.get("warn")
        if t.get("higher"):
            fig.add_hrect(y0=g, y1=g * 1.5 + 1,  fillcolor=C_GOOD, opacity=0.06, line_width=0)
            fig.add_hrect(y0=w, y1=g,              fillcolor=C_WARN, opacity=0.06, line_width=0)
            fig.add_hrect(y0=0, y1=w,              fillcolor=C_BAD,  opacity=0.06, line_width=0)
            fig.add_hline(y=g, line_dash="dot", line_color=C_GOOD, line_width=1,
                          annotation_text=f"Tốt ≥{g}", annotation_position="top right")
        else:
            fig.add_hrect(y0=0, y1=g,              fillcolor=C_GOOD, opacity=0.06, line_width=0)
            fig.add_hline(y=g, line_dash="dot", line_color=C_GOOD, line_width=1,
                          annotation_text=f"Tốt ≤{g}", annotation_position="top right")

    # Đường xu hướng
    fig.add_trace(go.Scatter(
        x=mdf["date_label"], y=mdf[key],
        mode="lines+markers",
        line=dict(color=C_BLUE, width=2.5),
        marker=dict(size=10, color=colors, line=dict(width=1.5, color="white")),
        text=[f"Phiên {r.session_no}<br>{r.date.strftime('%d/%m/%Y %H:%M')}<br>{v:.1f} {unit}"
              for r, v in zip(mdf.itertuples(), mdf[key])],
        hovertemplate="%{text}<extra></extra>",
    ))

    fig.update_layout(
        title=dict(text=f"<b>{name}</b> theo phiên", font=dict(color=C_NAVY, size=14)),
        xaxis_title="Phiên tập",
        yaxis_title=f"{name} ({unit})",
        plot_bgcolor="white",
        paper_bgcolor="white",
        height=320,
        margin=dict(l=50, r=20, t=50, b=50),
        font=dict(family="Arial, sans-serif", size=11),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#EEE")
    fig.update_yaxes(showgrid=True, gridcolor="#EEE")
    return fig


def chart_radar(mdf: pd.DataFrame) -> go.Figure:
    """Radar chart so sánh phiên đầu vs phiên cuối (normalize 0–100)."""
    keys  = ["rom_pitch", "rom_roll", "active_ratio", "grip_rate", "left_ratio"]
    norms = {
        "rom_pitch":    (0, 60),  "rom_roll":    (0, 45),
        "active_ratio": (0, 100), "grip_rate":   (0, 20),
        "left_ratio":   (0, 100),
    }
    labels = [THRESHOLDS[k]["label"] for k in keys]

    def normalize(key, val):
        lo, hi = norms[key]
        return min(100, max(0, (val - lo) / (hi - lo) * 100)) if hi > lo else 0

    fig = go.Figure()
    sessions_to_show = []
    if len(mdf) >= 1:
        sessions_to_show.append(("Phiên 1", mdf.iloc[0], "rgba(46,134,171,0.3)", C_BLUE))
    if len(mdf) >= 2:
        sessions_to_show.append((f"Phiên {mdf.iloc[-1]['session_no']}", mdf.iloc[-1], "rgba(39,174,96,0.3)", C_GOOD))

    for label, row, fill, color in sessions_to_show:
        vals = [normalize(k, row[k]) for k in keys] + [normalize(keys[0], row[keys[0]])]
        fig.add_trace(go.Scatterpolar(
            r=vals, theta=labels + [labels[0]],
            fill="toself", fillcolor=fill,
            line=dict(color=color, width=2),
            name=label,
        ))

    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        title=dict(text="<b>So sánh: Phiên đầu vs Phiên mới nhất</b>",
                   font=dict(color=C_NAVY, size=14)),
        height=380, paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=-0.2),
        font=dict(family="Arial, sans-serif"),
    )
    return fig


def chart_session_detail(csv_path: str, smooth_factor: int = 1) -> go.Figure:
    """Biểu đồ tín hiệu thô của 1 phiên (Pitch, Roll, Grip).
    smooth_factor: cửa sổ Moving Average để làm mượt (1 = không lọc).
    """
    df = pd.read_csv(csv_path)
    for col in ["Pitch", "Roll"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["Grip"] = pd.to_numeric(df["Grip"], errors="coerce").fillna(0).astype(int)

    # Áp dụng Moving Average nếu smooth_factor > 1
    if smooth_factor > 1:
        df["Pitch"] = df["Pitch"].rolling(smooth_factor, min_periods=1).mean()
        df["Roll"]  = df["Roll"].rolling(smooth_factor,  min_periods=1).mean()

    t = [i * 0.02 for i in range(len(df))]

    # Subsample để tránh render quá nặng (tối đa 3000 điểm)
    step = max(1, len(df) // 3000)
    t_s = t[::step]; df_s = df.iloc[::step]

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        subplot_titles=("Pitch (°)", "Roll (°)", "Grip"),
                        vertical_spacing=0.08)

    fig.add_trace(go.Scatter(x=t_s, y=df_s["Pitch"], mode="lines",
                             line=dict(color=C_BLUE, width=1), name="Pitch"), row=1, col=1)
    fig.add_trace(go.Scatter(x=t_s, y=df_s["Roll"], mode="lines",
                             line=dict(color="#E07B54", width=1), name="Roll"), row=2, col=1)
    fig.add_trace(go.Scatter(x=t_s, y=df_s["Grip"], mode="lines",
                             line=dict(color=C_GOOD, width=1.5),
                             fill="tozeroy", fillcolor="rgba(39,174,96,0.2)",
                             name="Grip"), row=3, col=1)

    fig.update_xaxes(title_text="Thời gian (s)", row=3, col=1)
    fig.update_layout(
        height=480, paper_bgcolor="white", plot_bgcolor="white",
        showlegend=False,
        font=dict(family="Arial, sans-serif", size=10),
        margin=dict(l=50, r=20, t=40, b=40),
    )
    for i in range(1, 4):
        fig.update_xaxes(showgrid=True, gridcolor="#EEE", row=i, col=1)
        fig.update_yaxes(showgrid=True, gridcolor="#EEE", row=i, col=1)
    return fig


def chart_bilateral_progression(mdf: pd.DataFrame) -> go.Figure:
    """Stacked bar: % đóng góp tay trái vs tay phải theo phiên."""
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Tay liệt / Trái",
        x=mdf["date_label"], y=mdf["left_ratio"],
        marker_color=C_BLUE,
        text=[f"{v:.0f}%" for v in mdf["left_ratio"]],
        textposition="inside",
    ))
    fig.add_trace(go.Bar(
        name="Tay lành / Phải",
        x=mdf["date_label"], y=mdf["right_ratio"],
        marker_color="#E07B54",
        text=[f"{v:.0f}%" for v in mdf["right_ratio"]],
        textposition="inside",
    ))
    fig.add_hline(y=40, line_dash="dot", line_color=C_GOOD, line_width=1.5,
                  annotation_text="Mục tiêu tay liệt ≥ 40%")
    fig.update_layout(
        barmode="stack", height=300,
        title=dict(text="<b>Phân bổ hai tay theo phiên</b>", font=dict(color=C_NAVY)),
        xaxis_title="Phiên tập", yaxis_title="%",
        paper_bgcolor="white", plot_bgcolor="white",
        font=dict(family="Arial, sans-serif"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=50, r=20, t=60, b=50),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  UI CHÍNH
# ══════════════════════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title="BME Rehabilitation Dashboard",
        page_icon="🏥",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── CSS tùy chỉnh ──────────────────────────────────────────────────────
    st.markdown("""
    <style>
    .main { background-color: #F7F9FC; }
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    h1 { color: #1A3A5C; font-size: 1.8rem !important; }
    h2 { color: #1A3A5C; font-size: 1.3rem !important; border-bottom: 2px solid #2E86AB; padding-bottom: 4px; }
    h3 { color: #2E86AB; font-size: 1.05rem !important; }
    .stMetric > div { background: white; border-radius: 10px;
                      padding: 12px; border: 1px solid #DDE3EC; }
    .stMetric label { color: #1A3A5C !important; font-weight: 600 !important; }
    div[data-testid="stSidebar"] { background: #1A3A5C; }
    div[data-testid="stSidebar"] * { color: white !important; }
    div[data-testid="stSidebar"] .stSelectbox label { color: #AAC4E0 !important; }
    </style>
    """, unsafe_allow_html=True)

    # ── SIDEBAR ─────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## 🏥 BME Rehab")
        st.markdown("---")

        patients = get_all_patients()

        page = st.radio("📋 Trang", [
            "📊 Tổng quan tiến triển",
            "🔬 Chi tiết phiên tập",
            "📈 So sánh 7 tham số",
            "📝 Xuất báo cáo",
            "📂 Nạp & Phân tích file mới",
        ])
        st.markdown("---")

        if page != "📂 Nạp & Phân tích file mới":
            if not patients:
                st.warning("Chưa có dữ liệu.\nChạy ít nhất 1 phiên tập.")
                st.markdown(f"**Thư mục:** `{CSV_DIR}`")
                st.stop()
            selected_patient = st.selectbox("👤 Bệnh nhân", patients)
        else:
            selected_patient = None

        st.markdown(f"**Dữ liệu:** `{CSV_DIR}`")
        st.markdown(f"**Báo cáo:** `{PDF_DIR}`")

    # ── LOAD DỮ LIỆU (chỉ khi không ở trang Upload) ────────────────────────
    if page != "📂 Nạp & Phân tích file mới":
        with st.spinner("Đang tải dữ liệu..."):
            mdf = load_metrics_for_patient(selected_patient)

        if mdf.empty:
            st.error(f"Không tìm thấy file CSV cho bệnh nhân: **{selected_patient}**")
            st.stop()

        last = mdf.iloc[-1]  # Phiên mới nhất
    else:
        mdf = pd.DataFrame()
        last = None

    # ════════════════════════════════════════════════════════════════════════
    #  TRANG 1 — TỔNG QUAN TIẾN TRIỂN
    # ════════════════════════════════════════════════════════════════════════
    if page == "📊 Tổng quan tiến triển":
        st.title(f"📊 Tiến triển — {selected_patient.replace('_', ' ')}")
        st.caption(f"Tổng cộng **{len(mdf)} phiên tập** | Phiên gần nhất: "
                   f"**{last['date'].strftime('%d/%m/%Y %H:%M')}**")

        # ── 7 KPI phiên mới nhất ────────────────────────────────────────────
        st.markdown("## Kết quả phiên mới nhất")
        kpi_keys = ["rom_pitch", "rom_roll", "tremor_index",
                    "grip_rate", "active_ratio", "left_ratio", "fatigue_pct"]

        cols = st.columns(7)
        for col, key in zip(cols, kpi_keys):
            t   = THRESHOLDS[key]
            val = last[key]
            delta = None
            if len(mdf) >= 2:
                prev_val = mdf.iloc[-2][key]
                delta    = round(val - prev_val, 1)
            with col:
                st.metric(
                    label=t["label"],
                    value=f"{val:.1f} {t['unit']}",
                    delta=f"{delta:+.1f}" if delta is not None else None,
                    delta_color="normal" if t["higher"] else "inverse",
                )

        # ── Trạng thái tổng hợp ──────────────────────────────────────────────
        statuses = [metric_status(k, last[k]) for k in kpi_keys]
        good_cnt = sum(1 for s in statuses if "✅" in s)
        warn_cnt = sum(1 for s in statuses if "⚠️" in s)
        bad_cnt  = sum(1 for s in statuses if "🔴" in s)

        st.markdown("---")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("✅ Chỉ số tốt",        f"{good_cnt}/7")
        c2.metric("⚠️ Cần theo dõi",      f"{warn_cnt}/7")
        c3.metric("🔴 Cần cải thiện",     f"{bad_cnt}/7")
        c4.metric("⏱ Thời gian phiên",    f"{last['task_duration']/60:.1f} phút")

        # ── Radar chart ──────────────────────────────────────────────────────
        st.markdown("---")
        col_r, col_bi = st.columns(2)
        with col_r:
            st.markdown("## Radar — Phiên đầu vs Mới nhất")
            st.plotly_chart(chart_radar(mdf), use_container_width=True)
        with col_bi:
            st.markdown("## Phân bổ hai tay")
            st.plotly_chart(chart_bilateral_progression(mdf), use_container_width=True)

        # ── Xu hướng 7 tham số ────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("## Xu hướng từng tham số qua các phiên")

        row1 = st.columns(2)
        row2 = st.columns(2)
        row3 = st.columns(2)
        rows_cols = [row1[0], row1[1], row2[0], row2[1], row3[0], row3[1]]

        for i, key in enumerate(["rom_pitch", "rom_roll", "tremor_index",
                                   "active_ratio", "grip_rate", "fatigue_pct"]):
            with rows_cols[i]:
                st.plotly_chart(chart_trend(mdf, key), use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    #  TRANG 2 — CHI TIẾT PHIÊN TẬP
    # ════════════════════════════════════════════════════════════════════════
    elif page == "🔬 Chi tiết phiên tập":
        st.title(f"🔬 Chi tiết phiên — {selected_patient.replace('_', ' ')}")

        session_options = {
            f"Phiên {r.session_no} — {r.date.strftime('%d/%m/%Y %H:%M')}": r.csv_path
            for r in mdf.itertuples()
        }
        selected_label = st.selectbox("Chọn phiên tập", list(session_options.keys()),
                                       index=len(session_options) - 1)
        selected_csv  = session_options[selected_label]
        selected_row  = mdf[mdf["csv_path"] == selected_csv].iloc[0]

        # KPI phiên được chọn
        st.markdown("### Chỉ số phiên này")
        cols = st.columns(7)
        kpi_keys = ["rom_pitch", "rom_roll", "tremor_index",
                    "grip_rate", "active_ratio", "left_ratio", "fatigue_pct"]
        for col, key in zip(cols, kpi_keys):
            t   = THRESHOLDS[key]
            val = selected_row[key]
            status = metric_status(key, val)
            with col:
                st.metric(t["label"], f"{val:.1f} {t['unit']}")
                st.caption(status)

        # Biểu đồ tín hiệu thô
        st.markdown("---")
        st.markdown("### Tín hiệu thô — Pitch, Roll, Grip")
        st.caption(f"Tổng: **{selected_row['n_samples']}** mẫu "
                   f"({selected_row['n_samples'] * 0.02:.1f}s) "
                   f"| File: `{os.path.basename(selected_csv)}`")

        smooth_factor = st.slider(
            "🔧 Độ mượt biểu đồ (Lọc Moving Average)",
            min_value=1, max_value=20, value=5,
            help="1 = không lọc (giữ nguyên nhiễu). Tăng lên để thấy xu hướng rõ hơn.",
        )

        with st.spinner("Đang vẽ biểu đồ..."):
            st.plotly_chart(
                chart_session_detail(selected_csv, smooth_factor=smooth_factor),
                use_container_width=True,
            )

        # Bảng thống kê chi tiết
        st.markdown("### Thống kê chi tiết")
        detail_data = {
            "Tham số": [
                "aROM Pitch (biên độ cổ tay trước/sau)",
                "aROM Roll  (biên độ cổ tay trái/phải)",
                "Pitch min / max",
                "Roll min / max",
                "Tremor Index",
                "Task Duration",
                "Grip count / Grip rate",
                "Active time / Rest time",
                "Active ratio",
                "Tay trái / Tay phải",
                "Fatigue Index",
            ],
            "Giá trị": [
                f"{selected_row['rom_pitch']}°",
                f"{selected_row['rom_roll']}°",
                f"{selected_row['pitch_min']}° / {selected_row['pitch_max']}°",
                f"{selected_row['roll_min']}° / {selected_row['roll_max']}°",
                f"{selected_row['tremor_index']} °std",
                f"{selected_row['task_duration']/60:.1f} phút",
                f"{selected_row['grip_count']} lần / {selected_row['grip_rate']} lần/phút",
                f"{selected_row['active_secs']:.0f}s / {selected_row['rest_secs']:.0f}s",
                f"{selected_row['active_ratio']}%",
                f"{selected_row['left_ratio']}% / {selected_row['right_ratio']}%",
                f"{selected_row['fatigue_pct']}%",
            ],
            "Đánh giá": [
                metric_status("rom_pitch",    selected_row["rom_pitch"]),
                metric_status("rom_roll",     selected_row["rom_roll"]),
                "—", "—",
                metric_status("tremor_index", selected_row["tremor_index"]),
                "—",
                metric_status("grip_rate",    selected_row["grip_rate"]),
                "—",
                metric_status("active_ratio", selected_row["active_ratio"]),
                metric_status("left_ratio",   selected_row["left_ratio"]),
                metric_status("fatigue_pct",  selected_row["fatigue_pct"]),
            ],
        }
        st.dataframe(pd.DataFrame(detail_data), use_container_width=True, hide_index=True)

        # ── PHẦN LƯU MASTER DATA ────────────────────────────────────────────
        st.markdown("---")
        st.subheader("💾 Lưu vào Cơ sở dữ liệu Đồ án")
        st.caption("Lưu 7 tham số của phiên đang xem vào file Excel tổng để phân tích nhóm.")

        col_input1, col_input2, col_input3 = st.columns(3)
        with col_input1:
            patient_id = st.text_input(
                "Mã Bệnh nhân/Người test",
                value=selected_patient,
                placeholder="VD: NguoiThuong_01, BN_01",
                key="master_patient_id",
            )
        with col_input2:
            session_type = st.selectbox(
                "Phân loại",
                ["Baseline (Người khỏe mạnh)", "Bệnh nhân (Trước tập)", "Bệnh nhân (Sau tập)"],
                key="master_session_type",
            )
        with col_input3:
            st.write("")
            st.write("")
            if st.button("💾 Lưu vào Master Data", type="primary", key="btn_save_master"):
                if not patient_id.strip():
                    st.error("Vui lòng nhập Mã Bệnh nhân!")
                else:
                    master_file = BASE_DIR / "Patient_Records" / "Excel_Reports" / "Master_Data_DoAn.xlsx"
                    master_file.parent.mkdir(parents=True, exist_ok=True)

                    new_data = {
                        "Thời gian":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Mã Hồ Sơ":         patient_id.strip(),
                        "Phân loại":        session_type,
                        "Phiên số":         int(selected_row["session_no"]),
                        "Ngày phiên":       selected_row["date"].strftime("%Y-%m-%d %H:%M"),
                        "aROM_Pitch (°)":   selected_row["rom_pitch"],
                        "aROM_Roll (°)":    selected_row["rom_roll"],
                        "Tremor Index":     selected_row["tremor_index"],
                        "Grip Rate (lần/ph)": selected_row["grip_rate"],
                        "Active Ratio (%)": selected_row["active_ratio"],
                        "Tay trái (%)":     selected_row["left_ratio"],
                        "Fatigue (%)":      selected_row["fatigue_pct"],
                    }
                    new_row_df = pd.DataFrame([new_data])

                    if master_file.exists():
                        master_df = pd.read_excel(str(master_file))
                        master_df = pd.concat([master_df, new_row_df], ignore_index=True)
                    else:
                        master_df = new_row_df

                    master_df.to_excel(str(master_file), index=False)
                    st.success(
                        f"✅ Đã lưu **{patient_id}** — Phiên {int(selected_row['session_no'])} "
                        f"({session_type}) vào `Master_Data_DoAn.xlsx`!"
                    )

    # ════════════════════════════════════════════════════════════════════════
    #  TRANG 3 — SO SÁNH 7 THAM SỐ
    # ════════════════════════════════════════════════════════════════════════
    elif page == "📈 So sánh 7 tham số":
        st.title(f"📈 So sánh 7 tham số — {selected_patient.replace('_', ' ')}")

        # Bảng tất cả phiên
        display_cols = {
            "session_no": "Phiên",
            "date_label": "Ngày/Giờ",
            "rom_pitch":    "aROM Pitch°",
            "rom_roll":     "aROM Roll°",
            "tremor_index": "Tremor",
            "grip_rate":    "Grip/phút",
            "active_ratio": "Active%",
            "left_ratio":   "Tay trái%",
            "fatigue_pct":  "Fatigue%",
            "task_duration": "Thời gian(s)",
        }
        display_df = mdf[list(display_cols.keys())].rename(columns=display_cols)
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # Download CSV
        csv_bytes = mdf.drop(columns=["csv_path"], errors="ignore").to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️  Tải bảng metrics (CSV)",
            data=csv_bytes,
            file_name=f"metrics_{selected_patient}.csv",
            mime="text/csv",
        )

        st.markdown("---")
        st.markdown("### Xu hướng toàn bộ 7 tham số")
        all_keys = ["rom_pitch", "rom_roll", "tremor_index",
                    "grip_rate", "active_ratio", "left_ratio", "fatigue_pct"]
        for key in all_keys:
            st.plotly_chart(chart_trend(mdf, key), use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    #  TRANG 4 — XUẤT BÁO CÁO PDF
    # ════════════════════════════════════════════════════════════════════════
    elif page == "📝 Xuất báo cáo":
        st.title(f"📝 Xuất báo cáo PDF — {selected_patient.replace('_', ' ')}")

        if not HAS_REPORT:
            st.error("Không tìm thấy `bme_report.py`. Đặt file này cùng thư mục với dashboard.")
            st.stop()

        session_options = {
            f"Phiên {r.session_no} — {r.date.strftime('%d/%m/%Y %H:%M')}": (r.csv_path, r.session_no)
            for r in mdf.itertuples()
        }

        col1, col2 = st.columns(2)
        with col1:
            selected_label = st.selectbox("Chọn phiên cần xuất PDF",
                                           list(session_options.keys()),
                                           index=len(session_options) - 1)
        with col2:
            patient_display = st.text_input("Tên hiển thị trên báo cáo",
                                             value=selected_patient.replace("_", " "))

        selected_csv, session_no = session_options[selected_label]

        if st.button("📄 Tạo báo cáo PDF", type="primary"):
            with st.spinner("Đang tạo báo cáo PDF 3 trang..."):
                try:
                    pdf_path = bme_report.generate_report(
                        selected_csv,
                        patient_name = patient_display,
                        session_no   = session_no,
                    )
                    st.success(f"✅ Đã tạo: `{pdf_path}`")
                    with open(pdf_path, "rb") as f:
                        st.download_button(
                            "⬇️  Tải PDF ngay",
                            data=f.read(),
                            file_name=os.path.basename(pdf_path),
                            mime="application/pdf",
                        )
                except Exception as e:
                    st.error(f"Lỗi tạo PDF: {e}")

        st.markdown("---")
        st.markdown("### Tất cả báo cáo PDF đã tạo")
        if PDF_DIR.exists():
            pdfs = sorted(PDF_DIR.glob("*.pdf"), key=os.path.getmtime, reverse=True)
            if pdfs:
                for pdf in pdfs[:20]:
                    col_a, col_b = st.columns([4, 1])
                    with col_a:
                        st.text(f"📄 {pdf.name}")
                    with col_b:
                        with open(str(pdf), "rb") as f:
                            st.download_button("Tải", data=f.read(),
                                               file_name=pdf.name,
                                               mime="application/pdf",
                                               key=str(pdf))
            else:
                st.info("Chưa có báo cáo PDF nào.")
        else:
            st.info(f"Thư mục PDF chưa tồn tại: `{PDF_DIR}`")



    # ════════════════════════════════════════════════════════════════════════
    #  TRANG 5 — NẠP & PHÂN TÍCH FILE MỚI
    # ════════════════════════════════════════════════════════════════════════
    elif page == "📂 Nạp & Phân tích file mới":
        st.title("📂 Nạp & Phân tích file CSV mới")
        st.caption("Upload file Raw CSV từ thiết bị → tính 7 tham số ngay lập tức, không cần lưu vào thư mục.")

        uploaded_file = st.file_uploader(
            "Bấm vào đây để chọn file CSV (hoặc kéo thả vào đây)",
            type=["csv"],
            help="File phải có các cột: Pitch, Roll, Grip, JX, JY",
        )

        if uploaded_file is None:
            st.info("👆 Chưa có file nào được chọn. Bấm vào ô trên để mở thư mục.")
            st.stop()

        # ── Đọc & kiểm tra file ─────────────────────────────────────────────
        try:
            df_up = pd.read_csv(uploaded_file)
        except Exception as e:
            st.error(f"Không đọc được file CSV: {e}")
            st.stop()

        required_cols = {"Pitch", "Roll", "Grip", "JX", "JY"}
        missing = required_cols - set(df_up.columns)
        if missing:
            st.error(f"File thiếu cột: **{', '.join(missing)}**. Kiểm tra lại format CSV.")
            st.stop()

        # Ép kiểu
        for col in ["JX", "JY", "Grip"]:
            df_up[col] = pd.to_numeric(df_up[col], errors="coerce").fillna(0).astype(int)
        for col in ["Pitch", "Roll"]:
            df_up[col] = pd.to_numeric(df_up[col], errors="coerce").fillna(0.0)
        df_up = df_up.reset_index(drop=True)

        st.success(f"✅ Đã nạp: **{uploaded_file.name}** — {len(df_up):,} mẫu "
                   f"({len(df_up) * 0.02:.1f} giây)")

        # ── Tính metrics ────────────────────────────────────────────────────
        if HAS_REPORT:
            up_metrics = bme_report.compute_metrics(df_up)
        else:
            up_metrics = _fallback_metrics(df_up)

        # ── Hiển thị 7 KPI ──────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("## 📊 7 Tham số Y Sinh Học")

        kpi_keys = ["rom_pitch", "rom_roll", "tremor_index",
                    "grip_rate", "active_ratio", "left_ratio", "fatigue_pct"]
        cols_kpi = st.columns(7)
        for col, key in zip(cols_kpi, kpi_keys):
            t = THRESHOLDS[key]
            val = up_metrics.get(key, 0)
            with col:
                st.metric(label=t["label"], value=f"{val:.1f} {t['unit']}")
                st.caption(metric_status(key, val))

        # ── Bảng chi tiết ───────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### Bảng chi tiết")
        detail_data = {
            "Tham số": [
                "aROM Pitch (biên độ cổ tay trước/sau)",
                "aROM Roll  (biên độ cổ tay trái/phải)",
                "Pitch min / max",
                "Roll min / max",
                "Tremor Index",
                "Task Duration",
                "Grip count / Grip rate",
                "Active time / Rest time",
                "Active ratio",
                "Tay trái / Tay phải",
                "Fatigue Index",
            ],
            "Giá trị": [
                f"{up_metrics.get('rom_pitch', 0)}°",
                f"{up_metrics.get('rom_roll', 0)}°",
                f"{up_metrics.get('pitch_min', 0)}° / {up_metrics.get('pitch_max', 0)}°",
                f"{up_metrics.get('roll_min', 0)}° / {up_metrics.get('roll_max', 0)}°",
                f"{up_metrics.get('tremor_index', 0)} °std",
                f"{up_metrics.get('task_duration', 0)/60:.1f} phút",
                f"{up_metrics.get('grip_count', 0)} lần / {up_metrics.get('grip_rate', 0)} lần/phút",
                f"{up_metrics.get('active_secs', 0):.0f}s / {up_metrics.get('rest_secs', 0):.0f}s",
                f"{up_metrics.get('active_ratio', 0)}%",
                f"{up_metrics.get('left_ratio', 0)}% / {up_metrics.get('right_ratio', 0)}%",
                f"{up_metrics.get('fatigue_pct', 0)}%",
            ],
            "Đánh giá": [
                metric_status("rom_pitch",    up_metrics.get("rom_pitch", 0)),
                metric_status("rom_roll",     up_metrics.get("rom_roll", 0)),
                "—", "—",
                metric_status("tremor_index", up_metrics.get("tremor_index", 0)),
                "—",
                metric_status("grip_rate",    up_metrics.get("grip_rate", 0)),
                "—",
                metric_status("active_ratio", up_metrics.get("active_ratio", 0)),
                metric_status("left_ratio",   up_metrics.get("left_ratio", 0)),
                metric_status("fatigue_pct",  up_metrics.get("fatigue_pct", 0)),
            ],
        }
        st.dataframe(pd.DataFrame(detail_data), use_container_width=True, hide_index=True)

        # ── Biểu đồ tín hiệu thô ────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 📈 Biểu đồ tín hiệu thô")

        smooth_up = st.slider(
            "🔧 Độ mượt biểu đồ (Moving Average)",
            min_value=1, max_value=20, value=5,
            key="smooth_upload",
            help="1 = không lọc. Kéo lên để thấy xu hướng rõ hơn.",
        )

        df_plot = df_up.copy()
        if smooth_up > 1:
            df_plot["Pitch"] = df_plot["Pitch"].rolling(smooth_up, min_periods=1).mean()
            df_plot["Roll"]  = df_plot["Roll"].rolling(smooth_up,  min_periods=1).mean()

        t_axis = [i * 0.02 for i in range(len(df_plot))]
        step   = max(1, len(df_plot) // 3000)
        t_s    = t_axis[::step]
        df_s   = df_plot.iloc[::step]

        fig_up = make_subplots(rows=3, cols=1, shared_xaxes=True,
                               subplot_titles=("Pitch (°)", "Roll (°)", "Grip (lực bóp)"),
                               vertical_spacing=0.08)
        fig_up.add_trace(go.Scatter(x=t_s, y=df_s["Pitch"], mode="lines",
                                    line=dict(color=C_BLUE, width=1), name="Pitch"), row=1, col=1)
        fig_up.add_trace(go.Scatter(x=t_s, y=df_s["Roll"], mode="lines",
                                    line=dict(color="#E07B54", width=1), name="Roll"), row=2, col=1)
        fig_up.add_trace(go.Scatter(x=t_s, y=df_s["Grip"], mode="lines",
                                    line=dict(color=C_GOOD, width=1.5),
                                    fill="tozeroy", fillcolor="rgba(39,174,96,0.2)",
                                    name="Grip"), row=3, col=1)
        fig_up.update_xaxes(title_text="Thời gian (s)", row=3, col=1)
        fig_up.update_layout(
            height=500, paper_bgcolor="white", plot_bgcolor="white",
            showlegend=False,
            font=dict(family="Arial, sans-serif", size=10),
            margin=dict(l=50, r=20, t=40, b=40),
        )
        for i in range(1, 4):
            fig_up.update_xaxes(showgrid=True, gridcolor="#EEE", row=i, col=1)
            fig_up.update_yaxes(showgrid=True, gridcolor="#EEE", row=i, col=1)
        st.plotly_chart(fig_up, use_container_width=True)

        # ── Lưu vào Master Data ─────────────────────────────────────────────
        st.markdown("---")
        st.subheader("💾 Lưu vào Cơ sở dữ liệu Đồ án")
        st.caption("Lưu 7 tham số vừa tính vào file Excel tổng để phân tích nhóm.")

        col_u1, col_u2, col_u3 = st.columns(3)
        with col_u1:
            up_patient_id = st.text_input(
                "Mã Bệnh nhân/Người test",
                placeholder="VD: NguoiThuong_01, BN_01",
                key="up_patient_id",
            )
        with col_u2:
            up_session_type = st.selectbox(
                "Phân loại",
                ["Baseline (Người khỏe mạnh)", "Bệnh nhân (Trước tập)", "Bệnh nhân (Sau tập)"],
                key="up_session_type",
            )
        with col_u3:
            st.write("")
            st.write("")
            if st.button("💾 Lưu vào Master Data", type="primary", key="btn_up_master"):
                if not up_patient_id.strip():
                    st.error("Vui lòng nhập Mã Bệnh nhân!")
                else:
                    master_file = BASE_DIR / "Patient_Records" / "Excel_Reports" / "Master_Data_DoAn.xlsx"
                    master_file.parent.mkdir(parents=True, exist_ok=True)

                    new_data = {
                        "Thời gian":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Mã Hồ Sơ":         up_patient_id.strip(),
                        "Phân loại":        up_session_type,
                        "Phiên số":         "—",
                        "Ngày phiên":       datetime.now().strftime("%Y-%m-%d"),
                        "aROM_Pitch (°)":   up_metrics.get("rom_pitch", 0),
                        "aROM_Roll (°)":    up_metrics.get("rom_roll", 0),
                        "Tremor Index":     up_metrics.get("tremor_index", 0),
                        "Grip Rate (lần/ph)": up_metrics.get("grip_rate", 0),
                        "Active Ratio (%)": up_metrics.get("active_ratio", 0),
                        "Tay trái (%)":     up_metrics.get("left_ratio", 0),
                        "Fatigue (%)":      up_metrics.get("fatigue_pct", 0),
                        "File gốc":         uploaded_file.name,
                    }
                    new_row_df = pd.DataFrame([new_data])

                    if master_file.exists():
                        master_df = pd.read_excel(str(master_file))
                        master_df = pd.concat([master_df, new_row_df], ignore_index=True)
                    else:
                        master_df = new_row_df

                    master_df.to_excel(str(master_file), index=False)
                    st.success(
                        f"✅ Đã lưu **{up_patient_id}** ({up_session_type}) "
                        f"từ file `{uploaded_file.name}` vào `Master_Data_DoAn.xlsx`!"
                    )


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()