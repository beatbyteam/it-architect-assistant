import { titleStatus } from './format';

function normalizeSearchText(value: unknown) {
  return String(value)
    .toLocaleLowerCase('ru-RU')
    .replace(/ё/g, 'е')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function collectSearchParts(value: unknown, seen: WeakSet<object>): string[] {
  if (value === null || value === undefined || value === '') return [];
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    const raw = String(value);
    const titled = typeof value === 'string' ? titleStatus(value) : raw;
    return titled && titled !== raw ? [raw, titled] : [raw];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => collectSearchParts(item, seen));
  }
  if (typeof value === 'object') {
    if (seen.has(value)) return [];
    seen.add(value);
    return Object.entries(value).flatMap(([key, item]) => [key, ...collectSearchParts(item, seen)]);
  }
  return [];
}

export function buildSearchText(parts: unknown[]) {
  return collectSearchParts(parts, new WeakSet())
    .map(normalizeSearchText)
    .filter(Boolean)
    .join(' ');
}

export function matchesSearch(parts: unknown[], query: string) {
  const tokens = normalizeSearchText(query).split(' ').filter(Boolean);
  if (tokens.length === 0) return true;

  const haystack = buildSearchText(parts);
  return tokens.every((token) => haystack.includes(token));
}
