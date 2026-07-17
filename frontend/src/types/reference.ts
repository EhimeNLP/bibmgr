export type CitationContext = {
  id: string;
  sourcePaperTitle?: string;
  sourceFileName?: string;
  before?: string;
  context: string;
  after?: string;
};

export type Reference = {
  id: string;
  title: string;
  authors: string[];
  year?: number;
  venue?: string;
  doi?: string;
  url?: string;
  bibtexKey?: string;
  bibtex?: string;
  citationContexts?: CitationContext[];
};

export type RegistrationStatus =
  | "success"
  | "needs_review"
  | "not_found"
  | "api_error";

export type RegistrationSource = "pdf" | "manual";

export type RegistrationReviewItem = {
  id: string;
  title: string;
  authors: string[];
  year?: number;
  venue?: string;
  doi?: string;
  bibtex: string;
  status: RegistrationStatus;
  confidenceScore?: number;
  sourceApi?: string;
  rawReferenceText?: string;
  registrationState?: "idle" | "registered" | "failed";
  registrationMessage?: string;
};

export type PdfRegistrationResult = {
  uploadId?: string;
  sourceFileName: string;
  references: RegistrationReviewItem[];
};

export type RegisterBibtexPayload = {
  bibtex: string;
  source: RegistrationSource;
  uploadId?: string;
  reviewItemId?: string;
  metadata?: Partial<Reference>;
};

export type RegisterBibtexResult = {
  reference: Reference;
};
