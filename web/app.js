const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const PAGE_META = {
  video: ['视频工坊', '编码诊断、转 Win 通用 MP4、压缩、裁剪、旋转、多视频合并、批量截图与字幕互转'],
  image: ['图片工坊', '批量压缩、HEIC/AVIF 格式互转、拼长图与宫格、批量旋转、长图分割与去 EXIF'],
  pdf: ['PDF 工坊', '纯本地 PDF↔Word、合并、拆分、删页、旋转、转图、压缩与 AES-256 加密解锁'],
  text: ['文本与杂项', '文本统计、JSON、离线二维码、强密码、双向时间戳、批量重命名、乱码修复与文件哈希'],
  calc: ['计算与换算', '无广告房贷提前还款（等额本息/本金双方案对比）、复利定投、日期推算与色值换算'],
};

const state = {
  outputDir: '',
  videoPath: '',
  videoTaskId: '',
  videoPoll: null,
  videoMergeFiles: [],
  videoMergeTaskId: '',
  videoMergePoll: null,
  videoSubPath: '',
  imageFiles: [],
  pdfMergeFiles: [],
  pdfEditPath: '',
  pdfImgPath: '',
  pdfFromImgFiles: [],
  pdfCompPath: '',
  pdfProtPath: '',
  p2wPath: '',
  w2pPath: '',
  renamePreview: null,
  zipFixPath: '',
  txtFixPath: '',
  hashData: null,
  tsLastSec: '',
  tsLastMs: '',
};

function escHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function toast(msg) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('show'), 2600);
}

function fmtBytes(n) {
  if (!n && n !== 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0, v = Number(n);
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i === 0 ? 0 : 2)} ${units[i]}`;
}

function fmtDuration(sec) {
  if (!sec || sec <= 0) return '—';
  const s = Math.floor(sec % 60);
  const m = Math.floor((sec / 60) % 60);
  const h = Math.floor(sec / 3600);
  const pad = (x) => String(x).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

const API_TOKEN = document.querySelector('meta[name="toolbox-token"]')?.content || '';

async function api(url, body) {
  const opt = body === undefined
    ? { method: 'GET' }
    : {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Toolbox-Token': API_TOKEN },
        body: JSON.stringify(body),
      };
  const res = await fetch(url, opt);
  const data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
}

async function uploadFile(file) {
  const res = await fetch(`/api/upload?name=${encodeURIComponent(file.name)}`, {
    method: 'POST',
    headers: { 'X-Toolbox-Token': API_TOKEN },
    body: file,
  });
  const data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || '上传失败');
  return data;
}

function openPath(p) {
  api('/api/open-path', { path: p || state.outputDir }).catch((e) => toast(e.message));
}

function downloadUrl(p) {
  return `/api/download?path=${encodeURIComponent(p)}`;
}

function previewUrl(p) {
  return `/api/preview?path=${encodeURIComponent(p)}&t=${Date.now()}`;
}

function buildPreviewHtml(filePath) {
  const ext = (filePath.split('.').pop() || '').toLowerCase();
  const url = previewUrl(filePath);
  if (['mp4', 'webm', 'mov', 'm4v'].includes(ext)) {
    return `<div class="preview-box"><video controls preload="metadata" src="${url}"></video></div>`;
  }
  if (['mp3', 'm4a', 'wav', 'ogg'].includes(ext)) {
    return `<div class="preview-box"><audio controls src="${url}"></audio></div>`;
  }
  if (['png', 'jpg', 'jpeg', 'webp', 'avif', 'gif', 'bmp', 'ico'].includes(ext)) {
    return `<div class="preview-box"><a href="${url}" target="_blank" title="点击新标签页查看原图"><img src="${url}" alt="预览图"></a></div>`;
  }
  if (ext === 'pdf') {
    return `<div class="preview-box"><iframe src="${url}" title="PDF 预览"></iframe></div>`;
  }
  return '';
}

function renderResultCard(container, title, filePath, fileName, extraText = '', previewPath = '') {
  const targetPreview = previewPath || filePath;
  const ext = (targetPreview.split('.').pop() || '').toLowerCase();
  const canInline = ['png', 'jpg', 'jpeg', 'webp', 'avif', 'gif', 'bmp', 'ico', 'pdf', 'mp4', 'mp3', 'm4a', 'wav'].includes(ext);
  const autoShow = ['png', 'jpg', 'jpeg', 'webp', 'avif', 'gif', 'bmp', 'ico'].includes(ext);

  container.innerHTML = `
    <div class="alert alert-ok" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-top:14px;">
      <div>
        <strong>✅ ${escHtml(title)}</strong>
        <div style="font-size:12px;margin-top:2px;">${escHtml(fileName)}${extraText ? ' · ' + escHtml(extraText) : ''}</div>
      </div>
      <div class="row">
        ${canInline ? '<button class="btn btn-sm js-toggle-preview">👁️ ' + (autoShow ? '收起预览' : '预览') + '</button>' : ''}
        <button class="btn btn-sm js-open-path">📂 打开所在文件夹</button>
        <a class="btn btn-sm btn-primary" href="${downloadUrl(filePath)}">⬇️ 浏览器下载</a>
      </div>
    </div>
    <div class="js-preview-slot"></div>`;
  container.querySelector('.js-open-path').onclick = () => openPath(filePath);
  if (canInline) {
    const slot = container.querySelector('.js-preview-slot');
    const toggleBtn = container.querySelector('.js-toggle-preview');
    let shown = autoShow;
    if (shown) slot.innerHTML = buildPreviewHtml(targetPreview);
    toggleBtn.onclick = () => {
      shown = !shown;
      slot.innerHTML = shown ? buildPreviewHtml(targetPreview) : '';
      toggleBtn.textContent = shown ? '👁️ 收起预览' : '👁️ 预览';
    };
  }
}

// ==================== 主题与导航 ====================
function initTheme() {
  const saved = localStorage.getItem('toolbox-theme');
  const preferDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const theme = saved || (preferDark ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', theme);
}
initTheme();

$('#btn-theme').onclick = () => {
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('toolbox-theme', next);
};

$$('.nav-btn').forEach((btn) => {
  btn.onclick = () => {
    const id = btn.dataset.panel;
    $$('.nav-btn').forEach((b) => b.classList.toggle('active', b === btn));
    $$('.panel').forEach((p) => p.classList.toggle('active', p.id === `panel-${id}`));
    $('#page-title').textContent = PAGE_META[id][0];
    $('#page-desc').textContent = PAGE_META[id][1];
  };
});

$$('.subtabs').forEach((group) => {
  const tabs = group.querySelectorAll('.subtab');
  tabs.forEach((tab) => {
    tab.onclick = () => {
      tabs.forEach((t) => t.classList.toggle('active', t === tab));
      const parent = group.parentElement;
      parent.querySelectorAll(':scope > .subpanel').forEach((sp) => {
        sp.classList.toggle('active', sp.id === tab.dataset.sub);
      });
    };
  });
});

$('#btn-open-out').onclick = () => openPath(state.outputDir);
$('#btn-shutdown').onclick = async () => {
  if (!confirm('确定要停止本地工具箱后台服务吗？')) return;
  try { await api('/api/shutdown', {}); } catch (_) {}
  document.body.innerHTML = '<div style="padding:60px;text-align:center;"><h2>本地工具箱已安全退出</h2><p style="color:#64748b;">可以直接关闭此标签页，下次双击「启动工具箱.cmd」重新打开。</p></div>';
};

// 初始化健康检查
api('/api/health').then((h) => {
  state.outputDir = h.output_dir;
  const nv = h.nvenc ? 'NVENC 硬编可用' : 'CPU x264 编码';
  $('#env-status').innerHTML = `<span class="env-dot"></span>FFmpeg ${h.ffmpeg ? '就绪' : '缺失'}<br>${nv}`;
  if (!h.nvenc) {
    ['#vc-nvenc', '#vcomp-nvenc', '#vtrim-nvenc', '#vrot-nvenc', '#vmerge-nvenc'].forEach((sel) => {
      const el = $(sel);
      if (el) el.checked = false;
    });
  }
}).catch(() => {
  $('#env-status').textContent = '后端连接异常';
});

function setupDropzone(el, onFiles) {
  el.addEventListener('dragover', (e) => { e.preventDefault(); el.classList.add('dragover'); });
  el.addEventListener('dragleave', () => el.classList.remove('dragover'));
  el.addEventListener('drop', (e) => {
    e.preventDefault();
    el.classList.remove('dragover');
    if (e.dataTransfer.files.length) onFiles(Array.from(e.dataTransfer.files));
  });
}

// ==================== 1. 视频工坊 ====================
async function loadVideo(path) {
  try {
    toast('正在解析视频编码…');
    const info = await api('/api/video/probe', { path });
    state.videoPath = info.path;
    $('#video-probe-box').style.display = 'block';
    $('#video-action-card').style.display = 'block';
    $('#v-name').textContent = info.name;
    $('#v-vcodec').textContent = info.video_codec.toUpperCase();
    $('#v-pixfmt').textContent = info.pix_fmt;
    $('#v-acodec').textContent = info.audio_codec.toUpperCase();
    $('#v-res').textContent = `${info.width}×${info.height} · ${info.fps}fps`;
    $('#v-dur').textContent = fmtDuration(info.duration);
    $('#v-size').textContent = fmtBytes(info.size_bytes);

    const badge = $('#v-compat-badge');
    const advice = $('#v-advice');
    if (info.compatible) {
      badge.className = 'badge badge-ok';
      badge.textContent = 'Win 已兼容';
      advice.className = 'alert alert-ok';
    } else {
      badge.className = 'badge badge-warn';
      badge.textContent = info.can_remux_video ? '可无损秒换壳' : '需转码兼容';
      advice.className = 'alert alert-warn';
    }
    const issueHtml = info.issues.length ? `<div>原因：${escHtml(info.issues.join('；'))}</div>` : '';
    advice.innerHTML = `${issueHtml}<div style="margin-top:3px;"><strong>建议：</strong>${escHtml(info.advice)}</div>`;

    // 加载 FFmpeg 抽取的封面缩略图（即使浏览器无法直接播 HEVC/MKV 也能看到画面）
    const thumb = $('#v-thumb');
    thumb.style.display = 'none';
    thumb.onload = () => { thumb.style.display = 'block'; };
    thumb.onerror = () => { thumb.style.display = 'none'; };
    thumb.src = `/api/video/thumb?path=${encodeURIComponent(info.path)}&t=${Date.now()}`;
    $('#v-src-preview').innerHTML = '';
    $('#btn-video-preview').textContent = '▶ 预览原视频';
  } catch (e) {
    toast(e.message);
  }
}

$('#btn-video-preview').onclick = () => {
  if (!state.videoPath) return;
  const box = $('#v-src-preview');
  if (box.innerHTML) {
    box.innerHTML = '';
    $('#btn-video-preview').textContent = '▶ 预览原视频';
  } else {
    box.innerHTML = `<div class="preview-box"><video controls preload="metadata" src="${previewUrl(state.videoPath)}"></video><div style="font-size:12px;color:var(--muted);margin-top:6px;">若原视频为 HEVC/MKV 等浏览器不支持的编码，可能无法直接播放，转码后即可预览</div></div>`;
    $('#btn-video-preview').textContent = '⏹ 收起预览';
  }
};

function clearVideo() {
  clearInterval(state.videoPoll);
  if (state.videoTaskId) {
    api('/api/video/cancel', { id: state.videoTaskId }).catch(() => {});
    state.videoTaskId = '';
  }
  state.videoPath = '';
  $('#video-probe-box').style.display = 'none';
  $('#video-action-card').style.display = 'none';
  $('#video-progress-box').style.display = 'none';
  $('#vp-actions').innerHTML = '';
  $('#vp-preview').innerHTML = '';
  $('#v-src-preview').innerHTML = '';
  toast('已移除当前视频');
}

$('#btn-video-clear').onclick = clearVideo;

$('#btn-video-pick').onclick = async (e) => {
  e.stopPropagation();
  try {
    const res = await api('/api/pick-files', {
      title: '选择视频文件',
      filetypes: [['视频文件', '*.mp4 *.mkv *.mov *.flv *.ts *.avi *.webm *.wmv *.m4v'], ['所有文件', '*.*']],
      multiple: false,
    });
    if (res.files.length) loadVideo(res.files[0]);
  } catch (err) { toast(err.message); }
};
$('#btn-video-upload').onclick = (e) => { e.stopPropagation(); $('#video-file-input').click(); };
$('#video-file-input').onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  try {
    toast('正在接收视频文件…');
    const up = await uploadFile(f);
    loadVideo(up.path);
  } catch (err) { toast(err.message); }
  e.target.value = '';
};
setupDropzone($('#video-drop'), async (files) => {
  try {
    toast('正在接收视频文件…');
    const up = await uploadFile(files[0]);
    loadVideo(up.path);
  } catch (err) { toast(err.message); }
});

function pollVideoTask(task, ui, pollKey, taskKey = 'videoTaskId') {
  clearInterval(state[pollKey]);
  state[taskKey] = task.id;
  ui.box.style.display = 'block';
  ui.desc.textContent = task.mode_desc;
  ui.bar.style.width = '2%';
  ui.stat.className = 'badge badge-info';
  ui.stat.textContent = '启动中…';
  ui.actions.innerHTML = `<button class="btn btn-sm btn-danger js-v-cancel">取消任务</button>`;
  ui.preview.innerHTML = '';
  ui.actions.querySelector('.js-v-cancel').onclick = () => api('/api/video/cancel', { id: task.id });

  state[pollKey] = setInterval(async () => {
    try {
      const cur = await api(`/api/video/task/${task.id}`);
      ui.bar.style.width = `${cur.progress}%`;
      if (cur.status === 'running') {
        ui.stat.textContent = `${cur.progress}%${cur.speed ? ' · ' + cur.speed : ''}`;
      } else {
        clearInterval(state[pollKey]);
        if (cur.status === 'done') {
          ui.bar.style.width = '100%';
          ui.stat.className = 'badge badge-ok';
          ui.stat.textContent = `完成 · 耗时 ${cur.elapsed}s`;
          const ratio = cur.input_size ? `${fmtBytes(cur.input_size)} → ${fmtBytes(cur.output_size)}` : fmtBytes(cur.output_size);
          ui.actions.innerHTML = `
            <span style="font-size:12px;color:var(--muted);">${escHtml(cur.output_name)} (${escHtml(ratio)})</span>
            <button class="btn btn-sm js-toggle-vprev">👁️ 收起预览</button>
            <button class="btn btn-sm js-open-path">📂 打开所在文件夹</button>
            <a class="btn btn-sm btn-primary" href="${downloadUrl(cur.output_path)}">⬇️ 下载</a>`;
          ui.actions.querySelector('.js-open-path').onclick = () => openPath(cur.output_path);
          ui.preview.innerHTML = buildPreviewHtml(cur.output_path);
          let pvShown = true;
          const pvBtn = ui.actions.querySelector('.js-toggle-vprev');
          pvBtn.onclick = () => {
            pvShown = !pvShown;
            ui.preview.innerHTML = pvShown ? buildPreviewHtml(cur.output_path) : '';
            pvBtn.textContent = pvShown ? '👁️ 收起预览' : '👁️ 预览结果';
          };
          toast('视频处理完成！');
        } else if (cur.status === 'cancelled') {
          ui.stat.className = 'badge badge-warn';
          ui.stat.textContent = '已取消';
          ui.actions.innerHTML = '';
        } else {
          ui.stat.className = 'badge badge-warn';
          ui.stat.textContent = '失败';
          ui.actions.innerHTML = `<div class="alert alert-err" style="width:100%;">${escHtml(cur.error)}</div>`;
        }
      }
    } catch (err) {
      clearInterval(state[pollKey]);
      toast(err.message);
    }
  }, 450);
}

async function startVideoJob(mode, options) {
  if (!state.videoPath) return toast('请先选择视频文件');
  try {
    const task = await api('/api/video/start', { path: state.videoPath, mode, options });
    pollVideoTask(task, {
      box: $('#video-progress-box'),
      desc: $('#vp-desc'),
      bar: $('#vp-bar'),
      stat: $('#vp-stat'),
      actions: $('#vp-actions'),
      preview: $('#vp-preview'),
    }, 'videoPoll');
  } catch (e) {
    toast(e.message);
  }
}

$('#btn-run-compat').onclick = () => startVideoJob('compat', {
  quality: $('#vc-quality').value,
  use_nvenc: $('#vc-nvenc').checked,
  force_reencode: $('#vc-force').checked,
});
$('#btn-run-compress').onclick = () => startVideoJob('compress', {
  quality: $('#vcomp-quality').value,
  max_height: Number($('#vcomp-height').value),
  use_nvenc: $('#vcomp-nvenc').checked,
});
$('#btn-run-trim').onclick = () => startVideoJob('trim', {
  start: $('#vtrim-start').value,
  end: $('#vtrim-end').value,
  lossless: $('#vtrim-lossless').checked,
  use_nvenc: $('#vtrim-nvenc').checked,
});
$('#btn-run-rotate').onclick = () => startVideoJob('rotate', {
  rotate_op: $('#vrot-op').value,
  quality: $('#vrot-quality').value,
  use_nvenc: $('#vrot-nvenc').checked,
});
$('#btn-run-audio').onclick = () => startVideoJob('audio', { audio_format: $('#vaudio-fmt').value });
$('#btn-run-gif').onclick = () => startVideoJob('gif', {
  start: $('#vgif-start').value,
  end: $('#vgif-end').value,
  width: Number($('#vgif-width').value),
  fps: Number($('#vgif-fps').value),
});
$('#btn-run-frames').onclick = async () => {
  if (!state.videoPath) return toast('请先选择视频文件');
  try {
    toast('正在批量截取视频画面…');
    const res = await api('/api/video/frames', {
      path: state.videoPath,
      mode: $('#vfr-mode').value,
      interval: Number($('#vfr-interval').value),
      count: Number($('#vfr-count').value),
      start: $('#vfr-start').value,
      end: $('#vfr-end').value,
      format: $('#vfr-fmt').value,
    });
    renderResultCard(
      $('#v-frames-result'),
      '批量截图导出完成',
      res.path,
      res.name,
      `共 ${res.count} 张 · ${fmtBytes(res.output_size)}`,
      res.preview_path,
    );
  } catch (e) { toast(e.message); }
};

// 多视频合并
const refreshVideoMerge = () => renderFileList($('#vmerge-list'), state.videoMergeFiles, refreshVideoMerge, false, true);
$('#btn-vmerge-pick').onclick = async (e) => {
  e.stopPropagation();
  try {
    const res = await api('/api/pick-files', {
      title: '选择多个视频文件',
      filetypes: [['视频文件', '*.mp4 *.mkv *.mov *.flv *.ts *.avi *.webm *.wmv *.m4v'], ['所有文件', '*.*']],
      multiple: true,
    });
    res.files.forEach((p) => state.videoMergeFiles.push({ path: p, name: p.split(/[\\/]/).pop() }));
    refreshVideoMerge();
  } catch (err) { toast(err.message); }
};
$('#btn-vmerge-clear').onclick = (e) => {
  e.stopPropagation();
  state.videoMergeFiles = [];
  refreshVideoMerge();
};
setupDropzone($('#vmerge-drop'), async (files) => {
  try {
    toast('正在接收视频文件…');
    for (const f of files) state.videoMergeFiles.push(await uploadFile(f));
    refreshVideoMerge();
  } catch (err) { toast(err.message); }
});
$('#btn-run-vmerge').onclick = async () => {
  if (state.videoMergeFiles.length < 2) return toast('请至少选择 2 个视频文件');
  try {
    const task = await api('/api/video/merge', {
      paths: state.videoMergeFiles.map((f) => f.path),
      options: {
        reencode: $('#vmerge-reencode').checked,
        use_nvenc: $('#vmerge-nvenc').checked,
      },
    });
    pollVideoTask(task, {
      box: $('#vmerge-progress-box'),
      desc: $('#vmp-desc'),
      bar: $('#vmp-bar'),
      stat: $('#vmp-stat'),
      actions: $('#vmp-actions'),
      preview: $('#vmp-preview'),
    }, 'videoMergePoll', 'videoMergeTaskId');
  } catch (e) { toast(e.message); }
};

// 字幕格式互转
function setVideoSub(path, name, size) {
  state.videoSubPath = path;
  $('#vsub-meta').textContent = size ? `${name}（${fmtBytes(size)}）` : name;
  $('#btn-vsub-clear').style.display = 'inline-flex';
}
$('#btn-vsub-pick').onclick = async (e) => {
  e.stopPropagation();
  try {
    const res = await api('/api/pick-files', {
      title: '选择字幕文件',
      filetypes: [['字幕文件', '*.srt *.vtt *.ass *.ssa'], ['所有文件', '*.*']],
      multiple: false,
    });
    if (res.files.length) setVideoSub(res.files[0], res.files[0].split(/[\\/]/).pop(), 0);
  } catch (err) { toast(err.message); }
};
$('#btn-vsub-clear').onclick = (e) => {
  e.stopPropagation();
  state.videoSubPath = '';
  $('#vsub-meta').textContent = '';
  $('#btn-vsub-clear').style.display = 'none';
  $('#vsub-result').innerHTML = '';
};
setupDropzone($('#vsub-drop'), async (files) => {
  try {
    const up = await uploadFile(files[0]);
    setVideoSub(up.path, up.name, up.size);
  } catch (err) { toast(err.message); }
});
$('#btn-vsub-run').onclick = async () => {
  if (!state.videoSubPath) return toast('请先选择字幕文件');
  try {
    const res = await api('/api/video/subtitle', {
      path: state.videoSubPath,
      format: $('#vsub-fmt').value,
    });
    renderResultCard(
      $('#vsub-result'),
      '字幕转换完成',
      res.path,
      res.name,
      `共 ${res.cues} 条字幕 · 源编码 ${res.detected_encoding} → UTF-8 · ${fmtBytes(res.output_size)}`,
    );
  } catch (e) { toast(e.message); }
};

// ==================== 2. 图片工坊 ====================
function renderFileList(el, arr, onChange, showThumb = false, sortable = true) {
  el.innerHTML = arr.map((f, idx) => `
    <div class="file-item" ${sortable ? `draggable="true" data-idx="${idx}"` : ''}>
      <div class="row" style="gap:10px; min-width:0; flex:1;">
        ${sortable ? '<span class="drag-handle" title="拖拽可调整顺序">⋮⋮</span>' : ''}
        ${showThumb ? `<img class="thumb-mini" src="${previewUrl(f.path)}" alt="">` : ''}
        <div style="min-width:0; word-break:break-all;"><strong>${idx + 1}. ${escHtml(f.name)}</strong> <span class="meta">${f.size ? fmtBytes(f.size) : ''}</span></div>
      </div>
      <div class="item-actions">
        ${sortable ? `<button class="btn btn-sm js-up" data-idx="${idx}" ${idx === 0 ? 'disabled' : ''} title="上移">↑</button>` : ''}
        ${sortable ? `<button class="btn btn-sm js-down" data-idx="${idx}" ${idx === arr.length - 1 ? 'disabled' : ''} title="下移">↓</button>` : ''}
        <button class="btn btn-sm js-del" data-idx="${idx}">移除</button>
      </div>
    </div>`).join('');

  el.querySelectorAll('.thumb-mini').forEach((img) => {
    img.addEventListener('error', () => { img.style.display = 'none'; });
  });

  el.querySelectorAll('.js-del').forEach((b) => {
    b.onclick = () => { arr.splice(Number(b.dataset.idx), 1); onChange(); };
  });
  if (sortable) {
    el.querySelectorAll('.js-up').forEach((b) => {
      b.onclick = () => {
        const i = Number(b.dataset.idx);
        if (i > 0) { [arr[i - 1], arr[i]] = [arr[i], arr[i - 1]]; onChange(); }
      };
    });
    el.querySelectorAll('.js-down').forEach((b) => {
      b.onclick = () => {
        const i = Number(b.dataset.idx);
        if (i < arr.length - 1) { [arr[i], arr[i + 1]] = [arr[i + 1], arr[i]]; onChange(); }
      };
    });
    let dragFrom = -1;
    el.querySelectorAll('.file-item[draggable="true"]').forEach((item) => {
      item.addEventListener('dragstart', (e) => {
        dragFrom = Number(item.dataset.idx);
        item.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
      });
      item.addEventListener('dragend', () => {
        item.classList.remove('dragging');
        el.querySelectorAll('.drag-over').forEach((x) => x.classList.remove('drag-over'));
      });
      item.addEventListener('dragover', (e) => {
        e.preventDefault();
        item.classList.add('drag-over');
      });
      item.addEventListener('dragleave', () => item.classList.remove('drag-over'));
      item.addEventListener('drop', (e) => {
        e.preventDefault();
        item.classList.remove('drag-over');
        const to = Number(item.dataset.idx);
        if (dragFrom >= 0 && to >= 0 && dragFrom !== to) {
          const [moved] = arr.splice(dragFrom, 1);
          arr.splice(to, 0, moved);
          onChange();
        }
        dragFrom = -1;
      });
    });
  }
}

const refreshImgList = () => renderFileList($('#img-file-list'), state.imageFiles, refreshImgList, true, true);

$('#btn-img-pick').onclick = async (e) => {
  e.stopPropagation();
  try {
    const res = await api('/api/pick-files', {
      title: '选择图片',
      filetypes: [['图片文件', '*.png *.jpg *.jpeg *.webp *.heic *.heif *.avif *.bmp *.tiff'], ['所有文件', '*.*']],
      multiple: true,
    });
    res.files.forEach((p) => state.imageFiles.push({ path: p, name: p.split(/[\\/]/).pop() }));
    refreshImgList();
  } catch (err) { toast(err.message); }
};
$('#btn-img-upload').onclick = (e) => { e.stopPropagation(); $('#img-file-input').click(); };
$('#btn-img-clear').onclick = (e) => {
  e.stopPropagation();
  state.imageFiles = [];
  refreshImgList();
  $('#img-result').innerHTML = '';
};
$('#img-file-input').onchange = async (e) => {
  try {
    for (const f of Array.from(e.target.files)) {
      const up = await uploadFile(f);
      state.imageFiles.push(up);
    }
    refreshImgList();
  } catch (err) { toast(err.message); }
  e.target.value = '';
};
setupDropzone($('#img-drop'), async (files) => {
  try {
    for (const f of files) {
      const up = await uploadFile(f);
      state.imageFiles.push(up);
    }
    refreshImgList();
  } catch (err) { toast(err.message); }
});

$('#btn-img-run').onclick = async () => {
  if (!state.imageFiles.length) return toast('请先添加图片');
  try {
    toast('正在处理图片…');
    const res = await api('/api/image/process', {
      paths: state.imageFiles.map((f) => f.path),
      format: $('#img-fmt').value,
      quality: Number($('#img-quality').value),
      max_width: Number($('#img-maxw').value),
      max_height: Number($('#img-maxh').value),
      strip_exif: $('#img-strip-exif').checked,
    });
    const first = res.files[0];
    const dlPath = res.zip_path || first.path;
    const dlName = res.zip_name || first.name;
    const summary = res.files.length === 1
      ? `${fmtBytes(first.input_size)} → ${fmtBytes(first.output_size)}（节省 ${first.saved_pct}%）`
      : `共处理 ${res.files.length} 张，已同时打包 ZIP`;
    renderResultCard($('#img-result'), '图片处理完成', dlPath, dlName, summary, first.path);
  } catch (e) { toast(e.message); }
};

$('#btn-stitch-run').onclick = async () => {
  if (state.imageFiles.length < 2) return toast('拼接至少需要 2 张图片');
  try {
    toast('正在拼接图片…');
    const res = await api('/api/image/stitch', {
      paths: state.imageFiles.map((f) => f.path),
      mode: $('#stitch-mode').value,
      cols: Number($('#stitch-cols').value),
      gap: Number($('#stitch-gap').value),
      bg_color: $('#stitch-bg').value,
      format: $('#stitch-fmt').value,
    });
    renderResultCard($('#img-result'), '拼接完成', res.path, res.name, `${res.width}×${res.height} · ${fmtBytes(res.output_size)}`);
  } catch (e) { toast(e.message); }
};

$('#btn-img-rot-run').onclick = async () => {
  if (!state.imageFiles.length) return toast('请先添加图片');
  try {
    toast('正在批量旋转/翻转图片…');
    const res = await api('/api/image/rotate', {
      paths: state.imageFiles.map((f) => f.path),
      op: $('#img-rot-op').value,
      format: $('#img-rot-fmt').value,
    });
    const first = res.files[0];
    const dlPath = res.zip_path || first.path;
    const dlName = res.zip_name || first.name;
    const summary = res.files.length === 1
      ? `${first.width}×${first.height} · ${fmtBytes(first.output_size)}`
      : `共处理 ${res.files.length} 张，已打包 ZIP`;
    renderResultCard($('#img-result'), '旋转/翻转完成', dlPath, dlName, summary, first.path);
  } catch (e) { toast(e.message); }
};

$('#btn-split-run').onclick = async () => {
  if (!state.imageFiles.length) return toast('请先在上方添加至少 1 张图片');
  try {
    toast('正在分割图片…');
    const res = await api('/api/image/split', {
      path: state.imageFiles[0].path,
      mode: $('#split-mode').value,
      parts: Number($('#split-parts').value),
      max_piece_height: Number($('#split-maxh').value),
      rows: Number($('#split-rows').value),
      cols: Number($('#split-cols').value),
      format: $('#split-fmt').value,
    });
    renderResultCard(
      $('#img-result'),
      '图片分割完成',
      res.zip_path,
      res.zip_name,
      `共切分 ${res.count} 张并已打包 ZIP · ${fmtBytes(res.output_size)}`,
      res.first_path,
    );
  } catch (e) { toast(e.message); }
};

// ==================== 3. PDF 工坊 ====================
const refreshPdfMerge = () => renderFileList($('#pdf-merge-list'), state.pdfMergeFiles, refreshPdfMerge, false, true);
const refreshPfi = () => renderFileList($('#pfi-list'), state.pdfFromImgFiles, refreshPfi, true, true);

$('#btn-pdf-merge-pick').onclick = async (e) => {
  e.stopPropagation();
  try {
    const res = await api('/api/pick-files', { title: '选择多个 PDF', filetypes: [['PDF 文件', '*.pdf']], multiple: true });
    res.files.forEach((p) => state.pdfMergeFiles.push({ path: p, name: p.split(/[\\/]/).pop() }));
    refreshPdfMerge();
  } catch (err) { toast(err.message); }
};
$('#btn-pdf-merge-clear').onclick = (e) => { e.stopPropagation(); state.pdfMergeFiles = []; refreshPdfMerge(); };
setupDropzone($('#pdf-merge-drop'), async (files) => {
  try {
    for (const f of files) state.pdfMergeFiles.push(await uploadFile(f));
    refreshPdfMerge();
  } catch (err) { toast(err.message); }
});
$('#btn-pdf-merge-run').onclick = async () => {
  if (state.pdfMergeFiles.length < 2) return toast('请至少选择 2 个 PDF');
  try {
    const res = await api('/api/pdf/merge', { paths: state.pdfMergeFiles.map((f) => f.path) });
    renderResultCard($('#pdf-result'), 'PDF 合并完成', res.path, res.name, `共 ${res.pages} 页 · ${fmtBytes(res.output_size)}`);
  } catch (e) { toast(e.message); }
};

async function loadSinglePdf(path, metaEl, clearBtn, setter) {
  const info = await api('/api/pdf/info', { path });
  setter(info.path);
  const lockTip = info.needs_pass
    ? '🔒 已设打开密码'
    : (info.is_encrypted ? '🔐 含权限限制' : `${info.pages} 页`);
  metaEl.textContent = `${info.name}（${lockTip} · ${fmtBytes(info.size_bytes)}）`;
  clearBtn.style.display = 'inline-flex';
}
async function pickSinglePdf(metaEl, clearBtn, setter) {
  try {
    const res = await api('/api/pick-files', { title: '选择 PDF 文件', filetypes: [['PDF 文件', '*.pdf']], multiple: false });
    if (!res.files.length) return;
    await loadSinglePdf(res.files[0], metaEl, clearBtn, setter);
  } catch (err) { toast(err.message); }
}
function bindDropSinglePdf(dropEl, metaEl, clearBtn, setter) {
  setupDropzone(dropEl, async (files) => {
    try {
      const up = await uploadFile(files[0]);
      await loadSinglePdf(up.path, metaEl, clearBtn, setter);
    } catch (err) { toast(err.message); }
  });
}
function bindClearPdf(clearBtn, metaEl, setter) {
  clearBtn.onclick = (e) => {
    if (e) e.stopPropagation();
    setter('');
    metaEl.textContent = '';
    clearBtn.style.display = 'none';
    $('#pdf-result').innerHTML = '';
    toast('已移除所选 PDF');
  };
}

$('#btn-pdf-edit-pick').onclick = (e) => { e.stopPropagation(); pickSinglePdf($('#pdf-edit-meta'), $('#btn-pdf-edit-clear'), (p) => state.pdfEditPath = p); };
bindClearPdf($('#btn-pdf-edit-clear'), $('#pdf-edit-meta'), (p) => state.pdfEditPath = p);
bindDropSinglePdf($('#pdf-edit-drop'), $('#pdf-edit-meta'), $('#btn-pdf-edit-clear'), (p) => state.pdfEditPath = p);
$('#btn-pdf-edit-run').onclick = async () => {
  if (!state.pdfEditPath) return toast('请先选择 PDF');
  try {
    const res = await api('/api/pdf/edit', {
      path: state.pdfEditPath,
      action: $('#pdf-edit-action').value,
      pages: $('#pdf-edit-pages').value,
      angle: Number($('#pdf-edit-angle').value),
    });
    renderResultCard($('#pdf-result'), 'PDF 处理完成', res.path, res.name, `${res.pages} 页 · ${fmtBytes(res.output_size)}`);
  } catch (e) { toast(e.message); }
};

$('#btn-pdf-img-pick').onclick = (e) => { e.stopPropagation(); pickSinglePdf($('#pdf-img-meta'), $('#btn-pdf-img-clear'), (p) => state.pdfImgPath = p); };
bindClearPdf($('#btn-pdf-img-clear'), $('#pdf-img-meta'), (p) => state.pdfImgPath = p);
bindDropSinglePdf($('#pdf-img-drop'), $('#pdf-img-meta'), $('#btn-pdf-img-clear'), (p) => state.pdfImgPath = p);
$('#btn-pdf-img-run').onclick = async () => {
  if (!state.pdfImgPath) return toast('请先选择 PDF');
  try {
    toast('正在渲染页面为图片…');
    const res = await api('/api/pdf/to-images', {
      path: state.pdfImgPath,
      format: $('#pdf-img-fmt').value,
      dpi: Number($('#pdf-img-dpi').value),
      pages: $('#pdf-img-pages').value,
    });
    renderResultCard($('#pdf-result'), '导出图片完成', res.path, res.name, `共 ${res.count} 张 · ${fmtBytes(res.output_size)}`);
  } catch (e) { toast(e.message); }
};

$('#btn-pfi-pick').onclick = async (e) => {
  e.stopPropagation();
  try {
    const res = await api('/api/pick-files', { title: '选择多张图片', filetypes: [['图片文件', '*.png *.jpg *.jpeg *.webp *.heic *.heif *.avif *.bmp']], multiple: true });
    res.files.forEach((p) => state.pdfFromImgFiles.push({ path: p, name: p.split(/[\\/]/).pop() }));
    refreshPfi();
  } catch (err) { toast(err.message); }
};
$('#btn-pfi-clear').onclick = (e) => { e.stopPropagation(); state.pdfFromImgFiles = []; refreshPfi(); };
setupDropzone($('#pfi-drop'), async (files) => {
  try {
    for (const f of files) state.pdfFromImgFiles.push(await uploadFile(f));
    refreshPfi();
  } catch (err) { toast(err.message); }
});
$('#btn-pfi-run').onclick = async () => {
  if (!state.pdfFromImgFiles.length) return toast('请至少选择 1 张图片');
  try {
    const res = await api('/api/pdf/from-images', { paths: state.pdfFromImgFiles.map((f) => f.path) });
    renderResultCard($('#pdf-result'), '图片合成 PDF 完成', res.path, res.name, `${res.pages} 页 · ${fmtBytes(res.output_size)}`);
  } catch (e) { toast(e.message); }
};

$('#btn-pdf-comp-pick').onclick = (e) => { e.stopPropagation(); pickSinglePdf($('#pdf-comp-meta'), $('#btn-pdf-comp-clear'), (p) => state.pdfCompPath = p); };
bindClearPdf($('#btn-pdf-comp-clear'), $('#pdf-comp-meta'), (p) => state.pdfCompPath = p);
bindDropSinglePdf($('#pdf-comp-drop'), $('#pdf-comp-meta'), $('#btn-pdf-comp-clear'), (p) => state.pdfCompPath = p);
$('#btn-pdf-comp-run').onclick = async () => {
  if (!state.pdfCompPath) return toast('请先选择 PDF');
  try {
    toast('正在压缩 PDF…');
    const res = await api('/api/pdf/compress', { path: state.pdfCompPath, level: $('#pdf-comp-level').value });
    renderResultCard($('#pdf-result'), 'PDF 压缩完成', res.path, res.name,
      `${fmtBytes(res.input_size)} → ${fmtBytes(res.output_size)}（节省 ${res.saved_pct}%）`);
  } catch (e) { toast(e.message); }
};

// PDF 加密与解锁
$('#btn-pdf-prot-pick').onclick = (e) => { e.stopPropagation(); pickSinglePdf($('#pdf-prot-meta'), $('#btn-pdf-prot-clear'), (p) => state.pdfProtPath = p); };
bindClearPdf($('#btn-pdf-prot-clear'), $('#pdf-prot-meta'), (p) => state.pdfProtPath = p);
bindDropSinglePdf($('#pdf-prot-drop'), $('#pdf-prot-meta'), $('#btn-pdf-prot-clear'), (p) => state.pdfProtPath = p);
$('#btn-pdf-protect-run').onclick = async () => {
  if (!state.pdfProtPath) return toast('请先选择 PDF 文件');
  try {
    const res = await api('/api/pdf/protect', {
      path: state.pdfProtPath,
      user_pw: $('#pdf-user-pw').value,
      owner_pw: $('#pdf-owner-pw').value,
      allow_print: $('#pdf-allow-print').checked,
      allow_copy: $('#pdf-allow-copy').checked,
    });
    renderResultCard($('#pdf-result'), 'PDF 加密完成', res.path, res.name, `${res.pages} 页 · AES-256 · ${fmtBytes(res.output_size)}`);
  } catch (e) { toast(e.message); }
};
$('#btn-pdf-unlock-run').onclick = async () => {
  if (!state.pdfProtPath) return toast('请先选择 PDF 文件');
  try {
    const res = await api('/api/pdf/unlock', {
      path: state.pdfProtPath,
      password: $('#pdf-unlock-pw').value,
    });
    renderResultCard($('#pdf-result'), 'PDF 解锁完成', res.path, res.name, `已移除密码与权限限制 · ${res.pages} 页 · ${fmtBytes(res.output_size)}`);
  } catch (e) { toast(e.message); }
};

// PDF <-> Word 互转
$('#btn-p2w-pick').onclick = (e) => {
  e.stopPropagation();
  pickSinglePdf($('#p2w-meta'), $('#btn-p2w-clear'), (p) => state.p2wPath = p);
};
bindClearPdf($('#btn-p2w-clear'), $('#p2w-meta'), (p) => state.p2wPath = p);
bindDropSinglePdf($('#p2w-drop'), $('#p2w-meta'), $('#btn-p2w-clear'), (p) => state.p2wPath = p);
$('#btn-p2w-run').onclick = async () => {
  if (!state.p2wPath) return toast('请先选择 PDF 文件');
  try {
    toast('正在转换 PDF 为 Word，请稍候…');
    const res = await api('/api/pdf/to-word', { path: state.p2wPath });
    const note = res.is_scanned ? ' · ⚠️ 检测到扫描图片型 PDF，转换后内容仍为图片' : '';
    renderResultCard($('#pdf-result'), 'PDF 转 Word 完成', res.path, res.name,
      `${res.pages} 页 · ${fmtBytes(res.output_size)}${note}`);
  } catch (e) { toast(e.message); }
};

function setW2pFile(path, name, size) {
  state.w2pPath = path;
  $('#w2p-meta').textContent = size ? `${name}（${fmtBytes(size)}）` : name;
  $('#btn-w2p-clear').style.display = 'inline-flex';
}
$('#btn-w2p-pick').onclick = async (e) => {
  e.stopPropagation();
  try {
    const res = await api('/api/pick-files', {
      title: '选择 Word 文档',
      filetypes: [['Word 文档', '*.docx *.doc'], ['所有文件', '*.*']],
      multiple: false,
    });
    if (res.files.length) setW2pFile(res.files[0], res.files[0].split(/[\\/]/).pop(), 0);
  } catch (err) { toast(err.message); }
};
bindClearPdf($('#btn-w2p-clear'), $('#w2p-meta'), (p) => state.w2pPath = p);
setupDropzone($('#w2p-drop'), async (files) => {
  try {
    const up = await uploadFile(files[0]);
    setW2pFile(up.path, up.name, up.size);
  } catch (err) { toast(err.message); }
});
$('#btn-w2p-run').onclick = async () => {
  if (!state.w2pPath) return toast('请先选择 Word 文件');
  try {
    toast('正在调用本机 Word 导出 PDF…');
    const res = await api('/api/pdf/from-word', { path: state.w2pPath });
    renderResultCard($('#pdf-result'), 'Word 转 PDF 完成', res.path, res.name,
      `${res.pages} 页 · ${fmtBytes(res.output_size)}`);
  } catch (e) { toast(e.message); }
};

// ==================== 4. 文本与杂项 ====================
function updateTextStats() {
  const v = $('#tc-input').value;
  $('#st-chars').textContent = v.length;
  $('#st-nospace').textContent = v.replace(/\s/g, '').length;
  $('#st-zh').textContent = (v.match(/[\u4e00-\u9fa5]/g) || []).length;
  $('#st-lines').textContent = v ? v.split(/\r?\n/).length : 0;
}
$('#tc-input').oninput = updateTextStats;
$$('[data-tact]').forEach((b) => {
  b.onclick = () => {
    const el = $('#tc-input');
    const act = b.dataset.tact;
    const lines = el.value.split(/\r?\n/);
    if (act === 'dedup') el.value = [...new Set(lines)].join('\n');
    else if (act === 'trim') el.value = lines.map((l) => l.trim()).join('\n');
    else if (act === 'noblank') el.value = lines.filter((l) => l.trim() !== '').join('\n');
    else if (act === 'sort') el.value = lines.sort((a, b2) => a.localeCompare(b2, 'zh-CN')).join('\n');
    else if (act === 'clear') el.value = '';
    else if (act === 'copy') { navigator.clipboard.writeText(el.value); toast('已复制到剪贴板'); }
    updateTextStats();
  };
});

$('#btn-json-fmt').onclick = () => {
  try {
    $('#tj-input').value = JSON.stringify(JSON.parse($('#tj-input').value), null, 2);
    $('#tj-msg').innerHTML = '<div class="alert alert-ok">JSON 格式校验通过</div>';
  } catch (e) { $('#tj-msg').innerHTML = `<div class="alert alert-err">语法错误：${escHtml(e.message)}</div>`; }
};
$('#btn-json-min').onclick = () => {
  try {
    $('#tj-input').value = JSON.stringify(JSON.parse($('#tj-input').value));
    $('#tj-msg').innerHTML = '<div class="alert alert-ok">已压缩为单行</div>';
  } catch (e) { $('#tj-msg').innerHTML = `<div class="alert alert-err">语法错误：${escHtml(e.message)}</div>`; }
};
$('#btn-json-copy').onclick = () => { navigator.clipboard.writeText($('#tj-input').value); toast('已复制 JSON'); };

function genQR() {
  const txt = $('#qr-text').value.trim() || '本地工具箱 · 离线二维码';
  try {
    window.drawQRCode($('#qr-canvas'), txt, 240);
    $('#qr-tip').textContent = `纯离线生成 · ${new TextEncoder().encode(txt).length} 字节`;
  } catch (e) { $('#qr-tip').textContent = e.message; }
}
$('#btn-qr-gen').onclick = genQR;
$('#qr-text').oninput = genQR;
$('#btn-qr-dl').onclick = () => {
  const a = document.createElement('a');
  a.download = 'qrcode.png';
  a.href = $('#qr-canvas').toDataURL('image/png');
  a.click();
};
genQR();

function genPasswords() {
  const len = Math.max(6, Math.min(64, Number($('#pw-len').value) || 16));
  const cnt = Math.max(1, Math.min(20, Number($('#pw-cnt').value) || 5));
  let chars = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  if (!$('#pw-noamb').checked) chars += 'olIO01';
  if ($('#pw-sym').checked) chars += '!@#$%^&*()-_=+[]?';
  const list = [];
  for (let i = 0; i < cnt; i++) {
    const arr = new Uint32Array(len);
    crypto.getRandomValues(arr);
    list.push(Array.from(arr, (n) => chars[n % chars.length]).join(''));
  }
  $('#pw-list').innerHTML = list.map((p, idx) => `
    <div class="file-item">
      <code style="font-size:14px;">${escHtml(p)}</code>
      <button class="btn btn-sm" data-idx="${idx}">复制</button>
    </div>`).join('');
  $('#pw-list').querySelectorAll('button').forEach((btn) => {
    btn.onclick = () => {
      navigator.clipboard.writeText(list[Number(btn.dataset.idx)]);
      toast('已复制密码');
    };
  });
}
$('#btn-pw-gen').onclick = genPasswords;
genPasswords();

function formatLocalDateTime(d) {
  const pad = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
function formatLocalDate(d) {
  const pad = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function parseLocalDate(str) {
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec((str || '').trim());
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

function updateTs() {
  const raw = $('#ts-in').value.trim();
  if (!raw) { $('#ts-out').textContent = '—'; return; }
  const num = Number(raw);
  if (Number.isNaN(num)) { $('#ts-out').textContent = '请输入数字时间戳'; return; }
  const ms = Math.abs(num) < 1e11 ? num * 1000 : num;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) { $('#ts-out').textContent = '时间戳超出有效范围'; return; }
  $('#ts-out').textContent = `${formatLocalDateTime(d)}（ISO: ${d.toISOString()}）`;
}
function parseLocalDateTimeInput(raw) {
  const s = (raw || '').trim();
  // 优先按本地时区解析 YYYY-M-D [H:m[:s[.ms]]]（支持 - 或 / 分隔，避免纯日期被 JS 当作 UTC 产生 8 小时偏差）
  const m = /^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[T\s]+(\d{1,2}):(\d{1,2})(?::(\d{1,2})(?:\.(\d{1,3}))?)?)?$/.exec(s);
  if (m) {
    const y = Number(m[1]), mo = Number(m[2]), day = Number(m[3]);
    const hh = m[4] !== undefined ? Number(m[4]) : 0;
    const mm = m[5] !== undefined ? Number(m[5]) : 0;
    const ss = m[6] !== undefined ? Number(m[6]) : 0;
    const ms = m[7] !== undefined ? Number(m[7].padEnd(3, '0')) : 0;
    const d = new Date(y, mo - 1, day, hh, mm, ss, ms);
    if (d.getFullYear() === y && d.getMonth() === mo - 1 && d.getDate() === day
        && d.getHours() === hh && d.getMinutes() === mm && d.getSeconds() === ss) {
      return d;
    }
    return null;
  }
  // 带显式时区（如 Z / +08:00）的 ISO 字符串交由 Date 原生解析
  const fallback = new Date(s);
  return Number.isNaN(fallback.getTime()) ? null : fallback;
}
function updateDateToTs() {
  const raw = $('#ts-date-in').value.trim();
  if (!raw) { $('#ts-date-out').textContent = '—'; state.tsLastSec = ''; state.tsLastMs = ''; return; }
  const d = parseLocalDateTimeInput(raw);
  if (!d) {
    $('#ts-date-out').textContent = '日期格式无法识别，示例：2026-11-25 12:30:00';
    state.tsLastSec = '';
    state.tsLastMs = '';
    return;
  }
  state.tsLastMs = String(d.getTime());
  state.tsLastSec = String(Math.floor(d.getTime() / 1000));
  $('#ts-date-out').textContent = `秒级：${state.tsLastSec}  |  毫秒级：${state.tsLastMs}`;
}
$('#ts-in').oninput = updateTs;
$('#ts-date-in').oninput = updateDateToTs;
$('#btn-ts-now').onclick = () => {
  const now = new Date();
  $('#ts-in').value = Math.floor(now.getTime() / 1000);
  $('#ts-date-in').value = formatLocalDateTime(now);
  updateTs();
  updateDateToTs();
};
$('#btn-ts-copy-sec').onclick = () => {
  if (!state.tsLastSec) return toast('请先输入有效日期时间');
  navigator.clipboard.writeText(state.tsLastSec);
  toast('已复制秒级时间戳');
};
$('#btn-ts-copy-ms').onclick = () => {
  if (!state.tsLastMs) return toast('请先输入有效日期时间');
  navigator.clipboard.writeText(state.tsLastMs);
  toast('已复制毫秒级时间戳');
};
$('#btn-ts-now').click();

function updateRegex() {
  const pat = $('#rx-pat').value;
  const txt = $('#rx-text').value;
  if (!pat) { $('#rx-out').textContent = '请输入正则表达式'; return; }
  try {
    const matches = [...txt.matchAll(new RegExp(pat, 'g'))].map((m) => m[0]);
    $('#rx-out').textContent = matches.length ? `匹配到 ${matches.length} 处：${matches.slice(0, 20).join(' | ')}` : '无匹配结果';
  } catch (e) { $('#rx-out').textContent = `正则有误：${e.message}`; }
}
$('#rx-pat').oninput = updateRegex;
$('#rx-text').oninput = updateRegex;

$('#btn-rn-folder').onclick = async () => {
  const res = await api('/api/pick-folder', { title: '选择要批量重命名的文件夹' });
  if (res.folder) $('#rn-folder').value = res.folder;
};
$('#btn-rn-preview').onclick = async () => {
  try {
    const res = await api('/api/rename/preview', {
      folder: $('#rn-folder').value.trim(),
      find: $('#rn-find').value,
      replace: $('#rn-replace').value,
      prefix: $('#rn-prefix').value,
      suffix: $('#rn-suffix').value,
      use_regex: $('#rn-regex').checked,
      numbering: $('#rn-num').checked,
      start_num: Number($('#rn-start').value) || 1,
      pad_digits: Number($('#rn-pad').value) || 2,
      ext_filter: $('#rn-ext').value,
      new_ext: $('#rn-newext').value,
      ext_case: $('#rn-extcase').value,
    });
    state.renamePreview = res;
    $('#rn-summary').innerHTML = `<div class="alert ${res.conflicts ? 'alert-err' : 'alert-ok'}">共 ${res.total} 个文件，将改名 ${res.changed} 个，重名冲突 ${res.conflicts} 个</div>`;
    $('#rn-table-wrap').style.display = 'block';
    $('#rn-tbody').innerHTML = res.items.map((it) => `
      <tr>
        <td>${escHtml(it.old_name)}</td>
        <td><strong>${escHtml(it.new_name)}</strong></td>
        <td>${it.conflict ? '<span class="badge badge-warn">冲突</span>' : (it.changed ? '<span class="badge badge-info">改名</span>' : '不变')}</td>
      </tr>`).join('');
    $('#btn-rn-exec').disabled = !(res.changed > 0 && res.conflicts === 0);
  } catch (e) { toast(e.message); }
};
$('#btn-rn-exec').onclick = async () => {
  if (!state.renamePreview) return;
  if (!confirm(`确定重命名这 ${state.renamePreview.changed} 个文件吗？`)) return;
  try {
    const res = await api('/api/rename/execute', {
      folder: state.renamePreview.folder,
      items: state.renamePreview.items,
    });
    toast(`已成功重命名 ${res.renamed} 个文件`);
    $('#btn-rn-preview').click();
  } catch (e) { toast(e.message); }
};

// ZIP 中文文件名乱码修复
function setZipFixFile(path, name, size) {
  state.zipFixPath = path;
  $('#zipfix-meta').textContent = size ? `${name}（${fmtBytes(size)}）` : name;
  $('#btn-zipfix-clear').style.display = 'inline-flex';
}
$('#btn-zipfix-pick').onclick = async (e) => {
  e.stopPropagation();
  try {
    const res = await api('/api/pick-files', { title: '选择 ZIP 压缩包', filetypes: [['ZIP 压缩包', '*.zip']], multiple: false });
    if (res.files.length) setZipFixFile(res.files[0], res.files[0].split(/[\\/]/).pop(), 0);
  } catch (err) { toast(err.message); }
};
$('#btn-zipfix-clear').onclick = (e) => {
  e.stopPropagation();
  state.zipFixPath = '';
  $('#zipfix-meta').textContent = '';
  $('#btn-zipfix-clear').style.display = 'none';
  $('#zipfix-result').innerHTML = '';
};
setupDropzone($('#zipfix-drop'), async (files) => {
  try {
    const up = await uploadFile(files[0]);
    setZipFixFile(up.path, up.name, up.size);
  } catch (err) { toast(err.message); }
});
$('#btn-zipfix-run').onclick = async () => {
  if (!state.zipFixPath) return toast('请先选择 ZIP 压缩包');
  try {
    toast('正在修复 ZIP 文件名编码…');
    const res = await api('/api/file/zip-fix', {
      path: state.zipFixPath,
      source_encoding: $('#zipfix-enc').value,
    });
    renderResultCard(
      $('#zipfix-result'),
      'ZIP 编码修复完成',
      res.path,
      res.name,
      `共 ${res.total} 个条目，修复 ${res.fixed} 个 · ${fmtBytes(res.output_size)}`,
    );
    const changed = res.items.filter((i) => i.changed);
    if (changed.length) {
      const listHtml = changed.slice(0, 10).map((i) => `${escHtml(i.old)}  →  ${escHtml(i.new)}`).join('\n');
      $('#zipfix-result').insertAdjacentHTML('beforeend', `<div class="code-pre">${listHtml}</div>`);
    }
  } catch (e) { toast(e.message); }
};

// 文本 / CSV 编码乱码修复
function setTxtFixFile(path, name, size) {
  state.txtFixPath = path;
  $('#txtfix-meta').textContent = size ? `${name}（${fmtBytes(size)}）` : name;
  $('#btn-txtfix-clear').style.display = 'inline-flex';
}
$('#btn-txtfix-pick').onclick = async (e) => {
  e.stopPropagation();
  try {
    const res = await api('/api/pick-files', {
      title: '选择文本/CSV文件',
      filetypes: [['文本与表格文件', '*.txt *.csv *.srt *.lrc *.log *.json *.xml *.html *.md'], ['所有文件', '*.*']],
      multiple: false,
    });
    if (res.files.length) setTxtFixFile(res.files[0], res.files[0].split(/[\\/]/).pop(), 0);
  } catch (err) { toast(err.message); }
};
$('#btn-txtfix-clear').onclick = (e) => {
  e.stopPropagation();
  state.txtFixPath = '';
  $('#txtfix-meta').textContent = '';
  $('#btn-txtfix-clear').style.display = 'none';
  $('#txtfix-result').innerHTML = '';
};
setupDropzone($('#txtfix-drop'), async (files) => {
  try {
    const up = await uploadFile(files[0]);
    setTxtFixFile(up.path, up.name, up.size);
  } catch (err) { toast(err.message); }
});
$('#btn-txtfix-run').onclick = async () => {
  if (!state.txtFixPath) return toast('请先选择文本文件');
  try {
    toast('正在转换编码…');
    const res = await api('/api/file/text-fix', {
      path: state.txtFixPath,
      source_encoding: $('#txtfix-src').value,
      target_encoding: $('#txtfix-dst').value,
    });
    renderResultCard(
      $('#txtfix-result'),
      '文本编码修复完成',
      res.path,
      res.name,
      `识别编码 ${res.detected_encoding} → ${res.target_encoding} · ${fmtBytes(res.output_size)}`,
    );
    if (res.preview) {
      $('#txtfix-result').insertAdjacentHTML('beforeend', `<div class="code-pre">${escHtml(res.preview)}</div>`);
    }
  } catch (e) { toast(e.message); }
};

// 文件哈希校验与比对
function updateHashCompare() {
  const expect = $('#hash-expect').value.trim().toLowerCase().replace(/\s+/g, '');
  const out = $('#hash-compare-out');
  if (!expect || !state.hashData) { out.innerHTML = ''; return; }
  const pairs = [
    ['MD5', state.hashData.md5],
    ['SHA1', state.hashData.sha1],
    ['SHA256', state.hashData.sha256],
    ['CRC32', state.hashData.crc32],
  ];
  const matched = pairs.find(([, v]) => v.toLowerCase() === expect);
  if (matched) {
    out.innerHTML = `<div class="alert alert-ok">✅ 校验通过！与当前文件的 <strong>${matched[0]}</strong> 完全一致。</div>`;
  } else {
    out.innerHTML = `<div class="alert alert-err">❌ 校验不匹配！输入值与该文件的 MD5 / SHA1 / SHA256 / CRC32 均不一致。</div>`;
  }
}
async function runFileHash(path) {
  try {
    toast('正在计算文件哈希…');
    const res = await api('/api/file/hash', { path });
    state.hashData = res;
    $('#hash-meta').textContent = `${res.name}（${fmtBytes(res.size_bytes)}）`;
    const rows = [
      ['MD5', res.md5],
      ['SHA1', res.sha1],
      ['SHA256', res.sha256],
      ['CRC32', res.crc32],
    ];
    $('#hash-values').innerHTML = rows.map(([k, v]) => `
      <div class="file-item">
        <div style="min-width:0; word-break:break-all;"><strong>${k}：</strong><code>${escHtml(v)}</code></div>
        <button class="btn btn-sm js-copy-hash" data-val="${escHtml(v)}">复制</button>
      </div>`).join('');
    $('#hash-values').querySelectorAll('.js-copy-hash').forEach((btn) => {
      btn.onclick = () => { navigator.clipboard.writeText(btn.dataset.val); toast('已复制哈希值'); };
    });
    updateHashCompare();
  } catch (e) { toast(e.message); }
}
$('#btn-hash-pick').onclick = async (e) => {
  e.stopPropagation();
  try {
    const res = await api('/api/pick-files', { title: '选择要计算哈希的文件', filetypes: [['所有文件', '*.*']], multiple: false });
    if (res.files.length) runFileHash(res.files[0]);
  } catch (err) { toast(err.message); }
};
$('#btn-hash-clear').onclick = (e) => {
  e.stopPropagation();
  state.hashData = null;
  $('#hash-meta').textContent = '';
  $('#hash-values').innerHTML = '';
  $('#hash-compare-out').innerHTML = '';
};
setupDropzone($('#hash-drop'), async (files) => {
  try {
    toast('正在接收文件…');
    const up = await uploadFile(files[0]);
    runFileHash(up.path);
  } catch (err) { toast(err.message); }
});
$('#hash-expect').oninput = updateHashCompare;

// ==================== 5. 计算与换算 ====================
function fmtMonths(m) {
  const y = Math.floor(m / 12);
  const rem = m % 12;
  if (y && rem) return `${y} 年 ${rem} 个月`;
  if (y) return `${y} 年`;
  return `${rem} 个月`;
}

function calcLoan() {
  const type = $('#ln-type').value;
  const P = (Number($('#ln-amount').value) || 0) * 10000;
  const r = Math.max(0, Number($('#ln-rate').value) || 0) / 100 / 12;
  const years = Math.max(1, Math.min(40, Number($('#ln-years').value) || 30));
  const n = years * 12;
  const prepay = Math.max(0, Number($('#ln-prepay').value) || 0) * 10000;
  const preYear = Math.max(1, Math.floor(Number($('#ln-preyear').value) || 3));
  const preMonth = preYear * 12;

  if (P <= 0) {
    $('#ln-out').innerHTML = '';
    $('#ln-compare').innerHTML = '';
    return;
  }

  let origFirstLabel = '';
  let origFirstVal = 0;
  let totalInterest = 0;
  let remain = 0;
  let oldLeftInterest = 0;
  const invalidPreYear = preMonth >= n;
  const leftN = Math.max(0, n - preMonth);

  // 方案 A（年限不变、减月供）与 方案 B（月供不变、缩年限）
  let newFirstA = 0, savedA = 0;
  let newMonthsB = leftN, cutMonthsB = 0, savedB = 0;

  if (type === 'equal_payment') {
    const monthly = r > 0 ? (P * r * Math.pow(1 + r, n) / (Math.pow(1 + r, n) - 1)) : (P / n);
    origFirstLabel = '原月供（等额本息）';
    origFirstVal = monthly;
    totalInterest = monthly * n - P;
    remain = invalidPreYear ? 0 : (r > 0
      ? P * (Math.pow(1 + r, n) - Math.pow(1 + r, preMonth)) / (Math.pow(1 + r, n) - 1)
      : P * (1 - preMonth / n));
    oldLeftInterest = invalidPreYear ? 0 : Math.max(0, monthly * leftN - remain);

    if (!invalidPreYear && prepay > 0 && remain > 0) {
      const afterP = Math.max(0, remain - prepay);
      // 方案 A：年限不变，减少月供
      newFirstA = afterP > 0
        ? (r > 0 ? afterP * r * Math.pow(1 + r, leftN) / (Math.pow(1 + r, leftN) - 1) : afterP / leftN)
        : 0;
      const newLeftIntA = Math.max(0, newFirstA * leftN - afterP);
      savedA = Math.max(0, oldLeftInterest - newLeftIntA);

      // 方案 B：月供不变，缩短年限（逐月精确模拟）
      if (afterP <= 0) {
        newMonthsB = 0;
        savedB = oldLeftInterest;
      } else {
        let bal = afterP;
        let intB = 0;
        let mCnt = 0;
        while (bal > 0.01 && mCnt < leftN) {
          const interest = bal * r;
          const pay = Math.min(bal + interest, monthly);
          intB += interest;
          bal = bal + interest - pay;
          mCnt++;
        }
        newMonthsB = mCnt;
        savedB = Math.max(0, oldLeftInterest - intB);
      }
      cutMonthsB = Math.max(0, leftN - newMonthsB);
    } else {
      newFirstA = monthly;
    }
  } else {
    // 等额本金
    const mp = P / n;
    const firstM = mp + P * r;
    const dec = mp * r;
    origFirstLabel = `原首月月供（月减 ¥${dec.toFixed(1)}）`;
    origFirstVal = firstM;
    totalInterest = P * r * (n + 1) / 2;
    remain = invalidPreYear ? 0 : Math.max(0, P - mp * preMonth);
    oldLeftInterest = invalidPreYear ? 0 : remain * r * (leftN + 1) / 2;

    if (!invalidPreYear && prepay > 0 && remain > 0) {
      const afterP = Math.max(0, remain - prepay);
      // 方案 A：年限不变，降低每月还本额
      const newMp = afterP / leftN;
      newFirstA = afterP > 0 ? newMp + afterP * r : 0;
      const newLeftIntA = afterP * r * (leftN + 1) / 2;
      savedA = Math.max(0, oldLeftInterest - newLeftIntA);

      // 方案 B：每月还本不变，缩短年限
      if (afterP <= 0) {
        newMonthsB = 0;
        savedB = oldLeftInterest;
      } else {
        let bal = afterP;
        let intB = 0;
        let mCnt = 0;
        while (bal > 0.01 && mCnt < leftN) {
          intB += bal * r;
          bal = Math.max(0, bal - mp);
          mCnt++;
        }
        newMonthsB = mCnt;
        savedB = Math.max(0, oldLeftInterest - intB);
      }
      cutMonthsB = Math.max(0, leftN - newMonthsB);
    } else {
      newFirstA = mp + remain * r;
    }
  }

  $('#ln-out').innerHTML = `
    <div class="stat-box"><div class="k">${escHtml(origFirstLabel)}</div><div class="v">¥ ${origFirstVal.toFixed(2)}</div></div>
    <div class="stat-box"><div class="k">原总利息</div><div class="v">¥ ${(totalInterest / 10000).toFixed(2)} 万</div></div>
    <div class="stat-box"><div class="k">第 ${preYear} 年末剩余本金</div><div class="v">¥ ${(remain / 10000).toFixed(2)} 万</div></div>
    <div class="stat-box"><div class="k">原剩余总利息</div><div class="v">¥ ${(oldLeftInterest / 10000).toFixed(2)} 万</div></div>`;

  if (prepay <= 0) {
    $('#ln-compare').innerHTML = '';
    return;
  }
  if (invalidPreYear) {
    $('#ln-compare').innerHTML = `<div class="alert alert-warn" style="margin-top:10px;">⚠️ 第 ${preYear} 年已不小于贷款总年限（${years} 年），贷款已正常结清，请将“第几年提前还”调小至 ${Math.max(1, years - 1)} 年以内。</div>`;
    return;
  }
  const paidOffTip = prepay >= remain ? '（已一次全额结清！）' : '';
  const extraSave = Math.max(0, savedB - savedA);
  $('#ln-compare').innerHTML = `
    <div class="grid-2" style="margin-top:10px;">
      <div class="card" style="margin:0; box-shadow:none;">
        <h3>方案 A：年限不变，减少月供 ${paidOffTip}</h3>
        <div class="info-grid" style="margin:0;">
          <div class="stat-box"><div class="k">${type === 'equal_payment' ? '新月供' : '新首月月供'}</div><div class="v">¥ ${newFirstA.toFixed(2)}</div></div>
          <div class="stat-box"><div class="k">节省总利息</div><div class="v" style="color:var(--ok);">¥ ${(savedA / 10000).toFixed(2)} 万</div></div>
        </div>
      </div>
      <div class="card" style="margin:0; box-shadow:none;">
        <h3>方案 B：月供不变，缩短年限 ${paidOffTip}</h3>
        <div class="info-grid" style="margin:0;">
          <div class="stat-box"><div class="k">缩短还款期</div><div class="v">${fmtMonths(cutMonthsB)}（余 ${fmtMonths(newMonthsB)}）</div></div>
          <div class="stat-box"><div class="k">节省总利息</div><div class="v" style="color:var(--ok);">¥ ${(savedB / 10000).toFixed(2)} 万</div></div>
        </div>
      </div>
    </div>
    ${extraSave > 100 ? `<div class="alert alert-ok">💡 对比结论：选「月供不变、缩短年限」比「减少月供」可多省利息 <strong>¥ ${(extraSave / 10000).toFixed(2)} 万</strong>。</div>` : ''}`;
}
['#ln-type', '#ln-amount', '#ln-rate', '#ln-years', '#ln-prepay', '#ln-preyear'].forEach((s) => {
  $(s).oninput = calcLoan;
  $(s).onchange = calcLoan;
});
calcLoan();

function calcCompound() {
  const init = Number($('#cp-init').value) || 0;
  const mon = Number($('#cp-month').value) || 0;
  const rate = (Number($('#cp-rate').value) || 0) / 100 / 12;
  const months = Math.max(1, (Number($('#cp-years').value) || 10) * 12);
  let total = init;
  for (let i = 0; i < months; i++) total = total * (1 + rate) + mon;
  const principal = init + mon * months;
  const profit = total - principal;
  $('#cp-out').innerHTML = `
    <div class="stat-box"><div class="k">累计投入本金</div><div class="v">¥ ${principal.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}</div></div>
    <div class="stat-box"><div class="k">期末总资产</div><div class="v">¥ ${total.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}</div></div>
    <div class="stat-box"><div class="k">复利净收益</div><div class="v" style="color:var(--ok);">¥ ${profit.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}</div></div>`;
}
['#cp-init', '#cp-month', '#cp-rate', '#cp-years'].forEach((s) => $(s).oninput = calcCompound);
calcCompound();

const nowLocal = new Date();
const after90 = new Date(nowLocal.getFullYear(), nowLocal.getMonth(), nowLocal.getDate() + 90);
$('#dt-start').value = formatLocalDate(nowLocal);
$('#dt-end').value = formatLocalDate(after90);
function calcDate() {
  const d1 = parseLocalDate($('#dt-start').value);
  const d2 = parseLocalDate($('#dt-end').value);
  if (!d1 || !d2) return;
  const diffDays = Math.round((d2 - d1) / 86400000);
  let workdays = 0;
  const step = diffDays >= 0 ? 1 : -1;
  for (let i = 0; i !== diffDays; i += step) {
    const cur = new Date(d1.getFullYear(), d1.getMonth(), d1.getDate() + i);
    const wd = cur.getDay();
    if (wd !== 0 && wd !== 6) workdays++;
  }
  $('#dt-out').innerHTML = `
    <div class="stat-box"><div class="k">相差自然日</div><div class="v">${diffDays} 天</div></div>
    <div class="stat-box"><div class="k">折合周数</div><div class="v">${(Math.abs(diffDays) / 7).toFixed(1)} 周</div></div>
    <div class="stat-box"><div class="k">约计工作日（不含周末）</div><div class="v">${workdays} 天</div></div>`;
}
$('#dt-start').oninput = calcDate;
$('#dt-end').oninput = calcDate;
calcDate();

function calcUnits() {
  const val = Number($('#u-val').value) || 0;
  const mult = { KB: 1024, MB: 1024 ** 2, GB: 1024 ** 3, TB: 1024 ** 4 }[$('#u-unit').value];
  const bytes = val * mult;
  $('#u-out').innerHTML = [
    ['KB', bytes / 1024], ['MB', bytes / 1024 ** 2], ['GB', bytes / 1024 ** 3], ['TB', bytes / 1024 ** 4],
  ].map(([k, v]) => `<div class="stat-box"><div class="k">${k}</div><div class="v">${Number(v.toFixed(4))}</div></div>`).join('');
}
$('#u-val').oninput = calcUnits;
$('#u-unit').onchange = calcUnits;
calcUnits();

function updateColor(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return;
  const h = '#' + m[1].toLowerCase();
  $('#col-pick').value = h;
  $('#col-hex').value = h;
  const r = parseInt(m[1].slice(0, 2), 16);
  const g = parseInt(m[1].slice(2, 4), 16);
  const b = parseInt(m[1].slice(4, 6), 16);
  const rn = r / 255, gn = g / 255, bn = b / 255;
  const max = Math.max(rn, gn, bn), min = Math.min(rn, gn, bn), d = max - min;
  let hh = 0, ss = 0, ll = (max + min) / 2;
  if (d) {
    ss = d / (1 - Math.abs(2 * ll - 1));
    if (max === rn) hh = ((gn - bn) / d) % 6;
    else if (max === gn) hh = (bn - rn) / d + 2;
    else hh = (rn - gn) / d + 4;
    hh = Math.round(hh * 60);
    if (hh < 0) hh += 360;
  }
  $('#col-out').innerHTML = `
    <div class="stat-box"><div class="k">RGB</div><div class="v">rgb(${r}, ${g}, ${b})</div></div>
    <div class="stat-box"><div class="k">HSL</div><div class="v">hsl(${hh}, ${Math.round(ss * 100)}%, ${Math.round(ll * 100)}%)</div></div>`;
}
$('#col-pick').oninput = (e) => updateColor(e.target.value);
$('#col-hex').oninput = (e) => updateColor(e.target.value);
updateColor('#2563eb');
