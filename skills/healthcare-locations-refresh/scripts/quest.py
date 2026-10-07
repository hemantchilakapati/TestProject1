"""Quest Diagnostics locations.

Quest's robots.txt points to a sitemap index whose "locations" sitemap lists
every location detail page (/locations/detail.html/<SITECODE>/<ZIP>/75/1, plus
slug URLs for international sites). Each detail page is server-rendered HTML.
Pages that render with no data are closed sites still listed -> 'excluded'.

usage: quest.py WORK_DIR [--workers N]
"""
import argparse
import html
import os
import re

from common import Fetcher, refetch_empty, get_text, grab, log, txt, write_result

BOILERPLATE = ('We offer broad access to clinical testing services through our national network of '
               'laboratories in most major metropolitan areas as well as approximately 2,000 patient locations.')


def sitemap_urls():
    idx = get_text('https://www.questdiagnostics.com/sitemap.xml')
    maps = [m for m in re.findall(r'<loc>\s*([^<]+?)\s*</loc>', idx) if 'location' in m.lower()]
    if not maps:
        raise SystemExit('No locations sitemap in https://www.questdiagnostics.com/sitemap.xml - see references/sources.md')
    urls = []
    for sm in maps:
        urls += [u for u in re.findall(r'<loc>\s*([^<]+?)\s*</loc>', get_text(sm)) if '/locations/detail.html/' in u]
    return list(dict.fromkeys(urls))


def parse(h, url):
    if 'location-detail-container' not in h:
        return None
    parts = url.split('detail.html/')[-1].split('/')
    r = {'Location URL': url, 'Site Code': parts[0] if len(parts) > 1 else None,
         'Name': grab(r'id="loc-title"[^>]*>(.*?)</div>', h)}
    if not r['Name']:
        return None
    addr = grab(r'<div class="address">(.*?)</div>', h, lambda s: s)
    lines = [txt(x) for x in re.split(r'<br\s*/?>', addr or '') if txt(x)]
    r['Street Address'] = ', '.join(lines[:-1]) if len(lines) > 1 else (lines[0] if lines else None)
    last = lines[-1] if lines else ''
    m = re.match(r'(.*?),\s*([A-Z]{2})\s+(\S+)$', last)
    if m:
        r['City'], r['State'], r['ZIP'] = m.groups()
    else:
        r['City'], r['State'], r['ZIP'] = last, None, None
    r['Phone'] = grab(r'class="phone-num[^"]*"[^>]*>(.*?)</a>', h)
    r['Fax'] = grab(r'class="fax-num[^"]*"[^>]*>(.*?)</a>', h)
    r['Latitude'] = grab(r'<div class="latitude">(.*?)</div>', h)
    r['Longitude'] = grab(r'<div class="longitude">(.*?)</div>', h)
    hrs = grab(r'<div class="week-time-content">(.*?)</div>', h, lambda s: s) or ''
    for d, v in re.findall(r'<p>\s*(\w+):\s*</p>\s*<span>(.*?)</span>', hrs, re.S):
        r[f'{d} Hours'] = txt(v)
    desc = grab(r'<h3 id="detail".*?<div class="label-desc">(.*?)</div>', h, lambda s: s) or ''
    r['Landmark'] = grab(r'<b>\s*Landmark\s*:\s*</b>(.*?)(?:<br|$)', desc)
    r['Schedule Online Link'] = grab(r'href="([^"]+)"[^>]*class="[^"]*schedule-online', h, html.unescape)
    r['Online Scheduling'] = 'Yes' if r['Schedule Online Link'] else 'No'
    # classify
    if r['State']:
        r['Country'] = 'US'
    else:
        blob = ' '.join([url, r['Name'], r['City'] or '', r['Street Address'] or '', r['Phone'] or '']).lower()
        r['Country'] = ('Mexico' if 'mexico' in blob or 'méxico' in blob or '+52' in blob else
                        'Brazil' if 'brasil' in blob or 'brazil' in blob else
                        'Ireland' if 'ireland' in blob else 'India' if 'india' in blob else 'International')
        r['Street Address'] = ', '.join(x for x in [r['Street Address'], (r['City'] or '').strip(', ')] if x)
        r['City'] = None
    r['Operator / Brand'] = r['Name'].split(' - ')[0].strip()
    b = r['Operator / Brand']
    r['Location Type'] = ('International site' if r['Country'] != 'US' else
                          'Quest Patient Service Center' if b.startswith('Quest Diagnostics') else
                          'Quest joint venture / affiliate' if b.startswith(('Sonora Quest', 'Diagnostic Laboratory of Oklahoma')) else
                          'Partner collection site')
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('work_dir')
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    warnings = []
    urls = sitemap_urls()
    log(f'[quest] {len(urls)} location pages in sitemap')
    f = Fetcher(os.path.join(a.work_dir, 'cache', 'quest'), a.workers)
    fails = f.fetch_many(urls, 'quest')
    if fails:
        warnings.append(f'{len(fails)} pages could not be downloaded (re-run to retry)')
    out, excluded = [], []
    parsed = refetch_empty(f, urls, parse, 'quest')
    for u in urls:
        r = parsed[u]
        if r:
            out.append(r)
        else:
            excluded.append({'Source': 'Quest Diagnostics', 'Location URL': u,
                             'Reason': 'Not downloaded' if f.status(u) == 'missing' else
                             'Page on questdiagnostics.com has no location data (likely a closed site still in the sitemap)'})
    write_result(a.work_dir, 'quest', out, excluded, warnings)


if __name__ == '__main__':
    main()
