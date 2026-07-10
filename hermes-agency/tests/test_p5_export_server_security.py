import json
import subprocess
import textwrap
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXPORTERS = [
    _REPO_ROOT / "hermes-agency/default_staff/profiles/agency-asset-artist/skills/creative/p5js/scripts/export-frames.js",
    _REPO_ROOT / "hermes-agency/default_staff/profiles/agency-environment-artist/skills/creative/p5js/scripts/export-frames.js",
    _REPO_ROOT / "hermes-agency/default_staff/profiles/agency-motion-designer/skills/creative/p5js/scripts/export-frames.js",
    _REPO_ROOT / "hermes-agency/default_staff/profiles/agency-technical-artist/skills/creative/p5js/scripts/export-frames.js",
]


def test_p5_export_server_blocks_sensitive_files_and_symlinks(tmp_path):
    outside_secret = tmp_path / "outside-secret.txt"
    outside_secret.write_text("outside secret", encoding="utf-8")

    harness = tmp_path / "exercise-export-server.js"
    harness.write_text(
        textwrap.dedent(
            r"""
            const fs = require('fs');
            const http = require('http');
            const path = require('path');
            const vm = require('vm');

            function loadExporter(exporterPath) {
              const source = fs.readFileSync(exporterPath, 'utf8').replace(
                /main\(\)\.catch\([\s\S]*$/,
                'module.exports = { serveSketchDirectory };'
              );
              const sandbox = {
                require: (name) => name === 'puppeteer' ? {} : require(name),
                module: { exports: {} },
                exports: {},
                process: { argv: [], exit: () => { throw new Error('unexpected exit'); } },
                console,
                __dirname: path.dirname(exporterPath),
                __filename: exporterPath,
              };
              vm.runInNewContext(source, sandbox, { filename: exporterPath });
              return sandbox.module.exports;
            }

            function request(urlPath, port) {
              return new Promise((resolve, reject) => {
                const req = http.get({ host: '127.0.0.1', port, path: urlPath }, (res) => {
                  let body = '';
                  res.setEncoding('utf8');
                  res.on('data', chunk => { body += chunk; });
                  res.on('end', () => resolve({ status: res.statusCode, body }));
                });
                req.on('error', reject);
              });
            }

            (async () => {
              const [exporterPath, outsideSecret, sketchRoot] = process.argv.slice(2);
              fs.mkdirSync(sketchRoot, { recursive: true });
              fs.writeFileSync(path.join(sketchRoot, 'sketch.html'), '<script src="sketch.js"></script>');
              fs.writeFileSync(path.join(sketchRoot, 'sketch.js'), 'window._p5Ready = true;');
              fs.writeFileSync(path.join(sketchRoot, '.env'), 'ROOT_DOTENV_SECRET=inside');
              fs.writeFileSync(path.join(sketchRoot, 'config.yaml'), 'secret: inside');
              fs.symlinkSync(outsideSecret, path.join(sketchRoot, 'linked-secret.txt'));

              const target = await loadExporter(exporterPath).serveSketchDirectory(path.join(sketchRoot, 'sketch.html'));
              const port = new URL(target.url).port;
              try {
                const results = {
                  html: await request('/sketch.html', port),
                  js: await request('/sketch.js', port),
                  dotenv: await request('/.env', port),
                  config: await request('/config.yaml', port),
                  symlink: await request('/linked-secret.txt', port),
                  traversal: await request('/..%2Foutside-secret.txt', port),
                };
                console.log(JSON.stringify(results));
              } finally {
                await target.closeServer();
              }
            })().catch(err => {
              console.error(err.stack || err.message);
              process.exit(1);
            });
            """
        ),
        encoding="utf-8",
    )

    for exporter in _EXPORTERS:
        sketch_root = tmp_path / exporter.parts[-6]
        result = subprocess.run(
            ["node", str(harness), str(exporter), str(outside_secret), str(sketch_root)],
            check=True,
            text=True,
            capture_output=True,
        )
        responses = json.loads(result.stdout)
        assert responses["html"]["status"] == 200, exporter
        assert responses["js"]["status"] == 200, exporter
        assert responses["dotenv"]["status"] == 403, exporter
        assert responses["config"]["status"] == 404, exporter
        assert responses["symlink"]["status"] == 404, exporter
        assert responses["traversal"]["status"] == 403, exporter
