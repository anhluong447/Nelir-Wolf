// Toasts, promise-based dialogs and dropdown menus.
import { $, $$, esc, html, icon } from './dom.js';

/* ---------------- Toasts ---------------- */
const TOAST_ICON = { success: 'checkCircle', error: 'alert', warn: 'alert', info: 'info' };

export function toast(message, type = 'info', ms = 3500) {
  let box = $('.toasts');
  if (!box) { box = html('<div class="toasts" role="status" aria-live="polite"></div>'); document.body.appendChild(box); }
  const el = html(`<div class="toast ${type}">${icon(TOAST_ICON[type] || 'info')}<div>${esc(message)}</div></div>`);
  box.appendChild(el);
  const close = () => { el.classList.add('leaving'); setTimeout(() => el.remove(), 200); };
  el.addEventListener('click', close);
  setTimeout(close, type === 'error' ? Math.max(ms, 7000) : ms);
}

/* ---------------- Dialogs ----------------
 * openDialog({ title, body (HTML string or Node), actions:[{label, value, kind, icon}], width })
 * returns { el, close(value), result: Promise }
 */
let dialogDepth = 0;

export function openDialog({ title, body = '', actions = [], width = '', dismissible = true, onOpen } = {}) {
  const backdrop = html(`
    <div class="dialog-backdrop" role="presentation">
      <div class="dialog ${width}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <div class="dialog-head"><h3>${esc(title)}</h3>
          ${dismissible ? `<button class="btn ghost icon-only" data-close title="Đóng (Esc)">${icon('x')}</button>` : ''}
        </div>
        <div class="dialog-body"></div>
        ${actions.length ? '<div class="dialog-foot"></div>' : ''}
      </div>
    </div>`);
  const bodyEl = $('.dialog-body', backdrop);
  if (typeof body === 'string') bodyEl.innerHTML = body; else bodyEl.appendChild(body);
  const foot = $('.dialog-foot', backdrop);
  actions.forEach((a) => {
    const b = html(`<button class="btn ${a.kind || ''} ${a.left ? 'left' : ''}">${a.icon ? icon(a.icon) : ''}<span>${esc(a.label)}</span></button>`);
    b.addEventListener('click', () => (a.onClick ? a.onClick(b) : close(a.value)));
    foot.appendChild(b);
  });

  let resolve;
  const result = new Promise((r) => { resolve = r; });
  const prevFocus = document.activeElement;
  function close(value) {
    if (!backdrop.isConnected) return;
    backdrop.remove();
    dialogDepth--;
    document.removeEventListener('keydown', onKey, true);
    if (prevFocus && prevFocus.focus) prevFocus.focus();
    resolve(value);
  }
  function onKey(e) {
    if (e.key === 'Escape' && dismissible) { e.stopPropagation(); e.preventDefault(); close(undefined); }
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      const primary = $('.dialog-foot .btn.primary, .dialog-foot .btn.danger.solid', backdrop);
      if (primary) { e.preventDefault(); primary.click(); }
    }
  }
  backdrop.addEventListener('mousedown', (e) => { if (e.target === backdrop && dismissible) close(undefined); });
  $$('[data-close]', backdrop).forEach((b) => b.addEventListener('click', () => close(undefined)));
  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(backdrop);
  dialogDepth++;
  setTimeout(() => {
    const first = $('[autofocus], .dialog-body input, .dialog-body textarea, .dialog-body select', backdrop)
      || $('.dialog-foot .btn.primary', backdrop) || $('.dialog-foot .btn', backdrop);
    if (first) first.focus();
    if (onOpen) onOpen(backdrop);
  }, 0);
  return { el: backdrop, close, result };
}

export const isDialogOpen = () => dialogDepth > 0;

export function alertDialog(title, message, { detail = '', kind = 'info' } = {}) {
  const ic = { info: 'info', warn: 'alert', danger: 'alert', success: 'checkCircle' }[kind] || 'info';
  return openDialog({
    title,
    body: `<div class="callout ${kind === 'success' ? '' : kind}">${icon(ic)}<div>${esc(message).replace(/\n/g, '<br>')}</div></div>
           ${detail ? `<pre class="detail">${esc(detail)}</pre>` : ''}`,
    actions: [{ label: 'Đóng', value: true, kind: 'primary' }],
  }).result;
}

export function confirmDialog(title, message, { okLabel = 'Đồng ý', danger = false, detail = '' } = {}) {
  return openDialog({
    title,
    body: `<p>${esc(message).replace(/\n/g, '<br>')}</p>${detail ? `<pre class="detail">${esc(detail)}</pre>` : ''}`,
    actions: [
      { label: 'Hủy', value: false },
      { label: okLabel, value: true, kind: danger ? 'danger solid' : 'primary' },
    ],
  }).result.then((v) => v === true);
}

export function promptDialog(title, label, { value = '', placeholder = '', okLabel = 'OK', hint = '' } = {}) {
  const d = openDialog({
    title,
    body: `<div class="field"><label>${esc(label)}</label>
             <input class="input" id="dlgPrompt" value="${esc(value)}" placeholder="${esc(placeholder)}" autofocus>
             ${hint ? `<div class="hint">${esc(hint)}</div>` : ''}</div>`,
    actions: [
      { label: 'Hủy', value: null },
      { label: okLabel, kind: 'primary', onClick: () => d.close($('#dlgPrompt', d.el).value.trim()) },
    ],
  });
  $('#dlgPrompt', d.el).addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); d.close(e.target.value.trim()); }
  });
  return d.result;
}

/* ---------------- Menus ---------------- */
export function closeMenus(except) {
  $$('.menu.open').forEach((m) => { if (m !== except) m.classList.remove('open'); });
}

export function bindMenu(button, menu) {
  button.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = !menu.classList.contains('open');
    closeMenus(menu);
    menu.classList.toggle('open', open);
  });
  menu.addEventListener('click', (e) => {
    if (e.target.closest('.menu-item')) menu.classList.remove('open');
  });
}
document.addEventListener('click', () => closeMenus());
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenus(); });

/** Run an async action while a button shows a spinner. */
export async function busy(button, fn) {
  const prev = button ? button.innerHTML : '';
  if (button) { button.disabled = true; button.innerHTML = '<span class="spinner"></span>' + (button.dataset.busy ? `<span>${esc(button.dataset.busy)}</span>` : ''); }
  try { return await fn(); } finally { if (button) { button.disabled = false; button.innerHTML = prev; } }
}
