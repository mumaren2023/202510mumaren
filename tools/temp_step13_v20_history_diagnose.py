from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def identify_root(folder: Path) -> Path:
    for p in folder.iterdir():
        if p.is_dir() and (p / 'current').is_dir() and (p / 'history').is_dir():
            return p
    dirs = [p for p in folder.iterdir() if p.is_dir()]
    if len(dirs) == 1:
        return dirs[0]
    raise RuntimeError('cannot identify root')


def clean(root: Path) -> None:
    for p in list(root.rglob('__pycache__')):
        shutil.rmtree(p, ignore_errors=True)
    for p in list(root.rglob('*.pyc')):
        p.unlink(missing_ok=True)


def flatten_failures(value: Any, path: str = '') -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if isinstance(value, dict):
        is_failure = False
        if value.get('ok') is False or value.get('passed') is False or value.get('result') == 'FAIL':
            is_failure = True
        if isinstance(value.get('failed'), int) and value.get('failed', 0) > 0 and any(k in value for k in ('name','test_id','title')):
            is_failure = True
        if is_failure:
            failures.append({'path': path, 'value': value})
        for k, v in value.items():
            failures.extend(flatten_failures(v, f'{path}.{k}' if path else str(k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            failures.extend(flatten_failures(v, f'{path}[{i}]'))
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-zip', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source = Path(args.source_zip)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='v20_history_diag_'))
    outer = work / 'outer'; outer.mkdir()
    with zipfile.ZipFile(source) as z:
        z.extractall(outer)
    inner_candidates = list(outer.rglob('*第13步教育转化接口准备完整包_V2.1_修正版_候选_20260722.zip'))
    if len(inner_candidates) != 1:
        raise RuntimeError(f'inner package count={len(inner_candidates)}')
    inner = work / 'inner'; inner.mkdir()
    with zipfile.ZipFile(inner_candidates[0]) as z:
        z.extractall(inner)
    root = identify_root(inner)
    histories = [p for p in (root / 'history').iterdir() if p.is_dir() and 'V2.0' in p.name]
    if len(histories) != 1:
        raise RuntimeError(f'history count={len(histories)}')
    current = histories[0] / 'current'
    runtime = work / 'runtime'; shutil.copytree(current, runtime); clean(runtime)
    env = dict(os.environ); env['PYTHONDONTWRITEBYTECODE'] = '1'
    proc = subprocess.run([sys.executable, str(runtime / 'validate_current.py')], cwd=runtime, env=env, capture_output=True, text=True, timeout=300)
    result: dict[str, Any] = {
        'returncode': proc.returncode,
        'stdout': proc.stdout,
        'stderr': proc.stderr,
        'reports': {},
        'failures': [],
    }
    for report in sorted((runtime / 'reports').glob('*v20*.json')):
        try:
            obj = read_json(report)
        except Exception as exc:
            result['reports'][report.name] = {'parse_error': str(exc)}
            continue
        result['reports'][report.name] = obj
        for failure in flatten_failures(obj, report.name):
            result['failures'].append(failure)
    (out / 'v20_history_diagnosis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'returncode': proc.returncode,
        'summary_stdout': proc.stdout[-2000:],
        'failure_count': len(result['failures']),
        'failures': result['failures'][:20],
        'output': str(out / 'v20_history_diagnosis.json'),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
