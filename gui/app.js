const settingsMeta = [
  ['search_url', 'Search URL', 'text', 'Public listing/search URL used when the monitor scans for newly listed products.'],
  ['product_check_delay', 'Delay between product API checks (sec)', 'number', 'Wait time between sequential product availability API checks. Higher values are gentler on Public.'],
  ['watchlist_check_interval', 'Watchlist check interval (sec)', 'number', 'How often known watchlist products become eligible for direct API rechecks.'],
  ['shallow_listing_scan_interval', 'Shallow listing scan interval (sec)', 'number', 'How often the monitor scans the first few listing pages to discover fresh products quickly.'],
  ['shallow_listing_pages', 'Shallow listing page limit', 'number', 'Number of listing pages scanned during a shallow discovery pass.'],
  ['deep_listing_scan_interval', 'Deep listing scan interval (sec)', 'number', 'How often the monitor performs a deeper listing scan across more pages.'],
  ['max_listing_pages', 'Deep listing page limit', 'number', 'Maximum number of pages scanned during a deep listing discovery pass.'],
  ['full_verify_interval', 'Full verify interval (sec)', 'number', 'Safety interval for rechecking previously discovered non-watchlist products even if their listing text did not change.'],
  ['listing_backoff_initial', 'Listing backoff initial (sec)', 'number', 'First cooldown period after a listing scan fails. This reduces repeat requests after errors.'],
  ['listing_backoff_max', 'Listing backoff max (sec)', 'number', 'Maximum cooldown period after repeated listing scan failures.'],
  ['check_interval', 'Monitor loop delay (sec)', 'number', 'Base wait time between monitor cycles after due checks finish.'],
  ['check_interval_jitter', 'Loop jitter max (sec)', 'number', 'Random extra wait added to each monitor cycle so timing is less robotic.'],
  ['api_timeout', 'API timeout (sec)', 'number', 'Maximum time to wait for Public product API responses before treating the check as failed.'],
  ['store_availability_timeout', 'Store API timeout (sec)', 'number', 'Maximum time to wait for Public store availability responses.'],
  ['target_store_area', 'Store area', 'text', 'Store region used for store-only availability checks, currently Athens.'],
  ['first_run_notify', 'Notify on first run', 'boolean', 'Whether available products found on the first run should send Discord notifications immediately.'],
];

let config = { settings: {}, watchlist_products: [] };
let state = { products: {} };
let status = { running: false };

const $ = (id) => document.getElementById(id);

function toast(message) {
  const el = $('toast');
  el.textContent = message;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}

function skuFromUrl(url) {
  const match = String(url || '').match(/\/(\d+)(?:[/?#]|$)/);
  return match ? match[1] : '—';
}

function renderStatus() {
  const statusEl = $('monitor-status');
  statusEl.textContent = status.running ? 'ONLINE' : 'OFFLINE';
  statusEl.classList.toggle('online', Boolean(status.running));
  $('pid-value').textContent = status.pid || '—';
  $('started-value').textContent = status.started_at || '—';
}

function renderSettings() {
  const grid = $('settings-grid');
  grid.innerHTML = '';
  for (const [key, label, type, description] of settingsMeta) {
    const wrap = document.createElement('div');
    wrap.className = 'field';
    const labelRow = document.createElement('div');
    labelRow.className = 'label-row';
    const labelEl = document.createElement('label');
    labelEl.textContent = label;
    labelEl.htmlFor = `setting-${key}`;
    const info = document.createElement('span');
    info.className = 'info-tip';
    info.textContent = 'i';
    info.tabIndex = 0;
    info.setAttribute('role', 'button');
    info.setAttribute('aria-label', `${label}: ${description}`);
    info.dataset.tooltip = description;
    labelRow.append(labelEl, info);
    let input;
    if (type === 'boolean') {
      input = document.createElement('select');
      input.innerHTML = '<option value="false">false</option><option value="true">true</option>';
      input.value = String(Boolean(config.settings[key]));
    } else {
      input = document.createElement('input');
      input.type = type;
      if (type === 'number') input.min = '0';
      input.value = config.settings[key] ?? '';
    }
    input.id = `setting-${key}`;
    input.dataset.setting = key;
    input.dataset.type = type;
    wrap.append(labelRow, input);
    grid.appendChild(wrap);
  }
}

function productRow(product, index) {
  const row = document.createElement('tr');
  row.innerHTML = `
    <td><input value="${escapeHtml(product.name || '')}" data-product-name="${index}" /></td>
    <td class="url-cell"><input value="${escapeHtml(product.url || '')}" data-product-url="${index}" /></td>
    <td class="sku">${skuFromUrl(product.url)}</td>
    <td><button class="danger" data-delete-product="${index}" title="Remove product">Remove</button></td>
  `;
  return row;
}

function renderProducts() {
  const body = $('products-body');
  body.innerHTML = '';
  config.watchlist_products.forEach((product, index) => body.appendChild(productRow(product, index)));
  $('tracked-count').textContent = config.watchlist_products.length;
}

function renderState() {
  const products = Object.values(state.products || {});
  const available = products.filter((p) => p.available === true);
  $('available-count').textContent = available.length;
  $('available-metric').textContent = available.length;
  const list = $('state-list');
  list.innerHTML = '';
  const recent = products
    .sort((a, b) => {
      if (a.available === true && b.available !== true) return -1;
      if (a.available !== true && b.available === true) return 1;
      return (b.last_verified || b.last_seen || 0) - (a.last_verified || a.last_seen || 0);
    })
    .slice(0, 18);
  if (!recent.length) {
    list.innerHTML = '<div class="state-item"><strong>No telemetry yet</strong><span>Start the monitor to populate state.</span></div>';
    return;
  }
  for (const product of recent) {
    const item = document.createElement('div');
    item.className = 'state-item';
    const statusClass = product.available ? 'available' : 'offline';
    const statusText = product.available ? 'Available' : 'Unavailable';
    item.innerHTML = `
      <div><strong>${escapeHtml(product.detail_title || product.name || 'Unknown')}</strong><br><span>${escapeHtml(product.price || 'No price')} · ${skuFromUrl(product.url)}</span></div>
      <div class="badge ${statusClass}">${statusText}</div>
    `;
    list.appendChild(item);
  }
}

function renderLogs(lines) {
  const logEl = $('logs');
  logEl.textContent = (lines || []).join('\n');
  logEl.scrollTop = logEl.scrollHeight;
}

function readConfigFromDom() {
  const settings = { ...config.settings };
  document.querySelectorAll('[data-setting]').forEach((input) => {
    const key = input.dataset.setting;
    const type = input.dataset.type;
    if (type === 'number') settings[key] = Number(input.value || 0);
    else if (type === 'boolean') settings[key] = input.value === 'true';
    else settings[key] = input.value.trim();
  });
  const products = config.watchlist_products.map((product, index) => ({
    name: document.querySelector(`[data-product-name="${index}"]`)?.value.trim() || product.name,
    url: document.querySelector(`[data-product-url="${index}"]`)?.value.trim() || product.url,
  }));
  return { settings, watchlist_products: products };
}

async function refreshAll(silent = false) {
  try {
    const [newConfig, newState, newStatus, logs] = await Promise.all([
      api('/api/config'), api('/api/state'), api('/api/status'), api('/api/logs')
    ]);
    config = newConfig;
    state = newState;
    status = newStatus;
    renderStatus();
    renderSettings();
    renderProducts();
    renderState();
    renderLogs(logs.lines);
    if (!silent) toast('HUD refreshed');
  } catch (error) {
    toast(error.message);
  }
}

async function refreshRuntime() {
  try {
    const [newState, newStatus, logs] = await Promise.all([api('/api/state'), api('/api/status'), api('/api/logs')]);
    state = newState;
    status = newStatus;
    renderStatus();
    renderState();
    renderLogs(logs.lines);
  } catch (error) {
    console.warn(error);
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char]));
}

function wireEvents() {
  $('refresh-button').addEventListener('click', () => refreshAll(false));
  $('save-button').addEventListener('click', async () => {
    try {
      config = await api('/api/config', { method: 'POST', body: JSON.stringify(readConfigFromDom()) });
      renderSettings();
      renderProducts();
      toast('Configuration saved');
    } catch (error) { toast(error.message); }
  });
  $('start-button').addEventListener('click', async () => {
    try { status = await api('/api/start', { method: 'POST' }); renderStatus(); toast('Monitor started'); }
    catch (error) { toast(error.message); }
  });
  $('stop-button').addEventListener('click', async () => {
    try { status = await api('/api/stop', { method: 'POST' }); renderStatus(); toast('Monitor stopped'); }
    catch (error) { toast(error.message); }
  });
  $('add-product-button').addEventListener('click', () => {
    config = readConfigFromDom();
    config.watchlist_products.push({ name: 'New Product', url: 'https://www.public.gr/product/.../0000000' });
    renderProducts();
    toast('Product row added');
  });
  $('products-body').addEventListener('click', (event) => {
    const button = event.target.closest('[data-delete-product]');
    if (!button) return;
    config = readConfigFromDom();
    config.watchlist_products.splice(Number(button.dataset.deleteProduct), 1);
    renderProducts();
  });
  $('products-body').addEventListener('input', () => {
    config = readConfigFromDom();
    renderProducts();
  });
}

function startCanvas() {
  const canvas = $('hud-canvas');
  const ctx = canvas.getContext('2d');
  let width = 0;
  let height = 0;
  function resize() {
    width = canvas.width = window.innerWidth * devicePixelRatio;
    height = canvas.height = window.innerHeight * devicePixelRatio;
    canvas.style.width = `${window.innerWidth}px`;
    canvas.style.height = `${window.innerHeight}px`;
  }
  function draw(time) {
    ctx.clearRect(0, 0, width, height);
    const cx = width * 0.74;
    const cy = height * 0.28;
    const base = Math.min(width, height) * 0.18;
    ctx.save();
    ctx.strokeStyle = 'rgba(81, 231, 255, 0.22)';
    ctx.lineWidth = 1.5 * devicePixelRatio;
    for (let i = 1; i <= 5; i++) {
      ctx.beginPath();
      ctx.arc(cx, cy, base * i / 5, 0, Math.PI * 2.5);
      ctx.stroke();
    }
    ctx.translate(cx, cy);
    ctx.rotate(time / 2000);
    ctx.strokeStyle = 'rgba(255, 190, 92, 0.35)';
    ctx.beginPath();
    ctx.moveTo(0,0);
    ctx.lineTo(base, 0);
    ctx.stroke();
    ctx.restore();
    requestAnimationFrame(draw);
  }
  window.addEventListener('resize', resize);
  resize();
  requestAnimationFrame(draw);
}

wireEvents();
startCanvas();
refreshAll(true);
setInterval(refreshRuntime, 2500);
