import { postManualParam } from './api.js';
import { showToast } from '../components/toast.js';

// Manual control queue for AC parameter changes.
// Tracks pending params to show loading state in UI until backend confirms.
// UI reflects server state; pending overlay shows the in-flight target value.
export class ManualControlQueue {
    constructor() {
        this.queue      = [];
        this.processing = false;
        // Last values confirmed by the server (from poll)
        this.lastAcknowledged = { mode: 'cool', fan_speed: 0, temperature: 23.0 };
        // Values currently in-flight (set on enqueue, cleared when poll confirms)
        this.pendingParams = new Map(); // param -> target value
        // Callbacks to render/clear pending state per param
        this._setPendingUI  = null;
        this._clearPendingUI = null;
    }

    registerUI(setPendingFn, clearPendingFn) {
        this._setPendingUI   = setPendingFn;
        this._clearPendingUI = clearPendingFn;
    }

    // Called when a new value arrives from the server poll.
    // If the polled value matches what we sent, clear pending state.
    onPollUpdate(param, serverValue) {
        if (!this.pendingParams.has(param)) return;
        const expected = this.pendingParams.get(param);
        // For temperature compare with tolerance (float rounding)
        const matches = param === 'temperature'
            ? Math.abs(serverValue - expected) < 0.15
            : serverValue === expected;
        if (matches) {
            this.pendingParams.delete(param);
            if (this._clearPendingUI) this._clearPendingUI(param);
        }
    }

    enqueue(param, value, successFn = null, errorFn = null) {
        this.pendingParams.set(param, value);
        if (this._setPendingUI) this._setPendingUI(param, value);
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
                // On error: clear pending immediately and revert label
                this.pendingParams.delete(param);
                if (this._clearPendingUI) this._clearPendingUI(param);
                if (errorFn) errorFn();
                else showToast('Error: ' + param, 'error');
            }
        }
        this.processing = false;
    }
}
