from pages.request import PageRequest
from pages.select import select_candidate_rows
from pages.store import CandidatePage, CandidateStore


def prepare(store: CandidateStore, request: PageRequest) -> CandidatePage:
    with store.claims.transaction() as db:
        previous = store.get_candidate(request.request_id, db=db)
        if previous is not None:
            if previous.request.fingerprint() != request.fingerprint():
                raise ValueError('page request_id already bound to other parameters')
            return previous

        batch_id, readings = select_candidate_rows(store.claims, request, db=db)
        page = CandidatePage(request, batch_id, tuple(reading.position for reading in readings))
        store.save_candidate(page, db=db)
        return page
