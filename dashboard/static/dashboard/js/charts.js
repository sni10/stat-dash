// Charts of the dashboard: every <div class="chart" data-endpoint data-mode data-cur> gets an ApexCharts line chart
// from the JSON endpoint. Styling follows TailAdmin's statistics chart.
(function () {
  'use strict';

  const COLORS = ['#465FFF', '#12B76A', '#F79009', '#7A5AF8'];
  const SYMBOLS = { usd: '$', uah: '₴' };
  const ROOM_LABELS = { 1: '1 кімн.', 2: '2 кімн.', 3: '3 кімн.' };  // 4+ rooms are not shown

  const isDark = () => document.documentElement.classList.contains('dark');
  const number = (value, digits) =>
    value == null ? '—' : new Intl.NumberFormat('uk-UA', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
  const date = (ms) => new Date(ms).toLocaleDateString('uk-UA', { day: '2-digit', month: '2-digit', year: 'numeric' });

  const FONT = 'Outfit, sans-serif';  // Outfit has no Cyrillic: letters fall back to the system sans-serif
  const axisText = () => (isDark() ? '#98A2B3' : '#667085');

  // [{name, points: [{x, y, preliminary}]}] from the API answer
  function buildSeries(mode, points) {
    if (mode === 'city-m2') {
      const byDate = new Map();
      for (const p of points) if (!byDate.has(p.date)) byDate.set(p.date, p);
      return [{
        name: 'Медіана м²',
        points: [...byDate.values()].map((p) => ({ x: Date.parse(p.date), y: p.price_m2, preliminary: p.preliminary })),
      }];
    }
    const byRoom = new Map();
    for (const p of points) {
      if (!byRoom.has(p.rooms)) byRoom.set(p.rooms, []);
      byRoom.get(p.rooms).push({ x: Date.parse(p.date), y: p.price, preliminary: p.preliminary });
    }
    return [...byRoom.entries()].sort((a, b) => a[0] - b[0])
      .map(([rooms, pts]) => ({ name: ROOM_LABELS[rooms] || `${rooms} кімн.`, points: pts }));
  }

  function render(el, data) {
    const mode = el.dataset.mode;
    const symbol = SYMBOLS[el.dataset.cur] || '';
    const series = buildSeries(mode, data.points);
    if (!series.length || !series.some((s) => s.points.length)) {
      el.innerHTML = '<p class="py-16 text-center text-sm text-gray-500 dark:text-gray-400">Немає даних за вибраний період.</p>';
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
        x: { formatter: (ms) => date(ms) + (preliminaryDates.has(ms) ? ' · попередньо' : '') },
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
      el.innerHTML = `<p class="py-16 text-center text-sm text-red-600 dark:text-red-500">Не вдалося завантажити дані: ${error.message}</p>`;
    }
  }

  document.querySelectorAll('.chart[data-endpoint]').forEach(load);

  // --- Specs embedded in the page (dashboard/charts.py): line | area | bar | hbar | donut ---------------------

  const PALETTE = ['#465FFF', '#12B76A', '#F79009', '#7A5AF8', '#EE46BC', '#0BA5EC', '#F04438', '#667085',
    '#9CB9FF', '#6CE9A6', '#FEC84B', '#BDB4FE'];

  function specOptions(el, spec) {
    const value = (v) => (v == null ? '—' : `${number(v, spec.digits)} ${spec.unit}`.trim());
    const base = {
      chart: { height: spec.height || 320, fontFamily: FONT, toolbar: { show: false }, zoom: { enabled: false },
        animations: { enabled: false } },
      colors: PALETTE,
      dataLabels: { enabled: false },
      legend: { show: spec.series.length > 1 || spec.type === 'donut', position: 'top', horizontalAlign: 'left',
        fontFamily: FONT, labels: { colors: axisText() } },
      grid: { borderColor: isDark() ? '#1E2640' : '#F3F4F6' },
      tooltip: { theme: isDark() ? 'dark' : 'light', y: { formatter: value } },
    };
    if (spec.type === 'donut') {
      return { ...base, chart: { ...base.chart, type: 'donut' }, series: spec.values, labels: spec.labels,
        stroke: { colors: [isDark() ? '#101828' : '#ffffff'] },
        dataLabels: { enabled: true, formatter: (v) => `${number(v, 0)}%` },
        plotOptions: { pie: { donut: { size: '62%' } } } };
    }
    if (spec.type === 'bar' || spec.type === 'hbar') {
      const horizontal = spec.type === 'hbar';
      const axis = { labels: { style: { colors: axisText() } } };
      return { ...base, chart: { ...base.chart, type: 'bar' },
        series: spec.series, xaxis: { categories: spec.categories, axisBorder: { show: false }, axisTicks: { show: false },
          labels: { ...axis.labels, ...(horizontal ? { formatter: (v) => number(Number(v), 0) } : { rotate: -45, trim: true }) } },
        yaxis: { labels: { ...axis.labels, maxWidth: 220, ...(horizontal ? {} : { formatter: (v) => number(v, spec.digits) }) } },
        plotOptions: { bar: { horizontal, borderRadius: 4, columnWidth: '60%', barHeight: '70%' } },
        tooltip: { ...base.tooltip, shared: true, intersect: false },
        grid: { ...base.grid, xaxis: { lines: { show: horizontal } }, yaxis: { lines: { show: !horizontal } } } };
    }
    const preliminary = new Set(spec.preliminary.map((d) => Date.parse(d)));
    const series = spec.series.map((s) => ({ name: s.name, data: s.data.map((p) => ({ x: Date.parse(p.x), y: p.y })) }));
    const discrete = [];
    series.forEach((s, si) => s.data.forEach((p, pi) => {
      if (preliminary.has(p.x)) discrete.push({ seriesIndex: si, dataPointIndex: pi, fillColor: '#fff', strokeColor: PALETTE[si % PALETTE.length], size: 6 });
    }));
    return { ...base, chart: { ...base.chart, type: spec.type === 'area' ? 'area' : 'line' }, series,
      stroke: { curve: 'straight', width: 2 }, markers: { size: 0, hover: { size: 5 }, discrete },
      xaxis: { type: 'datetime', axisBorder: { show: false }, axisTicks: { show: false }, tooltip: { enabled: false },
        labels: { datetimeUTC: false, format: 'MM.yyyy', style: { colors: axisText() } } },
      yaxis: { labels: { formatter: (v) => number(v, spec.digits), style: { colors: axisText() } } },
      grid: { ...base.grid, xaxis: { lines: { show: false } }, yaxis: { lines: { show: true } } },
      tooltip: { ...base.tooltip, shared: true, intersect: false,
        x: { formatter: (ms) => date(ms) + (preliminary.has(ms) ? ' · попередньо' : '') } } };
  }

  const specsNode = document.getElementById('chart-specs');
  if (specsNode) {
    const specs = JSON.parse(specsNode.textContent);
    document.querySelectorAll('.chart[data-spec]').forEach((el) => {
      const spec = specs[Number(el.dataset.spec)];
      const chart = new ApexCharts(el, specOptions(el, spec));
      chart.render();
      window.addEventListener('theme-changed', () => chart.updateOptions(specOptions(el, spec), false, false));
    });
  }
})();
