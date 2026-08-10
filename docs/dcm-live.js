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
  const DATA = window.DCM_DATA_BASE || "data/api";
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
        return live ? API + "/api/health" : DATA + "/health.json" + stamp();
      case "rubrics":
        return live ? API + "/api/rubrics" : DATA + "/rubrics.json" + stamp();
      case "top":
        return live ? API + "/api/articles/top?limit=5"
                    : DATA + "/articles/top.json" + stamp();
      case "articles":
        if (!rubric || rubric === "semua") {
          return live ? API + "/api/articles" : DATA + "/articles.json" + stamp();
        }
        return live
          ? API + "/api/articles?rubric=" + encodeURIComponent(rubric)
          : DATA + "/articles/" + encodeURIComponent(rubric) + ".json" + stamp();
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
