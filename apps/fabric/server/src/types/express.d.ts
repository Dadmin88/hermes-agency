import type { AuthorizationActor } from "../services/authorization.js";

type RequestActor = AuthorizationActor & {
  [key: string]: unknown;
  userId?: string;
  userName?: string | null;
  userEmail?: string | null;
  agentId?: string;
  companyId?: string;
  keyId?: string;
  runId?: string;
};

declare global {
  namespace Express {
    interface Request {
      actor: RequestActor;
    }
  }
}

export {};
