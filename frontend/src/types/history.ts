import type { AuthenticatedUser } from "./auth";

export type ReferenceHistoryAction =
  | "baseline"
  | "create"
  | "update"
  | "delete"
  | "restore"
  | "context";

export type ReferenceHistorySummary = {
  referenceId: string;
  headRevision: number;
  exists: boolean;
  title?: string;
  latestAction: ReferenceHistoryAction;
  updatedAt: string;
};

export type ReferenceRevision = {
  revision: number;
  action: ReferenceHistoryAction;
  actor: AuthenticatedUser;
  occurredAt: string;
  restoredFromRevision?: number;
  title?: string;
  sourceRevision?: string;
  submittedBibtex?: string;
  canonicalBibtex?: string;
  restorable: boolean;
};

export type ReferenceHistory = {
  referenceId: string;
  headRevision: number;
  exists: boolean;
  revisions: ReferenceRevision[];
};

export type ReferenceHistoryPage = {
  items: ReferenceHistorySummary[];
  total: number;
  limit: number;
  offset: number;
};
