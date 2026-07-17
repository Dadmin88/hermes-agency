import { describe, expect, it } from "vitest";
import { effectiveSkillActions, filterSharedPoolSkills, readSharedDeleteImpact } from "./shared-skill-ui";

describe("shared skill UI helpers", () => {
  it("retains 409 consumer impact until an explicit confirmation is possible", () => {
    expect(readSharedDeleteImpact({ status: 409, body: { impact: { count: 2, profiles: ["agency-a", "agency-b"] } } })).toEqual({ count: 2, profiles: ["agency-a", "agency-b"] });
    expect(readSharedDeleteImpact({ status: 422, body: { impact: { count: 2, profiles: ["agency-a"] } } })).toBeNull();
  });
  it("filters shared skills by search and category", () => {
    const skills = [{ name: "deploy", category: "ops", description: "Deploy safely", tags: ["release"] }, { name: "review", category: "engineering", description: "Review code", tags: [] }];
    expect(filterSharedPoolSkills(skills, "release", "").map((skill) => skill.name)).toEqual(["deploy"]);
    expect(filterSharedPoolSkills(skills, "", "engineering").map((skill) => skill.name)).toEqual(["review"]);
  });
  it("shows source-correct actions and protects built-in, shadowed, and disabled entries", () => {
    const base = { name: "skill", description: "", enabled: true, editable: true, assigned: false, shadowed: false, status: "enabled" as const, category: null, effective: true };
    expect(effectiveSkillActions({ ...base, origin: "shared_pool" })).toMatchObject({ detach: true, editShared: true, editLocal: false });
    expect(effectiveSkillActions({ ...base, origin: "profile" })).toMatchObject({ editLocal: true, detach: false, editShared: false });
    expect(effectiveSkillActions({ ...base, origin: "builtin" })).toMatchObject({ readOnly: true, detach: false, editShared: false, editLocal: false });
    expect(effectiveSkillActions({ ...base, origin: "shared_pool", effective: false, shadowed: true, status: "shadowed" as const })).toMatchObject({ readOnly: true, detach: false, editShared: false });
  });
});
