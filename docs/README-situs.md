# Daily Crypto Media — Cara Menjalankan di Localhost

Situs ini adalah **satu file HTML mandiri** (`index.html`) yang sudah berisi HTML + CSS + JavaScript.
Tidak perlu build, tidak perlu `npm install`, tidak perlu database.

```
dailycryptomedia/
└── index.html      ← seluruh situs ada di sini
```

---

## Cara 1 — Buka langsung (paling cepat, 5 detik)

Klik dua kali `index.html`, atau klik kanan → *Open with* → browser (Chrome/Edge/Firefox).

Alamatnya akan jadi `file:///.../index.html`. Semua fitur (jam, ticker, konverter, kalkulator pajak,
pencarian, filter berita) tetap berfungsi karena datanya masih data contoh di dalam file.

> Kekurangan: bukan `http://localhost`. Kalau nanti ditambah `fetch()` ke API harga sungguhan,
> browser akan memblokirnya (CORS). Untuk itu pakai Cara 2.

---

## Cara 2 — Python (rekomendasi, tanpa instal apa pun di Mac/Linux)

Cek Python dulu:

```bash
python3 --version      # Windows: python --version
```

Kalau belum ada, unduh di https://www.python.org/downloads/ — saat instal di Windows,
**centang "Add Python to PATH"**.

Lalu:

```bash
cd path/ke/folder/dailycryptomedia
python3 -m http.server 8080        # Windows: python -m http.server 8080
```

Buka browser ke **http://localhost:8080**

Hentikan server dengan `Ctrl + C`.

Kalau port 8080 dipakai aplikasi lain, ganti saja: `python3 -m http.server 5500` → http://localhost:5500

---

## Cara 3 — VS Code + Live Server (otomatis refresh saat file disimpan)

1. Instal [VS Code](https://code.visualstudio.com/)
2. Buka folder ini: *File → Open Folder → dailycryptomedia*
3. Tab **Extensions** (`Ctrl+Shift+X`) → cari **Live Server** (Ritwick Dey) → *Install*
4. Klik kanan `index.html` → **Open with Live Server**
5. Browser terbuka otomatis di `http://127.0.0.1:5500`

Setiap kali kamu simpan (`Ctrl+S`), halaman langsung ter-refresh. Ini paling nyaman untuk mengedit.

---

## Cara 4 — Node.js

```bash
npx serve .          # → http://localhost:3000
# atau
npx http-server -p 8080
```

---

## Menemukan bagian yang mau diedit

Semua bagian sudah diberi penanda komentar besar di dalam `index.html`. Tekan `Ctrl+F` lalu cari:

| Cari teks ini | Isinya |
|---|---|
| `1. TOKEN` | Warna, font, radius, lebar maksimum — **ubah tampilan mulai dari sini** |
| `PITA DATA HIDUP` | Pita navy paling atas (jam, ticker harga) |
| `HERO` | Berita utama + 5 berita berperingkat |
| `PASAR` | Tabel harga + pengukur sentimen |
| `BERITA TERBARU` | Grid berita yang bisa disaring per rubrik |
| `ALAT` | Konverter mata uang & kalkulator pajak |
| `3. DATA` (di dalam `<script>`) | **Semua isi berita, koin, dan angka ada di objek `DATA`** |
| `10. JALANKAN` | Daftar fungsi yang dipanggil saat halaman dibuka |

Contoh mengubah warna biru utama — cari `--signal:` di bagian `:root{`:

```css
--signal: #1466D8;   /* ganti ke warna lain, seluruh situs ikut berubah */
```

Contoh menambah berita — cari `news:` di dalam objek `DATA`, salin satu blok `{...}`,
lalu ubah isinya. Halaman akan otomatis menampilkannya tanpa mengubah HTML.

---

## Catatan penting

- **Seluruh harga, artikel, dan angka di halaman ini adalah data contoh** untuk demonstrasi
  rancangan antarmuka — bukan data pasar sungguhan.
- Font diambil dari Google Fonts, jadi butuh koneksi internet agar tampilannya persis.
  Tanpa internet, situs tetap jalan tapi memakai font cadangan sistem.
- Untuk memakai harga sungguhan nanti, ganti isi `DATA.coins` dengan hasil `fetch()` ke
  API bursa (mis. Indodax/CoinGecko), dan pastikan situs dijalankan lewat `http://localhost`, bukan `file://`.
