# Panduan Menjalankan Pipeline Berita di Windows (Localhost)

Nanti akan ada **dua server yang jalan bersamaan**:

| | Isi | Alamat | Jendela CMD |
|---|---|---|---|
| Frontend | `index.html` — tampilan situs | http://localhost:8080 | jendela 1 |
| Backend | API berita hasil tarikan | http://127.0.0.1:8000 | jendela 2 |

Frontend memanggil backend. Kalau backend mati, situs tetap tampil dengan data contoh —
tidak pernah jadi halaman kosong.

---

## Langkah 1 — Taruh foldernya

Ekstrak `dcm-ingest` sejajar dengan folder situsmu:

```
D:\
├── dailycryptomedia\        ← index.html + dcm-live.js (sudah ada)
└── dcm-ingest\              ← folder ini
```

## Langkah 2 — Buat virtual environment

Buka Command Prompt **baru** (jendela 2):

```cmd
d:
cd dcm-ingest
python -m venv .venv
.venv\Scripts\activate
```

Setelah aktif, prompt berubah jadi `(.venv) D:\dcm-ingest>`. Ini wajib terlihat
sebelum lanjut. Kalau muncul error izin, jalankan CMD sebagai Administrator.

## Langkah 3 — Instal paket

```cmd
pip install -r requirements.txt
```

Butuh 1–3 menit. Kalau `pip` tidak dikenali, pakai `python -m pip install -r requirements.txt`.

## Langkah 4 — Buat file .env

```cmd
copy .env.example .env
notepad .env
```

Yang **wajib** diubah hanya satu baris — kunci API dari https://console.anthropic.com
(menu *API Keys* → *Create Key*, salin, tempel):

```
DCM_ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx
```

Simpan (`Ctrl+S`), tutup Notepad. Jangan pernah membagikan file `.env` ini ke siapa pun.

> Belum punya kunci API? Tidak apa-apa. Empat sumber Indonesia (Coinvestasi,
> Blockchainmedia, BeInCrypto ID, CoinDesk ID) tidak lewat terjemahan sama sekali,
> jadi pipeline tetap menghasilkan berita. Hanya tiga sumber Inggris yang judulnya
> akan dilewati.

## Langkah 5 — Cek feed sumbernya hidup

```cmd
python -m dcm.cli verify
```

Perintah ini tidak mengubah apa pun, hanya mengetes tujuh alamat feed. Tanda `✓`
berarti hidup, `✗` berarti sumber itu ganti alamat — pipeline tetap jalan dengan
sumber yang tersisa. Wajar kalau satu-dua gagal.

## Langkah 6 — Siapkan database

```cmd
python -m dcm.cli init
```

Muncul `Basis data siap.` dan file `dcm.db` lahir di folder itu. Cukup sekali seumur hidup.

## Langkah 7 — Tarik berita pertama kali

```cmd
python -m dcm.cli run
```

Satu putaran penuh: ambil feed → buang berita kembar → terjemahkan judul → beri skor.
Perlu 1–3 menit karena jeda 3 detik per domain (sopan-santun ke penerbit, jangan dikurangi).

Cek hasilnya:

```cmd
python -m dcm.cli status
```

## Langkah 8 — Nyalakan API

```cmd
python -m dcm.cli serve
```

Muncul `Uvicorn running on http://127.0.0.1:8000`. **Biarkan jendela ini terbuka.**

Tes di browser: buka http://127.0.0.1:8000/api/articles — harus muncul teks JSON berisi berita.

## Langkah 9 — Nyalakan frontend

Buka Command Prompt **kedua** (jendela 1), yang tadi sudah kamu pakai:

```cmd
d:
cd dailycryptomedia
python -m http.server 8080
```

Buka http://localhost:8080 — sekarang berita di halaman itu datang dari tujuh media,
sudah berbahasa Indonesia, lengkap dengan nama penerbit dan tautan ke artikel aslinya.

## Langkah 10 — Biarkan menarik berita terus

Buka Command Prompt **ketiga**, aktifkan venv lagi, lalu:

```cmd
d:
cd dcm-ingest
.venv\Scripts\activate
python -m dcm.cli watch --interval 10
```

Menarik berita baru tiap 10 menit. Halaman depan menyegarkan dirinya tiap 5 menit.

---

## Menjalankan lagi besok

Kunci pemasangan sudah selesai; tiap hari cukup tiga jendela ini:

```cmd
:: jendela 1 — situs
d: & cd dailycryptomedia & python -m http.server 8080

:: jendela 2 — API
d: & cd dcm-ingest & .venv\Scripts\activate & python -m dcm.cli serve

:: jendela 3 — penarik berita
d: & cd dcm-ingest & .venv\Scripts\activate & python -m dcm.cli watch --interval 10
```

Hentikan semuanya dengan `Ctrl + C` di tiap jendela.

---

## Kalau ada yang salah

**Halaman masih menampilkan berita contoh lama.**
Tekan `F12` di browser → tab *Console*. Kalau tertulis `CORS`, berarti port frontend-mu
bukan 8080. Buka `.env`, tambahkan alamatmu ke `DCM_CORS_ORIGINS`, lalu jalankan ulang `serve`.
Kalau tertulis `Failed to fetch`, berarti jendela `serve` belum jalan.

**`python` tidak dikenali.**
Python belum masuk PATH. Instal ulang dari python.org dan centang *Add Python to PATH*.

**`.venv\Scripts\activate` ditolak.**
Itu terjadi di PowerShell, bukan CMD. Pakai Command Prompt biasa, atau di PowerShell
jalankan `Set-ExecutionPolicy -Scope Process RemoteSigned` lebih dulu.

**`verify` gagal semua.**
Cek koneksi internet, atau antivirus/firewall memblokir Python. Coba `python -m dcm.cli verify -v`
untuk melihat pesan aslinya.

**Berita yang masuk sedikit sekali.**
Ambang skor terlalu tinggi. Di `.env`, turunkan `DCM_MIN_PUBLISH_SCORE` dari 20 ke 10,
lalu `python -m dcm.cli run` lagi.

**Ingin mengulang dari nol.**
Hapus `dcm.db`, jalankan `init` lalu `run` lagi.

---

## Sebelum tayang ke publik

Baca bagian pertama `README.md` sampai habis. Ringkasnya: pipeline ini sengaja
**tidak menyalin isi artikel** — hanya judul (diterjemahkan), ringkasan yang ditulis
ulang orisinal, nama penerbit, dan tautan balik. Itu batas yang menjaga situsmu tetap
aman secara hak cipta.

Yang masih harus kamu urus sendiri: setiap sumber ditandai `needs_permission: true`
di `config/sources.yaml`. Hubungi redaksi masing-masing untuk perjanjian sindikasi.
Selama belum ada izin, kamu bisa menyetel `publish: false` untuk sumber tersebut —
beritanya tetap masuk database untuk pemantauan internal, hanya tidak keluar ke publik.

Untuk sumber Indonesia, berlaku pula Pedoman Media Siber Dewan Pers soal pengutipan
karya jurnalistik media lain.
