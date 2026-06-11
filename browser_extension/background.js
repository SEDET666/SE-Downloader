/**
 * SE Downloader Extension - Manifest V3 Service Worker
 *
 * MV3 核心差异：
 * - webRequest blocking 已移除 → 用 downloads.onCreated + cancel()
 * - XMLHttpRequest 不可用 → 用 fetch()
 * - Service Worker 随时被终止 → 关键状态用 chrome.storage.session
 * - 全局变量在 SW 重启后丢失 → 每次使用前从 storage 读取
 *
 * 拦截流程：
 * 1. webRequest.onBeforeRequest (observer, 不能 cancel) → 收集请求信息
 * 2. webRequest.onBeforeSendHeaders → 收集 Referer
 * 3. webRequest.onBeforeRedirect → 追踪重定向目标 URL
 * 4. webRequest.onHeadersReceived (observer) → 分析响应头，标记需要拦截的 URL
 * 5. downloads.onCreated → 根据标记决定是否 cancel 并发给应用
 */

// ── 默认配置 ──────────────────────────────────────────────────────────────────
const DEFAULTS = {
  appPort: 26339,
  autoIntercept: true,
  interceptAllDownloads: false,
  interceptExtensions: "zip,rar,7z,tar,gz,bz2,xz,exe,msi,dmg,pkg,iso,mp4,mp3,mkv,avi,mov,wmv,flac,wav,aac,ogg,pdf,apk,torrent,bin,img,deb,rpm,jar,war,nupkg,crx",
  showNotification: true,
};

// ── 配置缓存（SW 重启后会重新从 storage 加载）───────────────────────────────
let cfg = { ...DEFAULTS };

async function loadCfg() {
  const saved = await chrome.storage.sync.get(DEFAULTS);
  cfg = { ...DEFAULTS, ...saved };
}

// 启动时加载配置
loadCfg();

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "sync") {
    for (const [k, { newValue }] of Object.entries(changes)) {
      cfg[k] = newValue;
    }
  }
});

// ── 连接状态（用 session storage 跨 SW 生命周期缓存）──────────────────────────
let appConnected = false;

async function checkConn() {
  try {
    // no-cors: response is opaque but if fetch succeeds, server is running
    await fetch(`http://127.0.0.1:${cfg.appPort}`, {
      method: "GET",
      mode: "no-cors",
      signal: AbortSignal.timeout(5000),
    });
    appConnected = true;
  } catch {
    appConnected = false;
  }
}

// SW 激活时检查
checkConn();
// 定期检查（alarm API，MV3 service worker 安全方式）
chrome.alarms.create("connCheck", { periodInMinutes: 0.1 }); // ~6s
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === "connCheck") checkConn();
});

// ── 请求信息表（requestId → meta）────────────────────────────────────────────
// MV3 service worker 可能被终止，这里只用于单次请求生命周期内
const reqMap = new Map();   // requestId → { url, finalUrl, tabId, referer }

// 已标记为需要拦截的 URL（由 onHeadersReceived 写入）
// key: url, value: { referer, cookies, ts }
const interceptQueue = new Map();

// 已发往应用的 URL（防重复 10s）
const sentUrls = new Map();

function cleanSentUrls() {
  const now = Date.now();
  for (const [url, ts] of sentUrls) {
    if (now - ts > 10000) sentUrls.delete(url);
  }
}

// ── Content-Type 判断 ─────────────────────────────────────────────────────────
const SKIP_CT = [
  "text/html", "text/css", "text/javascript", "application/javascript",
  "application/json", "application/xml", "text/xml",
  "image/", "font/", "audio/", "video/",  // allow media through unless CD:attachment
];

const DOWNLOAD_CT = [
  "application/octet-stream", "application/x-msdownload",
  "application/x-apple-diskimage", "application/download",
  "application/force-download", "binary/octet-stream",
  "application/zip", "application/x-7z-compressed",
  "application/x-rar", "application/x-rar-compressed",
  "application/x-tar", "application/gzip", "application/x-gzip",
  "application/x-msi", "application/pdf",
  "application/java-archive", "application/vnd.android.package-archive",
];

const MEDIA_EXT = new Set([
  "mp4","m4v","mkv","avi","wmv","mov","flv","webm","3gp","mpg","mpeg",
  "mp3","m4a","aac","ogg","wav","wma","flac","opus",
  "torrent",
]);

const REDIRECT_CODES = new Set([301, 302, 303, 307, 308]);

// ── 工具函数 ──────────────────────────────────────────────────────────────────

function extFromUrl(url) {
  try {
    const u = new URL(url);
    for (const k of ["filename","fn","name","file"]) {
      const v = u.searchParams.get(k);
      if (v) { const e = extFromName(v); if (e) return e; }
    }
    return extFromName(decodeURIComponent(u.pathname.split("/").pop() || ""));
  } catch { return ""; }
}

function extFromName(name) {
  if (!name) return "";
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).split("?")[0].toLowerCase() : "";
}

function parseCDFilename(cd) {
  if (!cd) return "";
  let m = cd.match(/filename\*\s*=\s*([^'\s;]+)''\s*([^\s;]+)/i);
  if (m) { try { return decodeURIComponent(m[2]); } catch {} }
  m = cd.match(/filename\s*=\s*"([^"]+)"/i);
  if (m) return m[1].trim();
  m = cd.match(/filename\s*=\s*([^\s;]+)/i);
  if (m) return m[1].trim().replace(/^['"]|['"]$/g, "");
  return "";
}

function userExtList() {
  return cfg.interceptExtensions
    .split(",").map(e => e.trim().toLowerCase()).filter(Boolean);
}

function matchesUserExt(url, filename) {
  const exts = userExtList();
  if (filename) {
    const e = extFromName(filename);
    if (e && exts.includes(e)) return true;
  }
  const e = extFromUrl(url);
  return e && exts.includes(e);
}

async function getCookies(url) {
  try {
    const list = await chrome.cookies.getAll({ url });
    return list.map(c => `${c.name}=${c.value}`).join("; ");
  } catch { return ""; }
}

// ── HTTP 请求到本地应用 ────────────────────────────────────────────────────────
async function sendToApp(url, referer, cookies) {
  if (!url) return false;
  try {
    // Use no-cors to bypass CORS preflight — service worker to localhost
    // no-cors means response is opaque (can't read body), but POST still delivers
    await fetch(`http://127.0.0.1:${cfg.appPort}`, {
      method: "POST",
      mode: "no-cors",
      body: JSON.stringify({ url, referer: referer || "", cookies: cookies || "", source: "se-ext-mv3" }),
      signal: AbortSignal.timeout(8000),
    });
    appConnected = true;

    if (cfg.showNotification) {
      let name = url;
      try {
        const u = new URL(url);
        name = u.searchParams.get("filename") ||
               decodeURIComponent(u.pathname.split("/").pop()) || url;
      } catch {}
      if (name.length > 70) name = name.slice(0, 67) + "...";
      chrome.notifications.create("ok_" + Date.now(), {
        type: "basic", iconUrl: "icons/icon48.png",
        title: "SE Downloader", message: "✅ " + name,
      });
    }
    return true;
  } catch {
    appConnected = false;
    chrome.notifications.create("err_" + Date.now(), {
      type: "basic", iconUrl: "icons/icon48.png",
      title: "SE Downloader ⚠️", message: "Cannot connect to SE Downloader app",
    });
    return false;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Layer 1: onBeforeRequest — 记录请求（不能 blocking cancel in MV3 non-DNR）
// ═══════════════════════════════════════════════════════════════════════════════
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (details.tabId < 0) return;
    const url = details.url;
    if (!url.startsWith("http://") && !url.startsWith("https://")) return;
    reqMap.set(details.requestId, {
      url,
      finalUrl: url,
      tabId:  details.tabId,
      referer: "",
    });
    setTimeout(() => reqMap.delete(details.requestId), 60000);
  },
  { urls: ["<all_urls>"], types: ["main_frame","sub_frame","xmlhttprequest","media","object","other"] }
);

// ── Layer 1b: 记录 Referer ────────────────────────────────────────────────────
chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    const req = reqMap.get(details.requestId);
    if (!req) return;
    const h = (details.requestHeaders || []).find(h => h.name.toLowerCase() === "referer");
    if (h) req.referer = h.value;
  },
  { urls: ["<all_urls>"] },
  ["requestHeaders"]
);

// ── Layer 2: 追踪重定向 ────────────────────────────────────────────────────────
chrome.webRequest.onBeforeRedirect.addListener(
  (details) => {
    const req = reqMap.get(details.requestId);
    if (req && details.redirectUrl) req.finalUrl = details.redirectUrl;
  },
  { urls: ["<all_urls>"] }
);

// ═══════════════════════════════════════════════════════════════════════════════
// Layer 3: onHeadersReceived — 分析响应头，标记需要拦截的 URL
// MV3 中此处不能 cancel，只能记录
// ═══════════════════════════════════════════════════════════════════════════════
chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (!cfg.autoIntercept || !appConnected) return;

    const req = reqMap.get(details.requestId);
    if (!req) return;

    const status = parseInt((details.statusLine || "").split(" ")[1]) || 0;
    if (REDIRECT_CODES.has(status)) return;
    if (status !== 200 && status !== 206) return;

    const url   = req.finalUrl || req.url;
    const hdrs  = details.responseHeaders || [];
    const getH  = n => { const h = hdrs.find(h => h.name.toLowerCase() === n); return h ? h.value : ""; };

    const rawCT = getH("content-type");
    const rawCD = getH("content-disposition");
    const rawCL = getH("content-length");
    const rawCR = getH("content-range");

    const ct = rawCT.split(";")[0].trim().toLowerCase();
    const cdFilename = parseCDFilename(rawCD);
    const cdType = rawCD.split(";")[0].trim().toLowerCase();
    const isAttachment = cdType === "attachment" || (cdType === "inline" && !!cdFilename);

    let fileSize = parseInt(rawCL) || 0;
    if (rawCR) { const m = rawCR.match(/\/(\d+)$/); if (m) fileSize = parseInt(m[1]) || fileSize; }

    const urlExt  = extFromUrl(url);
    const bestExt = cdFilename ? extFromName(cdFilename) : urlExt;

    const isPageCt = SKIP_CT.some(p => ct.startsWith(p));
    const isDownloadCt = DOWNLOAD_CT.some(p => ct === p);
    const isMediaExt = MEDIA_EXT.has(bestExt) && fileSize > 204800;
    const extMatch = bestExt && userExtList().includes(bestExt);
    const allDownloads = cfg.interceptAllDownloads && !isPageCt && fileSize > 0;

    const shouldIntercept = isAttachment || isDownloadCt || extMatch || isMediaExt || allDownloads;
    if (!shouldIntercept) return;

    // 标记此 URL — downloads.onCreated 将据此 cancel
    interceptQueue.set(url, {
      referer: req.referer || "",
      tabId:   details.tabId,
      ts:      Date.now(),
    });
    // 10s 后清理
    setTimeout(() => interceptQueue.delete(url), 10000);

    // 关闭空白下载跳转 tab
    const tabId = req.tabId || details.tabId;
    if (tabId > 0) {
      setTimeout(() => {
        chrome.tabs.get(tabId, tab => {
          if (chrome.runtime.lastError) return;
          if (tab && (tab.url === url || tab.url === "about:blank" || tab.url === "")) {
            chrome.tabs.remove(tabId);
          }
        });
      }, 400);
    }
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);

// ── 清理 reqMap ───────────────────────────────────────────────────────────────
chrome.webRequest.onCompleted.addListener(
  d => reqMap.delete(d.requestId),
  { urls: ["<all_urls>"] }
);
chrome.webRequest.onErrorOccurred.addListener(
  d => reqMap.delete(d.requestId),
  { urls: ["<all_urls>"] }
);

// ═══════════════════════════════════════════════════════════════════════════════
// Layer 4: downloads.onCreated — 实际 cancel 并发给应用
// ═══════════════════════════════════════════════════════════════════════════════
const handledDlIds = new Set();

chrome.downloads.onCreated.addListener(async (item) => {
  if (!cfg.autoIntercept || !appConnected) return;
  if (handledDlIds.has(item.id)) return;

  await loadCfg(); // ensure cfg is fresh after SW restart

  const url      = item.url || "";
  const finalUrl = item.finalUrl || url;
  const filename = item.filename || "";

  // Check if flagged by onHeadersReceived
  const queued = interceptQueue.get(url) || interceptQueue.get(finalUrl);
  const isBlob  = url.startsWith("blob:") || url.startsWith("data:");
  const extOk   = matchesUserExt(finalUrl || url, filename);

  if (!queued && !isBlob && !extOk) return;

  cleanSentUrls();
  const canonUrl = finalUrl || url;
  if (sentUrls.has(canonUrl)) {
    // Already sent — just cancel the download
    handledDlIds.add(item.id);
    chrome.downloads.cancel(item.id);
    setTimeout(() => { chrome.downloads.erase({ id: item.id }); handledDlIds.delete(item.id); }, 1500);
    return;
  }
  sentUrls.set(canonUrl, Date.now());

  handledDlIds.add(item.id);
  chrome.downloads.cancel(item.id);

  const referer = queued ? queued.referer : (item.referrer || "");
  const cookies = await getCookies(canonUrl);

  const ok = await sendToApp(canonUrl, referer, cookies);
  if (!ok) {
    sentUrls.delete(canonUrl);
    handledDlIds.delete(item.id);
    chrome.downloads.download({ url });
  }
  setTimeout(() => {
    chrome.downloads.erase({ id: item.id });
    handledDlIds.delete(item.id);
  }, 1500);

  if (queued) interceptQueue.delete(url); 
});

// ── 右键菜单 ──────────────────────────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "se-link",  title: "🔽 SE Downloader: Download Link",  contexts: ["link"]           });
    chrome.contextMenus.create({ id: "se-image", title: "🔽 SE Downloader: Download Image", contexts: ["image"]          });
    chrome.contextMenus.create({ id: "se-media", title: "🔽 SE Downloader: Download Media", contexts: ["video","audio"]  });
    chrome.contextMenus.create({ id: "se-page",  title: "🔽 SE Downloader: Download Page",  contexts: ["page"]           });
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const url = info.linkUrl || info.srcUrl || info.pageUrl || "";
  if (!url) return;
  const referer = tab ? tab.url : "";
  const cookies = await getCookies(url);
  sendToApp(url, referer, cookies);
});

// ── popup 消息 ────────────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "check_connection") {
    fetch(`http://127.0.0.1:${cfg.appPort}`, {
      mode: "no-cors",
      signal: AbortSignal.timeout(5000),
    })
      .then(() => { appConnected = true;  sendResponse({ ok: true  }); })
      .catch(() => { appConnected = false; sendResponse({ ok: false }); });
    return true;
  }

  if (msg.type === "send_url") {
    const url = msg.url || "";
    getCookies(url).then(cookies =>
      sendToApp(url, msg.referer || "", cookies).then(ok => sendResponse({ ok }))
    );
    return true;
  }

  if (msg.type === "get_config") {
    sendResponse({ ...cfg });
    return false;
  }
});
