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

export type RegistrationSource = "manual" | "file";

export type RegisterBibtexPayload = {
  bibtex: string;
  source: RegistrationSource;
};

export type RegisterBibtexResult = {
  reference: Reference;
};
