import datetime as dt
import io
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase, override_settings

from collector import models as m
from collector.service import collect

from .factories import FakeClient, _ok, all_answers, median_exposure

NO_PAUSE = {'BASE_URL': 'http://lun.test/', 'PAUSE': (0, 0)}
SNAP = dt.date(2026, 1, 10)  # TODAY_ISO of the factories


def run(data=None):
    with override_settings(LUN=NO_PAUSE):
        result = collect([m.City.objects.get(slug='odesa')], client=FakeClient({**all_answers(), **(data or {})}),
                         sleep=lambda _: None, alert=lambda _: None)
    assert result.status == m.CollectRun.Status.OK, result.error
    return result


def counts():
    return {model.__name__: model.objects.count() for model in m.ENTITIES}


class ParsersTests(TestCase):
    """Every endpoint of the synthetic answers (factories.all_answers) lands in its table."""

    def setUp(self):
        self.odesa = m.City.objects.get(slug='odesa')
        run()

    def test_every_table_is_filled(self):
        self.assertEqual(counts(), {
            'District': 4, 'HousePricePoint': 24, 'ExposurePoint': 48, 'DealPricePoint': 48,
            'AffordabilityPoint': 36, 'RentPaybackPoint': 18, 'PrimaryClassPrice': 5, 'HousingCommissioning': 16,
            'DistrictPrice': 24, 'DistrictAveragePrice': 8, 'HouseDistrictPrice': 4, 'PriceBucket': 45,
            'ProfessionAffordability': 18, 'ParkingClassPrice': 8, 'DeveloperRank': 6, 'DeveloperShare': 6,
            'ConstructionStat': 4, 'LendingStat': 4, 'PetsRentShare': 1,
        })

    def test_rerun_is_idempotent(self):
        before = counts()
        run()
        self.assertEqual(counts(), before)

    def test_series_values_and_all_rooms_as_0(self):
        point = m.ExposurePoint.objects.get(city=self.odesa, contract_type=2, room_count=0, date=dt.date(2025, 12, 24))
        self.assertEqual(point.days, 35)
        deal = m.DealPricePoint.objects.get(city=self.odesa, contract_type=1, room_count=3, date=dt.date(2025, 12, 24))
        self.assertEqual((deal.listing_usd, deal.deal_usd), (Decimal('120000.00'), Decimal('108000.00')))
        house = m.HousePricePoint.objects.get(city=self.odesa, contract_type=2, scope='region', date=dt.date(2025, 12, 24))
        self.assertEqual(house.median_usd, Decimal('50000.00'))

    def test_today_point_of_a_series_is_replaced(self):
        def with_today(day):
            data = median_exposure()
            data['data'].append({'cityId': 115, 'dateStr': day, 'isToday': True, 'contractType': 1, 'roomCount': None,
                                 'exposure': 70, 'count': 1})
            return {('median-exposure', None): data}

        run(with_today('2026-01-10'))
        run(with_today('2026-01-17'))
        today = m.ExposurePoint.objects.filter(city=self.odesa, is_today=True)
        self.assertEqual(list(today.values_list('date', flat=True)), [dt.date(2026, 1, 17)])

    def test_districts_dimension(self):
        names = dict(m.District.objects.filter(city=self.odesa).values_list('lun_id', 'name_uk'))
        self.assertEqual(names, {11: 'Київський', 12: 'Хаджибейський', 13: 'Приморський', 14: 'Пересипський'})
        price = m.DistrictPrice.objects.get(district__lun_id=14, contract_type=1, room_count=2, snap_date=SNAP)
        self.assertEqual(price.median_uah, Decimal(4 * 10000 * 2 * 40))
        self.assertEqual(price.usd_to_uah, Decimal('40.0000'))
        self.assertEqual(m.DistrictAveragePrice.objects.filter(item='parking').count(), 4)

    def test_microdistricts_get_their_own_kind(self):
        rows = [{'cityId': 115, 'districtId': 10027077, 'districtName': 'Будівельників', 'contractTypeId': 2,
                 'roomCount': 1, 'median': '100', 'medianUsd': '2.5', 'count': 1, 'date': '2026-01-10T00:00:00.000Z'}]
        run({('market-districts', None): _ok(rows)})
        district = m.District.objects.get(lun_id=10027077)
        self.assertEqual(district.kind, m.District.Kind.MICRODISTRICT)
        self.assertEqual(m.DistrictPrice.objects.get(district=district).median_usd, Decimal('2.50'))

    def test_snapshots_build_history_by_date(self):
        later = all_answers()
        for row in later[('price-distribution', None)]['data']:
            row['date'] = '2026-01-17T00:00:00.000Z'
        run({('price-distribution', None): later[('price-distribution', None)]})
        self.assertEqual(sorted(set(m.PriceBucket.objects.values_list('snap_date', flat=True))),
                         [SNAP, dt.date(2026, 1, 17)])
        self.assertEqual(m.PriceBucket.objects.count(), 90)

    def test_open_bucket_and_currency(self):
        last = m.PriceBucket.objects.filter(contract_type=2, currency='uah', room_count=1).order_by('price_from').last()
        self.assertIsNone(last.price_to)
        self.assertEqual(set(m.PriceBucket.objects.values_list('currency', flat=True)), {'usd', 'uah'})

    def test_global_endpoints(self):
        self.assertEqual(set(m.HousingCommissioning.objects.values_list('region_id', flat=True)), {115, 10000})
        build = m.ConstructionStat.objects.get(city=self.odesa, scope='region')
        self.assertEqual((build.on_sale, build.built), (440, 1792))
        lending = m.LendingStat.objects.get(city=self.odesa, scope='city')
        self.assertEqual((lending.installments, lending.mortgages, lending.credits), (37, 7, 1))
        self.assertEqual(m.PetsRentShare.objects.get().city_id, 1)  # Kyiv only in the fake answer

    def test_classes_and_developers(self):
        self.assertEqual(set(m.PrimaryClassPrice.objects.values_list('housing_class', flat=True)),
                         {'comfort', 'business', 'all'})
        self.assertEqual(dict(m.ParkingClassPrice.objects.filter(scope='city').values_list('housing_class', 'median_usd')),
                         {'economy': Decimal('15000.00'), 'business': Decimal('30000.00'),
                          'premium': Decimal('45000.00'), 'comfort': Decimal('60000.00')})
        self.assertEqual(m.DeveloperRank.objects.get(year=2025, place='1').flats, 1000)
        self.assertEqual(m.DeveloperShare.objects.get(year=2025, name='Dev 1').share_pct, 30.0)


class AdminTests(TestCase):
    def test_every_entity_has_a_read_only_changelist(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        run()
        self.client.force_login(get_user_model().objects.create_superuser('admin', password='pw'))
        for model in m.ENTITIES:
            with self.subTest(model=model.__name__):
                url = reverse(f'admin:collector_{model._meta.model_name}_changelist')
                self.assertEqual(self.client.get(url).status_code, 200)
                self.assertEqual(self.client.get(url + '?q=x').status_code, 200)


class ReparseTests(TestCase):
    def test_rebuilds_the_tables_from_the_archive(self):
        run()
        before = counts()
        for model in reversed(m.ENTITIES):
            model.objects.all().delete()
        out = io.StringIO()
        call_command('reparse_lun', stdout=out, stderr=io.StringIO())
        self.assertEqual(counts(), before)
        self.assertIn('market-districts', out.getvalue())

    def test_filters(self):
        run()
        m.ExposurePoint.objects.all().delete()
        call_command('reparse_lun', '--endpoint', 'median-exposure', '--city', 'odesa', stdout=io.StringIO())
        self.assertEqual(m.ExposurePoint.objects.count(), 48)
