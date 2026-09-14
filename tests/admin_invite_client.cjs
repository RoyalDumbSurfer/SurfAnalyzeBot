const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

(async () => {
    const elements = {};
    for (const id of ['create-invite-form', 'create-invite', 'invite-link', 'invite-status', 'invite-result', 'copy-invite']) {
        elements[id] = {
            handlers: {}, value: '', hidden: true,
            addEventListener(event, callback) { this.handlers[event] = callback; },
            focus() { this.focused = true; },
            select() { this.selected = true; },
            setSelectionRange(start, end) { this.selection = [start, end]; },
        };
    }
    elements['create-invite-form'].action = 'https://testserver/api/invites';
    const url = 'https://surfanalyze.com/register?invite=local-test-only';
    let mode = 'success';
    let copied;
    const navigator = {clipboard: {async writeText(value) { copied = value; }}};
    const context = {
        document: {getElementById(id) { return elements[id]; }, dispatchEvent() {}},
        Event: class {},
        navigator,
        FormData: class { constructor(form) { assert.equal(form, elements['create-invite-form']); } },
        async fetch(target, options) {
            assert.equal(target, elements['create-invite-form'].action);
            assert.equal(options.method, 'POST');
            assert.equal(options.credentials, 'same-origin');
            assert.equal(elements['create-invite'].disabled, true);
            if (mode === 'network') throw new Error('offline');
            return {status: mode === 'denied' ? 403 : 201, async json() { return {url}; }};
        },
    };
    vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), context);
    const submit = () => elements['create-invite-form'].handlers.submit({preventDefault() {}});
    await submit();
    assert.equal(elements['invite-link'].value, url);
    assert.equal(elements['invite-result'].hidden, false);
    assert.equal(elements['create-invite'].disabled, false);
    await elements['copy-invite'].handlers.click();
    assert.equal(copied, url);
    assert.ok(elements['invite-status'].textContent);
    const copiedMessage = elements['invite-status'].textContent;
    navigator.clipboard.writeText = async () => { throw new Error('Permission denied'); };
    await elements['copy-invite'].handlers.click();
    assert.equal(elements['invite-link'].selected, true);
    assert.deepEqual(elements['invite-link'].selection, [0, url.length]);
    assert.notEqual(elements['invite-status'].textContent, copiedMessage);
    delete navigator.clipboard;
    await elements['copy-invite'].handlers.click();
    assert.equal(elements['invite-link'].focused, true);
    for (mode of ['denied', 'network']) {
        await submit();
        assert.equal(elements['create-invite'].disabled, false);
        assert.ok(elements['invite-status'].textContent);
        assert.equal(elements['invite-link'].value, url);
    }
    console.log('Invite creation, copy, fallback, and error interactions passed');
})().catch(error => { console.error(error); process.exit(1); });
