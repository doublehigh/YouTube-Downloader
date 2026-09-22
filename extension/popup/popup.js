// =========================================================
// Rhamify Studio — Extension Popup Logic (MV3)
// =========================================================

document.addEventListener("DOMContentLoaded", async () => {
  const DEFAULT_SERVER_URL = "http://127.0.0.1:5000";

  // Elements
  const btnToggleSettings = document.getElementById("btn-toggle-settings");
  const settingsPanel = document.getElementById("settings-panel");
  const serverUrlInput = document.getElementById("server-url-input");
  const btnSaveServer = document.getElementById("btn-save-server");
  const serverStatusDot = document.getElementById("server-status-dot");
  const serverStatusText = document.getElementById("server-status-text");

  const tabPlatformBadge = document.getElementById("tab-platform-badge");
  const tabTitle = document.getElementById("tab-title");
  const tabUrl = document.getElementById("tab-url");

  const tabOptVideo = document.getElementById("tab-opt-video");
  const tabOptAudio = document.getElementById("tab-opt-audio");
  const btnDownloadNow = document.getElementById("btn-download-now");
  const btnOpenStudio = document.getElementById("btn-open-studio");
  const popupToast = document.getElementById("popup-toast");

  let currentTab = null;
  let selectedMode = "video"; // 'video' or 'audio'
  let currentServerUrl = DEFAULT_SERVER_URL;

  // 1. Load Server Config
  try {
    const data = await chrome.storage.sync.get("rhamify_server_url");
    currentServerUrl = data.rhamify_server_url || DEFAULT_SERVER_URL;
    serverUrlInput.value = currentServerUrl;
    testServerConnection(currentServerUrl);
  } catch (err) {
    serverUrlInput.value = DEFAULT_SERVER_URL;
  }

  // 2. Query Active Tab
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    currentTab = tab;
    if (tab) {
      tabTitle.textContent = tab.title || "Untitled Tab";
      tabUrl.textContent = tab.url || "";
      const plat = detectPlatform(tab.url);
      if (plat) {
        tabPlatformBadge.textContent = `${plat.icon} ${plat.name}`;
      } else {
        tabPlatformBadge.textContent = "🌐 Online Video";
      }
    }
  } catch (err) {
    tabTitle.textContent = "Unable to read active tab";
  }

  // 3. Platform Detection
  function detectPlatform(url) {
    if (!url) return null;
    const u = url.toLowerCase();
    if (u.includes("youtube.com") || u.includes("youtu.be")) return { name: "YouTube", icon: "▶️" };
    if (u.includes("tiktok.com")) return { name: "TikTok", icon: "🎵" };
    if (u.includes("instagram.com")) return { name: "Instagram", icon: "📸" };
    if (u.includes("twitter.com") || u.includes("x.com")) return { name: "X / Twitter", icon: "🐦" };
    if (u.includes("facebook.com") || u.includes("fb.watch")) return { name: "Facebook", icon: "🔷" };
    if (u.includes("reddit.com")) return { name: "Reddit", icon: "🤖" };
    if (u.includes("vimeo.com")) return { name: "Vimeo", icon: "🎬" };
    if (u.includes("twitch.tv")) return { name: "Twitch", icon: "👾" };
    if (u.includes("soundcloud.com")) return { name: "SoundCloud", icon: "☁️" };
    if (u.includes("pinterest.com") || u.includes("pin.it")) return { name: "Pinterest", icon: "📌" };
    return null;
  }

  // 4. Test Server Connection
  async function testServerConnection(url) {
    serverStatusDot.className = "status-dot";
    serverStatusText.textContent = "Connecting...";
    try {
      const cleanUrl = url.replace(/\/+$/, "");
      const res = await fetch(`${cleanUrl}/api/system-status`, { signal: AbortSignal.timeout(3000) });
      if (res.ok) {
        serverStatusDot.className = "status-dot online";
        serverStatusText.textContent = "Connected to Rhamify Studio";
      } else {
        serverStatusDot.className = "status-dot offline";
        serverStatusText.textContent = "Server responded with error";
      }
    } catch {
      serverStatusDot.className = "status-dot offline";
      serverStatusText.textContent = "Server offline / check URL";
    }
  }

  // 5. Settings Toggle & Save
  btnToggleSettings.addEventListener("click", () => {
    const isHidden = settingsPanel.style.display === "none";
    settingsPanel.style.display = isHidden ? "flex" : "none";
  });

  btnSaveServer.addEventListener("click", async () => {
    let newUrl = serverUrlInput.value.trim().replace(/\/+$/, "");
    if (!newUrl) newUrl = DEFAULT_SERVER_URL;
    currentServerUrl = newUrl;
    await chrome.storage.sync.set({ "rhamify_server_url": newUrl });
    showToast("Server URL updated!");
    testServerConnection(newUrl);
  });

  // 6. Format Switcher
  tabOptVideo.addEventListener("click", () => {
    selectedMode = "video";
    tabOptVideo.classList.add("active");
    tabOptAudio.classList.remove("active");
    btnDownloadNow.innerHTML = "<span>⚡ Download Current Video (MP4)</span>";
  });

  tabOptAudio.addEventListener("click", () => {
    selectedMode = "audio";
    tabOptAudio.classList.add("active");
    tabOptVideo.classList.remove("active");
    btnDownloadNow.innerHTML = "<span>🎵 Download Current Audio (MP3)</span>";
  });

  // 7. Download Trigger
  btnDownloadNow.addEventListener("click", async () => {
    if (!currentTab || !currentTab.url) {
      showToast("No active URL to download", true);
      return;
    }

    const launchUrl = `${currentServerUrl}/?url=${encodeURIComponent(currentTab.url)}&autostart=1&mode=${selectedMode}`;
    chrome.tabs.create({ url: launchUrl });
    showToast("Launching download in Rhamify Studio...");
    setTimeout(() => window.close(), 800);
  });

  // 8. Open Studio Homepage
  btnOpenStudio.addEventListener("click", () => {
    chrome.tabs.create({ url: currentServerUrl });
    window.close();
  });

  function showToast(text, isError = false) {
    popupToast.textContent = text;
    popupToast.style.display = "block";
    popupToast.style.borderColor = isError ? "rgba(239, 68, 68, 0.4)" : "rgba(16, 185, 129, 0.4)";
    popupToast.style.color = isError ? "#f87171" : "#34d399";
    setTimeout(() => { popupToast.style.display = "none"; }, 2500);
  }
});
