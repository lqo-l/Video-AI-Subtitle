const API = "http://127.0.0.1:18765";
let nativePort = null;
const serviceLeases = new Set();
const UPDATE_API = "https://api.github.com/repos/lqo-l/Video-AI-Subtitle/releases/latest";
const UPDATE_CACHE_KEY = "ytbaExtensionUpdate";
const UPDATE_PROGRESS_KEY = "ytbaExtensionUpdateProgress";
const UPDATE_CACHE_MS = 6 * 60 * 60 * 1000;
const UPDATE_TIMEOUT_MS = 6000;

// Moon Begin: GitHub release discovery and a native-host mediated unpacked update.
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
    const asset = Array.isArray(release.assets)
      ? release.assets.find(item => item?.name === "youtube-bilingual-assistant.zip")
      : null;
    const result = {
      currentVersion, latestVersion, available: Boolean(latestVersion) && compareVersions(latestVersion, currentVersion) > 0,
      url: release.html_url || "https://github.com/lqo-l/Video-AI-Subtitle/releases/latest", checkedAt: Date.now(),
      assetUrl: asset?.browser_download_url || "",
      assetDigest: asset?.digest || "",
    };
    await chrome.storage.local.set({[UPDATE_CACHE_KEY]: result});
    return result;
  } catch (error) {
    return {...(cached || {}), currentVersion, available: false, error: "暂时无法检查更新", checkedAt: Date.now()};
  }
}

function installExtensionUpdate(update) {
  if (serviceLeases.size) return Promise.resolve({ok: false, error: "仍有视频任务在运行，请完成或取消后再更新"});
  if (!update?.available || !update.assetUrl) return Promise.resolve({ok: false, error: "未找到可安装的更新包"});
  return new Promise(resolve => {
    const port = chrome.runtime.connectNative("com.moon.youtube_bilingual_assistant");
    let replied = false;
    const finish = response => {
      if (replied) return;
      replied = true;
      try { port.disconnect(); } catch (_) {}
      resolve(response);
    };
    chrome.storage.local.set({[UPDATE_PROGRESS_KEY]: {state: "running", stage: "正在连接更新服务器", downloaded: 0, total: 0, speed: 0}});
    port.onMessage.addListener(response => {
      if (response?.progress) {
        chrome.storage.local.set({[UPDATE_PROGRESS_KEY]: {state: "running", ...response}});
        return;
      }
      chrome.storage.local.set({[UPDATE_PROGRESS_KEY]: {state: response?.ok ? "completed" : "failed", ...response}});
      finish(response);
    });
    port.onDisconnect.addListener(() => finish({ok: false, error: chrome.runtime.lastError?.message || "本机更新器连接中断"}));
    port.postMessage({action: "update", url: update.assetUrl, digest: update.assetDigest, version: update.latestVersion, extensionId: chrome.runtime.id});
  });
}
// Moon End

// Moon Begin: resolve Bilibili captions from the URL-authoritative resource API.
// Never use a live player object or a recent network request as the source of a
// CID: both can remain from the previous SPA video/part after navigation.
function bilibiliCaptionLanguage(value) {
  const language = String(value || "").toLowerCase();
  if (/^(en|ai-en)/.test(language)) return "en";
  if (/^(ja|jp|ai-ja|ai-jp)/.test(language)) return "ja";
  if (/^(zh|cn|ai-zh|ai-cn)/.test(language)) return "zh";
  return null;
}

function cleanBilibiliCaption(content) {
  return String(content || "").trim()
    .replace(/^(?:\.{3,}|…{2,})\s*/, "")
    .replace(/\s*(?:\.{3,}|…{2,})$/, "")
    .trim();
}

async function fetchBilibiliJson(url) {
  // Moon Add: some Bilibili AI-generated tracks are exposed only to the
  // currently signed-in browser session. Keep credentials inside Chrome; never
  // read, store, or transmit SESSDATA ourselves.
  const response = await fetch(url, {cache: "no-store", credentials: "include"});
  if (!response.ok) throw new Error(`B站接口 ${response.status}`);
  const payload = await response.json();
  if (Number(payload?.code || 0) !== 0) throw new Error(payload?.message || "B站接口返回失败");
  return payload.data;
}

async function resolveBilibiliUrlResource(rawUrl) {
  const url = new URL(rawUrl);
  const bvid = url.pathname.match(/\/video\/(BV[0-9A-Za-z]+)/i)?.[1];
  const aid = url.pathname.match(/\/video\/av(\d+)/i)?.[1];
  if (bvid || aid) {
    const resourceQuery = bvid ? `bvid=${encodeURIComponent(bvid)}` : `aid=${encodeURIComponent(aid)}`;
    const view = await fetchBilibiliJson(`https://api.bilibili.com/x/web-interface/view?${resourceQuery}`);
    const part = Math.max(1, Number.parseInt(url.searchParams.get("p") || "1", 10) || 1);
    const page = view?.pages?.[part - 1];
    if (!Number.isSafeInteger(Number(page?.cid)) || Number(page.cid) <= 0) {
      throw new Error("无法从当前链接确认 B 站视频分 P");
    }
    if (!view?.bvid) throw new Error("无法确认 B 站视频资源");
    return {bvid: view.bvid, cid: Number(page.cid), duration: Number(page.duration || view.duration || 0)};
  }

  const epId = url.pathname.match(/\/bangumi\/play\/ep(\d+)/i)?.[1];
  if (epId) {
    const season = await fetchBilibiliJson(`https://api.bilibili.com/pgc/view/web/season?ep_id=${encodeURIComponent(epId)}`);
    const episode = (season?.episodes || []).find(item => String(item?.id) === epId);
    if (!episode?.bvid || !Number.isSafeInteger(Number(episode.cid)) || Number(episode.cid) <= 0) {
      throw new Error("无法从当前番剧链接确认视频资源");
    }
    return {bvid: episode.bvid, cid: Number(episode.cid), duration: Number(episode.duration || 0) / 1000};
  }
  throw new Error("不支持的 B 站视频链接");
}

async function fetchBilibiliSubtitles(rawUrl) {
  const resource = await resolveBilibiliUrlResource(rawUrl);
  const player = await fetchBilibiliJson(
    `https://api.bilibili.com/x/player/v2?bvid=${encodeURIComponent(resource.bvid)}&cid=${resource.cid}`
  );
  const tracks = Array.isArray(player?.subtitle?.subtitles) ? player.subtitle.subtitles : [];
  const ranked = tracks.map(track => ({track, language: bilibiliCaptionLanguage(track?.lan)}))
    .filter(item => item.language && item.track?.subtitle_url)
    .sort((left, right) => ["en", "ja", "zh"].indexOf(left.language) - ["en", "ja", "zh"].indexOf(right.language));
  const selected = ranked[0];
  if (!selected) return {segments: [], identity: resource};

  const subtitleUrl = selected.track.subtitle_url.startsWith("//")
    ? `https:${selected.track.subtitle_url}` : selected.track.subtitle_url;
  const response = await fetch(subtitleUrl, {cache: "no-store", credentials: "include"});
  if (!response.ok) throw new Error(`B站字幕文件 ${response.status}`);
  const subtitle = await response.json();
  const segments = (Array.isArray(subtitle?.body) ? subtitle.body : [])
    .filter(item => Number.isFinite(item?.from) && Number.isFinite(item?.to) && item.to > item.from)
    .map(item => ({start: item.from, end: item.to, en: cleanBilibiliCaption(item.content), source_language: selected.language}))
    .filter(item => item.en);

  // A valid track should cover a meaningful part of the URL-authoritative resource.
  const endTime = Math.max(0, ...segments.map(item => item.end));
  const duration = resource.duration;
  const minimumCoverage = Math.min(60, duration * .55);
  const maximumCoverage = duration + Math.max(15, duration * .05);
  if (!segments.length || (duration > 0 && (endTime < minimumCoverage || endTime > maximumCoverage))) {
    return {segments: [], identity: resource};
  }
  return {segments, language: selected.language, identity: resource};
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
  if (message.type === "fetch-bilibili-subtitles") {
    fetchBilibiliSubtitles(message.url).then(sendResponse).catch(error => sendResponse({segments: [], error: error.message}));
    return true;
  }
  if(message.type==="check-extension-update"){
    checkExtensionUpdate(Boolean(message.force)).then(sendResponse);
    return true;
  }
  if(message.type==="install-extension-update"){
    installExtensionUpdate(message.update).then(sendResponse);
    return true;
  }
  return true;
});
