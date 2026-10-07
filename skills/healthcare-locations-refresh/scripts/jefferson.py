"""Jefferson Health locations (jeffersonhealth.org/locations).

The locations page is an Adobe AEM single-page app. Its page model
(/locations.model.json) contains a `search_listings` component with the Solr
(SearchStax) URL and the public read-only Basic-auth value the browser itself
uses. We query that index for every location, then read each location's own
page model for hours, extra phones and amenities.

usage: jefferson.py WORK_DIR [--workers N]
"""
import argparse
import json
import os
import re
import urllib.parse

from common import DAYS, Fetcher, get_json, log, txt, write_result

BASE = 'https://www.jeffersonhealth.org'


def find_search_config(o):
    if isinstance(o, dict):
        if o.get('solrUrl') and o.get('contentType') == 'location':
            return o
        for v in o.values():
            r = find_search_config(v)
            if r:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find_search_config(v)
            if r:
                return r
    return None


def yn(v):
    if v in (True, 'true'):
        return 'Yes'
    if v in (False, 'false'):
        return 'No'
    return None


def j(v):
    return '; '.join(v) if isinstance(v, list) else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('work_dir')
    ap.add_argument('--workers', type=int, default=6)
    a = ap.parse_args()
    warnings = []

    cfg = find_search_config(get_json(BASE + '/locations.model.json'))
    if not cfg:
        raise SystemExit('Could not find the location search config in /locations.model.json - see references/sources.md')
    headers = {'Accept': 'application/json'}
    if cfg.get('passBasicAuthToken') and cfg.get('authValue'):
        headers['Authorization'] = 'Basic ' + cfg['authValue']
    q = urllib.parse.urlencode({'fq': 'content_type:health2021/content-type/location', 'rows': 5000,
                                'start': 0, 'wt': 'json', 'fl': '*', 'facet': 'false'})
    resp = None
    for handler in ('/search-name-location', '/select'):
        try:
            resp = get_json(cfg['solrUrl'] + handler + '?' + q, headers=headers)
            break
        except Exception as e:
            log('solr handler failed', handler, e)
    if not resp:
        raise SystemExit('Jefferson search index query failed - see references/sources.md')
    docs = resp['response']['docs']
    if resp['response']['numFound'] != len(docs):
        warnings.append(f"index reports {resp['response']['numFound']} but returned {len(docs)}")

    f = Fetcher(os.path.join(a.work_dir, 'cache', 'jefferson'), a.workers)
    urls = {d['id']: BASE + d['page_url'] + '.model.json' for d in docs}
    failures = f.fetch_many(urls.values(), 'jefferson')
    if failures:
        warnings.append(f'{len(failures)} detail pages could not be downloaded (re-run to retry)')

    out, dead = [], 0
    for d in docs:
        raw = f.read(urls[d['id']])
        head = info = {}
        note = None
        if raw is None:
            dead += f.status(urls[d['id']]) == 'not_found'
            note = ('Detail page returns 404 on jeffersonhealth.org (still listed in site search)'
                    if f.status(urls[d['id']]) == 'not_found' else 'Detail page not downloaded')
        else:
            try:
                items = json.loads(raw)[':items']['root'][':items']['responsivegrid'][':items']
                head = next((v for k, v in items.items() if k.startswith('location_detail_head')), {}) or {}
                info = next((v for k, v in items.items() if k.startswith('location_info')), {}) or {}
            except Exception:
                note = 'Detail page could not be parsed'
        hi = head.get('locationDetailInfo') or {}
        ii = info.get('locationDetailInfo') or {}
        hd = head.get('hoursDetail') or {}
        geo = (d.get('location_geo_coordinates') or '').split(',')
        r = {
            'Location URL': BASE + d['page_url'],
            'Name': d.get('page_title'),
            'Location Type': j(d.get('location_type_tags')),
            'Facility Label': hi.get('jeffersonHealthFacilityLabel'),
            'Street Address': d.get('location_street_address'),
            'City': d.get('location_locality'), 'State': d.get('location_region'),
            'ZIP': d.get('location_zip_code'),
            'County': next((re.sub(r'^[A-Z]{2} ', '', t) for t in d.get('page_tags', [])
                            if re.match(r'^[A-Z]{2} .* County$', t)), None),
            'Latitude': geo[0] if len(geo) == 2 else None,
            'Longitude': geo[1] if len(geo) == 2 else None,
            'Phone': d.get('location_phone_number') or hi.get('phoneNumber'),
            'Other Phones': '; '.join(f"{p.get('type')}: {p.get('number')}" for p in hi.get('phoneNumbers') or []),
            'Fax': d.get('location_fax_number') or hi.get('faxNumber'),
            'Email': hi.get('email'),
            'Open 24 Hours': yn(hi.get('open24Hours')),
        }
        for day in DAYS:
            k = day.lower()
            if hd:
                items = hd.get(f'{k}HoursItems') or []
                r[f'{day} Hours'] = (', '.join(f"{i.get('openAtStr') or i.get('openAt')} - {i.get('closeAtStr') or i.get('closeAt')}"
                                               for i in items) if hd.get(f'{k}Open') else 'Closed')
            else:
                r[f'{day} Hours'] = 'Open 24 hours' if hi.get('open24Hours') else None
        r.update({
            'Hours Footnote': txt(hi.get('hoursFootNote')) or None,
            'Clinical Specialties': j(d.get('location_specialities_tags')),
            'Conditions': j(d.get('location_conditions_tags')),
            'Treatments': j(d.get('location_treatment_tags')),
            'Wheelchair Accessible': yn(d.get('location_wheelchair_accessible')),
            'Public Transportation': yn(d.get('location_public_transportation')),
            'Shuttle Service': yn(ii.get('shuttleService')),
            'Language Services': yn(ii.get('languageService')),
            'Einstein Location': yn(head.get('einsteinLocation')),
            'Online Scheduling': yn(hi.get('openScheduling')),
            'Description': d.get('page_description'),
            'Google Maps Link': hi.get('googleMapLocation'),
            'Directions/Parking Page': BASE + hi['directionParkingLink'] if hi.get('directionParkingLink') else None,
            'Department Directory': BASE + hi['depDirectoryLink'] if hi.get('depDirectoryLink') else None,
            'Last Published': (d.get('page_publish_date') or '')[:10] or None,
            'Note': note,
        })
        out.append(r)
    info = [f'{dead} locations are in the search index but their pages return 404 (kept, flagged in Note)'] if dead else []
    write_result(a.work_dir, 'jefferson', out, warnings=warnings, info=info)


if __name__ == '__main__':
    main()
