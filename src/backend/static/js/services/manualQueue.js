import { postManualParam } from './api.js';
import { showToast } from '../components/toast.js';

// Optimistic UI queue for AC manual parameter changes.
// Sends changes sequentially; reverts UI on failure.
// Calls successFn(data) on success so callers can show a contextual toast.
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

    // updateFn(value)   : applies optimistic change to UI immediately
    // revertFn(value)   : restores last known good value on failure
    // successFn(data)   : called after confirmed server response (optional)
    enqueue(param, value, updateFn, revertFn, successFn = null) {
        updateFn(value); // optimistic
        this.queue.push({ param, value, revertFn, successFn });
        if (!this.processing) this._process();
    }

    async _process() {
        this.processing = true;
        while (this.queue.length > 0) {
            const { param, value, revertFn, successFn } = this.queue.shift();
            try {
                const data = await postManualParam(param, value);
                // Store acknowledged value
                if (param === 'mode')        this.lastAcknowledged.mode        = data.applied.mode;
                if (param === 'fan_speed')   this.lastAcknowledged.fan_speed   = data.applied.fan_speed;
                if (param === 'temperature') this.lastAcknowledged.temperature = data.applied.temperature;
                // Notify caller of success
                if (successFn) successFn(data);
            } catch {
                revertFn(this.lastAcknowledged[param]);
                // Error toast shown by caller via revertFn or here as fallback
                showToast('Error: ' + param, 'error');
            }
        }
        this.processing = false;
    }
}
