// Inspector: detail editor for the selected row.
import { api } from './api.js';
import { FLAG_TEXT, isBlocking, missingCodes, qaFlags, renderText } from './codes.js';
import { $, basename, debounce, esc, fmt, icon, on } from './dom.js';
import { currentRow, markDirty, move, select, typeLabel, updateRowInList } from './list.js';
import { STATUS, defineAction, emit, listen, state } from './state.js';
import { busy, confirmDialog, toast } from './ui.js';

let current = null;      // row shown in the inspector
let savedText = '';      // last saved translation of `current`
let ctxSeq = 0;

const editor = () => $('#editor');
const isDirty = () => !!(current && editor() && editor().value !== savedText);
const maxLine = () => parseInt(state.settings?.qa_max_line_chars || '0', 10) || 0;
const refreshStatsSoon = debounce(() => emit('stats-dirty'), 700);

/* ---------------- Rendering ---------------- */
function lockedReason(row) {
  if (state.translatableTypes.has(row.row_type)) {
    return 'Chuỗi này là <strong>khóa logic</strong>: một lệnh khác (so sánh chuỗi, tra cứu Database, nhãn hoặc gọi sự kiện) dùng đúng văn bản này. ' +
      'Nếu dịch một phía, game sẽ rẽ nhánh sai hoặc báo lỗi “data name does not exist”, nên khi Patch nó luôn giữ nguyên bản gốc.';
  }
  return `Đây là lệnh logic của engine (<strong>${esc(typeLabel(row.row_type))}</strong>), không hiển thị cho người chơi nên không bao giờ được dịch.`;
}

function statusTag(row) {
  if (row.locked) return `<span class="tag st-locked">${icon('lock', 'icon-sm')} Khóa</span>`;
  const s = STATUS[row.status] || STATUS[0];
  return `<span class="tag ${s.cls}">${esc(s.label)}</span>`;
}

function render(row) {
  const el = $('#inspector');
  if (!row) {
    el.innerHTML = `<div class="insp-empty">${icon('list')}<div>Chọn một dòng ở danh sách để xem và sửa bản dịch.</div>${shortcutTable()}</div>`;
    return;
  }
  const showMtl = row.mtl && row.mtl !== row.translated;
  el.innerHTML = `
    <div class="insp-head">
      <div class="row">
        <span class="id">#${row.id}</span>${statusTag(row)}
        <span class="tag">${esc(typeLabel(row.row_type))}</span>
        <span class="spacer"></span>
        <button class="btn ghost sm icon-only" data-act="prev" title="Dòng trước (↑)">${icon('arrowUp', 'icon-sm')}</button>
        <button class="btn ghost sm icon-only" data-act="next" title="Dòng sau (↓)">${icon('arrowDown', 'icon-sm')}</button>
      </div>
      <div class="where" title="${esc(row.file)} → ${esc(row.path)}">${esc(row.file)} · <span class="mono">${esc(row.path)}</span></div>
    </div>
    <div class="insp-body">
      ${row.locked ? `<div class="callout locked">${icon('lock')}<div>${lockedReason(row)}</div></div>` : ''}
      <div>
        <div class="block-title">Văn bản gốc
          <span class="actions"><button class="btn ghost sm" data-act="copy-src" title="Chép văn bản gốc">${icon('copy', 'icon-sm')}Chép</button></span>
        </div>
        <div class="src-box">${renderText(row.raw)}</div>
      </div>
      ${row.locked ? '' : `
      ${showMtl ? `
      <div>
        <div class="block-title">Gợi ý AI
          <span class="actions"><button class="btn ghost sm" data-act="use-mtl" title="Dùng bản AI làm bản dịch (Ctrl+Shift+U)">${icon('check', 'icon-sm')}Dùng bản này</button></span>
        </div>
        <div class="mtl-box">${renderText(row.mtl)}</div>
      </div>` : ''}
      <div>
        <div class="block-title">Bản dịch <span id="dirtyMark"></span></div>
        <textarea class="editor" id="editor" spellcheck="false" placeholder="Gõ bản dịch tiếng Việt…  (Enter ở danh sách để vào đây, Esc để quay lại)">${esc(row.translated || '')}</textarea>
        <div class="editor-meta" id="editorMeta"></div>
        <div class="qa-list" id="qaList" style="margin-top:8px"></div>
      </div>
      <div id="glossBlock"></div>`}
      <div>
        <div class="block-title">Ngữ cảnh (cùng file)</div>
        <div class="ctx" id="ctxBox"><div class="ctx-row"><div class="skeleton"></div></div></div>
      </div>
    </div>
    ${row.locked ? '' : `
    <div class="insp-foot">
      <button class="btn" data-act="ai" title="Dịch dòng này bằng AI (Ctrl+Shift+A)">${icon('sparkles')}AI dịch</button>
      <button class="btn ghost icon-only danger" data-act="clear" title="Xóa bản dịch dòng này">${icon('eraser')}</button>
      <span class="spacer"></span>
      <button class="btn" data-act="save" title="Lưu (Ctrl+S)">Lưu</button>
      <button class="btn primary" data-act="confirm" title="Lưu, đánh dấu đã duyệt và sang dòng tiếp (Ctrl+Enter)">${icon('check')}Duyệt &amp; tiếp</button>
    </div>`}`;

  if (!row.locked) {
    autoGrow();
    updateLiveQa();
    renderGlossary(row);
  }
  loadContext(row);
}

function autoGrow() {
  const ed = editor();
  if (!ed) return;
  ed.style.height = 'auto';
  ed.style.height = `${Math.max(96, ed.scrollHeight + 2)}px`;
}

function updateLiveQa() {
  const ed = editor();
  if (!ed || !current) return;
  const text = ed.value;
  const dirty = isDirty();
  $('#dirtyMark').innerHTML = dirty ? '<span class="dirty" style="color:var(--st-mtl)">● chưa lưu</span>' : '';
  markDirty(current.id, dirty);

  const rawLines = current.raw.split('\n').length;
  const lines = text ? text.split('\n').length : 0;
  const longest = Math.max(0, ...text.split('\n').map((l) => l.length));
  const ml = maxLine();
  $('#editorMeta').innerHTML = `
    <span>${fmt(lines)}/${fmt(rawLines)} dòng</span><span>·</span>
    <span ${ml && longest > ml ? 'style="color:var(--st-mtl)"' : ''}>dòng dài nhất ${fmt(longest)}${ml ? `/${ml}` : ''} ký tự</span>`;

  if (!text.trim()) { $('#qaList').innerHTML = ''; return; }
  const flags = qaFlags(current.raw, text, current.row_type, ml);
  const missing = missingCodes(current.raw, text);
  const items = flags.map((f) => {
    const warn = !['empty', 'untranslated', 'jp_residue', 'line_count', 'missing_code'].includes(f);
    return `<span class="qa-item ${warn ? 'warn' : ''}">${icon('alert', 'icon-sm')}${esc(FLAG_TEXT[f] || f)}</span>`;
  });
  if (missing.length) {
    items.push(...missing.map((c) =>
      `<button class="btn sm" data-insert="${esc(c)}" title="Chèn mã này vào vị trí con trỏ"><span class="cc">${esc(c)}</span>chèn</button>`));
  }
  $('#qaList').innerHTML = items.length ? items.join('')
    : `<span class="qa-item ok">${icon('check', 'icon-sm')}QA ổn</span>`;
}

function renderGlossary(row) {
  const hits = state.glossary.filter((g) => g.src && row.raw.includes(g.src));
  const box = $('#glossBlock');
  if (!box) return;
  box.innerHTML = hits.length ? `
    <div class="block-title">Thuật ngữ</div>
    <div class="gloss">${hits.map((g) => `
      <button class="gloss-item btn ghost" data-insert="${esc(g.dst)}" title="Chèn “${esc(g.dst)}”${g.note ? ` — ${esc(g.note)}` : ''}">
        <span class="src">${esc(g.src)}</span><span class="arrow">→</span><strong>${esc(g.dst)}</strong></button>`).join('')}
    </div>` : '';
}

async function loadContext(row) {
  const seq = ++ctxSeq;
  try {
    const ctx = await api.context(row.id, 2);
    if (seq !== ctxSeq) return;
    const item = (r, cur) => `
      <div class="ctx-row ${cur ? 'current' : ''}" data-id="${r.id}" title="#${r.id} ${esc(typeLabel(r.row_type))}">
        <div class="src">${renderText(r.raw, { newlines: false })}</div>
        <div class="tgt">${r.locked ? '<span class="faint">🔒 giữ nguyên</span>' : renderText(r.translated || r.mtl || '', { newlines: false }) || '<span class="faint">—</span>'}</div>
      </div>`;
    $('#ctxBox').innerHTML = [...ctx.before.map((r) => item(r, false)), item(ctx.row, true), ...ctx.after.map((r) => item(r, false))].join('');
  } catch {
    if (seq === ctxSeq && $('#ctxBox')) $('#ctxBox').innerHTML = '<div class="ctx-row faint">Không tải được ngữ cảnh</div>';
  }
}

/* ---------------- Actions ---------------- */
async function save({ quiet = false } = {}) {
  if (!current || current.locked || !isDirty()) return current;
  const id = current.id;
  const text = editor().value;
  const res = await api.updateRow(id, text);
  if (current && current.id === id) { savedText = text; current = res.row; }
  updateRowInList(res.row);
  markDirty(id, false);
  refreshStatsSoon();
  if (!quiet) toast(`Đã lưu #${id}`, 'success', 1600);
  if (current && current.id === id) {
    const wasEditing = document.activeElement?.id === 'editor';
    const caret = wasEditing ? editor().selectionStart : 0;
    render(current);
    if (wasEditing) { editor().focus(); editor().selectionStart = editor().selectionEnd = caret; }
  }
  return res.row;
}

async function saveRowSilently(row, text) {
  try {
    const res = await api.updateRow(row.id, text);
    updateRowInList(res.row);
    markDirty(row.id, false);
    refreshStatsSoon();
  } catch (e) { toast(`Không lưu được #${row.id}: ${e.message}`, 'error'); }
}

async function confirmAndNext() {
  if (!current || current.locked) return;
  const text = editor().value;
  if (!text.trim() && !current.mtl) { toast('Dòng này chưa có bản dịch để duyệt.', 'warn'); return; }
  const flags = qaFlags(current.raw, text || current.mtl, current.row_type, maxLine());
  if (isBlocking(flags)) {
    const ok = await confirmDialog('Bản dịch chưa đạt QA',
      `Bản dịch đang có vấn đề:\n• ${flags.map((f) => FLAG_TEXT[f] || f).join('\n• ')}\n\nVẫn đánh dấu là đã duyệt?`, { okLabel: 'Vẫn duyệt' });
    if (!ok) { editor().focus(); return; }
  }
  const id = current.id;
  if (isDirty() && text.trim()) {
    await save({ quiet: true });          // manual edit => reviewed
  } else {
    await api.confirmRows([id]);
    const ctx = await api.context(id, 0);
    updateRowInList(ctx.row);
    refreshStatsSoon();
  }
  const keepEditing = document.activeElement === editor();
  await move(1);
  if (keepEditing) focusEditor();
}

async function translateAi(btn) {
  if (!current || current.locked) return;
  if (isDirty() && !(await confirmDialog('Bỏ thay đổi chưa lưu?', 'Bản dịch đang gõ chưa được lưu. AI sẽ ghi đè nội dung trong ô soạn thảo.', { okLabel: 'Dịch lại bằng AI' }))) return;
  const id = current.id;
  await busy(btn || $('[data-act="ai"]'), async () => {
    const row = await api.translateSingle(id);
    updateRowInList(row);
    refreshStatsSoon();
    if (current && current.id === id) { current = row; savedText = row.translated || ''; render(row); }
    toast(row.status === 3 ? `#${id}: AI dịch xong nhưng chưa đạt QA` : `#${id}: AI đã dịch`, row.status === 3 ? 'warn' : 'success');
  });
}

function useMtl() {
  if (!current || !current.mtl || !editor()) return;
  editor().value = current.mtl;
  autoGrow();
  updateLiveQa();
  editor().focus();
}

async function clearRow() {
  if (!current || current.locked) return;
  if (!(await confirmDialog('Xóa bản dịch?', `Xóa cả bản AI và bản dịch của dòng #${current.id}?`, { okLabel: 'Xóa', danger: true }))) return;
  await api.clearRows({ target: 'row', row_id: current.id, clear_type: 'both' });
  const ctx = await api.context(current.id, 0);
  updateRowInList(ctx.row);
  current = ctx.row; savedText = '';
  render(current);
  refreshStatsSoon();
}

function insertAtCursor(text) {
  const ed = editor();
  if (!ed) return;
  const { selectionStart: a, selectionEnd: b, value } = ed;
  ed.value = value.slice(0, a) + text + value.slice(b);
  ed.selectionStart = ed.selectionEnd = a + text.length;
  ed.focus();
  autoGrow();
  updateLiveQa();
}

export function focusEditor() {
  const ed = editor();
  if (ed) { ed.focus(); ed.selectionStart = ed.selectionEnd = ed.value.length; }
}

export function shortcutTable() {
  const rows = [
    [['↑', '↓'], 'Chọn dòng trước / sau'], [['Alt', '↓'], 'Tới dòng cần xử lý tiếp theo'],
    [['Enter'], 'Vào ô soạn thảo'], [['Esc'], 'Quay lại danh sách'],
    [['Ctrl', 'Enter'], 'Lưu, duyệt và sang dòng tiếp'], [['Ctrl', 'S'], 'Lưu'],
    [['Ctrl', 'Shift', 'A'], 'AI dịch dòng này'], [['Ctrl', 'Shift', 'U'], 'Dùng gợi ý AI'],
    [['Ctrl', 'F'], 'Tìm kiếm'], [['Ctrl', 'B'], 'Ẩn/hiện danh sách file'], [['?'], 'Bảng phím tắt'],
  ];
  return `<div class="shortcut-table">${rows.map(([keys, label]) =>
    `<span class="keys">${keys.map((k) => `<kbd>${k}</kbd>`).join('')}</span><span>${label}</span>`).join('')}</div>`;
}

/* ---------------- Init ---------------- */
export function initInspector() {
  const el = $('#inspector');

  listen('select', (row) => {
    // auto-save the row we are leaving
    if (current && isDirty() && (!row || row.id !== current.id)) saveRowSilently(current, editor().value);
    if (row && current && row.id === current.id && isDirty()) return; // keep unsaved edits on same row
    const wasEditing = document.activeElement?.id === 'editor';
    current = row;
    savedText = row ? row.translated || '' : '';
    render(row);
    if (wasEditing) focusEditor();   // keyboard navigation keeps you in the editor
  });
  listen('focus-editor', focusEditor);
  listen('glossary-changed', () => current && !current.locked && renderGlossary(current));

  el.addEventListener('input', (e) => { if (e.target.id === 'editor') { autoGrow(); updateLiveQa(); } });
  el.addEventListener('keydown', (e) => {
    if (e.target.id !== 'editor') return;
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && e.key === 'Enter') { e.preventDefault(); confirmAndNext().catch((err) => toast(err.message, 'error')); }
    else if (ctrl && e.key.toLowerCase() === 's') { e.preventDefault(); save().catch((err) => toast(err.message, 'error')); }
    else if (e.key === 'Escape') { e.preventDefault(); $('#segList').focus(); }
  });
  document.addEventListener('keydown', (e) => {
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && e.shiftKey && e.key.toLowerCase() === 'a') { e.preventDefault(); translateAi().catch((err) => toast(err.message, 'error')); }
    if (ctrl && e.shiftKey && e.key.toLowerCase() === 'u') { e.preventDefault(); useMtl(); }
    const ae = document.activeElement;
    const free = !ae || ae === document.body || ae.id === 'segList' || ae.closest?.('.seg-list, .insp-head, .insp-foot');
    if (ctrl && !e.shiftKey && e.key === 'Enter' && e.target.id !== 'editor' && free && !document.querySelector('.dialog-backdrop')) {
      e.preventDefault(); confirmAndNext().catch((err) => toast(err.message, 'error'));
    }
  });

  on(el, 'click', '[data-act]', (e, b) => {
    const act = b.dataset.act;
    const run = {
      prev: () => move(-1), next: () => move(1), 'copy-src': () => navigator.clipboard.writeText(current.raw).then(() => toast('Đã chép văn bản gốc', 'success', 1500)),
      'use-mtl': useMtl, save: () => save(), confirm: confirmAndNext, ai: () => translateAi(b), clear: clearRow,
    }[act];
    if (run) Promise.resolve(run()).catch((err) => toast(err.message, 'error'));
  });
  on(el, 'click', '[data-insert]', (e, b) => insertAtCursor(b.dataset.insert));
  on(el, 'click', '.ctx-row[data-id]', (e, r) => {
    const id = Number(r.dataset.id);
    if (current && id === current.id) return;
    if (state.rows.some((x) => x.id === id)) select(id);
    else toast('Dòng này không nằm trong bộ lọc / trang hiện tại.', 'info');
  });

  window.addEventListener('beforeunload', (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ''; } });

  defineAction('save-current', () => save());
  render(currentRow());
}
