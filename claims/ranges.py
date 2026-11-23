from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClaimRange:
    start: int
    stop: int

    def __post_init__(self) -> None:
        if type(self.start) is not int or type(self.stop) is not int:
            raise ValueError('range bounds must be integers')
        if self.start < 0 or self.stop < self.start:
            raise ValueError('invalid half-open range')

    def contains(self, position: int) -> bool:
        return self.start <= position < self.stop

    def covers(self, span: 'ClaimRange') -> bool:
        return self.start <= span.start <= span.stop <= self.stop


def partition_range(span: ClaimRange, boundary: int) -> tuple[ClaimRange, ClaimRange]:
    if type(boundary) is not int or not span.contains(boundary):
        raise ValueError('split boundary must be in the original claim range')
    return ClaimRange(span.start, boundary), ClaimRange(boundary, span.stop)


def positions_in_range(span: ClaimRange) -> range:
    return range(span.start, span.stop)
