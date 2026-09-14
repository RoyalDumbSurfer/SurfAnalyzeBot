const fs = require('node:fs');
const assert = require('node:assert/strict');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
const playwright = require(process.env.SURFANALYZE_PLAYWRIGHT_MODULE);
(async () => {
    const engine = process.env.SURFANALYZE_BROWSER_ENGINE || 'chromium';
    const browser = await playwright[engine].launch({headless: true,
        ...(process.env.SURFANALYZE_BROWSER_EXECUTABLE ? {executablePath: process.env.SURFANALYZE_BROWSER_EXECUTABLE} : {})});
    try {
        const context = await browser.newContext({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true});
        await context.addCookies([{name: 'surfanalyze_account', value: config.cookie, url: config.baseUrl},
            {name: 'surfanalyze_language', value: 'en', url: config.baseUrl}]);
        await context.route('**/telegram-web-app.js', route => route.abort());
        // Do not write test bearer links into the operator's OS clipboard.
        await context.addInitScript(() => Object.defineProperty(navigator, 'clipboard', {value: {
            async writeText(value) { window.testCopied = value; }
        }, configurable: true}));
        const page = await context.newPage();
        await page.goto(config.baseUrl + '/dashboard');
        await page.getByRole('link', {name: 'Admin', exact: true}).click();
        assert.equal(new URL(page.url()).pathname, '/admin/invites');
        await page.locator('#invite-label').fill('Mobile tester');
        await page.locator('#create-invite').click();
        await page.locator('#invite-result').waitFor({state: 'visible'});
        const link = await page.locator('#invite-link').inputValue();
        assert.equal(new URL(link).origin, 'https://surfanalyze.com');
        await page.getByRole('heading', {name: 'Mobile tester', exact: true}).waitFor();
        await page.locator('#copy-invite').click();
        assert.equal(await page.evaluate(() => window.testCopied), link);
        await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', {value: undefined}));
        await page.locator('#copy-invite').click();
        assert.match(await page.locator('#invite-status').textContent(), /Select and copy/);
        const selection = await page.locator('#invite-link').evaluate(e => [e.selectionStart, e.selectionEnd]);
        assert.deepEqual(selection, [0, link.length]);
        for (const width of [390, 320]) {
            await page.setViewportSize({width, height: 844});
            assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Admin horizontal overflow');
            const box = await page.locator('#create-invite').boundingBox();
            assert.ok(box.height >= 44);
        }
        const recipient = await browser.newContext({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true});
        await recipient.addCookies([{name: 'surfanalyze_language', value: 'en', url: config.baseUrl}]);
        await recipient.route('**/telegram-web-app.js', route => route.abort());
        const registration = await recipient.newPage();
        const secondDevice = await browser.newContext({viewport: {width: 320, height: 740}, isMobile: true, hasTouch: true});
        await secondDevice.addCookies([{name: 'surfanalyze_language', value: 'en', url: config.baseUrl}]);
        await secondDevice.route('**/telegram-web-app.js', route => route.abort());
        const second = await secondDevice.newPage();
        const localLink = config.baseUrl + new URL(link).pathname + new URL(link).search;
        await second.goto(localLink);
        await registration.goto(config.baseUrl + new URL(link).pathname + new URL(link).search);
        assert.equal(registration.url(), config.baseUrl + '/register');
        assert.ok(!(await registration.content()).includes(new URL(link).searchParams.get('invite')));
        const leaked = [];
        registration.on('request', r => { if ((r.headers().referer || '').includes('invite=')) leaked.push(r.url()); });
        let posts = 0;
        registration.on('request', r => {
            if (r.method() === 'POST' && new URL(r.url()).pathname === '/register') {
                assert.equal(r.headers().origin, config.baseUrl, 'Clean form must not send Origin: null');
                posts++;
            }
        });
        await registration.locator('#username').fill('alice');
        await registration.locator('#password').fill('a unique test passphrase');
        await Promise.all([registration.waitForNavigation(), registration.getByRole('button', {name: 'Create Account', exact: true}).click()]);
        assert.equal(posts, 1);
        assert.match(await registration.getByRole('alert').textContent(), /Unable to register/);
        await registration.reload();
        assert.equal(posts, 1, 'Rejected POST must redirect to GET before refresh');
        await registration.locator('#username').fill('mobile-tester');
        await registration.locator('#password').fill('a unique test passphrase');
        await Promise.all([registration.waitForURL('**/dashboard'), registration.getByRole('button', {name: 'Create Account', exact: true}).click()]);
        await registration.reload();
        await registration.goBack();
        await registration.goForward();
        assert.equal(posts, 2, 'Refresh/back/forward must not repeat registration POST');
        assert.equal(leaked.length, 0);
        assert.equal(await registration.locator('a[href="/admin"]').count(), 0);
        await second.locator('#username').fill('second-device');
        await second.locator('#password').fill('a unique test passphrase');
        await Promise.all([second.waitForNavigation(), second.getByRole('button', {name: 'Create Account', exact: true}).click()]);
        assert.match(await second.getByRole('alert').textContent(), /already been used/);
        await second.reload();
        assert.match(await second.getByRole('alert').textContent(), /already been used/);
        await page.reload();
        const used = page.locator('article').filter({has: page.getByRole('heading', {name: 'Mobile tester', exact: true})});
        assert.match(await used.textContent(), /Used[\s\S]*mobile-tester/);
        assert.equal(await used.getByRole('button', {name: 'Disable invite', exact: true}).count(), 0);
        await page.locator('#invite-label').fill('Disable on phone');
        await page.locator('#invite-expiry').selectOption('none');
        await page.locator('#create-invite').click();
        await page.locator('#invite-result').waitFor({state: 'visible'});
        const disabledLink = await page.locator('#invite-link').inputValue();
        const unused = page.locator('article').filter({has: page.getByRole('heading', {name: 'Disable on phone', exact: true})});
        await unused.waitFor();
        await unused.getByRole('checkbox').check();
        await Promise.all([page.waitForNavigation(), unused.getByRole('button', {name: 'Disable invite', exact: true}).click()]);
        assert.match(await page.getByRole('status').first().textContent(), /Invite disabled/);
        await second.goto(config.baseUrl + '/register' + new URL(disabledLink).search);
        assert.match(await second.getByRole('alert').textContent(), /disabled/);
        await second.goto(config.baseUrl + '/register?invite=' + config.expiredToken);
        assert.match(await second.getByRole('alert').textContent(), /expired/);
        await second.getByRole('button', {name: 'RU', exact: true}).click();
        await second.getByRole('alert').filter({hasText: 'Срок действия этого инвайта истёк.'}).waitFor();
        assert.ok(await second.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Registration horizontal overflow');
        await page.getByRole('button', {name: 'RU', exact: true}).click();
        await page.getByRole('heading', {name: 'Приглашения', exact: true}).waitFor();
        assert.equal(new URL(page.url()).pathname, '/admin/invites');
        await page.screenshot({path: config.output + '/invites-mobile.png', fullPage: true});
        await second.screenshot({path: config.output + '/invite-expired-mobile.png', fullPage: true});
        console.log(engine + ': create, copy/fallback, list, expiry, disable, registration PRG, history, two-device replay, RU/EN and 320px overflow checks passed.');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
