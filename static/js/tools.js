// Projects, tools menu, clear dialog, patch, glossary, shortcuts.
import { api } from './api.js';
import { shortcutTable } from './inspector.js';
import { $, $$, basename, esc, fmt, html, icon, on } from './dom.js';
import { loadRows, typeLabel } from './list.js';
import { defineAction, emit, runAction, state } from './state.js';
import { alertDialog, bindMenu, busy, confirmDialog, openDialog, promptDialog, toast } from './ui.js';

/* ---------------- Tools menu ---------------- */
function renderToolsMenu() {
  $('#toolsMenu').innerHTML = `
    <div class="menu-label">Chất lượng bản dịch</div>
    <button class="menu-item" data-tool="glossary">${icon('book')}Bảng thuật ngữ…<span class="kbd">${fmt(state.glossary.length)}</span></button>
    <button class="menu-item" data-tool="unify">${icon('layers')}Đồng bộ bản dịch câu trùng…</button>
    <button class="menu-item" data-tool="qa">${icon('shield')}Chạy lại kiểm tra QA</button>
    <button class="menu-item" data-tool="validate">${icon('checkCircle')}Kiểm tra logic dự án</button>
    <div class="menu-sep"></div>
    <button class="menu-item" data-tool="clear">${icon('eraser')}Xóa bản dịch…</button>
    <div class="menu-sep"></div>
    <div class="menu-label">Dự án &amp; game</div>
    <button class="menu-item" data-tool="gamepath">${icon('folder')}Đổi đường dẫn game…</button>
    <button class="menu-item" data-tool="resync">${icon('refresh')}Đồng bộ lại từ dump gốc</button>
    <button class="menu-item" data-tool="reextract">${icon('download')}Trích xuất lại từ game (game cập nhật)…</button>
    <button class="menu-item danger" data-tool="restore">${icon('undo')}Khôi phục tiếng Nhật vào game…</button>
    <div class="menu-sep"></div>
    <button class="menu-item" data-tool="appearance">${icon('palette')}Giao diện…</button>
    <button class="menu-item" data-tool="shortcuts">${icon('keyboard')}Phím tắt<span class="kbd">?</span></button>`;
}

const reloadAll = async () => { emit('stats-dirty'); await loadRows({ scroll: false }); };

const TOOLS = {
  glossary: openGlossary,
  async unify() {
    if (!(await confirmDialog('Đồng bộ câu trùng',
      'Các câu gốc giống hệt nhau nhưng đang có nhiều bản dịch khác nhau sẽ được đồng bộ về một bản (ưu tiên bản đã duyệt, rồi bản phổ biến nhất).\nDòng đã duyệt không bị thay đổi.',
      { okLabel: 'Đồng bộ' }))) return;
    const r = await api.unify();
    toast(`Đã đồng bộ ${fmt(r.updated)} dòng thuộc ${fmt(r.groups)} nhóm câu trùng`, 'success');
    await reloadAll();
  },
  async qa() {
    const r = await api.recheckQa();
    const changes = Object.entries(r.changes || {}).map(([k, v]) => `${k}: ${v}`).join(', ');
    toast(`Đã chạy lại QA${changes ? ` — thay đổi: ${changes}` : ' — không có thay đổi'}`, 'success');
    await reloadAll();
  },
  async validate() {
    const r = await api.validate();
    const qa = Object.entries(r.qa_counts || {}).map(([k, v]) => `• ${state.flagLabels[k] || k}: ${fmt(v)}`).join('\n');
    await alertDialog('Kiểm tra logic dự án',
      `Chuỗi khóa logic bị dịch: ${r.key_errors.length}\nLỗi sẵn có trong game gốc (không do bản dịch): ${r.dump_errors_in_original.length}\n\nThống kê QA các dòng đã dịch:\n${qa || '(không có)'}`,
      { kind: r.key_errors.length ? 'danger' : 'info', detail: [...r.key_errors.slice(0, 30), ...r.dump_errors_in_original.slice(0, 20)].join('\n') });
  },
  clear: openClearDialog,
  async gamepath() {
    const path = await promptDialog('Đổi đường dẫn game', 'Thư mục game (chứa Game.exe và thư mục Data)',
      { value: state.project?.game_path || '', okLabel: 'Lưu', placeholder: 'E:\\Games\\TenGame' });
    if (!path) return;
    const r = await api.setGamePath(path);
    toast(`Đã cập nhật: ${r.project.game_data_path}`, 'success');
    emit('project-meta-changed');
  },
  async resync() {
    if (!(await confirmDialog('Đồng bộ lại từ dump gốc', 'Quét lại danh sách chuỗi từ dump gốc của dự án. Bản dịch hiện có được giữ nguyên.', { okLabel: 'Đồng bộ' }))) return;
    const r = await api.reextract(false);
    const s = r.stats;
    toast(`Giữ ${fmt(s.kept)} · đổi ${fmt(s.changed)} · thêm ${fmt(s.inserted)} · xóa ${fmt(s.deleted)} dòng`, 'success', 6000);
    await reloadAll();
  },
  async reextract() {
    if (!(await confirmDialog('Trích xuất lại từ game',
      'Dùng khi game ra bản cập nhật. Game phải là bản GỐC chưa vá (nếu đã vá, hãy “Khôi phục tiếng Nhật vào game” trước) — tool sẽ từ chối nếu phát hiện game đã bị vá.\n\nBản dịch của các câu không đổi được giữ nguyên.',
      { okLabel: 'Trích xuất lại' }))) return;
    const r = await api.reextract(true);
    const s = r.stats;
    await alertDialog('Đã trích xuất lại', `Giữ ${fmt(s.kept)}, thay đổi ${fmt(s.changed)}, thêm mới ${fmt(s.inserted)}, xóa ${fmt(s.deleted)} dòng.`, { kind: 'success' });
    await reloadAll();
  },
  async restore() {
    if (!(await confirmDialog('Khôi phục tiếng Nhật vào game',
      'Ghi lại toàn bộ văn bản gốc tiếng Nhật vào game (gỡ bản dịch khỏi game).\nDữ liệu dịch trong dự án KHÔNG bị xóa — bạn có thể Patch lại bất cứ lúc nào.',
      { okLabel: 'Khôi phục', danger: true }))) return;
    const r = await api.restore();
    if (r.success) toast(r.message, 'success', 6000); else await alertDialog('Không khôi phục được', r.message, { kind: 'danger' });
  },
  appearance: () => runAction('appearance'),
  shortcuts: openShortcuts,
};

/* ---------------- Clear dialog ---------------- */
async function openClearDialog() {
  const body = html(`<div>
    <div class="field"><label>Phạm vi</label><div class="radio-cards">
      <label><input type="radio" name="cscope" value="file" ${state.file ? 'checked' : 'disabled'}>
        <span><strong>File đang chọn</strong><span class="sub">${state.file ? esc(state.file) : 'Chưa chọn file'}</span></span></label>
      <label><input type="radio" name="cscope" value="range"><span><strong>Khoảng ID</strong><span class="sub">Từ #… đến #…${state.file ? ' (trong file đang chọn)' : ''}</span></span></label>
      <label><input type="radio" name="cscope" value="all" ${state.file ? '' : 'checked'}><span><strong>Toàn bộ game</strong><span class="sub">Mọi file</span></span></label>
    </div></div>
    <div class="row hidden" id="rangeRow" style="margin-bottom:14px">
      <input class="input" type="number" id="rFrom" placeholder="Từ ID" value="${state.rows[0]?.id || ''}">
      <span class="muted">→</span>
      <input class="input" type="number" id="rTo" placeholder="Đến ID" value="${state.rows.at(-1)?.id || ''}">
    </div>
    <div class="field"><label>Chỉ các loại (bỏ trống = mọi loại)</label><div class="type-grid" id="ctypes"><div class="skeleton"></div></div></div>
    <div class="field"><label>Xóa phần nào</label><div class="radio-cards">
      <label><input type="radio" name="cmode" value="both" checked><span><strong>Cả bản AI và bản dịch</strong><span class="sub">Dòng về trạng thái chưa dịch (Patch sẽ dùng tiếng Nhật gốc)</span></span></label>
      <label><input type="radio" name="cmode" value="mtl_only"><span><strong>Chỉ gợi ý AI</strong></span></label>
      <label><input type="radio" name="cmode" value="trans_only"><span><strong>Chỉ bản dịch</strong><span class="sub">Giữ lại gợi ý AI</span></span></label>
    </div></div></div>`);
  const loadTypes = async () => {
    const scope = $('input[name=cscope]:checked', body).value;
    const types = await api.typeStats(scope === 'all' ? null : state.file);
    $('#ctypes', body).innerHTML = types.map((t) => `<label><input type="checkbox" value="${esc(t.row_type)}">
      ${t.translatable ? '' : '🔒 '}${esc(typeLabel(t.row_type))}<span class="n">${fmt(t.translated)} đã dịch</span></label>`).join('');
  };
  body.addEventListener('change', (e) => {
    if (e.target.name === 'cscope') { $('#rangeRow', body).classList.toggle('hidden', e.target.value !== 'range'); loadTypes(); }
  });
  loadTypes();
  const d = openDialog({
    title: 'Xóa bản dịch', body, width: 'wide',
    actions: [{ label: 'Hủy', value: null }, { label: 'Xóa', kind: 'danger solid', icon: 'eraser', onClick: () => d.close(true) }],
  });
  if (!(await d.result)) return;
  const scope = $('input[name=cscope]:checked', body).value;
  const mode = $('input[name=cmode]:checked', body).value;
  const types = $$('#ctypes input:checked', body).map((c) => c.value);
  const req = { clear_type: mode, row_types: types.length ? types : null };
  let desc;
  if (scope === 'file') { Object.assign(req, { target: 'file', file: state.file }); desc = `file “${basename(state.file)}”`; }
  else if (scope === 'all') { Object.assign(req, { target: 'all' }); desc = 'TOÀN BỘ GAME'; }
  else {
    const a = parseInt($('#rFrom', body).value, 10); const b = parseInt($('#rTo', body).value, 10);
    if (Number.isNaN(a) && Number.isNaN(b)) { toast('Nhập ít nhất một mốc ID.', 'warn'); return; }
    Object.assign(req, { target: 'range', file: state.file, start_id: Number.isNaN(a) ? null : a, end_id: Number.isNaN(b) ? null : b });
    desc = `#${Number.isNaN(a) ? '1' : a} → #${Number.isNaN(b) ? 'cuối' : b}${state.file ? ` trong “${basename(state.file)}”` : ''}`;
  }
  const what = { both: 'bản AI và bản dịch', mtl_only: 'gợi ý AI', trans_only: 'bản dịch' }[mode];
  if (!(await confirmDialog('Xác nhận xóa', `Xóa ${what} của ${desc}${types.length ? ` (loại: ${types.map(typeLabel).join(', ')})` : ''}?\nKhông thể hoàn tác.`,
    { okLabel: 'Xóa', danger: true }))) return;
  const r = await api.clearRows(req);
  toast(`Đã xóa ${fmt(r.affected)} dòng`, 'success');
  await reloadAll();
}

/* ---------------- Patch ---------------- */
async function patchGame() {
  const btn = $('#btnPatch');
  if (!state.project) return;
  if (!state.project.game_path_exists) {
    await alertDialog('Không tìm thấy game', `Thư mục Data của game không tồn tại:\n${state.project.game_data_path || '(chưa đặt)'}\n\nHãy đổi đường dẫn game trong menu Công cụ.`, { kind: 'warn' });
    return;
  }
  const s = state.stats;
  if (!(await confirmDialog('Patch vào game',
    `Ghi bản dịch vào: ${state.project.game_data_path}\n\n• ${fmt(s.completed)} dòng có bản dịch sẽ được ghi (gồm ${fmt(s.mtl)} dòng AI chưa duyệt)\n• ${fmt(s.empty + s.qa)} dòng chưa dịch / lỗi QA: lỗi QA vẫn được ghi nếu có chữ, còn dòng trống giữ tiếng Nhật\n• ${fmt(s.locked)} dòng khóa logic luôn giữ tiếng Nhật\n\nLần Patch đầu tiên sẽ tự sao lưu dữ liệu game.`,
    { okLabel: 'Patch' }))) return;
  await busy(btn, async () => {
    let r = await api.patch(false);
    if (!r.success && r.blocked) {
      const force = await confirmDialog('Patch bị chặn', `${r.message}\n\nBạn có muốn ép vá không? (Không khuyến khích — game có thể lỗi ở các chỗ dưới đây)`,
        { okLabel: 'Vẫn ép vá', danger: true, detail: (r.errors || []).join('\n') });
      if (!force) return;
      r = await api.patch(true);
    }
    if (r.success) {
      await alertDialog('Đã Patch vào game', `${r.message}\n\nMở game để kiểm tra ngay!`,
        { kind: 'success', detail: (r.mismatched || []).length ? `Dòng bị bỏ qua (dump gốc khác DB):\n${r.mismatched.join('\n')}` : '' });
    } else {
      await alertDialog('Patch thất bại', r.message, { kind: 'danger' });
    }
  });
}

/* ---------------- Glossary ---------------- */
async function openGlossary() {
  const g = await api.glossary();
  const text = (g.entries || []).map((e) => `${e.src} = ${e.dst}${e.note ? `  # ${e.note}` : ''}`).join('\n');
  const body = html(`<div>
    <div class="callout">${icon('book')}<div>Mỗi dòng một thuật ngữ: <code>tiếng Nhật = tiếng Việt</code>, thêm <code># ghi chú</code> nếu cần.
      Thuật ngữ có trong câu đang dịch sẽ được gửi kèm cho AI, và hiện ở khung chi tiết để chèn nhanh.</div></div>
    <textarea class="textarea mono" id="glossText" rows="16" spellcheck="false" placeholder="マリーカ = Marika\nプシカ = Pushika  # nhân vật chính\nグール = Ghoul">${esc(text)}</textarea>
    <div class="hint" id="glossHint" style="margin-top:6px"></div></div>`);
  const parse = () => {
    const entries = []; const bad = [];
    $('#glossText', body).value.split('\n').forEach((line, i) => {
      if (!line.trim()) return;
      const [main, ...note] = line.split('#');
      const eq = main.indexOf('=');
      const src = eq >= 0 ? main.slice(0, eq).trim() : '';
      const dst = eq >= 0 ? main.slice(eq + 1).trim() : '';
      if (!src || !dst) bad.push(i + 1); else entries.push({ src, dst, note: note.join('#').trim() });
    });
    $('#glossHint', body).innerHTML = `${fmt(entries.length)} thuật ngữ${bad.length ? ` · <span style="color:var(--st-qa)">dòng sai định dạng: ${bad.join(', ')}</span>` : ''}`;
    return { entries, bad };
  };
  body.addEventListener('input', parse);
  parse();
  const d = openDialog({
    title: 'Bảng thuật ngữ', body, width: 'wide',
    actions: [{ label: 'Hủy', value: null }, { label: 'Lưu', kind: 'primary', onClick: async (btn) => {
      const { entries, bad } = parse();
      if (bad.length && !(await confirmDialog('Có dòng sai định dạng', `Các dòng ${bad.join(', ')} sẽ bị bỏ qua. Vẫn lưu?`))) return;
      await busy(btn, async () => {
        const r = await api.saveGlossary(entries);
        state.glossary = entries;
        emit('glossary-changed');
        toast(`Đã lưu ${fmt(r.count)} thuật ngữ`, 'success');
        d.close(true);
      });
    } }],
  });
}

function openShortcuts() {
  openDialog({ title: 'Phím tắt', body: shortcutTable(), actions: [{ label: 'Đóng', value: true, kind: 'primary' }] });
}

/* ---------------- Projects ---------------- */
async function newProject() {
  const body = html(`<div>
    <div class="callout">${icon('info')}<div>Tool sẽ chạy <code>WolfTL --create</code> để bóc tách kịch bản. Game khác không bị ảnh hưởng.</div></div>
    <div class="field"><label>Tên game</label><input class="input" id="npName" placeholder="Ví dụ: Ghoul Goula Compagnia" autofocus></div>
    <div class="field"><label>Thư mục game</label><input class="input mono" id="npPath" placeholder="E:\\Games\\TenGame">
      <div class="hint">Thư mục chứa Game.exe hoặc thư mục Data. Nếu game đóng gói Data.wolf, hãy giải nén trước.</div></div></div>`);
  const d = openDialog({
    title: 'Thêm game mới', body,
    actions: [{ label: 'Hủy', value: null }, { label: 'Tạo dự án', kind: 'primary', icon: 'plus', onClick: async (btn) => {
      const name = $('#npName', body).value.trim(); const path = $('#npPath', body).value.trim();
      if (!name || !path) { toast('Nhập đủ tên và thư mục game.', 'warn'); return; }
      btn.dataset.busy = 'Đang bóc tách…';
      await busy(btn, async () => {
        try {
          const r = await api.createProject(name, path);
          toast(`Đã tạo dự án ${r.project.name}`, 'success');
          d.close(true);
          emit('project-changed');
        } catch (err) { toast(err.message, 'error'); }
      });
    } }],
  });
}

async function importNel() {
  const body = html(`<div>
    <div class="field"><label>Gói dự án (.nel)</label><input class="input" type="file" id="nelFile" accept=".nel,.zip" style="padding-top:5px"></div>
    <div class="field"><label>Thư mục game trên máy này (tùy chọn)</label><input class="input mono" id="nelPath" placeholder="Bỏ trống để dùng đường dẫn trong gói">
      <div class="hint">Cần đường dẫn game đúng để có thể Patch.</div></div></div>`);
  const d = openDialog({
    title: 'Nạp gói .nel', body,
    actions: [{ label: 'Hủy', value: null }, { label: 'Nạp dự án', kind: 'primary', icon: 'upload', onClick: async (btn) => {
      const f = $('#nelFile', body).files[0];
      if (!f) { toast('Chọn file .nel.', 'warn'); return; }
      const form = new FormData();
      form.append('file', f);
      const p = $('#nelPath', body).value.trim();
      if (p) form.append('override_game_path', p);
      await busy(btn, async () => {
        try {
          const r = await api.importNel(form);
          toast(`Đã nạp dự án ${r.project.name}`, 'success');
          d.close(true);
          if (r.warning) alertDialog('Lưu ý', r.warning, { kind: 'warn' });
          emit('project-changed');
        } catch (err) { toast(err.message, 'error'); }
      });
    } }],
  });
}

function exportNel() {
  if (!state.project) return;
  const a = document.createElement('a');
  a.href = `/api/projects/export-nel?project_id=${encodeURIComponent(state.project.id)}`;
  a.download = '';
  document.body.appendChild(a); a.click(); a.remove();
  toast('Đang đóng gói .nel…', 'info');
}

export function initTools() {
  bindMenu($('#btnTools'), $('#toolsMenu'));
  $('#btnTools').addEventListener('click', renderToolsMenu, true);
  on($('#toolsMenu'), 'click', '[data-tool]', (e, b) => {
    Promise.resolve(TOOLS[b.dataset.tool]()).catch((err) => toast(err.message, 'error'));
  });
  $('#btnPatch').addEventListener('click', () => patchGame().catch((e) => toast(e.message, 'error')));
  defineAction('new-project', newProject);
  defineAction('import-nel', importNel);
  defineAction('export-nel', exportNel);
  defineAction('shortcuts', openShortcuts);
  defineAction('glossary', openGlossary);
}
