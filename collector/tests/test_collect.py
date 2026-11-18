import datetime as dt
from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from collector.lun.client import LunBlocked, LunError
from collector.models import City, CollectRun, LunPriceSnapshot, LunRaw
from collector.service import collect, is_stale

from .factories import PRICE, RENT, SALE, ByCityClient, FakeClient, answers, flat_price_history

NO_PAUSE = {'BASE_URL': 'http://lun.test/', 'PAUSE': (0, 0)}


def no_sleep(_seconds):
    pass


@override_settings(LUN=NO_PAUSE)
class CollectTests(TestCase):
    def setUp(self):
        self.odesa = City.objects.get(slug='odesa')
        self.alerts = []

    def run_collect(self, client, cities=None):
        return collect(cities, client=client, sleep=no_sleep, alert=self.alerts.append)

    def snapshots(self, **filters):
        return LunPriceSnapshot.objects.filter(city=self.odesa, **filters)

    def test_first_run_loads_the_whole_history(self):
        run = self.run_collect(FakeClient(answers()))

        self.assertEqual(run.status, CollectRun.Status.OK)
        # 12 monthly dates x 4 rooms + 4 "today" points, for sale and for rent
        self.assertEqual(self.snapshots(contract_type=1).count(), 52)
        self.assertEqual(self.snapshots(contract_type=2).count(), 52)
        self.assertEqual(self.snapshots(is_today=True).count(), 8)
        self.assertEqual(run.rows_upserted, 104)
        self.assertEqual(LunRaw.objects.count(), 3)
        self.assertEqual(self.alerts, [])

    def test_only_enabled_cities_by_default(self):
        client = FakeClient(answers())
        self.run_collect(client)
        self.assertEqual({params['cityId'] for _, params in client.calls}, {115})
        self.assertEqual(len(client.calls), 3)

    def test_rerun_creates_no_duplicates(self):
        self.run_collect(FakeClient(answers()))
        second = self.run_collect(FakeClient(answers()))

        self.assertEqual(second.status, CollectRun.Status.OK)
        self.assertEqual(self.snapshots().count(), 104)
        self.assertEqual(LunRaw.objects.count(), 3)  # same data -> no new raw rows
        self.assertEqual(second.rows_upserted, 8)  # only the "today" points are rewritten

    def test_new_today_point_replaces_the_old_one(self):
        self.run_collect(FakeClient(answers()))
        later = answers()
        later[SALE] = flat_price_history(115, 1, today=dt.date(2026, 1, 17))
        self.run_collect(FakeClient(later))

        today = self.snapshots(contract_type=1, is_today=True)
        self.assertEqual(set(today.values_list('snap_date', flat=True)), {dt.date(2026, 1, 17)})
        self.assertEqual(today.count(), 4)
        # only "today" changed -> the hash without it is the same -> no new raw row
        self.assertEqual(LunRaw.objects.count(), 3)

    def test_monthly_point_wins_over_today_on_the_same_date(self):
        payload = flat_price_history(115, 1, today=dt.date(2025, 12, 24))
        data = answers()
        data[SALE] = payload
        self.run_collect(FakeClient(data))

        row = self.snapshots(contract_type=1, snap_date=dt.date(2025, 12, 24), room_count=1).get()
        self.assertFalse(row.is_today)
        self.assertEqual(float(row.median_m2_usd), 1011.0)  # the monthly value, not the "today" one (1099)
        self.assertEqual(self.snapshots(contract_type=1).count(), 48)

    def test_revised_past_point_is_overwritten_and_raw_kept(self):
        self.run_collect(FakeClient(answers()))
        revised = answers()
        revised[SALE] = flat_price_history(115, 1, m2_usd=1005.0)
        run = self.run_collect(FakeClient(revised))

        row = self.snapshots(contract_type=1, snap_date=dt.date(2025, 1, 24), room_count=1).get()
        self.assertEqual(float(row.median_m2_usd), 1005.0)
        self.assertEqual(LunRaw.objects.filter(endpoint='flat-price-history', params__contractTypeId=1).count(), 2)
        self.assertEqual(run.rows_upserted, 48 + 8)

    def test_schema_error_keeps_raw_skips_parsing_and_alerts(self):
        broken = answers()
        broken[SALE] = {'status': 'success', 'data': [{'cityId': 115, 'roomCount': 'one'}]}
        run = self.run_collect(FakeClient(broken))

        self.assertEqual(run.status, CollectRun.Status.PARTIAL)
        self.assertIn('schema', run.error)
        self.assertEqual(self.snapshots(contract_type=1).count(), 0)
        self.assertEqual(self.snapshots(contract_type=2).count(), 52)
        self.assertTrue(LunRaw.objects.filter(params__contractTypeId=1).exists())
        self.assertEqual(len(self.alerts), 1)

    def test_points_of_another_city_are_rejected(self):
        wrong = answers()
        wrong[SALE] = flat_price_history(1, 1)
        run = self.run_collect(FakeClient(wrong))
        self.assertEqual(run.status, CollectRun.Status.PARTIAL)
        self.assertFalse(self.snapshots(contract_type=1).exists())

    def test_blocked_stops_the_run(self):
        blocked = answers()
        blocked[SALE] = LunBlocked('HTTP 403')
        client = FakeClient(blocked)
        run = self.run_collect(client)

        self.assertEqual(run.status, CollectRun.Status.FAILED)
        self.assertEqual(len(client.calls), 1)
        self.assertIn('2 requests skipped', run.error)
        self.assertEqual(len(self.alerts), 1)

    def test_failed_request_does_not_stop_the_others(self):
        flaky = answers()
        flaky[RENT] = LunError('HTTP 502')
        run = self.run_collect(FakeClient(flaky))
        self.assertEqual(run.status, CollectRun.Status.PARTIAL)
        self.assertEqual(self.snapshots(contract_type=1).count(), 52)

    def test_crash_is_recorded_and_reraised(self):
        client = FakeClient(answers())
        with mock.patch('collector.service.store_raw', side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError):
                self.run_collect(client)
        run = CollectRun.objects.get()
        self.assertEqual(run.status, CollectRun.Status.FAILED)
        self.assertIn('disk full', run.error)

    def test_interrupted_runs_are_marked_failed(self):
        old = CollectRun.objects.create(
            started_at=timezone.now() - dt.timedelta(hours=3), status=CollectRun.Status.RUNNING
        )
        self.run_collect(FakeClient(answers()))
        old.refresh_from_db()
        self.assertEqual(old.status, CollectRun.Status.FAILED)

    def test_new_city_needs_only_a_row(self):
        kyiv = City.objects.get(slug='kyiv')
        kyiv.enabled = True
        kyiv.save()
        run = self.run_collect(ByCityClient())
        self.assertEqual(run.status, CollectRun.Status.OK)
        self.assertEqual(LunPriceSnapshot.objects.filter(city=kyiv).count(), 104)

    def test_price_endpoint_is_archived_and_validated(self):
        bad = answers()
        bad[PRICE] = {'status': 'success', 'data': {'cityAvg': []}}
        run = self.run_collect(FakeClient(bad))
        self.assertEqual(run.status, CollectRun.Status.PARTIAL)
        self.assertTrue(LunRaw.objects.filter(endpoint='price').exists())


class StalenessTests(TestCase):
    def test_no_runs_is_stale(self):
        self.assertTrue(is_stale(dt.timedelta(days=7)))

    def test_recent_ok_or_partial_is_fresh_failed_is_not(self):
        CollectRun.objects.create(started_at=timezone.now() - dt.timedelta(days=1), status=CollectRun.Status.FAILED)
        self.assertTrue(is_stale(dt.timedelta(days=7)))
        CollectRun.objects.create(started_at=timezone.now() - dt.timedelta(days=2), status=CollectRun.Status.PARTIAL)
        self.assertFalse(is_stale(dt.timedelta(days=7)))

    def test_old_ok_is_stale(self):
        CollectRun.objects.create(started_at=timezone.now() - dt.timedelta(days=8), status=CollectRun.Status.OK)
        self.assertTrue(is_stale(dt.timedelta(days=7)))


@override_settings(LUN=NO_PAUSE)
class MonthlyViewTests(TestCase):
    def test_today_point_is_not_aggregated(self):
        collect(client=FakeClient(answers()), sleep=no_sleep, alert=lambda _: None)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT month, w_avg_m2_usd FROM v_price_monthly "
                "WHERE city_id = 115 AND contract_type = 1 AND room_count = 1 ORDER BY month"
            )
            rows = cursor.fetchall()
        self.assertEqual(len(rows), 12)  # Jan..Dec 2025; the 2026-01-10 "today" point has no month of its own
        self.assertEqual(float(rows[-1][1]), 1011.0)


class SeedTests(TestCase):
    def test_cities_seeded_with_only_odesa_enabled(self):
        self.assertEqual(City.objects.count(), 22)
        self.assertEqual(list(City.objects.filter(enabled=True).values_list('id', flat=True)), [115])
        self.assertEqual(City.objects.get(slug='kyiv').id, 1)
