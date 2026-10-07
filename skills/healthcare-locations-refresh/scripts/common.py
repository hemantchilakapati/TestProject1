"""Shared helpers: polite HTTP fetching with retries and an on-disk cache (so interrupted runs resume)."""
import concurrent.futures as cf
import gzip
import hashlib
import html
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/130.0 Safari/537.36')
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class NotFound(Exception):
    pass


def http_get(url, headers=None, timeout=60, tries=6):
    """GET a URL and return bytes. Retries with backoff; raises NotFound on 404/410."""
    h = {'User-Agent': UA, 'Accept-Encoding': 'gzip'}
    h.update(headers or {})
    err = None
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)
            data = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                data = gzip.decompress(data)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                raise NotFound(f'{e.code} {url}')
            err = e
        except Exception as e:  # connection resets, timeouts, TLS hiccups
            err = e
        time.sleep(min(60, 3 * 2 ** i))
    raise RuntimeError(f'failed after {tries} tries: {url}: {err}')


def get_text(url, **kw):
    return http_get(url, **kw).decode('utf-8', 'replace')


def get_json(url, **kw):
    return json.loads(http_get(url, **kw))


class Fetcher:
    """Downloads many pages into a cache dir (gzip). Already-cached pages are skipped,
    so re-running after a timeout picks up where it left off."""

    def __init__(self, cache_dir, workers=4, headers=None):
        self.dir = cache_dir
        self.workers = workers
        self.headers = headers
        os.makedirs(cache_dir, exist_ok=True)

    def path(self, url):
        return os.path.join(self.dir, hashlib.md5(url.encode()).hexdigest() + '.gz')

    def read(self, url):
        p = self.path(url)
        if not os.path.exists(p):
            return None
        with gzip.open(p, 'rt', encoding='utf-8', errors='replace') as f:
            data = f.read()
        return None if data == '__404__' else data

    def status(self, url):
        p = self.path(url)
        if not os.path.exists(p):
            return 'missing'
        with gzip.open(p, 'rt', encoding='utf-8', errors='replace') as f:
            return 'not_found' if f.read(8) == '__404__' else 'ok'

    def fetch_many(self, urls, label=''):
        urls = list(dict.fromkeys(urls))
        todo = [u for u in urls if not os.path.exists(self.path(u))]
        log(f'[{label}] {len(urls)} pages, {len(urls) - len(todo)} already cached, fetching {len(todo)}')
        lock = threading.Lock()
        done = {'n': 0, 'fail': 0}
        failures = []

        def one(u):
            try:
                data = http_get(u, headers=self.headers)
            except NotFound:
                data = b'__404__'
            except Exception as e:
                with lock:
                    done['fail'] += 1
                    failures.append((u, str(e)))
                return
            tmp = self.path(u) + '.tmp'
            with gzip.open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, self.path(u))
            with lock:
                done['n'] += 1
                if done['n'] % 200 == 0:
                    log(f'[{label}] {done["n"]}/{len(todo)} fetched')

        with cf.ThreadPoolExecutor(self.workers) as ex:
            list(ex.map(one, todo))
        log(f'[{label}] fetched {done["n"]}, failed {done["fail"]}')
        return failures


def refetch_empty(fetcher, urls, parse, label, rounds=2, pause=15):
    """Sites sometimes serve a blank template for a real location. Re-download pages that
    parsed as empty a couple of times before treating them as genuinely empty."""
    parsed = {}
    for u in urls:
        h = fetcher.read(u)
        parsed[u] = parse(h, u) if h else None
    for i in range(rounds):
        empty = [u for u, r in parsed.items() if r is None and fetcher.status(u) != 'not_found']
        if not empty:
            break
        log(f'[{label}] re-checking {len(empty)} empty pages (round {i + 1})')
        time.sleep(pause)
        for u in empty:
            os.remove(fetcher.path(u)) if os.path.exists(fetcher.path(u)) else None
        fetcher.fetch_many(empty, label + '-recheck')
        for u in empty:
            h = fetcher.read(u)
            parsed[u] = parse(h, u) if h else None
    return parsed


def txt(s):
    """HTML fragment -> clean single-line text."""
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()


def grab(pat, h, f=txt):
    m = re.search(pat, h or '', re.S)
    return f(m.group(1)) if m else None


def write_result(work_dir, source, records, excluded=None, warnings=None, info=None):
    out = {'source': source, 'fetched_at': time.strftime('%Y-%m-%d %H:%M'),
           'count': len(records), 'records': records,
           'excluded': excluded or [], 'warnings': warnings or [], 'info': info or []}
    p = os.path.join(work_dir, f'{source}.json')
    with open(p, 'w') as f:
        json.dump(out, f)
    log(f'[{source}] wrote {len(records)} records -> {p}')
    print(json.dumps({'source': source, 'count': len(records), 'excluded': len(out['excluded']),
                      'warnings': out['warnings']}))
