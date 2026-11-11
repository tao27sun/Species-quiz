from dataclasses import dataclass


@dataclass(frozen=True)
class SpeciesImage:
    cell: str
    data: bytes
    mime_type: str


@dataclass(frozen=True)
class SpeciesQuestion:
    row_number: int
    name: str
    images: list[SpeciesImage]
