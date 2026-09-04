#!/usr/bin/env node
/**
 * Beekeeper Studio old-to-new state adapter.
 *
 * This adapter is deliberately intended for an ephemeral GitHub-hosted
 * Windows runner. It copies one portable build at a time into the same
 * isolated directory, seeds harmless SQLite-backed state through the UI, and
 * compares semantic database identities after the candidate starts.
 */

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import net from 'node:net';
import { spawn, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';


const SAVED_TITLE = 'StateGateRestoreQuery';
const SAVED_TEXT = 'select 1 as original_state_gate_text;';
const EDITED_TEXT = 'select 999 as retained_state_gate_edit;';


function parseArguments(argv) {
  const allowed = new Set(['mode', 'source-exe', 'profile', 'evidence']);
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith('--') || value === undefined) {
      throw new Error('arguments must be --name value pairs');
    }
    const name = key.slice(2);
    if (!allowed.has(name) || values[name] !== undefined) {
      throw new Error(`unknown or duplicate argument: ${key}`);
    }
    values[name] = value;
  }
  for (const required of allowed) {
    if (!values[required]) throw new Error(`missing --${required}`);
  }
  if (!['seed', 'verify'].includes(values.mode)) {
    throw new Error('--mode must be seed or verify');
  }
  return values;
}


function loadCustomerDependency(names) {
  const adapterRoot = path.dirname(fileURLToPath(import.meta.url));
  const searchRoots = [
    process.cwd(),
    path.join(process.cwd(), 'apps', 'studio'),
    adapterRoot,
  ];
  for (const root of searchRoots) {
    const requireFromRoot = createRequire(path.join(root, 'package.json'));
    for (const name of names) {
      try {
        return requireFromRoot(name);
      } catch (error) {
        if (error?.code !== 'MODULE_NOT_FOUND') throw error;
      }
    }
  }
  throw new Error(`required customer dependency is unavailable: ${names.join(' or ')}`);
}


function writeJsonAtomic(target, document) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const partial = `${target}.${process.pid}.${crypto.randomUUID()}.part`;
  try {
    fs.writeFileSync(partial, `${JSON.stringify(document, null, 2)}\n`, { flag: 'wx' });
    fs.renameSync(partial, target);
  } finally {
    if (fs.existsSync(partial)) fs.unlinkSync(partial);
  }
}


function fileWitness(filePath) {
  const bytes = fs.readFileSync(filePath);
  return {
    path: path.resolve(filePath),
    bytes: bytes.length,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
  };
}


function materializePortable(sourceExecutable, profile) {
  const source = path.resolve(sourceExecutable);
  if (!fs.statSync(source).isFile() || path.extname(source).toLowerCase() !== '.exe') {
    throw new Error('source artifact must be a Windows .exe file');
  }
  const applicationDirectory = path.join(path.resolve(profile), 'portable-application');
  fs.mkdirSync(applicationDirectory, { recursive: true });
  const activeExecutable = path.join(applicationDirectory, 'Beekeeper-Studio.exe');
  fs.copyFileSync(source, activeExecutable);
  return { activeExecutable, applicationDirectory };
}


async function dismissKnownFirstRunUi(window) {
  for (const label of ["Don't show again", 'Skip', 'Not now']) {
    try {
      await window.getByText(label, { exact: false }).first().click({ timeout: 800 });
    } catch {
      // Optional first-run surfaces vary between versions.
    }
  }
}


function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}


async function reserveLoopbackPort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : null;
      server.close((error) => {
        if (error) reject(error);
        else if (!port) reject(new Error('could not reserve a loopback debugging port'));
        else resolve(port);
      });
    });
  });
}


async function waitForCdp(port, child, timeoutMs) {
  const endpoint = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`portable wrapper exited before CDP became ready (code ${child.exitCode})`);
    }
    try {
      const response = await fetch(`${endpoint}/json/version`, { signal: AbortSignal.timeout(1000) });
      if (response.ok) return endpoint;
    } catch {
      // The portable wrapper needs time to extract and start the real app.
    }
    await delay(250);
  }
  throw new Error(`portable application CDP endpoint did not become ready within ${timeoutMs}ms`);
}


function waitForExit(child, timeoutMs) {
  if (!child || child.exitCode !== null) return Promise.resolve(true);
  return new Promise((resolve) => {
    const timeout = setTimeout(() => resolve(false), timeoutMs);
    child.once('exit', () => {
      clearTimeout(timeout);
      resolve(true);
    });
  });
}


function terminateExactProcessTree(child) {
  if (!child || child.exitCode !== null || !child.pid) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
      encoding: 'utf8',
      windowsHide: true,
      timeout: 15_000,
    });
  } else {
    child.kill('SIGKILL');
  }
}


async function launchPortable(playwright, activeExecutable, applicationDirectory) {
  const port = await reserveLoopbackPort();
  const child = spawn(activeExecutable, [
    '--enable-logging',
    '--remote-debugging-address=127.0.0.1',
    `--remote-debugging-port=${port}`,
  ], {
    env: {
      ...process.env,
      BEEKEEPER_DISABLE_UPDATES: '1',
      PORTABLE_EXECUTABLE_DIR: applicationDirectory,
    },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout?.resume();
  child.stderr?.resume();
  try {
    const endpoint = await waitForCdp(port, child, 45_000);
    const browser = await playwright.chromium.connectOverCDP(endpoint, { timeout: 45_000 });
    const context = browser.contexts()[0];
    if (!context) throw new Error('portable application exposed no browser context');
    let window = context.pages()[0];
    if (!window) window = await context.waitForEvent('page', { timeout: 45_000 });
    await window.setViewportSize({ width: 1600, height: 1000 });
    await dismissKnownFirstRunUi(window);
    return { application: { browser, child }, window };
  } catch (error) {
    terminateExactProcessTree(child);
    throw error;
  }
}


async function closeApplication(application) {
  if (!application) return;
  const { browser, child } = application;
  try {
    const session = await browser.newBrowserCDPSession();
    await session.send('Browser.close');
  } catch {
    // A process-tree fallback below handles versions without Browser.close.
  }
  const exitedGracefully = await waitForExit(child, 5000);
  try {
    await browser.close();
  } catch {
    // The remote browser may already be gone after Browser.close.
  }
  if (!exitedGracefully) terminateExactProcessTree(child);
  await delay(1500);
}


function databaseSnapshot(databasePath) {
  if (!fs.existsSync(databasePath)) throw new Error(`application database not found: ${databasePath}`);
  const helper = fileURLToPath(new URL('./beekeeper_db_snapshot.py', import.meta.url));
  const completed = spawnSync(
    'python',
    [helper, '--database', databasePath, '--title', SAVED_TITLE],
    { encoding: 'utf8', windowsHide: true, timeout: 30_000 }
  );
  if (completed.error) throw completed.error;
  if (completed.status !== 0) {
    throw new Error(`database snapshot failed: ${(completed.stderr || '').trim()}`);
  }
  return JSON.parse(completed.stdout);
}


function seedSnapshotPassed(snapshot) {
  return Boolean(
    snapshot.integrity.length === 1
      && snapshot.integrity[0] === 'ok'
      && snapshot.saved_queries.length === 1
      && snapshot.saved_queries[0].text === SAVED_TEXT
      && snapshot.linked_tabs.some((tab) => tab.unsavedQueryText === EDITED_TEXT)
      && snapshot.migrations.length > 0
      && snapshot.migrations_unique
  );
}


function compareSnapshots(before, after) {
  const beforeSaved = before.saved_queries[0];
  const afterSaved = after.saved_queries[0];
  const beforeTab = before.linked_tabs.find((tab) => tab.unsavedQueryText === EDITED_TEXT);
  const afterTab = after.linked_tabs.find((tab) => tab.unsavedQueryText === EDITED_TEXT);
  const oldMigrationsRetained = before.migrations.every((name) => after.migrations.includes(name));
  const checks = {
    database_integrity: after.integrity.length === 1 && after.integrity[0] === 'ok',
    one_saved_query: after.saved_queries.length === 1,
    saved_query_identity: Boolean(beforeSaved && afterSaved && beforeSaved.id === afterSaved.id),
    saved_query_meaning: Boolean(afterSaved && afterSaved.text === SAVED_TEXT),
    edited_tab_identity: Boolean(beforeTab && afterTab && beforeTab.id === afterTab.id),
    edited_tab_relation: Boolean(
      afterTab && afterSaved && afterTab.queryId === afterSaved.id && afterTab.connectionId === beforeTab.connectionId
    ),
    edited_tab_meaning: Boolean(afterTab && afterTab.unsavedQueryText === EDITED_TEXT),
    previous_migrations_retained: oldMigrationsRetained,
    migrations_not_duplicated: after.migrations_unique,
    migration_count_monotonic: after.migrations.length >= before.migrations.length,
  };
  return { passed: Object.values(checks).every(Boolean), checks };
}


async function seedState(window, profile) {
  const fixtureDirectory = path.join(path.resolve(profile), 'synthetic-fixture');
  fs.mkdirSync(fixtureDirectory, { recursive: true });
  const fixtureDatabase = path.join(fixtureDirectory, 'state-gate-source.sqlite');

  await window.getByLabel('Connection Type').selectOption('sqlite');
  await window.locator('#Database').fill(fixtureDatabase);
  await window.getByRole('button', { name: 'Connect' }).click();

  // Production releases seed and open a saved "Demo Query" on a fresh profile.
  // Saving that tab updates the existing favorite directly and never opens the
  // title modal. Create an explicit blank query first so this exercises the
  // same new-saved-query path as the upstream regression test.
  const querySurface = window.locator('#add-tab-group a.add-query, #tab-0 [role="textbox"]');
  await querySurface.first().waitFor({ state: 'visible', timeout: 30_000 });
  const addQuery = window.locator('#add-tab-group a.add-query');
  if (await addQuery.isVisible()) await addQuery.click();

  const activeEditor = window.locator('.tab-pane.active').getByRole('textbox');
  const editor = (await activeEditor.count()) > 0
    ? activeEditor.first()
    : window.locator('#tab-0').getByRole('textbox');
  await editor.waitFor({ state: 'visible', timeout: 30_000 });
  await editor.click();
  await editor.fill(SAVED_TEXT);
  await window.keyboard.press('Control+s');
  const titleInput = window.locator('input[name="title"]');
  await titleInput.waitFor({ state: 'visible', timeout: 10_000 });
  await titleInput.fill(SAVED_TITLE);
  await window.locator('form button[type="submit"].btn-primary').first().click();
  await window.waitForTimeout(1500);
  await editor.click();
  await editor.fill(EDITED_TEXT);
  await window.waitForTimeout(2500);
  return { fixtureDatabase, fixtureName: path.basename(fixtureDatabase) };
}


async function verifyState(window, fixtureName) {
  const recent = window.locator('.recent-connection-list').getByText(fixtureName, { exact: false }).first();
  await recent.waitFor({ state: 'visible', timeout: 20_000 });
  await recent.dblclick();
  const activeEditor = window.locator('.tab-pane.active').getByRole('textbox');
  const editor = (await activeEditor.count()) > 0
    ? activeEditor.first()
    : window.locator('#tab-0').getByRole('textbox');
  await editor.waitFor({ state: 'visible', timeout: 30_000 });
  await window.waitForTimeout(1500);
  const visibleText = (await editor.textContent()) || '';
  return {
    restored_edit_visible: visibleText.includes('retained_state_gate_edit'),
    original_text_not_substituted: !visibleText.includes('original_state_gate_text'),
  };
}


async function run(args) {
  const playwright = loadCustomerDependency(['@playwright/test', 'playwright']);
  if (!playwright.chromium) throw new Error('Playwright Chromium CDP support is unavailable');

  const profile = path.resolve(args.profile);
  const evidencePath = path.resolve(args.evidence);
  fs.mkdirSync(profile, { recursive: true });
  const { activeExecutable, applicationDirectory } = materializePortable(args['source-exe'], profile);
  const artifact = fileWitness(activeExecutable);
  const applicationDatabase = path.join(applicationDirectory, 'beekeeper_studio_data', 'app.db');
  const baselinePath = path.join(profile, 'beekeeper-state-gate-baseline.json');
  const fixtureName = 'state-gate-source.sqlite';
  let application;
  let window;
  try {
    ({ application, window } = await launchPortable(
      playwright, activeExecutable, applicationDirectory
    ));
    let ui;
    if (args.mode === 'seed') {
      ui = await seedState(window, profile);
    } else {
      if (!fs.existsSync(baselinePath)) throw new Error('seed baseline is missing from retained profile');
      ui = await verifyState(window, fixtureName);
    }
    const screenshotPath = path.join(path.dirname(evidencePath), `${args.mode}-beekeeper.png`);
    await window.screenshot({ path: screenshotPath, fullPage: false });
    await closeApplication(application);
    application = undefined;

    const snapshot = databaseSnapshot(applicationDatabase);
    if (args.mode === 'seed') {
      const passed = seedSnapshotPassed(snapshot);
      if (passed) writeJsonAtomic(baselinePath, snapshot);
      return {
        passed,
        mode: args.mode,
        artifact,
        ui,
        database: snapshot,
        screenshot: screenshotPath,
      };
    }

    const baseline = JSON.parse(fs.readFileSync(baselinePath, 'utf8'));
    const comparison = compareSnapshots(baseline, snapshot);
    const uiPassed = ui.restored_edit_visible && ui.original_text_not_substituted;
    return {
      passed: comparison.passed && uiPassed,
      mode: args.mode,
      artifact,
      ui: { ...ui, passed: uiPassed },
      semantic_comparison: comparison,
      database: snapshot,
      screenshot: screenshotPath,
    };
  } catch (error) {
    if (window) {
      const failureScreenshot = path.join(path.dirname(evidencePath), `${args.mode}-beekeeper-failure.png`);
      try {
        await window.screenshot({ path: failureScreenshot, fullPage: false });
        if (error && typeof error === 'object') error.stateGateScreenshot = failureScreenshot;
      } catch {
        // Preserve the original adapter error when screenshot capture also fails.
      }
    }
    throw error;
  } finally {
    await closeApplication(application);
  }
}


let parsed;
try {
  parsed = parseArguments(process.argv.slice(2));
  const evidence = await run(parsed);
  writeJsonAtomic(path.resolve(parsed.evidence), evidence);
  process.exitCode = evidence.passed ? 0 : 1;
} catch (error) {
  const evidence = {
    passed: false,
    mode: parsed?.mode || null,
    error: error instanceof Error ? error.message : String(error),
    screenshot: error?.stateGateScreenshot || null,
  };
  if (parsed?.evidence) writeJsonAtomic(path.resolve(parsed.evidence), evidence);
  console.error(JSON.stringify(evidence));
  process.exitCode = 1;
}
