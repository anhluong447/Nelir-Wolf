// Tiny shared store with change events.
import { store, save } from './dom.js';

const listeners = new Map();

export const state = {
  project: null,          // active project meta
  projects: [],
  files: [],
  stats: null,            // global stats
  scopeStats: null,       // stats for current file scope
  settings: null,
  glossary: [],
  flagLabels: {},
  translatableTypes: new Set(),

  // list query
  file: null,
  status: store('nelir.status', 4),   // default: chưa duyệt
  rowType: '',
  search: '',
  page: 1,
  pageSize: store('nelir.pageSize', 50),
  total: 0,
  rows: [],
  selectedId: null,

  ui: store('nelir.ui', {}),
  job: null,              // running batch job
};

export function emit(event, payload) {
  (listeners.get(event) || []).forEach((fn) => {
    try { fn(payload); } catch (e) { console.error(`listener ${event}`, e); }
  });
}

export function listen(event, fn) {
  if (!listeners.has(event)) listeners.set(event, []);
  listeners.get(event).push(fn);
}

export function setUi(patch) {
  Object.assign(state.ui, patch);
  save('nelir.ui', state.ui);
  const root = document.documentElement;
  if (state.ui.theme) root.dataset.theme = state.ui.theme;
  if (state.ui.density) root.dataset.density = state.ui.density; else delete root.dataset.density;
  if (state.ui.fontsize) root.dataset.fontsize = state.ui.fontsize; else delete root.dataset.fontsize;
}

export const STATUS = {
  0: { label: 'Chưa dịch', short: 'Trống', cls: 'st-0' },
  1: { label: 'AI dịch, chưa duyệt', short: 'AI', cls: 'st-1' },
  2: { label: 'Đã duyệt', short: 'Duyệt', cls: 'st-2' },
  3: { label: 'Lỗi QA, cần xem lại', short: 'QA', cls: 'st-3' },
};

/** Status filter chips: value sent to /api/rows. */
export const FILTERS = [
  { value: 4, label: 'Cần xử lý', key: 'todo', hint: 'Chưa dịch + AI chưa duyệt + lỗi QA' },
  { value: 0, label: 'Chưa dịch', key: 'empty', sw: 'sw-0' },
  { value: 3, label: 'Lỗi QA', key: 'qa', sw: 'sw-3' },
  { value: 1, label: 'AI chưa duyệt', key: 'mtl', sw: 'sw-1' },
  { value: 2, label: 'Đã duyệt', key: 'translated', sw: 'sw-2' },
  { value: 5, label: 'Khóa', key: 'locked', sw: 'sw-locked' },
  { value: -1, label: 'Tất cả', key: 'total' },
];

export function filterCount(stats, f) {
  if (!stats) return 0;
  if (f.key === 'todo') return stats.empty + stats.mtl + stats.qa;
  return stats[f.key] || 0;
}
