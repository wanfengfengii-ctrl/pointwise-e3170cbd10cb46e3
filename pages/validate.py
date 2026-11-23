from batches.reading import FrozenReading
from pages.request import PageRequest
from pages.store import CandidatePage, CandidateStore


def validate_candidate(store: CandidateStore, page: CandidatePage) -> tuple[FrozenReading, ...]:
    if not isinstance(page, CandidatePage) or not isinstance(page.request, PageRequest):
        raise ValueError('expected a prepared candidate page')
    stored = store.get_candidate(page.request.request_id)
    if stored != page or any(type(position) is not int for position in page.positions):
        raise ValueError('candidate differs from the prepared request')

    batch = store.claims.batches.get_batch(page.batch_id)
    if batch is None:
        raise RuntimeError('candidate has no frozen batch')
    readings = batch.rows[page.request.start:page.request.stop]
    if tuple(reading.position for reading in readings) != page.positions:
        raise ValueError('candidate does not reference its original ordered range')
    return readings
