import { TimeRange } from './timerange.js';
import { ChartManager } from './charts.js';
import API from './api.js';
import { handleApiError, showNotification } from './utils.js';

export class Dashboard {
    constructor() {
        this.charts = {};
        this.serverData = [];
        this.lastUpdate = new Date();
        this.updateInterval = 2000; // 2 seconds default
        this.initializeCharts();
        this.initializeEventListeners();
        this.startPerformanceMonitoring();
        this.initializeGridStack();
        this.initializePanelControls();
    }

    async initializeCharts() {
        // CPU Usage Chart
        this.charts.cpu = this.charts.createTimeSeriesChart('cpuChart', {
            title: 'CPU Usage',
            unit: '%',
            thresholds: [
                { value: 70, color: 'var(--warning-color)' },
                { value: 90, color: 'var(--error-color)' }
            ]
        });

        // Memory Usage Chart
        this.charts.memory = this.charts.createTimeSeriesChart('memoryChart', {
            title: 'Memory Usage',
            unit: '%',
            thresholds: [
                { value: 80, color: 'var(--warning-color)' },
                { value: 95, color: 'var(--error-color)' }
            ]
        });

        // Server Status Chart
        this.charts.status = this.charts.createPieChart('statusChart', {
            title: 'Server Status Distribution'
        });

        // Add new charts for network and disk
        this.charts.network = new Chart(
            document.getElementById('networkChart').getContext('2d'),
            {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Download (Mbps)',
                        data: [],
                        borderColor: '#2196F3'
                    }, {
                        label: 'Upload (Mbps)',
                        data: [],
                        borderColor: '#4CAF50'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false
                }
            }
        );

        this.charts.disk = new Chart(
            document.getElementById('diskChart').getContext('2d'),
            {
                type: 'doughnut',
                data: {
                    labels: ['Used', 'Free'],
                    datasets: [{
                        data: [0, 100],
                        backgroundColor: ['#FF5722', '#E0E0E0']
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false
                }
            }
        );
    }

    async startPerformanceMonitoring() {
        const updateMetrics = async () => {
            try {
                const metrics = await this.fetchPerformanceMetrics();
                this.updateDashboardMetrics(metrics);
                this.updateServerList();
            } catch (error) {
                console.error('Error updating metrics:', error);
            }
        };

        // Initial update
        await updateMetrics();

        // Set up interval for updates
        setInterval(updateMetrics, this.updateInterval);
    }

    async fetchPerformanceMetrics() {
        try {
            const response = await fetch('/api/metrics');
            if (!response.ok) throw new Error('Failed to fetch metrics');
            return await response.json();
        } catch (error) {
            console.error('Metrics fetch error:', error);
            throw error;
        }
    }

    updateDashboardMetrics(metrics) {
        // Update system overview
        document.getElementById('cpuUsage').textContent = `${metrics.cpu}%`;
        document.getElementById('memoryUsage').textContent = `${metrics.memory}%`;
        document.getElementById('totalServers').textContent = metrics.totalServers;
        document.getElementById('runningServers').textContent = metrics.runningServers;

        // Update charts
        this.updateChartData(this.charts.cpu, metrics.cpuHistory);
        this.updateChartData(this.charts.memory, metrics.memoryHistory);
        this.updateChartData(this.charts.network, metrics.networkHistory);
        this.updateChartData(this.charts.disk, metrics.diskUsage);

        // Update activity log
        this.updateActivityLog(metrics.recentActivity);
    }

    async updateServerList() {
        try {
            const serverList = document.getElementById('serverList');
            const template = document.getElementById('serverItemTemplate');
            const response = await fetch('/api/servers');
            const servers = await response.json();

            // Clear existing list
            serverList.innerHTML = '';

            servers.forEach(server => {
                const serverItem = template.content.cloneNode(true);
                
                // Update server item content
                serverItem.querySelector('.server-name').textContent = server.name;
                serverItem.querySelector('.server-status').textContent = server.status;
                serverItem.querySelector('.cpu-usage').textContent = `CPU: ${server.cpu}%`;
                serverItem.querySelector('.memory-usage').textContent = `RAM: ${server.memory}%`;
                serverItem.querySelector('.disk-usage').textContent = `Disk: ${server.disk}%`;
                serverItem.querySelector('.network-usage').textContent = `Net: ${server.network}`;

                // Add event listeners for server controls
                const controls = serverItem.querySelector('.server-controls');
                controls.querySelectorAll('.btn').forEach(button => {
                    button.addEventListener('click', () => {
                        const action = button.classList[1].replace('-btn', '');
                        this.controlServer(server.id, action);
                    });
                });

                serverList.appendChild(serverItem);
            });
        } catch (error) {
            console.error('Error updating server list:', error);
        }
    }

    async controlServer(serverId, action) {
        try {
            const response = await fetch('/api/server/control', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ serverId, action })
            });

            if (!response.ok) throw new Error('Server control action failed');

            // Update server list after action
            this.updateServerList();
            
            // Add to activity log
            this.addActivityLogEntry(`Server ${serverId} ${action} command sent`);

        } catch (error) {
            console.error('Server control error:', error);
            showNotification(`Failed to ${action} server: ${error.message}`, 'error');
        }
    }

    addActivityLogEntry(message) {
        const logContainer = document.getElementById('activityLog');
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
        logContainer.insertBefore(entry, logContainer.firstChild);

        // Keep only last 100 entries
        while (logContainer.children.length > 100) {
            logContainer.removeChild(logContainer.lastChild);
        }
    }

    initializeEventListeners() {
        // Server search
        document.getElementById('serverSearch')?.addEventListener('input', (e) => {
            this.filterServers(e.target.value);
        });

        // Status filter
        document.getElementById('statusFilter')?.addEventListener('change', (e) => {
            this.filterServers(document.getElementById('serverSearch').value, e.target.value);
        });

        // Refresh rate change
        document.getElementById('refreshRate')?.addEventListener('change', (e) => {
            this.updateInterval = parseInt(e.target.value) * 1000;
            this.restartPerformanceMonitoring();
        });
    }

    filterServers(searchText, status = 'all') {
        const servers = document.querySelectorAll('.server-item');
        servers.forEach(server => {
            const name = server.querySelector('.server-name').textContent.toLowerCase();
            const serverStatus = server.querySelector('.server-status').textContent.toLowerCase();
            const matchesSearch = name.includes(searchText.toLowerCase());
            const matchesStatus = status === 'all' || serverStatus === status;
            server.style.display = matchesSearch && matchesStatus ? '' : 'none';
        });
    }

    restartPerformanceMonitoring() {
        clearInterval(this.monitoringInterval);
        this.startPerformanceMonitoring();
    }

    initializeGridStack() {
        this.grid = GridStack.init({
            column: 12,
            cellHeight: 60,
            animate: true,
            draggable: {
                handle: '.panel-header'
            },
            resizable: {
                handles: 'e,se,s,sw,w'
            }
        });

        // Disable dragging by default
        this.setEditMode(false);
    }

    initializePanelControls() {
        const editBtn = document.querySelector('.edit-dashboard-btn');
        editBtn.addEventListener('click', () => {
            const isEditing = editBtn.classList.toggle('active');
            document.body.classList.toggle('dashboard-editing', isEditing);
            this.setEditMode(isEditing);
        });

        // Panel remove buttons
        document.querySelectorAll('.panel-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const item = e.target.closest('.grid-stack-item');
                this.grid.removeWidget(item);
            });
        });

        // Panel edit buttons
        document.querySelectorAll('.panel-edit').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const panel = e.target.closest('.visualization-card');
                this.openPanelEditor(panel);
            });
        });
    }

    setEditMode(enabled) {
        this.grid.enableMove(enabled);
        this.grid.enableResize(enabled);
    }

    openPanelEditor(panel) {
        // Implement panel editor modal
        console.log('Edit panel:', panel);
    }

    // Save dashboard layout
    saveDashboardLayout() {
        const layout = this.grid.save();
        localStorage.setItem('dashboardLayout', JSON.stringify(layout));
    }

    // Load dashboard layout
    loadDashboardLayout() {
        const savedLayout = localStorage.getItem('dashboardLayout');
        if (savedLayout) {
            this.grid.load(JSON.parse(savedLayout));
        }
    }
}
