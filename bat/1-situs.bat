@echo off
title SITUS 8080 - PRATINJAU LOKAL
rem Menyajikan folder docs, yaitu folder yang sama persis dengan yang
rem disajikan GitHub Pages. Apa yang tampil di sini akan tampil di domain.
cd /d "%~dp0..\docs"
echo.
echo   Buka di browser: http://localhost:8080
echo   Hentikan dengan Ctrl+C
echo.
python -m http.server 8080
