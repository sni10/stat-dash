import datetime as dt

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from collector.models import City, CollectRun, LunPriceSnapshot
from collector.service import collect
from collector.tests.factories import SALE, FakeClient, all_answers, answers, flat_price_history
from dashboard import charts, queries
from dashboard.templatetags.dash import money, num, pct

NO_PAUSE = {'BASE_URL': 'http://lun.test/', 'PAUSE': (0, 0)}

# Monthly points on the 24th of every month of 2025, "today" on 2026-01-10. m² = 1000 + month index,
# the same for every room count (as in LUN's data); the "today" point is 1099.


def load(data=None):
    """Collect every endpoint for Odesa from synthetic answers; `data` replaces the stage 1 ones (answers())."""
    with override_settings(LUN=NO_PAUSE):
        run = collect([City.objects.get(slug='odesa')], client=FakeClient({**all_answers(), **(data or {})}),
                      sleep=lambda _: None, alert=lambda _: None)
    assert run.status == CollectRun.Status.OK, run.error


class LoggedInTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('me', password='pw')
        self.client.force_login(self.user)


class QueriesTests(TestCase):
    def setUp(self):
        load()
        self.odesa = City.objects.get(slug='odesa')

    def test_overview_kpis_from_the_latest_point(self):
        kpi = queries.overview(queries.Filters(self.odesa))
        self.assertEqual(kpi['date'], dt.date(2026, 1, 10))
        self.assertTrue(kpi['preliminary'])
        self.assertEqual(kpi['price_m2'], 1099.0)
        self.assertEqual(kpi['month_ago'], dt.date(2025, 12, 24))
        self.assertAlmostEqual(kpi['m2_mom'], 1099 / 1011 - 1)
        self.assertEqual(kpi['year_ago'], dt.date(2025, 1, 24))
        self.assertAlmostEqual(kpi['m2_yoy'], 1099 / 1000 - 1)
        self.assertEqual(kpi['count'], 300)  # 1-3 rooms x 100 listings; 4+ rooms are not shown
        self.assertEqual(kpi['first_date'], dt.date(2025, 1, 24))

    def test_no_year_ago_point_within_tolerance(self):
        data = answers()
        data[SALE] = flat_price_history(115, 1, dates=[dt.date(2025, 12, 24)], today=dt.date(2026, 1, 10))
        LunPriceSnapshot.objects.all().delete()
        load(data)
        kpi = queries.overview(queries.Filters(self.odesa))
        self.assertIsNone(kpi['m2_yoy'])
        self.assertIsNone(kpi['year_ago'])

    def test_overview_without_data(self):
        self.assertIsNone(queries.overview(queries.Filters(City.objects.get(slug='kyiv'))))

    def test_rent_and_uah(self):
        kpi = queries.overview(queries.Filters(self.odesa, deal='rent', cur='uah'))
        self.assertEqual(kpi['price_m2'], (8.0 + 99) * 40)

    def test_parse_filters(self):
        f = queries.parse_filters({'city': 'odesa', 'deal': 'rent', 'cur': 'uah', 'rooms': '2,1',
                                   'from': '2025-03', 'to': '2025-06'})
        self.assertEqual((f.deal, f.cur, f.rooms), ('rent', 'uah', (1, 2)))
        self.assertEqual((f.date_from, f.date_to), (dt.date(2025, 3, 1), dt.date(2025, 6, 30)))
        self.assertEqual(queries.parse_filters({}).city.slug, 'odesa')

    def test_bad_filters(self):
        for params in ({'city': 'atlantis'}, {'deal': 'swap'}, {'cur': 'eur'}, {'rooms': 'x'}, {'rooms': '4'},
                       {'from': '2025-13'}, {'from': '2025-06', 'to': '2025-03'}):
            with self.subTest(params=params), self.assertRaises(queries.BadFilter):
                queries.parse_filters(params)


class ApiTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        load()

    def test_prices(self):
        response = self.client.get(reverse('api-prices'), {'city': 'odesa', 'rooms': '1', 'from': '2025-11'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual((data['city'], data['deal'], data['cur'], data['rooms']), ('odesa', 'sale', 'usd', [1]))
        self.assertEqual([p['date'] for p in data['points']], ['2025-11-24', '2025-12-24', '2026-01-10'])
        self.assertEqual(data['points'][-1], {'date': '2026-01-10', 'rooms': 1, 'price': 1099.0 * 45,
                                              'price_m2': 1099.0, 'count': 100, 'preliminary': True})

    def test_prices_rent_uah_all_rooms(self):
        data = self.client.get(reverse('api-prices'), {'deal': 'rent', 'cur': 'uah', 'to': '2025-01'}).json()
        self.assertEqual(len(data['points']), 3)  # no 4+ rooms
        self.assertEqual({p['price_m2'] for p in data['points']}, {8.0 * 40})

    def test_monthly_excludes_today(self):
        data = self.client.get(reverse('api-monthly'), {'rooms': '2'}).json()
        self.assertEqual(len(data['rows']), 12)
        self.assertEqual(data['rows'][-1], {'month': '2025-12', 'rooms': 2, 'w_avg_m2': 1011.0, 'med_m2': 1011.0,
                                            'w_avg_price': 1011.0 * 45 * 2, 'avg_count': 100.0})

    def test_bad_params_are_400(self):
        response = self.client.get(reverse('api-prices'), {'cur': 'eur'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('cur', response.json()['error'])

    def test_anonymous_gets_401(self):
        self.client.logout()
        for name in ('api-prices', 'api-monthly'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 401)


class PageTests(LoggedInTestCase):
    def test_pages_need_login(self):
        self.client.logout()
        for name in ('overview', 'rooms'):
            response = self.client.get(reverse(name))
            self.assertRedirects(response, f'{reverse("login")}?next={reverse(name)}')

    def test_login_page(self):
        self.client.logout()
        self.assertContains(self.client.get(reverse('login')), 'name="password"')
        response = self.client.post(reverse('login'), {'username': 'me', 'password': 'pw'})
        self.assertRedirects(response, reverse('overview'))

    def test_overview_shows_kpis_and_chart(self):
        load()
        response = self.client.get(reverse('overview'))
        self.assertContains(response, money(1099.0, 'usd'))
        self.assertContains(response, 'предварительно, на 10.01.2026')
        self.assertContains(response, pct(1099 / 1011 - 1))
        self.assertContains(response, 'data-mode="city-m2"')
        self.assertContains(response, '/api/prices?city=odesa&amp;deal=sale&amp;cur=usd&amp;rooms=1')
        self.assertNotContains(response, 'Сбор давно не выполнялся')

    def test_overview_without_data(self):
        self.assertContains(self.client.get(reverse('overview')), 'ещё нет данных')

    def test_rooms_page_modes(self):
        load()
        response = self.client.get(reverse('rooms'), {'from': '2025-06', 'metric': 'price'})
        self.assertContains(response, 'data-mode="rooms-price"')
        self.assertContains(response, 'from=2025-06')
        response = self.client.get(reverse('rooms'), {'metric': 'm2'})
        self.assertContains(response, 'data-mode="city-m2"')
        self.assertContains(response, 'линия одна')
        self.assertEqual(self.client.get(reverse('rooms'), {'metric': 'x'}).status_code, 400)

    def test_bad_filter_is_400(self):
        self.assertEqual(self.client.get(reverse('overview'), {'city': 'atlantis'}).status_code, 400)

    def test_stale_banner(self):
        CollectRun.objects.create(started_at=timezone.now() - dt.timedelta(days=9), status=CollectRun.Status.OK)
        self.assertContains(self.client.get(reverse('overview')), 'Сбор давно не выполнялся')

    def test_all_cities_in_the_select_odesa_by_default(self):
        response = self.client.get(reverse('overview'))
        self.assertEqual(response.content.decode().count('<option value='), 22)
        self.assertContains(response, '<option value="odesa" selected>')
        City.objects.filter(slug='lviv').update(enabled=False)  # not collected any more: still selectable
        response = self.client.get(reverse('overview'), {'city': 'lviv'})
        self.assertContains(response, '<option value="lviv" selected>')
        self.assertContains(response, 'ещё нет данных')


class ChartBuilderTests(TestCase):
    """The extra pages' charts, from the synthetic answers of collector/tests/factories.py."""

    def setUp(self):
        load()
        self.odesa = City.objects.get(slug='odesa')

    def ctx(self, **kw):
        return charts.Ctx(self.odesa, **kw)

    def test_flat_districts_in_usd_sorted_with_repair_and_m2(self):
        spec = charts.flat_districts(self.ctx(room=2))
        self.assertEqual(spec['type'], 'hbar')
        self.assertEqual(spec['categories'][0], 'Пересипський')  # district 14: the most expensive in the fake data
        self.assertEqual(spec['series'][0]['data'][0], 4 * 10000 * 2)  # UAH / usdToUah
        renovated = charts.flat_districts(self.ctx(room=2, repair='renovated', cur='uah'))
        self.assertAlmostEqual(renovated['series'][0]['data'][0], 4 * 10000 * 2 * 40 * 1.2)
        self.assertIn('с ремонтом', renovated['title'])
        m2 = charts.flat_districts(self.ctx(room=1, metric='m2'))
        self.assertAlmostEqual(m2['series'][0]['data'][0], 4 * 10000 / 40)

    def test_exposure_series_all_rooms_first_and_no_4_plus(self):
        spec = charts.exposure(self.ctx(deal='rent'))
        self.assertEqual([s['name'] for s in spec['series']], ['Все', '1 комн.', '2 комн.', '3 комн.'])
        self.assertEqual(spec['series'][0]['data'][-1], {'x': '2025-12-24', 'y': 35})
        self.assertIn('сдаётся', spec['title'])

    def test_price_distribution_currency_and_open_bucket(self):
        rent_uah = charts.price_distribution(self.ctx(deal='rent', cur='uah'))
        self.assertEqual(rent_uah['categories'][0], '0–4 тыс. ₴')
        self.assertEqual(rent_uah['categories'][-1], 'от 16 тыс. ₴')
        sale_uah = charts.price_distribution(self.ctx(deal='sale', cur='uah'))
        self.assertIn('только в USD', sale_uah['subtitle'])  # sale is published in USD only
        self.assertTrue(sale_uah['categories'][0].endswith('$'))

    def test_price_distribution_folds_the_long_tail(self):
        from collector.tests.factories import _ok
        rows = [{'roomCount': 1, 'currencyId': 1, 'contractTypeId': 1, 'priceStart': i * 1000.0,
                 'priceEnd': (i + 1) * 1000.0, 'count': 1000 if i < 10 else 1, 'date': '2026-01-10T00:00:00.000Z'}
                for i in range(80)]
        load({('price-distribution', None): _ok(rows)})
        spec = charts.price_distribution(self.ctx())
        self.assertEqual(len(spec['categories']), 11)  # 10 full buckets hold 97%+, then one "from" bucket
        self.assertEqual(spec['categories'][-1], 'от 10 тыс. $')
        self.assertEqual(spec['series'][0]['data'][-1], 70)
        self.assertEqual(len(spec['series']), 1)  # one room count

    def test_listing_vs_deal(self):
        spec = charts.listing_vs_deal(self.ctx(room=3))
        self.assertEqual([s['name'] for s in spec['series']], ['В объявлении', 'Сделка'])
        self.assertEqual(spec['series'][1]['data'][-1]['y'], 40000 * 3 * 0.9)

    def test_affordability(self):
        sale = charts.salary_history(self.ctx())
        self.assertEqual((sale['unit'], sale['series'][0]['data'][-1]['y']), ('лет', 7.0))
        rent = charts.salary_history(self.ctx(deal='rent'))
        self.assertEqual((rent['unit'], rent['series'][2]['data'][-1]['y']), ('%', 60.0))
        positions = charts.salary_positions(self.ctx())
        self.assertEqual(positions['categories'], ['Кухар', 'Водій', 'Касир'])  # by salary
        self.assertEqual(len(positions['series']), 3)
        self.assertEqual(charts.sale_in_rent(self.ctx())['series'][0]['data'][-1]['y'], 16.0)

    def test_pets_rent_only_where_published(self):
        self.assertIn('Киева и Львова', charts.pets_rent(self.ctx())['empty'])
        kyiv = charts.pets_rent(charts.Ctx(City.objects.get(slug='kyiv')))
        self.assertIsNone(kyiv['empty'])
        self.assertEqual(kyiv['values'], [20.0, 30.0, 10.0, 40.0])

    def test_new_buildings(self):
        classes = charts.primary_classes(self.ctx())
        self.assertEqual(classes['series'][-1]['name'], 'Средняя по городу')
        parking = charts.parking_classes(self.ctx())
        self.assertEqual(parking['categories'], ['Эконом', 'Комфорт', 'Бизнес', 'Премиум'])
        self.assertEqual(parking['series'][0]['data'], [15000.0, 60000.0, 30000.0, 45000.0])  # classId 1, 4, 2, 3
        ranking = charts.developers_ranking(self.ctx())
        self.assertIn('2025', ranking['title'])
        self.assertEqual(ranking['series'][0]['data'], [1000, 900, 800])
        share = charts.developers_share(self.ctx())
        self.assertEqual((share['labels'][-1], share['values'][-1]), ('Остальные', 40.0))
        build = charts.construction(self.ctx())
        self.assertEqual(build['series'][0]['data'], [220, 79, 7, 896])
        self.assertEqual(build['series'][1]['data'], [440, 158, 14, 1792])
        self.assertEqual(charts.lending(self.ctx())['series'][0]['data'], [37, 7, 1])
        dssu = charts.commissioning(self.ctx())
        self.assertEqual(dssu['categories'], ['2025', '2026'])
        self.assertEqual(dssu['series'][0]['data'], [1.0, 0.6])
        self.assertIn('за 3 кв.', dssu['subtitle'])

    def test_houses(self):
        price = charts.houses_price(self.ctx())
        self.assertEqual([s['name'] for s in price['series']], ['Одеса', 'Область'])
        self.assertEqual(charts.houses_districts(self.ctx())['categories'][0], 'Пересипський')
        self.assertIsNotNone(charts.houses_districts(self.ctx(deal='rent'))['empty'])

    def test_short_district_shape_and_top_20(self):
        """Ivano-Frankivsk: ~150 micro-districts with USD fields and no usdToUah: USD used as is, top 20 shown."""
        from collector.tests.factories import _ok
        rows = [{'cityId': 115, 'districtId': i, 'districtName': f'Мікрорайон {i}', 'contractTypeId': 1,
                 'roomCount': 1, 'median': 1000.0 * i * 40, 'medianUsd': 1000.0 * i, 'medianM2': 30.0 * i * 40,
                 'medianM2Usd': 30.0 * i, 'count': 5, 'date': '2026-11-18T00:00:00.000Z'} for i in range(1, 31)]
        rows.append({**rows[0], 'districtId': 99, 'median': None, 'medianUsd': None})  # no data: left out
        load({('market-districts', None): _ok(rows)})
        spec = charts.flat_districts(self.ctx())
        self.assertEqual(len(spec['categories']), 20)
        self.assertEqual((spec['categories'][0], spec['series'][0]['data'][0]), ('Мікрорайон 30', 30000.0))
        self.assertIn('20 самых дорогих из 30', spec['subtitle'])
        self.assertEqual(charts.flat_districts(self.ctx(metric='m2'))['series'][0]['data'][0], 900.0)
        self.assertEqual(charts.flat_districts(self.ctx(cur='uah'))['series'][0]['data'][0], 1200000.0)

    def test_string_district_label(self):
        from collector.tests.factories import average_by_district
        districts = average_by_district()
        districts['data'][0]['label'] = 'Київ'
        load({('districts', None): districts})
        self.assertIn('Київ', charts.primary_districts(self.ctx())['categories'])

    def test_city_without_data_says_so(self):
        lviv = charts.Ctx(City.objects.get(slug='lviv'))
        for build in (charts.flat_districts, charts.exposure, charts.salary_history, charts.primary_classes,
                      charts.construction, charts.commissioning, charts.houses_price):
            with self.subTest(build=build.__name__):
                self.assertTrue(build(lviv)['empty'])


class LunPagesTests(LoggedInTestCase):
    def test_every_page_renders_its_cards(self):
        load()
        expected = {'districts': 3, 'market': 3, 'affordability': 4, 'primary': 7, 'houses': 3}
        for page, cards in expected.items():
            with self.subTest(page=page):
                response = self.client.get(reverse(page), {'city': 'odesa'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.context['specs']), cards)
                self.assertContains(response, 'id="chart-specs"')

    def test_page_filters(self):
        load()
        response = self.client.get(reverse('districts'), {'room': '2', 'repair': 'not', 'metric': 'm2'})
        self.assertContains(response, 'без ремонта')
        self.assertNotContains(self.client.get(reverse('market')), 'name="room" value="4"')
        for params in ({'room': '4'}, {'repair': 'x'}, {'metric': 'x'}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(reverse('districts'), params).status_code, 400)

    def test_city_not_collected_yet_says_so(self):
        response = self.client.get(reverse('primary'), {'city': 'lviv'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ещё не собраны')
        self.assertNotContains(response, 'не публикует')

    def test_collected_city_without_some_data_says_lun_does_not_publish(self):
        load()
        response = self.client.get(reverse('affordability'), {'city': 'odesa'})
        self.assertContains(response, 'только для Киева и Львова')  # pets-rent: LUN has it for 2 cities only
        self.assertNotContains(response, 'ещё не собраны')

    def test_pages_need_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('houses')).status_code, 302)

    def test_sidebar_lists_the_pages(self):
        response = self.client.get(reverse('overview'))
        for title in ('Районы', 'Рынок', 'Доступность', 'Новостройки', 'Дома'):
            self.assertContains(response, title)


class FormatTests(TestCase):
    def test_formats(self):
        self.assertEqual(num(1162.79, 2), '1\u00a0162,79')
        self.assertEqual(money(51000, 'usd'), '51\u00a0000,00\u00a0$')
        self.assertEqual(pct(0.0284), '+2,8\u00a0%')
        self.assertEqual(pct(-0.1), '-10,0\u00a0%')
        self.assertEqual(num(None), '—')
