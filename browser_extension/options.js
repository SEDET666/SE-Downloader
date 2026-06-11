// SE Downloader Options Page — no inline scripts (CSP compliant)

const DEFAULTS = {
  appPort: 26339,
  autoIntercept: true,
  showNotification: true,
  interceptAllDownloads: false,
  interceptExtensions: "zip,rar,7z,tar,gz,bz2,xz,exe,msi,dmg,pkg,iso,mp4,mp3,mkv,avi,mov,wmv,flac,wav,aac,ogg,pdf,apk,torrent,bin,img,deb,rpm,jar",
};

let cfg = { ...DEFAULTS };

// ── Load settings ─────────────────────────────────────────────────────────────
chrome.storage.sync.get(DEFAULTS, saved => {
  cfg = { ...DEFAULTS, ...saved };
  document.getElementById("appPort").value = cfg.appPort;
  document.getElementById("interceptExtensions").value = cfg.interceptExtensions;
  setTog("tog-auto",  cfg.autoIntercept);
  setTog("tog-all",   cfg.interceptAllDownloads);
  setTog("tog-notif", cfg.showNotification);
});

// ── Bind events ───────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("tog-auto") .addEventListener("click", function() { togKey("autoIntercept",         this); });
  document.getElementById("tog-all")  .addEventListener("click", function() { togKey("interceptAllDownloads", this); });
  document.getElementById("tog-notif").addEventListener("click", function() { togKey("showNotification",       this); });
  document.getElementById("saveBtn")  .addEventListener("click", save);
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function setTog(id, v) {
  const el = document.getElementById(id);
  if (el) el.className = "toggle" + (v ? " on" : "");
}

function togKey(key, btn) {
  cfg[key] = !cfg[key];
  btn.className = "toggle" + (cfg[key] ? " on" : "");
}

function save() {
  cfg.appPort = parseInt(document.getElementById("appPort").value) || 26339;
  cfg.interceptExtensions = document.getElementById("interceptExtensions").value.trim();
  chrome.storage.sync.set(cfg, () => {
    const msg = document.getElementById("savedMsg");
    msg.style.display = "inline";
    setTimeout(() => { msg.style.display = "none"; }, 2000);
  });
}
