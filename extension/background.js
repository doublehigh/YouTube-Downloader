// =========================================================
// Rhamify Studio — Extension Background Service Worker (MV3)
// =========================================================

const DEFAULT_SERVER_URL = "http://127.0.0.1:5000";

// Helper to get configured server URL (NOT hardcoded — user can change in popup)
async function getServerUrl() {
  try {
    const data = await chrome.storage.sync.get("rhamify_server_url");
    let url = data.rhamify_server_url || DEFAULT_SERVER_URL;
    return url.replace(/\/+$/, ""); // remove trailing slash
  } catch {
    return DEFAULT_SERVER_URL;
  }
}

// Setup Context Menus on installation
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "rhamify-download-target",
      title: "⚡ Download with Rhamify Studio",
      contexts: ["link", "video", "audio"]
    });

    chrome.contextMenus.create({
      id: "rhamify-download-page",
      title: "⚡ Download Video on this Page",
      contexts: ["page"]
    });
  });
});

// Handle Context Menu Clicks
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const targetUrl = info.linkUrl || info.srcUrl || info.pageUrl || (tab && tab.url);
  if (!targetUrl) return;

  const serverUrl = await getServerUrl();
  const launchUrl = `${serverUrl}/?url=${encodeURIComponent(targetUrl)}&autostart=1`;

  // Open in new tab next to current tab
  chrome.tabs.create({
    url: launchUrl,
    index: tab ? tab.index + 1 : undefined
  });
});

// Handle Messages from Content Scripts or Popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    try {
      if (message.type === "GET_SERVER_URL") {
        const serverUrl = await getServerUrl();
        sendResponse({ serverUrl });
      } else if (message.type === "SET_SERVER_URL") {
        const newUrl = (message.serverUrl || "").trim().replace(/\/+$/, "");
        if (newUrl) {
          await chrome.storage.sync.set({ "rhamify_server_url": newUrl });
          sendResponse({ success: true, serverUrl: newUrl });
        } else {
          sendResponse({ success: false, error: "Invalid URL" });
        }
      } else if (message.type === "TRIGGER_DOWNLOAD") {
        const serverUrl = await getServerUrl();
        const targetUrl = message.url || (sender.tab && sender.tab.url);
        if (!targetUrl) {
          sendResponse({ success: false, error: "No URL provided" });
          return;
        }

        const mode = message.mode || "video";
        const formatParam = mode === "audio" ? "&mode=audio" : "";
        const launchUrl = `${serverUrl}/?url=${encodeURIComponent(targetUrl)}&autostart=1${formatParam}`;

        chrome.tabs.create({
          url: launchUrl,
          index: sender.tab ? sender.tab.index + 1 : undefined
        });

        sendResponse({ success: true });
      }
    } catch (err) {
      sendResponse({ success: false, error: err.message });
    }
  })();
  return true; // Keep channel open for async response
});
