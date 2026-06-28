import { postManualParam } from './api.js';
import { showToast } from '../components/toast.js';

// Manual control queue for AC parameter changes.
// Sends changes sequentially and shows toast on result.
// Does NOT update the UI optimistically - the UI reflects server state only,
// updated on the next poll cycle (every 5s).
export class ManualControlQueue {
    constructor() {
        this.queue = [];
        this.processing = false;
        this.lastAcknowledged = {
            mode: 'cool',
            fan_speed: 0,
            temperature: 23.0,
        };
    }

    // successFn(): called after confirmed server response (for toast)
    // errorFn():   called on failure (for toast)
    enqueue(param, value, successFn = null, errorFn = null) {
        this.queue.push({ param, value, successFn, errorFn });
        if (!this.processing) this._process();
    }

    async _process() {
        this.processing = true;
        while (this.queue.length > 0) {
            const { param, value, successFn, errorFn } = this.queue.shift();
            try {
                const data = await postManualParam(param, value);
                if (param === 'mode')        this.lastAcknowledged.mode        = data.applied.mode;
                if (param === 'fan_speed')   this.lastAcknowledged.fan_speed   = data.applied.fan_speed;
                if (param === 'temperature') this.lastAcknowledged.temperature = data.applied.temperature;
                if (successFn) successFn(data);
            } catch {
                if (errorFn) errorFn();
                else showToast('Error: ' + param, 'error');
            }
        }
        this.processing = false;
    }
}
