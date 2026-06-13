/**
 * SE Downloader Extension - Manifest V3 Service Worker
 *
 * Key points:
 * - fetch() to http://127.0.0.1 requires server to return
 *   Access-Control-Allow-Private-Network: true  (Chrome PNA requirement)
 * - POST body sent as plain text containing JSON (avoids preflight issues)
 * - Uses chrome.alarms for periodic connection check (SW-safe timer)
 */

// ── Config ────────────────────────────────────────────────────────────────────
const DEFAULTS = {
  appPort: 26339,
  autoIntercept: true,
  interceptAllDownloads: false,
  interceptExtensions: "zip,rar,7z,tar,gz,bz2,xz,exe,msi,dmg,pkg,iso,mp4,mp3,mkv,avi,mov,wmv,flac,wav,aac,ogg,pdf,apk,torrent,bin,img,deb,rpm,jar,war,nupkg,crx",
  showNotification: true,
};
let cfg = { ...DEFAULTS };

async function loadCfg() {
  try {
    const saved = await chrome.storage.sync.get(DEFAULTS);
    cfg = { ...DEFAULTS, ...saved };
  } catch(e) { console.warn('[SE] loadCfg error:', e); }
}
loadCfg();
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'sync') return;
  for (const [k, {newValue}] of Object.entries(changes)) cfg[k] = newValue;
});

// ── Connection state ──────────────────────────────────────────────────────────
let appConnected = false;

function appUrl() { return `http://127.0.0.1:${cfg.appPort}`; }

async function checkConn() {
  await loadCfg();
  try {
    const r = await fetch(appUrl(), {
      method: 'GET',
      // No mode:'no-cors' — we need actual CORS so server must send
      // Access-Control-Allow-Private-Network: true
    });
    appConnected = true;
    console.log('[SE] Connected to app on port', cfg.appPort);
  } catch(e) {
    appConnected = false;
    console.log('[SE] App not reachable:', e.message || e);
  }
}
checkConn();

// Alarm-based periodic check (setInterval not reliable in SW)
chrome.alarms.create('connCheck', { periodInMinutes: 0.083 }); // ~5s
chrome.alarms.onAlarm.addListener(a => { if (a.name === 'connCheck') checkConn(); });

// ── State tables (in-memory, reset if SW restarts) ────────────────────────────
const reqMap       = new Map(); // requestId → {url, finalUrl, tabId, referer}
const interceptQ   = new Map(); // url → {referer, tabId, ts}
const sentUrls     = new Map(); // url → timestamp  (dedup 10s)
const handledDlIds = new Set(); // download item ids being handled

// ── Context menus ─────────────────────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    const M = chrome.contextMenus.create.bind(chrome.contextMenus);
    M({id:'se-link',  title:'🔽 SE Downloader: Download Link',  contexts:['link']});
    M({id:'se-image', title:'🔽 SE Downloader: Download Image', contexts:['image']});
    M({id:'se-media', title:'🔽 SE Downloader: Download Media', contexts:['video','audio']});
    M({id:'se-page',  title:'🔽 SE Downloader: Download Page',  contexts:['page']});
  });
});
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const url = info.linkUrl || info.srcUrl || info.pageUrl || '';
  if (!url) return;
  await loadCfg();
  const cookies = await getCookies(url);
  sendToApp(url, tab?.url || '', cookies);
});

// ── Helper: extension lists ───────────────────────────────────────────────────
function extFromName(s) {
  if (!s) return '';
  const d = s.lastIndexOf('.');
  return d >= 0 ? s.slice(d+1).split('?')[0].toLowerCase() : '';
}
function extFromUrl(url) {
  try {
    const u = new URL(url);
    for (const k of ['filename','fn','name','file']) {
      const v = u.searchParams.get(k);
      if (v) { const e = extFromName(v); if (e) return e; }
    }
    return extFromName(decodeURIComponent(u.pathname.split('/').pop() || ''));
  } catch { return ''; }
}
function parseCDFilename(cd) {
  if (!cd) return '';
  let m = cd.match(/filename\*\s*=\s*[^';\s]+''\s*([^\s;]+)/i);
  if (m) { try { return decodeURIComponent(m[1]); } catch {} }
  m = cd.match(/filename\s*=\s*"([^"]+)"/i);
  if (m) return m[1].trim();
  m = cd.match(/filename\s*=\s*([^\s;]+)/i);
  if (m) return m[1].trim().replace(/^['"]|['"]$/g,'');
  return '';
}
function userExtList() {
  return cfg.interceptExtensions.split(',').map(e=>e.trim().toLowerCase()).filter(Boolean);
}
function matchExt(url, filename) {
  const exts = userExtList();
  if (filename && exts.includes(extFromName(filename))) return true;
  return exts.includes(extFromUrl(url));
}

// ── Cookies ───────────────────────────────────────────────────────────────────
async function getCookies(url) {
  try {
    const list = await chrome.cookies.getAll({url});
    return list.map(c=>`${c.name}=${c.value}`).join('; ');
  } catch { return ''; }
}

// ── Send to desktop app ───────────────────────────────────────────────────────
async function sendToApp(url, referer, cookies) {
  if (!url) return false;
  try {
    const body = JSON.stringify({url, referer:referer||'', cookies:cookies||'', source:'se-ext-mv3'});
    const r = await fetch(appUrl(), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body,
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    appConnected = true;
    console.log('[SE] Sent to app:', url.slice(0,80));
    if (cfg.showNotification) {
      let name = url;
      try {
        const u = new URL(url);
        name = u.searchParams.get('filename') ||
               decodeURIComponent(u.pathname.split('/').pop()) || url;
      } catch {}
      if (name.length > 70) name = name.slice(0,67)+'...';
      chrome.notifications.create('ok_'+Date.now(), {
        type:'basic', iconUrl:'icons/icon48.png',
        title:'SE Downloader', message:'✅ '+name,
      });
    }
    return true;
  } catch(e) {
    appConnected = false;
    console.error('[SE] sendToApp failed:', e.message || e);
    chrome.notifications.create('err_'+Date.now(), {
      type:'basic', iconUrl:'icons/icon48.png',
      title:'SE Downloader ⚠️',
      message:'Cannot connect — is SE Downloader running?',
    });
    return false;
  }
}

// ── WebRequest layer 1: record request info ───────────────────────────────────
chrome.webRequest.onBeforeRequest.addListener(
  d => {
    if (d.tabId < 0) return;
    const url = d.url;
    if (!url.startsWith('http')) return;
    reqMap.set(d.requestId, {url, finalUrl:url, tabId:d.tabId, referer:''});
    setTimeout(() => reqMap.delete(d.requestId), 60000);
  },
  {urls:['<all_urls>'], types:['main_frame','sub_frame','xmlhttprequest','media','object','other']}
);

// ── Layer 1b: record Referer ──────────────────────────────────────────────────
chrome.webRequest.onBeforeSendHeaders.addListener(
  d => {
    const req = reqMap.get(d.requestId);
    if (!req) return;
    const h = (d.requestHeaders||[]).find(h=>h.name.toLowerCase()==='referer');
    if (h) req.referer = h.value;
  },
  {urls:['<all_urls>']}, ['requestHeaders']
);

// ── Layer 2: track redirects ──────────────────────────────────────────────────
chrome.webRequest.onBeforeRedirect.addListener(
  d => {
    const req = reqMap.get(d.requestId);
    if (req && d.redirectUrl) req.finalUrl = d.redirectUrl;
  },
  {urls:['<all_urls>']}
);

// ── Layer 3: onHeadersReceived — judge and mark ───────────────────────────────
const SKIP_CT  = ['text/html','text/css','text/javascript','application/javascript',
                  'application/json','application/xml','text/xml','image/','font/'];
const DL_CT    = ['application/octet-stream','application/x-msdownload',
                  'application/download','application/force-download',
                  'binary/octet-stream','application/zip','application/x-7z-compressed',
                  'application/x-rar','application/x-rar-compressed','application/x-tar',
                  'application/gzip','application/x-gzip','application/x-msi',
                  'application/vnd.android.package-archive'];
const MEDIA_EXT= new Set(['mp4','mkv','avi','wmv','mov','flv','webm','3gp','mpg','mpeg',
                           'mp3','m4a','aac','ogg','wav','wma','flac','opus','torrent']);
const REDIR    = new Set([301,302,303,307,308]);

chrome.webRequest.onHeadersReceived.addListener(
  d => {
    if (!cfg.autoIntercept || !appConnected) return;
    const req = reqMap.get(d.requestId);
    if (!req) return;
    const status = parseInt((d.statusLine||'').split(' ')[1])||0;
    if (REDIR.has(status)) return;
    if (status !== 200 && status !== 206) return;

    const url  = req.finalUrl || req.url;
    const hdrs = d.responseHeaders || [];
    const getH = n => (hdrs.find(h=>h.name.toLowerCase()===n)||{}).value||'';

    const ct   = getH('content-type').split(';')[0].trim().toLowerCase();
    const cd   = getH('content-disposition');
    const cl   = parseInt(getH('content-length'))||0;
    const cr   = getH('content-range');

    let size = cl;
    if (cr) { const m = cr.match(/\/(\d+)$/); if (m) size = parseInt(m[1])||size; }

    const cdFile = parseCDFilename(cd);
    const cdType = cd.split(';')[0].trim().toLowerCase();
    const isAttach = cdType==='attachment' || (cdType==='inline' && !!cdFile);
    const bestExt  = cdFile ? extFromName(cdFile) : extFromUrl(url);

    const isPage   = SKIP_CT.some(p=>ct.startsWith(p));
    const isDlCt   = DL_CT.includes(ct);
    const isMedia  = MEDIA_EXT.has(bestExt) && size > 204800;
    const extMatch = bestExt && userExtList().includes(bestExt);
    const allDl    = cfg.interceptAllDownloads && !isPage && size > 0;

    if (!isAttach && !isDlCt && !isMedia && !extMatch && !allDl) return;

    // Mark for interception
    const now = Date.now();
    interceptQ.set(url, {referer:req.referer||'', tabId:d.tabId, ts:now});
    setTimeout(()=>interceptQ.delete(url), 10000);
    console.log('[SE] Marked for intercept:', url.slice(0,80), {isAttach,isDlCt,isMedia,extMatch});

    // Close blank tab opened just for the download
    const tabId = req.tabId||d.tabId;
    if (tabId > 0) {
      setTimeout(()=>{
        chrome.tabs.get(tabId, tab=>{
          if (chrome.runtime.lastError) return;
          if (tab && (tab.url===url||tab.url==='about:blank'||tab.url===''))
            chrome.tabs.remove(tabId);
        });
      }, 400);
    }
  },
  {urls:['<all_urls>']}, ['responseHeaders']
);

// ── Cleanup reqMap ────────────────────────────────────────────────────────────
chrome.webRequest.onCompleted   .addListener(d=>reqMap.delete(d.requestId), {urls:['<all_urls>']});
chrome.webRequest.onErrorOccurred.addListener(d=>reqMap.delete(d.requestId), {urls:['<all_urls>']});

// ── Layer 4: downloads.onCreated — actual cancel + send ──────────────────────
chrome.downloads.onCreated.addListener(async item => {
  if (!cfg.autoIntercept) return;
  if (handledDlIds.has(item.id)) return;
  await loadCfg();

  const url      = item.url      || '';
  const finalUrl = item.finalUrl || url;
  const filename = item.filename || '';
  const isBlob   = url.startsWith('blob:') || url.startsWith('data:');

  const queued = interceptQ.get(url) || interceptQ.get(finalUrl);
  const extOk  = !isBlob && matchExt(finalUrl||url, filename);

  if (!queued && !isBlob && !extOk) return;

  // Dedup
  const canon = finalUrl || url;
  const now = Date.now();
  if (sentUrls.has(canon) && now - sentUrls.get(canon) < 10000) {
    // Already sent, just cancel
    chrome.downloads.cancel(item.id);
    setTimeout(()=>chrome.downloads.erase({id:item.id}), 1000);
    return;
  }
  sentUrls.set(canon, now);
  setTimeout(()=>sentUrls.delete(canon), 10000);

  handledDlIds.add(item.id);
  chrome.downloads.cancel(item.id);
  console.log('[SE] Cancelled download, sending to app:', canon.slice(0,80));

  if (!appConnected) {
    console.log('[SE] App not connected, skipping send');
    handledDlIds.delete(item.id);
    // Fall back to browser download
    chrome.downloads.download({url});
    return;
  }

  const referer = queued?.referer || item.referrer || '';
  const cookies = await getCookies(canon);
  const ok = await sendToApp(canon, referer, cookies);

  if (!ok) {
    sentUrls.delete(canon);
    handledDlIds.delete(item.id);
    chrome.downloads.download({url});
  }

  setTimeout(()=>{
    chrome.downloads.erase({id:item.id});
    handledDlIds.delete(item.id);
  }, 1500);

  if (queued) { interceptQ.delete(url); interceptQ.delete(finalUrl); }
});

// ── Popup messages ────────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'check_connection') {
    checkConn().then(() => sendResponse({ok: appConnected}));
    return true;
  }
  if (msg.type === 'send_url') {
    const url = msg.url || '';
    (async () => {
      await loadCfg();
      const cookies = await getCookies(url);
      const ok = await sendToApp(url, msg.referer||'', cookies);
      sendResponse({ok});
    })();
    return true;
  }
  if (msg.type === 'get_config') {
    loadCfg().then(() => sendResponse({...cfg}));
    return true;
  }
});
