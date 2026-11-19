"""Response shapes of the LUN endpoints we use. Unknown extra fields are allowed; missing or retyped ones are not.

Only the fields the dashboard reads are declared: a change there must fail loudly (alert), anything else may come
and go. Numbers sometimes arrive as strings ("2379536"); pydantic's lax mode turns them into floats.
"""
import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, create_model

Num = float | None


class _Model(BaseModel):
    model_config = ConfigDict(extra='allow')


# --- flat-price-history (normalized into flat_price_point) ---------------------------------------------------

class FlatPricePoint(_Model):
    cityId: int
    contractType: int
    roomCount: int
    medianUah: Num
    medianUsd: Num
    medianM2Uah: Num
    medianM2Usd: Num
    count: int | None
    date: dt.date
    isToday: bool


class FlatPriceHistoryResponse(_Model):
    status: Literal['success']
    data: list[FlatPricePoint]


# --- price: primary market (new buildings), average m² price by housing class ---------------------------------

class PriceItem(_Model):
    cityId: int
    averageUah: Num
    averageUsd: Num
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


# --- secondary market and rent -------------------------------------------------------------------------------

class MedianExposure(_Model):
    """Median days on the market; roomCount None = all room counts."""
    cityId: int
    contractType: int
    roomCount: int | None
    dateStr: dt.date
    isToday: bool
    exposure: Num
    count: int | None


class MarketDistrict(_Model):
    """Latest medians by city district, in UAH (usdToUah converts). medianM2Total: per m² of total area.

    Two shapes: most cities send renovated / not renovated splits and usdToUah; some (Ivano-Frankivsk: ~150
    micro-districts) send only median, medianM2 and their USD values. Hence the optional fields."""
    cityId: int
    districtId: int
    districtName: str | None
    districtNameEng: str | None = None
    contractTypeId: int
    roomCount: int
    median: Num
    medianUsd: Num = None
    medianM2: Num = None
    medianM2Usd: Num = None
    medianRenovated: Num = None
    medianNotRenovated: Num = None
    medianM2Total: Num = None
    medianM2TotalRenovated: Num = None
    medianM2TotalNotRenovated: Num = None
    count: int | None
    countRenovated: int | None = None
    countNotRenovated: int | None = None
    usdToUah: Num = None
    date: dt.datetime


class PriceBucket(_Model):
    """Histogram of listing prices. currencyId: 1 = USD, 2 = UAH."""
    contractTypeId: int
    roomCount: int
    currencyId: int
    priceStart: float
    priceEnd: Num  # None: the open last bucket ("and more")
    count: int
    date: dt.datetime


class RieltorPoint(_Model):
    """Listing price vs deal price reported by realtors."""
    cityId: int
    contractType: int
    roomCount: int
    dateStr: dt.date
    isToday: bool
    price: Num
    dealPrice: Num
    priceUsd: Num
    dealPriceUsd: Num
    priceM2: Num = None
    dealPriceM2: Num = None
    priceUsdM2: Num = None
    dealPriceUsdM2: Num = None


# --- affordability -------------------------------------------------------------------------------------------

class SalaryPoint(_Model):
    """Sale: price in years of the median salary. Rent: rent as % of the median salary."""
    cityId: int
    contractTypeId: int
    roomCount: int
    date: dt.datetime
    isToday: bool
    value: Num
    price: Num
    salary: Num
    count: int | None = None


class SalaryPosition(_Model):
    cityId: int
    contractTypeId: int
    roomCount: int
    date: dt.datetime
    nameUa: str
    nameEn: str | None = None
    value: Num
    salary: Num
    price: Num = None
    url: str | None = None


class SaleInRentPoint(_Model):
    """Flat price in years of rent."""
    cityId: int
    roomCount: int
    date: dt.date
    isToday: bool
    value: Num


class PetsRent(_Model):
    cityId: int
    contractTypeId: int
    realtyType: str
    regionType: str
    count: int | None
    date: dt.datetime | None = None
    yesPercent: Num
    somePercent: Num
    noPercent: Num
    unknownPercent: Num


# --- houses --------------------------------------------------------------------------------------------------

class HousePricePoint(_Model):
    """regionType: city or region (oblast)."""
    cityId: int
    contractTypeId: int
    regionType: str
    date: dt.date
    isToday: bool
    medianUah: Num
    medianUsd: Num
    medianM2Uah: Num
    medianM2Usd: Num
    area: Num
    count: int | None


class DistrictHousePrice(_Model):
    cityId: int
    districtId: int
    nameUk: str
    nameEn: str | None = None
    contractTypeId: int
    date: dt.datetime
    medianUsd: Num
    medianM2Usd: Num
    area: Num
    count: int | None


# --- new buildings -------------------------------------------------------------------------------------------

class Label(_Model):
    uk: str
    en: str | None = None


class AverageByDistrict(_Model):
    """districts (start price per m² of new buildings) and parking-districts (parking space price)."""
    cityId: int
    key: int
    label: Label | str  # usually {"uk", "en"}; plain text for some rows (Kyiv)
    averageUah: Num
    averageUsd: Num
    count: int | None
    month: dt.datetime
    isCity: bool = False  # Kyiv's new-building answer: a town next to the city, not a district


class ParkingClass(_Model):
    """classId: 1 economy, 4 comfort, 2 business, 3 premium (checked against lun.ua/stat/primary)."""
    classId: int
    regionType: str
    date: dt.datetime
    count: int | None
    medianUah: Num
    medianUsd: Num


class DeveloperRank(_Model):
    cityId: int
    year: int
    place: str  # "1", or shared places like "9-10"
    name: str
    count: int


class DeveloperShare(_Model):
    cityId: int
    year: int
    name: str
    value: float  # % of the flats delivered that year


class Commissioning(_Model):
    """dssu: housing put into service, m² per quarter (State Statistics). regionId = LUN cityId of the region's
    center (the oblast), 10000 = Ukraine."""
    year: int
    quarter: int
    regionId: int
    allBuildings: Num
    apartmentBuildings: Num


class CityRegionCounts(_Model):
    """lending and sections: counts for the city and its oblast, keys vary (missing = 0)."""
    city: dict[str, int]
    region: dict[str, int]


def list_response(name: str, item: type[BaseModel]) -> type[BaseModel]:
    return create_model(name, __base__=_Model, status=(Literal['success'], ...), data=(list[item], ...))


def by_city_response(name: str) -> type[BaseModel]:
    """Global endpoints keyed by LUN cityId: {"1": {...}, "115": {...}}."""
    return create_model(name, __base__=_Model, status=(Literal['success'], ...),
                        data=(dict[int, CityRegionCounts], ...))
