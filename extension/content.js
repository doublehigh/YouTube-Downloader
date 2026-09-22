// =========================================================
// Rhamify Studio — In-Page Content Script (MV3)
// Injects 1-Click Download Button directly on YouTube & Video pages
// =========================================================

(() => {
  // Prevent duplicate injection
  if (window.__rhamify_injected) return;
  window.__rhamify_injected = true;

  function injectYouTubeButton() {
    if (!window.location.href.includes("watch?v=") && !window.location.href.includes("/shorts/")) return;
    if (document.getElementById("rhamify-yt-download-btn")) return;

    // Target YouTube action buttons container
    const targetContainer = document.querySelector("#top-level-buttons-computed") || 
                            document.querySelector("#actions-inner #top-level-buttons") ||
                            document.querySelector("ytd-watch-metadata #actions");

    if (!targetContainer) return;

    const btn = document.createElement("button");
    btn.id = "rhamify-yt-download-btn";
    btn.type = "button";
    btn.title = "Download this video in high quality with Rhamify Studio";
    btn.innerHTML = `
      <span style="font-size: 15px; margin-right: 5px;">⚡</span>
      <span style="font-weight: 600; font-family: Roboto, Arial, sans-serif;">Rhamify</span>
    `;

    // Modern YouTube native-matching styles
    btn.style.cssText = `
      display: inline-flex;
      align-items: center;
      justify-content: center;
      height: 36px;
      padding: 0 16px;
      margin-left: 8px;
      background: linear-gradient(135deg, #a855f7 0%, #ff0033 100%);
      color: #ffffff;
      border: none;
      border-radius: 18px;
      font-size: 14px;
      cursor: pointer;
      box-shadow: 0 2px 10px rgba(255, 0, 51, 0.35);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
      z-index: 9999;
      vertical-align: middle;
    `;

    btn.addEventListener("mouseenter", () => {
      btn.style.transform = "scale(1.04)";
      btn.style.boxShadow = "0 4px 16px rgba(255, 0, 51, 0.55)";
    });

    btn.addEventListener("mouseleave", () => {
      btn.style.transform = "scale(1)";
      btn.style.boxShadow = "0 2px 10px rgba(255, 0, 51, 0.35)";
    });

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      chrome.runtime.sendMessage({
        type: "TRIGGER_DOWNLOAD",
        url: window.location.href,
        mode: "video"
      });
    });

    targetContainer.appendChild(btn);
  }

  // Periodic check / MutationObserver for YouTube SPA dynamic loads
  let checkInterval = setInterval(injectYouTubeButton, 1500);

  // Listen to YouTube's custom navigation events
  window.addEventListener("yt-navigate-finish", () => {
    setTimeout(injectYouTubeButton, 800);
  });

  // Cleanup on unload
  window.addEventListener("unload", () => {
    if (checkInterval) clearInterval(checkInterval);
  });
})();
