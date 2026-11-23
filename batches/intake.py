from collections.abc import Sequence
from dataclasses import dataclass

from batches.reading import FrozenReading, parse_litres
from batches.source import require_label, validate_source


@dataclass(frozen=True, slots=True)
class BatchSubmission:
    submission_id: str
    readings: Sequence[FrozenReading]


def validate_submission(submission: BatchSubmission) -> tuple[FrozenReading, ...]:
    if not isinstance(submission, BatchSubmission):
        raise ValueError('expected a BatchSubmission')
    require_label(submission.submission_id, 'submission_id')
    if not isinstance(submission.readings, Sequence) or not submission.readings:
        raise ValueError('submission requires a nonempty sequence of readings')

    frozen = []
    for position, reading in enumerate(submission.readings):
        if not isinstance(reading, FrozenReading):
            raise ValueError(f'reading {position} must be a FrozenReading')
        if type(reading.position) is not int or reading.position != position:
            raise ValueError(f'expected original position {position}, got {reading.position!r}')
        litres = parse_litres(reading.litres)
        source = validate_source(reading.source)
        frozen.append(FrozenReading(position, litres, source))
    return tuple(frozen)
