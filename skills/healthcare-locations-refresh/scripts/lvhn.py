"""Lehigh Valley Health Network locations (lvhn.org/locations).

Drupal site with no public JSON API, so we read HTML:
  1. every listing page (/locations?page=N, 15 per page) -> location URLs + alerts
  2. every location page -> address, phone, fax, hours, lat/long (JSON-LD), description
  3. the site's own "Location Type" and "Service" filters -> which types/services each location has
LVHN drops connections under load, so keep workers low (default 3).

usage: lvhn.py WORK_DIR [--workers N]
"""
import argparse
import collections
import html
import json
import math
import os
import re

from common import DAYS, Fetcher, get_text, grab, log, txt, write_result

BASE = 'https://www.lvhn.org'
SHORT = {'Mon': 'Monday', 'Tue': 'Tuesday', 'Wed': 'Wednesday', 'Thu': 'Thursday',
         'Fri': 'Friday', 'Sat': 'Saturday', 'Sun': 'Sunday'}
TITLE_LINK = r'field--name-node-title.*?<a href="(/locations/[^"]+)"'


def hours_tables(seg):
    out = []
    for m in re.finditer(r'<div class="field__label">([^<]*)</div>(.*?)</table>', seg, re.S):
        rows = {}
        for d, v, c in re.findall(r'office-hours__item-label">(.*?)</td>\s*<td class="office-hours__item-slots"[^>]*>(.*?)</td>\s*'
                                  r'<td class="office-hours__item-comments">(.*?)</td>', m.group(2), re.S):
            d, v, c = txt(d).rstrip(':'), txt(v), txt(c)
            rows[SHORT.get(d[:3], d)] = (v + (f' ({c})' if c else '')).strip() or 'Closed'
        if rows:
            out.append((txt(m.group(1)), rows))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('work_dir')
    ap.add_argument('--workers', type=int, default=3)
    a = ap.parse_args()
    warnings = []
    f = Fetcher(os.path.join(a.work_dir, 'cache', 'lvhn'), a.workers)

    first = get_text(BASE + '/locations')
    m = re.search(r'pager__item--last.*?[?&]page=(\d+)', first, re.S)
    if not m:
        raise SystemExit('Could not find the LVHN pager - page layout changed? see references/sources.md')
    last = int(m.group(1))
    list_urls = [BASE + '/locations'] + [f'{BASE}/locations?page={p}' for p in range(1, last + 1)]
    f.fetch_many(list_urls, 'lvhn-list')

    urls, alerts = [], {}
    for lu in list_urls:
        h = f.read(lu) or ''
        for card in h.split('<div class="views-row">')[1:]:
            u = grab(TITLE_LINK, card, lambda s: s)
            if not u:
                continue
            urls.append(u)
            al = grab(r'field--name-field-alert-type[^>]*>(.*?)</div>\s*</div>', card)
            mv = grab(r'field--name-field-moved-to[^>]*>(.*?)</div>\s*</div>', card)
            if al or mv:
                alerts[u] = ' '.join(x for x in (al, mv) if x)
    urls = list(dict.fromkeys(urls))
    log(f'[lvhn] {len(urls)} locations on {len(list_urls)} listing pages')

    # Filters: types are <option> tags, services are in a JSON map in the page
    facets = {'type': {}, 'service': {}}
    for m in re.finditer(r'<option value="/locations\?f%5B0%5D=type%3A(\d+)"[^>]*>([^<]+?) \((\d+)\)</option>', first):
        facets['type'][m.group(1)] = (html.unescape(m.group(2)), int(m.group(3)))
    for m in re.finditer(r'"([^"]+?) \((\d+)\)":"\\/locations\?f%5B0%5D=service%3A([^"]+)"', html.unescape(first)):
        facets['service'][m.group(3)] = (m.group(1), int(m.group(2)))
    if not facets['type']:
        warnings.append('Location Type filter not found - Location Types column will be empty')
    if not facets['service']:
        warnings.append('Service filter not found - Services column will be empty')
    facet_urls = []
    for kind, d in facets.items():
        for fid, (lab, cnt) in d.items():
            for p in range(math.ceil(cnt / 15)):
                facet_urls.append((kind, lab, f'{BASE}/locations?f%5B0%5D={kind}%3A{fid}' + (f'&page={p}' if p else '')))

    detail_urls = [BASE + u for u in urls]
    fails = f.fetch_many(detail_urls + [x[2] for x in facet_urls], 'lvhn-pages')
    if fails:
        warnings.append(f'{len(fails)} pages could not be downloaded (re-run to retry)')

    tags = collections.defaultdict(lambda: collections.defaultdict(set))
    for kind, lab, fu in facet_urls:
        for m in re.finditer(TITLE_LINK, f.read(fu) or '', re.S):
            tags[m.group(1)][kind].add(lab)
    seen_types = collections.Counter(t for u in tags for t in tags[u]['type'])
    off = [lab for lab, cnt in facets['type'].values() if seen_types[lab] != cnt]
    if off:
        warnings.append(f'Location type counts differ from site filter for: {", ".join(off)}')

    out = []
    for u in urls:
        h = f.read(BASE + u)
        r = {'Location URL': BASE + u}
        if h is None:
            r['Name'] = None
            r['Note'] = 'Page not downloaded'
            out.append(r)
            continue
        ld = {}
        for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
            try:
                d = json.loads(m.group(1), strict=False)
            except Exception:
                continue
            for g in d.get('@graph', [d]):
                if g.get('address') and g.get('@id') != 'https://lvhn.org':
                    ld = g
                    break
        tag = grab(r'field--name-location-tagline[^>]*>(.*?)</div>\s*</div>', h, lambda s: s) or ''
        hdr = grab(r'(<section class="location-header">.*?</section>)', h, lambda s: s) or h
        geo = (ld.get('areaServed') or {}).get('geoMidpoint') or ld.get('geo') or {}
        a1 = grab(r'class="address-line1">(.*?)</span>', hdr)
        a2 = grab(r'class="address-line2">(.*?)</span>', hdr)
        r.update({
            'Node ID': grab(r'data-nid="(\d+)"', h, str),
            'Name': grab(r'<h1[^>]*>(.*?)</h1>', h) or ld.get('name'),
            'Location Types': '; '.join(sorted(tags[u]['type'])),
            'Located At': grab(r'Located at\s*(.*?)(?: and part of|$)', tag),
            'Part Of (Institute)': grab(r'part of\s*(.*)$', tag),
            'Street Address': ', '.join(x for x in (a1, a2) if x) or None,
            'Address Line 1': a1, 'Address Line 2': a2,
            'City': grab(r'class="locality">(.*?)</span>', hdr),
            'State': grab(r'class="administrative-area">(.*?)</span>', hdr),
            'ZIP': grab(r'class="postal-code">(.*?)</span>', hdr),
            'Latitude': geo.get('latitude'), 'Longitude': geo.get('longitude'),
            'Phone': grab(r'field--name-field-phone.*?<a href="tel:[^"]*">(.*?)</a>', hdr) or ld.get('telephone'),
            'Fax': grab(r'field--name-field-fax.*?<div class="field__item">(.*?)</div>', hdr),
        })
        tabs = hours_tables(hdr)
        if tabs:
            lab, rows = tabs[0]
            r['Hours Note'] = lab
            for d in DAYS:
                r[f'{d} Hours'] = rows.get(d, 'Closed')
            if len(tabs) > 1:
                r['Other Hours'] = ' | '.join(f'{l}: ' + '; '.join(f'{d[:3]} {v}' for d, v in rw.items()) for l, rw in tabs[1:])
        else:
            oh = ld.get('openingHours') or ''
            for d in DAYS:
                m = re.search(d + r':\s*(.*)', oh)
                r[f'{d} Hours'] = m.group(1).strip().replace('All day open', 'Open 24 hours') if m else None
            status = grab(r'<span class="hours-button-text">\s*<span class="font-normal">(.*?)</span>', hdr)
            r['Hours Note'] = status or ('Open 24 hours' if 'Open 24 hours' in txt(hdr) else None)
        r['Hours Text'] = grab(r'field--name-field-open-hours-text[^>]*>(.*?)</div>\s*</div>', h)
        r['Services'] = '; '.join(sorted(tags[u]['service']))
        r['Description'] = (grab(r'field--name-body[^>]*>(.*?)</div>', h) or '')[:1000] or None
        r['Alert'] = alerts.get(u)
        out.append(r)
    write_result(a.work_dir, 'lvhn', out, warnings=warnings)


if __name__ == '__main__':
    main()
