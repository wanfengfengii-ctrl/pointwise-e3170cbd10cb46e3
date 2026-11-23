from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceRef:
    station: str
    document: str
    line: int


def require_label(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a nonblank string')


def validate_source(source: SourceRef) -> SourceRef:
    if not isinstance(source, SourceRef):
        raise ValueError('every reading requires a SourceRef')
    require_label(source.station, 'station')
    require_label(source.document, 'document')
    if type(source.line) is not int or source.line < 1:
        raise ValueError('source line must be a positive integer')
    return source
