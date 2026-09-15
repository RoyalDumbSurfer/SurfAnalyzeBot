// Requires a test-only Playwright installation. Set SURFANALYZE_PLAYWRIGHT_MODULE
// to its module directory; optional SURFANALYZE_BROWSER_ENGINE=webkit and
// SURFANALYZE_BROWSER_EXECUTABLE for a system Chromium/Edge binary.
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
        let expectedFrameNote = 'Frame eight';
        for (const width of [390, 320]) {
            const height = 844;
            const context = await browser.newContext({viewport:{width,height}, isMobile:true, hasTouch:true});
            await context.addCookies([
                {name:'surfanalyze_account', value:config.cookie, url:config.baseUrl, httpOnly:true, sameSite:'Lax'},
                {name:'surfanalyze_language', value:'en', url:config.baseUrl}
            ]);
            const page = await context.newPage();
            const errors = [];
            page.on('pageerror', error => errors.push(error.message));
            await page.route('https://telegram.org/**', route => route.fulfill({body:''}));
            await page.goto(config.baseUrl + '/result/' + config.jobId);
            const knowledge = page.locator('#coach-knowledge-used');
            assert.equal(await knowledge.isVisible(), true);
            await knowledge.locator('summary').click();
            assert.match(await knowledge.textContent(), /Background guidance/);
            assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
            await knowledge.locator('summary').click();
            const summary = page.locator('#coach-review-summary');
            assert.equal(await summary.isVisible(), true, 'Saved summary must be visible on ' + page.url());
            assert.equal(await page.locator('#coach-review-editor').getAttribute('open'), null);
            assert.equal(await page.locator('#coach-review-edit').textContent(), 'Edit Coach Review');
            assert.equal(await page.locator('[data-coach-field]').evaluateAll(fields => fields.every(el => el.value === '')), true);
            await page.locator('#coach-review-edit').click();
            const comment = 'Saved on mobile <img src=x onerror=alert(1)>';
            await page.locator('#coach-general-comment').fill(comment);
            assert.deepEqual(errors, []);
            const saved = page.waitForResponse(response => response.url().includes('/api/coach-reviews/') && response.request().method() === 'POST');
            await page.locator('#coach-review-form button[type="submit"]').click();
            assert.equal((await saved).status(), 200, 'Local authenticated save must succeed');
            await page.waitForFunction(() => !document.getElementById('coach-review-editor').open);
            assert.equal(await page.locator('#coach-summary-comment-text').textContent(), comment);
            assert.equal(await summary.locator('img,script,form,textarea').count(), 0);
            assert.equal(await summary.isVisible(), true);
            await page.reload();
            assert.equal(await page.locator('#coach-summary-comment-text').textContent(), comment);
            assert.equal(await page.locator('#coach-review-editor').getAttribute('open'), null);

            async function closeInViewport() {
                const bounds = await page.locator('[data-frame-viewer-close]').boundingBox();
                const viewport = await page.evaluate(() => ({top:visualViewport.offsetTop, height:visualViewport.height, width:visualViewport.width}));
                assert.ok(bounds && bounds.y >= viewport.top && bounds.y + bounds.height <= viewport.top + viewport.height);
                assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= viewport.width);
                assert.ok(bounds.width >= 44 && bounds.height >= 44);
                assert.equal(await page.locator('#frame-viewer').evaluate(el => el.parentElement === document.body), true);
                assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
            }
            for (const index of [0, 14, 7]) {
                const thumb = page.locator(`[data-frame-index="${index}"]`);
                await thumb.evaluate(el => el.scrollIntoView({block:'center'}));
                const before = await page.evaluate(() => scrollY);
                if (index === 14) assert.ok(before > 1500, 'Exercise a thumbnail far down the result page');
                await thumb.tap();
                await closeInViewport();
                assert.equal(await page.locator('body').evaluate(el => getComputedStyle(el).position), 'fixed');
                await page.locator('#coach-frame-panel summary').click();
                await closeInViewport();
                if (index === 7) {
                    assert.equal(await page.locator('#coach-frame-note').inputValue(), expectedFrameNote);
                    await page.locator('#coach-frame-note').fill('Updated frame eight');
                    await page.locator('#coach-frame-note').press('ArrowRight');
                    assert.match(await page.locator('#frame-viewer-title').textContent(), /8 \/ 15/);
                    await page.locator('#coach-frame-save').click();
                    await page.waitForFunction(() => !document.getElementById('coach-frame-save').disabled);
                    await page.locator('[data-frame-viewer-next]').click();
                    await page.locator('[data-frame-viewer-previous]').click();
                    assert.equal(await page.locator('#coach-frame-note').inputValue(), 'Updated frame eight');
                    expectedFrameNote = 'Updated frame eight';
                }
                // Reduced visual viewport models keyboard/browser-chrome changes.
                await page.setViewportSize({width, height:420});
                await closeInViewport();
                await page.setViewportSize({width,height});
                await closeInViewport();
                if (index === 14) await page.screenshot({path:path.join(config.output,`frame-far-down-${engine}-${width}.png`)});
                await page.locator('[data-frame-viewer-close]').tap();
                assert.equal(await page.locator('#frame-viewer').isVisible(), false);
                assert.ok(Math.abs(await page.evaluate(() => scrollY) - before) <= 2, 'Closing restores the opening scroll position');
                assert.equal(await thumb.evaluate(el => document.activeElement === el), true);
                assert.notEqual(await page.locator('body').evaluate(el => getComputedStyle(el).position), 'fixed');
            }
            await page.reload();
            assert.match(await page.locator('#coach-summary-notes').textContent(), /2$/);
            await page.locator('#coach-review-edit').click();
            await page.locator('#coach-save-draft').click();
            await page.waitForFunction(() => document.getElementById('coach-review-summary').hidden);
            await page.locator('#coach-review-form button[type="submit"]').click();
            await page.waitForFunction(() => !document.getElementById('coach-review-summary').hidden);
            assert.deepEqual(errors, []);
            await context.close();
        }
        console.log('Mobile summary, escaping, distant-frame close, resize, note/navigation and scroll restoration passed.');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
