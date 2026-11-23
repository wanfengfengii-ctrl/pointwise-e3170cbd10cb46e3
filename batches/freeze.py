from batches.intake import BatchSubmission, validate_submission
from batches.store import BatchStore, FrozenBatch


def freeze(store: BatchStore, submission: BatchSubmission) -> str:
    rows = validate_submission(submission)
    batch = FrozenBatch(f'batch:{submission.submission_id}', submission.submission_id, rows)
    return store.insert_batch(batch)
