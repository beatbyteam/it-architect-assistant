const SCRIPT_TAG_RE = /<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi;
const IFRAME_TAG_RE = /<iframe\b[^<]*(?:(?!<\/iframe>)<[^<]*)*<\/iframe>/gi;
const STYLE_TAG_RE = /<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi;
const EMBEDDED_OBJECT_RE = /<(object|embed|svg|math|template|form|meta|link|base)\b[^>]*>[\s\S]*?<\/\1>/gi;
const INLINE_HANDLER_RE = /\son[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi;
const JS_PROTOCOL_RE = /(href|src|xlink:href)\s*=\s*(["'])\s*(javascript:|data:text\/html|vbscript:)[^"']*\2/gi;

const ALLOWED_TAGS = new Set([
  'a', 'abbr', 'article', 'aside', 'b', 'blockquote', 'br', 'code', 'dd', 'div', 'dl', 'dt', 'em', 'figcaption', 'figure',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img', 'li', 'main', 'mark', 'ol', 'p', 'pre', 'section', 'small', 'span',
  'strong', 'sub', 'sup', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'u', 'ul',
]);
const BLOCKED_TAGS = new Set(['script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'template', 'form', 'input', 'button', 'textarea', 'select', 'option', 'meta', 'link', 'base']);
const GLOBAL_ALLOWED_ATTRS = new Set(['class', 'id', 'title', 'aria-label', 'aria-labelledby', 'role']);
const TAG_ALLOWED_ATTRS: Record<string, Set<string>> = {
  a: new Set(['href', 'target', 'rel']),
  img: new Set(['src', 'alt', 'title']),
  td: new Set(['colspan', 'rowspan']),
  th: new Set(['colspan', 'rowspan', 'scope']),
};

function fallbackSanitize(html: string) {
  return html
    .replace(SCRIPT_TAG_RE, '')
    .replace(IFRAME_TAG_RE, '')
    .replace(STYLE_TAG_RE, '')
    .replace(EMBEDDED_OBJECT_RE, '')
    .replace(INLINE_HANDLER_RE, '')
    .replace(JS_PROTOCOL_RE, '$1="#"');
}

function isSafeUrl(value: string) {
  const normalized = value.trim().replace(/[\u0000-\u001f\u007f\s]+/g, '').toLowerCase();
  return normalized.startsWith('http://')
    || normalized.startsWith('https://')
    || normalized.startsWith('mailto:')
    || normalized.startsWith('tel:')
    || normalized.startsWith('#')
    || normalized.startsWith('/')
    || normalized.startsWith('./')
    || normalized.startsWith('../');
}

function sanitizeNodeAttributes(element: Element) {
  const tag = element.tagName.toLowerCase();
  const allowedAttrs = TAG_ALLOWED_ATTRS[tag] ?? new Set<string>();
  for (const attr of Array.from(element.attributes)) {
    const name = attr.name.toLowerCase();
    const value = attr.value;
    const isAllowed = GLOBAL_ALLOWED_ATTRS.has(name) || allowedAttrs.has(name);
    if (!isAllowed || name.startsWith('on') || name === 'style' || name === 'srcset') {
      element.removeAttribute(attr.name);
      continue;
    }
    if ((name === 'href' || name === 'src' || name === 'xlink:href') && !isSafeUrl(value)) {
      element.removeAttribute(attr.name);
      continue;
    }
    if (tag === 'a' && name === 'target' && value !== '_blank') {
      element.removeAttribute(attr.name);
      continue;
    }
  }

  if (tag === 'a') {
    if (!element.getAttribute('href')) {
      element.removeAttribute('target');
      element.removeAttribute('rel');
    } else if (element.getAttribute('target') === '_blank') {
      element.setAttribute('rel', 'noopener noreferrer');
    }
  }
}

export function sanitizeHtml(html?: string | null) {
  if (!html) return '';
  const stripped = fallbackSanitize(html);

  if (typeof DOMParser === 'undefined') return stripped;

  const parser = new DOMParser();
  const document = parser.parseFromString(stripped, 'text/html');
  const elements = Array.from(document.body.querySelectorAll('*'));

  for (const element of elements) {
    const tag = element.tagName.toLowerCase();
    if (BLOCKED_TAGS.has(tag)) {
      element.remove();
      continue;
    }
    if (!ALLOWED_TAGS.has(tag)) {
      element.replaceWith(...Array.from(element.childNodes));
      continue;
    }
    sanitizeNodeAttributes(element);
  }

  return document.body.innerHTML;
}
