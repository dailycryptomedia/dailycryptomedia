@echo off
title KIRIM PERUBAHAN KE GITHUB
rem Mengunggah perubahan ke GitHub. Situs di domain ikut terbarui otomatis
rem sekitar satu menit setelah push berhasil.
cd /d "%~dp0.."
git add -A
git status --short
echo.
set /p PESAN="Tulis catatan perubahan (Enter untuk lewati): "
if "%PESAN%"=="" set PESAN=perbarui situs
git commit -m "%PESAN%"
git pull --rebase --autostash
git push
echo.
pause
