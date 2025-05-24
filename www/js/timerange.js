export class TimeRange {
    constructor() {
        this.range = '1h';
        this.ranges = {
            '1h': 3600,
            '6h': 21600,
            '24h': 86400,
            '7d': 604800
        };
    }

    setRange(range) {
        if (this.ranges[range]) {
            this.range = range;
            return true;
        }
        return false;
    }

    getSeconds() {
        return this.ranges[this.range];
    }

    getStartTime() {
        return Date.now() - (this.getSeconds() * 1000);
    }
}
