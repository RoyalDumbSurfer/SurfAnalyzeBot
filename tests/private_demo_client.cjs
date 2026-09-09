// Exercise the actual rendered upload script using a minimal DOM test double.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const script = JSON.parse(fs.readFileSync(0, 'utf8'));
function element() {
    const classes = new Set(['hidden']);
    return {
        files: [], textContent: '', disabled: false, handlers: {}, clicks: 0,
        classList: { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c) },
        addEventListener(name, fn) { this.handlers[name] = fn; },
        click() { this.clicks++; }
    };
}
const ids = ['dropZone', 'fileInput', 'fileName', 'uploadError', 'uploadButton', 'errorMessage', 'retryButton', 'uploadForm', 'uploadStatus'];
const elements = Object.fromEntries(ids.map(id => [id, element()]));
const windowEvents = {};
vm.runInNewContext(script, {
    document: { getElementById: id => elements[id] },
    window: { addEventListener: (name, fn) => { windowEvents[name] = fn; } }
});
const file = (name, size, type) => ({name, size, type});
function select(value) { elements.fileInput.files = [value]; elements.fileInput.handlers.change(); }
function submit() {
    let prevented = false;
    elements.uploadForm.handlers.submit({preventDefault() { prevented = true; }});
    return prevented;
}
assert.equal(submit(), true);
select(file('bad.txt', 10, 'text/plain'));
assert.equal(submit(), true);
assert.match(elements.errorMessage.textContent, /Unsupported/);
select(file('ride.mp4', 50 * 1024 * 1024 + 1, 'video/mp4'));
assert.equal(submit(), true);
assert.match(elements.errorMessage.textContent, /too large/);
select(file('ride.mp4', 0, 'video/mp4'));
assert.equal(submit(), true);
elements.dropZone.handlers.click();
assert.equal(elements.fileInput.clicks, 1);
elements.dropZone.handlers.keydown({key: 'Enter', preventDefault() {}});
assert.equal(elements.fileInput.clicks, 2);
elements.dropZone.handlers.drop({preventDefault() {}, dataTransfer: { files: [file('ride.mp4', 1024, 'video/mp4')] }});
assert.match(elements.fileName.textContent, /ride.mp4.*1.0 KiB/);
assert.equal(elements.uploadError.classList.contains('hidden'), true);
assert.equal(submit(), false);
assert.equal(elements.uploadButton.disabled, true);
assert.equal(elements.uploadStatus.classList.contains('hidden'), false);
assert.equal(submit(), true);
windowEvents.pageshow();
assert.equal(elements.uploadButton.disabled, false);
console.log('Upload JavaScript interactions passed');
