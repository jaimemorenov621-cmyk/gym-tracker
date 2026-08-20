let endTime = null;
let intervalId = null;

function tick() {
    if (endTime === null) return;
    const remaining = Math.round((endTime - Date.now()) / 1000);
    self.postMessage({ type: 'tick', remaining: remaining });
    if (remaining <= 0) {
        clearInterval(intervalId);
        intervalId = null;
        endTime = null;
    }
}

self.onmessage = function (e) {
    if (e.data.type === 'start') {
        endTime = e.data.endTime;
        if (intervalId) clearInterval(intervalId);
        tick();
        intervalId = setInterval(tick, 1000);
    } else if (e.data.type === 'stop') {
        endTime = null;
        if (intervalId) clearInterval(intervalId);
        intervalId = null;
    }
};
