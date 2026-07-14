import { describe, expect, it } from "vitest";
import { fabricConfigSchema } from "./config-schema.js";

describe("fabric config schema", () => {
  it("defaults omitted runtime paths to legacy instance-root locations", () => {
    const parsed = fabricConfigSchema.parse({
      $meta: {
        version: 1,
        updatedAt: "2026-05-10T00:00:00.000Z",
        source: "configure",
      },
      database: {
        mode: "embedded-postgres",
      },
      logging: {
        mode: "file",
      },
      server: {},
    });

    expect(parsed.database.embeddedPostgresDataDir).toBe("~/.hermes-fabric/instances/default/db");
    expect(parsed.database.backup.dir).toBe("~/.hermes-fabric/instances/default/data/backups");
    expect(parsed.logging.logDir).toBe("~/.hermes-fabric/instances/default/logs");
    expect(parsed.storage.localDisk.baseDir).toBe("~/.hermes-fabric/instances/default/data/storage");
    expect(parsed.secrets.localEncrypted.keyFilePath).toBe("~/.hermes-fabric/instances/default/secrets/master.key");
  });
});
