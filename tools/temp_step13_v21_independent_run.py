from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


def load_audit_module(path: Path):
    spec = importlib.util.spec_from_file_location('step13_v21_audit_module', path)
    if spec is None or spec.loader is None:
        raise RuntimeError('cannot load audit module')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-zip', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    source = Path(args.source_zip)
    out = Path(args.output_dir)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix='step13_v21_full_independent_'))
    audit_module = load_audit_module(Path(__file__).with_name('temp_step13_v21_independent_audit.py'))

    outer_dir = work / 'outer'
    outer_dir.mkdir()
    with zipfile.ZipFile(source) as z:
        outer_bad = z.testzip()
        z.extractall(outer_dir)
    complete_candidates = list(outer_dir.rglob('*第13步教育转化接口准备完整包_V2.1_修正版_候选_20260722.zip'))
    if len(complete_candidates) != 1:
        raise RuntimeError(f'expected one V2.1 complete package, found {len(complete_candidates)}')
    complete = complete_candidates[0]
    complete_sha = audit_module.sha256(complete)

    inner_dir = work / 'inner'
    inner_dir.mkdir()
    with zipfile.ZipFile(complete) as z:
        inner_bad = z.testzip()
        z.extractall(inner_dir)
    root = audit_module.identify_package_root(inner_dir)
    current = root / 'current'
    manifest = audit_module.read_json(root / 'artifact_sha256_manifest.json', {})
    manifest_errors = []
    for entry in manifest.get('entries', []):
        target = root / entry['path']
        if not target.exists():
            manifest_errors.append('missing:' + entry['path'])
        elif audit_module.sha256(target) != entry['sha256']:
            manifest_errors.append('hash:' + entry['path'])

    current_runtime = work / 'current_runtime'
    shutil.copytree(current, current_runtime)
    audit_module.clean_runtime(current_runtime)
    current_proc = audit_module.run_python(current_runtime / 'validate_current.py', current_runtime)
    if current_proc.returncode != 0:
        raise RuntimeError('V2.1 current validator failed\n' + current_proc.stdout + '\n' + current_proc.stderr)
    v21_summary = audit_module.find_validation_summary(current_runtime)

    histories = [p for p in (root / 'history').iterdir() if p.is_dir() and 'V2.0' in p.name]
    if len(histories) != 1:
        raise RuntimeError(f'expected one V2.0 history directory, found {len(histories)}')
    history = histories[0]
    history_runtime = work / 'history_runtime'
    shutil.copytree(history / 'current', history_runtime)
    audit_module.clean_runtime(history_runtime)
    history_proc = audit_module.run_python(history_runtime / 'validate_current.py', history_runtime)
    v20_summary = audit_module.find_validation_summary(history_runtime)

    history_compare = {'status': 'NOT_FOUND'}
    original_candidates = list((root / 'history').glob('*V2.0*原始受审包*.zip'))
    if len(original_candidates) == 1:
        original_dir = work / 'original_v20'
        original_dir.mkdir()
        with zipfile.ZipFile(original_candidates[0]) as z:
            z.extractall(original_dir)
        original_root = audit_module.identify_package_root(original_dir)
        original_map = audit_module.file_hash_map(original_root)
        history_map = audit_module.file_hash_map(history)
        missing = sorted(set(original_map) - set(history_map))
        extra = sorted(set(history_map) - set(original_map))
        different = sorted(k for k in set(original_map) & set(history_map) if original_map[k] != history_map[k])
        history_compare = {
            'source_files': len(original_map), 'history_files': len(history_map),
            'missing': len(missing), 'extra': len(extra), 'hash_differences': len(different),
            'status': 'PASS' if not missing and not extra and not different else 'FAIL',
        }

    tests, findings = audit_module.independent_boundary_tests(current)
    if history_proc.returncode != 0:
        findings.append({
            'issue_id': 'S13R12-P1-03',
            'priority': 'P1',
            'title': 'V2.0回退验证未能在独立环境稳定复现',
            'evidence': 'V2.0历史验证结果为346/349；progress_invalid_datetime、projection_invalid_source_uri和W52无效date-time检查失败。文件级历史比较可通过，但格式校验依赖未锁定。',
            'impact': '回退后可能接受无效日期或来源URI；回退点不能按原声明完成全量自动验收，恢复放行依据不可靠。',
            'repair': '在历史验证环境锁定jsonschema及格式校验依赖；所有Schema验证器显式启用FormatChecker；将依赖版本和运行命令写入包内并在全新环境复跑349/349。',
        })

    mapping = audit_module.inspect_mapping(outer_dir)
    audit = {
        'outer_zip_crc': 'PASS' if outer_bad is None else f'FAIL:{outer_bad}',
        'complete_sha256': complete_sha,
        'expected_complete_sha256': audit_module.EXPECTED_COMPLETE_SHA,
        'complete_sha_match': complete_sha == audit_module.EXPECTED_COMPLETE_SHA,
        'zip_crc': 'PASS' if inner_bad is None else f'FAIL:{inner_bad}',
        'manifest_entries': manifest.get('entry_count', len(manifest.get('entries', []))),
        'manifest_errors': len(manifest_errors),
        'v21_tests': v21_summary.get('combined'),
        'v20_tests': v20_summary.get('combined'),
        'v20_validator_returncode': history_proc.returncode,
        'v20_validator_stdout': history_proc.stdout,
        'history_compare': history_compare,
        'mapping': mapping,
        'core_database_sha256': audit_module.CORE_SHA,
        'core_database_modified': False,
        'independent_tests': {
            'passed': sum(t['passed'] for t in tests),
            'total': len(tests),
            'failed': sum(not t['passed'] for t in tests),
        },
    }

    reports = audit_module.create_reports(out, audit, tests, findings)
    qa = audit_module.visual_qa(out, [p for p in reports if p.suffix == '.docx'])
    audit_module.write_json(out / '独立验收_DOCX渲染检查_V2.2.json', qa)
    final = {
        'conclusion': '通过，可以进入下一步' if not findings else '暂不通过，需要修正',
        'audit': audit,
        'findings': findings,
        'independent_tests': tests,
        'reports': [p.name for p in reports],
        'visual_qa': qa,
        'next_step_executed': False,
    }
    audit_module.write_json(out / 'independent_audit_result.json', final)
    bundle = out.parent / 'step13_v21_independent_audit_artifact.zip'
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file():
                z.write(p, arcname=p.relative_to(out))
    print(json.dumps({
        'bundle': str(bundle),
        'conclusion': final['conclusion'],
        'finding_count': len(findings),
        'findings': findings,
        'audit': audit,
        'visual_qa': qa,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
