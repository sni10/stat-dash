// Copies the browser builds of the JS libraries into dashboard/static/dashboard/vendor (committed, served as is).
import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const target = join(here, '..', 'dashboard', 'static', 'dashboard', 'vendor');
mkdirSync(target, { recursive: true });

const files = {
  'alpine.min.js': 'node_modules/alpinejs/dist/cdn.min.js',
  'apexcharts.min.js': 'node_modules/apexcharts/dist/apexcharts.min.js',
};
for (const [name, source] of Object.entries(files)) {
  copyFileSync(join(here, source), join(target, name));
  console.log(`${source} -> dashboard/static/dashboard/vendor/${name}`);
}
