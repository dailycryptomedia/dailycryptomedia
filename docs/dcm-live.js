/* =========================================================================
   DAILY CRYPTO MEDIA — ADAPTER DATA LANGSUNG
   -------------------------------------------------------------------------
   Menghubungkan index.html ke API agregasi.

   Cara pasang: muat berkas ini SETELAH skrip utama di index.html.

     <script src="/web/dcm-live.js"></script>

   Skrip ini menimpa DATA.articles, DATA.ranked, dan tab rubrik dengan data
   dari server, lalu memanggil ulang fungsi render yang sudah ada. Tidak ada
   fungsi render yang perlu diubah.

   Bila API tidak bisa dihubungi, halaman tetap menampilkan isi statis yang
   sudah ada. Kegagalan jaringan tidak boleh menghasilkan halaman kosong.

   ATRIBUSI — kartu berita ditulis ulang di sini agar setiap kartu membawa
   nama penerbit dan tautan ke artikel asli. Jangan menghapus bagian itu.
   ========================================================================= */

(function () {
  "use strict";

  /* ---------------------------------------------------------------------
     Dua mode, satu berkas
     ---------------------------------------------------------------------
     MODE STATIS (bawaan, dipakai di GitHub Pages)
       Membaca berkas JSON yang sudah ditulis lebih dulu oleh
       `python -m dcm.cli export`. Tidak ada server yang perlu hidup.

     MODE API (pengembangan lokal)
       Setel window.DCM_API_BASE sebelum skrip ini dimuat, misalnya
       "http://127.0.0.1:8000", lalu semua permintaan kembali ke FastAPI.

     Bentuk JSON kedua mode itu identik, jadi seluruh fungsi render di bawah
     tidak peduli mode mana yang aktif.
     --------------------------------------------------------------------- */

  const API = window.DCM_API_BASE || null;
  /* Dinamai DATA_BASE, bukan DATA. Template menyimpan seluruh isi halamannya
     di variabel global bernama DATA; memakai nama yang sama di sini akan
     menutupinya, dan penggantian data pasar akan menulis ke tempat yang
     salah tanpa memunculkan error apa pun. */
  const DATA_BASE = window.DCM_DATA_BASE || "data/api";
  const REFRESH_MS = 5 * 60 * 1000;

  /* Pembatal cache berbutir menit. CDN GitHub Pages menyimpan berkas cukup
     lama; tanpa ini, pembaca yang membuka tab lama bisa melihat berita
     kemarin. Butiran menit, bukan milidetik, supaya cache tetap berguna. */
  function stamp() {
    return "?v=" + Math.floor(Date.now() / 60000);
  }

  function endpoint(kind, rubric) {
    const live = Boolean(API);
    switch (kind) {
      case "health":
        return live ? API + "/api/health" : DATA_BASE + "/health.json" + stamp();
      case "rubrics":
        return live ? API + "/api/rubrics" : DATA_BASE + "/rubrics.json" + stamp();
      case "top":
        return live ? API + "/api/articles/top?limit=5"
                    : DATA_BASE + "/articles/top.json" + stamp();
      case "market":
        return live ? API + "/api/market" : DATA_BASE + "/market.json" + stamp();
      case "articles":
        if (!rubric || rubric === "semua") {
          return live ? API + "/api/articles" : DATA_BASE + "/articles.json" + stamp();
        }
        return live
          ? API + "/api/articles?rubric=" + encodeURIComponent(rubric)
          : DATA_BASE + "/articles/" + encodeURIComponent(rubric) + ".json" + stamp();
      default:
        throw new Error("endpoint tidak dikenal: " + kind);
    }
  }

  /* ---------------------------------------------------------------------
     Pengambilan
     --------------------------------------------------------------------- */

  async function getJSON(kind, rubric) {
    const url = endpoint(kind, rubric);
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`${kind} membalas ${response.status}`);
    return response.json();
  }

  /* ---------------------------------------------------------------------
     Kartu dengan atribusi
     Kartu berita agregasi berbeda dari kartu redaksi sendiri: judulnya
     menuju situs penerbit, dan nama penerbit ditampilkan menonjol.
     --------------------------------------------------------------------- */

  function attributedCard(a) {
    const badge = a.translated
      ? '<span class="dot"></span><span class="stamp">diterjemahkan</span>'
      : "";

    return `
      <article class="card">
        <div class="lead__meta" style="margin:0">
          <span class="eyebrow">${escapeHTML(a.cat)}</span>
          <span class="dot"></span><span class="stamp">${escapeHTML(a.a)}</span>
        </div>
        <h3 class="card__t">
          <a href="${escapeAttr(a.url)}" target="_blank" rel="noopener nofollow">
            ${escapeHTML(a.t)}
          </a>
        </h3>
        <p class="card__x">${escapeHTML(a.x || "")}</p>
        <div class="card__f">
          <span class="stamp" style="color:var(--signal);font-weight:700">
            ${escapeHTML(a.w)}
          </span>${badge}
        </div>
      </article>`;
  }

  function escapeHTML(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }
  const escapeAttr = escapeHTML;

  /* ---------------------------------------------------------------------
     Pemasangan ulang render
     --------------------------------------------------------------------- */

  /* ---------------------------------------------------------------------
     Laporan utama

     Blok ini semula berisi artikel contoh bawaan, lengkap dengan baris
     "Oleh Tim Redaksi Daily Crypto Media". Untuk berita agregasi, baris itu
     keliru: penulisnya bukan redaksi kita. Versi ini menggantinya dengan
     artikel teratas yang sesungguhnya, dan menyebut penerbit aslinya.
     --------------------------------------------------------------------- */

  /* ---------------------------------------------------------------------
     Blok sekunder

     Template menyediakan empat blok yang semula diisi data karangan:
     Fokus Regulasi, Kolom Opini, Agenda, dan Akademi. Dua di antaranya punya
     padanan nyata di basis data dan disambungkan di sini. Dua sisanya —
     Agenda dan Akademi — tidak punya sumber data sama sekali, jadi
     disembunyikan lewat CSS alih-alih diisi karangan.
     --------------------------------------------------------------------- */

  function renderReg(articles) {
    const host = document.getElementById("reggrid");
    if (!host) return;

    if (!articles || !articles.length) {
      // Rubrik regulasi bisa kosong pada hari yang sepi. Sembunyikan seluruh
      // bagiannya daripada menampilkan kisi melompong.
      const section = document.getElementById("regulasi");
      if (section) section.style.display = "none";
      return;
    }

    host.innerHTML = articles.slice(0, 4).map(a => `
      <a class="regcard" href="${escapeAttr(a.url)}" target="_blank" rel="noopener nofollow">
        <span class="eyebrow" style="color:var(--amber)">${escapeHTML(a.w)}</span>
        <h3 class="regcard__t">${escapeHTML(a.t)}</h3>
        <p class="regcard__x">${escapeHTML(a.x || "")}</p>
        <div class="regcard__f">
          <span class="stamp" style="color:var(--on-ink-2)">${escapeHTML(a.a)}</span>
        </div>
      </a>`).join("");
  }

  function renderSlim(id, articles) {
    const host = document.getElementById(id);
    if (!host) return;

    if (!articles || !articles.length) {
      const box = host.closest(".aside-box");
      if (box) box.style.display = "none";
      return;
    }

    host.innerHTML = articles.slice(0, 5).map(a => `
      <div class="slim__row">
        <div>
          <h4 class="slim__t">
            <a href="${escapeAttr(a.url)}" target="_blank" rel="noopener nofollow">
              ${escapeHTML(a.t)}
            </a>
          </h4>
          <span class="stamp">${escapeHTML(a.w)} · ${escapeHTML(a.a)}</span>
        </div>
      </div>`).join("");
  }

  /* ---------------------------------------------------------------------
     Pasar

     Strategi di sini sengaja berbeda dari blok berita. Template sudah punya
     renderMarket() dan renderTicker() lengkap dengan pengurutan kolom,
     format rupiah, dan grafik kecil. Menulis ulang semua itu berarti
     menduplikasi logika yang sudah bekerja.

     Jadi yang kita lakukan hanya mengganti isi DATA.coins dengan angka
     sungguhan, lalu memanggil ulang fungsi bawaannya. Seluruh perilaku
     tabel — termasuk klik untuk mengurutkan — tetap utuh.
     --------------------------------------------------------------------- */

  function terapkanPasar(m) {
    if (!m || !Array.isArray(m.coins) || !m.coins.length) return;

    if (typeof DATA === "object" && DATA) {
      DATA.coins = m.coins;
      if (typeof renderMarket === "function") renderMarket();
      if (typeof renderTicker === "function") renderTicker();
    }

    // Label bagian Pasar masih berbunyi "data contoh". Sekarang tidak lagi.
    const label = document.querySelector("#pasar .eyebrow");
    if (label) label.textContent = `Harga dalam rupiah · sumber ${m.sumber || "CoinGecko"}`;

    terapkanIndeks(m.fng);
    terapkanStatistik(m);
  }

  function terapkanIndeks(f) {
    if (!f || f.kini == null) return;

    const nilai = document.querySelector(".gauge__v");
    const label = document.querySelector(".gauge__l");
    const kaki = document.querySelector(".gauge-card__foot");

    if (nilai) nilai.textContent = f.kini;
    if (label) label.textContent = f.label || "";

    // Busur berwarna dipotong sesuai angka indeks. Panjang penuh busur
    // setengah lingkaran berjari-jari 80 adalah pi x 80 = 251.
    const busur = document.getElementById("gaugeArc");
    if (busur) {
      const penuh = 251;
      busur.setAttribute("stroke-dasharray",
        `${(f.kini / 100) * penuh} ${penuh}`);
    }

    if (kaki) {
      const bagian = [];
      if (f.kemarin != null) bagian.push(`Kemarin ${f.kemarin}`);
      if (f.pekan_lalu != null) bagian.push(`Pekan lalu ${f.pekan_lalu}`);
      kaki.innerHTML = bagian.map(t => `<span>${escapeHTML(t)}</span>`).join("");
    }
  }

  function terapkanStatistik(m) {
    const kotak = document.querySelectorAll(".gauge-card .stat");
    if (!kotak.length) return;

    const tulis = (el, teks) => {
      const v = el && el.querySelector(".stat__v");
      if (v) v.textContent = teks;
    };

    const rp = n => "Rp" + Number(n).toLocaleString("id-ID") + " T";

    if (m.global) {
      tulis(kotak[0], rp(m.global.cap_t));
      tulis(kotak[1], rp(m.global.vol_t));
    }

    if (m.lokal) {
      tulis(kotak[2], rp(m.lokal.vol_t));
    } else if (kotak[2]) {
      // Tanpa angka bursa lokal, barisnya disembunyikan daripada
      // menampilkan nilai contoh yang keliru.
      kotak[2].style.display = "none";
    }

    if (m.global && kotak[3]) {
      const nilai = kotak[3].querySelector(".stat__v");
      if (nilai) {
        nilai.textContent =
          `BTC ${m.global.btc}% · ETH ${m.global.eth}%`.replace(/\./g, ",");
      }
      const batang = kotak[3].querySelectorAll(".bar i");
      if (batang.length >= 3) {
        const sisa = Math.max(0, 100 - m.global.btc - m.global.eth);
        batang[0].style.width = m.global.btc + "%";
        batang[1].style.width = m.global.eth + "%";
        batang[2].style.width = sisa + "%";
      }
    }
  }

  function renderLead(a) {
    const host = document.getElementById("lead");
    if (!host || !a) return;

    host.innerHTML = `
      <div class="lead__meta">
        <span class="eyebrow eyebrow--amber">${escapeHTML(a.cat)}</span>
        <span class="dot"></span><span class="stamp">${escapeHTML(a.a)}</span>
        <span class="dot"></span><span class="stamp">${escapeHTML(a.r || "")}</span>
      </div>
      <h1 class="lead__title">
        <a href="${escapeAttr(a.url)}" target="_blank" rel="noopener nofollow">
          ${escapeHTML(a.t)}
        </a>
      </h1>
      <p class="lead__deck">${escapeHTML(a.x || "")}</p>
      <p class="byline">Dari <b>${escapeHTML(a.w)}</b> · baca selengkapnya di situs penerbit</p>`;
  }

  function renderGrid(articles) {
    const grid = document.getElementById("newsgrid");
    const empty = document.getElementById("newsempty");
    if (!grid) return;

    grid.innerHTML = articles.map(attributedCard).join("");
    if (empty) empty.style.display = articles.length ? "none" : "block";
  }

  function renderRankedLive(articles) {
    const box = document.getElementById("ranked");
    if (!box) return;

    box.innerHTML = articles.map((a, i) => `
      <div class="ranked__row">
        <span class="ranked__n">${String(i + 1).padStart(2, "0")}</span>
        <div>
          <h3 class="ranked__t">
            <a href="${escapeAttr(a.url)}" target="_blank" rel="noopener nofollow">
              ${escapeHTML(a.t)}
            </a>
          </h3>
          <div class="ranked__m">
            <span class="eyebrow">${escapeHTML(a.cat)}</span>
            <span class="dot"></span><span class="stamp">${escapeHTML(a.a)}</span>
            <span class="dot"></span><span class="stamp">${escapeHTML(a.w)}</span>
          </div>
        </div>
      </div>`).join("");
  }

  function renderTabsLive(rubrics, onPick) {
    const tabs = document.getElementById("tabs");
    if (!tabs) return;

    tabs.innerHTML =
      `<button class="tab" role="tab" data-f="semua" aria-selected="true">Semua</button>` +
      rubrics.map(r =>
        `<button class="tab" role="tab" data-f="${escapeAttr(r.k)}" aria-selected="false">
           ${escapeHTML(r.label)} <span class="mono" style="opacity:.55">${r.jumlah}</span>
         </button>`).join("");

    tabs.querySelectorAll(".tab").forEach(tab =>
      tab.addEventListener("click", () => {
        tabs.querySelectorAll(".tab").forEach(t =>
          t.setAttribute("aria-selected", t === tab));
        onPick(tab.dataset.f);
      }));
  }

  /* ---------------------------------------------------------------------
     Penanda sumber langsung
     --------------------------------------------------------------------- */

  function markLive(ok, detail) {
    const badge = document.querySelector(".rail__badge");
    if (!badge) return;
    badge.title = ok
      ? `Data langsung · ${detail}`
      : `Data contoh · API tidak terhubung (${detail})`;
    const pulse = badge.querySelector(".pulse");
    if (pulse) pulse.style.background = ok ? "var(--up)" : "var(--amber)";
  }

  /* ---------------------------------------------------------------------
     Orkestrasi
     --------------------------------------------------------------------- */

  let currentRubric = "semua";

  async function loadArticles(rubric) {
    const payload = await getJSON("articles", rubric);
    renderGrid(payload.articles);
    return payload;
  }

  async function boot() {
    try {
      const [health, rubrics, top] = await Promise.all([
        getJSON("health"),
        getJSON("rubrics"),
        getJSON("top"),
      ]);

      renderTabsLive(rubrics, r => {
        currentRubric = r;
        loadArticles(r).catch(err => console.warn("[DCM] gagal memuat rubrik:", err));
      });

      renderRankedLive(top);
      // Artikel teratas naik jadi laporan utama, sehingga blok terbesar di
      // halaman tidak lagi menampilkan artikel contoh.
      renderLead(Array.isArray(top) ? top[0] : null);
      const payload = await loadArticles(currentRubric);

      // Blok sekunder diambil terpisah dan tidak boleh menggagalkan halaman:
      // kalau rubriknya kosong, berkasnya memang tidak ada, dan itu wajar.
      const ambilRubrik = async (nama) => {
        try {
          const r = await getJSON("articles", nama);
          return r.articles || [];
        } catch {
          return [];
        }
      };

      const [regulasi, semua] = await Promise.all([
        ambilRubrik("regulasi"),
        ambilRubrik("semua"),
      ]);

      // Pasar diambil terpisah: harga yang gagal dimuat tidak boleh
      // menghalangi berita tampil, dan sebaliknya.
      getJSON("market")
        .then(terapkanPasar)
        .catch(() => console.info("[DCM] data pasar belum tersedia"));

      renderReg(regulasi);
      // Kolom samping diisi artikel di luar sorotan, supaya tidak mengulang
      // judul yang sudah tampil besar di bagian atas halaman.
      const idSorotan = new Set((Array.isArray(top) ? top : []).map(a => a.id));
      renderSlim("opini", semua.filter(a => !idSorotan.has(a.id)));

      const usia = health.menit_sejak_pengambilan_terakhir;
      const segar = usia == null ? "" : ` · diperbarui ${usia} menit lalu`;
      markLive(true, `${payload.total} artikel · ${health.artikel_tayang} tayang${segar}`);
      console.info("[DCM] data aktif:", payload.total, "artikel", API ? "(mode API)" : "(mode statis)");

    } catch (err) {
      // Halaman tetap menampilkan isi statis. Ini jalur mundur yang sengaja
      // dibiarkan, bukan kegagalan diam-diam.
      markLive(false, err.message);
      console.warn("[DCM] API tidak terhubung, memakai data contoh:", err.message);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    boot();
    setInterval(() => {
      loadArticles(currentRubric).catch(() => { /* jalur mundur sudah aktif */ });
    }, REFRESH_MS);
  });
})();
