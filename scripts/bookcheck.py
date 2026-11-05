import re, glob, os, sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOID = {'br', 'img', 'hr', 'meta', 'link', 'input', 'source'}

def num(p):
    m = re.match(r'(?:ch|sql|cs|pt|dk)(\d{2})-', os.path.basename(p))
    return int(m.group(1)) if m else None

class P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.st = []
        self.err = []
    def handle_starttag(self, t, a):
        if t not in VOID:
            self.st.append((t, self.getpos()[0]))
    def handle_endtag(self, t):
        if not self.st:
            self.err.append(('extra-close', t, self.getpos()[0]))
            return
        if self.st[-1][0] != t:
            self.err.append(('mismatch', self.st[-1], t, self.getpos()[0]))
            self.st.pop()
        else:
            self.st.pop()

os.chdir(ROOT)
bad = []
pages = [f for f in sorted(glob.glob('*.html')) if num(f)]
h1s = {}
for f in pages:
    s = open(f, encoding='utf-8').read()
    p = P()
    p.feed(s)
    if p.st or p.err:
        bad.append((f, 'tags', p.st[:3], p.err[:3]))
    if s.count('</html>') != 1:
        bad.append((f, 'html-close', s.count('</html>')))
    if s.count('class="pager"') != 1:
        bad.append((f, 'pager-count', s.count('class="pager"')))
    if '<!--CUT' in s:
        bad.append((f, 'CUT-marker'))
    m = re.search(r'<h1>(.*?)</h1>', s, re.S)
    h1s[f] = re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else None
    for h in re.findall(r'href="([^"#?]+\.html)', s):
        if not os.path.exists(h):
            bad.append((f, 'broken-link', h))
    raw = re.findall(r'&(?![A-Za-z][A-Za-z0-9]*;|#\d+;|#x[0-9a-fA-F]+;)', s)
    if raw:
        bad.append((f, 'raw-amp', len(raw)))
    # обратные кавычки (markdown), которых не должно быть в тексте главы
    text = re.sub(r'<pre>.*?</pre>', '', s, flags=re.S)
    text = re.sub(r'<code>.*?</code>', '', text, flags=re.S)
    if '`' in text:
        bad.append((f, 'backtick-in-text'))

# оглавления: номер и заголовок должны совпадать с <h1> главы
toc_files = ['csharp.html', 'net.html', 'sql.html', 'docker.html', 'patterns.html']
entry = re.compile(
    r'<a href="((?:ch|sql|cs|pt|dk)\d{2}-[^"]+\.html)">\s*'
    r'<span class="n">(.*?)</span>\s*<span class="t">(.*?)</span>', re.S)
for toc in toc_files:
    s = open(toc, encoding='utf-8').read()
    for href, n, t in entry.findall(s):
        n = re.sub(r'<[^>]+>', '', n).strip()
        t = re.sub(r'<[^>]+>', '', t).strip()
        real = h1s.get(href)
        if real is None:
            bad.append((toc, 'toc-target-missing', href))
            continue
        rn, _, rt = real.partition('. ')
        if n != rn.strip():
            bad.append((toc, 'toc-number', href, n, rn))
        if t != rt.strip():
            bad.append((toc, 'toc-title', href, t[:50], rt[:50]))

# пейджеры: подпись ссылки должна совпадать с <h1> целевой главы
for f in pages:
    s = open(f, encoding='utf-8').read()
    m = re.search(r'<div class="pager">(.*?)</div>', s, re.S)
    if not m:
        continue
    for href, label in re.findall(r'<a href="([^"]+)">(.*?)</a>', m.group(1), re.S):
        sp = re.search(r'<span class="sp">(.*?)</span>', label, re.S)
        if not sp or href not in h1s:
            continue
        text = re.sub(r'<[^>]+>', '', sp.group(1)).strip()
        if h1s[href] and text != h1s[href]:
            bad.append((f, 'pager-label', href, text[:45], h1s[href][:45]))

# порядок глав в оглавлении = порядок листания: соседи в пейджере и верхней панели
PREFIX = {'csharp.html': 'cs', 'net.html': 'ch', 'sql.html': 'sql',
          'docker.html': 'dk', 'patterns.html': 'pt'}
for toc, pref in PREFIX.items():
    tocs = open(toc, encoding='utf-8').read()
    order = re.findall(r'<a href="(%s\d{2}-[^"]+\.html)"><span class="n">Глава' % pref, tocs)
    for i, f in enumerate(order):
        if f not in pages:
            continue
        s = open(f, encoding='utf-8').read()
        m = re.search(r'<div class="pager">(.*?)</div>', s, re.S)
        links = re.findall(r'href="([^"]+)"', m.group(1)) if m else []
        got = [h for h in links if re.match(r'%s\d{2}-' % pref, h)]  # ссылки на оглавление игнорируем
        want = [x for x in [order[i - 1] if i else None,
                            order[i + 1] if i + 1 < len(order) else None] if x]
        if got != want:
            bad.append((f, 'pager-neighbors', got, want))
        top = re.search(r'<div class="topbar">.*?</div></div>', s, re.S)
        if top and i + 1 < len(order):
            nxt = [h for h in re.findall(r'href="([^"]+)"', top.group(0))
                   if re.match(r'%s\d{2}-' % pref, h)]
            if not nxt or nxt[-1] != order[i + 1]:
                bad.append((f, 'topbar-next', nxt[-1] if nxt else None, order[i + 1]))

# оглавления разделов: запись обязана иметь номер и название,
# и все главы раздела должны быть в нём перечислены
for toc, pref in PREFIX.items():
    s = open(toc, encoding='utf-8').read()
    for block in re.findall(r'<div class="toc">(.*?)</div>', s, re.S):
        for inner in re.findall(r'<a [^>]*>(.*?)</a>', block, re.S):
            if 'class="n"' not in inner or 'class="t"' not in inner:
                bad.append((toc, 'toc-entry-shape', re.sub(r'<[^>]+>', '', inner)[:40]))
    listed = set(re.findall(r'href="(%s\d{2}-[^"]+\.html)"' % pref, s))
    for missing in sorted({os.path.basename(f) for f in pages
                           if os.path.basename(f).startswith(pref)} - listed):
        bad.append((toc, 'toc-missing-page', missing))

print('pages:', len(pages), '| PROBLEMS:', len(bad))
for b in bad[:25]:
    print(' -', b)
sys.exit(1 if bad else 0)
