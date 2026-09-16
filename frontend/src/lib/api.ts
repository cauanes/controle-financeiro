export type Row = {id: string; version: number; [key: string]: any};
export type List = {data: Row[]; next_cursor?: string|null};
export type User = {user_id: string; display_name: string; email: string; households: {id: string; name: string; timezone: string; role: string}[]};
let household = '';
export function setHousehold(id: string) { household = id; }
function csrf() { return document.cookie.split('; ').find(c => c.startsWith('ff_csrf='))?.slice(8) || ''; }
export async function api<T = Row>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = {'X-Household-Id': household};
  if (method !== 'GET') { headers['X-CSRF-Token'] = csrf(); headers['Idempotency-Key'] = crypto.randomUUID(); }
  if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch('/api/v1' + path, {method, credentials: 'include', headers, body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined, signal});
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error?.message || `Não foi possível concluir (${response.status}).`);
  return result as T;
}
export function currency(value: string | undefined | null) {
  if (value == null) return '—';
  const [integer, fraction='00'] = value.split('.');
  try { return `${integer.startsWith('-') ? '− ' : ''}R$ ${BigInt(integer.replace('-','')).toLocaleString('pt-BR')},${fraction.padEnd(2,'0').slice(0,2)}`; }
  catch { return '—'; }
}
export function today(timezone = 'America/Sao_Paulo') { return new Intl.DateTimeFormat('en-CA', {timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()); }
export function dateLabel(value: string) { if (!value) return '—'; const [y,m,d] = value.slice(0,10).split('-'); return `${d}/${m}/${y}`; }
export function decimalInput(value: string) { return value.trim().replace(/\./g,'').replace(',','.'); }
export function labelOf(rows: Row[], id?: string|null) { return rows.find(r=>r.id===id)?.name || 'Sem categoria'; }
