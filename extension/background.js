const API = "http://127.0.0.1:18765";
let nativePort = null;

async function fetchBilibiliSubtitles(url) {
  const parsed=new URL(url);
  const match=parsed.pathname.match(/\/(BV[0-9A-Za-z]+)/i);
  if(!match)return {segments:[]};
  const page=Math.max(1,Number(parsed.searchParams.get("p")||"1"));
  const view=await fetch(`https://api.bilibili.com/x/web-interface/view?bvid=${match[1]}`).then(response=>response.json());
  const cid=view?.data?.pages?.[page-1]?.cid || view?.data?.cid;
  if(!cid)return {segments:[]};
  const player=await fetch(`https://api.bilibili.com/x/player/v2?bvid=${match[1]}&cid=${cid}`).then(response=>response.json());
  const tracks=player?.data?.subtitle?.subtitles||[];
  const supported=tracks.find(track=>/^(en|ai-en)/i.test(track.lan))||tracks.find(track=>/^(ja|jp|ai-ja|ai-jp)/i.test(track.lan))||tracks.find(track=>/^(zh|cn|ai-zh|ai-cn)/i.test(track.lan));
  if(!supported?.subtitle_url)return {segments:[]};
  const subtitleUrl=supported.subtitle_url.startsWith("//")?`https:${supported.subtitle_url}`:supported.subtitle_url;
  const subtitle=await fetch(subtitleUrl).then(response=>response.json());
  const language=/^(en|ai-en)/i.test(supported.lan)?"en":/^(ja|jp|ai-ja|ai-jp)/i.test(supported.lan)?"ja":"zh";
  return {language,segments:(subtitle.body||[]).filter(item=>item.content?.trim()).map(item=>({start:item.from,end:item.to,en:item.content.trim(),source_language:language}))};
}

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
    fetchBilibiliSubtitles(message.url).then(sendResponse).catch(error=>sendResponse({segments:[],error:error.message}));
    return true;
  }
  return true;
});
