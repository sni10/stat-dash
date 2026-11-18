"""Response shapes of the LUN endpoints we use. Unknown extra fields are allowed; missing or retyped ones are not."""
import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra='allow')


class FlatPricePoint(_Model):
    cityId: int
    contractType: int
    roomCount: int
    medianUah: float | None
    medianUsd: float | None
    medianM2Uah: float | None
    medianM2Usd: float | None
    count: int | None
    date: dt.date
    isToday: bool


class FlatPriceHistoryResponse(_Model):
    status: Literal['success']
    data: list[FlatPricePoint]


class PriceItem(_Model):
    cityId: int
    averageUah: float | None
    averageUsd: float | None
    label: str | None
    count: int | None
    monthDate: dt.date
    isToday: bool


class PriceData(_Model):
    cityClasses: list[PriceItem]
    regionClasses: list[PriceItem]
    cityAvg: list[PriceItem]
    regionAvg: list[PriceItem]


class PriceResponse(_Model):
    status: Literal['success']
    data: PriceData
