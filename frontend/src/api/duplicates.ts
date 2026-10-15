export type DuplicateFinding = {
  incoming_index: number;
  candidate_index: number;
  existing: boolean;
  reference_id?: string;
  citation_key?: string;
  title?: string;
  action: "warn" | "confirm" | "reject";
  comparison: {
    kind: string;
    fields: Array<{
      field: string;
      agreement: "match" | "different" | "missing";
      left: string[];
      right: string[];
    }>;
  };
};

export class DuplicateReviewError extends Error {
  findings: DuplicateFinding[];
  confirmationToken?: string;
  constructor(findings: DuplicateFinding[], confirmationToken?: string) {
    super(confirmationToken ? "Review possible duplicates before saving." : "This reference matches an existing record.");
    this.name = "DuplicateReviewError";
    this.findings = findings;
    this.confirmationToken = confirmationToken;
  }
}

export function duplicateReviewError(payload: unknown): DuplicateReviewError | undefined {
  const value = payload as { error?: { details?: { duplicates?: DuplicateFinding[]; confirmation_token?: string } } } | null;
  const details = value?.error?.details;
  if (!Array.isArray(details?.duplicates)) return undefined;
  return new DuplicateReviewError(details.duplicates, details.confirmation_token || undefined);
}
