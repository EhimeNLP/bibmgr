import type {
  BibmgrSchemaVersion,
  BibtexExportResult,
  VenueNameStyle,
} from "./bibtex";
import type { AuthenticatedUser } from "./auth";

export type PreprintRepresentation =
  | "misc-eprint"
  | "misc-howpublished"
  | "article-journal";
export type ExportMonthFormat = "numeric" | "bibtex-macro";
export type ExportFieldCase = "lowercase" | "canonical";
export type ExportValueDelimiter = "braces" | "quotes";
export type ExportLineEnding = "lf" | "cr-lf";

export type ExportFieldSelection = {
  allowed_fields: string[] | null;
  excluded_fields: string[];
};

export type ExportProfileData = {
  schema_version: BibmgrSchemaVersion;
  profile: string;
  display_name: string;
  description: string;
  validation_profile: string;
  preprint_representation: PreprintRepresentation;
  month_format: ExportMonthFormat;
  supported_entry_types: string[];
  field_order: string[];
  field_case: ExportFieldCase;
  case_protected_fields: string[];
  value_delimiter: ExportValueDelimiter;
  line_ending: ExportLineEnding;
  indent: string;
  trailing_comma: boolean;
  include_doi: boolean;
  include_url: boolean;
  include_extra_fields: boolean;
  field_renames: Record<string, string>;
  field_selection: ExportFieldSelection;
  excluded_fields: string[];
  allow_unknown_work_type: boolean;
};

export type ExportProfilePreviewRequest = {
  source: string;
  data: ExportProfileData;
  venue_name_style?: VenueNameStyle;
};

export type ExportProfilePreviewResult = BibtexExportResult;

export type VenueKind =
  | "conference"
  | "journal"
  | "workshop"
  | "book-series"
  | "other";

export type VenueData = {
  id: string;
  full_name: string;
  short_name: string;
  aliases: string[];
  kind: VenueKind;
};

export type ConfigurationEntry<T> = {
  key: string;
  data: T;
  revision: number;
  built_in: boolean;
  updated_at: string | null;
  updated_by: AuthenticatedUser | null;
};

export type ApplicationConfiguration = {
  schema_version: BibmgrSchemaVersion;
  export_profiles: Array<ConfigurationEntry<ExportProfileData>>;
  venues: Array<ConfigurationEntry<VenueData>>;
};

export type ConfigurationUpdateResult<T> = {
  schema_version: BibmgrSchemaVersion;
  setting: ConfigurationEntry<T>;
};

export type ConfigurationDeleteResult = {
  schema_version: BibmgrSchemaVersion;
  key: string;
  revision: number;
  reset: boolean;
};

export type ConfigurationKind = "export_profile" | "venue";

export type ConfigurationHistoryAction =
  | "change"
  | "create"
  | "override"
  | "update"
  | "restore_default"
  | "delete";

export type ConfigurationHistoryEvent = {
  id: string;
  key: string;
  revision: number;
  action: ConfigurationHistoryAction;
  before_data: Record<string, unknown> | null;
  after_data: Record<string, unknown> | null;
  occurred_at: string;
  actor: AuthenticatedUser;
};

export type ConfigurationHistoryPage = {
  schema_version: BibmgrSchemaVersion;
  kind: ConfigurationKind;
  items: ConfigurationHistoryEvent[];
  total: number;
  limit: number;
  offset: number;
};
