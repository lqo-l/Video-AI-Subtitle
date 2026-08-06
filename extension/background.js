const API = "http://127.0.0.1:18765";
let nativePort = null;

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
  return true;
});
