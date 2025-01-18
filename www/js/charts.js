export class ChartManager {
    constructor() {
        this.charts = new Map();
        this.maxDataPoints = 20;
    }

    createTimeSeriesChart(elementId, options) {
        const ctx = document.getElementById(elementId)?.getContext('2d');
        if (!ctx) return null;

        const chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: options.title,
                    data: [],
                    borderColor: 'rgb(75, 192, 192)',
                    tension: 0.1,
                    fill: false
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        title: {
                            display: true,
                            text: options.unit
                        }
                    }
                },
                plugins: {
                    title: {
                        display: true,
                        text: options.title
                    }
                }
            }
        });

        this.charts.set(elementId, { chart, options });
        return chart;
    }

    createPieChart(elementId, options) {
        const ctx = document.getElementById(elementId)?.getContext('2d');
        if (!ctx) return null;

        const chart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['Running', 'Stopped', 'Error'],
                datasets: [{
                    data: [0, 0, 0],
                    backgroundColor: ['#4CAF50', '#FFA726', '#F44336']
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: options.title
                    }
                }
            }
        });

        this.charts.set(elementId, { chart, options });
        return chart;
    }

    updateCharts(stats, servers) {
        const timestamp = new Date().toLocaleTimeString();

        // Update CPU chart
        const cpuChart = this.charts.get('cpuChart')?.chart;
        if (cpuChart) {
            this.updateTimeSeriesData(cpuChart, timestamp, stats.cpuUsage);
        }

        // Update Memory chart
        const memChart = this.charts.get('memoryChart')?.chart;
        if (memChart) {
            this.updateTimeSeriesData(memChart, timestamp, stats.memoryUsage);
        }

        // Update Status chart
        const statusChart = this.charts.get('statusChart')?.chart;
        if (statusChart) {
            const statusCounts = servers.reduce((acc, server) => {
                acc[server.status]++;
                return acc;
            }, { Running: 0, Stopped: 0, Error: 0 });

            statusChart.data.datasets[0].data = [
                statusCounts.Running,
                statusCounts.Stopped,
                statusCounts.Error
            ];
            statusChart.update();
        }
    }

    updateTimeSeriesData(chart, label, value) {
        chart.data.labels.push(label);
        chart.data.datasets[0].data.push(value);

        if (chart.data.labels.length > this.maxDataPoints) {
            chart.data.labels.shift();
            chart.data.datasets[0].data.shift();
        }

        chart.update();
    }
}
