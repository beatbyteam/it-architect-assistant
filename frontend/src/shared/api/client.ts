const viteEnv = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env;
const API_BASE = viteEnv?.VITE_API_BASE_URL?.replace(/\/$/, '') ?? 'http://localhost:8000/api/v1';

type ValidationDetailItem = {
  loc?: unknown;
  msg?: string;
  type?: string;
};

type ValidationErrorContainer = {
  errors?: ValidationDetailItem[] | null;
};

export type ApiErrorPayload = Record<string, unknown> & {
  code?: string;
  error_code?: string;
  message?: string;
  detail?: string | ValidationDetailItem[] | null;
  details?: ValidationErrorContainer | null;
  user_message?: string;
  technical_message?: string;
  request_id?: string;
  operation_id?: string;
};

export interface ApiError extends Error {
  status: number;
  payload: ApiErrorPayload | null;
}

function isAbsoluteUrl(value: string) {
  return /^[a-z][a-z\d+.-]*:\/\//i.test(value);
}

function normalizePath(path: string) {
  if (/^[a-z][a-z\d+.-]*:\/\//i.test(path)) return path;
  return path.startsWith('/') ? path : `/${path}`;
}

function getBaseOrigin() {
  if (typeof window !== 'undefined' && window.location?.origin) return window.location.origin;
  return 'http://localhost';
}

function buildUrl(path: string, query?: Record<string, string | number | undefined | null>) {
  const normalizedPath = normalizePath(path);
  const url = isAbsoluteUrl(API_BASE)
    ? new URL(`${API_BASE}${normalizedPath}`)
    : new URL(`${API_BASE}${normalizedPath}`, getBaseOrigin());

  if (query) {
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value));
      }
    });
  }
  return url.toString();
}

export function apiUrl(path: string, query?: Record<string, string | number | undefined | null>) {
  return buildUrl(path, query);
}

function formatValidationLocation(value: unknown) {
  if (!Array.isArray(value) || value.length === 0) return null;
  const labels: Record<string, string> = {
    body: 'запрос',
    query: 'параметры',
    path: 'адрес',
    raw_text: 'описание задачи',
    title: 'название',
    name: 'название',
    file: 'файл',
    files: 'файлы',
    knowledge_base_id: 'база знаний',
    knowledge_version_id: 'версия базы знаний',
    source_id: 'источник',
    source_ids: 'источники',
    status: 'статус',
  };
  const parts = value
    .map((item) => labels[String(item)] ?? String(item))
    .filter((item) => !['запрос', 'параметры', 'адрес'].includes(item));
  return (parts.length ? parts : value.map((item) => labels[String(item)] ?? String(item))).join('.');
}

function translateValidationMessage(message?: string, type?: string) {
  const value = (message ?? '').trim();
  const normalized = value.toLowerCase();
  const byType: Record<string, string> = {
    missing: 'Поле обязательно.',
    string_too_short: 'Слишком короткое значение.',
    string_too_long: 'Слишком длинное значение.',
    value_error: 'Некорректное значение.',
    bool_parsing: 'Ожидалось значение да/нет.',
    int_parsing: 'Ожидалось целое число.',
    float_parsing: 'Ожидалось число.',
  };

  if (type && byType[type]) return byType[type];
  if (normalized === 'field required') return 'Поле обязательно.';
  if (normalized.includes('at least one file must be provided')) return 'Выберите хотя бы один файл.';
  if (normalized.includes('input should be a valid')) return 'Некорректный формат значения.';
  if (normalized.includes('string should have at least')) return 'Слишком короткое значение.';
  if (normalized.includes('string should have at most')) return 'Слишком длинное значение.';
  if (normalized.includes('ensure this value has at least')) return 'Слишком короткое значение.';
  if (normalized.includes('ensure this value has at most')) return 'Слишком длинное значение.';
  return value || null;
}

function formatValidationDetails(detail: unknown) {
  if (!Array.isArray(detail) || detail.length === 0) return null;
  const messages = detail
    .filter((item): item is ValidationDetailItem => Boolean(item) && typeof item === 'object')
    .map((item) => {
      const location = formatValidationLocation(item.loc);
      const message = translateValidationMessage(item.msg, item.type);
      if (location && message) return `${location}: ${message}`;
      if (message) return message;
      if (location && item.type) return `${location}: ${translateValidationMessage(undefined, item.type) ?? item.type}`;
      return item.type ?? null;
    })
    .filter((item): item is string => typeof item === 'string' && item.trim().length > 0);

  return messages.length ? messages.join('; ') : null;
}

function extractValidationMessage(payload?: ApiErrorPayload | null) {
  if (!payload) return null;
  const directDetails = formatValidationDetails(payload.detail);
  if (directDetails) return directDetails;
  return formatValidationDetails(payload.details?.errors);
}

function extractPayloadMessage(payload?: ApiErrorPayload | null) {
  if (!payload) return null;
  const validationMessage = extractValidationMessage(payload);
  if (validationMessage) return validationMessage;
  if (typeof payload.user_message === 'string' && payload.user_message.trim()) return payload.user_message;
  if (typeof payload.message === 'string' && payload.message.trim()) return payload.message;
  if (typeof payload.detail === 'string' && payload.detail.trim()) return payload.detail;
  if (typeof payload.technical_message === 'string' && payload.technical_message.trim()) {
    return payload.technical_message;
  }
  return null;
}

async function parseError(response: Response): Promise<ApiError> {
  let payload: ApiErrorPayload | null = null;
  try {
    payload = (await response.json()) as ApiErrorPayload;
  } catch {
    payload = null;
  }

  const error = new Error(
    extractPayloadMessage(payload)
    ?? response.statusText,
  ) as ApiError;
  error.status = response.status;
  error.payload = payload;
  return error;
}

export function getApiErrorMessage(error: unknown, fallback = 'Не удалось выполнить запрос.') {
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object') {
    const apiError = error as Partial<ApiError>;
    const payload = apiError.payload;
    const payloadMessage = extractPayloadMessage(payload);
    if (payloadMessage) return payloadMessage;
    if (apiError.message && typeof apiError.message === 'string') return apiError.message;
  }
  return fallback;
}

export function getApiErrorStatus(error: unknown) {
  if (error && typeof error === 'object' && 'status' in error) {
    const status = (error as Partial<ApiError>).status;
    return typeof status === 'number' ? status : null;
  }
  return null;
}

export type RequestOptions = RequestInit & {
  signal?: AbortSignal;
};

export async function request<T>(
  path: string,
  init?: RequestOptions,
  query?: Record<string, string | number | undefined | null>,
): Promise<T> {
  const headers = new Headers(init?.headers ?? {});
  const body = init?.body;
  const isFormDataBody = typeof FormData !== 'undefined' && body instanceof FormData;
  const hasBody = body !== undefined && body !== null;

  if (hasBody && !isFormDataBody && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(buildUrl(path, query), {
    credentials: 'include',
    ...init,
    headers,
  });

  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
