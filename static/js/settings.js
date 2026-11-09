// Settings dialog: AI providers, translation & QA, appearance.
import { api } from './api.js';
import { $, $$, esc, html, icon, on } from './dom.js';
import { defineAction, emit, setUi, state } from './state.js';
import { busy, confirmDialog, openDialog, toast } from './ui.js';

const GEMINI_MODELS = [
  'gemini-3.5-flash-lite', 'gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-3.1-flash-lite',
  'gemini-2.5-flash-lite', 'gemini-3.6-flash', 'gemini-3.8-flash',
];
const mask = (k) => (k.length > 14 ? `${k.slice(0, 8)}…${k.slice(-6)}` : '••••••');

function providerPanel(s) {
  const g = s.gemini;
  return `
  <div class="tabs" id="provTabs">
    <button class="tab" data-prov="gemini">Google Gemini</button>
    <button class="tab" data-prov="kaggle">Kaggle / Local</button>
    <button class="tab" data-prov="openrouter">OpenRouter</button>
  </div>
  <div data-panel="gemini">
    <div class="callout">${icon('info')}<div>Mỗi batch luôn thử <strong>NV1</strong> trước; gặp giới hạn (429) thì xuống NV2 → NV5 cho batch đó.
      Khi một key lỗi ở mọi model, hệ thống tự chuyển sang key kế tiếp và nhớ lại key đang dùng.</div></div>
    <div class="card">
      <div class="row"><strong class="grow">${icon('key', 'icon-sm')} API key</strong><span class="muted" id="keyCount"></span></div>
      <div class="row" style="margin-top:8px">
        <input class="input" type="password" id="newKey" placeholder="Dán Google AI Studio key (AIza…) rồi Enter" autocomplete="off">
        <button class="btn primary" id="addKey">${icon('plus', 'icon-sm')}Thêm</button>
      </div>
      <div class="key-list" id="keyList"></div>
    </div>
    <div class="field"><label>Thứ tự model ưu tiên</label>
      <datalist id="geminiModels">${GEMINI_MODELS.map((m) => `<option value="${m}">`).join('')}</datalist>
      ${[1, 2, 3, 4, 5].map((i) => `<div class="model-row"><span class="nv">NV${i}</span>
        <input class="input" list="geminiModels" id="gm${i}" value="${esc(g[`model_${i}`] || '')}" placeholder="tên model"></div>`).join('')}
    </div>
    <div class="field"><label>Base URL</label><input class="input mono" id="geminiBase" value="${esc(g.base_url)}"></div>
  </div>
  <div data-panel="kaggle" class="hidden">
    <div class="callout">${icon('terminal')}<div>Ollama chạy local hoặc trên Kaggle qua Cloudflare Tunnel — không tốn phí, không giới hạn quota.</div></div>
    <div class="field"><label>Base URL</label><input class="input mono" id="kaggleBase" value="${esc(s.kaggle.base_url)}" placeholder="http://localhost:11434/v1 hoặc https://xxxx.trycloudflare.com/v1"></div>
    <div class="field"><label>API key</label><input class="input" id="kaggleKey" value="${esc(s.kaggle.api_key)}"><div class="hint">Ollama không cần key, để “local”.</div></div>
    <div class="field"><label>Model</label><input class="input" id="kaggleModel" value="${esc(s.kaggle.model)}" placeholder="qwen2.5:32b"></div>
  </div>
  <div data-panel="openrouter" class="hidden">
    <div class="callout">${icon('globe')}<div>Hàng trăm model qua một API key duy nhất.</div></div>
    <div class="field"><label>Base URL</label><input class="input mono" id="orBase" value="${esc(s.openrouter.base_url)}"></div>
    <div class="field"><label>API key</label><input class="input" type="password" id="orKey" value="${esc(s.openrouter.api_key)}" placeholder="sk-or-v1-…" autocomplete="off"></div>
    <div class="field"><label>Model</label><input class="input" id="orModel" value="${esc(s.openrouter.model)}"></div>
  </div>
  <div class="row" style="margin-top:6px">
    <button class="btn" id="testProvider">${icon('plug', 'icon-sm')}Kiểm tra kết nối</button>
    <span class="muted" style="font-size:12px">Provider được chọn ở tab trên sẽ là provider dùng để dịch.</span>
  </div>
  <pre class="detail hidden" id="testResult"></pre>`;
}

function translatePanel(s) {
  return `
    <h4>Dịch &amp; kiểm tra chất lượng</h4>
    <div class="field"><label>Số câu mỗi batch</label>
      <input class="input" type="number" min="1" max="100" id="batchSize" value="${esc(s.batch_size)}" style="width:120px">
      <div class="hint">10–20 là hợp lý cho Gemini/OpenRouter. Batch lớn nhanh hơn nhưng dễ trả về sai định dạng.</div></div>
    <div class="field"><label>Prompt hệ thống
        <button class="btn ghost sm" id="resetPrompt" style="float:right">${icon('undo', 'icon-sm')}Về mặc định</button></label>
      <textarea class="textarea" id="sysPrompt" rows="10" placeholder="Để trống = prompt mặc định">${esc(s.system_prompt)}</textarea>
      <div class="hint">Glossary của dự án được tự động gửi kèm khi câu có chứa thuật ngữ.</div></div>
    <div class="field"><label>Số ký tự tối đa mỗi dòng thoại</label>
      <input class="input" type="number" min="0" max="200" id="qaMaxLine" value="${esc(s.qa_max_line_chars)}" style="width:120px">
      <div class="hint">Dòng Lời thoại / Lựa chọn dài hơn được cảnh báo “quá dài” (không chặn Patch). 0 = tắt.</div></div>`;
}

function appearancePanel() {
  const ui = state.ui;
  const opt = (name, value, label, sub, cur) => `<label><input type="radio" name="${name}" value="${value}" ${cur === value ? 'checked' : ''}>
      <span><strong>${label}</strong><span class="sub">${sub}</span></span></label>`;
  return `
    <h4>Giao diện</h4>
    <div class="field"><label>Chủ đề</label><div class="radio-cards">
      ${opt('theme', 'dark', 'Tối', 'Nền xám đậm, dịu mắt khi làm việc lâu', ui.theme || document.documentElement.dataset.theme)}
      ${opt('theme', 'light', 'Sáng', 'Nền giấy ngà, hợp phòng sáng', ui.theme || document.documentElement.dataset.theme)}
    </div></div>
    <div class="field"><label>Mật độ danh sách</label><div class="radio-cards">
      ${opt('density', '', 'Thoải mái', 'Khoảng cách rộng, dễ đọc', ui.density || '')}
      ${opt('density', 'compact', 'Gọn', 'Thấy nhiều dòng hơn trên màn hình', ui.density || '')}
    </div></div>
    <div class="field"><label>Cỡ chữ</label><div class="radio-cards">
      ${opt('fontsize', '', 'Thường', '13.5px', ui.fontsize || '')}
      ${opt('fontsize', 'large', 'Lớn', '15px — dễ đọc chữ Nhật hơn', ui.fontsize || '')}
    </div></div>`;
}

export async function openSettings(section = 'ai') {
  const s = await api.settings();
  let keys = [...(s.gemini.keys || [])];
  let activeIdx = s.gemini.active_key_index || 0;
  let provider = s.active_provider || 'gemini';

  const body = html(`<div class="settings-layout">
      <nav class="settings-nav">
        <button class="menu-item" data-sec="ai">${icon('sparkles')}Nhà cung cấp AI</button>
        <button class="menu-item" data-sec="translate">${icon('shield')}Dịch &amp; QA</button>
        <button class="menu-item" data-sec="ui">${icon('palette')}Giao diện</button>
      </nav>
      <div class="settings-panel">
        <div data-sec-panel="ai">${providerPanel(s)}</div>
        <div data-sec-panel="translate" class="hidden">${translatePanel(s)}</div>
        <div data-sec-panel="ui" class="hidden">${appearancePanel()}</div>
      </div></div>`);

  const showSection = (sec) => {
    $$('[data-sec]', body).forEach((b) => b.classList.toggle('active', b.dataset.sec === sec));
    $$('[data-sec-panel]', body).forEach((p) => p.classList.toggle('hidden', p.dataset.secPanel !== sec));
  };
  const showProvider = (p) => {
    provider = p;
    $$('[data-prov]', body).forEach((b) => b.classList.toggle('active', b.dataset.prov === p));
    $$('[data-panel]', body).forEach((el) => el.classList.toggle('hidden', el.dataset.panel !== p));
  };
  const renderKeys = () => {
    $('#keyCount', body).textContent = `${keys.length} key`;
    $('#keyList', body).innerHTML = keys.length ? keys.map((k, i) => `
      <div class="key-row ${i === activeIdx ? 'active' : ''}" data-i="${i}">
        <span class="tag ${i === activeIdx ? 'st-2' : ''}">#${i + 1}${i === activeIdx ? ' · đang dùng' : ''}</span>
        <span class="mono grow ellipsis" title="${esc(mask(k))}">${esc(mask(k))}</span>
        <span class="result" id="kr${i}"></span>
        <button class="btn ghost sm" data-k="test">${icon('plug', 'icon-sm')}Test</button>
        ${i === activeIdx ? '' : '<button class="btn ghost sm" data-k="use">Dùng</button>'}
        <button class="btn ghost sm icon-only" data-k="up" ${i === 0 ? 'disabled' : ''} title="Lên">${icon('arrowUp', 'icon-sm')}</button>
        <button class="btn ghost sm icon-only" data-k="down" ${i === keys.length - 1 ? 'disabled' : ''} title="Xuống">${icon('arrowDown', 'icon-sm')}</button>
        <button class="btn ghost sm icon-only danger" data-k="del" title="Xóa key">${icon('trash', 'icon-sm')}</button>
      </div>`).join('') : '<div class="muted" style="padding:8px;font-size:12px">Chưa có key nào.</div>';
  };
  const addKey = () => {
    const v = $('#newKey', body).value.trim();
    if (!v) return;
    if (keys.includes(v)) { toast('Key này đã có trong danh sách.', 'warn'); return; }
    keys.push(v);
    $('#newKey', body).value = '';
    renderKeys();
  };

  on(body, 'click', '[data-sec]', (e, b) => showSection(b.dataset.sec));
  on(body, 'click', '[data-prov]', (e, b) => showProvider(b.dataset.prov));
  $('#addKey', body).addEventListener('click', addKey);
  $('#newKey', body).addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addKey(); } });
  on(body, 'click', '[data-k]', async (e, b) => {
    const i = Number(b.closest('.key-row').dataset.i);
    const act = b.dataset.k;
    if (act === 'use') activeIdx = i;
    if (act === 'up' || act === 'down') {
      const j = act === 'up' ? i - 1 : i + 1;
      [keys[i], keys[j]] = [keys[j], keys[i]];
      if (activeIdx === i) activeIdx = j; else if (activeIdx === j) activeIdx = i;
    }
    if (act === 'del') {
      if (!(await confirmDialog('Xóa key?', `Xóa key #${i + 1} (${mask(keys[i])}) khỏi danh sách?`, { okLabel: 'Xóa', danger: true }))) return;
      keys.splice(i, 1);
      if (activeIdx >= keys.length) activeIdx = Math.max(0, keys.length - 1);
    }
    if (act === 'test') {
      const out = $(`#kr${i}`, body);
      out.innerHTML = '<span class="spinner" style="display:inline-block"></span>';
      try {
        const r = await api.testKey({ api_key: keys[i], base_url: $('#geminiBase', body).value.trim(), model: $('#gm1', body).value.trim() });
        out.innerHTML = `<span style="color:var(${r.ok ? '--st-reviewed' : '--st-qa'})">${esc(r.message)}</span>`;
      } catch (err) { out.textContent = err.message; }
      return;
    }
    renderKeys();
  });
  $('#resetPrompt', body).addEventListener('click', () => { $('#sysPrompt', body).value = s.default_system_prompt || ''; });
  body.addEventListener('change', (e) => {
    if (['theme', 'density', 'fontsize'].includes(e.target.name)) setUi({ [e.target.name]: e.target.value });
  });
  $('#testProvider', body).addEventListener('click', async (e) => {
    const out = $('#testResult', body);
    const p = collect().provider;
    await busy(e.currentTarget, async () => {
      const c = collect();
      const req = p === 'gemini' ? { base_url: c.gemini.base_url, api_key: keys[activeIdx] || '', model: c.gemini.model_1 }
        : p === 'kaggle' ? { base_url: c.kaggle.base_url, api_key: c.kaggle.api_key, model: c.kaggle.model }
          : { base_url: c.openrouter.base_url, api_key: c.openrouter.api_key, model: c.openrouter.model };
      try {
        const r = await api.testConnection({ provider: p, ...req });
        out.textContent = r.message;
        out.style.color = r.ok ? 'var(--st-reviewed)' : 'var(--st-qa)';
      } catch (err) { out.textContent = err.message; out.style.color = 'var(--st-qa)'; }
      out.classList.remove('hidden');
    });
  });

  function collect() {
    return {
      provider,
      active_provider: provider,
      batch_size: $('#batchSize', body).value.trim(),
      system_prompt: $('#sysPrompt', body).value.trim(),
      qa_max_line_chars: $('#qaMaxLine', body).value.trim(),
      gemini: {
        base_url: $('#geminiBase', body).value.trim(), keys, active_key_index: activeIdx,
        ...Object.fromEntries([1, 2, 3, 4, 5].map((i) => [`model_${i}`, $(`#gm${i}`, body).value.trim()])),
      },
      kaggle: { base_url: $('#kaggleBase', body).value.trim(), api_key: $('#kaggleKey', body).value.trim(), model: $('#kaggleModel', body).value.trim() },
      openrouter: { base_url: $('#orBase', body).value.trim(), api_key: $('#orKey', body).value.trim(), model: $('#orModel', body).value.trim() },
    };
  }

  showSection(section);
  showProvider(provider);
  renderKeys();
  const d = openDialog({
    title: 'Cài đặt',
    body,
    width: 'xwide',
    actions: [
      { label: 'Đóng', value: null },
      { label: 'Lưu cài đặt', kind: 'primary', onClick: async (btn) => {
        const c = collect();
        delete c.provider;
        if ($('#newKey', body).value.trim()) addKey();
        await busy(btn, async () => {
          try {
            await api.saveSettings(c);
            toast('Đã lưu cài đặt', 'success');
            emit('settings-changed');
            d.close(true);
          } catch (err) { toast(err.message, 'error'); }
        });
      } },
    ],
  });
}

export function initSettings() {
  defineAction('settings', () => openSettings('ai'));
  defineAction('appearance', () => openSettings('ui'));
}
