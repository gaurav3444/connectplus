// npm start — set up whatever is missing, then run the whole project:
//   connectplus-llm (answer service, with connectplus-rag inside) on :8000
//   connect-plus-app (web app) on :3000
// Ctrl+C stops both. No dependencies: Node's own child_process only.
//
// First run installs the app's packages and a Python environment for the LLM
// and RAG (PyTorch included, a few GB). Later runs start in seconds.

import { spawn, spawnSync } from "node:child_process";
import { copyFileSync, existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const ROOT = import.meta.dirname;
const APP = join(ROOT, "connect-plus-app");
const LLM = join(ROOT, "connectplus-llm");
const RAG = join(ROOT, "connectplus-rag");
const WIN = process.platform === "win32";
const VENV_PY = join(LLM, ".venv", WIN ? "Scripts/python.exe" : "bin/python");

const say = (msg) => console.log(`\x1b[36m[start]\x1b[0m ${msg}`);

function run(cmd, args, cwd) {
  say(`${cmd} ${args.join(" ")}`);
  // npm is a .cmd on Windows and needs a shell; Python is launched directly,
  // since a shell would split paths with spaces in them
  const r = spawnSync(cmd, args, { cwd, stdio: "inherit", shell: WIN && cmd === "npm" });
  if (r.status !== 0) {
    say(`failed: ${cmd} ${args.join(" ")}`);
    process.exit(1);
  }
}

// rag needs Python 3.11+. Windows has the py launcher; elsewhere python3.
function findPython() {
  const tries = WIN ? [["py", ["-3.13"]], ["py", ["-3.12"]], ["py", ["-3.11"]], ["python", []]] : [["python3", []], ["python", []]];
  for (const [cmd, pre] of tries) {
    const r = spawnSync(cmd, [...pre, "-c", "import sys; print(sys.version_info >= (3, 11))"], { encoding: "utf8" });
    if (r.stdout?.trim() === "True") return [cmd, pre];
  }
  say("Python 3.11 or newer is needed for the answer service: https://www.python.org/downloads/");
  process.exit(1);
}

// .env files are never committed; start each one from its template.
for (const [dir, file, example] of [
  [APP, ".env.local", ".env.local.example"],
  [LLM, ".env", ".env.example"],
  [RAG, ".env", ".env.example"],
]) {
  if (!existsSync(join(dir, file)) && existsSync(join(dir, example))) {
    copyFileSync(join(dir, example), join(dir, file));
    say(`created ${join(dir, file)} from its template — fill in your keys`);
  }
}

if (!existsSync(join(APP, "node_modules"))) run("npm", ["install"], APP);

if (!existsSync(VENV_PY)) {
  const [py, pre] = findPython();
  run(py, [...pre, "-m", "venv", ".venv"], LLM);
  run(VENV_PY, ["-m", "pip", "install", "-r", "requirements.txt"], LLM);
  run(VENV_PY, ["-m", "pip", "install", "-e", RAG], LLM);
}

// Real answers need rag's database and a Gemini key. Without them, run the
// LLM's own offline mode (sample sources, canned writer) so the app still works.
const env = (f) => (existsSync(f) ? readFileSync(f, "utf8") : "");
const has = (text, key) => new RegExp(`^${key}=\\S+`, "m").test(text);
const real = has(env(join(RAG, ".env")), "DATABASE_URL") && has(env(join(LLM, ".env")), "GEMINI_API_KEY");
say(
  real
    ? "answers: real (connectplus-rag + Gemini). The first question downloads rag's models once (~6 GB)."
    : "answers: offline demo mode. Set DATABASE_URL in connectplus-rag/.env and GEMINI_API_KEY in connectplus-llm/.env for real ones.",
);

const children = [];
function start(name, color, cmd, args, cwd, extraEnv = {}) {
  const child = spawn(cmd, args, {
    cwd,
    shell: WIN && cmd === "npm",
    env: { ...process.env, PYTHONIOENCODING: "utf-8", ...extraEnv },
  });
  const tag = `\x1b[${color}m[${name}]\x1b[0m `;
  for (const stream of [child.stdout, child.stderr])
    stream.on("data", (d) => process.stdout.write(d.toString().replace(/^(?=.)/gm, tag)));
  child.on("exit", (code) => {
    say(`${name} stopped (${code ?? "signal"})`);
    stop();
  });
  children.push(child);
}

let stopping = false;
function stop() {
  if (stopping) return;
  stopping = true;
  // on Windows a child's own children (next dev's workers, uvicorn) only go
  // with the whole process tree
  for (const c of children)
    if (c.exitCode === null)
      WIN ? spawnSync("taskkill", ["/pid", String(c.pid), "/T", "/F"], { stdio: "ignore" }) : c.kill("SIGTERM");
  process.exit(0);
}
process.on("SIGINT", stop);
process.on("SIGTERM", stop);

start("llm", "35", VENV_PY, ["-m", "uvicorn", "demo.server:app", "--port", "8000"], LLM,
  real ? { CONNECTPLUS_RAG: "real" } : { CONNECTPLUS_RAG: "stub", LLM_PROVIDER: "mock" });
start("app", "32", "npm", ["run", "dev"], APP);
say("open http://localhost:3000  (helpers: http://localhost:3000/m/queue) — Ctrl+C stops both");
