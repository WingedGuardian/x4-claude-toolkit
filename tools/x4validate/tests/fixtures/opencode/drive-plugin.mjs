// Test driver for the OpenCode plugin (.opencode/plugins/x4guard.js), run under node by
// tests/test_opencode_plugin_node.py. OpenCode runs plugins under Bun; this drives the same hook
// functions the way OpenCode's plugin loader does (READ packages/opencode/src/plugin/index.ts):
// EVERY export of a legacy plugin module is called as a plugin, so the module must export
// exactly one function.
//
//   node drive-plugin.mjs <plugin.js> <case.json>
// case.json: {"ctx": {...}, "steps": [{"hook": "<hook name>", "input": {...}, "output": {...}}]}
// stdout: ONE JSON line {"exports": [...], "steps": [{"threw", "message", "output", "ms"}]}
import { readFileSync } from "node:fs"
import { pathToFileURL } from "node:url"

const [pluginPath, casePath] = process.argv.slice(2)
const c = JSON.parse(readFileSync(casePath, "utf8"))
const mod = await import(pathToFileURL(pluginPath).href)
const exports = Object.keys(mod)
const result = { exports, steps: [] }
if (exports.length !== 1 || typeof mod[exports[0]] !== "function") {
  process.stdout.write(JSON.stringify(result) + "\n")
  process.exit(0)
}
const hooks = await mod[exports[0]](c.ctx)
for (const step of c.steps) {
  const t0 = Date.now()
  const output = step.output ?? {}
  let threw = false
  let message = null
  try {
    const fn = hooks[step.hook]
    if (typeof fn !== "function") throw new Error("NO SUCH HOOK: " + step.hook)
    await fn(step.input ?? {}, output)
  } catch (e) {
    threw = true
    message = e && e.message ? e.message : String(e)
  }
  result.steps.push({ threw, message, output, ms: Date.now() - t0 })
}
process.stdout.write(JSON.stringify(result) + "\n")
