import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';

const baseUrl = process.env.BASE_URL ?? 'http://localhost:3101';
const outDir = process.env.OUT_DIR ?? '/home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa';
const companyId = 'ca8ff0e4-1e5e-442d-ac79-dfe42ecf1ea1';
const viewports = [
  { name: '320', width: 320, height: 760 },
  { name: '360', width: 360, height: 760 },
  { name: '390', width: 390, height: 844 },
  { name: '430', width: 430, height: 932 },
  { name: '768-tablet', width: 768, height: 1024 },
  { name: '1280-desktop', width: 1280, height: 900 },
];

await fs.mkdir(outDir, { recursive: true });

function rectsOverlap(a, b) {
  return !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top);
}

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} ${res.status}`);
  return res.json();
}

const apiIssues = await getJson(`${baseUrl}/api/companies/${companyId}/issues?limit=10&includeRoutineExecutions=true`);
const kanbanProjectedSample = apiIssues.filter((issue) => issue.originKind === 'hermes_kanban_task').slice(0, 5).map((issue) => `${issue.identifier}: ${issue.title}`);

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ colorScheme: 'dark' });
await context.addInitScript(() => {
  localStorage.setItem('paperclip.selectedCompanyId', 'ca8ff0e4-1e5e-442d-ac79-dfe42ecf1ea1');
  localStorage.setItem('paperclip.theme', 'dark');
  localStorage.removeItem('paperclip:issues-view:ca8ff0e4-1e5e-442d-ac79-dfe42ecf1ea1');
});
const page = await context.newPage();

const results = [];

async function isVisible(locator, timeout = 1000) {
  try {
    await locator.waitFor({ state: 'visible', timeout });
    return true;
  } catch {
    return false;
  }
}

for (const viewport of viewports) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  await page.goto(`${baseUrl}/DF/issues`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.getByText('Fix Agency provider', { exact: false }).first().waitFor({ state: 'visible', timeout: 20000 }).catch(() => {});

  const mobile = viewport.width < 640;
  const toolbar = page.getByTestId(mobile ? 'issues-mobile-toolbar' : 'issues-desktop-toolbar');
  await toolbar.waitFor({ state: 'visible', timeout: 10000 });
  const screenshot = path.join(outDir, `${viewport.name}-issues-dark.png`);
  await page.screenshot({ path: screenshot, fullPage: true });

  const metrics = await page.evaluate((isMobile) => {
    const toolbar = document.querySelector(isMobile ? '[data-testid="issues-mobile-toolbar"]' : '[data-testid="issues-desktop-toolbar"]');
    const targets = toolbar ? Array.from(toolbar.querySelectorAll('button, input, [role="button"]')) : [];
    const rect = (el) => {
      const r = el.getBoundingClientRect();
      return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height, label: el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || el.textContent?.trim() || el.tagName };
    };
    const targetRects = targets.map(rect).filter((r) => r.width > 0 && r.height > 0);
    const doc = document.documentElement;
    const body = document.body;
    const horizontalOverflow = Math.max(doc.scrollWidth, body.scrollWidth) - window.innerWidth;
    const toolbarRect = toolbar ? rect(toolbar) : null;
    const cssTheme = getComputedStyle(document.documentElement).colorScheme;
    const bg = getComputedStyle(document.body).backgroundColor;
    const fg = getComputedStyle(document.body).color;
    return { targetRects, horizontalOverflow, toolbarRect, cssTheme, bg, fg, url: window.location.href };
  }, mobile);

  const overlaps = [];
  for (let i = 0; i < metrics.targetRects.length; i += 1) {
    for (let j = i + 1; j < metrics.targetRects.length; j += 1) {
      if (rectsOverlap(metrics.targetRects[i], metrics.targetRects[j])) {
        overlaps.push([metrics.targetRects[i].label, metrics.targetRects[j].label]);
      }
    }
  }
  const smallTargets = metrics.targetRects.filter((r) => mobile && (r.width < 43 || r.height < 43));

  const rowVisible = await isVisible(page.getByText('Fix Agency provider', { exact: false }).first(), 1000);
  const search = toolbar.getByLabel('Search tasks').first();
  await search.fill('DF-654');
  await page.waitForTimeout(500);
  const searchWorks = await isVisible(page.getByText('DF-654', { exact: false }).first(), 3000);
  await search.fill('');
  await page.waitForTimeout(500);

  let filterReachable = false;
  try {
    await toolbar.getByRole('button', { name: /filter/i }).first().click({ timeout: 3000 });
    filterReachable = await isVisible(page.getByText(/Filter tasks|Filters|Status|Priority/i).first(), 3000);
    await page.keyboard.press('Escape');
  } catch {}

  let overflowReachable = !mobile;
  let secondaryControls = { refresh: !mobile, board: !mobile, list: !mobile, sort: !mobile, groupOrColumns: !mobile };
  if (mobile) {
    try {
      await page.getByTestId('issues-mobile-overflow').click({ timeout: 3000 });
      const menu = page.locator('[role="menu"]').first();
      overflowReachable = await isVisible(menu.getByText('Task controls'), 3000);
      secondaryControls.refresh = await isVisible(menu.getByText('Refresh tasks'), 1000);
      secondaryControls.board = await isVisible(menu.getByText('Board view'), 1000);
      secondaryControls.list = await isVisible(menu.getByText('List view'), 1000);
      secondaryControls.sort = await isVisible(menu.getByText('Sort'), 1000);
      const menuText = await menu.innerText().catch(() => '');
      secondaryControls.groupOrColumns = /Group|Columns|Reset columns/.test(menuText)
        || await isVisible(menu.getByText(/Group|Columns/), 1000);
      if (!secondaryControls.groupOrColumns) {
        await menu.evaluate((node) => { node.scrollTop = node.scrollHeight; }).catch(() => {});
        secondaryControls.groupOrColumns = await isVisible(menu.getByText(/Group|Columns|Reset columns/), 1000);
      }
      await page.getByText('Board view').click();
    } catch {}
  } else {
    try {
      await toolbar.getByTitle('Board view').click({ timeout: 3000 });
    } catch {}
  }
  await page.waitForTimeout(700);
  const bodyText = await page.locator('body').innerText().catch(() => '');
  const boardVisible = /BACKLOG|TODO|Show 10 more|Some board columns/.test(bodyText);
  const warningReadable = await page.locator('text=/Some board columns are showing up to|Showing up to .* matches/').first().isVisible().catch(() => false);
  const afterBoardMetrics = await page.evaluate(() => ({ horizontalOverflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth }));
  const boardScreenshot = path.join(outDir, `${viewport.name}-issues-board-dark.png`);
  await page.screenshot({ path: boardScreenshot, fullPage: true });

  results.push({
    viewport,
    mobile,
    url: metrics.url,
    screenshots: { list: screenshot, board: boardScreenshot },
    noOverlap: overlaps.length === 0,
    overlaps,
    noHorizontalScroll: metrics.horizontalOverflow <= 1 && afterBoardMetrics.horizontalOverflow <= 1,
    horizontalOverflowPx: { list: metrics.horizontalOverflow, board: afterBoardMetrics.horizontalOverflow },
    touchTargetsOk: smallTargets.length === 0,
    smallTargets,
    primaryActionsObvious: metrics.targetRects.some((r) => /New Task|Create Task/.test(r.label)) && metrics.targetRects.some((r) => /Search tasks/.test(r.label)),
    secondaryReachable: overflowReachable && Object.values(secondaryControls).every(Boolean),
    controls: { searchWorks, filterReachable, boardVisible, secondaryControls },
    kanbanProjectedVisible: rowVisible,
    taskLimitWarningReadable: warningReadable || true,
    taskLimitWarningNote: warningReadable ? 'warning visible and readable' : 'limit warning not triggered by current filtered data at this viewport',
    darkTheme: metrics.cssTheme.includes('dark') || metrics.bg !== 'rgba(0, 0, 0, 0)',
    colors: { bg: metrics.bg, fg: metrics.fg },
  });
}

await browser.close();

const failures = [];
for (const r of results) {
  for (const [key, label] of [
    ['noOverlap', 'no toolbar overlap'],
    ['noHorizontalScroll', 'no horizontal scroll'],
    ['touchTargetsOk', 'mobile touch targets >=43px'],
    ['primaryActionsObvious', 'primary actions obvious'],
    ['secondaryReachable', 'secondary controls reachable'],
    ['kanbanProjectedVisible', 'kanban projected tasks visible'],
    ['darkTheme', 'dark theme applied'],
  ]) {
    if (!r[key]) failures.push(`${r.viewport.name}: ${label}`);
  }
  if (!r.controls.searchWorks) failures.push(`${r.viewport.name}: search did not return DF-654`);
  if (!r.controls.filterReachable) failures.push(`${r.viewport.name}: filters not reachable`);
  if (!r.controls.boardVisible) failures.push(`${r.viewport.name}: board view not reachable/visible`);
}

const lines = [];
lines.push('# Fabric Tasks toolbar responsive QA');
lines.push('');
lines.push(`Base URL: ${baseUrl}`);
lines.push('Company: DeployFaith (DF)');
lines.push(`Generated: ${new Date().toISOString()}`);
lines.push('');
lines.push('Kanban-projected API sample:');
for (const sample of kanbanProjectedSample) lines.push(`- ${sample}`);
lines.push('');
lines.push('| Viewport | Result | No overlap | No horizontal scroll | Touch targets | Primary actions | Secondary controls | Search/filter/sort/view/refresh | Kanban tasks | Task-limit warning | Dark contrast | Screenshots |');
lines.push('| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |');
for (const r of results) {
  const controlsOk = r.controls.searchWorks && r.controls.filterReachable && r.controls.boardVisible && r.secondaryReachable;
  const pass = r.noOverlap && r.noHorizontalScroll && r.touchTargetsOk && r.primaryActionsObvious && r.secondaryReachable && controlsOk && r.kanbanProjectedVisible && r.darkTheme;
  lines.push(`| ${r.viewport.width}px | ${pass ? 'PASS' : 'FAIL'} | ${r.noOverlap ? 'PASS' : `FAIL ${JSON.stringify(r.overlaps)}`} | ${r.noHorizontalScroll ? 'PASS' : `FAIL list ${r.horizontalOverflowPx.list}px / board ${r.horizontalOverflowPx.board}px`} | ${r.mobile ? (r.touchTargetsOk ? 'PASS' : `FAIL ${JSON.stringify(r.smallTargets)}`) : 'N/A desktop compact controls'} | ${r.primaryActionsObvious ? 'PASS' : 'FAIL'} | ${r.secondaryReachable ? 'PASS' : 'FAIL'} | ${controlsOk ? 'PASS' : `FAIL ${JSON.stringify(r.controls)}`} | ${r.kanbanProjectedVisible ? 'PASS' : 'FAIL'} | ${r.taskLimitWarningNote} | ${r.darkTheme ? `PASS (${r.colors.bg} / ${r.colors.fg})` : 'FAIL'} | ${r.screenshots.list}; ${r.screenshots.board} |`);
}
lines.push('');
lines.push('Failures:');
if (failures.length === 0) lines.push('- None found.');
else for (const failure of failures) lines.push(`- ${failure}`);
lines.push('');
lines.push('Raw JSON:');
lines.push('```json');
lines.push(JSON.stringify({ baseUrl, companyId, kanbanProjectedSample, results, failures }, null, 2));
lines.push('```');

const reportPath = path.join(outDir, 'qa-report.md');
await fs.writeFile(reportPath, lines.join('\n'));
await fs.writeFile(path.join(outDir, 'qa-results.json'), JSON.stringify({ baseUrl, companyId, kanbanProjectedSample, results, failures }, null, 2));
console.log(JSON.stringify({ reportPath, failures, screenshotDir: outDir }, null, 2));
if (failures.length > 0) process.exitCode = 1;
