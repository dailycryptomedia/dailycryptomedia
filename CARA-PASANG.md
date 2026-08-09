# Cara memasang Daily Crypto Media di GitHub Pages

Panduan ini dipakai sekali saja. Setelah selesai, situs memperbarui dirinya
sendiri setiap 30 menit tanpa komputermu perlu menyala.

---

## Yang berubah dibanding versi localhost

| Sebelum (localhost) | Sesudah (GitHub) |
|---|---|
| 3 jendela CMD menyala terus | GitHub Actions, otomatis tiap 30 menit |
| FastAPI menjawab `/api/articles` | Berkas `docs/data/api/*.json` yang sudah jadi |
| `python -m http.server 8080` | GitHub Pages |
| Kunci API di `.env` | GitHub Secrets |

Isi JSON-nya identik dengan balasan FastAPI, jadi tidak ada satu pun fungsi
render di `index.html` yang berubah.

---

## Langkah 1 — Siapkan Git di Windows

Install Git dari <https://git-scm.com> dan GitHub CLI dari
<https://cli.github.com>. Lalu buka CMD:

```cmd
git config --global user.name "Daily Crypto Media"
git config --global user.email "deficryptoindonesia@gmail.com"
gh auth login
```

Pada `gh auth login` pilih: GitHub.com → HTTPS → Login with a web browser.

## Langkah 2 — Taruh folder ini di D:\

Letakkan isi paket ini di `D:\dailycryptomedia\` sehingga strukturnya:

```
D:\dailycryptomedia\
    .github\workflows\update-news.yml
    .gitignore
    CARA-PASANG.md
    bat\
    docs\              <- ini yang jadi situs
    dcm-ingest\        <- ini yang menarik berita
```

Salin `.venv` lamamu ke dalam `dcm-ingest\`, atau buat ulang:

```cmd
cd /d D:\dailycryptomedia\dcm-ingest
python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
```

Salin juga `.env` lamamu ke `dcm-ingest\.env`. Berkas ini **tidak** akan
ikut terunggah — sudah dikunci oleh `.gitignore`.

## Langkah 3 — Uji dulu di lokal

```cmd
D:\dailycryptomedia\bat\2-tarik-dan-ekspor.bat
D:\dailycryptomedia\bat\1-situs.bat
```

Buka <http://localhost:8080>. Situs harus tampil normal **tanpa** API server
menyala sama sekali. Kalau berhasil, artinya mode statis sudah benar.

## Langkah 4 — Unggah ke GitHub

```cmd
cd /d D:\dailycryptomedia
git init -b main
git add .
git status
```

Periksa keluaran `git status`: pastikan **`.env` tidak muncul** dan
**`.venv/` tidak muncul**. Bila aman, lanjutkan:

```cmd
git commit -m "commit pertama"
gh repo create dailycryptomedia --public --source=. --push
```

## Langkah 5 — Nyalakan GitHub Pages

Buka repo di browser → **Settings** → **Pages**:

- Source: **Deploy from a branch**
- Branch: **main**, folder: **/docs**
- Save

Tunggu satu menit, lalu buka
`https://<nama-akunmu>.github.io/dailycryptomedia`. Pastikan tampilannya
benar sebelum lanjut ke domain.

## Langkah 6 — Pasang domain sendiri

Di panel DNS domainmu, buat lima catatan:

| Tipe | Host | Nilai |
|---|---|---|
| A | @ | 185.199.108.153 |
| A | @ | 185.199.109.153 |
| A | @ | 185.199.110.153 |
| A | @ | 185.199.111.153 |
| CNAME | www | `<nama-akunmu>.github.io` |

Kembali ke **Settings → Pages**, isi **Custom domain** dengan domainmu,
tunggu verifikasi selesai, lalu centang **Enforce HTTPS**.

> Empat alamat A itu milik GitHub dan jarang berubah. Bila salah satu
> ditolak, cek daftar terbaru di dokumentasi GitHub Pages.

## Langkah 7 — Simpan kunci API

**Settings → Secrets and variables → Actions → New repository secret**

- Name: `ANTHROPIC_API_KEY`
- Secret: kunci Anthropic-mu

Selama secret ini kosong, pipeline tetap berjalan dan situs tetap terbit —
hanya tahap terjemahan yang dilewati, jadi artikel berbahasa Inggris belum
muncul dalam bahasa Indonesia.

## Langkah 8 — Uji alur otomatisnya

Buka tab **Actions** → **Perbarui berita** → tombol **Run workflow**.
Setelah hijau, periksa bahwa ada commit baru bernama `berita: perbarui ...`
dan situs di domainmu ikut berubah.

---

## Perawatan harian

Tidak ada. Situs berjalan sendiri.

Yang perlu kamu lakukan hanya saat ingin mengubah tampilan atau konfigurasi:
edit berkas di `docs\` atau `dcm-ingest\config\`, lalu jalankan
`bat\3-kirim-ke-github.bat`.

## Kalau situs berhenti diperbarui

1. Buka tab **Actions**, cari putaran yang merah, baca lognya.
2. Penyebab paling lazim: satu feed RSS mati. Jalankan
   `python -m dcm.cli verify` di lokal untuk melihat sumber mana.
3. GitHub menonaktifkan `schedule` di repo yang tidak tersentuh selama 60
   hari. Cukup buka Actions dan tekan **Enable workflow** untuk menyalakannya
   lagi.

## Dua hal yang masih menunggu sebelum promosi terbuka

- **Izin sindikasi.** Semua sumber di `config\sources.yaml` masih bertanda
  `needs_permission: true`. Situs ini hanya menampilkan judul, kutipan feed,
  dan tautan balik — posisi yang jauh lebih aman daripada menyalin isi — tapi
  izin tertulis tetap perlu diselesaikan sebelum situs dipromosikan luas.
- **Feed Coinvestasi.** URL-nya masih gagal resolve. Jalankan
  `python -m dcm.cli verify` untuk melihat statusnya.
