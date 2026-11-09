// Segment list: filters, rows, pagination, selection and list navigation.
import { api } from './api.js';
import { renderText } from './codes.js';
import { $, $$, basename, debounce, esc, fmt, html, icon, on, save } from './dom.js';
import { FILTERS, STATUS, emit, filterCount, state } from './state.js';
import { toast } from './ui.js';

const TYPE_LABELS = {
  Message: 'Lời thoại', Choice: 'Lựa chọn', SetString: 'Chuỗi biến', Picture: 'Chữ trên ảnh',
  DBName: 'Tên DB', DBField: 'Mô tả DB', GameTitle: 'Tiêu đề game', Database: 'Lệnh Database',
  StringCondition: 'So sánh chuỗi', JumpLabel: 'Nhảy nhãn', SetLabel: 'Đặt nhãn', CommonEvent: 'Gọi sự kiện',
  CommonEventByName: 'Gọi sự kiện (tên)', Comment: 'Ghi chú', DebugMessage: 'Debug',
};
export const typeLabel = (t) => TYPE_LABELS[t] || t;

let loadSeq = 0;

/* ---------------- Filter bar ---------------- */
export function renderScope() {
  const el = $('#scopeLabel');
  if (state.file) {
    const f = state.files.find((x) => x.file === state.file);
    el.innerHTML = `${icon('file', 'icon-sm')}<span class="ellipsis">${esc(basename(state.file))}</span>
      <span class="path ellipsis">${esc(f?.category || '')}</span>`;
  } else {
    el.innerHTML = `${icon('layers', 'icon-sm')}<span>Toàn bộ game</span>`;
  }
}

export function renderChips() {
  const s = state.scopeStats;
  $('#statusChips').innerHTML = FILTERS.map((f) => `
    <button class="chip ${state.status === f.value ? 'active' : ''}" data-status="${f.value}" role="tab"
      aria-selected="${state.status === f.value}" title="${esc(f.hint || f.label)}">
      ${f.sw ? `<span class="swatch ${f.sw}"></span>` : ''}${esc(f.label)}
      <span class="count">${s ? fmt(filterCount(s, f)) : ''}</span>
    </button>`).join('');
}

export async function loadTypeFilter() {
  const sel = $('#typeFilter');
  try {
    const types = await api.typeStats(state.file);
    types.forEach((t) => { if (t.translatable) state.translatableTypes.add(t.row_type); });
    if (state.rowType && !types.some((t) => t.row_type === state.rowType)) state.rowType = '';
    sel.innerHTML = `<option value="">Mọi loại lệnh</option>` + types.map((t) =>
      `<option value="${esc(t.row_type)}" ${t.row_type === state.rowType ? 'selected' : ''}>
        ${t.translatable ? '' : '🔒 '}${esc(typeLabel(t.row_type))} (${fmt(t.total)})</option>`).join('');
  } catch (e) { /* non-critical */ }
}

/* ---------------- Rows ---------------- */
function rowHtml(r) {
  const st = r.locked ? 'locked' : `st-${r.status}`;
  const tagCls = r.locked ? 'st-locked' : STATUS[r.status]?.cls;
  const tagTxt = r.locked ? 'Khóa' : STATUS[r.status]?.short;
  let tgt;
  if (r.locked) tgt = `<div class="seg-tgt placeholder">${icon('lock', 'icon-sm')} Giữ nguyên bản gốc</div>`;
  else if (r.translated) tgt = `<div class="seg-tgt">${renderText(r.translated, { search: state.search })}</div>`;
  else if (r.mtl) tgt = `<div class="seg-tgt"><span class="from-mtl">${renderText(r.mtl, { search: state.search })}</span></div>`;
  else tgt = `<div class="seg-tgt placeholder">Chưa dịch</div>`;
  return `<div class="seg ${st} ${r.id === state.selectedId ? 'selected' : ''}" data-id="${r.id}" role="option"
             aria-selected="${r.id === state.selectedId}">
      <div class="seg-meta">
        <span class="id">#${r.id}</span>
        <span class="tag ${tagCls}" title="${esc(typeLabel(r.row_type))}">${esc(tagTxt)}</span>
        ${state.file ? '' : `<span class="seg-file" title="${esc(r.file)}">${esc(basename(r.file).replace(/\.json$/, ''))}</span>`}
      </div>
      <div class="seg-src">${renderText(r.raw, { search: state.search })}</div>
      ${tgt}
    </div>`;
}

export function renderRows() {
  const list = $('#segList');
  if (!state.rows.length) {
    const f = FILTERS.find((x) => x.value === state.status);
    list.innerHTML = `<div class="empty">${icon(state.status === 4 ? 'checkCircle' : 'search')}
      <div>${state.status === 4 && !state.search ? 'Không còn dòng nào cần xử lý trong phạm vi này 🎉'
        : `Không có dòng nào ${f ? `ở mục “${esc(f.label)}”` : ''}${state.search ? ` khớp “${esc(state.search)}”` : ''}.`}</div></div>`;
  } else {
    list.innerHTML = state.rows.map(rowHtml).join('');
  }
  renderPager();
}

export function updateRowInList(row) {
  const i = state.rows.findIndex((r) => r.id === row.id);
  if (i < 0) return;
  state.rows[i] = row;
  const el = $(`.seg[data-id="${row.id}"]`);
  if (el) el.replaceWith(html(rowHtml(row)));
}

export function markDirty(id, dirty) {
  const el = $(`.seg[data-id="${id}"]`);
  if (el) el.classList.toggle('dirty', dirty);
}

function renderPager() {
  const pages = Math.max(1, Math.ceil(state.total / state.pageSize));
  const from = state.total ? (state.page - 1) * state.pageSize + 1 : 0;
  const to = Math.min(state.total, state.page * state.pageSize);
  $('#pager').innerHTML = `
    <span>${fmt(from)}–${fmt(to)} / ${fmt(state.total)} dòng</span>
    <span class="spacer"></span>
    <select class="select" id="pageSize" title="Số dòng mỗi trang">
      ${[25, 50, 100, 200].map((n) => `<option value="${n}" ${n === state.pageSize ? 'selected' : ''}>${n} / trang</option>`).join('')}
    </select>
    <button class="btn sm icon-only" data-page="prev" ${state.page <= 1 ? 'disabled' : ''} title="Trang trước (PageUp)">${icon('chevronLeft', 'icon-sm')}</button>
    <span>Trang <input class="input page-input" id="pageInput" value="${state.page}"> / ${fmt(pages)}</span>
    <button class="btn sm icon-only" data-page="next" ${state.page >= pages ? 'disabled' : ''} title="Trang sau (PageDown)">${icon('chevronRight', 'icon-sm')}</button>`;
}

export const totalPages = () => Math.max(1, Math.ceil(state.total / state.pageSize));

/** Load the current page. opts.select: 'first' | 'last' | id | null(keep) */
export async function loadRows(opts = {}) {
  const seq = ++loadSeq;
  const list = $('#segList');
  if (!state.rows.length) list.innerHTML = Array.from({ length: 8 }, () =>
    '<div class="seg"><div class="skeleton" style="width:40px"></div><div class="skeleton"></div><div class="skeleton"></div></div>').join('');
  try {
    const data = await api.rows({
      page: state.page, page_size: state.pageSize, file: state.file, status: state.status,
      search: state.search || null, row_type: state.rowType || null,
    });
    if (seq !== loadSeq) return;
    state.flagLabels = data.flag_labels || state.flagLabels;
    state.rows = data.rows;
    state.total = data.total;
    const pages = totalPages();
    if (state.page > pages && state.total) { state.page = pages; return loadRows(opts); }
    let target = null;
    if (opts.select === 'first') target = state.rows[0]?.id ?? null;
    else if (opts.select === 'last') target = state.rows.at(-1)?.id ?? null;
    else if (typeof opts.select === 'number') target = opts.select;
    else target = state.rows.some((r) => r.id === state.selectedId) ? state.selectedId : (state.rows[0]?.id ?? null);
    state.selectedId = target;
    renderRows();
    emit('select', currentRow());
    if (opts.scroll !== false) scrollToSelected();
  } catch (e) {
    if (seq !== loadSeq) return;
    list.innerHTML = `<div class="empty">${icon('alert')}<div>${esc(e.message)}</div></div>`;
  }
}

export const currentRow = () => state.rows.find((r) => r.id === state.selectedId) || null;

export function select(id, { focusList = false } = {}) {
  if (id === state.selectedId) return;
  state.selectedId = id;
  $$('.seg.selected').forEach((el) => { el.classList.remove('selected'); el.setAttribute('aria-selected', 'false'); });
  const el = $(`.seg[data-id="${id}"]`);
  if (el) { el.classList.add('selected'); el.setAttribute('aria-selected', 'true'); }
  scrollToSelected();
  if (focusList) $('#segList').focus();
  emit('select', currentRow());
}

function scrollToSelected() {
  const el = $(`.seg[data-id="${state.selectedId}"]`);
  if (el) el.scrollIntoView({ block: 'nearest' });
}

/** Move selection by delta rows, crossing page boundaries. */
export async function move(delta) {
  const i = state.rows.findIndex((r) => r.id === state.selectedId);
  const j = i + delta;
  if (j >= 0 && j < state.rows.length) return select(state.rows[j].id);
  if (j >= state.rows.length && state.page < totalPages()) { state.page++; return loadRows({ select: 'first' }); }
  if (j < 0 && state.page > 1) { state.page--; return loadRows({ select: 'last' }); }
}

const needsWork = (r) => !r.locked && r.status !== 2;

/** Jump to the next/previous row that still needs work (empty, machine, QA). */
export async function moveToUnreviewed(dir = 1) {
  const i = state.rows.findIndex((r) => r.id === state.selectedId);
  const seq = dir > 0 ? state.rows.slice(i + 1) : state.rows.slice(0, Math.max(0, i)).reverse();
  const hit = seq.find(needsWork);
  if (hit) return select(hit.id);
  const pages = totalPages();
  if (dir > 0 && state.page < pages) { state.page++; await loadRows({ select: 'first' }); if (currentRow() && !needsWork(currentRow())) return moveToUnreviewed(1); return; }
  if (dir < 0 && state.page > 1) { state.page--; await loadRows({ select: 'last' }); if (currentRow() && !needsWork(currentRow())) return moveToUnreviewed(-1); return; }
  toast(dir > 0 ? 'Đã tới dòng cuối cần xử lý trong bộ lọc này.' : 'Đã tới dòng đầu cần xử lý trong bộ lọc này.', 'info');
}

export function initList() {
  $('#searchWrap').innerHTML = `${icon('search', 'icon-sm')}<input class="input" id="searchInput" placeholder="Tìm trong gốc / bản dịch…  (Ctrl+F)" autocomplete="off">`;
  $('#searchInput').addEventListener('input', debounce((e) => {
    state.search = e.target.value.trim();
    state.page = 1;
    loadRows({ select: 'first' });
  }, 300));
  $('#searchInput').addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.target.value = ''; e.target.dispatchEvent(new Event('input')); $('#segList').focus(); }
    if (e.key === 'Enter' || e.key === 'ArrowDown') { e.preventDefault(); $('#segList').focus(); }
  });

  on($('#statusChips'), 'click', '.chip', (e, chip) => {
    state.status = Number(chip.dataset.status);
    save('nelir.status', state.status);
    state.page = 1;
    renderChips();
    loadRows({ select: 'first' });
  });
  $('#typeFilter').addEventListener('change', (e) => {
    state.rowType = e.target.value;
    state.page = 1;
    loadRows({ select: 'first' });
  });

  on($('#segList'), 'click', '.seg', (e, el) => select(Number(el.dataset.id)));
  on($('#segList'), 'dblclick', '.seg', () => emit('focus-editor'));

  const pager = $('#pager');
  on(pager, 'click', '[data-page]', (e, b) => {
    state.page += b.dataset.page === 'next' ? 1 : -1;
    loadRows({ select: 'first' });
  });
  pager.addEventListener('change', (e) => {
    if (e.target.id === 'pageSize') {
      state.pageSize = Number(e.target.value);
      save('nelir.pageSize', state.pageSize);
      state.page = 1;
      loadRows({ select: 'first' });
    } else if (e.target.id === 'pageInput') {
      const p = Math.min(totalPages(), Math.max(1, parseInt(e.target.value, 10) || 1));
      state.page = p;
      loadRows({ select: 'first' });
    }
  });
}
