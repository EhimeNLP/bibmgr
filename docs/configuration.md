# Configuration

Versioned TOML files define validation policy. Registration and semantic export use separate typed policies so that an export representation cannot silently change whether a source is accepted. Venue and repository identity live in separate registries.

```text
config/
|- export-profiles/
|  |- modern.toml
|  |- laboratory.toml
|  |- acl.toml
|  |- aaai.toml
|  |- classical-bst.toml
|  `- legacy-arxiv-article.toml
|- policies/
|  |- laboratory.toml
|  |- modern.toml
|  |- acl.toml
|  `- classical-bst.toml
`- registries/
   |- venues.toml
   `- repositories.toml
```

## Loading

Defaults are embedded in the Rust binary/extension, so missing checkout files do not make basic analysis unusable. The current CLI and Python API select these embedded validation and export profiles by ID. Applications that load the checked-in TOML files must accept a snapshot only when every file has schema version 1 and passes typed validation; a request must never observe a partially reloaded registry.

Rust hosts can inject immutable `VenueRegistry` and `RepositoryRegistry` snapshots through `AnalysisOptions`. Omitting a snapshot selects the embedded registry; supplying an explicitly empty snapshot disables it. This keeps the CLI/Python defaults deterministic while allowing externally managed registries without introducing adapter-side rules.

## Policy shape

```toml
schema_version = "1"
profile = "laboratory"
field_case = "lowercase"
field_order = ["title", "author", "booktitle", "pages", "year", "doi", "url"]
citation_key_pattern = '^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$'
forbidden_fields = ["file", "timestamp"]
url_policy = "discourage"
arxiv_representation = "eprint"
prefer_braces = true

[required_fields]
article = ["author", "title", "journal", "year"]
inproceedings = ["author", "title", "booktitle", "year"]

[rules."LAB-KEY-002"]
enabled = true
severity = "warning"
blocking = true
```

`field_case` is `lowercase`, `canonical`, or `preserve`. `url_policy` is `allow`, `discourage`, or `forbid`. Rule entries may override enabled state, severity, and blocking independently. Omitted registered rules use embedded defaults; an unknown code is an error.

The syntax style catalog includes `BIB-SYNTAX-006`, which normalizes each simple horizontal whitespace gap adjacent to a field's `=` to one space, and `BIB-SYNTAX-007`, which reports percent comments located inside an entry. The whitespace fix never rewrites a gap containing a line break or comment. Inline percent comments are diagnostic only and should be moved between entries manually.

The `laboratory` profile treats field spelling, field order, trailing commas, value delimiters, whitespace around `=`, and discouraged retention of a valid URL as non-blocking presentation guidance. Correctness, identity, required-data, malformed URLs, entry-internal percent comments that require parser recovery, and explicit laboratory-convention rules remain blocking.

The duplicate semantic analyzer codes `BIB-SEMANTIC-103`, `BIB-SEMANTIC-104`, and `BIB-SEMANTIC-105` are retired in favor of the canonical DOI, arXiv, and date codes `BIB-SEMANTIC-001`, `BIB-SEMANTIC-002`, and `BIB-SEMANTIC-007`. TOML loaders migrate the retired codes to their canonical replacements and reject conflicting settings.

Validation-time arXiv representations are `any`, `eprint`, `howpublished`, and `article-journal`. Field order contains valid, unique BibTeX names. Invalid regular expressions, duplicate fields, unknown rule codes, empty profile IDs, and unsupported schema versions are rejected while loading.

Parse mode is an analysis option rather than policy content: editors use tolerant mode, while registration and export use strict mode.

## Registration policy

Registration resolves one validation profile and then applies independent acceptance settings:

```toml
schema_version = "1"
validation_profile = "laboratory"
minimum_severity = "error"
allow_unresolved_semantics = false
apply_safe_fixes = false

[blocking_rules]
all = false
include = ["LAB-KEY-002", "LAB-ENTRY-003"]
exclude = []
```

An empty `blocking_rules.include` list does not disable per-diagnostic blocking or the optional severity threshold. The built-in `laboratory` registration policy blocks all errors plus rules explicitly marked blocking, rejects unresolved semantics, and does not promote every warning to blocking. The core returns the final `accepted` decision; adapters do not re-evaluate these fields.

## Export profile

Export profiles are typed separately and include serialization-only fields such as `preprint_representation`, `venue_style`, `field_case`, `value_delimiter`, `line_ending`, `indent`, and `trailing_comma`. Each profile also names an explicit `validation_profile`. The generated BibTeX is re-analyzed with that policy; an unavailable validation profile is an error rather than a skipped readiness check. Supported preprint values are:

- `misc-eprint`: `@misc`, `eprint`, and `archivePrefix`;
- `misc-howpublished`: `@misc` and `howpublished`;
- `article-journal`: legacy `@article` and `journal`.

Venue styles are `full`, `short`, and `as-recorded`. The built-in validation and export profiles share IDs (`modern`, `laboratory`, `acl`, and `classical-bst`) but remain separate values. `aaai` and `legacy-arxiv-article` use `modern` as their target validation profile.

Each checked-in output profile is a complete TOML document and includes user-facing catalog metadata. Field selection is configured separately from presentation order:

```toml
schema_version = "1"
profile = "laboratory"
display_name = "Laboratory Canonical"
description = "Canonical laboratory output with full venue names and a compact field projection."
validation_profile = "laboratory"
preprint_representation = "misc-eprint"
venue_style = "full"
field_case = "lowercase"
field_order = ["title", "author", "editor", "journal", "booktitle", "series", "volume", "number", "pages", "publisher", "institution", "school", "address", "year", "doi", "eprint", "archiveprefix", "primaryclass", "url", "note"]
include_url = false

[field_selection]
allowed_fields = ["title", "author", "editor", "journal", "booktitle", "series", "volume", "number", "pages", "publisher", "institution", "school", "address", "year", "doi", "eprint", "archiveprefix", "primaryclass", "note"]
excluded_fields = ["url"]
```

`field_order` controls only serialization order and never implicitly deletes a field. `field_selection.allowed_fields` is a case-insensitive allowlist applied to every generated candidate field, including structured identifiers and extra fields; omitting it allows every candidate. `field_selection.excluded_fields` is a case-insensitive denylist applied after the allowlist. Invalid names, duplicates, and fields present in both lists are rejected while loading.

The older top-level `include_doi`, `include_url`, `include_extra_fields`, and `excluded_fields` keys remain accepted for API compatibility, but new profiles should express the final field projection with `[field_selection]`. After compatibility include switches are applied, profile optimization projects all enabled structured and extra candidate fields, normalizes field names, sorts the survivors, and serializes them.

| Export profile | Intended optimization |
| --- | --- |
| `modern` | General modern BibTeX with `eprint` metadata and preserved supported extras |
| `laboratory` | Full venue names, lowercase laboratory order, `misc-eprint`, and no discouraged URL or private metadata |
| `acl` | ACL-oriented field allowlist and ordering |
| `aaai` | AAAI-oriented field allowlist and ordering without URL |
| `classical-bst` | Classical BibTeX fields with preprints represented through `howpublished` |
| `legacy-arxiv-article` | Legacy preprints represented as `@article` with an arXiv `journal` value |

`default` remains an API alias for `modern`, and `article-journal` remains an API alias for `legacy-arxiv-article`; aliases are not duplicated in the profile catalog.

## Inheritance

`extends` is reserved on validation policy files for a profile-set loader. The checked-in policies are intentionally self-contained. A loader that accepts a set must resolve parents before publication and reject a missing parent, duplicate ID, self-reference, or multi-profile cycle. Resolved values, rather than partial files, participate in determinism and cache keys.

## Registry validation

Startup fails with a path-aware error for:

- an unknown rule code or invalid regular expression;
- duplicate policy/profile or venue/repository IDs;
- profile inheritance cycles;
- invalid/duplicate fields in field ordering;
- alias collisions after Unicode case folding and whitespace normalization;
- malformed identifier patterns or URL templates.

Configuration errors are not returned as document diagnostics because changing the document cannot fix them.

## Deployment guidance

Check policy and registry files into source control. Pin the active profile by ID in each environment. Log the resolved profile and registry snapshot digest with registration/export operations. A production service should validate a new snapshot before atomically swapping it into use.

See [Adding a rule](adding-rules.md) and [Adding a venue](venues.md).
