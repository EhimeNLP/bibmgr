import type { ExportProfileData } from "../types/configuration";

const FIELD_NAME = /^[A-Za-z0-9_-]+$/;

export function exportProfileErrors(profile: ExportProfileData): string[] {
  const errors: string[] = [];
  if (profile.schema_version !== "1") {
    errors.push("Schema version must be 1.");
  }
  if (!profile.profile.trim()) errors.push("Profile ID is required.");
  if (!profile.display_name.trim()) errors.push("Display name is required.");
  if (!profile.description.trim()) errors.push("Description is required.");
  if (!profile.validation_profile.trim()) {
    errors.push("Validation baseline is required.");
  }
  if (!/^[ \t]*$/.test(profile.indent)) {
    errors.push("Indentation may contain only spaces or tabs.");
  }

  validateFieldList("Field order", profile.field_order, errors);
  validateFieldList(
    "Supported entry types",
    profile.supported_entry_types,
    errors,
  );
  validateFieldList(
    "Case-protected fields",
    profile.case_protected_fields,
    errors,
  );
  validateFieldList("Excluded fields", profile.excluded_fields, errors);
  if (profile.field_selection.allowed_fields) {
    validateFieldList(
      "Included fields",
      profile.field_selection.allowed_fields,
      errors,
    );
  }
  validateFieldList(
    "Excluded fields",
    profile.field_selection.excluded_fields,
    errors,
  );

  const allowed = profile.field_selection.allowed_fields;
  const excluded = [
    ...profile.excluded_fields,
    ...profile.field_selection.excluded_fields,
  ];
  if (allowed) {
    for (const name of allowed) {
      if (hasField(excluded, name)) {
        errors.push(`Field “${name}” cannot be both included and excluded.`);
      }
    }
  }

  const renameSources = Object.keys(profile.field_renames);
  const renameTargets = Object.values(profile.field_renames);
  validateFieldList("Rename source fields", renameSources, errors);
  validateFieldList("Rename target fields", renameTargets, errors);
  for (const [source, target] of Object.entries(profile.field_renames)) {
    if (source.toLowerCase() === target.toLowerCase()) {
      errors.push(`Field “${source}” is renamed to the same name.`);
    } else if (!fieldIsSelected(profile, target)) {
      errors.push(`Renamed field “${target}” must be included in the output.`);
    }
  }
  return [...new Set(errors)];
}

export function profileFieldNames(profile: ExportProfileData): string[] {
  const fields = [
    ...profile.field_order,
    ...(profile.field_selection.allowed_fields ?? []),
    ...profile.field_selection.excluded_fields,
    ...profile.excluded_fields,
    ...profile.case_protected_fields,
    ...Object.keys(profile.field_renames),
    ...Object.values(profile.field_renames),
  ];
  return uniqueFields(fields);
}

export function hasField(fields: readonly string[], candidate: string) {
  return fields.some(
    (field) => field.toLowerCase() === candidate.toLowerCase(),
  );
}

export function withoutField(fields: readonly string[], candidate: string) {
  return fields.filter(
    (field) => field.toLowerCase() !== candidate.toLowerCase(),
  );
}

export function uniqueFields(fields: readonly string[]) {
  const seen = new Set<string>();
  return fields.filter((field) => {
    const key = field.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function validFieldName(value: string) {
  return FIELD_NAME.test(value);
}

function fieldIsSelected(profile: ExportProfileData, field: string) {
  const excluded = [
    ...profile.excluded_fields,
    ...profile.field_selection.excluded_fields,
  ];
  if (hasField(excluded, field)) return false;
  const allowed = profile.field_selection.allowed_fields;
  return allowed === null || hasField(allowed, field);
}

function validateFieldList(
  label: string,
  fields: readonly string[],
  errors: string[],
) {
  const seen = new Set<string>();
  for (const field of fields) {
    if (!FIELD_NAME.test(field)) {
      errors.push(`${label} contains an invalid name: “${field}”.`);
      continue;
    }
    const key = field.toLowerCase();
    if (seen.has(key)) {
      errors.push(`${label} contains “${field}” more than once.`);
    }
    seen.add(key);
  }
}
