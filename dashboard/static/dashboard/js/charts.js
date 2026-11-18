// Charts of the dashboard: every <div class="chart" data-endpoint data-mode data-cur> gets an ApexCharts line chart
// from the JSON endpoint. Styling follows TailAdmin's statistics chart.
(function () {
  'use strict';

  const COLORS = ['#465FFF', '#12B76A', '#F79009', '#7A5AF8'];
  const SYMBOLS = { usd: '$', uah: '₴' };
  const ROOM_LABELS = { 1: '1 комн.', 2: '2 комн.', 3: '3 комн.', 4: '4 комн.' };

  const isDark = () => document.documentElement.classList.contains('dark');
  const number = (value, digits) =>
    value == null ? '—' : new Intl.NumberFormat('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
  const date = (ms) => new Date(ms).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });

  const FONT = 'Outfit, sans-serif';  // Outfit has no Cyrillic: letters fall back to the system sans-serif
  const axisText = () => (isDark() ? '#98A2B3' : '#667085');

  // [{name, points: [{x, y, preliminary}]}] from the API answer
  function buildSeries(mode, points) {
    if (mode === 'city-m2') {
      const byDate = new Map();
      for (const p of points) if (!byDate.has(p.date)) byDate.set(p.date, p);
      return [{
        name: 'Медиана м²',
        points: [...byDate.values()].map((p) => ({ x: Date.parse(p.date), y: p.price_m2, preliminary: p.preliminary })),
      }];
    }
    const byRoom = new Map();
    for (const p of points) {
      if (!byRoom.has(p.rooms)) byRoom.set(p.rooms, []);
      byRoom.get(p.rooms).push({ x: Date.parse(p.date), y: p.price, preliminary: p.preliminary });
    }
    return [...byRoom.entries()].sort((a, b) => a[0] - b[0])
      .map(([rooms, pts]) => ({ name: ROOM_LABELS[rooms] || `${rooms} комн.`, points: pts }));
  }

  function render(el, data) {
    const mode = el.dataset.mode;
    const symbol = SYMBOLS[el.dataset.cur] || '';
    const series = buildSeries(mode, data.points);
    if (!series.length || !series.some((s) => s.points.length)) {
      el.innerHTML = '<p class="py-16 text-center text-sm text-gray-500 dark:text-gray-400">Нет данных за выбранный период.</p>';
      return;
    }
    const colors = mode === 'city-m2' ? [COLORS[0]] : series.map((s, i) => COLORS[i % COLORS.length]);
    // the floating "today" point: hollow marker
    const discrete = [];
    series.forEach((s, si) => s.points.forEach((p, pi) => {
      if (p.preliminary) discrete.push({ seriesIndex: si, dataPointIndex: pi, fillColor: '#fff', strokeColor: colors[si], size: 6 });
    }));
    const preliminaryDates = new Set(series.flatMap((s) => s.points.filter((p) => p.preliminary).map((p) => p.x)));
    const digits = mode === 'city-m2' && el.dataset.cur === 'usd' ? 2 : 0;
    const options = () => ({
      series: series.map((s) => ({ name: s.name, data: s.points.map((p) => ({ x: p.x, y: p.y, preliminary: p.preliminary })) })),
      colors,
      chart: {
        type: mode === 'city-m2' ? 'area' : 'line',
        height: Number(el.dataset.height) || 320,
        fontFamily: FONT,
        toolbar: { show: false },
        zoom: { enabled: false },
        animations: { enabled: false },
      },
      fill: mode === 'city-m2' ? { type: 'gradient', gradient: { opacityFrom: 0.45, opacityTo: 0 } } : { type: 'solid' },
      stroke: { curve: 'straight', width: 2 },
      markers: { size: 0, hover: { size: 5 }, discrete },
      dataLabels: { enabled: false },
      legend: { show: series.length > 1, position: 'top', horizontalAlign: 'left', fontFamily: FONT, labels: { colors: axisText() } },
      xaxis: {
        type: 'datetime',
        axisBorder: { show: false },
        axisTicks: { show: false },
        labels: { datetimeUTC: false, format: 'MM.yyyy', style: { colors: axisText() } },
        tooltip: { enabled: false },
      },
      yaxis: { labels: { formatter: (v) => number(v, 0), style: { colors: axisText() } } },
      grid: { borderColor: isDark() ? '#1E2640' : '#F3F4F6', xaxis: { lines: { show: false } }, yaxis: { lines: { show: true } } },
      tooltip: {
        theme: isDark() ? 'dark' : 'light',
        shared: true,
        intersect: false,
        x: { formatter: (ms) => date(ms) + (preliminaryDates.has(ms) ? ' · предварительно' : '') },
        y: { formatter: (v) => `${number(v, digits)} ${symbol}` },
      },
    });
    el.innerHTML = '';
    const chart = new ApexCharts(el, options());
    chart.render();
    // the whole config again: a partial update would drop the axis formatters
    window.addEventListener('theme-changed', () => chart.updateOptions(options(), false, false));
  }

  async function load(el) {
    try {
      const response = await fetch(el.dataset.endpoint, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(el, await response.json());
    } catch (error) {
      el.innerHTML = `<p class="py-16 text-center text-sm text-red-600 dark:text-red-500">Не удалось загрузить данные: ${error.message}</p>`;
    }
  }

  document.querySelectorAll('.chart[data-endpoint]').forEach(load);
})();
