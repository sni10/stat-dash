"""HTTP client for LUN's undocumented statistics API (https://lun.ua/stat/api/data/<endpoint>)."""
import logging
import time
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
)
ATTEMPTS = 3


class LunError(Exception):
    """The request failed after all attempts, or the answer is not usable JSON."""


class LunNotFound(LunError):
    """404: LUN does not publish this endpoint for the city (developers-ranking of small cities). Not an error."""


class LunBlocked(LunError):
    """403 or an HTML page instead of JSON (Cloudflare challenge): stop, don't retry."""


class LunClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Accept-Language': 'uk,en;q=0.8'},
        )
        self._sleep = sleep

    def close(self):
        self._http.close()

    def get(self, endpoint: str, params: dict) -> dict:
        """GET one endpoint. Network errors, 429 and 5xx are retried with backoff 2 s, 4 s."""
        error: Exception | None = None
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = self._http.get(endpoint, params=params)
            except httpx.TransportError as exc:
                error = exc
            else:
                if response.status_code == 403:
                    raise LunBlocked(f'{endpoint} {params}: HTTP 403')
                if response.status_code == 429 or response.status_code >= 500:
                    error = LunError(f'{endpoint} {params}: HTTP {response.status_code}')
                elif response.status_code == 404:
                    raise LunNotFound(f'{endpoint} {params}: HTTP 404')
                elif response.status_code != 200:
                    raise LunError(f'{endpoint} {params}: HTTP {response.status_code}')
                elif 'json' not in response.headers.get('content-type', ''):
                    raise LunBlocked(
                        f'{endpoint} {params}: {response.headers.get("content-type") or "no content-type"} '
                        'instead of JSON'
                    )
                else:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise LunError(f'{endpoint} {params}: invalid JSON: {exc}') from exc
            logger.warning('%s %s: attempt %d/%d failed: %s', endpoint, params, attempt, ATTEMPTS, error)
            if attempt < ATTEMPTS:
                self._sleep(2**attempt)
        raise LunError(f'{endpoint} {params}: {error}') from error
