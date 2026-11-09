// File tree: grouped by category, per-file progress, filter, collapse state.
import { $, $$, basename, debounce, esc, fmt, html, icon, on, pct, save, store } from './dom.js';
import { emit, state } from './state.js';

const CATEGORIES = [
  { key: 'Map', label: 'Bản đồ', icon: 'map' },
  { key: 'CommonEvent', label: 'Sự kiện chung', icon: 'zap' },
  { key: 'Database', label: 'Database', icon: 'database' },
  { key: 'System', label: 'Hệ thống', icon: 'gear' },
];

let collapsed = store('nelir.collapsed', {});
let filter = '';

export function stackbar(reviewed, mtl, qa, total, thin = true) {
  if (!total) return `<div class="stackbar ${thin ? 'thin' : ''}"></div>`;
  const w = (n) => `${(n / total) * 100}%`;
  return `<div class="stackbar ${thin ? 'thin' : ''}">
    <span class="sw-2" style="width:${w(reviewed)}"></span>
    <span class="sw-1" style="width:${w(mtl)}"></span>
    <span class="sw-3" style="width:${w(qa)}"></span></div>`;
}

function fileRow(f) {
  const mtl = Math.max(0, f.translated - f.reviewed);
  const done = f.translatable > 0 && f.translated >= f.translatable && !f.qa;
  return `<button class="tree-file ${state.file === f.file ? 'active' : ''} ${done ? 'done' : ''}" data-file="${esc(f.file)}"
            title="${esc(f.file)}\n${fmt(f.translated)}/${fmt(f.translatable)} dòng dịch được${f.qa ? ` · ${f.qa} lỗi QA` : ''}">
      <span class="name">${esc(basename(f.file).replace(/\.json$/, ''))}</span>
      <span class="num">${f.translatable ? `${pct(f.translated, f.translatable)}%` : '🔒'}</span>
      ${stackbar(f.reviewed, mtl, f.qa, f.translatable)}
    </button>`;
}

export function renderSidebar() {
  const tree = $('#fileTree');
  const q = filter.toLowerCase();
  const files = state.files.filter((f) => !q || f.file.toLowerCase().includes(q));
  const s = state.stats;
  let out = `<button class="tree-all ${state.file === null ? 'active' : ''}" data-file="">
      <span>${icon('layers', 'icon-sm')} Toàn bộ game</span>
      <span class="num">${s ? `${s.percent}%` : ''}</span>
      ${s ? stackbar(s.translated, s.mtl, s.qa, s.translatable) : ''}
    </button>`;
  for (const cat of CATEGORIES) {
    const items = files.filter((f) => f.category === cat.key);
    if (!items.length) continue;
    const isCollapsed = collapsed[cat.key] && !q;
    out += `<div class="tree-group ${isCollapsed ? 'collapsed' : ''}" data-cat="${cat.key}">
        <button class="tree-group-head">${icon('chevronDown', 'icon-sm chev')}${icon(cat.icon, 'icon-sm')}
          <span>${cat.label}</span><span class="num">${items.length}</span></button>
        <div class="tree-items">${items.map(fileRow).join('')}</div></div>`;
  }
  if (!files.length && q) out += `<div class="empty">${icon('search')}<div>Không có file nào khớp “${esc(filter)}”</div></div>`;
  tree.innerHTML = out;
  $('#sidebarFoot').textContent = `${fmt(state.files.length)} file · ${fmt(s?.total || 0)} dòng`;
}

export function initSidebar() {
  const wrap = $('#fileSearchWrap');
  wrap.innerHTML = `${icon('search', 'icon-sm')}<input class="input" id="fileSearch" placeholder="Lọc file…" autocomplete="off">`;
  $('#fileSearch').addEventListener('input', debounce((e) => { filter = e.target.value.trim(); renderSidebar(); }, 120));

  const tree = $('#fileTree');
  on(tree, 'click', '.tree-group-head', (e, btn) => {
    const cat = btn.parentElement.dataset.cat;
    collapsed[cat] = !collapsed[cat];
    save('nelir.collapsed', collapsed);
    btn.parentElement.classList.toggle('collapsed', collapsed[cat]);
  });
  on(tree, 'click', '.tree-all, .tree-file', (e, btn) => {
    const file = btn.dataset.file || null;
    if (file === state.file) return;
    state.file = file;
    $$('.tree-all, .tree-file', tree).forEach((b) => b.classList.toggle('active', (b.dataset.file || null) === file));
    emit('scope');
  });
}

export function updateFileEntry(file) {
  // re-render one file row after its counts changed
  const f = state.files.find((x) => x.file === file);
  const el = $(`.tree-file[data-file="${CSS.escape(file)}"]`);
  if (f && el) el.replaceWith(html(fileRow(f)));
}
