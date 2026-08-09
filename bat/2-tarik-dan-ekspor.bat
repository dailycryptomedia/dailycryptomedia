@echo off
title TARIK BERITA + EKSPOR JSON
rem Menjalankan pipeline sekali lalu menulis ulang docs\data\api\*.json
rem Ini yang dikerjakan GitHub Actions setiap 30 menit; jalankan di sini
rem bila ingin melihat hasilnya lebih dulu sebelum push.
cd /d "%~dp0..\dcm-ingest"
call .venv\Scripts\activate
python -m dcm.cli run
python -m dcm.cli export
echo.
echo   Selesai. Jalankan 1-situs.bat untuk melihat hasilnya.
pause
