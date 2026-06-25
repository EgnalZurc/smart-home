import { postManualParam } from './api.js';
import { showToast } from '../components/toast.js';

// Optimistic UI queue for AC manual parameter changes.
// Sends changes sequentially; reverts UI on failure.
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

    // updateFn(value)  : applies optimistic change to UI immediately
    // revertFn(value)  : restores last known good value on failure
    enqueue(param, value, updateFn, revertFn) {
        updateFn(value); // optimistic
        this.queue.push({ param, value, revertFn });
        if (!this.processing) this._process();
    }

    async _process() {
        this.processing = true;
        while (this.queue.length > 0) {
            const { param, value, revertFn } = this.queue.shift();
            try {
                const data = await postManualParam(param, value);
                // Store acknowledged value
                if (param === 'mode')        this.lastAcknowledged.mode        = data.applied.mode;
                if (param === 'fan_speed')   this.lastAcknowledged.fan_speed   = data.applied.fan_speed;
                if (param === 'temperature') this.lastAcknowledged.temperature = data.applied.temperature;
            } catch {
                revertFn(this.lastAcknowledged[param]);
                showToast('Error updating ' + param, 'error');
            }
        }
        this.processing = false;
    }
}
