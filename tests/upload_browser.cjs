// Runs against the isolated Python fixture using Chromium or WebKit.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const playwright = require(process.env.SURFANALYZE_PLAYWRIGHT_MODULE);
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
(async () => {
    const engine = process.env.SURFANALYZE_BROWSER_ENGINE || 'chromium';
    const browser = await playwright[engine].launch({headless:true,
        ...(process.env.SURFANALYZE_BROWSER_EXECUTABLE ? {executablePath:process.env.SURFANALYZE_BROWSER_EXECUTABLE} : {})});
    try {
        for (const mobile of [false, true]) {
            for (const language of ['ru', 'en']) {
                const context = await browser.newContext({viewport:{width:mobile ? 390 : 1280,height:844}, isMobile:mobile, hasTouch:mobile});
                await context.addCookies([
                    {name:'surfanalyze_account',value:config.cookie,url:config.baseUrl},
                    {name:'surfanalyze_language',value:language,url:config.baseUrl}
                ]);
                const page = await context.newPage();
                const errors = [];
                page.on('pageerror', error => errors.push(error.message));
                await page.route('https://telegram.org/**', route => route.fulfill({body:''}));
                await page.goto(config.baseUrl);
                assert.match(await page.locator('body').innerText(), /100 MiB/);
                assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
                let posts = 0;
                page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/upload')) posts++; });
                await page.locator('#fileInput').setInputFiles(path.join(config.output, 'oversized.avi'));
                assert.equal(await page.locator('#uploadError').isVisible(), true);
                assert.match(await page.locator('#errorMessage').innerText(), /100 MiB/);
                await page.locator('#uploadButton').click();
                assert.equal(posts, 0);
                for (const name of ['normal.avi', 'boundary.avi']) {
                    await page.locator('#fileInput').setInputFiles(path.join(config.output, name));
                    assert.equal(await page.locator('#uploadError').isVisible(), false);
                    const response = page.waitForResponse(r => r.url().endsWith('/upload') && r.request().method() === 'POST');
                    await page.locator('#uploadButton').click();
                    assert.equal((await response).status(), 303);
                    await page.waitForURL('**/processing/**');
                    await page.goto(config.baseUrl);
                }
                assert.deepEqual(errors, []);
                console.log(`${engine} ${mobile ? 'mobile' : 'desktop'} ${language}: normal/exact 100 MiB accepted; oversized blocked; layout passed`);
                await context.close();
            }
        }
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
