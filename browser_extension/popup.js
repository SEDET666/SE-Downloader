// SE Downloader Popup — no inline handlers (CSP compliant)

let cfg = {};

document.addEventListener('DOMContentLoaded', () => {
  checkConn();
  loadCfg();
  bindEvents();
});

// ── connection check ──────────────────────────────────────────────────────────
function checkConn() {
  chrome.runtime.sendMessage({ type: 'check_connection' }, r => {
    const dot  = document.getElementById('dot');
    const stxt = document.getElementById('stxt');
    if (r && r.ok) {
      dot.className  = 'dot ok';
      stxt.textContent = '已连接到 SE Downloader';
    } else {
      dot.className  = 'dot err';
      stxt.textContent = '未连接 — 请先启动 SE Downloader';
    }
  });
}

// ── config load ───────────────────────────────────────────────────────────────
function loadCfg() {
  chrome.runtime.sendMessage({ type: 'get_config' }, c => {
    cfg = c || {};
    setTog('tog-auto',  cfg.autoIntercept);
    setTog('tog-all',   cfg.interceptAllDownloads);
    setTog('tog-notif', cfg.showNotification);
    const ei = document.getElementById('extIn');
    const pi = document.getElementById('portIn');
    if (ei) ei.value = cfg.interceptExtensions || '';
    if (pi) pi.value = cfg.appPort || 26339;
  });
}

// ── bind all events (no inline handlers) ─────────────────────────────────────
function bindEvents() {
  // Tabs
  document.getElementById('tab-dl')   .addEventListener('click', () => switchTab('dl'));
  document.getElementById('tab-batch').addEventListener('click', () => switchTab('batch'));
  document.getElementById('tab-opt')  .addEventListener('click', () => switchTab('opt'));

  // Download tab
  document.getElementById('btnSend')   .addEventListener('click', send1);
  document.getElementById('btnFillTab').addEventListener('click', fillTab);

  // Batch tab
  document.getElementById('btnBatch').addEventListener('click', sendBatch);

  // Options tab — toggles
  document.getElementById('tog-auto') .addEventListener('click', function() { toggleCfg('autoIntercept', this); });
  document.getElementById('tog-all')  .addEventListener('click', function() { toggleCfg('interceptAllDownloads', this); });
  document.getElementById('tog-notif').addEventListener('click', function() { toggleCfg('showNotification', this); });

  // Options tab — buttons
  document.getElementById('btnSaveOpt') .addEventListener('click', saveOpt);
  document.getElementById('btnAdvanced').addEventListener('click', () => chrome.runtime.openOptionsPage());
}

// ── tab switching ─────────────────────────────────────────────────────────────
function switchTab(name) {
  ['dl', 'batch', 'opt'].forEach(n => {
    document.getElementById('tab-' + n).classList.toggle('active', n === name);
    document.getElementById('panel-' + n).classList.toggle('active', n === name);
  });
}

// ── send single URL ───────────────────────────────────────────────────────────
function send1() {
  const url = document.getElementById('urlInput').value.trim();
  if (!url) { showToast('请输入下载链接'); return; }
  chrome.runtime.sendMessage({ type: 'send_url', url }, r => {
    if (r && r.ok) {
      showToast('✅ 已发送到下载器');
      document.getElementById('urlInput').value = '';
    } else {
      showToast('❌ 发送失败，请确认下载器已启动');
    }
  });
}

// ── fill current tab URL ──────────────────────────────────────────────────────
function fillTab() {
  chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
    if (tabs[0]) document.getElementById('urlInput').value = tabs[0].url;
  });
}

// ── batch send ────────────────────────────────────────────────────────────────
function sendBatch() {
  const lines = document.getElementById('batchTxt').value
    .split('\n').map(l => l.trim()).filter(l => l.startsWith('http'));
  if (!lines.length) { showToast('没有有效 URL'); return; }
  let sent = 0;
  const next = i => {
    if (i >= lines.length) {
      showToast('✅ 已发送 ' + sent + ' 个任务');
      document.getElementById('batchTxt').value = '';
      return;
    }
    chrome.runtime.sendMessage({ type: 'send_url', url: lines[i] }, r => {
      if (r && r.ok) sent++;
      setTimeout(() => next(i + 1), 80);
    });
  };
  next(0);
}

// ── toggle config key ─────────────────────────────────────────────────────────
function toggleCfg(key, btn) {
  cfg[key] = !cfg[key];
  btn.classList.toggle('on', !!cfg[key]);
}

function setTog(id, val) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle('on', !!val);
}

// ── save options ──────────────────────────────────────────────────────────────
function saveOpt() {
  const updates = {
    autoIntercept:        !!cfg.autoIntercept,
    interceptAllDownloads:!!cfg.interceptAllDownloads,
    showNotification:     !!cfg.showNotification,
    interceptExtensions:  document.getElementById('extIn').value.trim(),
    appPort:              parseInt(document.getElementById('portIn').value) || 26339,
  };
  chrome.storage.sync.set(updates, () => {
    cfg = Object.assign({}, cfg, updates);
    showToast('✅ 设置已保存');
  });
}

// ── toast ─────────────────────────────────────────────────────────────────────
function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2500);
}
