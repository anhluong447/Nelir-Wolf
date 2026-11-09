// Topbar: project switcher, global progress, model pill, statusbar.
import { api } from './api.js';
import { $, esc, fmt, icon, on } from './dom.js';
import { stackbar } from './sidebar.js';
import { emit, state } from './state.js';
import { bindMenu, toast } from './ui.js';

export function renderProgress() {
  const s = state.stats;
  if (!s) return;
  $('#globalBar').outerHTML = stackbar(s.translated, s.mtl, s.qa, s.translatable, false).replace('class="stackbar', 'id="globalBar" class="stackbar');
  $('#globalLabel').textContent = `${fmt(s.completed)} / ${fmt(s.translatable)} · ${s.percent}%`;
  $('.topbar-progress').title =
    `Đã duyệt ${fmt(s.translated)} · AI chưa duyệt ${fmt(s.mtl)} · Lỗi QA ${fmt(s.qa)} · Chưa dịch ${fmt(s.empty)}\n` +
    `🔒 ${fmt(s.locked)} dòng là khóa logic, không tính vào tiến độ`;
  renderStatusbar();
}

export function renderStatusbar() {
  const s = state.stats;
  const dot = (cls) => `<span class="dot ${cls}"></span>`;
  $('#statusbar').innerHTML = s ? `
    <span>${dot('sw-2')}Đã duyệt ${fmt(s.translated)}</span>
    <span>${dot('sw-1')}AI ${fmt(s.mtl)}</span>
    <span>${dot('sw-3')}Lỗi QA ${fmt(s.qa)}</span>
    <span>${dot('sw-0')}Chưa dịch ${fmt(s.empty)}</span>
    <span>${dot('sw-locked')}Khóa ${fmt(s.locked)}</span>
    <span class="spacer"></span>
    <span id="jobStatus"></span>
    <span><kbd>↑</kbd><kbd>↓</kbd> chọn · <kbd>Enter</kbd> sửa · <kbd>Ctrl</kbd>+<kbd>Enter</kbd> duyệt &amp; tiếp · <kbd>?</kbd> phím tắt</span>` : '';
}

export function renderProjectButton() {
  $('#projectName').textContent = state.project ? state.project.name : 'Chưa có dự án';
  $('#projectChevron').innerHTML = icon('chevronDown', 'icon-sm');
  document.title = state.project ? `${state.project.name} — Nelir Wolf` : 'Nelir Wolf Translator';
}

function renderProjectMenu() {
  const items = state.projects.map((p) => `
    <button class="menu-item project-item ${p.is_active ? 'current' : ''}" data-project="${esc(p.id)}">
      <div class="row"><strong class="ellipsis">${esc(p.name)}</strong><span class="meta">${p.stats.percent}%</span></div>
      ${stackbar(p.stats.translated, p.stats.mtl, p.stats.qa, p.stats.translatable)}
      <span class="meta">${fmt(p.stats.completed)}/${fmt(p.stats.translatable)} dòng${p.game_path_exists ? '' : ' · ⚠ không tìm thấy thư mục game'}</span>
    </button>`).join('');
  $('#projectMenu').innerHTML = `
    <div class="menu-label">Dự án</div>${items || '<div class="menu-item muted">Chưa có dự án</div>'}
    <div class="menu-sep"></div>
    <button class="menu-item" data-action="new-project">${icon('plus')}Thêm game mới…</button>
    <button class="menu-item" data-action="import-nel">${icon('upload')}Nạp gói .nel…</button>
    <button class="menu-item" data-action="export-nel" ${state.project ? '' : 'disabled'}>${icon('download')}Xuất dự án ra .nel</button>`;
}

export async function loadProjects() {
  const data = await api.projects();
  state.projects = data.projects || [];
  state.project = data.active_project || null;
  renderProjectButton();
  renderProjectMenu();
}

export async function loadModel() {
  try {
    state.settings = await api.settings();
    $('#modelName').textContent = state.settings.active_model_display || '';
  } catch { /* ignore */ }
}

export function initTopbar() {
  $('#btnToggleSidebar').innerHTML = icon('sidebar');
  $('#btnTranslateMain').innerHTML = `${icon('sparkles')}<span>Dịch AI</span>`;
  $('#btnTranslateMenu').innerHTML = icon('chevronDown', 'icon-sm');
  $('#btnPatch').innerHTML = `${icon('upload')}<span>Patch vào game</span>`;
  $('#btnTools').innerHTML = icon('wrench');
  $('#btnSettings').innerHTML = icon('gear');

  bindMenu($('#btnProject'), $('#projectMenu'));
  on($('#projectMenu'), 'click', '[data-project]', async (e, el) => {
    const id = el.dataset.project;
    if (state.project && id === state.project.id) return;
    try {
      await api.selectProject(id);
      toast('Đã chuyển dự án', 'success');
      emit('project-changed');
    } catch (err) { toast(err.message, 'error'); }
  });
  on($('#projectMenu'), 'click', '[data-action]', (e, el) => emit('action', el.dataset.action));
  $('#btnModel').addEventListener('click', () => emit('action', 'settings'));
  $('#btnSettings').addEventListener('click', () => emit('action', 'settings'));
  $('#btnToggleSidebar').addEventListener('click', () => emit('action', 'toggle-sidebar'));
}
