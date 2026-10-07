"""Run all four scrapers in parallel, then build the workbook.

Safe to re-run: downloaded pages are cached in WORK_DIR/cache, so a run that
timed out resumes instead of starting over. Use a fresh WORK_DIR each month.

usage: run_all.py --work-dir DIR --output FILE.xlsx [--previous LAST.xlsx]
                  [--sources jefferson,lvhn,quest,labcorp] [--build-only]
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ALL = ['jefferson', 'lvhn', 'quest', 'labcorp']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work-dir', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--previous')
    ap.add_argument('--sources', default=','.join(ALL))
    ap.add_argument('--build-only', action='store_true', help='skip scraping, rebuild workbook from existing JSON')
    a = ap.parse_args()
    os.makedirs(os.path.join(a.work_dir, 'logs'), exist_ok=True)
    failed = []
    if not a.build_only:
        procs = {}
        for s in [x.strip() for x in a.sources.split(',') if x.strip()]:
            if s not in ALL:
                raise SystemExit(f'unknown source {s}; choose from {ALL}')
            log = open(os.path.join(a.work_dir, 'logs', f'{s}.log'), 'w')
            procs[s] = (subprocess.Popen([sys.executable, os.path.join(HERE, f'{s}.py'), a.work_dir],
                                         stdout=log, stderr=subprocess.STDOUT, cwd=HERE), log)
            print(f'started {s} (log: {a.work_dir}/logs/{s}.log)', flush=True)
        t0 = time.time()
        while procs:
            for s, (p, log) in list(procs.items()):
                if p.poll() is not None:
                    log.close()
                    print(f'{s}: {"done" if p.returncode == 0 else "FAILED (exit %d)" % p.returncode} after {int(time.time() - t0)}s', flush=True)
                    if p.returncode:
                        failed.append(s)
                    del procs[s]
            time.sleep(5)
    if failed:
        print(f'Failed sources: {failed}. Check their logs; the workbook will use any older JSON left in the work dir.', flush=True)
    cmd = [sys.executable, os.path.join(HERE, 'build_workbook.py'), a.work_dir, a.output]
    if a.previous:
        cmd += ['--previous', a.previous]
    sys.exit(subprocess.call(cmd, cwd=HERE) or (1 if failed else 0))


if __name__ == '__main__':
    main()
