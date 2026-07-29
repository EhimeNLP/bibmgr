import type { BibmgrSchemaVersion } from "./bibtex";
import type { AuthenticatedUser } from "./auth";

export type ExportProfileData = {
  schema_version: BibmgrSchemaVersion;
  profile: string;
  display_name: string;
  description: string;
  validation_profile: string;
  preprint_representation: string;
  [key: string]: unknown;
};

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
