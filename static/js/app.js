// =========================================================
// YouTube Downloader Studio — Frontend Application Logic
// =========================================================

document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const urlInput = document.getElementById('url-input');
  const btnPaste = document.getElementById('btn-paste');
  const btnInspect = document.getElementById('btn-inspect');
  const btnSpinner = btnInspect.querySelector('.btn-spinner');
  const btnLabel = btnInspect.querySelector('.btn-label');

  // Preview Section
  const previewSection = document.getElementById('preview-section');
  const previewThumb = document.getElementById('preview-thumb');
  const previewDuration = document.getElementById('preview-duration');
  const previewTitle = document.getElementById('preview-title');
  const previewChannel = document.getElementById('preview-channel');
  const previewViews = document.getElementById('preview-views');
  const tabVideo = document.getElementById('tab-video');
  const tabAudio = document.getElementById('tab-audio');
  const videoOptions = document.getElementById('video-options');
  const autoResNotice = document.getElementById('auto-res-notice');
  const audioOptions = document.getElementById('audio-options');
  const resolutionChips = document.getElementById('resolution-chips');
  const playlistNotice = document.getElementById('playlist-notice');
  const playlistInfoText = document.getElementById('playlist-info-text');
  const chkFullPlaylist = document.getElementById('chk-full-playlist');
  const playlistSelectionPanel = document.getElementById('playlist-selection-panel');
  const playlistSelectedCount = document.getElementById('playlist-selected-count');
  const btnPlaylistSelectAll = document.getElementById('btn-playlist-select-all');
  const btnPlaylistDeselectAll = document.getElementById('btn-playlist-deselect-all');
  const playlistFilterInput = document.getElementById('playlist-filter-input');
  const playlistItemsList = document.getElementById('playlist-items-list');
  const btnDownload = document.getElementById('btn-download');
  const downloadBtnText = document.getElementById('download-btn-text');

  // Tasks Section
  const activeTasksContainer = document.getElementById('active-tasks-container');
  const noTasksEmpty = document.getElementById('no-tasks-empty');
  const activeTasksCount = document.getElementById('active-tasks-count');

  // System & Header
  const ffmpegBadge = document.getElementById('ffmpeg-badge');
  const btnOpenFolder = document.getElementById('btn-open-folder');
  const btnToggleHistory = document.getElementById('btn-toggle-history');
  const historyBadgeCount = document.getElementById('history-badge-count');
  const btnToggleSettings = document.getElementById('btn-toggle-settings');

  // Drawers & Modals
  const historyDrawer = document.getElementById('history-drawer');
  const btnCloseHistory = document.getElementById('btn-close-history');
  const historyList = document.getElementById('history-list');
  const btnClearHistory = document.getElementById('btn-clear-history');

  const settingsModal = document.getElementById('settings-modal');
  const btnCloseSettings = document.getElementById('btn-close-settings');
  const settingDownloadDir = document.getElementById('setting-download-dir');
  const settingPreferredRes = document.getElementById('setting-preferred-res');
  const btnSaveDir = document.getElementById('btn-save-dir');
  const settingsFfmpegInfo = document.getElementById('settings-ffmpeg-info');

  const toastContainer = document.getElementById('toast-container');

  // State
  let currentVideoData = null;
  let selectedMode = 'video'; // 'video' or 'audio'
  let preferredResolution = localStorage.getItem('preferred_resolution') || '1080';
  let selectedResolution = null;
  let selectedAudioFormat = 'mp3';
  let selectedPlaylistIndices = new Set(); // Set of 1-based indices currently selected
  let activeTaskStreams = new Map(); // taskId -> EventSource
  let runningTasksCount = 0;

  // Initialize
  initSystem();
  loadHistory();
  setupEventListeners();
  checkPendingDownloads();

  // --- Initial System Setup ---
  async function initSystem() {
    try {
      const res = await fetch('/api/system-status');
      const data = await res.json();

      if (data.ffmpeg_installed) {
        ffmpegBadge.className = 'status-pill status-ready tooltip-trigger';
        ffmpegBadge.setAttribute('data-tooltip', 'FFmpeg installed & ready (All formats supported)');
        settingsFfmpegInfo.innerHTML = `
          <p style="color: #10b981; font-weight: 600;">✓ FFmpeg is detected on your system.</p>
          <p style="margin-top: 4px;">High-resolution video merging (1080p, 1440p, 4K) and MP3 conversion are fully enabled.</p>
        `;
      } else {
        ffmpegBadge.className = 'status-pill status-warning tooltip-trigger';
        ffmpegBadge.setAttribute('data-tooltip', 'FFmpeg not detected. Using high-speed progressive streams.');
        settingsFfmpegInfo.innerHTML = `
          <p style="color: #f59e0b; font-weight: 600;">⚠ FFmpeg is not found in system PATH.</p>
          <p style="margin-top: 4px;">Single-stream video and raw audio downloads work smoothly. To unlock separate stream 4K/1080p 60fps merging, run in terminal: <code style="background: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px;">winget install Gyan.FFmpeg</code></p>
        `;
      }

      settingDownloadDir.value = data.download_dir || '';
      if (settingPreferredRes) {
        settingPreferredRes.value = preferredResolution;
      }
    } catch (err) {
      console.warn('System status check failed:', err);
    }
  }

  // --- Event Listeners ---
  function setupEventListeners() {
    // Paste button
    btnPaste.addEventListener('click', async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text) {
          urlInput.value = text.trim();
          showToast('URL pasted from clipboard', 'info');
          inspectUrl();
        }
      } catch (err) {
        showToast('Clipboard access denied. Please paste manually.', 'error');
      }
    });

    // Enter key triggers inspect
    urlInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        inspectUrl();
      }
    });

    // Inspect button
    btnInspect.addEventListener('click', inspectUrl);

    // Format Tabs
    tabVideo.addEventListener('click', () => setMode('video'));
    tabAudio.addEventListener('click', () => setMode('audio'));

    // Audio format chips
    audioOptions.querySelectorAll('.chip').forEach(chip => {
      chip.addEventListener('click', (e) => {
        audioOptions.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
        e.currentTarget.classList.add('active');
        selectedAudioFormat = e.currentTarget.dataset.audioFormat;
      });
    });

    // Download Button
    btnDownload.addEventListener('click', triggerDownload);

    // Playlist Selection Controls
    if (chkFullPlaylist) {
      chkFullPlaylist.addEventListener('change', () => {
        handlePlaylistToggle();
      });
    }

    if (btnPlaylistSelectAll) {
      btnPlaylistSelectAll.addEventListener('click', () => {
        selectAllPlaylistItems(true);
      });
    }

    if (btnPlaylistDeselectAll) {
      btnPlaylistDeselectAll.addEventListener('click', () => {
        selectAllPlaylistItems(false);
      });
    }

    if (playlistFilterInput) {
      playlistFilterInput.addEventListener('input', () => {
        filterPlaylistItems(playlistFilterInput.value);
      });
    }

    // Folder Actions
    btnOpenFolder.addEventListener('click', () => openLocalFolder());

    // Drawer & Modal Toggles
    btnToggleHistory.addEventListener('click', () => openDrawer(historyDrawer));
    btnCloseHistory.addEventListener('click', () => closeDrawer(historyDrawer));
    historyDrawer.querySelector('.drawer-overlay').addEventListener('click', () => closeDrawer(historyDrawer));

    btnToggleSettings.addEventListener('click', () => openModal(settingsModal));
    btnCloseSettings.addEventListener('click', () => closeModal(settingsModal));
    settingsModal.querySelector('.modal-overlay').addEventListener('click', () => closeModal(settingsModal));

    // Save Settings
    btnSaveDir.addEventListener('click', async () => {
      const newPath = settingDownloadDir.value.trim();
      if (settingPreferredRes) {
        preferredResolution = settingPreferredRes.value;
        localStorage.setItem('preferred_resolution', preferredResolution);
      }
      if (!newPath) return;
      try {
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            download_dir: newPath,
            preferred_quality: preferredResolution
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast('Preferences updated', 'success');
          closeModal(settingsModal);
        } else {
          showToast(data.error || 'Failed to update preferences', 'error');
        }
      } catch (err) {
        showToast('Network error saving config', 'error');
      }
    });

    if (settingPreferredRes) {
      settingPreferredRes.addEventListener('change', () => {
        preferredResolution = settingPreferredRes.value;
        localStorage.setItem('preferred_resolution', preferredResolution);
      });
    }

    // Clear History
    btnClearHistory.addEventListener('click', async () => {
      if (!confirm('Are you sure you want to clear your download history?')) return;
      try {
        const res = await fetch('/api/history', { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
          renderHistory([]);
          showToast('History cleared', 'info');
        }
      } catch (err) {
        showToast('Failed to clear history', 'error');
      }
    });
  }

  // --- Inspect URL ---
  async function inspectUrl() {
    const url = urlInput.value.trim();
    if (!url) {
      showToast('Please enter or paste a valid YouTube URL', 'error');
      urlInput.focus();
      return;
    }

    // Show loading state
    btnSpinner.style.display = 'inline-block';
    btnLabel.textContent = 'Analyzing...';
    btnInspect.disabled = true;

    try {
      const res = await fetch('/api/info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
      });

      const data = await res.json();

      if (!res.ok || data.error) {
        throw new Error(data.error || 'Failed to retrieve video details.');
      }

      currentVideoData = data;
      renderPreview(data);
      showToast('Video information loaded!', 'success');
    } catch (err) {
      showToast(err.message || 'Error inspecting URL. Make sure it is a valid YouTube link.', 'error');
    } finally {
      btnSpinner.style.display = 'none';
      btnLabel.textContent = 'Analyze';
      btnInspect.disabled = false;
    }
  }

  // --- Render Preview Card ---
  function renderPreview(data) {
    previewSection.style.display = 'block';
    previewThumb.src = data.thumbnail || 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600';
    previewTitle.textContent = data.title || 'Untitled Video';
    previewChannel.textContent = data.uploader || 'YouTube Creator';

    if (data.is_playlist) {
      previewDuration.textContent = `${data.item_count} Videos`;
      previewViews.textContent = 'Full Playlist';
      playlistNotice.style.display = 'flex';
      playlistInfoText.textContent = `Playlist containing ${data.item_count} items`;

      // Reset checkbox to checked (default)
      chkFullPlaylist.checked = true;
      playlistSelectionPanel.style.display = 'none';

      // Pre-populate selection with all entries
      selectedPlaylistIndices.clear();
      (data.entries || []).forEach(e => selectedPlaylistIndices.add(e.index));
      renderPlaylistItemsList(data.entries || []);
      updatePlaylistSelectionCount();
      updateDownloadButtonText();
    } else {
      previewDuration.textContent = data.duration || 'Unknown';
      previewViews.textContent = data.views ? `${Number(data.views).toLocaleString()} views` : 'YouTube Video';
      playlistNotice.style.display = 'none';
      playlistSelectionPanel.style.display = 'none';
      selectedPlaylistIndices.clear();
      updateDownloadButtonText();
    }

    // Render Resolutions with Smart Auto-Selection & Fallback
    resolutionChips.innerHTML = '';
    const resList = (data.resolutions && data.resolutions.length > 0) 
      ? data.resolutions 
      : [1080, 720, 480, 360];

    // 1. Add "Auto (Best Available)" Chip
    const autoChip = document.createElement('button');
    autoChip.className = 'chip';
    autoChip.dataset.resolution = 'auto';
    autoChip.textContent = '⚡ Auto (Best)';
    resolutionChips.appendChild(autoChip);

    // 2. Add individual resolution chips
    resList.forEach((r) => {
      const btn = document.createElement('button');
      btn.className = 'chip';
      btn.dataset.resolution = r;
      btn.textContent = `${r}p ${r >= 2160 ? '⚡ 4K' : r >= 1080 ? 'HD' : ''}`.trim();
      resolutionChips.appendChild(btn);
    });

    // 3. Smart Resolution Selection Logic
    autoResNotice.style.display = 'none';

    if (preferredResolution === 'auto') {
      autoChip.classList.add('active');
      selectedResolution = 'auto';
      autoResNotice.style.display = 'inline-flex';
      autoResNotice.textContent = `⚡ Auto: best quality (${resList[0]}p)`;
    } else {
      const target = parseInt(preferredResolution, 10);
      if (resList.includes(target)) {
        const targetBtn = resolutionChips.querySelector(`[data-resolution="${target}"]`);
        if (targetBtn) targetBtn.classList.add('active');
        selectedResolution = target;
      } else {
        const smaller = resList.filter(r => r <= target);
        const fallback = smaller.length > 0 ? smaller[0] : resList[resList.length - 1];
        const fallbackBtn = resolutionChips.querySelector(`[data-resolution="${fallback}"]`);
        if (fallbackBtn) fallbackBtn.classList.add('active');
        selectedResolution = fallback;

        autoResNotice.style.display = 'inline-flex';
        autoResNotice.textContent = `⚡ Auto-selected ${fallback}p (${target}p unavailable)`;
        showToast(`Auto-selected ${fallback}p (${target}p is not available for this video)`, 'info');
      }
    }

    // Attach click handlers to all chips
    resolutionChips.querySelectorAll('.chip').forEach(chip => {
      chip.addEventListener('click', () => {
        resolutionChips.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');

        const val = chip.dataset.resolution;
        if (val === 'auto') {
          selectedResolution = 'auto';
          preferredResolution = 'auto';
          localStorage.setItem('preferred_resolution', 'auto');
          autoResNotice.style.display = 'inline-flex';
          autoResNotice.textContent = `⚡ Auto: best quality (${resList[0]}p)`;
        } else {
          selectedResolution = parseInt(val, 10);
          preferredResolution = String(selectedResolution);
          localStorage.setItem('preferred_resolution', preferredResolution);
          autoResNotice.style.display = 'none';
        }
      });
    });

    // Smooth scroll down to preview
    previewSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // --- Playlist Selection Functions ---
  function handlePlaylistToggle() {
    if (!currentVideoData || !currentVideoData.is_playlist) return;

    if (!chkFullPlaylist.checked) {
      // User UNCHECKED "Download entire playlist" -> Show list of videos inside
      playlistSelectionPanel.style.display = 'block';
      if (playlistFilterInput) playlistFilterInput.value = '';
      filterPlaylistItems('');

      // If nothing was selected before, select all by default
      if (selectedPlaylistIndices.size === 0 && currentVideoData.entries) {
        currentVideoData.entries.forEach(e => selectedPlaylistIndices.add(e.index));
        renderPlaylistItemsList(currentVideoData.entries);
      }

      updatePlaylistSelectionCount();
      updateDownloadButtonText();
    } else {
      // User RE-CHECKED "Download entire playlist" -> Hide list
      playlistSelectionPanel.style.display = 'none';
      updateDownloadButtonText();
      btnDownload.disabled = false;
      btnDownload.style.opacity = '1';
    }
  }

  function renderPlaylistItemsList(entries) {
    if (!playlistItemsList) return;
    playlistItemsList.innerHTML = '';

    if (!entries || entries.length === 0) {
      playlistItemsList.innerHTML = '<div class="playlist-empty-notice">No videos found in this playlist.</div>';
      return;
    }

    entries.forEach(item => {
      const isSelected = selectedPlaylistIndices.has(item.index);
      const row = document.createElement('div');
      row.className = `playlist-item-row ${isSelected ? 'selected' : ''}`;
      row.dataset.index = item.index;

      row.innerHTML = `
        <input type="checkbox" class="playlist-item-checkbox" ${isSelected ? 'checked' : ''} data-index="${item.index}" />
        <span class="playlist-item-idx">#${item.index}</span>
        <div class="playlist-item-thumb-box">
          <img class="playlist-item-thumb" src="${item.thumbnail || '/static/img/placeholder.jpg'}" alt="" loading="lazy" />
          <span class="playlist-item-duration-tag">${item.duration || '--:--'}</span>
        </div>
        <div class="playlist-item-info">
          <div class="playlist-item-title" title="${escapeQuotes(item.title)}">${escapeHtml(item.title)}</div>
        </div>
        <button type="button" class="playlist-item-quick-dl" title="Download only this video" data-index="${item.index}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
          <span class="quick-dl-text">Only this</span>
        </button>
      `;

      // Checkbox click
      const chk = row.querySelector('.playlist-item-checkbox');
      chk.addEventListener('change', (e) => {
        e.stopPropagation();
        togglePlaylistItem(item.index, chk.checked, row);
      });

      // Row click toggles selection
      row.addEventListener('click', (e) => {
        if (e.target.closest('.playlist-item-quick-dl')) return;
        if (e.target !== chk) {
          chk.checked = !chk.checked;
          togglePlaylistItem(item.index, chk.checked, row);
        }
      });

      // Quick DL single video
      const quickDl = row.querySelector('.playlist-item-quick-dl');
      quickDl.addEventListener('click', (e) => {
        e.stopPropagation();
        downloadSinglePlaylistItem(item);
      });

      playlistItemsList.appendChild(row);
    });
  }

  function togglePlaylistItem(index, checked, row) {
    if (checked) {
      selectedPlaylistIndices.add(index);
      if (row) row.classList.add('selected');
    } else {
      selectedPlaylistIndices.delete(index);
      if (row) row.classList.remove('selected');
    }
    updatePlaylistSelectionCount();
    updateDownloadButtonText();
  }

  function selectAllPlaylistItems(select) {
    if (!currentVideoData || !currentVideoData.entries) return;

    const rows = playlistItemsList.querySelectorAll('.playlist-item-row');
    rows.forEach(row => {
      if (row.style.display !== 'none') {
        const idx = parseInt(row.dataset.index, 10);
        const chk = row.querySelector('.playlist-item-checkbox');
        if (select) {
          selectedPlaylistIndices.add(idx);
          if (chk) chk.checked = true;
          row.classList.add('selected');
        } else {
          selectedPlaylistIndices.delete(idx);
          if (chk) chk.checked = false;
          row.classList.remove('selected');
        }
      }
    });

    updatePlaylistSelectionCount();
    updateDownloadButtonText();
  }

  function filterPlaylistItems(query) {
    const q = (query || '').toLowerCase().trim();
    const rows = playlistItemsList.querySelectorAll('.playlist-item-row');
    let visibleCount = 0;

    rows.forEach(row => {
      const titleEl = row.querySelector('.playlist-item-title');
      const title = (titleEl ? titleEl.textContent : '').toLowerCase();
      if (!q || title.includes(q)) {
        row.style.display = 'flex';
        visibleCount++;
      } else {
        row.style.display = 'none';
      }
    });

    let emptyMsg = playlistItemsList.querySelector('.playlist-no-filter-match');
    if (visibleCount === 0) {
      if (!emptyMsg) {
        emptyMsg = document.createElement('div');
        emptyMsg.className = 'playlist-empty-notice playlist-no-filter-match';
        emptyMsg.textContent = 'No videos match your search.';
        playlistItemsList.appendChild(emptyMsg);
      }
    } else if (emptyMsg) {
      emptyMsg.remove();
    }
  }

  function updatePlaylistSelectionCount() {
    if (!playlistSelectedCount) return;
    const total = currentVideoData && currentVideoData.entries ? currentVideoData.entries.length : 0;
    const count = selectedPlaylistIndices.size;
    playlistSelectedCount.textContent = `${count} of ${total} selected`;
  }

  function updateDownloadButtonText() {
    if (!currentVideoData) {
      downloadBtnText.textContent = selectedMode === 'audio' ? 'Download Audio' : 'Download Video';
      btnDownload.disabled = false;
      btnDownload.style.opacity = '1';
      return;
    }

    if (currentVideoData.is_playlist) {
      if (chkFullPlaylist.checked) {
        downloadBtnText.textContent = `Download Entire Playlist (${currentVideoData.item_count} Videos)`;
        btnDownload.disabled = false;
        btnDownload.style.opacity = '1';
      } else {
        const count = selectedPlaylistIndices.size;
        if (count === 0) {
          downloadBtnText.textContent = 'Select at least 1 video';
          btnDownload.disabled = true;
          btnDownload.style.opacity = '0.5';
        } else {
          downloadBtnText.textContent = `Download Selected (${count} Video${count > 1 ? 's' : ''})`;
          btnDownload.disabled = false;
          btnDownload.style.opacity = '1';
        }
      }
    } else {
      downloadBtnText.textContent = selectedMode === 'audio' ? 'Download Audio' : 'Download Video';
      btnDownload.disabled = false;
      btnDownload.style.opacity = '1';
    }
  }

  async function downloadSinglePlaylistItem(item) {
    if (!item) return;
    const payload = {
      url: item.url,
      title: item.title,
      thumbnail: item.thumbnail || (currentVideoData ? currentVideoData.thumbnail : ''),
      audio_only: selectedMode === 'audio',
      audio_format: selectedAudioFormat,
      resolution: selectedResolution,
      is_playlist: false,
    };

    try {
      showToast(`Starting download: "${item.title.slice(0, 28)}..."`, 'info');
      const res = await fetch('/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || 'Failed to start download.');
      }
      createTaskCard(data.task_id, payload);
      listenToTaskProgress(data.task_id);
    } catch (err) {
      showToast(err.message || 'Error starting single video download', 'error');
    }
  }

  // --- Mode Switching (Video vs Audio) ---
  function setMode(mode) {
    selectedMode = mode;
    if (mode === 'video') {
      tabVideo.classList.add('active');
      tabAudio.classList.remove('active');
      videoOptions.style.display = 'block';
      audioOptions.style.display = 'none';
    } else {
      tabVideo.classList.remove('active');
      tabAudio.classList.add('active');
      videoOptions.style.display = 'none';
      audioOptions.style.display = 'block';
    }
    updateDownloadButtonText();
  }

  // --- Trigger Download ---
  async function triggerDownload() {
    if (!currentVideoData) {
      showToast('Please inspect a valid link first', 'error');
      return;
    }

    let isPlaylist = false;
    let playlistItems = null;
    let downloadUrl = currentVideoData.webpage_url || currentVideoData.url || urlInput.value.trim();
    let downloadTitle = currentVideoData.title;
    let downloadThumb = currentVideoData.thumbnail;

    if (currentVideoData.is_playlist) {
      if (chkFullPlaylist.checked) {
        isPlaylist = true;
      } else {
        const selected = Array.from(selectedPlaylistIndices).sort((a, b) => a - b);
        if (selected.length === 0) {
          showToast('Please select at least one video to download', 'error');
          return;
        }

        if (selected.length === 1) {
          const singleEntry = (currentVideoData.entries || []).find(e => e.index === selected[0]);
          if (singleEntry) {
            downloadUrl = singleEntry.url;
            downloadTitle = singleEntry.title;
            downloadThumb = singleEntry.thumbnail;
            isPlaylist = false;
          } else {
            isPlaylist = true;
            playlistItems = String(selected[0]);
          }
        } else {
          isPlaylist = true;
          playlistItems = selected.join(',');
          downloadTitle = `${currentVideoData.title} (${selected.length} videos)`;
        }
      }
    }

    const payload = {
      url: downloadUrl,
      title: downloadTitle,
      thumbnail: downloadThumb,
      audio_only: selectedMode === 'audio',
      audio_format: selectedAudioFormat,
      resolution: selectedResolution,
      is_playlist: isPlaylist,
      playlist_items: playlistItems,
    };

    btnDownload.disabled = true;
    btnDownload.style.opacity = '0.6';

    try {
      const res = await fetch('/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || 'Failed to start download.');
      }

      showToast(`Started downloading: "${downloadTitle.slice(0, 32)}..."`, 'info');
      createTaskCard(data.task_id, payload);
      listenToTaskProgress(data.task_id);
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setTimeout(() => {
        btnDownload.disabled = false;
        btnDownload.style.opacity = '1';
      }, 1000);
    }
  }

  // --- Task Card Creation & SSE Progress Stream ---
  function createTaskCard(taskId, info) {
    noTasksEmpty.style.display = 'none';
    runningTasksCount++;
    updateActiveTasksBadge();

    const card = document.createElement('div');
    card.id = `task-${taskId}`;
    card.className = 'task-card';
    card.innerHTML = `
      <div class="task-top">
        <img class="task-thumb" src="${info.thumbnail || '/static/img/placeholder.jpg'}" alt="" />
        <div class="task-info">
          <div class="task-title" title="${info.title}">${info.title}</div>
          <div class="task-meta">
            <span class="task-type-badge">${info.audio_only ? '🎵 ' + (info.audio_format || 'MP3').toUpperCase() : '🎥 ' + (info.resolution || 'Best') + 'p'}</span>
            <span class="task-status-text" id="status-text-${taskId}">Starting download...</span>
          </div>
        </div>
      </div>
      <div class="task-progress-bar-bg">
        <div class="task-progress-bar-fill" id="progress-fill-${taskId}"></div>
      </div>
      <div class="task-bottom">
        <div class="task-stats">
          <div class="task-stat-item">⚡ <span id="speed-${taskId}">--</span></div>
          <div class="task-stat-item">⏳ <span id="eta-${taskId}">--</span></div>
        </div>
        <div class="task-actions" id="actions-${taskId}">
          <button class="btn-task-pause" id="pause-btn-${taskId}" data-state="playing" onclick="window.togglePause('${taskId}')" title="Pause download">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>
            <span class="btn-pause-text">Pause</span>
          </button>
          <span id="percent-${taskId}" style="font-weight: 700; color: #fff; min-width: 36px; text-align: right;">0%</span>
        </div>
      </div>
    `;

    activeTasksContainer.prepend(card);
  }

  function listenToTaskProgress(taskId) {
    if (activeTaskStreams.has(taskId)) {
      activeTaskStreams.get(taskId).close();
    }

    const evtSource = new EventSource(`/api/progress/${taskId}`);
    activeTaskStreams.set(taskId, evtSource);

    evtSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        updateTaskProgress(taskId, data, evtSource);
      } catch (err) {
        console.error('SSE JSON error:', err);
      }
    };

    evtSource.onerror = () => {
      evtSource.close();
      activeTaskStreams.delete(taskId);
    };
  }

  function updateTaskProgress(taskId, task, evtSource) {
    const card = document.getElementById(`task-${taskId}`);
    if (!card) return;

    const fill = document.getElementById(`progress-fill-${taskId}`);
    const percentEl = document.getElementById(`percent-${taskId}`);
    const speedEl = document.getElementById(`speed-${taskId}`);
    const etaEl = document.getElementById(`eta-${taskId}`);
    const statusEl = document.getElementById(`status-text-${taskId}`);
    const actionsEl = document.getElementById(`actions-${taskId}`);

    const percent = task.percent || 0;
    if (fill) fill.style.width = `${Math.min(percent, 100)}%`;
    if (percentEl) percentEl.textContent = `${percent}%`;
    if (speedEl && task.speed) speedEl.textContent = task.speed;
    if (etaEl && task.eta) etaEl.textContent = task.eta;

    if (task.status === 'downloading' || task.status === 'starting') {
      const itemSuffix = task.current_item ? ` • ${task.current_item}` : '';
      if (statusEl) {
        if (task.total_bytes > 0) {
          statusEl.textContent = `Downloading (${formatBytes(task.downloaded_bytes)} / ${formatBytes(task.total_bytes)})${itemSuffix}`;
        } else {
          statusEl.textContent = `Downloading...${itemSuffix}`;
        }
        statusEl.style.color = 'var(--text-muted)';
        if (task.current_item) statusEl.title = task.current_item;
      }
      if (fill) {
        fill.classList.remove('paused');
        fill.classList.remove('error');
      }
      // Ensure pause button is visible and in "playing" state (shows Pause)
      const pauseBtn = document.getElementById(`pause-btn-${taskId}`);
      if (pauseBtn && pauseBtn.dataset.state === 'paused') {
        pauseBtn.dataset.state = 'playing';
        pauseBtn.title = 'Pause download';
        pauseBtn.innerHTML = `
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>
          <span class="btn-pause-text">Pause</span>
        `;
        pauseBtn.classList.remove('is-paused');
      }
    } else if (task.status === 'paused') {
      if (statusEl) {
        statusEl.textContent = `Paused (${formatBytes(task.downloaded_bytes)} / ${formatBytes(task.total_bytes)})`;
        statusEl.style.color = '#f59e0b';
      }
      if (fill) fill.classList.add('paused');
      // Update pause button to show play icon and "Resume"
      const pauseBtn = document.getElementById(`pause-btn-${taskId}`);
      if (pauseBtn) {
        pauseBtn.dataset.state = 'paused';
        pauseBtn.title = 'Resume download';
        pauseBtn.innerHTML = `
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
          <span class="btn-pause-text">Resume</span>
        `;
        pauseBtn.classList.add('is-paused');
      }
    } else if (task.status === 'processing') {
      if (fill) fill.classList.remove('paused');
      if (statusEl) {
        statusEl.textContent = 'Processing & Finalizing audio/video...';
        statusEl.style.color = 'var(--accent-cyan)';
      }
    } else if (task.status === 'completed') {
      if (fill) {
        fill.style.width = '100%';
        fill.classList.add('finished');
        fill.classList.remove('paused');
      }
      if (statusEl) {
        statusEl.textContent = 'Completed ✓';
        statusEl.style.color = 'var(--accent-green)';
      }
      if (percentEl) percentEl.textContent = '100%';
      if (speedEl) speedEl.textContent = 'Finished';
      if (etaEl) etaEl.textContent = '00:00';

      if (actionsEl) {
        actionsEl.innerHTML = `
          <button class="btn-task-action" onclick="openFileExplorer('${escapeQuotes(task.filepath)}')">
            📂 Show in Folder
          </button>
        `;
      }

      runningTasksCount = Math.max(0, runningTasksCount - 1);
      updateActiveTasksBadge();
      if (evtSource) evtSource.close();
      activeTaskStreams.delete(taskId);
      showToast(`Finished downloading "${task.title}"`, 'success');
      loadHistory();
    } else if (task.status === 'error') {
      if (fill) {
        fill.classList.add('error');
        fill.classList.remove('paused');
      }
      if (statusEl) {
        const errorMsg = task.error || 'Connection interrupted';
        let friendly = 'Download failed';
        if (errorMsg.includes('500') || errorMsg.includes('Internal Server Error')) {
          friendly = 'YouTube server 500 error — Tap Retry to continue';
        } else if (errorMsg.includes('10054') || errorMsg.includes('closed by the remote host')) {
          friendly = 'Connection dropped — Tap Retry to continue';
        } else if (errorMsg.includes('timeout') || errorMsg.includes('timed out')) {
          friendly = 'Timed out — Tap Retry to continue';
        } else {
          friendly = `Failed: ${errorMsg.slice(0, 42)}`;
        }
        statusEl.textContent = friendly;
        statusEl.style.color = '#ef4444';
        statusEl.title = errorMsg;
      }
      if (actionsEl) {
        actionsEl.innerHTML = `
          <button class="btn-task-retry" id="retry-btn-${taskId}" onclick="window.retryFailedDownload('${taskId}')" title="Retry and continue download from current progress">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <path d="M23 4v6h-6"></path>
              <path d="M1 20v-6h6"></path>
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
            </svg>
            <span>Retry</span>
          </button>
          <button class="btn-task-dismiss" onclick="window.dismissTaskCard('${taskId}')" title="Dismiss">
            ✕
          </button>
          <span id="percent-${taskId}" style="font-weight: 700; color: #ef4444; min-width: 36px; text-align: right;">${task.percent || 0}%</span>
        `;
      }

      runningTasksCount = Math.max(0, runningTasksCount - 1);
      updateActiveTasksBadge();
      if (evtSource) evtSource.close();
      activeTaskStreams.delete(taskId);
      showToast(`Download failed. Tap "Retry" to continue.`, 'error');
    }
  }

  function updateActiveTasksBadge() {
    activeTasksCount.textContent = `${runningTasksCount} running`;
  }

  // --- Active & Pending Downloads Recovery ---
  async function checkPendingDownloads() {
    try {
      // 1. Check in-memory session tasks (running, paused, or failed)
      const tasksRes = await fetch('/api/tasks');
      const taskList = await tasksRes.json();
      if (Array.isArray(taskList) && taskList.length > 0) {
        taskList.forEach(task => {
          if (!document.getElementById(`task-${task.id}`)) {
            createTaskCard(task.id, {
              title: task.title || 'Download',
              thumbnail: task.thumbnail || '',
              audio_only: task.is_audio,
              audio_format: task.quality || 'mp3',
              resolution: task.quality,
            });
            updateTaskProgress(task.id, task, null);
            if (task.status === 'starting' || task.status === 'downloading' || task.status === 'paused') {
              listenToTaskProgress(task.id);
            }
          }
        });
      }

      // 2. Check pending interrupted downloads from previous sessions
      const res = await fetch('/api/pending');
      const data = await res.json();
      const pending = data.pending || [];
      if (pending.length > 0) {
        noTasksEmpty.style.display = 'none';
        pending.forEach(item => createPendingCard(item));
        showToast(`${pending.length} interrupted download${pending.length > 1 ? 's' : ''} found. Resume to continue.`, 'info');
      }
    } catch (err) {
      console.warn('Failed to check pending downloads:', err);
    }
  }

  function createPendingCard(item) {
    const cardId = `pending-${item.task_id}`;
    // Don't add duplicates
    if (document.getElementById(cardId)) return;

    const opts = item.options || {};
    const isAudio = opts.audio_only;
    const qualityLabel = isAudio
      ? '\uD83C\uDFB5 ' + (opts.audio_format || 'MP3').toUpperCase()
      : '\uD83C\uDFA5 ' + (opts.resolution || 'Best') + 'p';

    const card = document.createElement('div');
    card.id = cardId;
    card.className = 'task-card task-card-pending';
    card.innerHTML = `
      <div class="task-top">
        <img class="task-thumb" src="${item.thumbnail || '/static/img/placeholder.jpg'}" alt="" />
        <div class="task-info">
          <div class="task-title" title="${item.title || 'Unknown'}">${item.title || 'Unknown Video'}</div>
          <div class="task-meta">
            <span class="task-type-badge">${qualityLabel}</span>
            <span class="task-status-text" style="color: #f59e0b;">Interrupted</span>
          </div>
        </div>
      </div>
      <div class="task-progress-bar-bg">
        <div class="task-progress-bar-fill paused" style="width: 50%;"></div>
      </div>
      <div class="task-bottom">
        <div class="task-stats">
          <div class="task-stat-item" style="color: #f59e0b;">\u26A0 Interrupted on ${item.started_at || 'unknown date'}</div>
        </div>
        <div class="task-actions">
          <button class="btn-task-resume" onclick="window.resumePendingDownload('${item.task_id}', '${cardId}')" title="Resume download">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
            Resume
          </button>
          <button class="btn-task-dismiss" onclick="window.dismissPendingDownload('${item.task_id}', '${cardId}')" title="Dismiss">
            \u2715
          </button>
        </div>
      </div>
    `;

    activeTasksContainer.prepend(card);
  }

  // Global: Resume a pending download
  window.resumePendingDownload = async function(pendingTaskId, cardId) {
    const card = document.getElementById(cardId);
    if (card) {
      // Show loading state on the card
      const resumeBtn = card.querySelector('.btn-task-resume');
      if (resumeBtn) {
        resumeBtn.disabled = true;
        resumeBtn.textContent = 'Resuming...';
      }
    }

    try {
      const res = await fetch('/api/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pending_task_id: pendingTaskId })
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        throw new Error(data.error || 'Failed to resume download.');
      }

      // Remove the pending card
      if (card) card.remove();

      // Create a live task card with progress tracking
      const info = {
        title: data.title || 'Resuming download...',
        thumbnail: data.thumbnail || '',
        audio_only: false,
        audio_format: 'mp3',
        resolution: 'Best',
      };
      createTaskCard(data.task_id, info);
      listenToTaskProgress(data.task_id);
      showToast(`Resumed: "${data.title || 'Download'}"`, 'success');
    } catch (err) {
      showToast(err.message || 'Failed to resume download', 'error');
      // Re-enable the button
      if (card) {
        const resumeBtn = card.querySelector('.btn-task-resume');
        if (resumeBtn) {
          resumeBtn.disabled = false;
          resumeBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Resume`;
        }
      }
    }
  };

  // Global: Dismiss a pending download
  window.dismissPendingDownload = async function(pendingTaskId, cardId) {
    try {
      await fetch(`/api/pending/${pendingTaskId}/dismiss`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      const card = document.getElementById(cardId);
      if (card) {
        card.style.opacity = '0';
        card.style.transform = 'translateX(20px)';
        card.style.transition = 'all 0.3s ease-out';
        setTimeout(() => card.remove(), 300);
      }
      showToast('Interrupted download dismissed', 'info');
    } catch (err) {
      showToast('Failed to dismiss', 'error');
    }
  };

  // --- History Management ---
  async function loadHistory() {
    try {
      const res = await fetch('/api/history');
      const data = await res.json();
      renderHistory(data.history || []);
    } catch (err) {
      console.warn('Failed to load history:', err);
    }
  }

  function renderHistory(items) {
    historyBadgeCount.textContent = items.length;
    if (items.length === 0) {
      historyList.innerHTML = `
        <div class="empty-state" style="padding: 30px 10px;">
          <p>No download history yet.</p>
        </div>
      `;
      return;
    }

    historyList.innerHTML = items.map(item => `
      <div class="history-item">
        <img class="history-thumb" src="${item.thumbnail || ''}" alt="" />
        <div class="history-info">
          <div class="history-title" title="${item.title}">${item.title}</div>
          <div class="history-meta">
            ${item.type === 'audio' ? '🎵 Audio' : '🎥 ' + item.format} • ${item.timestamp}
          </div>
        </div>
        <button class="btn-ghost" style="padding: 4px 8px; font-size: 0.75rem;" onclick="openFileExplorer('${escapeQuotes(item.filepath)}')">
          Reveal
        </button>
      </div>
    `).join('');
  }

  // Global helper for opening file in explorer
  window.openFileExplorer = async function(filepath) {
    if (!filepath) return;
    try {
      const res = await fetch('/api/open-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filepath })
      });
      const data = await res.json();
      if (!data.success) {
        // Fallback to opening folder directly
        openLocalFolder();
      }
    } catch (err) {
      openLocalFolder();
    }
  };

  // Global helper for pause/resume toggle
  window.togglePause = async function(taskId) {
    const btn = document.getElementById(`pause-btn-${taskId}`);
    if (!btn) return;
    
    const isPaused = btn.dataset.state === 'paused';
    const endpoint = isPaused ? 'resume' : 'pause';
    
    btn.disabled = true;
    try {
      const res = await fetch(`/api/task/${taskId}/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      const data = await res.json();
      if (data.success) {
        if (isPaused) {
          // Switched to playing
          btn.dataset.state = 'playing';
          btn.title = 'Pause download';
          btn.innerHTML = `
            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>
            <span class="btn-pause-text">Pause</span>
          `;
          btn.classList.remove('is-paused');
          const fill = document.getElementById(`progress-fill-${taskId}`);
          if (fill) fill.classList.remove('paused');
          const statusEl = document.getElementById(`status-text-${taskId}`);
          if (statusEl) {
            statusEl.textContent = 'Resuming download...';
            statusEl.style.color = 'var(--text-muted)';
          }
          showToast('Download resumed', 'info');
        } else {
          // Switched to paused
          btn.dataset.state = 'paused';
          btn.title = 'Resume download';
          btn.innerHTML = `
            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
            <span class="btn-pause-text">Resume</span>
          `;
          btn.classList.add('is-paused');
          const fill = document.getElementById(`progress-fill-${taskId}`);
          if (fill) fill.classList.add('paused');
          const statusEl = document.getElementById(`status-text-${taskId}`);
          if (statusEl) {
            statusEl.textContent = 'Paused by user';
            statusEl.style.color = '#f59e0b';
          }
          showToast('Download paused', 'info');
        }
      } else {
        showToast(data.error || 'Action failed', 'error');
      }
    } catch (err) {
      showToast('Network error', 'error');
    } finally {
      btn.disabled = false;
    }
  };

  // Global: Retry a failed active download
  window.retryFailedDownload = async function(taskId) {
    const retryBtn = document.getElementById(`retry-btn-${taskId}`);
    const statusEl = document.getElementById(`status-text-${taskId}`);
    const fill = document.getElementById(`progress-fill-${taskId}`);
    const actionsEl = document.getElementById(`actions-${taskId}`);

    if (retryBtn) {
      retryBtn.disabled = true;
      retryBtn.innerHTML = `<span class="btn-spinner-sm"></span> <span>Retrying...</span>`;
    }
    if (statusEl) {
      statusEl.textContent = 'Reconnecting & continuing download...';
      statusEl.style.color = 'var(--text-muted)';
    }
    if (fill) {
      fill.classList.remove('error');
    }

    try {
      const res = await fetch(`/api/task/${taskId}/retry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || 'Failed to retry download.');
      }

      runningTasksCount++;
      updateActiveTasksBadge();

      // Restore active Pause button
      if (actionsEl) {
        actionsEl.innerHTML = `
          <button class="btn-task-pause" id="pause-btn-${taskId}" data-state="playing" onclick="window.togglePause('${taskId}')" title="Pause download">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>
            <span class="btn-pause-text">Pause</span>
          </button>
          <span id="percent-${taskId}" style="font-weight: 700; color: #fff; min-width: 36px; text-align: right;">--</span>
        `;
      }

      // Reconnect SSE progress listener
      listenToTaskProgress(taskId);
      showToast('Retrying download (continuing from saved progress)...', 'info');
    } catch (err) {
      showToast(err.message || 'Retry failed', 'error');
      if (retryBtn) {
        retryBtn.disabled = false;
        retryBtn.innerHTML = `
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M23 4v6h-6"></path>
            <path d="M1 20v-6h6"></path>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
          </svg>
          <span>Retry</span>
        `;
      }
      if (statusEl) {
        statusEl.textContent = 'Retry failed. Click to try again.';
        statusEl.style.color = '#ef4444';
      }
    }
  };

  // Global: Dismiss a task card from UI
  window.dismissTaskCard = async function(taskId) {
    try {
      await fetch(`/api/task/${taskId}/dismiss`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      const card = document.getElementById(`task-${taskId}`);
      if (card) {
        card.style.opacity = '0';
        card.style.transform = 'translateX(20px)';
        card.style.transition = 'all 0.3s ease-out';
        setTimeout(() => {
          card.remove();
          if (!activeTasksContainer.querySelector('.task-card')) {
            noTasksEmpty.style.display = 'block';
          }
        }, 300);
      }
    } catch (err) {
      console.warn('Dismiss error:', err);
    }
  };

  async function openLocalFolder(path = null) {
    try {
      const res = await fetch('/api/open-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
      });
      const data = await res.json();
      if (data.success) {
        showToast('Opened downloads folder', 'info');
      } else {
        showToast('Could not open folder', 'error');
      }
    } catch (err) {
      showToast('Error opening folder', 'error');
    }
  }

  // --- Drawer & Modal Helpers ---
  function openDrawer(drawer) {
    drawer.classList.add('open');
  }
  function closeDrawer(drawer) {
    drawer.classList.remove('open');
  }
  function openModal(modal) {
    modal.classList.add('open');
  }
  function closeModal(modal) {
    modal.classList.remove('open');
  }

  // --- Toast System ---
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    let icon = 'ℹ️';
    if (type === 'success') icon = '✅';
    if (type === 'error') icon = '❌';

    toast.innerHTML = `<span>${icon}</span><span>${message}</span>`;
    toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 0.3s ease-out';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  // Utility
  function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return '0 MB';
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(1)} MB`;
  }

  function escapeQuotes(str) {
    if (!str) return '';
    return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
});
