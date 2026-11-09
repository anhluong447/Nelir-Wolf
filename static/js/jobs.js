// Translation jobs: translate menu, batch setup dialog, non-blocking job dock.
import { api, streamEvents } from './api.js';
import { renderText } from './codes.js';
import { $, $$, basename, debounce, esc, fmt, html, icon, on } from './dom.js';
import { loadRows, typeLabel, updateRowInList } from './list.js';
import { defineAction, emit, state } from './state.js';
import { bindMenu, confirmDialog, openDialog, toast } from './ui.js';

const refreshSoon = debounce(() => emit('stats-dirty'), 600);

function renderTranslateMenu() {
  const pageTodo = state.rows.filter((r) => !r.locked && (r.status === 0 || r.status === 3)).length;
  $('#translateMenu').innerHTML = `
    <div class="menu-label">Dịch bằng AI</div>
    <button class="menu-item" data-job="page">${icon('list')}Dịch trang đang xem<span class="kbd">${fmt(pageTodo)} dòng</span></button>
    <button class="menu-item" data-job="file" ${state.file ? '' : 'disabled'}>${icon('file')}Dịch file đang chọn…<span class="kbd">${state.file ? esc(basename(state.file)) : ''}</span></button>
    <button class="menu-item" data-job="all">${icon('globe')}Dịch toàn bộ game…</button>
    <div class="menu-sep"></div>
    <div class="menu-label">Chỉ dịch dòng chưa dịch / lỗi QA, dòng 🔒 luôn được bỏ qua</div>`;
}

/* ---------------- Page translate (sync) ---------------- */
async function translatePage() {
  const ids = state.rows.filter((r) => !r.locked && (r.status === 0 || r.status === 3)).map((r) => r.id);
  if (!ids.length) { toast('Trang này không còn dòng nào chưa dịch hoặc lỗi QA.', 'info'); return; }
  const btn = $('#btnTranslateMain');
  const prev = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span><span>Đang dịch ${ids.length} dòng…</span>`;
  try {
    const r = await api.translateBatch(ids);
    toast(`Đã dịch ${fmt(r.translated_count)} dòng${r.qa ? ` · ${r.qa} dòng lỗi QA` : ''}`, r.qa ? 'warn' : 'success');
    await loadRows({ scroll: false });
    refreshSoon();
  } finally { btn.disabled = false; btn.innerHTML = prev; }
}

/* ---------------- Batch dialog ---------------- */
async function openBatchDialog(scopeFile) {
  if (state.job) { toast('Đang có một tiến trình dịch chạy, hãy đợi hoặc dừng nó trước.', 'warn'); showDock(); return; }
  const body = html(`<div>
      <div class="field"><label>Phạm vi</label>
        <div class="radio-cards">
          <label><input type="radio" name="scope" value="file" ${scopeFile ? 'checked' : ''} ${state.file ? '' : 'disabled'}>
            <span><strong>File đang chọn</strong><span class="sub">${state.file ? esc(state.file) : 'Chưa chọn file nào ở thanh bên'}</span></span></label>
          <label><input type="radio" name="scope" value="all" ${scopeFile ? '' : 'checked'}>
            <span><strong>Toàn bộ game</strong><span class="sub">${fmt(state.files.length)} file</span></span></label>
        </div></div>
      <div class="field"><label>Loại nội dung <span class="muted" id="typeSummary"></span></label>
        <div class="type-grid" id="typeGrid"><div class="skeleton"></div></div>
        <div class="hint">Loại có 🔒 là lệnh logic của engine, luôn bị bỏ qua. Dòng là khóa logic cũng tự động bị bỏ qua.</div></div>
      <label class="check"><input type="checkbox" id="optAutofill" checked>
        <span>Điền thẳng vào ô bản dịch<span class="sub">Kết quả vẫn ở trạng thái “AI chưa duyệt”. Bỏ chọn để chỉ lưu vào gợi ý AI.</span></span></label>
      <label class="check"><input type="checkbox" id="optOverwrite">
        <span>Dịch đè cả dòng đã có bản dịch<span class="sub">Kể cả dòng đã duyệt. Thường không nên bật.</span></span></label>
    </div>`);

  async function loadTypes() {
    const file = $('input[name=scope]:checked', body).value === 'file' ? state.file : null;
    const types = await api.typeStats(file);
    $('#typeGrid', body).innerHTML = types.map((t) => `
      <label class="${t.translatable ? '' : 'disabled'}" title="${t.translatable ? '' : 'Lệnh logic — không dịch'}">
        <input type="checkbox" value="${esc(t.row_type)}" ${t.translatable ? 'checked' : 'disabled'}>
        ${t.translatable ? '' : '🔒 '}${esc(typeLabel(t.row_type))}
        <span class="n">${t.translatable ? `${fmt(t.empty)} chờ` : fmt(t.total)}</span></label>`).join('');
    updateSummary();
  }
  function updateSummary() {
    const n = $$('#typeGrid input:checked', body).reduce((acc, cb) => acc + (parseInt(cb.closest('label').querySelector('.n').textContent.replace(/\D/g, ''), 10) || 0), 0);
    $('#typeSummary', body).textContent = `— khoảng ${fmt(n)} dòng chờ dịch`;
  }
  body.addEventListener('change', (e) => {
    if (e.target.name === 'scope') loadTypes();
    else updateSummary();
  });

  const d = openDialog({
    title: 'Dịch AI hàng loạt',
    body,
    width: 'wide',
    actions: [
      { label: 'Hủy', value: null },
      { label: 'Bắt đầu dịch', kind: 'primary', icon: 'play', onClick: () => {
        const types = $$('#typeGrid input:checked', body).map((c) => c.value);
        if (!types.length) { toast('Chọn ít nhất một loại nội dung.', 'warn'); return; }
        d.close({
          file: $('input[name=scope]:checked', body).value === 'file' ? state.file : null,
          types, autoFill: $('#optAutofill', body).checked, overwrite: $('#optOverwrite', body).checked,
        });
      } },
    ],
  });
  loadTypes().catch((e) => { $('#typeGrid', body).innerHTML = `<span class="muted">${esc(e.message)}</span>`; });
  const opts = await d.result;
  if (opts) {
    if (opts.overwrite && !(await confirmDialog('Dịch đè?', 'Các bản dịch hiện có (kể cả đã duyệt) trong phạm vi này sẽ bị AI ghi đè.', { okLabel: 'Dịch đè', danger: true }))) return;
    startJob(opts);
  }
}

/* ---------------- Job dock ---------------- */
function showDock() { $('#jobDock').classList.remove('hidden', 'min'); }

function feed(htmlStr) {
  const f = $('#jobFeed');
  if (!f) return;
  f.appendChild(html(htmlStr));
  while (f.children.length > 200) f.firstElementChild.remove();
  f.scrollTop = f.scrollHeight;
}

function setJobStatusText(text) {
  const el = $('#jobStatus');
  if (el) el.innerHTML = text;
}

async function startJob({ file, types, autoFill, overwrite }) {
  const controller = new AbortController();
  const job = { controller, done: 0, total: 0, qa: 0, label: file ? basename(file) : 'Toàn bộ game', running: true };
  state.job = job;
  const dock = $('#jobDock');
  dock.className = 'job-dock';
  dock.innerHTML = `
    <div class="job-head">${icon('sparkles')}<span class="title ellipsis">Đang dịch: ${esc(job.label)}</span>
      <button class="btn ghost sm icon-only" data-dock="min" title="Thu nhỏ">${icon('minimize', 'icon-sm')}</button>
      <button class="btn sm danger" data-dock="stop">${icon('stop', 'icon-sm')}Dừng</button></div>
    <div class="job-prog"><div class="row"><span id="jobText">Đang kết nối AI…</span><span id="jobPct">0%</span></div>
      <div class="bar"><span id="jobBar" style="width:0%"></span></div></div>
    <div class="job-stats" id="jobStats"></div>
    <div class="job-feed" id="jobFeed"></div>`;

  const url = `/api/translate/stream?file=${encodeURIComponent(file || 'ALL')}&overwrite=${overwrite}&auto_fill=${autoFill}&types=${encodeURIComponent(types.join(','))}`;
  let finalMsg = '';
  let failed = false;
  try {
    await streamEvents(url, (ev) => {
      if (ev.type === 'start') {
        job.total = ev.total;
        $('#jobText').textContent = `0 / ${fmt(ev.total)} dòng`;
      } else if (ev.type === 'memory') {
        feed(`<div class="feed-note">${esc(ev.message)}</div>`);
      } else if (ev.type === 'progress') {
        job.done = ev.done;
        job.qa += (ev.items || []).filter((i) => i.status === 3).length;
        $('#jobBar').style.width = `${ev.percent}%`;
        $('#jobPct').textContent = `${ev.percent}%`;
        $('#jobText').textContent = `${fmt(ev.done)} / ${fmt(ev.total)} dòng${ev.current_file ? ` · ${basename(ev.current_file)}` : ''}`;
        $('#jobStats').innerHTML = `<span>⚠ ${fmt(job.qa)} lỗi QA</span>`;
        setJobStatusText(`<span class="spinner" style="display:inline-block;vertical-align:-2px"></span> Dịch ${ev.percent}%`);
        for (const it of ev.items || []) {
          feed(`<div class="feed-item ${it.status === 3 ? 'qa' : ''}"><div class="src">#${it.id} ${renderText(it.raw, { newlines: false })}</div>
                <div class="tgt">${it.status === 3 ? '⚠ ' : ''}${renderText(it.translated || '', { newlines: false })}</div></div>`);
          const row = state.rows.find((r) => r.id === it.id);
          if (row && row.id !== state.selectedId) {
            updateRowInList({ ...row, translated: autoFill ? it.translated : row.translated, mtl: it.translated, status: it.status, qa_flags: [] });
          }
        }
        refreshSoon();
      } else if (ev.type === 'fallback') {
        feed(`<div class="feed-note warn">${esc(ev.message)}</div>`);
      } else if (ev.type === 'key_rotate') {
        feed(`<div class="feed-note warn">${esc(ev.message)}</div>`);
        emit('settings-changed');
      } else if (ev.type === 'error') {
        failed = true;
        finalMsg = ev.message;
        feed(`<div class="feed-note error"><strong>Lỗi ${esc(ev.code || '')}:</strong> ${esc(ev.message)}</div>`);
      } else if (ev.type === 'complete') {
        finalMsg = ev.message;
      }
    }, controller.signal);
  } catch (e) {
    if (e.name === 'AbortError') { finalMsg = `Đã dừng sau ${fmt(job.done)} dòng.`; }
    else { failed = true; finalMsg = e.message; feed(`<div class="feed-note error">${esc(e.message)}</div>`); }
  }
  job.running = false;
  state.job = null;
  dock.classList.add(failed ? 'failed' : 'done');
  $('.job-head .title', dock).textContent = failed ? 'Dịch bị dừng do lỗi' : 'Đã xong';
  $('[data-dock="stop"]', dock).outerHTML = `<button class="btn ghost sm icon-only" data-dock="close" title="Đóng">${icon('x', 'icon-sm')}</button>`;
  $('#jobText').textContent = finalMsg || `${fmt(job.done)} dòng`;
  setJobStatusText(failed ? '⚠ Dịch bị lỗi' : `✓ ${esc(finalMsg)}`);
  toast(finalMsg || 'Xong', failed ? 'error' : 'success', 6000);
  emit('stats-dirty');
  loadRows({ scroll: false });
}

export function initJobs() {
  bindMenu($('#btnTranslateMenu'), $('#translateMenu'));
  $('#btnTranslateMenu').addEventListener('click', renderTranslateMenu, true);
  $('#btnTranslateMain').addEventListener('click', () => openBatchDialog(state.file));
  on($('#translateMenu'), 'click', '[data-job]', (e, b) => {
    const kind = b.dataset.job;
    const p = kind === 'page' ? translatePage() : openBatchDialog(kind === 'file' ? state.file : null);
    Promise.resolve(p).catch((err) => toast(err.message, 'error'));
  });
  on($('#jobDock'), 'click', '[data-dock]', (e, b) => {
    const act = b.dataset.dock;
    if (act === 'stop' && state.job) state.job.controller.abort();
    if (act === 'min') $('#jobDock').classList.toggle('min');
    if (act === 'close') { $('#jobDock').classList.add('hidden'); setJobStatusText(''); }
  });
  defineAction('translate-page', translatePage);
  defineAction('translate-batch', () => openBatchDialog(state.file));
}
