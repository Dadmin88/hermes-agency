import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  bootstrapDevRunnerWorktreeEnv,
  isLinkedGitWorktreeCheckout,
  resolveWorktreeEnvFilePath,
} from "../dev-runner-worktree.ts";

const tempRoots = new Set<string>();

afterEach(() => {
  for (const root of tempRoots) {
    fs.rmSync(root, { recursive: true, force: true });
  }
  tempRoots.clear();
});

function createTempRoot(prefix: string): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  tempRoots.add(root);
  return root;
}

describe("dev-runner worktree env bootstrap", () => {
  it("detects linked git worktrees from .git files", () => {
    const root = createTempRoot("fabric-dev-runner-worktree-");
    fs.writeFileSync(path.join(root, ".git"), "gitdir: /tmp/fabric/.git/worktrees/feature\n", "utf8");

    expect(isLinkedGitWorktreeCheckout(root)).toBe(true);
  });

  it("loads repo-local HermesFabric env for initialized worktrees without overriding explicit env", () => {
    const root = createTempRoot("fabric-dev-runner-worktree-env-");
    fs.mkdirSync(path.join(root, ".fabric"), { recursive: true });
    fs.writeFileSync(path.join(root, ".git"), "gitdir: /tmp/fabric/.git/worktrees/feature\n", "utf8");
    fs.writeFileSync(
      resolveWorktreeEnvFilePath(root),
      [
        "HERMES_FABRIC_HOME=/tmp/fabric-worktrees",
        "HERMES_FABRIC_INSTANCE_ID=feature-worktree",
        "HERMES_FABRIC_IN_WORKTREE=true",
        "HERMES_FABRIC_WORKTREE_NAME=feature-worktree",
        "HERMES_FABRIC_OPTIONAL= # comment-only value",
        "",
      ].join("\n"),
      "utf8",
    );

    const env: NodeJS.ProcessEnv = {
      HERMES_FABRIC_INSTANCE_ID: "already-set",
    };
    const result = bootstrapDevRunnerWorktreeEnv(root, env);

    expect(result).toEqual({
      envPath: resolveWorktreeEnvFilePath(root),
      missingEnv: false,
    });
    expect(env.HERMES_FABRIC_HOME).toBe("/tmp/fabric-worktrees");
    expect(env.HERMES_FABRIC_INSTANCE_ID).toBe("already-set");
    expect(env.HERMES_FABRIC_IN_WORKTREE).toBe("true");
    expect(env.HERMES_FABRIC_OPTIONAL).toBe("");
  });

  it("repairs stale migrated config paths before loading worktree env", () => {
    const root = createTempRoot("fabric-dev-runner-worktree-migrated-env-");
    const localConfigPath = path.join(root, ".fabric", "config.json");
    const worktreesDir = path.join(root, ".fabric-worktrees");
    fs.mkdirSync(path.dirname(localConfigPath), { recursive: true });
    fs.writeFileSync(path.join(root, ".git"), "gitdir: /tmp/fabric/.git/worktrees/feature\n", "utf8");
    fs.writeFileSync(localConfigPath, "{}\n", "utf8");
    fs.writeFileSync(
      resolveWorktreeEnvFilePath(root),
      [
        "HERMES_FABRIC_HOME=/old/home/.fabric-worktrees",
        "HERMES_FABRIC_INSTANCE_ID=feature-worktree",
        "HERMES_FABRIC_CONFIG=/old/home/fabric/.fabric/worktrees/feature/.fabric/config.json",
        "HERMES_FABRIC_CONTEXT=/old/home/.fabric-worktrees/context.json",
        "HERMES_FABRIC_IN_WORKTREE=true",
        "HERMES_FABRIC_WORKTREE_NAME=feature-worktree",
        "",
      ].join("\n"),
      "utf8",
    );

    const env: NodeJS.ProcessEnv = {
      HERMES_FABRIC_WORKTREES_DIR: worktreesDir,
    };
    const result = bootstrapDevRunnerWorktreeEnv(root, env);

    expect(result).toEqual({
      envPath: resolveWorktreeEnvFilePath(root),
      missingEnv: false,
    });
    expect(env.HERMES_FABRIC_HOME).toBe(worktreesDir);
    expect(env.HERMES_FABRIC_CONFIG).toBe(localConfigPath);
    expect(env.HERMES_FABRIC_CONTEXT).toBe(path.join(worktreesDir, "context.json"));
    expect(env.HERMES_FABRIC_INSTANCE_ID).toBe("feature-worktree");
  });

  it("reports uninitialized linked worktrees so dev runner can fail fast", () => {
    const root = createTempRoot("fabric-dev-runner-worktree-missing-");
    fs.writeFileSync(path.join(root, ".git"), "gitdir: /tmp/fabric/.git/worktrees/feature\n", "utf8");

    expect(bootstrapDevRunnerWorktreeEnv(root, {})).toEqual({
      envPath: resolveWorktreeEnvFilePath(root),
      missingEnv: true,
    });
  });
});
