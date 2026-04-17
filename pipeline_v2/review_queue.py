from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def build_step3_review_queue(rows: List[Dict[str, Any]], source_stage: str = 'step3') -> List[Dict[str, Any]]:
    queue: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        match_status = str(row.get('match_status', '')).strip()
        review_status = str(row.get('review_status', '')).strip()
        needs_review = match_status in {'candidate_only', 'unmatched', 'conflict'}
        needs_review = needs_review or (match_status == 'matched' and review_status in {'pending', 'rejected', 'needs_review'})
        if needs_review:
            queue.append({
                'record_id': row.get('record_id') or f'{source_stage}-{row.get("row_id") or idx}',
                'source_stage': source_stage,
                'row_id': row.get('row_id') or '',
                'quantity_component': row.get('quantity_component') or row.get('component_type') or '',
                'calculation_item_code': row.get('calculation_item_code') or '',
                'review_status': review_status or 'pending',
                'manual_notes': row.get('manual_notes') or '',
                'reviewed_at': row.get('reviewed_at') or '',
                'match_status': match_status,
            })
    return queue


def write_review_ledger(output_path: str, rows: List[Dict[str, Any]], source_stage: str = 'step3') -> Dict[str, Any]:
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'source_stage': source_stage,
        'generated_at': datetime.now().isoformat(),
        'total_rows': len(rows),
        'queued_rows': len(rows),
        'rows': rows,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def load_review_ledger(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding='utf-8'))
