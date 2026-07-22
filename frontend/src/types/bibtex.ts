export type BibmgrSchemaVersion = "1";

export type ParseMode = "strict" | "tolerant";
export type DiagnosticSeverity = "error" | "warning" | "information" | "hint";
export type FixApplicability =
  | "safe"
  | "requires_confirmation"
  | "unsafe";

/** Half-open UTF-8 byte range, not a JavaScript string offset. */
export type TextRange = {
  start: number;
  end: number;
};

export type SourceLocation = {
  source_id: string;
  range: TextRange;
};

export type RelatedLocation = {
  message: string;
  location: SourceLocation;
};

export type BibtexDiagnostic = {
  id: string;
  code: string;
  severity: DiagnosticSeverity;
  blocking: boolean;
  message: string;
  primary_location: SourceLocation | null;
  related_locations: RelatedLocation[];
  notes: string[];
  fixes: string[];
};

export type TextEdit = {
  range: TextRange;
  replacement: string;
};

export type BibtexFix = {
  id: string;
  title: string;
  applicability: FixApplicability;
  source_revision: string;
  edits: TextEdit[];
};

export type SyntaxSummary = {
  mode?: ParseMode;
  source_id?: string;
  entry_count?: number;
  recovered?: boolean;
  diagnostic_count?: number;
  [key: string]: unknown;
};

export type SemanticBibliography = {
  records: Array<Record<string, unknown>>;
  diagnostics: BibtexDiagnostic[];
  [key: string]: unknown;
};

export type BibtexAnalysisResult = {
  schema_version: BibmgrSchemaVersion;
  source_revision: string;
  syntax: SyntaxSummary;
  bibliography: SemanticBibliography;
  diagnostics: BibtexDiagnostic[];
  available_fixes: BibtexFix[];
};

export type ApplyBibtexFixesResult = {
  schema_version: BibmgrSchemaVersion;
  source: string;
  source_revision: string;
  applied_fix_ids: string[];
  diff?: string;
  analysis?: BibtexAnalysisResult;
};

export type RegistrationValidationResult = {
  schema_version: BibmgrSchemaVersion;
  accepted: boolean;
  source_revision: string;
  diagnostics: BibtexDiagnostic[];
  bibliography?: SemanticBibliography;
  source: string;
  applied_fix_ids: string[];
  unresolved_semantics: boolean;
};

export type BibtexExportResult = {
  schema_version: BibmgrSchemaVersion;
  source: string;
  profile: string;
  record_count: number;
  warnings: Array<{
    record_index: number;
    message: string;
  }>;
};

export type BibtexExportProfile = {
  id: string;
  display_name: string;
  description: string;
  validation_profile: string;
  preprint_representation: string;
};

export type BibtexExportProfilesResult = {
  schema_version: BibmgrSchemaVersion;
  profiles: BibtexExportProfile[];
};

export type AnalyzeBibtexRequest = {
  source: string;
  profile?: string;
  mode?: ParseMode;
};

export type ApplyBibtexFixesRequest = {
  source: string;
  source_revision: string;
  fix_ids: string[];
  profile?: string;
};

export type ValidateRegistrationRequest = {
  source: string;
  policy?: string;
};

export type ExportBibtexRequest = {
  source: string;
  profile?: string;
};

export type BibmgrErrorResponse = {
  schema_version: BibmgrSchemaVersion;
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
};
