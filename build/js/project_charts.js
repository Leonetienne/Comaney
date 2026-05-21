import Chart from 'chart.js/auto';

const PALETTE = [
    '#4e79a7','#f28e2b','#e15759','#76b7b2','#59a14f',
    '#edc948','#b07aa1','#ff9da7','#9c755f','#bab0ac',
    '#86bcb6','#f1ce63','#d4a6c8','#a0cbe8','#ffbe7d',
];

let _lineChart = null;
let _barChart  = null;

function _isDark() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function _fmtDate(iso) {
    const d   = new Date(iso + 'T00:00:00');
    const day = String(d.getDate()).padStart(2, '0');
    const mon = d.toLocaleString('en', { month: 'short' });
    return `${day}. ${mon}`;
}

function _applyDefaults(dark) {
    Chart.defaults.color       = dark ? '#888' : '#666';
    Chart.defaults.borderColor = dark ? '#333' : '#e8e8e8';
}

function _renderLine(data, currency) {
    const canvas = document.getElementById('proj-spending-line');
    if (!canvas || !data || !data.labels || !data.labels.length) return;
    if (_lineChart) { _lineChart.destroy(); _lineChart = null; }

    const dark = _isDark();
    _applyDefaults(dark);

    const labels   = data.labels;
    const datasets = data.series.map((s, i) => {
        // series[0] is "Total" – given an explicit neutral color from Python
        const color = s.color || PALETTE[(i - 1 + PALETTE.length) % PALETTE.length];
        return {
            label:            s.label,
            data:             s.values,
            borderColor:      color,
            backgroundColor:  color + '28',
            borderWidth:      2,
            pointRadius:      labels.length > 60 ? 0 : 2,
            pointHoverRadius: 4,
            tension:          0.35,
            fill:             false,
        };
    });

    canvas.style.width  = '100%';
    canvas.style.height = '220px';

    _lineChart = new Chart(canvas, {
        type: 'line',
        data: { labels, datasets },
        options: {
            animation:             false,
            responsive:            true,
            maintainAspectRatio:   false,
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 12, padding: 12, font: { size: 11 } } },
                tooltip: { callbacks: {
                    title: items  => _fmtDate(labels[items[0].dataIndex]),
                    label: c      => ` ${c.dataset.label}: ${c.parsed.y.toFixed(2)} ${currency}`,
                }},
            },
            scales: {
                x: {
                    ticks: {
                        maxTicksLimit: 8,
                        maxRotation:   45,
                        minRotation:   20,
                        callback: (_v, idx) => _fmtDate(labels[idx]),
                    },
                    grid: { display: false },
                },
                y: { ticks: { font: { size: 11 } } },
            },
        },
    });
}

function _renderBar(data, currency) {
    const canvas = document.getElementById('proj-tag-bar');
    if (!canvas || !data || !data.labels || !data.labels.length) return;
    if (_barChart) { _barChart.destroy(); _barChart = null; }

    const dark = _isDark();
    _applyDefaults(dark);

    const n      = data.labels.length;
    const colors = Array.from({ length: n }, (_, i) => PALETTE[i % PALETTE.length]);

    // Drive height from the wrapper so maintainAspectRatio:false fills it correctly
    const wrap = canvas.closest('.proj-chart-wrap');
    const h    = Math.max(80, n * 32);
    if (wrap) wrap.style.height = h + 'px';
    canvas.style.width  = '100%';
    canvas.style.height = '100%';

    _barChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: data.labels,
            datasets: [{
                data:               data.values,
                backgroundColor:    colors,
                borderRadius:       3,
                borderSkipped:      false,
                categoryPercentage: 0.85,
                barPercentage:      0.9,
            }],
        },
        options: {
            animation:           false,
            indexAxis:           'y',
            responsive:          true,
            maintainAspectRatio: false,
            plugins: {
                legend:  { display: false },
                tooltip: { callbacks: { label: c => ` ${c.parsed.x.toFixed(2)} ${currency}` } },
            },
            scales: {
                y: { grid: { display: false }, ticks: { font: { size: 11 }, autoSkip: false } },
            },
        },
    });
}

function renderProjectCharts() {
    const cfg = window.PROJECT_CHARTS;
    if (!cfg) return;
    _renderLine(cfg.spendingOverTime, cfg.currency);
    _renderBar(cfg.tagDist, cfg.currency);
}

document.addEventListener('DOMContentLoaded', renderProjectCharts);

window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (_lineChart) { _lineChart.destroy(); _lineChart = null; }
    if (_barChart)  { _barChart.destroy();  _barChart  = null; }
    renderProjectCharts();
});
