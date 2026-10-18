// JavaScript harness. Runs INSIDE the sandboxed child process.
// argv: workdir fnName timeoutMs. User code runs in a fresh vm context that has no require/process;
// only strings cross the realm boundary, so prototype-chain escapes to the host are not possible.
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const [workdir, fnName, timeoutArg] = process.argv.slice(2);
const timeout = Math.max(100, parseInt(timeoutArg || '2000', 10));
const out = (obj) => fs.writeFileSync(path.join(workdir, 'result.json'), JSON.stringify(obj));

try {
  const code = fs.readFileSync(path.join(workdir, 'solution.js'), 'utf8');
  const argsJson = fs.readFileSync(path.join(workdir, 'case.json'), 'utf8');
  const ctx = vm.createContext({}, { codeGeneration: { strings: false, wasm: false } });
  ctx.__argsJson = argsJson;
  vm.runInContext(
    'var __logs = []; var console = {};' +
      "['log','info','warn','error','debug'].forEach(function (k) {" +
      "  console[k] = function () { if (__logs.length < 200) __logs.push(Array.prototype.map.call(arguments, String).join(' ')); };" +
      '});',
    ctx,
  );
  new vm.Script(code, { filename: 'solution.js' }).runInContext(ctx, { timeout });
  const probe = vm.runInContext('typeof ' + JSON.stringify(fnName).slice(1, -1), ctx);
  if (probe !== 'function') {
    out({ ok: false, error: "Function '" + fnName + "' is not defined" });
  } else {
    const t0 = process.hrtime.bigint();
    const raw = vm.runInContext(
      'JSON.stringify({ out: ' + fnName + '.apply(null, JSON.parse(__argsJson)) })',
      ctx,
      { timeout },
    );
    const ms = Number(process.hrtime.bigint() - t0) / 1e6;
    const parsed = JSON.parse(raw === undefined ? '{}' : raw);
    const logs = String(vm.runInContext('__logs.join("\\n")', ctx)).slice(0, 4000);
    out({ ok: true, output: parsed.out === undefined ? null : parsed.out, ms: Math.round(ms * 100) / 100, stdout: logs });
  }
} catch (e) {
  const msg = String((e && e.message) || e).slice(0, 500);
  if (/timed out/i.test(msg)) out({ ok: false, error: 'TimeLimit: ' + msg });
  else out({ ok: false, error: (e && e.name ? e.name + ': ' : '') + msg });
}
