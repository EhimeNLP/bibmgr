export type CitationContext = {
  id: string;
  sourcePaperTitle?: string;
  sourceFileName?: string;
  before?: string;
  context: string;
  after?: string;
};

export type CitationContextInput = Omit<CitationContext, "id">;

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
  sourceRevision?: string;
  citationContexts?: CitationContext[];
  createdAt?: string;
  updatedAt?: string;
};

export type RegistrationSource = "manual" | "file" | "pipeline";

export type RegisterBibtexPayload = {
  bibtex: string;
  source: RegistrationSource;
  citation_contexts?: Array<{
    source_paper_title?: string;
    source_file_name?: string;
    before?: string;
    context: string;
    after?: string;
  }>;
};

export type RegisterBibtexResult = {
  reference: Reference;
  references?: Reference[];
};

export type PipelineImportItem = {
  bibtex: string;
  citation_contexts: NonNullable<
    RegisterBibtexPayload["citation_contexts"]
  >;
};

export type UpdateReferencePayload = {
  bibtex: string;
  source_revision: string;
};

export type ReferenceSort =
  | "updated_desc"
  | "updated_asc"
  | "year_desc"
  | "year_asc"
  | "title_asc";

export type ReferenceSearchFilters = {
  query?: string;
  year?: number;
  author?: string;
  venue?: string;
  identifier?: string;
  entryType?: string;
  createdBy?: string;
  updatedFrom?: string;
  updatedTo?: string;
  sort?: ReferenceSort;
};

export type ReferencePage = {
  items: Reference[];
  total: number;
  limit: number;
  offset: number;
};
