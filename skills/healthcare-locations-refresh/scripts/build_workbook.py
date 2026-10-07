"""Build the Excel workbook from the per-source JSON files in WORK_DIR.

Tabs: Summary, Changes (only with --previous), one tab per source, Excluded, Checks.
Checks compare counts and key-field fill rates against the previous workbook
(or references/baseline.json when there is no previous file).

usage: build_workbook.py WORK_DIR OUTPUT.xlsx [--previous LAST_MONTH.xlsx]
"""
import argparse
import json
import os
import re
import time

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
DAYS = [f'{d} Hours' for d in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']]
SOURCES = {  # key: (tab name, columns)
    'jefferson': ('Jefferson Health', ['Name', 'Location Type', 'Facility Label', 'Street Address', 'City', 'State', 'ZIP', 'County',
                                       'Latitude', 'Longitude', 'Phone', 'Other Phones', 'Fax', 'Email', 'Open 24 Hours'] + DAYS +
                  ['Hours Footnote', 'Clinical Specialties', 'Conditions', 'Treatments', 'Wheelchair Accessible',
                   'Public Transportation', 'Shuttle Service', 'Language Services', 'Einstein Location', 'Online Scheduling',
                   'Description', 'Google Maps Link', 'Directions/Parking Page', 'Department Directory', 'Location URL',
                   'Last Published', 'Note']),
    'lvhn': ('LVHN', ['Name', 'Location Types', 'Located At', 'Part Of (Institute)', 'Street Address', 'Address Line 1',
                      'Address Line 2', 'City', 'State', 'ZIP', 'Latitude', 'Longitude', 'Phone', 'Fax', 'Hours Note'] + DAYS +
             ['Other Hours', 'Hours Text', 'Services', 'Description', 'Alert', 'Location URL', 'Node ID', 'Note']),
    'quest': ('Quest Diagnostics', ['Name', 'Site Code', 'Location Type', 'Operator / Brand', 'Street Address', 'City', 'State',
                                    'ZIP', 'Country', 'Latitude', 'Longitude', 'Phone', 'Fax'] + DAYS +
              ['Landmark', 'Online Scheduling', 'Schedule Online Link', 'Location URL']),
    'labcorp': ('Labcorp', ['Name', 'Location ID', 'Location Type', 'Street Address', 'City', 'State', 'ZIP', 'Country',
                            'Latitude', 'Longitude', 'Phone', 'Fax'] + DAYS +
                ['Holiday / Special Hours', 'Services', 'Location URL']),
}
DIFF_FIELDS = ['Name', 'Street Address', 'City', 'State', 'ZIP', 'Phone', 'Fax'] + DAYS
KEY_FIELDS = ['Name', 'Street Address', 'City', 'Phone', 'Latitude']
WIDE = {'Description': 60, 'Clinical Specialties': 60, 'Services': 60, 'Hours Footnote': 50, 'Landmark': 50}

F = Font(name='Arial', size=10)
B = Font(name='Arial', size=10, bold=True)
HF = Font(name='Arial', size=10, bold=True, color='FFFFFF')
LINK = Font(name='Arial', size=10, color='0563C1', underline='single')
FILL = PatternFill('solid', fgColor='1F4E78')
WARN = PatternFill('solid', fgColor='FCE4D6')


def clean(v):
    if isinstance(v, str):
        v = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', v).strip()
        return v or None
    return v


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def norm(v):
    return re.sub(r'\s+', ' ', str(v)).strip().lower() if v not in (None, '') else ''


def add_sheet(wb, title, rows, cols):
    ws = wb.create_sheet(title)
    ws.append(cols)
    for c in ws[1]:
        c.font, c.fill, c.alignment = HF, FILL, Alignment(vertical='center', wrap_text=True)
    for r in rows:
        ws.append([num(clean(r.get(c))) if c in ('Latitude', 'Longitude') else clean(r.get(c)) for c in cols])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font = F
            if isinstance(c.value, str) and c.value.startswith('http') and ' ' not in c.value:
                c.hyperlink, c.font = c.value, LINK
    for i, c in enumerate(cols, 1):
        w = WIDE.get(c)
        if w is None:
            L = sorted(len(str(r.get(c) or '')) for r in rows[:500]) or [0]
            w = min(max(10, len(c) + 2, int(L[int(len(L) * .9)] * 1.1) + 2), 50)
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'B2'
    ws.auto_filter.ref = ws.dimensions
    ws.row_dimensions[1].height = 30
    return ws


def read_previous(path):
    """{source_key: {url: row_dict}} from last month's workbook."""
    wb = load_workbook(path, read_only=True, data_only=True)
    out = {}
    for key, (tab, _) in SOURCES.items():
        if tab not in wb.sheetnames:
            continue
        it = wb[tab].iter_rows(values_only=True)
        hdr = list(next(it))
        if 'Location URL' not in hdr:
            continue
        out[key] = {r[hdr.index('Location URL')]: dict(zip(hdr, r)) for r in it if r and r[hdr.index('Location URL')]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('work_dir')
    ap.add_argument('output')
    ap.add_argument('--previous')
    a = ap.parse_args()

    data = {}
    for key in SOURCES:
        p = os.path.join(a.work_dir, f'{key}.json')
        if os.path.exists(p):
            data[key] = json.load(open(p))
    if not data:
        raise SystemExit('No source JSON files found in ' + a.work_dir)
    prev = read_previous(a.previous) if a.previous else {}
    baseline = json.load(open(os.path.join(HERE, '..', 'references', 'baseline.json')))

    checks, changes, excluded = [], [], []
    for key, d in data.items():
        tab, cols = SOURCES[key]
        recs = d['records']
        excluded += d.get('excluded', [])
        for w in d.get('warnings', []):
            checks.append((tab, 'Scraper warning', w, 'WARN'))
        for w in d.get('info', []):
            checks.append((tab, 'Note', w, 'INFO'))
        # count check
        ref_n, ref_src = (len(prev[key]), 'last month') if key in prev else (baseline[key]['count'], f"baseline ({baseline['_date']})")
        n = len(recs)
        chg = (n - ref_n) / ref_n if ref_n else 0
        status = 'WARN' if chg < -0.10 or chg > 0.25 else 'OK'
        checks.append((tab, 'Location count', f'{n} vs {ref_n} {ref_src} ({chg:+.1%})', status))
        # fill-rate check on key fields
        for fld in KEY_FIELDS:
            if fld not in cols:
                continue
            rate = sum(1 for r in recs if r.get(fld) not in (None, '')) / max(n, 1)
            exp = baseline[key]['fill'].get(fld, 0.9)
            checks.append((tab, f'{fld} filled', f'{rate:.0%} (usual ~{exp:.0%})', 'WARN' if rate < exp - 0.10 else 'OK'))
        # month-over-month changes
        if key in prev:
            cur = {r['Location URL']: r for r in recs}
            old = prev[key]
            for u in cur.keys() - old.keys():
                r = cur[u]
                changes.append({'Source': tab, 'Change': 'Added', 'Name': r.get('Name'), 'City': r.get('City'),
                                'State': r.get('State'), 'Field': None, 'Old Value': None, 'New Value': None, 'Location URL': u})
            for u in old.keys() - cur.keys():
                r = old[u]
                changes.append({'Source': tab, 'Change': 'Removed', 'Name': r.get('Name'), 'City': r.get('City'),
                                'State': r.get('State'), 'Field': None, 'Old Value': None, 'New Value': None, 'Location URL': u})
            for u in cur.keys() & old.keys():
                for fld in DIFF_FIELDS:
                    if fld in cols and fld in old[u] and norm(cur[u].get(fld)) != norm(old[u].get(fld)):
                        changes.append({'Source': tab, 'Change': 'Changed', 'Name': cur[u].get('Name'), 'City': cur[u].get('City'),
                                        'State': cur[u].get('State'), 'Field': fld, 'Old Value': old[u].get(fld),
                                        'New Value': cur[u].get(fld), 'Location URL': u})

    wb = Workbook()
    s = wb.active
    s.title = 'Summary'
    s['A1'] = 'Healthcare & Lab Locations'
    s['A1'].font = Font(name='Arial', size=14, bold=True)
    s['A2'] = f"Collected {time.strftime('%B %d, %Y')} from each organization's public website"
    s['A2'].font = Font(name='Arial', size=10, italic=True)
    hdr = ['Organization', 'Locations', 'States / Regions', 'Added', 'Removed', 'Changed fields', 'Checks']
    for i, h in enumerate(hdr, 1):
        c = s.cell(row=4, column=i, value=h)
        c.font, c.fill = HF, FILL
    row = 5
    for key in SOURCES:
        if key not in data:
            continue
        tab, cols = SOURCES[key]
        recs = sorted(data[key]['records'], key=lambda r: (str(r.get('Country') or 'US') != 'US', r.get('State') or '',
                                                           r.get('City') or '', r.get('Name') or ''))
        add_sheet(wb, tab, recs, cols)
        st = get_column_letter(cols.index('State') + 1)
        s.cell(row=row, column=1, value=tab)
        s.cell(row=row, column=2, value=f"=COUNTA('{tab}'!A:A)-1")
        s.cell(row=row, column=3, value=f"=SUMPRODUCT(('{tab}'!{st}2:{st}20000<>\"\")/COUNTIF('{tab}'!{st}2:{st}20000,'{tab}'!{st}2:{st}20000&\"\"))")
        if changes or prev:
            for col, kind in ((4, 'Added'), (5, 'Removed'), (6, 'Changed')):
                s.cell(row=row, column=col, value=f'=COUNTIFS(Changes!A:A,"{tab}",Changes!B:B,"{kind}")')
        warns = sum(1 for c in checks if c[0] == tab and c[3] == 'WARN')
        s.cell(row=row, column=7, value='OK' if not warns else f'{warns} warning(s) - see Checks tab')
        if warns:
            s.cell(row=row, column=7).fill = WARN
        row += 1
    s.cell(row=row, column=1, value='Total').font = B
    s.cell(row=row, column=2, value=f'=SUM(B5:B{row - 1})').font = B
    s.cell(row=row + 1, column=1, value='Excluded (listed but no data)')
    s.cell(row=row + 1, column=2, value='=COUNTA(Excluded!A:A)-1')
    notes = ['Notes',
             'Every row links back to its source page (Location URL). Blank hours mean the website lists none (often "hours vary / please call").',
             'Changes tab: locations added/removed since last month and changed name, address, phone, fax or hours (only when a previous file was supplied).',
             'Quest: Location Type separates Quest patient service centers, joint ventures/affiliates, partner collection sites and international sites.',
             'Labcorp: "Labcorp at Walgreens" = Labcorp service center inside a Walgreens store.',
             'LVHN: Location Types and Services come from the lvhn.org location filters; a location can have several.']
    for i, n in enumerate(notes, row + 3):
        s.cell(row=i, column=1, value=n).font = B if n == 'Notes' else F
    for r_ in s.iter_rows(min_row=5, max_row=row + 1):
        for c in r_:
            if not c.font.b:
                c.font = F
    for col, w in zip('ABCDEFG', (32, 12, 16, 10, 10, 15, 34)):
        s.column_dimensions[col].width = w

    if prev:
        add_sheet(wb, 'Changes', changes, ['Source', 'Change', 'Name', 'City', 'State', 'Field', 'Old Value', 'New Value', 'Location URL'])
    add_sheet(wb, 'Excluded', excluded, ['Source', 'Location URL', 'Reason'])
    ck = add_sheet(wb, 'Checks', [dict(zip(['Source', 'Check', 'Result', 'Status'], c)) for c in checks],
                   ['Source', 'Check', 'Result', 'Status'])
    for r_ in ck.iter_rows(min_row=2):
        if r_[3].value == 'WARN':
            for c in r_:
                c.fill = WARN
    wb.move_sheet('Checks', offset=-(len(wb.sheetnames) - 2))
    wb.save(a.output)

    summary = {'output': a.output,
               'counts': {k: len(v['records']) for k, v in data.items()},
               'excluded': len(excluded),
               'changes': {k: sum(1 for c in changes if c['Change'] == k) for k in ('Added', 'Removed', 'Changed')} if prev else None,
               'warnings': [f'{c[0]}: {c[1]}: {c[2]}' for c in checks if c[3] == 'WARN']}
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
