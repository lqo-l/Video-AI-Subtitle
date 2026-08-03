const API = "http://127.0.0.1:8765";

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "notify") {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icon128.png",
      title: "YouTube 双语字幕助手",
      message: message.message
    });
    sendResponse({ ok: true });
  }
  if (message.type === "download-markdown") {
    chrome.downloads.download({
      url: `${API}/jobs/${message.jobId}/markdown`,
      filename: `${message.filename || "youtube-summary"}.md`,
      saveAs: true
    });
    sendResponse({ ok: true });
  }
  return true;
});
