const API = "http://127.0.0.1:18765";
let nativePort = null;
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

// Moon Add: Bilibili subtitle tracks sometimes place continuation dots at a cue boundary.
function cleanBilibiliCaption(content) {
  return String(content || "").trim()
    .replace(/^(?:\.{3,}|…{2,})\s*/, "")
    .replace(/\s*(?:\.{3,}|…{2,})$/, "")
    .trim();
}

// Moon Begin: only accept the CID reported by the page's current player. URL p can be stale after Bilibili SPA navigation.
async function fetchBilibiliSubtitles(identity) {
  const bvid=String(identity?.bvid||"").trim();
  const cid=Number(identity?.cid);
  if(!/^BV[0-9A-Za-z]+$/i.test(bvid)||!Number.isSafeInteger(cid)||cid<=0)return {segments:[]};
  // Moon Begin: a stale player request can return a subtitle URL for another video.
  // Verify the live CID belongs to the URL's BVID and retain duration for subtitle coverage validation.
  const view=await fetch(`https://api.bilibili.com/x/web-interface/view?bvid=${encodeURIComponent(bvid)}`).then(response=>response.json());
  const pages=view?.data?.pages||[];
  const currentPage=pages.find(page=>Number(page?.cid)===cid);
  const duration=Number(currentPage?.duration||view?.data?.duration||0);
  if(!currentPage||!Number.isFinite(duration)||duration<=0)return {segments:[]};
  const player=await fetch(`https://api.bilibili.com/x/player/v2?bvid=${encodeURIComponent(bvid)}&cid=${cid}`).then(response=>response.json());
  const tracks=player?.data?.subtitle?.subtitles||[];
  const supported=tracks.find(track=>/^(en|ai-en)/i.test(track.lan))||tracks.find(track=>/^(ja|jp|ai-ja|ai-jp)/i.test(track.lan))||tracks.find(track=>/^(zh|cn|ai-zh|ai-cn)/i.test(track.lan));
  if(!supported?.subtitle_url)return {segments:[]};
  const subtitleUrl=supported.subtitle_url.startsWith("//")?`https:${supported.subtitle_url}`:supported.subtitle_url;
  const subtitle=await fetch(subtitleUrl).then(response=>response.json());
  const language=/^(en|ai-en)/i.test(supported.lan)?"en":/^(ja|jp|ai-ja|ai-jp)/i.test(supported.lan)?"ja":"zh";
  const segments=(subtitle.body||[])
    .filter(item=>Number.isFinite(item.from)&&Number.isFinite(item.to)&&item.to>item.from)
    .map(item=>({start:item.from,end:item.to,en:cleanBilibiliCaption(item.content),source_language:language}))
    .filter(item=>item.en);
  const endTime=Math.max(0,...segments.map(item=>item.end));
  // A 3-minute subtitle track for a 9-minute video is overwhelmingly likely to be stale player data.
  if(!segments.length||endTime<Math.min(60,duration*.55))return {segments:[]};
  return {language,segments,duration};
}
// Moon End

// Moon Begin: Chrome launches the registered local host only while work is active.
function ensureService(sendResponse) {
  let answered = false;
  if (!nativePort) {
    nativePort = chrome.runtime.connectNative("com.moon.youtube_bilingual_assistant");
    nativePort.onDisconnect.addListener(() => {
      nativePort = null;
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
// Moon End

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "ensure-service") {
    ensureService(sendResponse);
    return true;
  }
  if (message.type === "release-service") {
    nativePort?.disconnect();
    nativePort = null;
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
  if(message.type==="fetch-bilibili-subtitles"){
    fetchBilibiliSubtitles(message.identity).then(sendResponse).catch(error=>sendResponse({segments:[],error:error.message}));
    return true;
  }
  if(message.type==="check-extension-update"){
    checkExtensionUpdate(Boolean(message.force)).then(sendResponse);
    return true;
  }
  return true;
});
