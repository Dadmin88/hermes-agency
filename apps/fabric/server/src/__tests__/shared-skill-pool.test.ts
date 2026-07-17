import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { SharedSkillPoolError, createSharedPoolSkill, deleteSharedPoolSkill, effectiveProfileSkills, getProfileLocalSkill, listSharedPool, setProfilePoolSkill, updateProfileLocalSkill, updateSharedPoolSkill } from "../services/shared-skill-pool.js";

const dirs: string[] = [];
async function fixture() {
  const dir = await mkdtemp(path.join(os.tmpdir(), "fabric-shared-pool-")); dirs.push(dir);
  const pool = path.join(dir, "pool"); const profiles = path.join(dir, "profiles"); const builtin = path.join(dir, "builtin");
  await mkdir(pool, { recursive: true }); await mkdir(profiles, { recursive: true }); await mkdir(builtin, { recursive: true });
  await writeFile(path.join(pool, "pool-manifest.json"), JSON.stringify({ version: "1.0", categories: {} }));
  return { dir, pool, profiles, builtin, options: { poolRoot: pool, profilesDir: profiles, builtinSkillsDir: builtin } };
}
const skill = (name: string) => `---\nname: ${name}\ndescription: Test ${name}\n---\n\n# ${name}\n`;
afterEach(async () => { await Promise.all(dirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true }))); });

describe("shared skill pool", () => {
  it("rejects traversal, symlinks, secrets, and corrupt manifests", async () => {
    const { pool, options } = await fixture();
    await expect(createSharedPoolSkill({ name: "safe", category: "test", files: { "../outside": "x", "SKILL.md": skill("safe") } }, options)).rejects.toBeInstanceOf(SharedSkillPoolError);
    await expect(createSharedPoolSkill({ name: "safe", category: "test", files: { "SKILL.md": `${skill("safe")}\napi_key=abcdefghijklmnopqrstuvwxyz` } }, options)).rejects.toBeInstanceOf(SharedSkillPoolError);
    await writeFile(path.join(pool, "pool-manifest.json"), "{");
    await expect(listSharedPool(options)).rejects.toThrow("manifest is corrupt");
  });

  it("uses profile precedence and disabled state without mutating the pool", async () => {
    const { pool, profiles, builtin, options } = await fixture();
    await createSharedPoolSkill({ name: "shared", category: "test", files: { "SKILL.md": skill("shared") } }, options);
    await mkdir(path.join(builtin, "shared"), { recursive: true }); await writeFile(path.join(builtin, "shared", "SKILL.md"), skill("shared"));
    await mkdir(path.join(profiles, "agency-test", "skills", "shared"), { recursive: true }); await writeFile(path.join(profiles, "agency-test", "skills", "shared", "SKILL.md"), skill("shared"));
    await writeFile(path.join(profiles, "agency-test", "config.yaml"), `skills:\n  external_dirs:\n    - ${pool}\n`);
    let skills = await effectiveProfileSkills("agency-test", options);
    expect(skills.filter((item) => item.name === "shared").map((item) => item.origin)).toEqual(["profile", "shared_pool", "builtin"]);
    expect(skills.find((item) => item.origin === "profile")?.effective).toBe(true);
    await expect(setProfilePoolSkill("agency-test", "shared", false, options)).rejects.toMatchObject({ code: "conflict" });
    skills = await effectiveProfileSkills("agency-test", options);
    expect(skills.find((item) => item.origin === "profile")?.effective).toBe(true);
    expect(skills.find((item) => item.origin === "shared_pool")).toMatchObject({ status: "shadowed", shadowed: true, enabled: true });
    expect((await readFile(path.join(pool, "test", "shared", "SKILL.md"), "utf8"))).toContain("name: shared");
  });

  it("lists valid filesystem skills missing from a stale manifest", async () => {
    const { pool, options } = await fixture();
    const dir = path.join(pool, "newsjack", "breaking-news");
    await mkdir(dir, { recursive: true });
    await writeFile(path.join(dir, "SKILL.md"), skill("breaking-news"));

    await expect(listSharedPool(options)).resolves.toEqual([
      expect.objectContaining({ name: "breaking-news", category: "newsjack", manifested: false, source: "shared_pool" }),
    ]);
  });

  it("quarantines one invalid-YAML skill without hiding valid pool entries", async () => {
    const { pool, profiles, options } = await fixture();
    await createSharedPoolSkill({ name: "healthy", category: "newsjack", files: { "SKILL.md": skill("healthy") } }, options);
    const invalidDir = path.join(pool, "newsjack", "broken-yaml");
    await mkdir(invalidDir, { recursive: true });
    await writeFile(path.join(invalidDir, "SKILL.md"), "---\nname: broken-yaml\ndescription: [unterminated\n---\n");
    await mkdir(path.join(profiles, "agency-test"), { recursive: true });
    await writeFile(path.join(profiles, "agency-test", "config.yaml"), `skills:\n  external_dirs:\n    - ${pool}\n`);

    const listed = await listSharedPool(options);
    expect(listed.find((entry) => entry.name === "healthy")).toMatchObject({ valid: true, actionable: true, diagnostic: null });
    expect(listed.find((entry) => entry.name === "broken-yaml")).toMatchObject({
      valid: false,
      actionable: false,
      files: [],
      diagnostic: {
        code: "invalid_skill",
        location: "newsjack/broken-yaml/SKILL.md",
        message: "SKILL.md frontmatter is invalid YAML.",
      },
    });
    expect(JSON.stringify(listed)).not.toContain(pool);
    await expect(effectiveProfileSkills("agency-test", options)).resolves.toEqual(expect.arrayContaining([
      expect.objectContaining({ name: "healthy", origin: "shared_pool", effective: true }),
    ]));
  });

  it("keeps filesystem and manifest consistent across create, update, and delete", async () => {
    const { pool, options } = await fixture();
    await createSharedPoolSkill({ name: "managed", category: "one", files: { "SKILL.md": skill("managed") } }, options);
    await writeFile(path.join(pool, "one", "managed", "evidence.md"), "preserve me\n");
    let manifest = JSON.parse(await readFile(path.join(pool, "pool-manifest.json"), "utf8"));
    expect(manifest.categories.one.skills.managed.path).toBe("one/managed");

    await updateSharedPoolSkill("managed", { category: "two", files: { "SKILL.md": `${skill("managed")}\nUpdated\n` } }, options);
    manifest = JSON.parse(await readFile(path.join(pool, "pool-manifest.json"), "utf8"));
    expect(manifest.categories.one.skills.managed).toBeUndefined();
    expect(manifest.categories.two.skills.managed.path).toBe("two/managed");
    expect(await readFile(path.join(pool, "two", "managed", "SKILL.md"), "utf8")).toContain("Updated");
    expect(await readFile(path.join(pool, "two", "managed", "evidence.md"), "utf8")).toBe("preserve me\n");

    await deleteSharedPoolSkill("managed", true, options);
    manifest = JSON.parse(await readFile(path.join(pool, "pool-manifest.json"), "utf8"));
    expect(manifest.categories.two.skills.managed).toBeUndefined();
    await expect(readFile(path.join(pool, "two", "managed", "SKILL.md"), "utf8")).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("adds the canonical pool once, then persists disable and re-enable state", async () => {
    const { pool, profiles, options } = await fixture();
    await createSharedPoolSkill({ name: "shared", category: "test", files: { "SKILL.md": skill("shared") } }, options);
    await mkdir(path.join(profiles, "agency-test"), { recursive: true });
    await writeFile(path.join(profiles, "agency-test", "config.yaml"), "skills:\n  external_dirs:\n    - /opt/other-skills\n  disabled:\n    - keep-disabled\n");

    let skills = await setProfilePoolSkill("agency-test", "shared", true, options);
    expect(skills.find((item) => item.name === "shared" && item.origin === "shared_pool")).toMatchObject({ effective: true, enabled: true });
    await setProfilePoolSkill("agency-test", "shared", false, options);
    skills = await effectiveProfileSkills("agency-test", options);
    expect(skills.find((item) => item.name === "shared" && item.origin === "shared_pool")).toMatchObject({ effective: false, enabled: false, status: "disabled" });
    await setProfilePoolSkill("agency-test", "shared", true, options);

    const config = await readFile(path.join(profiles, "agency-test", "config.yaml"), "utf8");
    expect(config.match(new RegExp(pool.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g"))).toHaveLength(1);
    expect(config).toContain("/opt/other-skills");
    expect(config).toContain("keep-disabled");
    expect(config).not.toMatch(/disabled:\n(?:\s+- .*\n)*\s+- shared/);
    await expect(effectiveProfileSkills("agency-test", options)).resolves.toEqual(expect.arrayContaining([
      expect.objectContaining({ name: "shared", origin: "shared_pool", effective: true, enabled: true }),
    ]));
  });

  it("requires delete confirmation when profiles consume a pool skill", async () => {
    const { pool, profiles, options } = await fixture();
    await createSharedPoolSkill({ name: "shared", category: "test", files: { "SKILL.md": skill("shared") } }, options);
    await mkdir(path.join(profiles, "agency-test"), { recursive: true }); await writeFile(path.join(profiles, "agency-test", "config.yaml"), `skills:\n  external_dirs:\n    - ${pool}\n`);
    await expect(deleteSharedPoolSkill("shared", false, options)).rejects.toMatchObject({ code: "conflict", impact: { profiles: ["agency-test"] } });
    await expect(deleteSharedPoolSkill("shared", true, options)).resolves.toMatchObject({ deleted: true, affectedProfiles: ["agency-test"] });
  });

  it("edits only a profile-local skill through managed text files", async () => {
    const { profiles, options } = await fixture();
    const dir = path.join(profiles, "agency-test", "skills", "local"); await mkdir(dir, { recursive: true }); await writeFile(path.join(dir, "SKILL.md"), skill("local"));
    await expect(getProfileLocalSkill("agency-test", "../outside", options)).rejects.toBeInstanceOf(SharedSkillPoolError);
    await expect(updateProfileLocalSkill("agency-test", "local", { files: { "SKILL.md": `${skill("local")}\nsecret=abcdefghijklmnopqrstuvwxyz` } }, options)).rejects.toBeInstanceOf(SharedSkillPoolError);
    await updateProfileLocalSkill("agency-test", "local", { files: { "SKILL.md": `${skill("local")}\nupdated` } }, options);
    await expect(getProfileLocalSkill("agency-test", "local", options)).resolves.toMatchObject({ content: { "SKILL.md": expect.stringContaining("updated") } });
  });
});
