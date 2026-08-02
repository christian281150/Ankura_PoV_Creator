import { gzipSync } from 'node:zlib';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

const BUDGETS = {
  js: 200 * 1024,
  css: 20 * 1024,
};

const command = process.platform === 'win32' ? (process.env.ComSpec ?? 'cmd.exe') : 'npm';
const args = process.platform === 'win32' ? ['/d', '/s', '/c', 'npm.cmd run build'] : ['run', 'build'];
const build = spawnSync(command, args, {
  cwd: process.cwd(),
  stdio: 'inherit',
});
if (build.error) {
  console.error(`Unable to run production build: ${build.error.message}`);
  process.exit(1);
}
if (build.status !== 0) process.exit(build.status ?? 1);

function filesIn(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? filesIn(path) : [path];
  });
}

const assets = filesIn(join(process.cwd(), 'dist'));
const totals = Object.fromEntries(
  Object.keys(BUDGETS).map((extension) => [
    extension,
    assets
      .filter((file) => file.endsWith(`.${extension}`))
      .reduce((total, file) => total + gzipSync(readFileSync(file)).length, 0),
  ]),
);

const failures = Object.entries(BUDGETS).filter(([extension, budget]) => totals[extension] > budget);
for (const [extension, budget] of Object.entries(BUDGETS)) {
  console.log(`${extension.toUpperCase()}: ${(totals[extension] / 1024).toFixed(1)} KB gzip (budget ${(budget / 1024).toFixed(0)} KB)`);
}

if (failures.length > 0) {
  for (const [extension, budget] of failures) {
    console.error(`${extension.toUpperCase()} bundle exceeds its ${(budget / 1024).toFixed(0)} KB gzip budget.`);
  }
  process.exit(1);
}
