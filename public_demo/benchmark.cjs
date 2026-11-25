const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { performance } = require("node:perf_hooks");

async function measure(browser, url, scenario) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  try {
    const page = await context.newPage();
    const failed = [];
    const requests = [];
    page.on("request", request => requests.push(request.url()));
    page.on("pageerror", error => failed.push(error.message));
    const session = await context.newCDPSession(page);
    await session.send("Network.enable");
    await session.send("Network.emulateNetworkConditions", {
      offline: false, latency: 70, downloadThroughput: 750000, uploadThroughput: 375000
    });
    await session.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    const start = performance.now();
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.locator("#evidence h3").waitFor();
    const ready = performance.now() - start;
    const bytes = await page.evaluate(() =>
      [...performance.getEntriesByType("navigation"), ...performance.getEntriesByType("resource")]
        .reduce((sum, entry) => sum + entry.encodedBodySize, 0));
    assert.match(await page.locator("#count").innerText(), new RegExp("of " + scenario.size + " "));
    // Bound bytes deterministically. Record timing separately because CI hosts vary.
    const byteBudget = scenario.size <= 1000 ? 180000 : 80000 + 32 * scenario.size;
    assert(bytes > 0 && bytes <= byteBudget, `Initial response bodies: ${bytes} bytes, budget ${byteBudget}`);
    const second = page.locator("#rows button").nth(1);
    const secondId = await second.getAttribute("data-id");
    await second.click();
    await page.getByRole("heading", { name: secondId, exact: true }).waitFor();
    const search = performance.now();
    await page.locator("#search").fill(scenario.expected.incident_id);
    await page.getByRole("heading", { name: scenario.expected.incident_id, exact: true }).waitFor();
    const searchMs = performance.now() - search;
    const downloading = page.waitForEvent("download");
    await page.locator("#download").click();
    const download = await downloading;
    const evidence = JSON.parse(fs.readFileSync(await download.path(), "utf8"));
    assert.deepEqual(evidence.incident, scenario.expected);
    assert.equal(download.suggestedFilename(), scenario.expected.incident_id + "-evidence.json");
    if (scenario.size > 1000) {
      // Exercise an uncached page and ensure a late fetch can't overwrite a newer selection.
      await page.locator("#search").fill("");
      const ids = await page.locator("#snapshot").evaluate(node => {
        const index = JSON.parse(node.textContent).index;
        return [index[Math.floor(index.length / 2)][0], index[0][0]];
      });
      let release;
      const paused = new Promise(resolve => { release = resolve; });
      let observed;
      const intercepted = new Promise(resolve => { observed = resolve; });
      await page.route("**/details/*.json", async route => {
        observed();
        await paused;
        await route.continue();
      }, {times: 1});
      await page.locator("#search").fill(ids[0]);
      await Promise.race([intercepted, page.waitForTimeout(5000)]);
      assert(await page.locator("#download").isDisabled());
      await page.locator("#search").fill(ids[1]);
      const response = page.waitForResponse(r => r.url().includes("/details/"));
      release();
      await (await response).finished();
      await page.getByRole("heading", {name: ids[1], exact: true}).waitFor();
    }
    await page.locator("#search").fill("");
    await page.locator("#next").click();
    await page.getByText(/^7–12 of /).waitFor();
    await page.locator("#priority").selectOption("Critical");
    await page.locator("#search").fill("no-such-incident");
    await page.getByText("0 incidents", {exact: true}).waitFor();
    assert(await page.locator("#download").isDisabled());
    assert(!requests.some(request => /stlite|pyodide|\.whl|demo\.zip/.test(request)));
    assert.deepEqual(failed, []);
    const heap = await session.send("Runtime.getHeapUsage");
    return {ready_ms: Math.round(ready), initial_bytes: bytes,
      search_and_evidence_ms: Math.round(searchMs), heap_used_mb: +(heap.usedSize / 1048576).toFixed(1)};
  } finally {
    await context.close();
  }
}

(async () => {
  const browser = await chromium.launch();
  try {
    for (const scenario of JSON.parse(fs.readFileSync(0, "utf8"))) {
      for (let run = 1; run <= Number(process.argv[3]); run++) {
        const result = await measure(browser, process.argv[2] + "/" + scenario.folder + "/", scenario);
        console.log(JSON.stringify({ rows: scenario.size, run, ...result }));
      }
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
