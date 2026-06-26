@echo off
cd /d "%~dp0"
chcp 65001 >nul
title HE THONG PHUC HOI CHUC NANG - BME

cls
echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║        HE THONG PHUC HOI CHUC NANG - BME        ║
echo  ║         Rehabilitation System v2.2              ║
echo  ╚══════════════════════════════════════════════════╝
echo.

:: ── KIỂM TRA FILE CẦN THIẾT ──────────────────────────────────
if not exist "bin\Release\luanti.exe" (
    if not exist "bin\Release\minetest.exe" (
        echo  [LOI] Khong tim thay bin\Release\luanti.exe
        echo       Kiem tra lai thu muc cai dat.
        pause & exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo  [LOI] Khong tim thay .venv\Scripts\python.exe
    echo       Kiem tra lai moi truong Python.
    pause & exit /b 1
)

:: ── NHẬP THÔNG TIN PHIÊN TẬP ─────────────────────────────────
echo  ── Thong tin phien tap ──────────────────────────────────
echo.
set /p INPUT_NAME="  Ten benh nhan (VD: Nguyen Van A): "
set /p INPUT_SESSION="  So phien tap   (VD: 1):           "

:: Chuẩn hóa tên: thay dấu cách bằng _ để dùng trong tên file
if "%INPUT_NAME%"==""    set INPUT_NAME=Benh_Nhan
if "%INPUT_SESSION%"=="" set INPUT_SESSION=1

:: Tên hiển thị (giữ nguyên dấu cách)
set BME_PATIENT_DISPLAY=%INPUT_NAME%

:: Tên dùng cho file: thay khoảng trắng → _
set BME_PATIENT=%INPUT_NAME: =_%
set BME_SESSION=%INPUT_SESSION%

:: Timestamp: YYYYMMDD_HHMM
for /f "tokens=1-3 delims=/ " %%a in ("%DATE%") do (
    set _DD=%%a
    set _MM=%%b
    set _YY=%%c
)
for /f "tokens=1-2 delims=:. " %%a in ("%TIME: =0%") do (
    set _HH=%%a
    set _MIN=%%b
)
set TIMESTAMP=%_YY%%_MM%%_DD%_%_HH%%_MIN%

:: Tên file Excel: TenBenhNhan_PhienSo_YYYYMMDD_HHMM.xlsx
set EXCEL_NAME=%BME_PATIENT%_Phien%BME_SESSION%_%TIMESTAMP%.xlsx
set CSV_NAME=%BME_PATIENT%_Phien%BME_SESSION%_%TIMESTAMP%.csv

:: Truyền tên file sang controller qua biến môi trường
set BME_EXCEL_OUT=Patient_Records\Excel_Reports\%EXCEL_NAME%
set BME_CSV_OUT=Patient_Records\Raw_CSV\%CSV_NAME%

echo.
echo  ┌──────────────────────────────────────────────────┐
echo  │  Benh nhan : %BME_PATIENT_DISPLAY%
echo  │  Phien so  : %BME_SESSION%
echo  │  Thoi gian : %DATE% %TIME%
echo  │  File xuat : %EXCEL_NAME%
echo  └──────────────────────────────────────────────────┘
echo.

:: ── TẠO THƯ MỤC ──────────────────────────────────────────────
if not exist "Patient_Records\Raw_CSV"      mkdir "Patient_Records\Raw_CSV"
if not exist "Patient_Records\Excel_Reports" mkdir "Patient_Records\Excel_Reports"

:: ── BƯỚC 1: Khởi động BME Controller (ẩn cửa sổ) ────────────
echo  [1/4] Khoi dong BME Controller...
start "" /MIN ".\.venv\Scripts\python.exe" bme_controller.py

echo       Dang ket noi Arduino (5 giay)...
timeout /t 5 /nobreak >nul

:: ── BƯỚC 2: Khởi động Streamlit Dashboard (ẩn cửa sổ) ────────
echo  [2/4] Khoi dong Dashboard (http://localhost:8501)...

where streamlit >nul 2>&1
if %errorlevel%==0 (
    start "" /MIN ".\.venv\Scripts\streamlit.exe" run bme_dashboard.py --server.headless true --server.port 8501
    timeout /t 4 /nobreak >nul
    start "" "http://localhost:8501"
    echo       Dashboard: http://localhost:8501
) else (
    echo  [!] Streamlit chua cai. Bo qua dashboard.
    echo      Cai bang: pip install streamlit plotly pandas openpyxl
)

:: ── BƯỚC 3: Khởi động Luanti (chờ đến khi đóng) ─────────────
echo  [3/4] Khoi dong Phong tap ao (Luanti)...
echo       (Cua so game se mo. Dong game de ket thuc phien tap.)
echo.

if exist "bin\Release\luanti.exe" (
    start /WAIT "" "bin\Release\luanti.exe"
) else (
    start /WAIT "" "bin\Release\minetest.exe"
)

:: ── BƯỚC 4: Kết thúc — tạo file Excel ───────────────────────
echo.
echo  [4/4] Game da dong. Dang xu ly du lieu...
timeout /t 2 /nobreak >nul

:: Dừng BME Controller → kích hoạt lưu dữ liệu
taskkill /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq BME Controller*" /F >nul 2>&1

echo       Dang xuat file Excel: %EXCEL_NAME%
echo       (Vui long cho 20 giay...)
timeout /t 20 /nobreak >nul

:: Gọi script Python xuất Excel nếu có
if exist "bme_export_excel.py" (
    ".\.venv\Scripts\python.exe" bme_export_excel.py ^
        --patient "%BME_PATIENT%" ^
        --session "%BME_SESSION%" ^
        --timestamp "%TIMESTAMP%" ^
        --csv-in "Patient_Records\Raw_CSV\%CSV_NAME%" ^
        --excel-out "%BME_EXCEL_OUT%"
)

:: ── KẾT QUẢ ──────────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║            PHIEN TAP HOAN TAT                   ║
echo  ╚══════════════════════════════════════════════════╝
echo.
echo  Du lieu thu  : Patient_Records\Raw_CSV\
echo  Bao cao Excel: Patient_Records\Excel_Reports\
echo  Dashboard    : http://localhost:8501  (van dang chay)
echo.

:: Tự động mở thư mục Excel nếu có file
if exist "Patient_Records\Excel_Reports\%EXCEL_NAME%" (
    echo  [OK] File Excel da xuat thanh cong:
    echo       %EXCEL_NAME%
    explorer "Patient_Records\Excel_Reports"
) else (
    if exist "Patient_Records\Excel_Reports" (
        explorer "Patient_Records\Excel_Reports"
    )
)

echo.
echo  Dashboard bac si van mo tai http://localhost:8501
echo  Dong cua so "BME Dashboard" de tat hoan toan.
echo.
echo  Nhan phim bat ky de dong...
pause >nul
exit /b 0