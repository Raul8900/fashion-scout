// Read a product page in headless Chromium and print its structured data as JSON.
// Usage: node tools/pagefetch.js <url> [--shot out.png]
// Output: {status, url, title, jsonld:[...], og:{...}, sizes:{label:available}|null, text}
const { chromium } = require('playwright');

(async () => {
  const url = process.argv[2];
  const shotIdx = process.argv.indexOf('--shot');
  const shot = shotIdx > 0 ? process.argv[shotIdx + 1] : null;
  const out = { status: null, url, title: null, jsonld: [], og: {}, sizes: null, text: '' };
  const browser = await chromium.launch();
  try {
    const ctx = await browser.newContext({
      locale: 'en-IN',
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
      viewport: { width: 1366, height: 1000 },
    });
    const page = await ctx.newPage();
    const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    out.status = resp ? resp.status() : null;
    await page.waitForTimeout(6000);
    out.url = page.url();
    out.title = await page.title();
    out.jsonld = await page.$$eval('script[type="application/ld+json"]', ss => ss.map(s => {
      try { return JSON.parse(s.textContent); } catch (e) { return null; }
    }).filter(Boolean));
    out.og = await page.$$eval('meta[property^="og:"], meta[property^="product:"]', ms =>
      Object.fromEntries(ms.map(m => [m.getAttribute('property'), m.getAttribute('content')])));
    // Best-effort size buttons: many Indian stores render sizes as buttons/labels, disabled when sold out.
    out.sizes = await page.evaluate(() => {
      const re = /^(XXS|XS|S|M|L|XL|XXL|2XL|3XL|4XL|\d{2}|UK ?\d{1,2}(\.5)?|\d{1,2}(\.5)?)$/i;
      const res = {};
      const nodes = document.querySelectorAll('button, li, label, a, span, div');
      for (const n of nodes) {
        if (n.children.length > 2) continue;
        const t = (n.innerText || '').trim();
        if (!re.test(t) || t.length > 6) continue;
        const cls = (n.className && n.className.toString()) || '';
        const dis = n.disabled || n.getAttribute('aria-disabled') === 'true' ||
          /disabled|sold|unavailable|out-of-stock|oos|strike/i.test(cls);
        if (!(t in res)) res[t] = !dis;
      }
      return Object.keys(res).length >= 2 ? res : null;
    });
    out.text = (await page.innerText('body')).replace(/\s+/g, ' ').slice(0, 4000);
    if (shot) await page.screenshot({ path: shot, fullPage: false });
  } catch (e) {
    out.error = String(e.message || e).split('\n')[0];
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify(out));
})();
