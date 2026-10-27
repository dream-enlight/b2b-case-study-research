// Optional compatibility entry point. No npm packages required.
// The blank seed is already bundled; Python-only users can run build_seed.py.
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const result = spawnSync('python3', [fileURLToPath(new URL('./build_seed.py', import.meta.url))], {stdio:'inherit'});
if (result.error) throw result.error;
process.exit(result.status ?? 1);
