import datetime as dt

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from collector.models import City, CollectRun, LunPriceSnapshot
from collector.service import collect
from collector.tests.factories import RENT, SALE, FakeClient, answers, flat_price_history
from dashboard import queries
from dashboard.templatetags.dash import money, num, pct

NO_PAUSE = {'BASE_URL': 'http://lun.test/', 'PAUSE': (0, 0)}

# Monthly points on the 24th of every month of 2025, "today" on 2026-01-10. m² = 1000 + month index,
# the same for every room count (as in LUN's data); the "today" point is 1099.


def load(data=None):
    with override_settings(LUN=NO_PAUSE):
        collect([City.objects.get(slug='odesa')], client=FakeClient(data or answers()), sleep=lambda _: None,
                alert=lambda _: None)


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
        self.assertEqual(kpi['count'], 400)  # 4 room counts x 100 listings
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
        for params in ({'city': 'atlantis'}, {'deal': 'swap'}, {'cur': 'eur'}, {'rooms': 'x'}, {'rooms': '7'},
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
        self.assertEqual(len(data['points']), 4)
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


class FormatTests(TestCase):
    def test_formats(self):
        self.assertEqual(num(1162.79, 2), '1\u00a0162,79')
        self.assertEqual(money(51000, 'usd'), '51\u00a0000,00\u00a0$')
        self.assertEqual(pct(0.0284), '+2,8\u00a0%')
        self.assertEqual(pct(-0.1), '-10,0\u00a0%')
        self.assertEqual(num(None), '—')
