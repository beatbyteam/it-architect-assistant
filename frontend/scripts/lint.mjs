import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const targets = [join(root, 'src'), join(root, 'tests')];
const problems = [];

function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const fullPath = join(dir, entry);
    const stats = statSync(fullPath);
    if (stats.isDirectory()) {
      walk(fullPath);
      continue;
    }
    if (!/\.(ts|tsx)$/.test(fullPath)) {
      continue;
    }
    const content = readFileSync(fullPath, 'utf8');
    const relative = fullPath.replace(`${root}/`, '');
    if (/console\.log\(/.test(content)) {
      problems.push(`${relative}: console.log is not allowed in committed frontend sources`);
    }
    if (/\t/.test(content)) {
      problems.push(`${relative}: tabs are not allowed`);
    }
  }
}

targets.forEach(walk);
if (problems.length) {
  console.error(problems.join('\n'));
  process.exit(1);
}
console.log('Frontend source lint checks passed.');
