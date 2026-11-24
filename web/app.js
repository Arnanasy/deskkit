const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const PAGE_META = {
  video: ['视频工坊', '自动诊断编码，一键转 Win 全兼容 MP4（支持无损秒换壳与显卡硬编）'],
  image: ['图片工坊', '批量压缩、格式互转、拼长图与宫格，默认清除 EXIF 隐私信息'],
  pdf: ['PDF 工坊', '纯本地合并、拆分、删页、旋转、转图与压缩，隐私文档不上传云端'],
  text: ['文本与杂项', '文本去重统计、JSON 格式化、离线二维码、强密码与批量文件重命名'],
  calc: ['计算与换算', '无广告房贷提前还款、复利定投、日期推算、存储单位与色值换算'],
};

const state = {
  outputDir: '',
  videoPath: '',
  videoTaskId: '',
  videoPoll: null,
  imageFiles: [],
  pdfMergeFiles: [],
  pdfEditPath: '',
  pdfImgPath: '',
  pdfFromImgFiles: [],
  pdfCompPath: '',
  p2wPath: '',
  w2pPath: '',
  renamePreview: null,
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
  if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'ico'].includes(ext)) {
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
  const canInline = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'ico', 'pdf', 'mp4', 'mp3', 'm4a', 'wav'].includes(ext);
  const autoShow = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'ico'].includes(ext);

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
    $('#vc-nvenc').checked = false;
    $('#vcomp-nvenc').checked = false;
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

async function startVideoJob(mode, options) {
  if (!state.videoPath) return toast('请先选择视频文件');
  try {
    const task = await api('/api/video/start', { path: state.videoPath, mode, options });
    clearInterval(state.videoPoll);
    state.videoTaskId = task.id;
    $('#video-progress-box').style.display = 'block';
    $('#vp-desc').textContent = task.mode_desc;
    $('#vp-bar').style.width = '2%';
    $('#vp-stat').className = 'badge badge-info';
    $('#vp-stat').textContent = '启动中…';
    $('#vp-actions').innerHTML = `<button class="btn btn-sm btn-danger" id="btn-v-cancel">取消任务</button>`;
    $('#vp-preview').innerHTML = '';
    $('#btn-v-cancel').onclick = () => api('/api/video/cancel', { id: task.id });

    state.videoPoll = setInterval(async () => {
      try {
        const cur = await api(`/api/video/task/${task.id}`);
        $('#vp-bar').style.width = `${cur.progress}%`;
        if (cur.status === 'running') {
          $('#vp-stat').textContent = `${cur.progress}%${cur.speed ? ' · ' + cur.speed : ''}`;
        } else {
          clearInterval(state.videoPoll);
          if (cur.status === 'done') {
            $('#vp-bar').style.width = '100%';
            $('#vp-stat').className = 'badge badge-ok';
            $('#vp-stat').textContent = `完成 · 耗时 ${cur.elapsed}s`;
            const ratio = cur.input_size ? `${fmtBytes(cur.input_size)} → ${fmtBytes(cur.output_size)}` : fmtBytes(cur.output_size);
            $('#vp-actions').innerHTML = `
              <span style="font-size:12px;color:var(--muted);">${escHtml(cur.output_name)} (${escHtml(ratio)})</span>
              <button class="btn btn-sm js-toggle-vprev">👁️ 收起预览</button>
              <button class="btn btn-sm js-open-path">📂 打开所在文件夹</button>
              <a class="btn btn-sm btn-primary" href="${downloadUrl(cur.output_path)}">⬇️ 下载</a>`;
            $('#vp-actions .js-open-path').onclick = () => openPath(cur.output_path);
            const pvSlot = $('#vp-preview');
            pvSlot.innerHTML = buildPreviewHtml(cur.output_path);
            let pvShown = true;
            const pvBtn = $('#vp-actions .js-toggle-vprev');
            pvBtn.onclick = () => {
              pvShown = !pvShown;
              pvSlot.innerHTML = pvShown ? buildPreviewHtml(cur.output_path) : '';
              pvBtn.textContent = pvShown ? '👁️ 收起预览' : '👁️ 预览结果';
            };
            toast('视频处理完成！');
          } else if (cur.status === 'cancelled') {
            $('#vp-stat').className = 'badge badge-warn';
            $('#vp-stat').textContent = '已取消';
            $('#vp-actions').innerHTML = '';
          } else {
            $('#vp-stat').className = 'badge badge-warn';
            $('#vp-stat').textContent = '失败';
            $('#vp-actions').innerHTML = `<div class="alert alert-err" style="width:100%;">${escHtml(cur.error)}</div>`;
          }
        }
      } catch (err) {
        clearInterval(state.videoPoll);
        toast(err.message);
      }
    }, 450);
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
  use_nvenc: $('#vc-nvenc').checked,
});
$('#btn-run-audio').onclick = () => startVideoJob('audio', { audio_format: $('#vaudio-fmt').value });
$('#btn-run-gif').onclick = () => startVideoJob('gif', {
  start: $('#vgif-start').value,
  end: $('#vgif-end').value,
  width: Number($('#vgif-width').value),
  fps: Number($('#vgif-fps').value),
});

// ==================== 2. 图片工坊 ====================
function renderFileList(el, arr, onRemove, showThumb = false) {
  el.innerHTML = arr.map((f, idx) => `
    <div class="file-item">
      <div class="row" style="gap:10px; min-width:0;">
        ${showThumb ? `<img class="thumb-mini" src="${previewUrl(f.path)}" alt="">` : ''}
        <div><strong>${idx + 1}. ${escHtml(f.name)}</strong> <span class="meta">${f.size ? fmtBytes(f.size) : ''}</span></div>
      </div>
      <button class="btn btn-sm" data-idx="${idx}">移除</button>
    </div>`).join('');
  el.querySelectorAll('button').forEach((b) => {
    b.onclick = () => { arr.splice(Number(b.dataset.idx), 1); onRemove(); };
  });
}

const refreshImgList = () => renderFileList($('#img-file-list'), state.imageFiles, refreshImgList, true);

$('#btn-img-pick').onclick = async (e) => {
  e.stopPropagation();
  try {
    const res = await api('/api/pick-files', {
      title: '选择图片',
      filetypes: [['图片文件', '*.png *.jpg *.jpeg *.webp *.bmp *.tiff'], ['所有文件', '*.*']],
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

// ==================== 3. PDF 工坊 ====================
const refreshPdfMerge = () => renderFileList($('#pdf-merge-list'), state.pdfMergeFiles, refreshPdfMerge);
const refreshPfi = () => renderFileList($('#pfi-list'), state.pdfFromImgFiles, refreshPfi, true);

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

async function pickSinglePdf(metaEl, clearBtn, setter) {
  try {
    const res = await api('/api/pick-files', { title: '选择 PDF 文件', filetypes: [['PDF 文件', '*.pdf']], multiple: false });
    if (!res.files.length) return;
    const info = await api('/api/pdf/info', { path: res.files[0] });
    setter(info.path);
    metaEl.textContent = `${info.name}（${info.pages} 页 · ${fmtBytes(info.size_bytes)}）`;
    clearBtn.style.display = 'inline-flex';
  } catch (err) { toast(err.message); }
}
function bindClearPdf(clearBtn, metaEl, setter) {
  clearBtn.onclick = () => {
    setter('');
    metaEl.textContent = '';
    clearBtn.style.display = 'none';
    $('#pdf-result').innerHTML = '';
    toast('已移除所选 PDF');
  };
}
$('#btn-pdf-edit-pick').onclick = () => pickSinglePdf($('#pdf-edit-meta'), $('#btn-pdf-edit-clear'), (p) => state.pdfEditPath = p);
bindClearPdf($('#btn-pdf-edit-clear'), $('#pdf-edit-meta'), (p) => state.pdfEditPath = p);
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

$('#btn-pdf-img-pick').onclick = () => pickSinglePdf($('#pdf-img-meta'), $('#btn-pdf-img-clear'), (p) => state.pdfImgPath = p);
bindClearPdf($('#btn-pdf-img-clear'), $('#pdf-img-meta'), (p) => state.pdfImgPath = p);
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

$('#btn-pfi-pick').onclick = async () => {
  const res = await api('/api/pick-files', { title: '选择多张图片', filetypes: [['图片文件', '*.png *.jpg *.jpeg *.webp *.bmp']], multiple: true });
  res.files.forEach((p) => state.pdfFromImgFiles.push({ path: p, name: p.split(/[\\/]/).pop() }));
  refreshPfi();
};
$('#btn-pfi-clear').onclick = () => { state.pdfFromImgFiles = []; refreshPfi(); };
$('#btn-pfi-run').onclick = async () => {
  if (!state.pdfFromImgFiles.length) return toast('请至少选择 1 张图片');
  try {
    const res = await api('/api/pdf/from-images', { paths: state.pdfFromImgFiles.map((f) => f.path) });
    renderResultCard($('#pdf-result'), '图片合成 PDF 完成', res.path, res.name, `${res.pages} 页 · ${fmtBytes(res.output_size)}`);
  } catch (e) { toast(e.message); }
};

$('#btn-pdf-comp-pick').onclick = () => pickSinglePdf($('#pdf-comp-meta'), $('#btn-pdf-comp-clear'), (p) => state.pdfCompPath = p);
bindClearPdf($('#btn-pdf-comp-clear'), $('#pdf-comp-meta'), (p) => state.pdfCompPath = p);
$('#btn-pdf-comp-run').onclick = async () => {
  if (!state.pdfCompPath) return toast('请先选择 PDF');
  try {
    toast('正在压缩 PDF…');
    const res = await api('/api/pdf/compress', { path: state.pdfCompPath, level: $('#pdf-comp-level').value });
    renderResultCard($('#pdf-result'), 'PDF 压缩完成', res.path, res.name,
      `${fmtBytes(res.input_size)} → ${fmtBytes(res.output_size)}（节省 ${res.saved_pct}%）`);
  } catch (e) { toast(e.message); }
};

// PDF <-> Word 互转
$('#btn-p2w-pick').onclick = (e) => {
  e.stopPropagation();
  pickSinglePdf($('#p2w-meta'), $('#btn-p2w-clear'), (p) => state.p2wPath = p);
};
bindClearPdf($('#btn-p2w-clear'), $('#p2w-meta'), (p) => state.p2wPath = p);
setupDropzone($('#p2w-drop'), async (files) => {
  try {
    const up = await uploadFile(files[0]);
    const info = await api('/api/pdf/info', { path: up.path });
    state.p2wPath = info.path;
    $('#p2w-meta').textContent = `${info.name}（${info.pages} 页 · ${fmtBytes(info.size_bytes)}）`;
    $('#btn-p2w-clear').style.display = 'inline-flex';
  } catch (err) { toast(err.message); }
});
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

function updateTs() {
  const raw = $('#ts-in').value.trim();
  if (!raw) return;
  const num = Number(raw);
  if (Number.isNaN(num)) { $('#ts-out').textContent = '请输入数字时间戳'; return; }
  const ms = raw.length <= 10 ? num * 1000 : num;
  const d = new Date(ms);
  $('#ts-out').textContent = `${d.toLocaleString('zh-CN', { hour12: false })}（ISO: ${d.toISOString()}）`;
}
$('#ts-in').oninput = updateTs;
$('#btn-ts-now').onclick = () => { $('#ts-in').value = Math.floor(Date.now() / 1000); updateTs(); };
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
      ext_filter: $('#rn-ext').value,
      new_ext: $('#rn-newext').value,
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

// ==================== 5. 计算与换算 ====================
function calcLoan() {
  const P = (Number($('#ln-amount').value) || 0) * 10000;
  const r = (Number($('#ln-rate').value) || 0) / 100 / 12;
  const n = Math.max(1, (Number($('#ln-years').value) || 30) * 12);
  const prepay = (Number($('#ln-prepay').value) || 0) * 10000;
  const preMonth = Math.min(n - 1, Math.max(1, (Number($('#ln-preyear').value) || 3) * 12));
  if (P <= 0 || r <= 0) return;

  const monthly = P * r * Math.pow(1 + r, n) / (Math.pow(1 + r, n) - 1);
  const totalInterest = monthly * n - P;

  // 等额本息第 preMonth 期剩余本金
  let remain = P * (Math.pow(1 + r, n) - Math.pow(1 + r, preMonth)) / (Math.pow(1 + r, n) - 1);
  let savedInterest = 0;
  let newMonthly = monthly;
  if (prepay > 0 && remain > 0) {
    const afterP = Math.max(0, remain - prepay);
    const leftN = n - preMonth;
    newMonthly = afterP > 0 ? afterP * r * Math.pow(1 + r, leftN) / (Math.pow(1 + r, leftN) - 1) : 0;
    const oldLeftInterest = monthly * leftN - remain;
    const newLeftInterest = newMonthly * leftN - afterP;
    savedInterest = Math.max(0, oldLeftInterest - newLeftInterest);
  }
  $('#ln-out').innerHTML = `
    <div class="stat-box"><div class="k">原月供（等额本息）</div><div class="v">¥ ${monthly.toFixed(2)}</div></div>
    <div class="stat-box"><div class="k">原总利息</div><div class="v">¥ ${(totalInterest / 10000).toFixed(2)} 万</div></div>
    <div class="stat-box"><div class="k">提前还后新月供（年限不变）</div><div class="v">¥ ${newMonthly.toFixed(2)}</div></div>
    <div class="stat-box"><div class="k">预计节省总利息</div><div class="v" style="color:var(--ok);">¥ ${(savedInterest / 10000).toFixed(2)} 万</div></div>`;
}
['#ln-amount', '#ln-rate', '#ln-years', '#ln-prepay', '#ln-preyear'].forEach((s) => $(s).oninput = calcLoan);
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

const todayStr = new Date().toISOString().slice(0, 10);
const nextYearStr = new Date(Date.now() + 90 * 86400000).toISOString().slice(0, 10);
$('#dt-start').value = todayStr;
$('#dt-end').value = nextYearStr;
function calcDate() {
  const d1 = new Date($('#dt-start').value);
  const d2 = new Date($('#dt-end').value);
  if (isNaN(d1) || isNaN(d2)) return;
  const diffDays = Math.round((d2 - d1) / 86400000);
  let workdays = 0;
  const step = diffDays >= 0 ? 1 : -1;
  for (let i = 0; i !== diffDays; i += step) {
    const cur = new Date(d1.getTime() + i * 86400000);
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
