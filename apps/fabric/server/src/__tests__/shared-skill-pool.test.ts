import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { SharedSkillPoolError, createSharedPoolSkill, deleteSharedPoolSkill, effectiveProfileSkills, getProfileLocalSkill, listSharedPool, setProfilePoolSkill, updateProfileLocalSkill } from "../services/shared-skill-pool.js";

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
    expect(skills.find((item) => item.origin === "shared_pool")?.status).toBe("shadowed");
    expect((await readFile(path.join(pool, "test", "shared", "SKILL.md"), "utf8"))).toContain("name: shared");
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
