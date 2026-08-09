# Daily Crypto Media — Pipeline Agregasi Berita

Menarik berita dari tujuh media kripto, menerjemahkan yang berbahasa Inggris,
lalu menyajikannya ke frontend Daily Crypto Media dalam bahasa Indonesia.

---

## Baca ini lebih dulu

Pipeline ini **tidak menyalin isi artikel**, dan itu keputusan rancangan yang
disengaja, bukan fitur yang belum sempat dibuat.

Menarik badan artikel milik penerbit lain, menerjemahkannya, lalu
menerbitkannya di situs sendiri adalah dua pelanggaran sekaligus: penggandaan
dan pembuatan karya turunan. Keduanya hak eksklusif pemegang hak cipta.
Terjemahan tidak membuat karya itu menjadi milik penerjemah, justru
sebaliknya, terjemahan adalah salah satu bentuk karya turunan yang paling
jelas diatur. Ketujuh penerbit dalam daftar ini juga mencantumkan larangan
serupa di ketentuan penggunaan masing-masing.

Yang dilakukan pipeline ini:

| | Diambil | Disimpan | Ditampilkan |
|---|---|---|---|
| Judul | ya | ya | ya, diterjemahkan |
| Kutipan feed | ya | ya, maksimal 400 karakter | tidak langsung |
| Ringkasan | — | ditulis ulang orisinal | ya |
| **Isi artikel** | **tidak** | **tidak** | **tidak** |
| Tautan kanonis | ya | ya | ya, wajib |
| Nama penerbit | ya | ya | ya, wajib |

Tabel `articles` **tidak punya kolom untuk isi artikel**. Batasan itu
ditegakkan di skema, bukan sekadar disepakati di dokumen. Kalau suatu saat ada
yang hendak menambahkan kolom `body`, hentikan dan selesaikan dulu perjanjian
sindikasinya.

Ringkasan **ditulis ulang, bukan diterjemahkan**. Model membaca kutipan feed
lalu menyusun dua kalimat orisinal berbahasa Indonesia. Hasilnya karya baru,
bukan versi berbahasa lain dari tulisan penerbit. Judul tetap diterjemahkan
karena judul terlalu pendek untuk ditulis ulang tanpa berubah makna, dan
mengutip judul beserta tautan balik adalah praktik lazim di seluruh dunia
agregasi berita.

**Yang tetap perlu Anda lakukan sendiri.** Model di atas jauh lebih aman
daripada menyalin isi artikel, tetapi tetap bukan izin. Setiap sumber ditandai
`needs_permission: true` di `config/sources.yaml`. Hubungi redaksi masing-masing
untuk perjanjian sindikasi, dan sampai perjanjian itu ada, pertimbangkan
menyetel `publish: false` untuk sumber yang bersangkutan. Item tetap masuk basis
data untuk pemantauan redaksi internal, hanya tidak keluar lewat API publik.

Untuk sumber Indonesia, berlaku juga Pedoman Media Siber Dewan Pers soal
pengutipan karya jurnalistik media lain.

---

## Mulai cepat

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # isi DCM_ANTHROPIC_API_KEY

python -m dcm.cli verify      # cek endpoint feed, tidak menyentuh basis data
python -m dcm.cli init        # buat tabel, muat sumber dari YAML
python -m dcm.cli run         # satu putaran penuh
python -m dcm.cli serve       # API di http://127.0.0.1:8000
```

Jalankan `verify` lebih dulu. Perintah itu memberi tahu endpoint mana yang
hidup tanpa mengubah apa pun, dan itulah cara tercepat mengetahui sumber mana
yang berganti alamat feed.

Menjalankan terus-menerus:

```bash
python -m dcm.cli watch --interval 10
```

---

## Tujuh sumber

Empat dari tujuh sudah berbahasa Indonesia. Keempatnya **tidak melewati
terjemahan sama sekali**, yang memangkas biaya API sekitar 55 persen. Ini poin
yang mudah terlewat kalau semua sumber diperlakukan sama.

| Sumber | Bahasa | Terjemahan |
|---|---|---|
| CoinDesk Indonesia | id | tidak¹ |
| BeInCrypto Indonesia | id | tidak |
| Blockchainmedia.id | id | tidak |
| Coinvestasi | id | tidak |
| Cointelegraph | en | ya |
| Decrypt | en | ya |
| The Block | en | ya |

¹ Bila edisi Indonesia ternyata tidak menyediakan feed terpisah, discovery
akan jatuh ke feed induk berbahasa Inggris dan item itu masuk antrean
terjemahan. Jalankan `verify` untuk memastikan yang mana yang berlaku.

URL feed **tidak ditulis keras di kode**. Feed berpindah alamat tanpa
pengumuman, dan pipeline yang alamatnya dipaku akan mati diam-diam suatu hari
nanti. Penemuan berjenjang: kandidat dari YAML, lalu tag
`<link rel="alternate">` di homepage, lalu jalur konvensional seperti `/feed`
dan `/rss.xml`.

---

## Alur

```
  verify ─► discovery URL feed
              │
  fetch  ─────┴─► robots.txt ─► batas laju per domain ─► permintaan bersyarat
                                                              │
                                                              ▼
                                       parse ─► potong kutipan (maks 400 char)
                                                              │
                                                              ▼
                             simpan  (unik per source_id + guid, idempoten)
                                                              │
  dedupe ─────────────────────────────────────────────────────┤
     SimHash judul ─► kemiripan token ─► cluster ─► pilih pemimpin
                                                              │
  translate ──────────────────────────────────────────────────┤
     hanya pemimpin cluster, hanya sumber berbahasa Inggris
     judul diterjemahkan · ringkasan ditulis ulang
                                                              │
  publish ────────────────────────────────────────────────────┤
     ambang skor · sumber publish=true · judul ID wajib ada
                                                              ▼
                                                     GET /api/articles
```

Setiap tahap idempoten. Menjalankan pipeline dua kali berturut-turut tidak
menghasilkan artikel ganda dan tidak memicu terjemahan ulang. Itu penting
karena pipeline berita akan gagal di tengah jalan — feed timeout, kuota API
habis, proses mati saat deploy — dan pemulihannya harus sesederhana
menjalankannya lagi.

---

## Deduplikasi

Tujuh sumber memberitakan peristiwa yang sama. Tanpa penanganan, halaman depan
berisi lima versi kabar yang sama.

Dua lapis: SimHash 64 bit atas judul yang sudah dinormalkan untuk menyaring
pasangan yang layak diperiksa, lalu kemiripan token untuk memutuskan. Ini
menangkap "Bitcoin tembus $120.000" dan "Harga Bitcoin lewati $120.000"
sebagai satu berita.

Artikel kembar **tidak dihapus**, hanya ditandai `DUPLICATE` dan dikaitkan ke
satu cluster, sehingga tampilan bisa menambahkan keterangan "juga diberitakan
oleh" bila diinginkan. Pemimpin cluster dipilih berdasarkan skor tertinggi,
dengan keunggulan kecil untuk sumber berbahasa Indonesia karena tidak perlu
melewati terjemahan sehingga siap tayang lebih cepat.

Artikel kembar juga **tidak diterjemahkan**. Tidak ada gunanya membayar
terjemahan untuk berita yang tidak akan tampil.

---

## Pemeringkatan

Urutan berdasarkan waktu saja tidak cukup untuk media Indonesia. Berita "SEC
menunda keputusan ETF" penting, tetapi "OJK menerbitkan aturan kustodi" jauh
lebih penting bagi pembaca di Jakarta.

```
skor = relevansi_indonesia × 0,40
     + kesegaran           × 0,45      (peluruhan eksponensial, paruh 8 jam)
     + kualitas_kutipan    × 0,15
     + 5 bila sumber berbahasa Indonesia
```

Pencocokan istilah memakai **batas kata, bukan substring**. Ini pernah menjadi
sumber galat nyata: `"bi"` (Bank Indonesia) cocok di dalam `"Bitcoin"`,
sehingga setiap berita Bitcoin global terangkat seolah-olah berita Indonesia.
Ada pengujian regresi khusus untuk itu di `tests/test_dcm.py`.

---

## Glosarium terjemahan

Masalah terbesar terjemahan mesin di berita kripto bukan tata bahasa,
melainkan istilah yang diterjemahkan padahal seharusnya dibiarkan. "Staking"
jadi "mempertaruhkan", "bullish" jadi "kelakuan banteng".

`config/glossary.yaml` memuat tiga daftar:

- **keep** — istilah yang sudah jadi kosakata sehari-hari komunitas kripto
  Indonesia: staking, airdrop, halving, bullish, gas fee, rollup.
- **translate** — istilah keuangan umum yang punya padanan mapan di media
  ekonomi Indonesia: *market cap* → kapitalisasi pasar, *yield* → imbal hasil.
- **institutions** — nama lembaga dengan keterangan untuk penyebutan pertama:
  SEC → Komisi Sekuritas dan Bursa Amerika Serikat (SEC).

Redaksi bisa menyunting berkas ini tanpa menyentuh kode. Setiap perubahan
langsung berlaku pada putaran berikutnya.

---

## Menyambungkan ke frontend

`GET /api/articles` mengembalikan bentuk yang **sama persis** dengan larik
`DATA.articles` di `index.html`, jadi tidak ada fungsi render yang perlu
diubah. Muat adapter setelah skrip utama:

```html
<script>window.DCM_API_BASE = "https://api.dailycryptomedia.id";</script>
<script src="/web/dcm-live.js"></script>
```

Adapter menimpa daftar berita, blok Sorotan, dan tab rubrik dengan data
langsung. Bila API tidak terhubung, halaman tetap menampilkan isi statis dan
titik indikator di pita pasar berubah warna. Kegagalan jaringan tidak
menghasilkan halaman kosong.

Kartu agregasi ditulis ulang oleh adapter agar setiap kartu membawa nama
penerbit dan tautan `rel="noopener nofollow"` ke artikel asli. Jangan hapus
bagian itu — atribusi dan tautan balik adalah dasar dari seluruh model ini.

---

## Endpoint

| Endpoint | Kegunaan |
|---|---|
| `GET /api/articles` | Daftar artikel. Parameter: `rubric`, `limit`, `offset`, `hours`, `order` |
| `GET /api/articles/top` | Berita berperingkat untuk blok Sorotan |
| `GET /api/rubrics` | Rubrik dan jumlah artikel, untuk membangun tab |
| `GET /api/sources` | Keadaan tiap sumber, untuk halaman kredit dan pemantauan |
| `GET /api/health` | Kesehatan pipeline. Pantau ini, bukan sekadar proses hidup |

`/api/health` melaporkan `menit_sejak_pengambilan_terakhir`. Bila melewati 60
menit, statusnya berubah jadi `basi`. Pasang peringatan di sana: pipeline yang
mati diam-diam jauh lebih berbahaya daripada pipeline yang gagal berisik.

---

## Biaya

Tiga sumber berbahasa Inggris, sekitar 40 item per hari per sumber, kelompok
delapan item per panggilan. Sekitar **15 panggilan API per hari**, kira-kira
40 ribu token masukan dan 12 ribu token keluaran harian. Volume ini kecil;
tarif terkini ada di https://docs.claude.com/en/docs/about-claude/pricing.

Bawaan memakai `claude-sonnet-5` karena judul adalah hal pertama yang dilihat
pembaca dan kualitasnya terasa. Untuk volume jauh lebih besar,
`claude-haiku-4-5-20251001` jauh lebih murah — bandingkan hasilnya pada 50
judul lebih dulu sebelum memindahkan seluruh volume ke sana.

Deduplikasi memangkas biaya lebih jauh karena artikel kembar tidak pernah
masuk antrean terjemahan.

---

## Menjadi tamu yang baik

Bot yang kasar diblokir, dan blokir itu biasanya permanen di tingkat CDN.

- `robots.txt` dipatuhi, hasilnya di-cache per host.
- Batas laju **per domain**, bawaan 3 detik. Tujuh sumber di-poll berbarengan,
  tetapi tidak ada satu pun penerbit yang menerima lebih dari satu permintaan
  per tiga detik.
- Permintaan bersyarat memakai ETag dan `If-Modified-Since`. Feed jarang
  berubah antar polling; balasan 304 menghemat bandwidth kedua pihak.
- `User-Agent` menyebutkan nama bot, URL keterangan, dan alamat surel yang
  bisa dihubungi. Kalau ada masalah, penerbit bisa menghubungi Anda sebelum
  memblokir.
- Sumber yang gagal sepuluh kali beruntun dinonaktifkan otomatis.

Jangan turunkan `min_interval_seconds` di bawah 2 detik. Feed berita
diperbarui dalam hitungan menit, bukan detik; polling lebih agresif tidak
memberi keuntungan apa pun.

---

## Pengujian

```bash
python -m pytest tests/ -v
```

42 pengujian. Prioritasnya bukan cakupan baris, melainkan tiga hal yang kalau
gagal tidak akan terlihat sampai terlambat: batas panjang kutipan, ketepatan
deduplikasi, dan kanonisasi URL. Ditambah pengujian regresi untuk galat
pencocokan istilah yang dijelaskan di atas.

---

## Struktur

```
dcm-ingest/
├── config/
│   ├── sources.yaml      tujuh sumber, rubrik, bobot relevansi
│   └── glossary.yaml     glosarium dan gaya selingkung terjemahan
├── dcm/
│   ├── settings.py       konfigurasi dari lingkungan dan YAML
│   ├── models.py         skema — tanpa kolom isi artikel, disengaja
│   ├── http_client.py    klien sopan + penemuan feed
│   ├── feeds.py          penguraian RSS/Atom, penegakan batas kutipan
│   ├── dedupe.py         SimHash + kemiripan token
│   ├── classify.py       rubrik dan pemeringkatan
│   ├── translate.py      terjemahan judul, penulisan ulang ringkasan
│   ├── pipeline.py       orkestrasi
│   ├── api.py            FastAPI
│   └── cli.py            antarmuka baris perintah
├── web/dcm-live.js       adapter untuk index.html
└── tests/test_dcm.py
```

---

## Untuk produksi

- Ganti SQLite ke PostgreSQL lewat `DCM_DATABASE_URL`.
- Jalankan `watch` sebagai unit systemd atau container terpisah dari API.
- Pasang peringatan pada `menit_sejak_pengambilan_terakhir` di `/api/health`.
- Simpan URL gambar sebagai rujukan saja. Jangan mengunduh ulang lalu
  menyajikannya dari server sendiri tanpa izin; bila ragu, biarkan kosong dan
  pakai placeholder milik Daily Crypto Media.
- Sediakan halaman kredit yang menyebut ketujuh sumber, mengambil datanya dari
  `/api/sources`.
