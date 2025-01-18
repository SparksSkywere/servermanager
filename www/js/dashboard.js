import { TimeRange } from './timerange.js';
import { ChartManager } from './charts.js';
import API from './api.js';
import { handleApiError, showNotification } from './utils.js';

export class Dashboard {
    constructor() {
        this.timeRange = new TimeRange();
        this.charts = new ChartManager();
        this.refreshRate = 10000; // 10 seconds
        this.init();
    }

    async init() {
        await this.setupCharts();
        this.startAutoRefresh();
        this.setupEventListeners();
        await this.refresh(); // Initial refresh
    }

    async setupCharts() {
        // CPU Usage Chart
        this.charts.createTimeSeriesChart('cpuChart', {
            title: 'CPU Usage',
            unit: '%',
            thresholds: [
                { value: 70, color: 'var(--warning-color)' },
                { value: 90, color: 'var(--error-color)' }
            ]
        });

        // Memory Usage Chart
        this.charts.createTimeSeriesChart('memoryChart', {
            title: 'Memory Usage',
            unit: '%',
            thresholds: [
                { value: 80, color: 'var(--warning-color)' },
                { value: 95, color: 'var(--error-color)' }
            ]
        });

        // Server Status Chart
        this.charts.createPieChart('statusChart', {
            title: 'Server Status Distribution'
        });
    }

    setupEventListeners() {
        document.getElementById('refreshRate')?.addEventListener('change', (e) => {
            this.refreshRate = parseInt(e.target.value) * 1000;
            this.startAutoRefresh();
        });

        document.getElementById('themeToggle').addEventListener('change', (e) => {
            document.documentElement.setAttribute('data-theme', 
                e.target.checked ? 'dark' : 'light');
        });
    }

    startAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
        this.refreshInterval = setInterval(() => this.refresh(), this.refreshRate);
    }

    async refresh() {
        try {
            const [stats, servers] = await Promise.all([
                API.getSystemStats(),
                API.getServers()
            ]);
            
            this.updateDashboardStats(stats);
            this.updateServerList(servers);
            this.charts.updateCharts(stats, servers);
        } catch (error) {
            handleApiError(error);
        }
    }

    updateDashboardStats(stats) {
        document.getElementById('totalServers').textContent = stats.totalServers;
        document.getElementById('runningServers').textContent = stats.runningServers;
        document.getElementById('cpuUsage').textContent = `${stats.cpuUsage.toFixed(1)}%`;
        document.getElementById('memoryUsage').textContent = `${stats.memoryUsage.toFixed(1)}%`;
    }

    updateServerList(servers) {
        const serverList = document.getElementById('serverList');
        if (!serverList) return;

        serverList.innerHTML = servers.map(server => `
            <div class="server-item ${server.status.toLowerCase()}">
                <div class="server-info">
                    <input type="checkbox" name="serverSelect" value="${server.name}">
                    <h4>${server.name}</h4>
                    <span class="status">${server.status}</span>
                </div>
                <div class="server-stats">
                    <span>CPU: ${server.cpuUsage}%</span>
                    <span>Memory: ${server.memoryUsage}%</span>
                    <span>Uptime: ${this.formatUptime(server.uptime)}</span>
                </div>
                <div class="server-actions">
                    <button onclick="controlServer('start', '${server.name}')" 
                            ${server.status === 'Running' ? 'disabled' : ''}>Start</button>
                    <button onclick="controlServer('stop', '${server.name}')"
                            ${server.status === 'Stopped' ? 'disabled' : ''}>Stop</button>
                    <button onclick="controlServer('restart', '${server.name}')"
                            ${server.status === 'Stopped' ? 'disabled' : ''}>Restart</button>
                </div>
            </div>
        `).join('');
    }

    formatUptime(seconds) {
        if (!seconds) return 'N/A';
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return `${days}d ${hours}h ${minutes}m`;
    }
}
