@echo off
cd /d "%~dp0"
chcp 65001 >nul
title BME REHABILITATION SYSTEM
chcp 65001 >nul
title BME REHABILITATION SYSTEM

:: ============================================================
::  REHAB.BAT — Khởi động 1-click Hệ thống Phục hồi Chức năng
::  v2.1 — Tích hợp Streamlit Dashboard
::
::  Cách dùng:
::    Double-click file này trước mỗi phiên tập
::    Điền tên bệnh nhân và số phiên khi được hỏi
:: ============================================================

cls
echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║        REHABILITATION SYSTEM          ║
echo  ║        Hệ thống Phục hồi Chức năng Qua Game     ║
echo  ╚══════════════════════════════════════════════════╝
echo.

:: ── KIỂM TRA FILE CẦN THIẾT ──────────────────────────────────

if not exist "bin\Release\luanti.exe" (
    if not exist "bin\Release\minetest.exe" (
        echo [LỖI] Không tìm thấy bin\Release\luanti.exe
        pause & exit /b 1
    )
)

:: ── NHẬP THÔNG TIN PHIÊN TẬP ─────────────────────────────────
echo  ── Thông tin phiên tập ──────────────────────────────────
echo.
set /p BME_PATIENT="  Tên bệnh nhân (VD: NguyenVanA): "
set /p BME_SESSION="  Số phiên tập  (VD: 1):          "

if "%BME_PATIENT%"=="" set BME_PATIENT=Benh_Nhan
if "%BME_SESSION%"=="" set BME_SESSION=1
set BME_PATIENT=%BME_PATIENT: =_%

echo.
echo  ┌──────────────────────────────────────────────────┐
echo  │  Bệnh nhân : %BME_PATIENT%
echo  │  Phiên số  : %BME_SESSION%
echo  │  Thời gian : %DATE% %TIME%
echo  └──────────────────────────────────────────────────┘
echo.

:: Tạo thư mục
if not exist "Patient_Records\Raw_CSV"     mkdir "Patient_Records\Raw_CSV"
if not exist "Patient_Records\PDF_Reports" mkdir "Patient_Records\PDF_Reports"

:: ── BƯỚC 1: Khởi động BME Controller ────────────────────────
echo  [1/4] Khởi động BME Controller (đọc phần cứng)...
set BME_PATIENT=%BME_PATIENT%
set BME_SESSION=%BME_SESSION%
start "BME Controller" /MIN cmd /c ".\.venv\Scripts\python.exe bme_controller.py"

echo       Đang tìm Arduino...
timeout /t 5 /nobreak >nul

:: ── BƯỚC 2: Khởi động Streamlit Dashboard ────────────────────
echo  [2/4] Khởi động Dashboard bác sĩ (http://localhost:8501)...

:: Kiểm tra Streamlit và Python có sẵn không
where streamlit >nul 2>&1
if %errorlevel%==0 (
    start "BME Dashboard" /MIN cmd /c "streamlit run bme_dashboard.py --server.headless true --server.port 8501 2>&1"
    timeout /t 4 /nobreak >nul
    :: Tự động mở trình duyệt
    start "" "http://localhost:8501"
    echo       Dashboard: http://localhost:8501
) else (
    echo  [!] Streamlit chưa cài. Bỏ qua dashboard.
    echo      Cài bằng: pip install streamlit plotly pandas
)

:: ── BƯỚC 3: Khởi động Luanti ─────────────────────────────────
echo  [3/4] Khởi động Phòng tập ảo (Luanti)...
if exist "bin\Release\luanti.exe" (
    start /WAIT "" "bin\Release\luanti.exe"
) else (
    start /WAIT "" "bin\Release\minetest.exe"
)

:: ── BƯỚC 4: Kết thúc phiên ───────────────────────────────────
echo.
echo  [4/4] Game đã đóng. Đang hoàn tất phiên tập...
timeout /t 2 /nobreak >nul

:: Dừng BME Controller → kích hoạt tạo PDF
taskkill /FI "WINDOWTITLE eq BME Controller" /F >nul 2>&1

echo       Đang xử lý báo cáo PDF...
timeout /t 20 /nobreak >nul

:: ── KẾT QUẢ ──────────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║              PHIÊN TẬP HOÀN TẤT                 ║
echo  ╚══════════════════════════════════════════════════╝
echo.
echo  Dữ liệu thô  : Patient_Records\Raw_CSV\
echo  Báo cáo PDF  : Patient_Records\PDF_Reports\
echo  Dashboard    : http://localhost:8501  (vẫn đang chạy)
echo.

if exist "Patient_Records\PDF_Reports" (
    explorer "Patient_Records\PDF_Reports"
)

echo  Dashboard bác sĩ vẫn mở tại http://localhost:8501
echo  Đóng cửa sổ "BME Dashboard" để tắt hoàn toàn.
echo.
echo  Nhấn phím bất kỳ để đóng cửa sổ này...
pause >nul
exit /b 0