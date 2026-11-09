// Thin fetch wrapper: always throws Error(detail) on non-2xx.

async function request(method, url, body, opts = {}) {
  const init = { method, headers: {} , signal: opts.signal };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, init);
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new Error('Không kết nối được tới server Nelir (server đã tắt?)');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.detail || data.message || `Lỗi ${res.status}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

const qs = (params) => {
  const p = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== '') p.set(k, v); });
  const s = p.toString();
  return s ? `?${s}` : '';
};

export const api = {
  get: (url, params) => request('GET', url + qs(params)),
  post: (url, body) => request('POST', url, body ?? {}),
  del: (url) => request('DELETE', url),

  projects: () => api.get('/api/projects'),
  selectProject: (project_id) => api.post('/api/projects/select', { project_id }),
  createProject: (name, game_path) => api.post('/api/projects/create', { name, game_path }),
  importNel: (form) => request('POST', '/api/projects/import-nel', form),
  setGamePath: (game_path) => api.post('/api/projects/game-path', { game_path }),
  reextract: (from_game) => api.post('/api/projects/reextract', { from_game }),

  stats: (file) => api.get('/api/stats', { file }),
  files: () => api.get('/api/files'),
  rows: (q) => api.post('/api/rows', q),
  context: (id, n = 2) => api.get(`/api/rows/${id}/context`, { n }),
  updateRow: (id, translated) => api.post('/api/rows/update', { id, translated }),
  confirmRows: (ids) => api.post('/api/rows/confirm', { ids }),
  clearRows: (body) => api.post('/api/rows/clear', body),
  typeStats: (file) => api.get('/api/types/stats', { file: file || 'ALL' }),

  translateSingle: (id) => api.post('/api/translate/single', { id }),
  translateBatch: (row_ids) => api.post('/api/translate/batch', { row_ids }),

  glossary: () => api.get('/api/glossary'),
  saveGlossary: (entries) => api.post('/api/glossary', { entries }),
  unify: () => api.post('/api/tm/unify'),
  recheckQa: () => api.post('/api/qa/recheck'),
  validate: () => api.get('/api/validate'),
  patch: (force) => api.post('/api/patch', { force }),
  restore: () => api.post('/api/patch/restore'),

  settings: () => api.get('/api/settings'),
  saveSettings: (s) => api.post('/api/settings', s),
  testConnection: (body) => api.post('/api/settings/test', body),
  testKey: (body) => api.post('/api/settings/test-key', body),
};

/** Server-sent events over fetch (so it can be aborted). Calls onEvent(obj) per event. */
export async function streamEvents(url, onEvent, signal) {
  const res = await fetch(url, { signal });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Lỗi ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop();
    for (const part of parts) {
      if (!part.startsWith('data: ')) continue;
      try { onEvent(JSON.parse(part.slice(6))); } catch (e) { console.error('bad SSE event', e); }
    }
  }
}
