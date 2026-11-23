from __future__ import annotations

from dataclasses import dataclass

from batches.source import SourceRef


def parse_litres(value: object) -> int | None:
    if value is None or type(value) is int:
        return value
    raise ValueError('litres must be an integer or None')


@dataclass(frozen=True, slots=True)
class FrozenReading:
    position: int
    litres: int | None
    source: SourceRef

    def storage_values(self) -> tuple[int, str | None, str, str, str]:
        # SQLite INTEGER is fixed width. Hex text preserves Python integers exactly.
        litres = None if self.litres is None else hex(self.litres)
        return self.position, litres, self.source.station, self.source.document, hex(self.source.line)

    @classmethod
    def from_storage(
        cls, position: int, litres: str | None, station: str, document: str, line: str
    ) -> FrozenReading:
        return cls(
            position,
            None if litres is None else int(litres, 16),
            SourceRef(station, document, int(line, 16)),
        )
