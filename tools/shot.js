// Screenshot a local HTML file (full page). Usage: node tools/shot.js page.html out.png
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1320, height: 900 } });
  await p.goto('file://' + process.argv[2], { waitUntil: 'networkidle', timeout: 120000 }).catch(() => {});
  await p.waitForTimeout(1500);
  await p.screenshot({ path: process.argv[3], fullPage: true });
  await b.close();
})();
