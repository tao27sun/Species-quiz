from dataclasses import dataclass


@dataclass(frozen=True)
class PlantImage:
    cell: str
    data: bytes
    mime_type: str


@dataclass(frozen=True)
class PlantQuestion:
    row_number: int
    name: str
    images: list[PlantImage]
