/* Small, safe Markdown renderer for AI messages. All text is appended as text nodes. */
'use strict';
(() => {
  const {h} = App;
  const inlinePattern = /`([^`\n]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)|\*\*([^*\n]+)\*\*|__([^_\n]+)__|\*([^*\n]+)\*|_([^_\n]+)_/g;

  function safeHref(value) {
    if (/^https?:\/\//i.test(value) || /^mailto:/i.test(value)) return value;
    if (value.startsWith('/') && !value.startsWith('//')) return value;
    if (value.startsWith('#/')) return value;
    return null;
  }

  function inline(source) {
    const value = String(source || '');
    const nodes = [];
    let cursor = 0;
    for (const match of value.matchAll(inlinePattern)) {
      if (match.index > cursor) nodes.push(value.slice(cursor, match.index));
      if (match[1] != null) nodes.push(h('code', {}, match[1]));
      else if (match[2] != null) {
        const href = safeHref(match[3]);
        nodes.push(href ? h('a', {href, ...(href.startsWith('http') ? {target: '_blank', rel: 'noopener noreferrer'} : {})}, match[2]) : match[2]);
      } else if (match[4] != null || match[5] != null) nodes.push(h('strong', {}, ...inline(match[4] ?? match[5])));
      else nodes.push(h('em', {}, ...inline(match[6] ?? match[7])));
      cursor = match.index + match[0].length;
    }
    if (cursor < value.length) nodes.push(value.slice(cursor));
    return nodes;
  }

  const heading = (line) => /^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
  const listItem = (line) => /^\s{0,3}([-+*]|\d+[.)])\s+(.+)$/.exec(line);
  const isRule = (line) => /^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line);
  const tableRule = (line) => /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  const cells = (line) => line.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());
  const isBlock = (line) => heading(line) || listItem(line) || isRule(line) || /^\s{0,3}>/.test(line) || /^\s{0,3}(```|~~~)/.test(line);

  function blocks(source) {
    const lines = String(source || '').replace(/\r\n?/g, '\n').split('\n');
    const nodes = [];
    for (let i = 0; i < lines.length;) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      const fence = /^\s{0,3}(```|~~~)/.exec(line);
      if (fence) {
        const content = [];
        i++;
        while (i < lines.length && !lines[i].trimStart().startsWith(fence[1])) content.push(lines[i++]);
        if (i < lines.length) i++;
        nodes.push(h('pre', {}, h('code', {}, content.join('\n'))));
        continue;
      }
      const title = heading(line);
      if (title) {
        nodes.push(h('h' + Math.min(6, Number(title[1].length) + 1), {}, ...inline(title[2])));
        i++; continue;
      }
      if (isRule(line)) { nodes.push(h('hr', {})); i++; continue; }
      if (line.includes('|') && tableRule(lines[i + 1] || '')) {
        const headers = cells(line);
        const rows = [];
        i += 2;
        while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
          rows.push(h('tr', {}, ...cells(lines[i++]).map((cell) => h('td', {}, ...inline(cell)))));
        }
        nodes.push(h('div', {class: 'research-table-scroll'}, h('table', {},
          h('thead', {}, h('tr', {}, ...headers.map((cell) => h('th', {}, ...inline(cell))))),
          h('tbody', {}, ...rows))));
        continue;
      }
      if (/^\s{0,3}>/.test(line)) {
        const quoted = [];
        while (i < lines.length && /^\s{0,3}>/.test(lines[i])) quoted.push(lines[i++].replace(/^\s{0,3}>\s?/, ''));
        nodes.push(h('blockquote', {}, ...blocks(quoted.join('\n'))));
        continue;
      }
      const first = listItem(line);
      if (first) {
        const ordered = /^\d/.test(first[1]);
        const items = [];
        while (i < lines.length) {
          const item = listItem(lines[i]);
          if (!item || /^\d/.test(item[1]) !== ordered) break;
          i++;
          const parts = [item[2]];
          while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !listItem(lines[i])) parts.push(lines[i++].trim());
          items.push(h('li', {}, ...inline(parts.join(' '))));
        }
        nodes.push(h(ordered ? 'ol' : 'ul', {}, ...items));
        continue;
      }
      const paragraph = [line.trim()];
      i++;
      while (i < lines.length && lines[i].trim() && !isBlock(lines[i]) &&
        !(lines[i].includes('|') && tableRule(lines[i + 1] || ''))) paragraph.push(lines[i++].trim());
      nodes.push(h('p', {}, ...inline(paragraph.join(' '))));
    }
    return nodes;
  }

  App.renderMarkdown = (source) => h('div', {class: 'research-markdown'}, ...blocks(source));
})();
