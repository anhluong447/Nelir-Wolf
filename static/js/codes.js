// WOLF RPG control codes: highlight in text + client-side QA mirroring qa.py.
import { esc } from './dom.js';

// \cself[3] (letters + [arg]) | \E (single letter) | <C> | @1   — same rules as qa.py
const CODE_RE = /\\([a-zA-Z]+)\[([^\]]*)\]|\\([a-zA-Z])|<([A-Z])>|(@\d+)/g;
const STRIP_RE = /\\[a-zA-Z]+\[[^\]]*\]|\\[a-zA-Z]|<[A-Z]>|@\d+/g;
const KANA_RE = /[ぁ-ゖァ-ヺ]/;
const CJK_RE = /[一-鿿㐀-䶿]/;
const JP_ANY_RE = /[぀-ヿ一-鿿]/;
const isAscii = (s) => /^[\x00-\x7F]*$/.test(s);

export const BLOCKING = ['empty', 'untranslated', 'jp_residue', 'line_count', 'missing_code'];
export const FLAG_TEXT = {
  empty: 'Bản dịch rỗng',
  untranslated: 'Giống hệt câu gốc (chưa dịch)',
  jp_residue: 'Còn sót chữ Nhật/Hán',
  line_count: 'Số dòng khác câu gốc',
  missing_code: 'Thiếu mã điều khiển',
  too_long: 'Có dòng quá dài',
};

function codeKey(m) {
  const [, name, arg, single, align, at] = m;
  if (name) return '\\' + name + (isAscii(arg) ? `[${arg.replace(/ /g, '')}]` : '');
  if (single) return '\\' + single;
  if (align) return `<${align}>`;
  return at;
}

export function codeCounts(text) {
  const counts = new Map();
  for (const m of (text || '').matchAll(CODE_RE)) {
    const k = codeKey(m);
    counts.set(k, (counts.get(k) || 0) + 1);
  }
  return counts;
}

/** Codes present in raw but missing (or fewer) in text. */
export function missingCodes(raw, text) {
  const a = codeCounts(raw); const b = codeCounts(text);
  const out = [];
  for (const [k, n] of a) for (let i = (b.get(k) || 0); i < n; i++) out.push(k);
  return out;
}

export function qaFlags(raw, text, rowType = '', maxLine = 0) {
  if (!text || !text.trim()) return ['empty'];
  const flags = [];
  if (text === raw && JP_ANY_RE.test(raw)) flags.push('untranslated');
  else if (KANA_RE.test(text) || CJK_RE.test(text)) flags.push('jp_residue');
  if ((raw.match(/\n/g) || []).length !== (text.match(/\n/g) || []).length) flags.push('line_count');
  if (missingCodes(raw, text).length) flags.push('missing_code');
  if (maxLine && (rowType === 'Message' || rowType === 'Choice')) {
    if (text.split('\n').some((l) => l.replace(STRIP_RE, '').length > maxLine)) flags.push('too_long');
  }
  return flags;
}

export const isBlocking = (flags) => flags.some((f) => BLOCKING.includes(f));

/** Escape text, render control codes as chips, newlines as ↵ + <br>, optional search highlight. */
export function renderText(text, { search = '', newlines = true, missing = [] } = {}) {
  if (!text) return '';
  let out = '';
  let last = 0;
  const hi = (s) => {
    let e = esc(s);
    if (search) {
      const q = esc(search).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      e = e.replace(new RegExp(q, 'gi'), (x) => `<mark>${x}</mark>`);
    }
    return newlines ? e.replace(/\n/g, '<span class="nl">↵</span><br>') : e.replace(/\n/g, '<span class="nl"> ↵ </span>');
  };
  for (const m of text.matchAll(CODE_RE)) {
    out += hi(text.slice(last, m.index));
    out += `<span class="cc" title="Mã điều khiển WOLF">${esc(m[0])}</span>`;
    last = m.index + m[0].length;
  }
  out += hi(text.slice(last));
  if (missing.length) out += ' ' + missing.map((k) => `<span class="cc missing" title="Thiếu so với câu gốc">${esc(k)}</span>`).join('');
  return out;
}
