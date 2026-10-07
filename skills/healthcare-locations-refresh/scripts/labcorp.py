"""Labcorp locations (locations.labcorp.com).

robots.txt -> sitemap index -> every location page (/<state>/<city>/<id>/).
Each page carries schema.org JSON-LD (MedicalBusiness) with address, geo,
phone, weekly + holiday hours and services; fax is read from the page text.

usage: labcorp.py WORK_DIR [--workers N]
"""
import argparse
import json
import os
import re

from common import DAYS, Fetcher, refetch_empty, get_text, log, write_result

LOC_RE = re.compile(r'^https://locations\.labcorp\.com/[a-z]{2}/[^/]+/\d+/?$')


def sitemap_urls():
    seen, todo, urls = set(), ['https://locations.labcorp.com/sitemap_index.xml'], []
    while todo:
        sm = todo.pop()
        if sm in seen:
            continue
        seen.add(sm)
        x = get_text(sm)
        locs = re.findall(r'<loc>\s*([^<]+?)\s*</loc>', x)
        if '<sitemapindex' in x:
            todo += locs
        else:
            urls += [u for u in locs if LOC_RE.match(u)]
    if not urls:
        raise SystemExit('No Labcorp location URLs found in sitemap - see references/sources.md')
    return list(dict.fromkeys(urls))


def fmt(t):
    h, m = map(int, t.split(':')[:2])
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def parse(h, url):
    lb = None
    for m in re.finditer(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', h, re.S):
        try:
            d = json.loads(m.group(1), strict=False)
        except Exception:
            continue
        if isinstance(d, dict) and d.get('address'):
            lb = d
    if not lb:
        return None
    a, g = lb.get('address', {}), lb.get('geo', {})
    r = {'Location URL': url, 'Location ID': url.rstrip('/').split('/')[-1], 'Name': lb.get('name')}
    r['Location Type'] = re.sub(r'\s*#.*$', '', r['Name'] or '').strip()
    r.update({'Street Address': a.get('streetAddress'), 'City': a.get('addressLocality'),
              'State': a.get('addressRegion'), 'ZIP': a.get('postalCode'), 'Country': a.get('addressCountry'),
              'Latitude': g.get('latitude'), 'Longitude': g.get('longitude'), 'Phone': lb.get('telephone')})
    m = re.search(r'Fax:\s*(?:<[^>]+>\s*)*([+\d][\d\s().-]{6,})', h)
    r['Fax'] = m.group(1).strip() if m else None
    hrs = {d: [] for d in DAYS}
    for s in lb.get('openingHoursSpecification') or []:
        days = s.get('dayOfWeek')
        for d in (days if isinstance(days, list) else [days]):
            d = str(d).split('/')[-1]
            if d in hrs and not (s.get('opens') == s.get('closes') == '00:00'):
                hrs[d].append(f"{fmt(s['opens'])} - {fmt(s['closes'])}")
    for d in DAYS:
        r[f'{d} Hours'] = ', '.join(hrs[d]) or 'Closed'
    r['Holiday / Special Hours'] = '; '.join(
        f"{s.get('validFrom')}: " + ('Closed' if s.get('opens') == s.get('closes') == '00:00'
                                     else f"{fmt(s['opens'])} - {fmt(s['closes'])}")
        for s in lb.get('specialOpeningHoursSpecification') or [])
    r['Services'] = '; '.join(o['itemOffered']['name'] for o in lb.get('makesOffer') or [] if o.get('itemOffered'))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('work_dir')
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    warnings = []
    urls = sitemap_urls()
    log(f'[labcorp] {len(urls)} location pages in sitemap')
    f = Fetcher(os.path.join(a.work_dir, 'cache', 'labcorp'), a.workers)
    fails = f.fetch_many(urls, 'labcorp')
    if fails:
        warnings.append(f'{len(fails)} pages could not be downloaded (re-run to retry)')
    out, excluded = [], []
    parsed = refetch_empty(f, urls, parse, 'labcorp')
    for u in urls:
        r = parsed[u]
        if r:
            out.append(r)
        else:
            excluded.append({'Source': 'Labcorp', 'Location URL': u,
                             'Reason': 'Not downloaded' if f.status(u) == 'missing' else 'Page has no location data'})
    write_result(a.work_dir, 'labcorp', out, excluded, warnings)


if __name__ == '__main__':
    main()
