from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _copy_file(src: Path, dst: Path, purpose: str, manifest_entries: List[Dict[str, Any]]) -> None:
    if not src.exists() or not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    manifest_entries.append({
        'source_path': str(src.resolve()),
        'imported_path': str(dst.resolve()),
        'kind': 'file',
        'purpose': purpose,
        'checksum_sha256': _sha256(dst),
        'imported_at': datetime.now().isoformat(),
    })


def _copy_dir(src: Path, dst: Path, purpose: str, manifest_entries: List[Dict[str, Any]]) -> None:
    if not src.exists() or not src.is_dir():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    manifest_entries.append({
        'source_path': str(src.resolve()),
        'imported_path': str(dst.resolve()),
        'kind': 'directory',
        'purpose': purpose,
        'checksum_sha256': '',
        'imported_at': datetime.now().isoformat(),
    })


def import_legacy_outputs(
    project_root: str,
    run_id: str,
    step1_dir: str | None = None,
    step2_dir: str | None = None,
    step3_dir: str | None = None,
) -> Dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    workspace_root = root / 'data' / 'workspaces_v2' / run_id / 'imports'
    manifest_entries: List[Dict[str, Any]] = []

    if step1_dir:
        src = Path(step1_dir).expanduser().resolve()
        dst = workspace_root / 'step1'
        _copy_file(src / 'chapter_index.json', dst / 'chapter_index.json', 'legacy_step1_chapter_index', manifest_entries)
        _copy_file(src / 'table_regions.json', dst / 'table_regions.json', 'legacy_step1_table_regions', manifest_entries)
        _copy_dir(src / 'chapter_regions', dst / 'chapter_regions', 'legacy_step1_chapter_regions', manifest_entries)

    if step2_dir:
        src = Path(step2_dir).expanduser().resolve()
        dst = workspace_root / 'step2'
        _copy_file(src / 'component_matching_result.json', dst / 'component_matching_result.json', 'legacy_step2_component_matching', manifest_entries)
        _copy_file(src / 'synonym_library.json', dst / 'synonym_library.json', 'legacy_step2_synonym_library', manifest_entries)
        _copy_file(src / 'run_summary.json', dst / 'run_summary.json', 'legacy_step2_run_summary', manifest_entries)

    if step3_dir:
        src = Path(step3_dir).expanduser().resolve()
        dst = workspace_root / 'step3'
        _copy_file(src / 'project_component_feature_calc_matching_result.json', dst / 'project_component_feature_calc_matching_result.json', 'legacy_step3_formal_result', manifest_entries)
        _copy_file(src / 'local_rule_project_component_feature_calc_result.json', dst / 'local_rule_project_component_feature_calc_result.json', 'legacy_step3_local_rule_result', manifest_entries)
        _copy_file(src / 'run_summary.json', dst / 'run_summary.json', 'legacy_step3_run_summary', manifest_entries)

    manifest = {
        'project_root': str(root),
        'run_id': run_id,
        'workspace_root': str(workspace_root.resolve()),
        'generated_at': datetime.now().isoformat(),
        'entries': manifest_entries,
    }
    workspace_root.mkdir(parents=True, exist_ok=True)
    manifest_path = workspace_root / 'import_manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'manifest': manifest, 'manifest_path': str(manifest_path.resolve())}
