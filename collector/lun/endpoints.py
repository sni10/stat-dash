"""Every LUN endpoint we collect, as found on lun.ua/stat/{sale,rent,primary}/<city> (19.11.2026).

Raw answers go to lun_raw (deduplicated by hash), the archive; collector/parsers.py turns every answer into rows of
the entity tables (docs/data-model.md), which the dashboard reads.
"""
from dataclasses import dataclass

from pydantic import BaseModel

from . import schemas as s


@dataclass(frozen=True)
class Endpoint:
    name: str
    schema: type[BaseModel]
    per_city: bool = True  # False: one request for all cities (the answer covers every region)
    contract_types: tuple[int, ...] = ()  # one request per contractTypeId; () -> no such parameter

    def params(self, city_id: int | None) -> list[dict]:
        base = {'cityId': city_id} if self.per_city else {}
        if not self.contract_types:
            return [base]
        return [{**base, 'contractTypeId': ct} for ct in self.contract_types]


FLAT_PRICE_HISTORY = 'flat-price-history'
SALE_RENT = (1, 2)

ENDPOINTS: dict[str, Endpoint] = {e.name: e for e in [
    Endpoint(FLAT_PRICE_HISTORY, s.FlatPriceHistoryResponse, contract_types=SALE_RENT),
    Endpoint('price', s.PriceResponse),
    Endpoint('median-exposure', s.list_response('MedianExposureResponse', s.MedianExposure)),
    Endpoint('market-districts', s.list_response('MarketDistrictsResponse', s.MarketDistrict)),
    Endpoint('price-distribution', s.list_response('PriceDistributionResponse', s.PriceBucket)),
    Endpoint('rieltor', s.list_response('RieltorResponse', s.RieltorPoint)),
    Endpoint('salary-history', s.list_response('SalaryHistoryResponse', s.SalaryPoint)),
    Endpoint('salary-positions', s.list_response('SalaryPositionsResponse', s.SalaryPosition)),
    Endpoint('sale-in-rent-history', s.list_response('SaleInRentResponse', s.SaleInRentPoint)),
    Endpoint('houses-price-history', s.list_response('HousesPriceHistoryResponse', s.HousePricePoint),
             contract_types=SALE_RENT),
    Endpoint('districts-house-price', s.list_response('DistrictsHousePriceResponse', s.DistrictHousePrice)),
    Endpoint('districts', s.list_response('PrimaryDistrictsResponse', s.AverageByDistrict)),
    Endpoint('parking-districts', s.list_response('ParkingDistrictsResponse', s.AverageByDistrict)),
    Endpoint('parking-classes', s.list_response('ParkingClassesResponse', s.ParkingClass)),
    Endpoint('developers-ranking', s.list_response('DevelopersRankingResponse', s.DeveloperRank)),
    Endpoint('developers-distribution', s.list_response('DevelopersDistributionResponse', s.DeveloperShare)),
    Endpoint('dssu', s.list_response('DssuResponse', s.Commissioning), per_city=False),
    Endpoint('lending', s.by_city_response('LendingResponse'), per_city=False),
    Endpoint('sections', s.by_city_response('SectionsResponse'), per_city=False),
    Endpoint('pets-rent', s.list_response('PetsRentResponse', s.PetsRent), per_city=False),
]}
