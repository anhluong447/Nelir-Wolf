// Inspector (detail editor) — placeholder until the editor milestone.
import { $, icon } from './dom.js';
import { listen } from './state.js';

export function initInspector() {
  listen('select', (row) => {
    $('#inspector').innerHTML = row
      ? `<div class="insp-empty">${icon('file')}<div>#${row.id}</div></div>`
      : `<div class="insp-empty">${icon('list')}<div>Chọn một dòng để xem chi tiết</div></div>`;
  });
}
