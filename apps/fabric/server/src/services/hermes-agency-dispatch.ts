import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type {
  HermesAgencyDispatchArtifact,
  HermesAgencyDispatchMode,
  HermesAgencyDispatchRecord,
  HermesAgencyDispatchStatus,
  HermesAgencyTaskPacketPreview,
} from "@paperclipai/shared";

export interface HermesAgencyDispatchClientInput {
  mode: HermesAgencyDispatchMode;
  skill: string | null;
  targetAgentName: string | null;
  message: string;
  packet: HermesAgencyTaskPacketPreview;
}

export interface HermesAgencyDispatchClientResult {
  status: HermesAgencyDispatchStatus;
  taskId?: string | null;
  queueId?: string | null;
  message?: string | null;
  artifacts?: HermesAgencyDispatchArtifact[];
  raw?: unknown;
}

export interface HermesAgencyDispatchClient {
  dispatch(input: HermesAgencyDispatchClientInput): Promise<HermesAgencyDispatchClientResult>;
}

export interface HermesAgencyDispatchServiceOptions {
  dispatchStorePath?: string;
  dispatchClient?: HermesAgencyDispatchClient;
}

interface DispatchStoreFile {
  dispatches: HermesAgencyDispatchRecord[];
}

const DEFAULT_DISPATCH_STORE_PATH = path.join(os.homedir(), ".paperclip", "hermes-agency-dispatches.json");

export class HermesAgencyDispatchUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "HermesAgencyDispatchUnavailableError";
  }
}

class UnconfiguredDispatchClient implements HermesAgencyDispatchClient {
  async dispatch(): Promise<HermesAgencyDispatchClientResult> {
    throw new HermesAgencyDispatchUnavailableError(
      "Hermes Agency dispatch client is not configured for this Hermes Fabric server process.",
    );
  }
}

class DryRunDispatchClient implements HermesAgencyDispatchClient {
  async dispatch(input: HermesAgencyDispatchClientInput): Promise<HermesAgencyDispatchClientResult> {
    return {
      status: "queued",
      taskId: null,
      queueId: `dry-run-${randomUUID()}`,
      message: `Dry-run ${input.mode} dispatch recorded; no Hermes Agency task was sent.`,
      raw: { dryRun: true, mode: input.mode, skill: input.skill, targetAgentName: input.targetAgentName },
    };
  }
}

function defaultDispatchClient(): HermesAgencyDispatchClient {
  if (process.env.HERMES_FABRIC_AGENCY_DISPATCH_DRY_RUN === "1") return new DryRunDispatchClient();
  return new UnconfiguredDispatchClient();
}

function dispatchStorePath(options: HermesAgencyDispatchServiceOptions) {
  return options.dispatchStorePath ?? process.env.HERMES_FABRIC_AGENCY_DISPATCH_STORE ?? DEFAULT_DISPATCH_STORE_PATH;
}

async function readStore(filePath: string): Promise<DispatchStoreFile> {
  try {
    const parsed = JSON.parse(await readFile(filePath, "utf8")) as Partial<DispatchStoreFile>;
    return { dispatches: Array.isArray(parsed.dispatches) ? parsed.dispatches as HermesAgencyDispatchRecord[] : [] };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { dispatches: [] };
    throw error;
  }
}

async function writeStore(filePath: string, store: DispatchStoreFile) {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, `${JSON.stringify(store, null, 2)}\n`);
}

function cleanString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function selectSkill(packet: HermesAgencyTaskPacketPreview) {
  return packet.requestedSkills.find((skill) => skill.trim().length > 0)?.trim() ?? null;
}

function buildDispatchMessage(packet: HermesAgencyTaskPacketPreview) {
  return [
    `Task: ${packet.title}`,
    "",
    "Goal:",
    packet.goal,
    "",
    "Context:",
    packet.context,
    "",
    "Validation expectations:",
    ...packet.validationExpectations.map((item) => `- ${item}`),
    "",
    "Artifact expectations:",
    ...packet.artifactExpectations.map((item) => `- ${item}`),
    "",
    "Stop conditions:",
    ...packet.stopConditions.map((item) => `- ${item}`),
  ].join("\n");
}

function normalizeDispatchStatus(result: HermesAgencyDispatchClientResult): HermesAgencyDispatchStatus {
  if (result.status === "wake_failed" && result.queueId) return "queued";
  return result.status;
}

export async function dispatchHermesAgencyTask(
  packet: HermesAgencyTaskPacketPreview,
  inputMode: HermesAgencyDispatchMode | undefined,
  options: HermesAgencyDispatchServiceOptions = {},
): Promise<HermesAgencyDispatchRecord> {
  const mode: HermesAgencyDispatchMode = inputMode ?? "skill-fit";
  const skill = mode === "skill-fit" ? selectSkill(packet) : null;
  const targetAgentName = mode === "direct-agent" ? cleanString(packet.targetAgentName) : null;

  if (mode === "skill-fit" && !skill) {
    throw new HermesAgencyDispatchUnavailableError("Skill-fit dispatch requires at least one requested skill.");
  }
  if (mode === "direct-agent" && !targetAgentName) {
    throw new HermesAgencyDispatchUnavailableError("Direct-agent dispatch requires targetAgentName.");
  }

  const client = options.dispatchClient ?? defaultDispatchClient();
  const result = await client.dispatch({
    mode,
    skill,
    targetAgentName,
    message: buildDispatchMessage(packet),
    packet,
  });
  const now = new Date().toISOString();
  const status = normalizeDispatchStatus(result);
  const record: HermesAgencyDispatchRecord = {
    id: randomUUID(),
    createdAt: now,
    updatedAt: now,
    packet,
    mode,
    skill,
    targetAgentName,
    taskId: result.taskId ?? null,
    queueId: result.queueId ?? null,
    status,
    message: result.message ?? null,
    artifacts: result.artifacts ?? [],
    statusHistory: [{ status, at: now, message: result.message ?? null }],
    raw: result.raw ?? null,
  };

  const filePath = dispatchStorePath(options);
  const store = await readStore(filePath);
  store.dispatches = [record, ...store.dispatches];
  await writeStore(filePath, store);
  return record;
}

export async function getHermesAgencyDispatch(
  id: string,
  options: HermesAgencyDispatchServiceOptions = {},
): Promise<HermesAgencyDispatchRecord | null> {
  const store = await readStore(dispatchStorePath(options));
  return store.dispatches.find((dispatch) => dispatch.id === id) ?? null;
}
