// Bootstrap + global keyboard shortcuts.
import { api } from './api.js';
import { $ } from './dom.js';
import { initInspector } from './inspector.js';
import { initJobs } from './jobs.js';
import { initSettings } from './settings.js';
import { initTools } from './tools.js';
import { initList, loadRows, loadTypeFilter, move, moveToUnreviewed, renderChips, renderScope } from './list.js';
import { initSidebar, renderSidebar } from './sidebar.js';
import { defineAction, emit, listen, runAction, setUi, state } from './state.js';
import { initTopbar, loadModel, loadProjects, renderProgress } from './topbar.js';
import { isDialogOpen, toast } from './ui.js';

listen('action', (name) => runAction(name).catch((e) => toast(e.message, 'error')));

/* ---------------- Data refresh ---------------- */
export async function refreshStats() {
  const [stats, scope, files] = await Promise.all([
    api.stats(), state.file ? api.stats(state.file) : null, api.files(),
  ]);
  state.stats = stats;
  state.scopeStats = scope || stats;
  state.files = files;
  renderProgress();
  renderSidebar();
  renderChips();
}

async function onScopeChanged() {
  state.page = 1;
  renderScope();
  await Promise.all([refreshStats(), loadTypeFilter()]);
  await loadRows({ select: 'first' });
}

async function loadProjectData() {
  await loadProjects();
  if (!state.project) {
    $('#segList').innerHTML = '<div class="empty"><div>Chưa có dự án nào.</div><div>Mở menu dự án ở góc trên để thêm game mới hoặc nạp gói .nel.</div></div>';
    $('#inspector').innerHTML = '';
    return;
  }
  if (state.file && !state.projectFilesHas?.(state.file)) state.file = null;
  api.glossary().then((g) => { state.glossary = g.entries || []; emit('glossary-changed'); }).catch(() => {});
  await onScopeChanged();
}

/* ---------------- Keyboard ---------------- */
const isTyping = (el) => el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable);

function onKey(e) {
  if (isDialogOpen()) return;
  const typing = isTyping(document.activeElement);
  const k = e.key;
  const ctrl = e.ctrlKey || e.metaKey;

  if (ctrl && k.toLowerCase() === 'f') { e.preventDefault(); $('#searchInput').focus(); $('#searchInput').select(); return; }
  if (ctrl && k.toLowerCase() === 'b') { e.preventDefault(); emit('action', 'toggle-sidebar'); return; }
  if (e.altKey && (k === 'ArrowDown' || k === 'ArrowUp')) { e.preventDefault(); emit('before-move'); moveToUnreviewed(k === 'ArrowDown' ? 1 : -1); return; }
  if (k === 'PageDown' && !typing) { e.preventDefault(); emit('action', 'next-page'); return; }
  if (k === 'PageUp' && !typing) { e.preventDefault(); emit('action', 'prev-page'); return; }
  if (typing) return;

  if (k === 'ArrowDown' || k === 'j') { e.preventDefault(); emit('before-move'); move(1); }
  else if (k === 'ArrowUp' || k === 'k') { e.preventDefault(); emit('before-move'); move(-1); }
  else if (k === 'Enter') { e.preventDefault(); emit('focus-editor'); }
  else if (k === '?') { e.preventDefault(); emit('action', 'shortcuts'); }
}

/* ---------------- Init ---------------- */
async function init() {
  initTopbar();
  initSidebar();
  initList();
  initInspector();
  initJobs();
  initSettings();
  initTools();
  document.addEventListener('keydown', onKey);
  setUi({});

  defineAction('toggle-sidebar', () => {
    $('#app').classList.toggle('sidebar-collapsed');
    setUi({ sidebarCollapsed: $('#app').classList.contains('sidebar-collapsed') });
  });
  if (state.ui.sidebarCollapsed) $('#app').classList.add('sidebar-collapsed');
  defineAction('next-page', () => { if (state.page * state.pageSize < state.total) { state.page++; return loadRows({ select: 'first' }); } });
  defineAction('prev-page', () => { if (state.page > 1) { state.page--; return loadRows({ select: 'first' }); } });

  listen('scope', onScopeChanged);
  listen('project-changed', async () => { state.file = null; state.rowType = ''; await loadProjectData(); });
  listen('stats-dirty', () => refreshStats().catch(() => {}));
  listen('settings-changed', () => loadModel());
  listen('project-meta-changed', () => loadProjects());

  state.projectFilesHas = (f) => state.files.some((x) => x.file === f);
  await Promise.all([loadModel(), loadProjectData()]);
  $('#segList').focus();
}

init().catch((e) => toast(e.message, 'error'));
