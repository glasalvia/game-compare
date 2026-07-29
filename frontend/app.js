// Game Compare — Frontend Logic v3
// Server-side pagination + Infinite Scroll + Dashboard A
const API = `http://${window.location.hostname}:5000`;

// ─── STATE ───
let currentSort = 'multiplier';
let currentOrder = 'desc';
let currentQuery = '';
let currentFilter = 'all';
let currentView = 'table'; // 'table' | 'cards'
let currentOffset = 0;
let isLoading = false;
let hasMore = true;
const PAGE_SIZE = 50;
let usdArsRate = 1520;
let lastTotal = 0;        // latest API total for footer

// ─── DOM REFS ───
const $loading = document.getElementById('loading');
const $error = document.getElementById('errorMsg');
const $noResults = document.getElementById('noResults');
const $tableWrap = document.getElementById('tableWrap');
const $cardGrid = document.getElementById('cardGrid');
const $tbody = document.getElementById('gameTableBody');
const $search = document.getElementById('searchInput');
const $sort = document.getElementById('sortSelect');
const $lastUpdateText = document.getElementById('lastUpdateText');
const $footerStats = document.getElementById('footerStats');
const $footerUpdate = document.getElementById('footerUpdate');
const $modalOverlay = document.getElementById('modalOverlay');
const $modalBody = document.getElementById('modalBody');
const $modalClose = document.getElementById('modalClose');
const $viewTable = document.getElementById('viewTable');
const $viewCards = document.getElementById('viewCards');
const $loadMoreWrap = document.getElementById('loadMoreWrap');
const $loadMoreBtn = document.getElementById('loadMoreBtn');

// ─── SENTINEL ───
const sentinel = document.getElementById('scrollSentinel');
const observer = new IntersectionObserver((entries) => {
  if (entries[0].isIntersecting && !isLoading && hasMore) {
    loadPage(currentOffset);
  }
}, { rootMargin: '200px' });
observer.observe(sentinel);

// ─── HELPERS ───
function formatARS(price) {
  if (price == null || price === 0) return 'Gratis';
  return 'ARS$ ' + price.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function formatUSD(price) {
  if (price == null || price === 0) return 'Gratis';
  return 'USD$ ' + price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function formatDate(isoStr) {
  if (!isoStr) return '—';
  const d = new Date(isoStr);
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: 'short', year: 'numeric' }) +
    ' ' + d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
}
function esc(str) {
  const div = document.createElement('div');
  div.appendChild(document.createTextNode(str || ''));
  return div.innerHTML;
}

// ─── RESET & RELOAD ───
function resetAndReload() {
  currentOffset = 0;
  hasMore = true;
  $tbody.innerHTML = '';
  $cardGrid.innerHTML = '';
  sentinel.style.display = 'none';
  loadPage(0);
}

// ─── LOAD STATS (legacy: last update + footer stats) ───
async function loadStats() {
  try {
    const res = await fetch(`${API}/api/stats`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const statsData = await res.json();
    if (statsData.usd_ars_rate) usdArsRate = statsData.usd_ars_rate;

    if (statsData.last_update && (statsData.last_update.xbox || statsData.last_update.steam)) {
      const latest = statsData.last_update.steam || statsData.last_update.xbox;
      $lastUpdateText.textContent = formatDate(latest);
      $footerUpdate.textContent = formatDate(latest);
    }
  } catch (e) {
    console.warn('Stats failed:', e);
  }
}

// ─── LOAD PAGE (server-side pagination) ───
async function loadPage(offset) {
  if (isLoading || !hasMore) return;
  isLoading = true;

  if ($loadMoreBtn) {
    $loadMoreBtn.textContent = 'CARGANDO...';
    $loadMoreBtn.disabled = true;
  }

  // Hide initial loading skeleton after first successful load
  if ($loading.style.display !== 'none') {
    // keep showing until first page
  }

  try {
    const params = new URLSearchParams({
      sort: currentSort,
      order: currentOrder,
      filter: currentFilter,
      limit: String(PAGE_SIZE),
      offset: String(offset)
    });
    if (currentQuery) params.set('q', currentQuery);

    const res = await fetch(`${API}/api/games?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    $loading.style.display = 'none';
    $error.style.display = 'none';

    const games = data.games;
    lastTotal = data.total || 0;

    if (offset === 0) {
      // First page — replace content
      $noResults.style.display = 'none';
      if (games.length === 0) {
        $noResults.style.display = 'block';
        $tableWrap.classList.remove('visible');
        $cardGrid.classList.remove('visible');
      } else {
        replaceGames(games);
      }
    } else {
      // Append to existing content
      appendGames(games);
    }

    currentOffset = offset + games.length;
    hasMore = currentOffset < data.total;

    // Update sentinel + load more button
    sentinel.style.display = hasMore ? 'block' : 'none';
    if ($loadMoreWrap) {
      $loadMoreWrap.style.display = hasMore && !isLoading ? 'block' : 'none';
    }

    isLoading = false;

    if ($loadMoreBtn) {
      $loadMoreBtn.textContent = '▼ CARGAR MÁS';
      $loadMoreBtn.disabled = false;
      $loadMoreWrap.style.display = hasMore ? 'block' : 'none';
    }

  } catch (e) {
    $loading.style.display = 'none';
    $error.style.display = 'block';
    $error.textContent = 'Error al conectar con la API. ¿Está corriendo el servidor en ' + API + '?';
    isLoading = false;
    if ($loadMoreBtn) {
      $loadMoreBtn.textContent = '▼ CARGAR MÁS';
      $loadMoreBtn.disabled = false;
    }
  }
}

// ─── APPEND GAMES (infinite scroll) ───
function appendGames(games) {
  const view = window.innerWidth <= 768 ? 'cards' : currentView;
  if (view === 'table') {
    $tableWrap.classList.add('visible');
    $cardGrid.classList.remove('visible');
    renderTableRows(games);
  } else {
    $cardGrid.classList.add('visible');
    $tableWrap.classList.remove('visible');
    renderCardsAppend(games);
  }
}

// ─── REPLACE GAMES ───
function replaceGames(games) {
  const view = window.innerWidth <= 768 ? 'cards' : currentView;
  if (view === 'table') {
    $tableWrap.classList.add('visible');
    $cardGrid.classList.remove('visible');
    $tbody.innerHTML = '';
    renderTableRows(games);
  } else {
    $cardGrid.classList.add('visible');
    $tableWrap.classList.remove('visible');
    $cardGrid.innerHTML = '';
    renderCardsAppend(games);
  }
}

// ─── RENDER TABLE ROWS ───
function renderTableRows(games) {
  for (const g of games) {
    const tr = document.createElement('tr');

    const tdTitle = document.createElement('td');
    tdTitle.innerHTML = `
      <div class="game-title" title="${esc(g.xbox.title)}">${esc(g.xbox.title)}</div>
      <div class="game-links">
        <a class="link-xbox" href="${esc(g.xbox.url)}" target="_blank" rel="noopener">Xbox</a>
        <a class="link-steam" href="${esc(g.steam.url)}" target="_blank" rel="noopener">Steam</a>
      </div>`;
    tr.appendChild(tdTitle);

    const tdXbox = document.createElement('td');
    tdXbox.className = 'price';
    if (g.xbox.is_free && !g.xbox.is_game_pass) tdXbox.classList.add('cheapest-free');
    else if (g.cheapest === 'xbox') tdXbox.classList.add('cheapest-xbox');

    let xboxHtml = g.xbox.is_free ? 'Gratis' : formatARS(g.xbox.price_ars);
    if (g.xbox.discount_pct && !g.xbox.is_free) {
      xboxHtml += ` <span class="price-original">${formatARS(g.xbox.original_price_ars)}</span>`;
    }
    if (g.xbox.is_game_pass) {
      xboxHtml += ' <span class="badge badge-gp">Game Pass</span>';
    }
    tdXbox.innerHTML = xboxHtml;
    tr.appendChild(tdXbox);

    const tdUsd = document.createElement('td');
    tdUsd.className = 'price-equiv';
    tdUsd.textContent = g.xbox.price_ars > 0 ? `≈USD$ ${g.xbox.price_usd_equiv.toFixed(2)}` : '—';
    tr.appendChild(tdUsd);

    const tdSteam = document.createElement('td');
    tdSteam.className = 'price';
    if (g.steam.is_free) tdSteam.classList.add('cheapest-free');
    else if (g.cheapest === 'steam') tdSteam.classList.add('cheapest-steam');

    let steamHtml = g.steam.is_free ? 'Gratis' : formatUSD(g.steam.price_usd);
    if (g.steam.discount_pct && !g.steam.is_free) {
      steamHtml += ` <span class="price-original">${formatUSD(g.steam.original_price_usd)}</span>`;
    }
    tdSteam.innerHTML = steamHtml;
    tr.appendChild(tdSteam);

    const tdDiff = document.createElement('td');
    tdDiff.className = 'diff';
    if (g.multiplier != null && g.multiplier > 1.0) {
      tdDiff.textContent = `${g.multiplier.toFixed(1)}x más barato en ${g.cheaper_on === 'xbox' ? 'Xbox' : 'Steam'}`;
      tdDiff.classList.add(g.cheaper_on === 'xbox' ? 'xbox-cheaper' : 'steam-cheaper');
    } else if (g.multiplier != null && g.multiplier >= 0.95) {
      tdDiff.textContent = '≈ Igual';
    } else {
      tdDiff.textContent = '—';
    }
    tr.appendChild(tdDiff);

    tr.style.cursor = 'pointer';
    tr.addEventListener('click', () => openDetail(g));
    $tbody.appendChild(tr);
  }
}

// ─── RENDER CARDS APPEND ───
function renderCardsAppend(games) {
  for (const g of games) {
    const card = document.createElement('div');
    card.className = 'game-card';

    let diffHtml = '';
    if (g.multiplier != null && g.multiplier > 1.0) {
      diffHtml = `<div class="card-diff-badge ${g.cheaper_on === 'xbox' ? 'xbox-cheaper' : 'steam-cheaper'}">
        ${g.multiplier.toFixed(1)}x más barato en ${g.cheaper_on === 'xbox' ? 'Xbox' : 'Steam'}
      </div>`;
    } else if (g.multiplier != null && g.multiplier >= 0.95) {
      diffHtml = `<div class="card-diff-badge equal">≈ Igual</div>`;
    }

    let xboxPriceClass = g.xbox.is_free ? '' : (g.cheapest === 'xbox' ? 'green' : '');
    let steamPriceClass = g.steam.is_free ? '' : (g.cheapest === 'steam' ? 'blue' : '');

    let badges = '';
    if (g.xbox.is_game_pass) badges += '<span class="card-badge gp">Game Pass</span>';
    if (g.xbox.is_free || g.steam.is_free) badges += '<span class="card-badge free">Gratis</span>';
    if (g.xbox.discount_pct && !g.xbox.is_game_pass && !g.xbox.is_free) badges += `<span class="card-badge discount">Xbox -${g.xbox.discount_pct}%</span>`;
    if (g.steam.discount_pct && !g.steam.is_free) badges += `<span class="card-badge discount">Steam -${g.steam.discount_pct}%</span>`;

    card.innerHTML = `
      <div class="card-title" title="${esc(g.xbox.title)}">${esc(g.xbox.title)}</div>
      ${diffHtml}
      <div class="card-prices">
        <div class="card-price-box">
          <div class="card-price-label">Xbox (ARS)</div>
          <div class="card-price-value ${xboxPriceClass}">${g.xbox.is_free ? 'Gratis' : formatARS(g.xbox.price_ars)}</div>
          ${g.xbox.price_ars > 0 ? `<div style="font-size:0.7rem;color:var(--text-dim)">≈USD$ ${g.xbox.price_usd_equiv.toFixed(2)}</div>` : ''}
        </div>
        <div class="card-price-box">
          <div class="card-price-label">Steam (USD)</div>
          <div class="card-price-value ${steamPriceClass}">${g.steam.is_free ? 'Gratis' : formatUSD(g.steam.price_usd)}</div>
          ${g.steam.discount_pct ? `<div style="font-size:0.7rem;color:var(--gold)">-${g.steam.discount_pct}%</div>` : ''}
        </div>
      </div>
      <div class="card-badges">${badges}</div>
    `;

    card.addEventListener('click', () => openDetail(g));
    $cardGrid.appendChild(card);
  }
}

// ─── MODAL ───
// ─── SHARE INLINE LOGOS ───
let _shareGames = {}; // lookup by xbox_store_id

function getShareUrl(g) {
  const base = window.location.origin + window.location.pathname;
  return `${base}?q=${encodeURIComponent(g.xbox.title)}`;
}

function getShareText(g) {
  const xboxPrice = g.xbox.price_ars > 0 ? `ARS$ ${g.xbox.price_ars.toLocaleString('es-AR')}` : 'Gratis';
  const steamPriceUsd = g.steam.price_usd > 0 ? g.steam.price_usd : 0;
  const steamPriceArs = Math.round(steamPriceUsd * usdArsRate);
  const steamPrice = steamPriceUsd === 0 ? 'Sin datos' : `ARS$ ${steamPriceArs.toLocaleString('es-AR')}`;
  
  let diffLine = '';
  if (g.multiplier != null && g.multiplier > 1.0 && steamPriceUsd > 0 && g.xbox.price_ars > 0) {
    const xboxArs = g.xbox.price_ars;
    const saving = g.cheaper_on === 'xbox' ? xboxArs : steamPriceArs;
    const expensive = g.cheaper_on === 'xbox' ? steamPriceArs : xboxArs;
    const diff = expensive - saving;
    if (diff > 0) {
      diffLine = `Ahorras ARS$ ${diff.toLocaleString('es-AR')} eligiendo ${g.cheaper_on === 'xbox' ? 'Xbox' : 'Steam'}\n`;
    }
  }

  const url = getShareUrl(g);
  return `🎮 Game Compare: ${g.xbox.title}\n${diffLine}Xbox: ${xboxPrice} | Steam: ${steamPrice}\n🔗 ${url}`;
}

function shareTo(platform, xboxStoreId) {
  const g = _shareGames[xboxStoreId];
  if (!g) return;
  const text = getShareText(g);
  const url = getShareUrl(g);
  if (platform === 'whatsapp') {
    window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, '_blank');
  } else if (platform === 'telegram') {
    window.open(`https://t.me/share/url?url=${encodeURIComponent(url)}\u0026text=${encodeURIComponent(g.xbox.title + '\n' + text)}`, '_blank');
  } else if (platform === 'copy') {
    navigator.clipboard.writeText(text + '\n' + url).then(() => alert('¡Copiado al portapapeles!'));
  } else {
    window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}`, '_blank');
  }
}

function shareXboxGame(id) { shareTo('x', id); }
function shareWhatsAppGame(id) { shareTo('whatsapp', id); }
function shareTelegramGame(id) { shareTo('telegram', id); }

// ─── VIEW TOGGLE

function platformBadge(playableOn) {
  const map = {
    'Xbox':        { icon: '🎮', label: 'Solo Xbox', cls: 'xbox-only', hint: 'Jugable solo en consola Xbox' },
    'PC+Xbox':     { icon: '💻🎮', label: 'PC + Xbox', cls: 'play-anywhere', hint: 'Play Anywhere — una compra, dos plataformas' },
    'PC':          { icon: '💻', label: 'Solo PC', cls: 'pc-only', hint: 'Solo Microsoft Store PC' },
  };
  const info = map[playableOn] || map['Xbox'];
  return `<span class="platform-badge ${info.cls}" title="${info.hint}">${info.icon} ${info.label}</span>`;
}

function openDetail(g) {
  _shareGames[g.xbox_store_id] = g;
  const xboxDisplay = g.xbox.is_game_pass ? 'Game Pass' : g.xbox.is_free ? 'Gratis' : formatARS(g.xbox.price_ars);
  const steamDisplay = g.steam.is_free ? 'Gratis' : formatUSD(g.steam.price_usd);

  $modalBody.innerHTML = `
    <h2>${esc(g.xbox.title)}</h2>
    <div class="detail-row">
      <span class="detail-label">Xbox (ARS)</span>
      <span class="detail-value" style="color:var(--green)">${xboxDisplay}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Xbox Eq. USD</span>
      <span class="detail-value">≈USD$ ${g.xbox.price_usd_equiv.toFixed(2)}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Steam (USD)</span>
      <span class="detail-value" style="color:var(--blue)">${steamDisplay}</span>
    </div>
    ${g.multiplier != null ? `
    <div class="detail-row">
      <span class="detail-label">Diferencia</span>
      <span class="detail-value">${g.multiplier.toFixed(1)}x más barato en ${g.cheaper_on === 'xbox' ? 'Xbox' : 'Steam'}</span>
    </div>` : ''}
    <div style="margin-top:0.5rem;display:flex;justify-content:center">
      ${platformBadge(g.xbox.playable_on)}
    </div>
    <div class="external-links">
      <a class="link-xbox" href="${esc(g.xbox.url)}" target="_blank" rel="noopener">Xbox Store ↗</a>
      <a class="link-steam" href="${esc(g.steam.url)}" target="_blank" rel="noopener">Steam ↗</a>
    </div>
    <div style="text-align:center;margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid var(--border);display:flex;justify-content:center;gap:1.25rem">
      <a onclick="shareXboxGame(${g.xbox_store_id})" style="cursor:pointer;text-decoration:none;display:inline-block;padding:2px" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.7" title="Compartir en X">
        <svg width="28" height="28" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
          <!-- fondo negro redondeado -->
          <rect x="1" y="1" width="14" height="14" rx="1" fill="#000"/>
          <!-- X blanca bold estilo 8-bit -->
          <rect x="4" y="3" width="2" height="1" fill="#fff"/><rect x="11" y="3" width="2" height="1" fill="#fff"/>
          <rect x="4" y="4" width="1" height="1" fill="#fff"/><rect x="5" y="4" width="1" height="1" fill="#fff"/><rect x="10" y="4" width="1" height="1" fill="#fff"/><rect x="11" y="4" width="1" height="1" fill="#fff"/>
          <rect x="5" y="5" width="2" height="1" fill="#fff"/><rect x="10" y="5" width="2" height="1" fill="#fff"/>
          <rect x="6" y="6" width="2" height="1" fill="#fff"/><rect x="9" y="6" width="2" height="1" fill="#fff"/>
          <rect x="7" y="7" width="3" height="1" fill="#fff"/>
          <rect x="6" y="8" width="2" height="1" fill="#fff"/><rect x="9" y="8" width="2" height="1" fill="#fff"/>
          <rect x="5" y="9" width="2" height="1" fill="#fff"/><rect x="10" y="9" width="2" height="1" fill="#fff"/>
          <rect x="4" y="10" width="2" height="1" fill="#fff"/><rect x="11" y="10" width="2" height="1" fill="#fff"/>
          <rect x="4" y="11" width="1" height="1" fill="#fff"/><rect x="5" y="11" width="1" height="1" fill="#fff"/><rect x="10" y="11" width="1" height="1" fill="#fff"/><rect x="11" y="11" width="1" height="1" fill="#fff"/>
          <rect x="4" y="12" width="2" height="1" fill="#fff"/><rect x="11" y="12" width="2" height="1" fill="#fff"/>
        </svg>
      </a>
      <a onclick="shareWhatsAppGame(${g.xbox_store_id})" style="cursor:pointer;text-decoration:none;display:inline-block;padding:2px" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.7" title="Compartir en WhatsApp">
        <img src="whatsapp-icon.png" width="28" height="28" alt="WhatsApp" style="display:block">
      </a>
      <a onclick="shareTelegramGame(${g.xbox_store_id})" style="cursor:pointer;text-decoration:none;display:inline-block;padding:2px" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.7" title="Compartir en Telegram">
        <img src="telegram-icon.png" width="28" height="28" alt="Telegram" style="display:block">
      </a>
    </div>
  `;
  $modalOverlay.classList.add('active');
}

function closeDetail() {
  $modalOverlay.classList.remove('active');
}

// ─── VIEW TOGGLE ───
$viewTable.addEventListener('click', () => {
  if (currentView === 'table') return;
  currentView = 'table';
  $viewTable.classList.add('active');
  $viewCards.classList.remove('active');
  resetAndReload();
});
$viewCards.addEventListener('click', () => {
  if (currentView === 'cards') return;
  currentView = 'cards';
  $viewCards.classList.add('active');
  $viewTable.classList.remove('active');
  resetAndReload();
});

// ─── FILTER CHIPS ───
document.getElementById('filterChips').addEventListener('click', (e) => {
  const chip = e.target.closest('.filter-chip');
  if (!chip) return;
  document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
  chip.classList.add('active');
  currentFilter = chip.dataset.filter;
  window.scrollTo({ top: 0, behavior: 'smooth' });
  resetAndReload();
});

// ─── SEARCH ───
let searchTimeout;
$search.addEventListener('input', () => {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    currentQuery = $search.value.trim();
    if (currentQuery) {
      const url = new URL(window.location);
      url.searchParams.set('q', currentQuery);
      window.history.pushState({}, '', url);
    } else {
      const url = new URL(window.location);
      url.searchParams.delete('q');
      window.history.pushState({}, '', url);
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
    resetAndReload();
  }, 300);
});

// ─── SORT ───
$sort.addEventListener('change', () => {
  const [sort, order] = $sort.value.split(',');
  currentSort = sort;
  currentOrder = order;
  document.querySelectorAll('thead th').forEach(th => {
    th.classList.remove('sorted');
    if (th.dataset.sort === sort) th.classList.add('sorted');
  });
  resetAndReload();
});

document.querySelector('thead').addEventListener('click', (e) => {
  const th = e.target.closest('th');
  if (!th || !th.dataset.sort) return;
  const sort = th.dataset.sort;
  if (sort === currentSort) {
    currentOrder = currentOrder === 'desc' ? 'asc' : 'desc';
  } else {
    currentSort = sort;
    currentOrder = sort === 'title' ? 'asc' : 'desc';
  }
  $sort.value = `${currentSort},${currentOrder}`;
  document.querySelectorAll('thead th').forEach(t => t.classList.remove('sorted'));
  th.classList.add('sorted');
  resetAndReload();
});

// ─── LOAD MORE BUTTON ───
if ($loadMoreBtn) {
  $loadMoreBtn.addEventListener('click', () => {
    if (!isLoading && hasMore) {
      loadPage(currentOffset);
    }
  });
}

// ─── MODAL CLOSE ───
$modalClose.addEventListener('click', closeDetail);
$modalOverlay.addEventListener('click', (e) => { if (e.target === $modalOverlay) closeDetail(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDetail(); });

// ─── LOAD FEATURED SECTIONS ───
async function loadFeatured() {
  try {
    const res = await fetch(`${API}/api/featured?filter=${currentFilter}&limit=3`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const grid = document.getElementById('featuredGrid');
    if (!grid) return;

    // Map known section ids to display names (fallback to server name)
    const displayName = (id, fallback) => {
      const map = {
        'ofertas_xbox': '🔥 MEJORES OFERTAS XBOX',
        'ofertas_steam': '💰 MEJORES OFERTAS STEAM',
        'juegos_comparados': '📊 JUEGOS COMPARADOS'
      };
      return map[id] || fallback;
    };

    const sectionCards = data.sections.map(section => {
      // If this is the count section, render big number
      if (section.id === 'juegos_comparados') {
        const count = section.games.length > 0 ? section.games[0].count : 0;
        return `<div class="featured-section-card">
          <div class="featured-section-title">${displayName(section.id, section.name)}</div>
          <div class="featured-big-count">
            <div class="featured-big-number">${count.toLocaleString('es-AR')}</div>
            <div class="featured-big-label">juegos comparados</div>
          </div>
        </div>`;
      }

      const gamesHtml = section.games.length === 0
        ? '<div class="featured-game-row"><span class="featured-game-name" style="color:var(--text-dim)">Sin datos</span></div>'
        : section.games.map(g => {
            const saveText = g.ahorro_ars > 0
              ? 'Ahorro ARS$ ' + g.ahorro_ars.toLocaleString('es-AR', {maximumFractionDigits: 0})
              : '';

            let pricesHtml = '';
            if (section.id === 'ofertas_xbox') {
              pricesHtml = `<div class="featured-game-prices">
                ARS$ ${g.xbox_price_ars.toLocaleString('es-AR')} 
                <span style="color:var(--text-dim);text-decoration:line-through">ARS$ ${g.xbox_msrp_ars.toLocaleString('es-AR')}</span>
                <span style="color:var(--green)">-${g.xbox_discount_pct}%</span>
              </div>`;
            } else if (section.id === 'ofertas_steam') {
              pricesHtml = `<div class="featured-game-prices">
                Steam $${g.steam_price.toFixed(2)} 
                <span style="color:var(--text-dim);text-decoration:line-through">$${g.steam_original_price.toFixed(2)}</span>
                <span style="color:var(--blue)">-${g.steam_discount_pct}%</span>
                <span style="margin-left:0.5rem">Xbox ARS$ ${g.xbox_price_ars.toLocaleString('es-AR')}</span>
              </div>`;
            }

            return `<div class="featured-game-row">
              <div style="flex:1;min-width:0">
                <div class="featured-game-name">${esc(g.xbox_title)}</div>
                ${pricesHtml}
              </div>
              <div class="featured-game-save">${saveText}</div>
            </div>`;
          }).join('');

      return `<div class="featured-section-card">
        <div class="featured-section-title">${displayName(section.id, section.name)}</div>
        ${gamesHtml}
      </div>`;
    }).join('');

    grid.innerHTML = sectionCards;

  } catch (err) {
    console.error('loadFeatured error:', err);
  }
}

// ─── INIT ───
(function init() {
  // Restore search from URL
  const params = new URLSearchParams(window.location.search);
  if (params.has('q')) {
    currentQuery = params.get('q');
    $search.value = currentQuery;
  }
})();

loadStats().then(() => {
  loadPage(0);
  loadFeatured();
});