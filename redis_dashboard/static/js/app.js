(() => {
    const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    const readJSON = (id) => JSON.parse(document.getElementById(id)?.textContent || 'null');
    const fmt = (n) => n == null ? '—' : Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(n);

    // htmx ignores 4xx by default; our form returns 422 with validation errors
    document.addEventListener('htmx:beforeSwap', (e) => {
        if (e.detail.xhr.status === 422) { e.detail.shouldSwap = true; e.detail.isError = false; }
        // free Chart.js instances before their canvas is replaced
        e.detail.target.querySelectorAll('canvas').forEach((c) => Chart.getChart(c)?.destroy());
    });

    function baseOptions() {
        Chart.defaults.color = css('--bs-secondary-color');
        Chart.defaults.borderColor = css('--grid');
        Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
        return { responsive: true, maintainAspectRatio: false, animation: false };
    }

    const charts = {
        timeline(canvas, data) {
            const colors = { ok: css('--ok'), warn: css('--warn'), crit: css('--crit'), unknown: css('--unknown') };
            return new Chart(canvas, {
                data: {
                    labels: data.map((d) => d.i),
                    datasets: [
                        {
                            type: 'line', label: 'CPU %', yAxisID: 'cpu', data: data.map((d) => d.cpu),
                            borderColor: css('--accent'), backgroundColor: css('--accent'), tension: .3,
                            pointBackgroundColor: data.map((d) => colors[d.level]), pointBorderWidth: 0, pointRadius: 4, pointHoverRadius: 6,
                        },
                        {
                            type: 'bar', label: 'ops/sec', yAxisID: 'ops', data: data.map((d) => d.ops),
                            backgroundColor: css('--bar'), borderRadius: 3,
                        },
                    ],
                },
                options: {
                    ...baseOptions(),
                    interaction: { mode: 'index', intersect: false },
                    onHover: (e, els) => { e.native.target.style.cursor = els.length ? 'pointer' : 'default'; },
                    onClick: (e, els) => els.length && selectSample(data[els[0].index].i),
                    plugins: {
                        legend: { position: 'top', align: 'end', labels: { boxWidth: 10, boxHeight: 10 } },
                        tooltip: {
                            callbacks: {
                                title: (items) => `Sample #${items[0].label}`,
                                label: (item) => item.dataset.yAxisID === 'cpu'
                                    ? ` CPU ${item.raw == null ? '—' : item.raw.toFixed(1) + '%'}`
                                    : ` ${fmt(item.raw)} ops/s`,
                                afterBody: (items) => {
                                    const avg = data[items[0].dataIndex].avg;
                                    return avg == null ? '' : ` ${avg.toFixed(1)} µs/call avg`;
                                },
                            },
                        },
                    },
                    scales: {
                        x: { grid: { display: false }, title: { display: true, text: 'sample' }, ticks: { maxRotation: 0, autoSkipPadding: 12 } },
                        cpu: { position: 'left', beginAtZero: true, suggestedMax: 100, ticks: { callback: (v) => v + '%' } },
                        ops: { position: 'right', beginAtZero: true, grid: { display: false }, ticks: { callback: fmt } },
                    },
                },
            });
        },

        mix(canvas, rows) {
            const top = rows.slice(0, 7);
            const rest = rows.slice(7).reduce((s, r) => s + r[1], 0);
            if (rest) top.push(['other', rest]);
            const palette = ['#ff4f44', '#ff8a3d', '#f2c14e', '#3fb950', '#2f81f7', '#a371f7', '#db61a2', '#6e7681'];
            return new Chart(canvas, {
                type: 'doughnut',
                data: {
                    labels: top.map((r) => r[0]),
                    datasets: [{ data: top.map((r) => r[1]), backgroundColor: palette, borderColor: css('--panel-bg'), borderWidth: 2 }],
                },
                options: {
                    ...baseOptions(),
                    cutout: '62%',
                    plugins: { legend: { position: canvas.parentElement.clientWidth < 420 ? 'bottom' : 'right', labels: { boxWidth: 10, boxHeight: 10, font: { family: 'ui-monospace, Menlo, monospace' } } } },
                },
            });
        },
    };

    function initCharts(root) {
        root.querySelectorAll('canvas[data-chart]').forEach((canvas) => {
            Chart.getChart(canvas)?.destroy();
            const data = readJSON(canvas.dataset.source);
            if (data && data.length) charts[canvas.dataset.chart](canvas, data);
        });
    }

    let selected = new URLSearchParams(location.search).get('sample');

    const tileFor = (index) => document.querySelector(`.tile[data-index="${index}"]`);

    // tiles are the source of truth, so Prev/Next keep working while new samples arrive
    function markActive() {
        document.querySelectorAll('.tile[data-index]').forEach((t) => t.classList.toggle('active', t.dataset.index === selected));
        document.querySelectorAll('#sample-detail [data-nav]').forEach((b) => {
            b.disabled = !tileFor(Number(selected) + Number(b.dataset.nav));
        });
    }

    // requests come from #sample-detail, not the tile, so a poll swapping tiles can't drop them
    function selectSample(index) {
        const tile = tileFor(index);
        if (!tile) return;
        selected = String(index);
        markActive();
        htmx.ajax('GET', tile.dataset.url, { target: '#sample-detail', source: '#sample-detail' }).then(() => {
            const detail = document.getElementById('sample-detail');
            if (detail.getBoundingClientRect().top > innerHeight * .6) detail.scrollIntoView({ behavior: 'smooth' });
        });
        const url = new URL(location.href);
        url.searchParams.set('sample', index);
        history.replaceState(null, '', url);
    }

    document.addEventListener('click', (e) => {
        const tile = e.target.closest('.tile[data-index]');
        const nav = e.target.closest('#sample-detail [data-nav]');
        if (tile) selectSample(tile.dataset.index);
        else if (nav) selectSample(Number(selected) + Number(nav.dataset.nav));
    });

    htmx.onLoad((el) => {
        initCharts(el);
        const detail = el.querySelector?.('[data-selected]') || (el.dataset?.selected ? el : null);
        if (detail) selected = detail.dataset.selected;
        markActive();
        el.querySelectorAll?.('[data-bs-toggle="tooltip"]').forEach((t) => bootstrap.Tooltip.getOrCreateInstance(t));
    });

    // arrow keys step through samples
    document.addEventListener('keydown', (e) => {
        if (e.target.closest('input, textarea, select') || e.metaKey || e.ctrlKey || e.altKey) return;
        const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
        if (step && selected && tileFor(Number(selected) + step)) { e.preventDefault(); selectSample(Number(selected) + step); }
    });

    document.getElementById('theme-toggle')?.addEventListener('click', () => {
        const next = document.documentElement.dataset.bsTheme === 'dark' ? 'light' : 'dark';
        document.documentElement.dataset.bsTheme = next;
        try { localStorage.setItem('theme', next); } catch (e) { }
        initCharts(document);
    });
})();
