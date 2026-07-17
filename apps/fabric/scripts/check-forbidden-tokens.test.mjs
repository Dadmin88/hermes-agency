import assert from "node:assert/strict";
import { execSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  resolveDynamicForbiddenTokens,
  runForbiddenTokenCheck,
} from "./check-forbidden-tokens.mjs";

function git(command, cwd) {
  return execSync(command, { cwd, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] });
}

test("ignores generic CI service accounts but retains maintainer usernames", () => {
  const tokens = resolveDynamicForbiddenTokens(
    { USER: "runner", LOGNAME: "root", USERNAME: "maintainer123" },
    { userInfo: () => ({ username: "runner" }) },
  );

  assert.deepEqual(tokens, ["maintainer123"]);
});

test("matches a forbidden username as a word without flagging identifier substrings", () => {
  const repoRoot = mkdtempSync(path.join(os.tmpdir(), "fabric-forbidden-token-"));
  const messages = [];

  try {
    git("git init -q", repoRoot);
    writeFileSync(path.join(repoRoot, "fixture.txt"), "copiedMaintainer123 grants\n", "utf8");
    git("git add fixture.txt", repoRoot);

    assert.equal(
      runForbiddenTokenCheck({
        repoRoot,
        tokens: ["maintainer123"],
        exec: execSync,
        log: (message) => messages.push(message),
        error: (message) => messages.push(message),
      }),
      0,
    );

    writeFileSync(path.join(repoRoot, "fixture.txt"), "/srv/maintainer123/project\n", "utf8");
    git("git add fixture.txt", repoRoot);

    assert.equal(
      runForbiddenTokenCheck({
        repoRoot,
        tokens: ["maintainer123"],
        exec: execSync,
        log: (message) => messages.push(message),
        error: (message) => messages.push(message),
      }),
      1,
    );
  } finally {
    rmSync(repoRoot, { recursive: true, force: true });
  }
});
