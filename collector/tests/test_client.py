import httpx
from django.test import SimpleTestCase

from collector.lun.client import LunBlocked, LunClient, LunError
from collector.lun.hashing import payload_hash, without_today


def client_for(*responses):
    """A LunClient whose transport returns the given responses (or raises given exceptions) in order."""
    queue = list(responses)
    requests = []

    def handler(request):
        requests.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    sleeps = []
    client = LunClient('http://lun.test/stat/api/data/', transport=httpx.MockTransport(handler), sleep=sleeps.append)
    return client, requests, sleeps


def json_response(body, status=200):
    return httpx.Response(status, json=body)


class LunClientTests(SimpleTestCase):
    def test_returns_json_and_sends_params(self):
        client, requests, _ = client_for(json_response({'status': 'success', 'data': []}))
        self.assertEqual(client.get('flat-price-history', {'cityId': 115, 'contractTypeId': 2}),
                         {'status': 'success', 'data': []})
        self.assertEqual(str(requests[0].url),
                         'http://lun.test/stat/api/data/flat-price-history?cityId=115&contractTypeId=2')
        self.assertIn('Mozilla', requests[0].headers['user-agent'])

    def test_retries_5xx_and_network_errors_with_backoff(self):
        client, requests, sleeps = client_for(
            httpx.Response(502), httpx.ConnectError('boom'), json_response({'ok': 1})
        )
        self.assertEqual(client.get('price', {'cityId': 115}), {'ok': 1})
        self.assertEqual(len(requests), 3)
        self.assertEqual(sleeps, [2, 4])

    def test_gives_up_after_three_attempts(self):
        client, requests, _ = client_for(httpx.Response(500), httpx.Response(503), httpx.Response(429))
        with self.assertRaises(LunError) as ctx:
            client.get('price', {'cityId': 115})
        self.assertNotIsInstance(ctx.exception, LunBlocked)
        self.assertEqual(len(requests), 3)

    def test_403_is_blocked_without_retry(self):
        client, requests, _ = client_for(httpx.Response(403))
        with self.assertRaises(LunBlocked):
            client.get('price', {'cityId': 115})
        self.assertEqual(len(requests), 1)

    def test_html_instead_of_json_is_blocked(self):
        page = httpx.Response(200, text='<html>Just a moment...</html>', headers={'content-type': 'text/html'})
        client, _, _ = client_for(page)
        with self.assertRaises(LunBlocked):
            client.get('price', {'cityId': 115})

    def test_404_fails_without_retry(self):
        client, requests, _ = client_for(httpx.Response(404))
        with self.assertRaises(LunError):
            client.get('nope', {})
        self.assertEqual(len(requests), 1)


class HashingTests(SimpleTestCase):
    def test_today_points_are_ignored_anywhere(self):
        a = {'data': {'x': [{'v': 1, 'isToday': False}, {'v': 2, 'isToday': True, 'date': '2026-11-18'}]}}
        b = {'data': {'x': [{'v': 1, 'isToday': False}, {'v': 3, 'isToday': True, 'date': '2026-11-25'}]}}
        self.assertEqual(payload_hash(a), payload_hash(b))
        self.assertEqual(without_today(a), {'data': {'x': [{'v': 1, 'isToday': False}]}})

    def test_monthly_change_changes_the_hash(self):
        self.assertNotEqual(payload_hash({'data': [{'v': 1}]}), payload_hash({'data': [{'v': 2}]}))

    def test_key_order_does_not_matter(self):
        self.assertEqual(payload_hash({'a': 1, 'b': 2}), payload_hash({'b': 2, 'a': 1}))

    def test_record_order_does_not_matter(self):
        # LUN shuffles records of `price` between requests
        self.assertEqual(payload_hash({'data': [{'m': '2026-10'}, {'m': '2026-11'}]}),
                         payload_hash({'data': [{'m': '2026-11'}, {'m': '2026-10'}]}))
