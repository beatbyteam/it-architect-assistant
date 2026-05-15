import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, rmSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const dist = join(root, '.test-dist');
const esbuildCli = join(root, 'node_modules', 'esbuild', 'bin', 'esbuild');
const esbuildCommand = process.platform === 'win32'
  ? join(root, 'node_modules', '.bin', 'esbuild.cmd')
  : esbuildCli;
const mode = process.argv[2] ?? 'unit';
const sourceDir = mode === 'smoke' ? join(root, 'tests', 'smoke') : join(root, 'tests');
const smokeSegment = `${sep}tests${sep}smoke${sep}`;
const matcher = mode === 'smoke'
  ? (file) => file.endsWith('.test.tsx') || file.endsWith('.test.ts')
  : (file) => (file.endsWith('.test.tsx') || file.endsWith('.test.ts')) && !file.includes(smokeSegment);

function walk(dir) {
  const files = [];
  for (const entry of readdirSync(dir)) {
    const absolute = join(dir, entry);
    const stats = statSync(absolute);
    if (stats.isDirectory()) {
      files.push(...walk(absolute));
      continue;
    }
    if (matcher(absolute)) files.push(absolute);
  }
  return files;
}

if (existsSync(dist)) {
  rmSync(dist, { recursive: true, force: true });
}
mkdirSync(dist, { recursive: true });

const testFiles = walk(sourceDir);
if (testFiles.length === 0) {
  console.error(`No ${mode} tests found.`);
  process.exit(1);
}

const outputFiles = [];
for (const file of testFiles) {
  const rel = relative(root, file).replace(/\.(tsx|ts)$/, '.cjs');
  const outfile = join(dist, rel);
  mkdirSync(dirname(outfile), { recursive: true });
  execFileSync(esbuildCommand, [
    file,
    '--bundle',
    '--platform=node',
    '--format=cjs',
    '--target=node20',
    '--jsx=automatic',
    '--log-override:empty-import-meta=silent',
    `--outfile=${outfile}`,
  ], {
    cwd: root,
    stdio: 'inherit',
  });
  outputFiles.push(relative(root, outfile));
}

execFileSync(process.execPath, ['--test', ...outputFiles], {
  cwd: root,
  stdio: 'inherit',
});
