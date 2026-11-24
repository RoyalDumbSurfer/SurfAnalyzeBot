const fs = require('node:fs');
const assert = require('node:assert/strict');
const playwright = require(process.env.SURFANALYZE_PLAYWRIGHT_MODULE);
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
(async () => {
  const browser = await playwright.chromium.launch({headless:true, executablePath:process.env.SURFANALYZE_BROWSER_EXECUTABLE});
  try {
    for (const width of [1280, 390, 320]) {
      const context = await browser.newContext({viewport:{width,height:900}});
      await context.addCookies([{name:'surfanalyze_account',value:config.cookie,url:config.baseUrl},
        {name:'surfanalyze_language',value:'en',url:config.baseUrl}]);
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(config.baseUrl+'/result/'+config.jobId);
      await page.locator('#director-editor').waitFor({state:'visible'});
      await page.waitForFunction(() => document.querySelector('video').readyState >= 1);
      await page.locator('video').evaluate(video => video.play());
      await page.locator('#director-cue-card').waitFor({state:'visible'});
      assert.equal(await page.locator('#director-still').isVisible(),true);
      assert.equal(await page.locator('#director-arrow-layer').isVisible(),true);
      const editor = page.locator('#director-editor');
      await editor.locator('input').first().fill('Coach approved '+width);
      assert.equal(await page.locator('#director-render').isDisabled(),true);
      const saved = page.waitForResponse(r => r.url().endsWith('/review') && r.request().method()==='POST');
      await page.locator('#director-save').click();
      assert.equal((await saved).status(),200);
      await page.reload();
      assert.equal(await editor.locator('input').first().inputValue(),'Coach approved '+width);
      const rendered = page.waitForResponse(r => r.url().includes('/render/') && r.request().method()==='POST');
      await page.locator('#director-render').click();
      assert.equal((await rendered).status(),200);
      await page.locator('#director-download').waitFor({state:'visible'});
      const downloading = page.waitForEvent('download');
      await page.locator('#director-download').click();
      const download = await downloading;
      await download.saveAs(config.output+'/coaching-'+width+'.mp4');
      assert.equal(await download.failure(),null);
      await page.locator('#director-add').click();
      assert.equal(await editor.locator('select').count(),2);
      await editor.getByRole('button',{name:'Delete moment'}).last().click();
      assert.equal(await editor.locator('select').count(),1);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({path:config.output+'/director-'+width+'.png',fullPage:true});
      await page.locator('#video-director').screenshot({path:config.output+'/director-panel-'+width+'.png'});
      assert.deepEqual(errors,[]);
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
