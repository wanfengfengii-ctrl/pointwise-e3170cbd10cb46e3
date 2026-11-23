"""Named offline handoff of a claimed frozen batch and detached offline signing."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from batches.reading import FrozenReading
from batches.source import SourceRef, require_label
from claims.transfer import get_batch_transfer, get_transfer, record_transfer
from delivery.receipts import PageReceipt, build_receipt, recover_publication
from delivery.rows import DeliveredRow
from delivery.store import DeliveryStore, HandoffRequest
from pages.request import PageRequest
from pages.store import CandidatePage, CandidateStore


@dataclass(frozen=True, slots=True)
class HandoffReceipt:
    handoff_id: str
    batch_id: str
    request_ids: tuple[str, ...]


def _validate_request_ids(request_ids: object) -> tuple[str, ...]:
    if isinstance(request_ids, (str, bytes)) or not isinstance(request_ids, Sequence):
        raise ValueError('request_ids must be a sequence of candidate request ids')
    if not request_ids:
        raise ValueError('request_ids must be a nonempty sequence')
    ids = []
    for request_id in request_ids:
        require_label(request_id, 'request_id')
        ids.append(request_id)
    if len(set(ids)) != len(ids):
        raise ValueError('request_ids must not contain duplicates')
    return tuple(sorted(ids))


def _material_to_json(material: tuple[HandoffRequest, ...]) -> str:
    payload = [
        {
            'request_id': request.request_id,
            'claim_id': request.claim_id,
            'group_id': request.group_id,
            'start': request.start,
            'stop': request.stop,
            'rows': [
                [reading.position, reading.litres, reading.source.station, reading.source.document, reading.source.line]
                for reading in request.rows
            ],
        }
        for request in material
    ]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _material_from_json(text: str) -> tuple[HandoffRequest, ...]:
    return tuple(
        HandoffRequest(
            entry['request_id'],
            entry['claim_id'],
            entry['group_id'],
            entry['start'],
            entry['stop'],
            tuple(
                FrozenReading(position, litres, SourceRef(station, document, line))
                for position, litres, station, document, line in entry['rows']
            ),
        )
        for entry in json.loads(text)
    )


def _adjudicate(
    candidates: CandidateStore,
    deliveries: DeliveryStore,
    batch_id: str,
    ids: tuple[str, ...],
    catalogue: sqlite3.Connection,
) -> tuple[HandoffRequest, ...]:
    """Freeze the checkpoint: formal deliveries, claim spans and listed candidates at once."""
    claims = candidates.claims
    batch = claims.batches.get_batch(batch_id, db=catalogue)
    if batch is None:
        raise ValueError(f'unknown batch {batch_id!r}')
    pages = {}
    for request_id in ids:
        page = candidates.get_candidate(request_id, db=catalogue)
        if page is None:
            raise ValueError(f'unknown candidate {request_id!r}')
        if page.batch_id != batch_id:
            raise ValueError(f'candidate {request_id!r} belongs to another batch')
        pages[request_id] = page

    occupied = {row.position for row in deliveries.get_committed_rows(batch_id)}
    material = []
    covered = set()
    for request_id in ids:
        page = pages[request_id]
        claim = claims.get_claim(page.request.claim_id, db=catalogue)
        if claim is None or claim.batch_id != batch_id:
            raise RuntimeError('candidate has no matching claim for this batch')
        rows: tuple[FrozenReading, ...] = ()
        if deliveries.get_publication_record(request_id) is None:
            eligible = tuple(
                position
                for position in page.positions
                if claim.span.contains(position) and position not in occupied
            )
            rows = tuple(batch.rows[position] for position in eligible)
            covered.update(eligible)
        material.append(
            HandoffRequest(request_id, claim.claim_id, claim.group_id, page.request.start, page.request.stop, rows)
        )

    missing = [
        reading.position
        for reading in batch.rows
        if reading.position not in occupied and reading.position not in covered
    ]
    if missing:
        raise ValueError(f'handoff list leaves undelivered original positions uncovered: {missing!r}')
    return tuple(material)


def _take_effect(
    deliveries: DeliveryStore, handoff_id: str, batch_id: str, material: tuple[HandoffRequest, ...]
) -> bool:
    with deliveries.transaction() as ledger:
        if deliveries.get_handoff(handoff_id, db=ledger) is not None:
            return False
        deliveries.write_handoff(handoff_id, batch_id, material, db=ledger)
        return True


def handoff(
    candidates: CandidateStore,
    deliveries: DeliveryStore,
    handoff_id: str,
    batch_id: str,
    request_ids: Sequence[str],
    *,
    before_decision: Callable[[], None] | None = None,
    after_checkpoint: Callable[[], None] | None = None,
) -> HandoffReceipt:
    require_label(handoff_id, 'handoff_id')
    require_label(batch_id, 'batch_id')
    ids = _validate_request_ids(request_ids)
    if before_decision is not None:
        before_decision()

    # An effective handoff can be re-claimed from the delivery store alone,
    # even after the working catalogue has been retired.
    effective = deliveries.get_handoff(handoff_id)
    if effective is not None:
        if effective != (batch_id, ids):
            raise ValueError('handoff_id already bound to other parameters')
        return HandoffReceipt(handoff_id, batch_id, ids)
    if deliveries.get_batch_handoff(batch_id) is not None:
        raise ValueError('batch already transferred under another handoff_id')

    claims = candidates.claims
    transferred = False
    with claims.transaction() as catalogue:
        existing = get_transfer(catalogue, handoff_id)
        if existing is not None:
            stored_batch, stored_ids, stored_material = existing
            if stored_batch != batch_id or stored_ids != ids:
                raise ValueError('handoff_id already bound to other parameters')
            material = _material_from_json(stored_material)
        else:
            if get_batch_transfer(catalogue, batch_id) is not None:
                raise ValueError('batch already transferred under another handoff_id')
            material = _adjudicate(candidates, deliveries, batch_id, ids, catalogue)
            record_transfer(catalogue, handoff_id, batch_id, ids, _material_to_json(material))
            transferred = True
    if transferred and after_checkpoint is not None:
        after_checkpoint()

    effected = _take_effect(deliveries, handoff_id, batch_id, material)
    if effected and not transferred and after_checkpoint is not None:
        after_checkpoint()
    return HandoffReceipt(handoff_id, batch_id, ids)


def publish_offline(
    deliveries: DeliveryStore,
    handoff_id: str,
    request_id: str,
    *,
    before_commit: Callable[[], None] | None = None,
    after_commit: Callable[[], None] | None = None,
) -> PageReceipt | None:
    require_label(handoff_id, 'handoff_id')
    require_label(request_id, 'request_id')
    with deliveries.transaction() as ledger:
        effective = deliveries.get_handoff(handoff_id, db=ledger)
        if effective is None:
            raise ValueError(f'no effective handoff {handoff_id!r}')
        batch_id, _ = effective
        material = deliveries.get_handoff_request(handoff_id, request_id, db=ledger)
        if material is None:
            raise ValueError(f'request {request_id!r} is not listed in handoff {handoff_id!r}')

        page = CandidatePage(
            PageRequest(request_id, material.claim_id, material.start, material.stop),
            batch_id,
            tuple(reading.position for reading in material.rows),
        )
        found, prior = recover_publication(deliveries, page, db=ledger)
        if found:
            return prior

        occupied = {row.position for row in deliveries.get_committed_rows(batch_id, db=ledger)}
        rows = tuple(
            DeliveredRow(batch_id, material.claim_id, material.group_id, reading)
            for reading in material.rows
            if reading.position not in occupied
        )
        receipt = build_receipt(request_id, rows) if rows else None
        deliveries.write_delivery(page, receipt, db=ledger)
        if before_commit is not None:
            before_commit()

    if after_commit is not None:
        after_commit()
    return receipt
