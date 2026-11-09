let state = {
  file: null,
  category: null,
  status: -1,
  search: '',
  page: 1,
  pageSize: 50,
  totalPages: 1,
  totalRows: 0,
  currentRows: []
};

let batchState = {
  targetFile: null, // null means ALL, or string for specific file
  abortController: null
};

// Toast helper
function showToast(msg, duration = 3000) {
  const toast = document.getElementById('toast');
  toast.innerText = msg;
  toast.style.display = 'block';
  setTimeout(() => {
    toast.style.display = 'none';
  }, duration);
}

// Format numbers
function formatNum(n) {
  return new Intl.NumberFormat().format(n || 0);
}

// Theme handling
const themeToggle = document.getElementById('themeToggle');
const savedTheme = localStorage.getItem('nelir_theme') || 'dark';
document.documentElement.setAttribute('data-theme', savedTheme);

themeToggle.addEventListener('click', () => {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('nelir_theme', next);
});

// Load Global Stats
async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    const percent = data.total > 0 ? ((data.completed / data.total) * 100).toFixed(1) : 0;
    document.getElementById('statsText').innerText = `${formatNum(data.completed)} / ${formatNum(data.total)} (${percent}%)`;
    document.getElementById('progressBar').style.width = `${percent}%`;
  } catch (e) {
    console.error('Error loading stats:', e);
  }
}

// Load Files into Sidebar
async function loadFiles() {
  try {
    const res = await fetch('/api/files');
    const files = await res.json();
    const container = document.getElementById('fileList');
    container.innerHTML = '';

    // "All Files" item
    const allItem = document.createElement('div');
    allItem.className = `file-item ${state.file === null ? 'active' : ''}`;
    allItem.innerHTML = `<span>📁 Tất cả các file</span>`;
    allItem.onclick = () => {
      state.file = null;
      state.category = null;
      state.page = 1;
      updateActiveFile();
      loadRows();
    };
    container.appendChild(allItem);

    // Group by category
    const groups = {};
    for (const f of files) {
      if (!groups[f.category]) groups[f.category] = [];
      groups[f.category].push(f);
    }

    const catLabels = {
      'Map': '🗺️ Bản đồ (Maps)',
      'CommonEvent': '⚡ Sự kiện chung (Common Events)',
      'Database': '📚 Dữ liệu (Databases)',
      'System': '⚙️ Hệ thống (Game Title / Sys)'
    };

    for (const [cat, catFiles] of Object.entries(groups)) {
      const grpEl = document.createElement('div');
      grpEl.className = 'category-group';
      grpEl.innerHTML = `<div class="category-title">${catLabels[cat] || cat} (${catFiles.length})</div>`;

      for (const f of catFiles) {
        const item = document.createElement('div');
        item.className = `file-item ${state.file === f.file ? 'active' : ''}`;
        item.dataset.file = f.file;
        const displayName = f.file.split(/[\\/]/).pop();
        
        item.innerHTML = `
          <div style="display: flex; align-items: center; gap: 6px; overflow: hidden;">
            <button class="btn" style="padding: 1px 4px; font-size: 10px; border-radius: 4px;" title="Dịch full file này" onclick="event.stopPropagation(); openBatchModal('${escapeJsString(f.file)}')">⚡</button>
            <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 170px;" title="${f.file}">
              ${displayName}
            </span>
          </div>
          <span class="file-pill">${f.translated}/${f.total}</span>
        `;
        
        item.onclick = () => {
          state.file = f.file;
          state.page = 1;
          updateActiveFile();
          loadRows();
        };
        grpEl.appendChild(item);
      }
      container.appendChild(grpEl);
    }
  } catch (e) {
    console.error('Error loading files:', e);
  }
}

function escapeJsString(str) {
  return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function updateActiveFile() {
  document.querySelectorAll('.file-item').forEach(el => {
    if (state.file === null) {
      el.classList.toggle('active', el.innerText.includes('Tất cả các file'));
    } else {
      el.classList.toggle('active', el.dataset.file === state.file);
    }
  });
}

// Load Rows
async function loadRows() {
  const tbody = document.getElementById('rowsBody');
  tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 40px; color: var(--text-muted);">Đang tải dữ liệu...</td></tr>`;

  try {
    const res = await fetch('/api/rows', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        page: state.page,
        page_size: state.pageSize,
        file: state.file,
        status: state.status,
        search: state.search
      })
    });
    const data = await res.json();
    state.currentRows = data.rows;
    state.totalRows = data.total;
    state.totalPages = Math.max(1, Math.ceil(data.total / state.pageSize));

    renderRows(data.rows);
    updatePagination();
  } catch (e) {
    console.error('Error loading rows:', e);
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 40px; color: var(--danger);">Lỗi khi tải dữ liệu!</td></tr>`;
  }
}

// Render Table Rows
function renderRows(rows) {
  const tbody = document.getElementById('rowsBody');
  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 40px; color: var(--text-muted);">Không tìm thấy dòng thoại nào khớp với điều kiện lọc.</td></tr>`;
    return;
  }

  tbody.innerHTML = '';
  for (const r of rows) {
    const tr = document.createElement('tr');
    tr.dataset.id = r.id;

    const statusIcons = { 0: '○', 1: '~', 2: '✓' };
    const statusTitles = { 0: 'Chưa dịch', 1: 'AI dịch (MTL)', 2: 'Đã có bản dịch' };

    tr.innerHTML = `
      <td class="col-stt" style="color: var(--text-muted); font-size: 11px;">#${r.id}</td>
      <td class="col-type"><span class="badge-type badge-${r.row_type}">${r.row_type}</span></td>
      <td class="col-raw"><div class="raw-text">${escapeHtml(r.raw)}</div></td>
      <td class="col-mtl"><div class="mtl-text" id="mtl-${r.id}">${escapeHtml(r.mtl || '')}</div></td>
      <td class="col-trans">
        <textarea class="trans-textarea" id="trans-${r.id}" placeholder="Gõ bản dịch tiếng Việt...">${escapeHtml(r.translated || '')}</textarea>
      </td>
      <td class="col-status">
        <span class="status-badge status-${r.status}" id="status-${r.id}" title="${statusTitles[r.status]}">
          ${statusIcons[r.status]}
        </span>
      </td>
      <td class="col-action">
        <div class="btn-action-group">
          <button class="btn" style="padding: 2px 5px; font-size: 11px;" title="Dịch dòng này bằng AI ngay" onclick="translateSingleRow(${r.id})">⚡</button>
          <button class="btn" style="padding: 2px 5px; font-size: 11px; color: var(--danger);" title="Xóa nhanh bản dịch dòng này" onclick="clearSingleRow(${r.id})">🗑️</button>
        </div>
      </td>
    `;

    const textarea = tr.querySelector('.trans-textarea');
    textarea.addEventListener('blur', () => saveRowTranslation(r.id, textarea.value));
    tbody.appendChild(tr);
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
}

// Save single row translation
async function saveRowTranslation(id, text) {
  try {
    await fetch('/api/rows/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, translated: text })
    });
    const badge = document.getElementById(`status-${id}`);
    if (badge) {
      if (text.trim()) {
        badge.className = 'status-badge status-2';
        badge.innerText = '✓';
      } else {
        const mtlText = document.getElementById(`mtl-${id}`).innerText.trim();
        badge.className = `status-badge status-${mtlText ? 1 : 0}`;
        badge.innerText = mtlText ? '~' : '○';
      }
    }
    loadStats();
  } catch (e) {
    console.error('Error saving row:', e);
  }
}

// Quick translate single row
window.translateSingleRow = async function(id) {
  const btn = event?.currentTarget;
  if (btn) btn.disabled = true;
  showToast(`Đang gọi OpenRouter dịch dòng #${id}...`, 1500);

  try {
    const res = await fetch('/api/translate/single', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id })
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      alert(`❌ Lỗi dịch dòng #${id}:\n${errData.detail || 'Không thể kết nối tới server AI!'}`);
      return;
    }
    const data = await res.json();
    const mtlEl = document.getElementById(`mtl-${id}`);
    if (mtlEl) mtlEl.innerText = data.mtl;

    const transEl = document.getElementById(`trans-${id}`);
    if (transEl) {
      transEl.value = data.translated;
    }

    const badge = document.getElementById(`status-${id}`);
    if (badge) {
      badge.className = `status-badge status-${data.status}`;
      badge.innerText = data.status === 2 ? '✓' : '~';
    }
    showToast(`Dịch xong dòng #${id}!`);
    loadStats();
    loadFiles();
  } catch (e) {
    showToast(`Lỗi khi dịch dòng #${id}`);
  } finally {
    if (btn) btn.disabled = false;
  }
};

// Clear single row quickly
window.clearSingleRow = async function(id) {
  try {
    await fetch('/api/rows/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: 'row', row_id: id, clear_type: 'both' })
    });

    const mtlEl = document.getElementById(`mtl-${id}`);
    if (mtlEl) mtlEl.innerText = '';

    const transEl = document.getElementById(`trans-${id}`);
    if (transEl) transEl.value = '';

    const badge = document.getElementById(`status-${id}`);
    if (badge) {
      badge.className = 'status-badge status-0';
      badge.innerText = '○';
    }

    showToast(`Đã xóa bản dịch dòng #${id}`);
    loadStats();
    loadFiles();
  } catch (e) {
    showToast(`Lỗi khi xóa dòng #${id}`);
  }
};

// Dropdown clear handling
const clearDropdownBtn = document.getElementById('btnClearDropdownBtn');
const clearDropdownMenu = document.getElementById('clearDropdownMenu');

if (clearDropdownBtn && clearDropdownMenu) {
  clearDropdownBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    clearDropdownMenu.classList.toggle('show');
  });

  document.addEventListener('click', () => {
    clearDropdownMenu.classList.remove('show');
  });
}

window.triggerClear = async function(target, clearType) {
  clearDropdownMenu.classList.remove('show');

  if (target === 'file' && !state.file) {
    showToast('Vui lòng chọn một file cụ thể ở danh sách bên trái trước!');
    return;
  }

  const targetName = target === 'file' ? `file "${state.file.split(/[\\/]/).pop()}"` : 'TOÀN BỘ GAME';
  let typeDesc = '';
  if (clearType === 'mtl_only') typeDesc = 'bản dịch máy (MTL)';
  else if (clearType === 'trans_only') typeDesc = 'bản dịch chính thức (TRANSLATED)';
  else if (clearType === 'both') typeDesc = 'TẤT CẢ bản dịch (Reset trắng về 0)';

  const confirmMsg = target === 'all' && clearType === 'both'
    ? '🚨 CẢNH BÁO: Bạn có chắc chắn muốn XÓA TRẮNG TOÀN BỘ BẢN DỊCH CỦA CẢ GAME không? Thao tác này không thể hoàn tác!'
    : `Bạn có chắc muốn xóa ${typeDesc} của ${targetName}?`;

  if (!confirm(confirmMsg)) return;

  try {
    const res = await fetch('/api/rows/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target,
        file: target === 'file' ? state.file : null,
        clear_type: clearType
      })
    });
    const result = await res.json();
    showToast(`Đã xóa thành công ${formatNum(result.affected)} dòng!`);
    loadRows();
    loadStats();
    loadFiles();
  } catch (e) {
    showToast('Lỗi khi thực hiện xóa bản dịch!');
  }
};

// Range Clear Modal Handling
const rangeClearModal = document.getElementById('rangeClearModal');
window.openRangeClearModal = function() {
  clearDropdownMenu.classList.remove('show');
  
  const labelFile = document.getElementById('labelScopeRangeFile');
  const textFile = document.getElementById('scopeRangeFileText');
  const scopeAllRadio = document.getElementById('scopeRangeAll');

  // Default to Global (all files)
  scopeAllRadio.checked = true;

  if (state.file) {
    labelFile.style.display = 'flex';
    textFile.innerText = `📁 Chỉ áp dụng trong file "${state.file.split(/[\\/]/).pop()}"`;
  } else {
    labelFile.style.display = 'none';
  }

  // Pre-fill min/max IDs from current view if available
  if (state.currentRows.length > 0) {
    document.getElementById('inputRangeStart').value = state.currentRows[0].id;
    document.getElementById('inputRangeEnd').value = state.currentRows[state.currentRows.length - 1].id;
  } else {
    document.getElementById('inputRangeStart').value = '';
    document.getElementById('inputRangeEnd').value = '';
  }

  rangeClearModal.classList.add('active');
};

document.getElementById('closeRangeClearModal').addEventListener('click', () => {
  rangeClearModal.classList.remove('active');
});
document.getElementById('cancelRangeClear').addEventListener('click', () => {
  rangeClearModal.classList.remove('active');
});

document.getElementById('confirmRangeClear').addEventListener('click', async () => {
  const startVal = document.getElementById('inputRangeStart').value.trim();
  const endVal = document.getElementById('inputRangeEnd').value.trim();
  const clearType = document.querySelector('input[name="rangeClearType"]:checked').value;
  const scopeVal = document.querySelector('input[name="rangeClearScope"]:checked')?.value || 'all';

  const startId = startVal ? parseInt(startVal) : null;
  const endId = endVal ? parseInt(endVal) : null;

  if (startId === null && endId === null) {
    alert('Vui lòng nhập ít nhất một trong hai mốc ID (Từ ID hoặc Đến ID)!');
    return;
  }

  const targetFile = (scopeVal === 'file' && state.file) ? state.file : null;
  const rangeDesc = `từ ID #${startId || '1'} đến ID #${endId || 'hết'}`;
  const scopeDesc = targetFile ? `trong file "${targetFile.split(/[\\/]/).pop()}"` : 'trên TOÀN BỘ GAME (xuyên suốt mọi file)';
  
  if (!confirm(`Bạn có chắc chắn muốn xóa bản dịch ${rangeDesc} ${scopeDesc}?`)) {
    return;
  }

  try {
    const res = await fetch('/api/rows/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target: 'range',
        file: targetFile,
        start_id: startId,
        end_id: endId,
        clear_type: clearType
      })
    });
    const result = await res.json();
    showToast(`Đã xóa thành công ${formatNum(result.affected)} dòng!`);
    rangeClearModal.classList.remove('active');
    loadRows();
    loadStats();
    loadFiles();
  } catch (e) {
    showToast('Lỗi khi xóa theo khoảng ID!');
  }
});

// ==========================================
// TYPE CLEAR MODAL HANDLING
// ==========================================
const SAFE_TYPES = ['Message', 'Choice', 'DBName', 'DBField', 'SetString', 'Picture', 'GameTitle'];
const RISKY_TYPES = ['Database', 'JumpLabel', 'SetLabel', 'StringCondition', 'CommonEvent', 'CommonEventByName', 'Comment', 'DebugMessage'];

function formatTypeLabel(type) {
  if (type === 'Database') return 'Database (Lệnh sự kiện ⚠️)';
  if (type === 'DBName') return 'DBName (Tên Item/Skill/Quái)';
  if (type === 'DBField') return 'DBField (Mô tả Item/Skill)';
  if (type === 'Message') return 'Message (Lời thoại)';
  if (type === 'Choice') return 'Choice (Lựa chọn)';
  if (type === 'JumpLabel') return 'JumpLabel (Nhãn nhảy ⚠️)';
  if (type === 'SetLabel') return 'SetLabel (Đặt nhãn ⚠️)';
  return type;
}

const typeClearModal = document.getElementById('typeClearModal');
window.openTypeClearModal = async function() {
  clearDropdownMenu.classList.remove('show');
  const scopeSelect = document.getElementById('typeClearScopeSelect');
  const scopeText = document.getElementById('typeClearScopeText');
  const container = document.getElementById('typeClearListContainer');

  if (scopeSelect) {
    scopeSelect.value = state.file ? 'CURRENT' : 'ALL';
  }

  container.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; grid-column: span 2;">Đang tải danh sách loại...</div>';
  typeClearModal.classList.add('active');

  const loadTypeClearStats = async () => {
    container.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; grid-column: span 2;">Đang tải...</div>';
    const scopeVal = scopeSelect ? scopeSelect.value : (state.file ? 'CURRENT' : 'ALL');
    const targetFile = (scopeVal === 'CURRENT' && state.file) ? state.file : null;
    const fileParam = targetFile ? encodeURIComponent(targetFile) : 'ALL';
    if (scopeText) {
      scopeText.innerText = targetFile ? `File: ${targetFile}` : 'Toàn bộ tất cả các file trong game';
    }

    try {
      const res = await fetch(`/api/types/stats?file=${fileParam}`);
      const stats = await res.json();
      container.innerHTML = '';

      for (const t of stats) {
        const isRisky = RISKY_TYPES.includes(t.row_type);
        const label = document.createElement('label');
        label.style.cssText = 'display: flex; align-items: center; gap: 6px; font-size: 12px; cursor: pointer; padding: 5px 8px; border-radius: 4px; background: rgba(255,255,255,0.03); border: 1px solid var(--border);';
        label.innerHTML = `
          <input type="checkbox" class="type-clear-checkbox" value="${t.row_type}" ${isRisky && t.translated > 0 ? 'checked' : ''} style="width: 14px; height: 14px;">
          <span style="${isRisky ? 'color: #f38ba8; font-weight: 500;' : ''}">${formatTypeLabel(t.row_type)}</span>
          <span style="font-size: 10px; color: ${t.translated > 0 ? '#fab387' : 'var(--text-muted)'}; margin-left: auto;">
            (${formatNum(t.translated)}/${formatNum(t.total)})
          </span>
        `;
        container.appendChild(label);
      }
    } catch (err) {
      container.innerHTML = '<div style="color: var(--danger); font-size: 12px; grid-column: span 2;">Lỗi khi tải danh sách loại!</div>';
    }
  };

  if (scopeSelect && !scopeSelect._hasListener) {
    scopeSelect._hasListener = true;
    scopeSelect.addEventListener('change', loadTypeClearStats);
  }

  await loadTypeClearStats();
};

document.getElementById('closeTypeClearModal').addEventListener('click', () => {
  typeClearModal.classList.remove('active');
});
document.getElementById('cancelTypeClear').addEventListener('click', () => {
  typeClearModal.classList.remove('active');
});

document.getElementById('btnSelectRiskyTypes').addEventListener('click', () => {
  document.querySelectorAll('.type-clear-checkbox').forEach(cb => {
    cb.checked = RISKY_TYPES.includes(cb.value);
  });
});
document.getElementById('btnSelectAllClearTypes').addEventListener('click', () => {
  document.querySelectorAll('.type-clear-checkbox').forEach(cb => cb.checked = true);
});
document.getElementById('btnUnselectAllClearTypes').addEventListener('click', () => {
  document.querySelectorAll('.type-clear-checkbox').forEach(cb => cb.checked = false);
});

document.getElementById('confirmTypeClear').addEventListener('click', async () => {
  const checked = Array.from(document.querySelectorAll('.type-clear-checkbox:checked')).map(cb => cb.value);
  if (checked.length === 0) {
    alert('Vui lòng tích chọn ít nhất 1 loại dữ liệu để xóa!');
    return;
  }

  const clearMode = document.querySelector('input[name="typeClearMode"]:checked').value;
  const scopeSelect = document.getElementById('typeClearScopeSelect');
  const scopeVal = scopeSelect ? scopeSelect.value : (state.file ? 'CURRENT' : 'ALL');
  const isAll = scopeVal === 'ALL' || !state.file;
  const targetFile = isAll ? null : state.file;

  const scopeDesc = isAll ? 'TOÀN BỘ GAME' : `trong file "${targetFile.split(/[\\/]/).pop()}"`;
  const desc = `Bạn có chắc muốn xóa bản dịch của các loại:\n[${checked.join(', ')}]\nphạm vi: ${scopeDesc}?`;
  if (!confirm(desc)) return;

  try {
    const res = await fetch('/api/rows/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target: isAll ? 'all' : 'type',
        file: targetFile,
        row_types: checked,
        clear_type: clearMode
      })
    });
    const result = await res.json();
    showToast(`Đã xóa thành công ${formatNum(result.affected)} dòng!`);
    typeClearModal.classList.remove('active');
    loadRows();
    loadStats();
    loadFiles();
  } catch (err) {
    showToast('Lỗi khi thực hiện xóa theo loại!');
  }
});

// Pagination update
function updatePagination() {
  const start = state.totalRows === 0 ? 0 : (state.page - 1) * state.pageSize + 1;
  const end = Math.min(state.totalRows, state.page * state.pageSize);
  document.getElementById('showingText').innerText = `${formatNum(start)} - ${formatNum(end)}`;
  document.getElementById('totalRowsText').innerText = formatNum(state.totalRows);
  document.getElementById('pageInfo').innerText = `Trang ${state.page} / ${state.totalPages}`;

  document.getElementById('prevPage').disabled = state.page <= 1;
  document.getElementById('nextPage').disabled = state.page >= state.totalPages;
}

document.getElementById('prevPage').addEventListener('click', () => {
  if (state.page > 1) {
    state.page--;
    loadRows();
  }
});

document.getElementById('nextPage').addEventListener('click', () => {
  if (state.page < state.totalPages) {
    state.page++;
    loadRows();
  }
});

document.getElementById('pageSizeSelect').addEventListener('change', (e) => {
  state.pageSize = parseInt(e.target.value);
  state.page = 1;
  loadRows();
});

// Search input with debounce
let searchTimer = null;
document.getElementById('searchInput').addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.search = e.target.value.trim();
    state.page = 1;
    loadRows();
  }, 350);
});

// Status filter change
document.getElementById('statusFilter').addEventListener('change', (e) => {
  state.status = parseInt(e.target.value);
  state.page = 1;
  loadRows();
});

// Translate Page (Quick)
document.getElementById('btnTranslatePage').addEventListener('click', async () => {
  const ids = state.currentRows.filter(r => r.status === 0).map(r => r.id);
  if (ids.length === 0) {
    showToast('Tất cả các dòng trên trang này đều đã có bản dịch!');
    return;
  }

  const btn = document.getElementById('btnTranslatePage');
  btn.disabled = true;
  btn.innerText = `⏳ Đang dịch (${ids.length} dòng)...`;
  showToast(`Đang gửi batch ${ids.length} dòng lên OpenRouter...`, 4000);

  try {
    const res = await fetch('/api/translate/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ row_ids: ids })
    });
    const result = await res.json();
    showToast(`Đã dịch thành công ${result.translated_count} dòng!`);
    loadRows();
    loadStats();
    loadFiles();
  } catch (e) {
    showToast('Lỗi khi dịch trang!');
  } finally {
    btn.disabled = false;
    btn.innerText = '⚡ Dịch trang này';
  }
});

// ==========================================
// BATCH TRANSLATION MODAL & STREAMING
// ==========================================
const batchModal = document.getElementById('batchModal');
const batchSetupView = document.getElementById('batchSetupView');
const batchProgressView = document.getElementById('batchProgressView');

window.openBatchModal = async function(targetFile) {
  batchState.targetFile = targetFile;
  document.getElementById('batchModalTitle').innerText = targetFile ? `🚀 Dịch Full File: ${targetFile.split(/[\\/]/).pop()}` : `🌐 Dịch Full Toàn Bộ Game`;
  document.getElementById('batchScopeDesc').innerText = targetFile ? `File: ${targetFile}` : `Toàn bộ tất cả 516 file trong game`;
  
  const container = document.getElementById('batchTypesContainer');
  container.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; grid-column: span 2;">Đang tải danh sách loại...</div>';

  batchSetupView.style.display = 'block';
  batchProgressView.style.display = 'none';
  batchModal.classList.add('active');

  try {
    const fileParam = targetFile ? encodeURIComponent(targetFile) : 'ALL';
    const res = await fetch(`/api/types/stats?file=${fileParam}`);
    const stats = await res.json();
    container.innerHTML = '';

    for (const t of stats) {
      const isSafe = SAFE_TYPES.includes(t.row_type);
      const isRisky = RISKY_TYPES.includes(t.row_type);
      const label = document.createElement('label');
      label.style.cssText = 'display: flex; align-items: center; gap: 6px; font-size: 12px; cursor: pointer; padding: 4px; border-radius: 4px; background: rgba(255,255,255,0.02);';
      label.innerHTML = `
        <input type="checkbox" class="batch-type-checkbox" value="${t.row_type}" ${isSafe ? 'checked' : ''} style="width: 14px; height: 14px;">
        <span style="${isRisky ? 'color: var(--text-muted);' : 'font-weight: 500;'}">${formatTypeLabel(t.row_type)}</span>
        <span style="font-size: 10px; color: ${t.empty > 0 ? '#fab387' : 'var(--text-muted)'}; margin-left: auto;">(${formatNum(t.empty)} chờ dịch)</span>
      `;
      container.appendChild(label);
    }
  } catch (err) {
    container.innerHTML = '<div style="color: var(--danger); font-size: 12px; grid-column: span 2;">Lỗi tải loại!</div>';
  }
};

document.getElementById('btnBatchSelectSafeTypes').addEventListener('click', () => {
  document.querySelectorAll('.batch-type-checkbox').forEach(cb => {
    cb.checked = SAFE_TYPES.includes(cb.value);
  });
});
document.getElementById('btnBatchSelectAllTypes').addEventListener('click', () => {
  document.querySelectorAll('.batch-type-checkbox').forEach(cb => cb.checked = true);
});

document.getElementById('btnOpenBatchFile').addEventListener('click', () => {
  if (!state.file) {
    showToast('Vui lòng chọn một file cụ thể ở danh sách bên trái trước!');
    return;
  }
  openBatchModal(state.file);
});

document.getElementById('btnOpenBatchAll').addEventListener('click', () => {
  openBatchModal(null); // null means ALL
});

document.getElementById('closeBatchModal').addEventListener('click', () => {
  if (batchState.abortController) {
    if (!confirm('Tiến trình dịch đang chạy. Bạn có chắc muốn đóng và hủy bỏ không?')) return;
    batchState.abortController.abort();
  }
  batchModal.classList.remove('active');
});

document.getElementById('cancelBatchBtn').addEventListener('click', () => {
  batchModal.classList.remove('active');
});

// Start Streaming Batch
document.getElementById('startBatchBtn').addEventListener('click', async () => {
  const checkedTypes = Array.from(document.querySelectorAll('.batch-type-checkbox:checked')).map(cb => cb.value);
  if (checkedTypes.length === 0) {
    alert('Vui lòng chọn ít nhất một loại nội dung để dịch!');
    return;
  }

  batchSetupView.style.display = 'none';
  batchProgressView.style.display = 'block';

  const overwrite = document.getElementById('checkOverwrite').checked;
  const autoFill = document.getElementById('checkAutoFill').checked;
  const fileParam = batchState.targetFile ? encodeURIComponent(batchState.targetFile) : 'ALL';
  const typesParam = encodeURIComponent(checkedTypes.join(','));

  const url = `/api/translate/stream?file=${fileParam}&overwrite=${overwrite}&auto_fill=${autoFill}&types=${typesParam}`;

  batchState.abortController = new AbortController();
  const progressBar = document.getElementById('batchProgressBar');
  const progressText = document.getElementById('batchProgressText');
  const percentText = document.getElementById('batchPercentText');
  const currentFileEl = document.getElementById('batchCurrentFile');

  progressBar.style.width = '0%';
  progressText.innerText = 'Đang khởi động kết nối AI...';
  percentText.innerText = '0%';
  currentFileEl.innerText = 'Đang kết nối...';

  const liveFeed = document.getElementById('batchLiveFeed');
  liveFeed.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 20px;">Đang kết nối tới server AI...</div>';

  try {
    const response = await fetch(url, { signal: batchState.abortController.signal });
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let hasClearedFeed = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const jsonStr = line.slice(6).trim();
        if (!jsonStr) continue;

        try {
          const event = JSON.parse(jsonStr);
          if (event.type === 'start') {
            progressText.innerText = `Đã tìm thấy ${formatNum(event.total)} dòng cần dịch`;
            currentFileEl.innerText = `Bắt đầu: ${event.file}...`;
          } else if (event.type === 'progress') {
            progressBar.style.width = `${event.percent}%`;
            percentText.innerText = `${event.percent}%`;
            progressText.innerText = `Đã dịch: ${formatNum(event.done)} / ${formatNum(event.total)} dòng`;
            currentFileEl.innerText = `Đang xử lý: ${event.current_file}`;

            if (event.items && event.items.length > 0) {
              if (!hasClearedFeed) {
                liveFeed.innerHTML = '';
                hasClearedFeed = true;
              }
              for (const it of event.items) {
                const rowCard = document.createElement('div');
                rowCard.style.cssText = 'margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 12px; line-height: 1.4;';
                rowCard.innerHTML = `
                  <div style="color: var(--text-muted); font-size: 10px; margin-bottom: 2px;">#${it.id}</div>
                  <div style="color: #fab387; margin-bottom: 2px;">🇯🇵 ${escapeHtml(it.raw)}</div>
                  <div style="color: #a6e3a1; font-weight: 500;">🇻🇳 ${escapeHtml(it.translated)}</div>
                `;
                liveFeed.appendChild(rowCard);
              }
              liveFeed.scrollTop = liveFeed.scrollHeight;
            }
          } else if (event.type === 'fallback') {
            const fbCard = document.createElement('div');
            fbCard.style.cssText = 'background: rgba(249, 226, 175, 0.18); border: 1px solid var(--warning); color: var(--warning); padding: 8px 12px; border-radius: 6px; margin: 8px 0; font-size: 12px; font-weight: 600; line-height: 1.4;';
            fbCard.innerHTML = `🔄 <strong>XOAY TUA MODEL:</strong> ${escapeHtml(event.message)}`;
            liveFeed.appendChild(fbCard);
            liveFeed.scrollTop = liveFeed.scrollHeight;
          } else if (event.type === 'key_rotate') {
            const krCard = document.createElement('div');
            krCard.style.cssText = 'background: rgba(137, 180, 250, 0.2); border: 1px solid var(--accent); color: var(--accent); padding: 8px 12px; border-radius: 6px; margin: 8px 0; font-size: 12px; font-weight: 700; line-height: 1.4;';
            krCard.innerHTML = `🔑 <strong>XOAY KEY THÀNH CÔNG:</strong> ${escapeHtml(event.message)}`;
            liveFeed.appendChild(krCard);
            liveFeed.scrollTop = liveFeed.scrollHeight;
            loadSettings();
          } else if (event.type === 'error') {
            progressBar.style.background = 'var(--danger)';
            percentText.innerText = 'LỖI!';
            progressText.innerHTML = `<span style="color: #f38ba8; font-weight: bold;">❌ LỖI [${event.code || 'API'}]: ${escapeHtml(event.message)}</span>`;
            currentFileEl.innerText = 'Đã dừng do gặp lỗi!';

            const errCard = document.createElement('div');
            errCard.style.cssText = 'background: rgba(243, 139, 168, 0.18); border: 1px solid #f38ba8; color: #f38ba8; padding: 12px; border-radius: 6px; margin: 10px 0; font-size: 13px; line-height: 1.5; white-space: pre-wrap;';
            errCard.innerHTML = `<strong>🚨 GẶP LỖI KẾT NỐI AI:</strong>\n${escapeHtml(event.message)}`;
            liveFeed.appendChild(errCard);
            liveFeed.scrollTop = liveFeed.scrollHeight;

            showToast(`Lỗi: ${event.message}`, 6000);
            break;
          } else if (event.type === 'complete') {
            progressBar.style.width = '100%';
            percentText.innerText = '100%';
            progressText.innerText = `🎉 ${event.message}`;
            currentFileEl.innerText = 'Hoàn tất toàn bộ!';
            showToast(`🎉 ${event.message}`);
            setTimeout(() => {
              batchModal.classList.remove('active');
              loadStats();
              loadFiles();
              loadRows();
            }, 1800);
          }
        } catch (e) {
          console.error('Error parsing SSE event:', e);
        }
      }
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      showToast('Đã dừng tiến trình dịch!');
    } else {
      showToast('Lỗi kết nối khi dịch batch!');
    }
    loadStats();
    loadFiles();
    loadRows();
  } finally {
    batchState.abortController = null;
  }
});

// Stop Batch
document.getElementById('stopBatchBtn').addEventListener('click', () => {
  if (batchState.abortController) {
    batchState.abortController.abort();
    batchState.abortController = null;
  }
  batchModal.classList.remove('active');
});

// Patch to Game
document.getElementById('btnPatchGame').addEventListener('click', async () => {
  const btn = document.getElementById('btnPatchGame');
  btn.disabled = true;
  btn.innerText = '⏳ Đang vá vào Game...';
  showToast('Đang áp dụng bản dịch tiếng Việt vào game...');

  try {
    const res = await fetch('/api/patch', { method: 'POST' });
    const result = await res.json();
    if (result.success) {
      alert(`🎉 ${result.message}\nBây giờ bạn có thể mở game lên và trải nghiệm ngay!`);
    } else {
      alert(`⚠️ ${result.message}`);
    }
  } catch (e) {
    alert('Lỗi khi gọi lệnh vá game!');
  } finally {
    btn.disabled = false;
    btn.innerText = '💾 Patch vào Game';
  }
});

// Settings Modal & Multi-Provider Handling
const settingsModal = document.getElementById('settingsModal');
let currentActiveProvider = 'gemini';
let geminiKeys = [];
let geminiActiveKeyIndex = 0;

function renderGeminiKeys() {
  const container = document.getElementById('geminiKeysContainer');
  const countText = document.getElementById('geminiKeyCountText');
  if (!container) return;

  container.innerHTML = '';
  if (countText) countText.innerText = `${geminiKeys.length} Key`;

  if (geminiKeys.length === 0) {
    container.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 12px; font-size: 12px;">Chưa có API Key nào. Hãy dán key vào ô trên và bấm Thêm Key.</div>';
    return;
  }

  geminiKeys.forEach((key, idx) => {
    const isActive = idx === geminiActiveKeyIndex;
    const masked = key.length > 10 ? `${key.slice(0, 8)}...${key.slice(-6)}` : '******';
    
    const row = document.createElement('div');
    row.style.cssText = `display: flex; align-items: center; justify-content: space-between; background: var(--bg-card); padding: 6px 10px; border-radius: 5px; border: 1px solid ${isActive ? 'var(--accent)' : 'var(--border)'}; font-size: 12px;`;
    
    row.innerHTML = `
      <div style="display: flex; align-items: center; gap: 8px; overflow: hidden; flex: 1;">
        <span class="priority-badge ${idx === 0 ? 'badge-nv1' : (idx === 1 ? 'badge-nv2' : 'badge-nv3')}">Key #${idx + 1}</span>
        <span style="font-family: monospace; color: var(--text-primary); font-size: 12px;" title="${key}">${masked}</span>
        ${isActive ? '<span style="font-size: 10px; padding: 1px 5px; border-radius: 3px; background: rgba(166,227,161,0.2); color: #a6e3a1; border: 1px solid #a6e3a1; font-weight: 600;">Đang dùng</span>' : ''}
        <span id="keyTestResult-${idx}" style="font-size: 11px; margin-left: 6px;"></span>
      </div>
      <div style="display: flex; gap: 4px; align-items: center;">
        <button type="button" class="btn" style="padding: 2px 7px; font-size: 11px;" title="Kiểm tra trạng thái & quota key này" onclick="testSingleKey(${idx})">🔌 Test</button>
        ${!isActive ? `<button type="button" class="btn" style="padding: 2px 7px; font-size: 11px;" title="Đặt key này làm Key chạy đầu tiên" onclick="setActiveGeminiKey(${idx})">⚡ Dùng</button>` : ''}
        <button type="button" class="btn" style="padding: 2px 6px; font-size: 10px; ${idx === 0 ? 'opacity: 0.3;' : ''}" title="Đổi thứ tự lên trên" ${idx === 0 ? 'disabled' : ''} onclick="moveGeminiKey(${idx}, -1)">▲</button>
        <button type="button" class="btn" style="padding: 2px 6px; font-size: 10px; ${idx === geminiKeys.length - 1 ? 'opacity: 0.3;' : ''}" title="Đổi thứ tự xuống dưới" ${idx === geminiKeys.length - 1 ? 'disabled' : ''} onclick="moveGeminiKey(${idx}, 1)">▼</button>
        <button type="button" class="btn btn-danger" style="padding: 2px 6px; font-size: 10px; background: rgba(243,139,168,0.2); color: #f38ba8; border: 1px solid #f38ba8;" title="Xóa key này" onclick="deleteGeminiKey(${idx})">✕</button>
      </div>
    `;
    container.appendChild(row);
  });
}

window.testSingleKey = async function(idx) {
  const statusEl = document.getElementById(`keyTestResult-${idx}`);
  if (!statusEl) return;
  const key = geminiKeys[idx];
  if (!key) return;

  statusEl.innerHTML = '<span style="color: var(--accent);">⏳ Test...</span>';
  const baseUrl = document.getElementById('geminiBaseUrl').value.trim();
  const model = getGeminiModel('geminiModel1Select', 'geminiModel1Input');

  try {
    const res = await fetch('/api/settings/test-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: key, base_url: baseUrl, model: model })
    });
    const data = await res.json();
    if (data.ok) {
      statusEl.innerHTML = `<span style="color: #a6e3a1; font-weight: 600;">${escapeHtml(data.message)}</span>`;
    } else {
      statusEl.innerHTML = `<span style="color: #f38ba8; font-weight: 600;">${escapeHtml(data.message)}</span>`;
    }
  } catch (err) {
    statusEl.innerHTML = `<span style="color: #f38ba8;">❌ Lỗi</span>`;
  }
};

window.setActiveGeminiKey = function(idx) {
  geminiActiveKeyIndex = idx;
  renderGeminiKeys();
};

window.moveGeminiKey = function(idx, dir) {
  const newIdx = idx + dir;
  if (newIdx < 0 || newIdx >= geminiKeys.length) return;
  const temp = geminiKeys[idx];
  geminiKeys[idx] = geminiKeys[newIdx];
  geminiKeys[newIdx] = temp;
  if (geminiActiveKeyIndex === idx) geminiActiveKeyIndex = newIdx;
  else if (geminiActiveKeyIndex === newIdx) geminiActiveKeyIndex = idx;
  renderGeminiKeys();
};

window.deleteGeminiKey = function(idx) {
  if (!confirm(`Bạn có chắc muốn xóa Key #${idx + 1}?`)) return;
  geminiKeys.splice(idx, 1);
  if (geminiActiveKeyIndex >= geminiKeys.length) {
    geminiActiveKeyIndex = Math.max(0, geminiKeys.length - 1);
  }
  renderGeminiKeys();
};

document.getElementById('btnAddGeminiKey').addEventListener('click', () => {
  const input = document.getElementById('inputNewGeminiKey');
  const val = input.value.trim();
  if (!val) {
    alert('Vui lòng dán API Key vào ô nhập!');
    return;
  }
  if (geminiKeys.includes(val)) {
    alert('Key này đã có trong danh sách!');
    return;
  }
  geminiKeys.push(val);
  input.value = '';
  renderGeminiKeys();
  showToast(`Đã thêm Key #${geminiKeys.length}!`);
});

// Helper: Setup dropdown custom input visibility
function setupGeminiDropdown(selectId, inputId) {
  const sel = document.getElementById(selectId);
  const inp = document.getElementById(inputId);
  if (!sel || !inp) return;
  sel.addEventListener('change', () => {
    if (sel.value === 'custom') {
      inp.style.display = 'block';
      inp.focus();
    } else {
      inp.style.display = 'none';
    }
  });
}

setupGeminiDropdown('geminiModel1Select', 'geminiModel1Input');
setupGeminiDropdown('geminiModel2Select', 'geminiModel2Input');
setupGeminiDropdown('geminiModel3Select', 'geminiModel3Input');
setupGeminiDropdown('geminiModel4Select', 'geminiModel4Input');
setupGeminiDropdown('geminiModel5Select', 'geminiModel5Input');

function setGeminiModel(selectId, inputId, val) {
  const sel = document.getElementById(selectId);
  const inp = document.getElementById(inputId);
  if (!sel || !inp) return;
  const standard = [
    'gemini-3.5-flash-lite',
    'gemini-3-flash-preview',
    'gemini-2.5-flash',
    'gemini-3.1-flash-lite',
    'gemini-2.5-flash-lite',
    'gemini-3.6-flash',
    'gemini-3.8-flash'
  ];
  if (standard.includes(val)) {
    sel.value = val;
    inp.style.display = 'none';
    inp.value = '';
  } else {
    sel.value = 'custom';
    inp.style.display = 'block';
    inp.value = val || '';
  }
}

function getGeminiModel(selectId, inputId) {
  const sel = document.getElementById(selectId);
  const inp = document.getElementById(inputId);
  if (!sel) return 'gemini-3.5-flash-lite';
  if (sel.value === 'custom') {
    return (inp ? inp.value.trim() : '') || 'gemini-3.5-flash-lite';
  }
  return sel.value;
}

// Switch Provider Tab
function switchProviderTab(providerName) {
  currentActiveProvider = providerName;
  document.querySelectorAll('.provider-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.provider === providerName);
  });

  document.getElementById('panelGemini').classList.toggle('active', providerName === 'gemini');
  document.getElementById('panelKaggle').classList.toggle('active', providerName === 'kaggle');
  document.getElementById('panelOpenRouter').classList.toggle('active', providerName === 'openrouter');
}

document.querySelectorAll('.provider-tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    switchProviderTab(btn.dataset.provider);
  });
});

document.getElementById('btnOpenSettings').addEventListener('click', async () => {
  const box = document.getElementById('testConnectionBox');
  if (box) box.style.display = 'none';

  try {
    const res = await fetch('/api/settings');
    const s = await res.json();

    // Gemini
    if (s.gemini) {
      document.getElementById('geminiBaseUrl').value = s.gemini.base_url || 'https://generativelanguage.googleapis.com/v1beta/openai';
      
      geminiKeys = Array.isArray(s.gemini.keys) ? s.gemini.keys : (s.gemini.api_key ? [s.gemini.api_key] : []);
      geminiActiveKeyIndex = s.gemini.active_key_index || 0;
      if (geminiActiveKeyIndex >= geminiKeys.length) geminiActiveKeyIndex = Math.max(0, geminiKeys.length - 1);
      renderGeminiKeys();

      setGeminiModel('geminiModel1Select', 'geminiModel1Input', s.gemini.model_1 || 'gemini-3.5-flash-lite');
      setGeminiModel('geminiModel2Select', 'geminiModel2Input', s.gemini.model_2 || 'gemini-3-flash-preview');
      setGeminiModel('geminiModel3Select', 'geminiModel3Input', s.gemini.model_3 || 'gemini-2.5-flash');
      setGeminiModel('geminiModel4Select', 'geminiModel4Input', s.gemini.model_4 || 'gemini-3.1-flash-lite');
      setGeminiModel('geminiModel5Select', 'geminiModel5Input', s.gemini.model_5 || 'gemini-2.5-flash-lite');
    }

    // Kaggle
    if (s.kaggle) {
      document.getElementById('kaggleBaseUrl').value = s.kaggle.base_url || '';
      document.getElementById('kaggleApiKey').value = s.kaggle.api_key || 'local';
      document.getElementById('kaggleModel').value = s.kaggle.model || 'qwen2.5:32b';
    }

    // OpenRouter
    if (s.openrouter) {
      document.getElementById('openrouterBaseUrl').value = s.openrouter.base_url || 'https://openrouter.ai/api/v1';
      document.getElementById('openrouterApiKey').value = s.openrouter.api_key || '';
      document.getElementById('openrouterModel').value = s.openrouter.model || 'deepseek/deepseek-v4.1-flash-1017';
    }

    // Common
    document.getElementById('inputBatchSize').value = s.batch_size || '15';
    document.getElementById('inputSystemPrompt').value = s.system_prompt || '';

    // Switch to active tab
    switchProviderTab(s.active_provider || 'gemini');

    settingsModal.classList.add('active');
  } catch (err) {
    showToast('Không thể tải cấu hình cài đặt!');
  }
});

document.getElementById('closeSettingsModal').addEventListener('click', () => {
  settingsModal.classList.remove('active');
});
document.getElementById('cancelSettings').addEventListener('click', () => {
  settingsModal.classList.remove('active');
});

// Test Connection for current active provider
document.getElementById('btnTestConnection').addEventListener('click', async () => {
  const btn = document.getElementById('btnTestConnection');
  const box = document.getElementById('testConnectionBox');

  let base_url = '';
  let api_key = '';
  let model = '';

  if (currentActiveProvider === 'gemini') {
    base_url = document.getElementById('geminiBaseUrl').value.trim();
    api_key = (geminiKeys.length > 0 && geminiKeys[geminiActiveKeyIndex]) ? geminiKeys[geminiActiveKeyIndex] : '';
    model = getGeminiModel('geminiModel1Select', 'geminiModel1Input');
  } else if (currentActiveProvider === 'kaggle') {
    base_url = document.getElementById('kaggleBaseUrl').value.trim();
    api_key = document.getElementById('kaggleApiKey').value.trim();
    model = document.getElementById('kaggleModel').value.trim();
  } else {
    base_url = document.getElementById('openrouterBaseUrl').value.trim();
    api_key = document.getElementById('openrouterApiKey').value.trim();
    model = document.getElementById('openrouterModel').value.trim();
  }

  btn.disabled = true;
  btn.innerText = '⏳ Đang kiểm tra...';
  box.style.display = 'block';
  box.style.background = 'rgba(137, 180, 250, 0.1)';
  box.style.border = '1px solid var(--accent)';
  box.style.color = 'var(--text)';
  box.innerText = `📡 Đang kiểm tra kết nối tới [${currentActiveProvider.toUpperCase()}] với model '${model}'...`;

  try {
    const res = await fetch('/api/settings/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: currentActiveProvider,
        base_url,
        api_key,
        model
      })
    });
    const data = await res.json();
    if (data.ok) {
      box.style.background = 'rgba(166, 227, 161, 0.15)';
      box.style.border = '1px solid #a6e3a1';
      box.style.color = '#a6e3a1';
    } else {
      box.style.background = 'rgba(243, 139, 168, 0.15)';
      box.style.border = '1px solid #f38ba8';
      box.style.color = '#f38ba8';
    }
    box.innerText = data.message;
  } catch (err) {
    box.style.background = 'rgba(243, 139, 168, 0.15)';
    box.style.border = '1px solid #f38ba8';
    box.style.color = '#f38ba8';
    box.innerText = `❌ Lỗi kết nối tới backend app: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.innerText = '🔌 Kiểm tra Provider hiện tại';
  }
});

// Save Settings
document.getElementById('saveSettings').addEventListener('click', async () => {
  const activeGeminiKey = (geminiKeys.length > 0 && geminiKeys[geminiActiveKeyIndex]) ? geminiKeys[geminiActiveKeyIndex] : '';

  const payload = {
    active_provider: currentActiveProvider,
    batch_size: document.getElementById('inputBatchSize').value.trim(),
    system_prompt: document.getElementById('inputSystemPrompt').value.trim(),
    gemini: {
      base_url: document.getElementById('geminiBaseUrl').value.trim(),
      api_key: activeGeminiKey,
      keys: geminiKeys,
      active_key_index: geminiActiveKeyIndex,
      model_1: getGeminiModel('geminiModel1Select', 'geminiModel1Input'),
      model_2: getGeminiModel('geminiModel2Select', 'geminiModel2Input'),
      model_3: getGeminiModel('geminiModel3Select', 'geminiModel3Input'),
      model_4: getGeminiModel('geminiModel4Select', 'geminiModel4Input'),
      model_5: getGeminiModel('geminiModel5Select', 'geminiModel5Input'),
    },
    kaggle: {
      base_url: document.getElementById('kaggleBaseUrl').value.trim(),
      api_key: document.getElementById('kaggleApiKey').value.trim(),
      model: document.getElementById('kaggleModel').value.trim(),
    },
    openrouter: {
      base_url: document.getElementById('openrouterBaseUrl').value.trim(),
      api_key: document.getElementById('openrouterApiKey').value.trim(),
      model: document.getElementById('openrouterModel').value.trim(),
    }
  };

  try {
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    settingsModal.classList.remove('active');
    showToast('Đã lưu cấu hình danh sách Key & xoay tua model!');
    loadSettings();
  } catch (err) {
    showToast('Lỗi khi lưu cài đặt!');
  }
});

// Load Settings on start
async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    const s = await res.json();
    if (s.active_model_display) {
      document.getElementById('currentModel').innerText = s.active_model_display;
    }
  } catch (e) {}
}

// Init
window.addEventListener('DOMContentLoaded', () => {
  loadProjects();
  loadSettings();
  loadStats();
  loadFiles();
  loadRows();
});

// ==========================================
// PROJECT MANAGEMENT & .NEL SYSTEM
// ==========================================
let currentProjects = [];

async function loadProjects() {
  try {
    const res = await fetch('/api/projects');
    const data = await res.json();
    currentProjects = data.projects || [];
    const select = document.getElementById('projectSelect');
    if (!select) return;
    select.innerHTML = '';

    if (currentProjects.length === 0) {
      select.innerHTML = '<option value="">(Chưa có dự án nào)</option>';
      return;
    }

    currentProjects.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id;
      const pct = p.stats ? `${p.stats.percent}%` : '0%';
      const count = p.stats ? `${formatNum(p.stats.completed)}/${formatNum(p.stats.total)}` : '';
      opt.innerText = `${p.name} (${pct} - ${count})`;
      if (p.is_active) opt.selected = true;
      select.appendChild(opt);
    });

    const active = data.active_project;
    if (active) {
      document.title = `Nelir Wolf - ${active.name}`;
    }
  } catch (err) {
    console.error('Error loading projects:', err);
  }
}

// Project select change
const projectSelectEl = document.getElementById('projectSelect');
if (projectSelectEl) {
  projectSelectEl.addEventListener('change', async (e) => {
    const newId = e.target.value;
    if (!newId) return;

    try {
      const res = await fetch('/api/projects/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: newId })
      });
      const result = await res.json();
      if (result.success) {
        showToast(`Đã chuyển sang dự án: ${result.active_project.name}`);
        state.file = null;
        state.category = null;
        state.page = 1;
        await loadProjects();
        await loadStats();
        await loadFiles();
        await loadRows();
      }
    } catch (err) {
      showToast('Lỗi khi chuyển đổi dự án!');
    }
  });
}

// Export .NEL
const btnExportNelEl = document.getElementById('btnExportNel');
if (btnExportNelEl) {
  btnExportNelEl.addEventListener('click', () => {
    const select = document.getElementById('projectSelect');
    const projId = select ? select.value : '';
    showToast('Đang đóng gói file .nel để tải về...');
    const a = document.createElement('a');
    a.href = `/api/projects/export-nel${projId ? `?project_id=${encodeURIComponent(projId)}` : ''}`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  });
}

// New Project Modal
const newProjectModal = document.getElementById('newProjectModal');
const inputNewProjectName = document.getElementById('inputNewProjectName');
const inputNewProjectGamePath = document.getElementById('inputNewProjectGamePath');
const newProjectStatusBox = document.getElementById('newProjectStatusBox');
const confirmNewProjectBtn = document.getElementById('confirmNewProjectBtn');

const btnOpenNewProjectEl = document.getElementById('btnOpenNewProject');
if (btnOpenNewProjectEl) {
  btnOpenNewProjectEl.addEventListener('click', () => {
    inputNewProjectName.value = '';
    inputNewProjectGamePath.value = '';
    newProjectStatusBox.style.display = 'none';
    confirmNewProjectBtn.disabled = false;
    confirmNewProjectBtn.innerText = '🚀 Khởi Tạo & Trích Xuất Dữ Liệu';
    newProjectModal.classList.add('active');
  });
}

const closeNewProjectModalEl = document.getElementById('closeNewProjectModal');
if (closeNewProjectModalEl) {
  closeNewProjectModalEl.addEventListener('click', () => {
    newProjectModal.classList.remove('active');
  });
}
const cancelNewProjectBtnEl = document.getElementById('cancelNewProjectBtn');
if (cancelNewProjectBtnEl) {
  cancelNewProjectBtnEl.addEventListener('click', () => {
    newProjectModal.classList.remove('active');
  });
}

if (confirmNewProjectBtn) {
  confirmNewProjectBtn.addEventListener('click', async () => {
    const name = inputNewProjectName.value.trim();
    const gamePath = inputNewProjectGamePath.value.trim();

    if (!name) {
      alert('Vui lòng nhập tên cho Game/Dự án!');
      return;
    }
    if (!gamePath) {
      alert('Vui lòng nhập đường dẫn thư mục cài đặt game!');
      return;
    }

    confirmNewProjectBtn.disabled = true;
    confirmNewProjectBtn.innerText = '⏳ Đang khởi tạo & trích xuất game (WolfTL)...';
    newProjectStatusBox.style.display = 'block';
    newProjectStatusBox.style.background = 'rgba(137, 180, 250, 0.1)';
    newProjectStatusBox.style.border = '1px solid var(--accent)';
    newProjectStatusBox.style.color = 'var(--text-primary)';
    newProjectStatusBox.innerText = 'Đang chạy WolfTL để giải nén kịch bản game. Vui lòng đợi trong giây lát...';

    try {
      const res = await fetch('/api/projects/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, game_path: gamePath })
      });
      const result = await res.json();
      if (!res.ok) {
        throw new Error(result.detail || 'Lỗi khi tạo dự án');
      }

      showToast(`Đã tạo và kích hoạt thành công dự án: ${result.project.name}!`);
      newProjectModal.classList.remove('active');
      state.file = null;
      state.category = null;
      state.page = 1;
      await loadProjects();
      await loadStats();
      await loadFiles();
      await loadRows();
    } catch (err) {
      newProjectStatusBox.style.background = 'rgba(243, 139, 168, 0.15)';
      newProjectStatusBox.style.border = '1px solid var(--danger)';
      newProjectStatusBox.style.color = 'var(--danger)';
      newProjectStatusBox.innerText = `❌ ${err.message}`;
      confirmNewProjectBtn.disabled = false;
      confirmNewProjectBtn.innerText = '🚀 Thử Lại';
    }
  });
}

// Import .NEL Modal
const importNelModal = document.getElementById('importNelModal');
const inputNelFile = document.getElementById('inputNelFile');
const inputImportGamePath = document.getElementById('inputImportGamePath');
const importNelStatusBox = document.getElementById('importNelStatusBox');
const confirmImportNelBtn = document.getElementById('confirmImportNelBtn');

const btnOpenImportNelEl = document.getElementById('btnOpenImportNel');
if (btnOpenImportNelEl) {
  btnOpenImportNelEl.addEventListener('click', () => {
    inputNelFile.value = '';
    inputImportGamePath.value = '';
    importNelStatusBox.style.display = 'none';
    confirmImportNelBtn.disabled = false;
    confirmImportNelBtn.innerText = '📥 Nạp Dự Án Ngay';
    importNelModal.classList.add('active');
  });
}

const closeImportNelModalEl = document.getElementById('closeImportNelModal');
if (closeImportNelModalEl) {
  closeImportNelModalEl.addEventListener('click', () => {
    importNelModal.classList.remove('active');
  });
}
const cancelImportNelBtnEl = document.getElementById('cancelImportNelBtn');
if (cancelImportNelBtnEl) {
  cancelImportNelBtnEl.addEventListener('click', () => {
    importNelModal.classList.remove('active');
  });
}

if (confirmImportNelBtn) {
  confirmImportNelBtn.addEventListener('click', async () => {
    if (!inputNelFile.files || inputNelFile.files.length === 0) {
      alert('Vui lòng chọn một file gói dự án .nel để nạp!');
      return;
    }

    const file = inputNelFile.files[0];
    const overridePath = inputImportGamePath.value.trim();

    const formData = new FormData();
    formData.append('file', file);
    if (overridePath) {
      formData.append('override_game_path', overridePath);
    }

    confirmImportNelBtn.disabled = true;
    confirmImportNelBtn.innerText = '⏳ Đang giải nén và nạp dự án...';
    importNelStatusBox.style.display = 'block';
    importNelStatusBox.style.background = 'rgba(137, 180, 250, 0.1)';
    importNelStatusBox.style.border = '1px solid var(--accent)';
    importNelStatusBox.style.color = 'var(--text-primary)';
    importNelStatusBox.innerText = 'Đang phân tích gói .nel và nạp vào hệ thống...';

    try {
      const res = await fetch('/api/projects/import-nel', {
        method: 'POST',
        body: formData
      });
      const result = await res.json();
      if (!res.ok) {
        throw new Error(result.detail || 'Lỗi khi nạp gói .nel');
      }

      showToast(`Đã nạp thành công dự án: ${result.project.name}!`);
      importNelModal.classList.remove('active');
      state.file = null;
      state.category = null;
      state.page = 1;
      await loadProjects();
      await loadStats();
      await loadFiles();
      await loadRows();
    } catch (err) {
      importNelStatusBox.style.background = 'rgba(243, 139, 168, 0.15)';
      importNelStatusBox.style.border = '1px solid var(--danger)';
      importNelStatusBox.style.color = 'var(--danger)';
      importNelStatusBox.innerText = `❌ ${err.message}`;
      confirmImportNelBtn.disabled = false;
      confirmImportNelBtn.innerText = '📥 Thử Lại';
    }
  });
}
