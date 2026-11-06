@echo off
setlocal
cd /d "%~dp0"
title GENORA
if not exist ".venv\Scripts\python.exe" (
    echo Lingkungan Python belum tersedia. Ikuti petunjuk instalasi di README.md.
    pause
    exit /b 1
)
echo Membuka GENORA...
echo Biarkan jendela ini terbuka selama aplikasi digunakan.
echo Alamat aplikasi: http://127.0.0.1:8501
echo Untuk menghentikan aplikasi, tekan Ctrl+C.
".venv\Scripts\python.exe" -m streamlit run "app.py" --server.address 127.0.0.1 --server.port 8501 --server.headless false --browser.gatherUsageStats false
if errorlevel 1 (
    echo.
    echo Aplikasi gagal dimulai. Jika port 8501 sudah digunakan,
    echo coba buka http://127.0.0.1:8501 pada browser.
    echo Jika ada pesan dependensi hilang, ikuti instalasi di README.md.
    pause
)
endlocal
