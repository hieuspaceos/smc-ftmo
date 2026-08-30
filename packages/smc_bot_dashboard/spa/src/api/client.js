// Thin fetch wrapper for the FastAPI backend (/api/*).
// In dev: Vite proxies /api → http://127.0.0.1:8501.
// In prod: configure VITE_API_BASE at build time.

const API_BASE = import.meta.env.VITE_API_BASE || '';

async function request(path, params = {}) {
  const url = new URL(API_BASE + path, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
  }
  const r = await fetch(url.toString());
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.statusText}`);
  return r.json();
}

export const api = {
  alerts: (params = {}) => request('/api/alerts', params),
  execution: (params = {}) => request('/api/execution', params),
  replay: (params = {}) => request('/api/replay', params),
  replayCsv: (name) => request(`/api/replay/csv/${encodeURIComponent(name)}`),
  audit: (params = {}) => request('/api/audit', params),
  health: () => request('/api/health'),
};

export function badgeClass(state) {
  const s = (state || '').toLowerCase();
  if (s === 'chart-qualified') return 'badge-chart';
  if (s === 'watch') return 'badge-watch';
  if (s === 'blocked') return 'badge-blocked';
  return 'badge-neutral';
}

export function decisionBadge(d) {
  if (d === 'accept') return '<span class="badge badge-accept">accept</span>';
  if (d === 'reject') return '<span class="badge badge-reject">reject</span>';
  return '<span class="badge badge-neutral">—</span>';
}

export function escape(s) {
  if (s == null) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function fmtTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}
