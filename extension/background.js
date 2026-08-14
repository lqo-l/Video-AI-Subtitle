const API = "http://127.0.0.1:18765";
let nativePort = null;
const serviceLeases = new Set();
const UPDATE_API = "https://api.github.com/repos/lqo-l/Video-AI-Subtitle/releases/latest";
const UPDATE_CACHE_KEY = "ytbaExtensionUpdate";
const UPDATE_CACHE_MS = 6 * 60 * 60 * 1000;
const UPDATE_TIMEOUT_MS = 6000;

// Moon Begin: unpacked extensions cannot self-replace, but can safely direct users to a verified release.
function compareVersions(left, right) {
  const parse = value => String(value).replace(/^v/i, "").split(".").map(part => Number(part) || 0);
  const a = parse(left), b = parse(right);
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
    if ((a[index] || 0) !== (b[index] || 0)) return (a[index] || 0) > (b[index] || 0) ? 1 : -1;
  }
  return 0;
}

async function checkExtensionUpdate(force = false) {
  const currentVersion = chrome.runtime.getManifest().version;
  const cached = (await chrome.storage.local.get(UPDATE_CACHE_KEY))[UPDATE_CACHE_KEY];
  if (!force && cached?.currentVersion === currentVersion && Date.now() - cached.checkedAt < UPDATE_CACHE_MS) return cached;
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), UPDATE_TIMEOUT_MS);
    const response = await fetch(UPDATE_API, {headers: {Accept: "application/vnd.github+json"}, signal: controller.signal});
    clearTimeout(timeout);
    if (!response.ok) throw new Error(`GitHub ${response.status}`);
    const release = await response.json();
    const latestVersion = String(release.tag_name || "").replace(/^v/i, "");
    const result = {
      currentVersion, latestVersion, available: Boolean(latestVersion) && compareVersions(latestVersion, currentVersion) > 0,
      url: release.html_url || "https://github.com/lqo-l/Video-AI-Subtitle/releases/latest", checkedAt: Date.now(),
    };
    await chrome.storage.local.set({[UPDATE_CACHE_KEY]: result});
    return result;
  } catch (error) {
    return {...(cached || {}), currentVersion, available: false, error: "暂时无法检查更新", checkedAt: Date.now()};
  }
}
// Moon End

// Moon Begin: Chrome launches the registered local host only while work is active.
function serviceLeaseKey(message) {
  return String(message.leaseId || "");
}

function ensureService(sendResponse, message) {
  let answered = false;
  const leaseId = serviceLeaseKey(message);
  if (leaseId) serviceLeases.add(leaseId);
  if (!nativePort) {
    nativePort = chrome.runtime.connectNative("com.moon.youtube_bilingual_assistant");
    nativePort.onDisconnect.addListener(() => {
      nativePort = null;
      serviceLeases.clear();
      if (!answered) {
        answered = true;
        sendResponse({ok:false, error:chrome.runtime.lastError?.message || "本机启动器连接中断"});
      }
    });
  }
  const listener = response => {
    answered = true;
    nativePort?.onMessage.removeListener(listener);
    sendResponse(response);
  };
  nativePort.onMessage.addListener(listener);
  nativePort.postMessage({action: "start"});
}

function releaseService(message) {
  const leaseId = serviceLeaseKey(message);
  if (!leaseId) return;
  serviceLeases.delete(leaseId);
  // Moon Add: one completed tab must never terminate another tab's active translation.
  if (!serviceLeases.size) {
    nativePort?.disconnect();
    nativePort = null;
  }
}
// Moon End

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "ensure-service") {
    ensureService(sendResponse, message);
    return true;
  }
  if (message.type === "release-service") {
    releaseService(message);
    sendResponse({ok: true});
  }
  if (message.type === "notify") {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icon128.png",
      title: "视频 AI 双语字幕助手",
      message: message.message
    });
    sendResponse({ ok: true });
  }
  if (message.type === "download-markdown") {
    chrome.downloads.download({
      url: `data:text/markdown;charset=utf-8,${encodeURIComponent(message.content)}`,
      filename: `${message.filename || "video-summary"}.md`,
      saveAs: true
    });
    sendResponse({ ok: true });
  }
  if(message.type==="check-extension-update"){
    checkExtensionUpdate(Boolean(message.force)).then(sendResponse);
    return true;
  }
  return true;
});
