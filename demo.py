import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from batches.freeze import freeze
from batches.intake import BatchSubmission
from batches.reading import FrozenReading
from batches.source import SourceRef
from batches.store import BatchStore
from claims.assign import assign
from claims.receipt import SplitRequest
from claims.split import split
from claims.store import ClaimStore
from delivery.publish import publish
from delivery.receipts import get_page
from delivery.store import DeliveryStore
from pages.build import prepare
from pages.request import PageRequest
from pages.store import CandidateStore
from reconcile.report import audit


def _submission(sample):
    return BatchSubmission(sample['submission_id'], tuple(
        FrozenReading(
            entry['position'], entry['litres'], SourceRef(sample['station'], sample['document'], entry['line'])
        )
        for entry in sample['readings']
    ))


def _detail(rows):
    return [[row.position, row.litres, row.group_id, row.source.line] for row in rows]


def _balance(report):
    return {
        'rows': _detail(report.delivered),
        'undelivered': list(report.undelivered_positions),
        'groups': {group: asdict(totals) for group, totals in report.groups},
        'total': asdict(report.total),
    }


def _emit(case_id, inputs, expected, actual, downstream_expected, downstream_actual, code_paths, oracle):
    if actual != expected:
        raise AssertionError(f'{case_id} receipt rows differ: {actual!r}')
    if downstream_actual != downstream_expected:
        raise AssertionError(f'{case_id} batch report differs: {downstream_actual!r}')
    evidence = {
        'case_id': case_id,
        'input': inputs,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': code_paths,
        'oracle': oracle,
    }
    print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False, sort_keys=True))


def _handoff(sample, batches, claims, candidates, deliveries):
    batch_id = freeze(batches, _submission(sample))
    day = assign(claims, batch_id, 'day')
    parent = prepare(candidates, PageRequest('day-page', day.claim_id, 0, 3))
    moved = split(claims, deliveries, SplitRequest('shift-change', day.claim_id, 1, 'night'))
    tail = prepare(candidates, PageRequest('night-page', moved.successor.claim_id, 1, 3))
    night_signed = publish(candidates, deliveries, tail)
    day_signed = publish(candidates, deliveries, parent)
    receipts = [get_page(deliveries, signed.receipt_id) for signed in (day_signed, night_signed)]
    expected = {'day': [[0, 7, 'day', 41]], 'night': [[1, 11, 'night', 42], [2, 13, 'night', 43]]}
    downstream = {
        'rows': [[0, 7, 'day', 41], [1, 11, 'night', 42], [2, 13, 'night', 43]],
        'undelivered': [],
        'groups': {
            'day': {'delivered_count': 1, 'missing_count': 0, 'litres': 7},
            'night': {'delivered_count': 2, 'missing_count': 0, 'litres': 24},
        },
        'total': {'delivered_count': 3, 'missing_count': 0, 'litres': 31},
    }
    _emit(
        'v5', {'station_batch': sample, 'boundary': 1, 'publication_order': ['night', 'day']},
        expected, {receipt.group_id: _detail(receipt.rows) for receipt in receipts},
        downstream, _balance(audit(batches, deliveries, batch_id)),
        ['claims/split.py', 'delivery/publish.py', 'delivery/receipts.py', 'reconcile/report.py'],
        '按原位手算，分界 1 留下 7 L，尾段 11 + 13 = 24 L，全批 31 L。',
    )


def _coverage(sample, batches, claims, candidates, deliveries):
    batch_id = freeze(batches, _submission(sample))
    day = assign(claims, batch_id, 'day')
    upper = prepare(candidates, PageRequest('coverage-upper', day.claim_id, 2, 4))
    lower = prepare(candidates, PageRequest('coverage-lower', day.claim_id, 0, 2))
    first = publish(candidates, deliveries, upper)
    second = publish(candidates, deliveries, lower)
    expected = [[2, 7, 'day', 93], [3, 0, 'day', 94], [0, 7, 'day', 91], [1, None, 'day', 92]]
    downstream = {
        'rows': [[0, 7, 'day', 91], [1, None, 'day', 92], [2, 7, 'day', 93], [3, 0, 'day', 94]],
        'undelivered': [4],
        'groups': {'day': {'delivered_count': 4, 'missing_count': 1, 'litres': 14}},
        'total': {'delivered_count': 4, 'missing_count': 1, 'litres': 14},
    }
    _emit(
        'v8', {'station_batch': sample, 'publication_order': [[2, 4], [0, 2]]},
        expected, _detail(first.rows + second.rows),
        downstream, _balance(audit(batches, deliveries, batch_id)),
        ['delivery/history.py', 'reconcile/coverage.py', 'reconcile/provenance.py', 'reconcile/totals.py', 'reconcile/report.py'],
        '实交原位 0 到 3，7 + 7 + 0 = 14 L。原位 1 缺测已交，原位 4 未交。',
    )


def main():
    path = Path(__file__).resolve().parent / 'samples' / 'day_batches.json'
    samples = json.loads(path.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='qinglan-demo-') as directory:
        root = Path(directory)
        batches = BatchStore(root / 'catalogue.sqlite3')
        claims = ClaimStore(batches)
        candidates = CandidateStore(claims)
        deliveries = DeliveryStore(root / 'delivery.sqlite3')
        for store in (batches, claims, candidates, deliveries):
            store.initialize()
        _handoff(samples['handoff'], batches, claims, candidates, deliveries)
        _coverage(samples['coverage'], batches, claims, candidates, deliveries)


if __name__ == '__main__':
    main()
