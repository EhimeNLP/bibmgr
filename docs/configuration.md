# Configuration

Versioned TOML files define validation policy. Registration and semantic export use separate typed policies so that an export representation cannot silently change whether a source is accepted. Venue and repository identity live in separate registries.

```text
config/
|- export-profiles/
|  |- aaai-conference.toml
|  |- acl-publications.toml
|  |- acm-publications.toml
|  |- classical-bst.toml
|  |- eamt-conference.toml
|  |- ieee-publications.toml
|  |- information-processing-society-of-japan-english.toml
|  |- information-processing-society-of-japan-japanese.toml
|  |- japanese-society-for-artificial-intelligence-journal.toml
|  |- journal-of-natural-language-processing-japanese.toml
|  |- laboratory.toml
|  |- legacy-arxiv-article.toml
|  |- lrec-language-resources.toml
|  |- machine-learning-conferences.toml
|  |- modern.toml
|  |- natbib-full-author-names.toml
|  `- springer-lncs.toml
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
field_case = "canonical"
field_order = ["title", "author", "booktitle", "pages", "year", "doi", "url"]
citation_key_pattern = '^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$'
forbidden_fields = ["file", "timestamp"]
url_policy = "allow"
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

The syntax style catalog includes `BIB-SYNTAX-006`, which normalizes each simple horizontal whitespace gap adjacent to a field's `=` to one space, `BIB-SYNTAX-007`, which reports percent comments located inside an entry, `BIB-SYNTAX-008`, which reports an unsafe raw TeX-special character in a field value that can be emitted as TeX text, and `BIB-SYNTAX-009`, which safely replaces line boundaries inside braced or quoted field values with one space. The value-line fix retains braces and all other BibTeX bytes, including title case-protection groups. The equals-whitespace fix never rewrites a gap containing a line break or comment. Inline percent comments are diagnostic only and should be moved between entries manually.

`BIB-SYNTAX-008` covers raw `%`, `&`, `#`, and `_` in text mode, raw `^` in text mode, and an unmatched `$`. Plain `%`, `&`, `#`, and `_` in conventional prose fields receive safe backslash fixes; a literal caret uses `\textasciicircum{}` and an unmatched dollar uses `\$`, both with confirmation because they can represent unfinished TeX. Complete `$...$`, `$$...$$`, `\(...\)`, `\[...\]`, and `\ensuremath{...}` spans preserve math syntax, although raw `%` remains unsafe and raw `#` requires review within math. A math delimiter pair must close within the same balanced brace group and optional argument scope; delimiters cannot become valid merely by pairing across either boundary. Paired dollar signs are therefore interpreted as math; literal currency or dollar text must use `\$`. Raw `~` remains a valid nonbreaking space, while backslashes and balanced braces remain TeX command and grouping syntax rather than literal-character diagnostics.

The TeX-special rule excludes raw identifier fields used for URLs, repository identifiers, and publication identifiers, plus literal content only inside complete braced arguments of `\url{...}`, `\nolinkurl{...}`, and `\path{...}`. Complete delimiter forms of `\verb`, `\verb*`, `\Verb`, and `\lstinline` are treated as verbatim and are not diagnosed, while incomplete or ambiguous literal forms and ordinary TeX command arguments require confirmation. Referenced `@string` definitions are followed recursively in the context of every consuming field; simple aliases retain the leaf applicability, command or math context that crosses a macro or concatenation boundary requires confirmation, a definition used only by excluded fields is not diagnosed, and a definition shared by prose and excluded fields is diagnosed without an automatic fix. Macro traversal is bounded by global visit and expansion-depth limits; if either limit is reached before traversal completes, an incomplete-analysis diagnostic is emitted and automatic fixes for all referenced `@string` values are disabled.

The `laboratory` profile treats field spelling, field order, trailing commas, value delimiters, whitespace around `=`, and field-value line normalization as non-blocking presentation guidance. Safe storage canonicalization applies these fixes, so internal line boundaries become spaces without changing title case-protection groups. Laboratory storage retains valid bibliographic metadata such as `abstract`, `keywords`, and `url`; only local `file` and generated `timestamp` fields are forbidden. An export profile may project retained metadata out of generated BibTeX without changing the stored source. No URL policy offers a metadata-deleting fix. Correctness, identity, required-data, malformed URLs, entry-internal percent comments that require parser recovery, unsafe raw TeX-special characters in text values, and explicit laboratory-convention rules remain blocking.

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

Venue styles are `full`, `short`, and `as-recorded`. The validation catalog contains `modern`, `laboratory`, `acl`, and `classical-bst`; export profiles with one of those IDs still resolve to a separate typed value. Artifact-derived export profiles explicitly reuse the closest validation policy: `aaai`, `acm-publications`, `ieee-publications`, `ml-conferences`, and `springer-lncs` use `modern`; `lrec` uses `acl`; `eamt`, both IPSJ profiles, `jnlp-japanese`, `jsai-journal`, and `natbib-full-author-names` use `classical-bst`. `legacy-arxiv-article` also uses `modern`.

These reused validation policies are general readiness baselines rather than complete validators for each referenced BST; target-specific field and entry-type compatibility is enforced by the export profile, while the selected validation policy checks the generated document's shared syntax and semantic requirements.

Each checked-in output profile is a complete TOML document and includes user-facing catalog metadata. Field selection is configured separately from presentation order:

```toml
schema_version = "1"
profile = "laboratory"
display_name = "Laboratory Canonical"
description = "Canonical laboratory output with full venue names, preserved URLs, and a compact field projection."
validation_profile = "laboratory"
preprint_representation = "misc-eprint"
venue_style = "full"
field_case = "canonical"
field_order = ["title", "author", "editor", "journal", "booktitle", "series", "volume", "number", "pages", "publisher", "institution", "school", "address", "year", "doi", "eprint", "archivePrefix", "primaryClass", "url", "note"]
include_url = true

[field_selection]
allowed_fields = ["title", "author", "editor", "journal", "booktitle", "series", "volume", "number", "pages", "publisher", "institution", "school", "address", "year", "doi", "eprint", "archivePrefix", "primaryClass", "url", "note"]
excluded_fields = []
```

`field_order` controls only serialization order and never implicitly deletes a field. `field_selection.allowed_fields` is a case-insensitive allowlist applied to every generated candidate field, including structured identifiers and extra fields; omitting it allows every candidate. `field_selection.excluded_fields` is a case-insensitive denylist applied after the allowlist. Invalid names, duplicates, and fields present in both lists are rejected while loading.

`month_format` is either `numeric` or `bibtex-macro`. `numeric` serializes a parsed month as a delimited number, while `bibtex-macro` emits a standard BibTeX month macro such as `jan` without braces or quotes; every artifact-derived profile uses `bibtex-macro` for compatibility with its target BST family.

`supported_entry_types` is a case-insensitive target entry-type allowlist. When the original non-preprint entry type appears in this list, export preserves that BST-native type instead of replacing it with the general semantic mapping; otherwise the mapped target type must itself appear in the allowlist. An empty list leaves the general mapping unrestricted.

`[field_renames]` defines case-insensitive source-to-target field names and is applied after candidate generation but before field projection. The ACL and LREC profiles use `pmid = "pubmed"`, allowing semantic PMID data to reach the `pubmed` field spelling expected by those BST families.

The older top-level `include_doi`, `include_url`, `include_extra_fields`, and `excluded_fields` keys remain accepted for API compatibility, but new profiles should express the final field projection with `[field_selection]`. After compatibility include switches are applied, profile optimization generates structured and extra candidate fields, applies `[field_renames]`, projects the enabled fields, normalizes field names, sorts the survivors, and serializes them.

During semantic export, prose text escapes raw `%`, `&`, `#`, and `_`, renders a text-mode caret as `\textasciicircum{}`, and escapes an unmatched dollar. Complete TeX math spans retain their delimiters, subscripts, superscripts, and alignment markers, while raw URL-like fields and recognized URL or verbatim command arguments retain their identifier bytes.

| Export profile | Configuration file | BST reference or role | Intended optimization |
| --- | --- | --- | --- |
| `modern` | `modern.toml` | General-purpose built-in | Modern BibTeX with structured identifiers, `eprint` metadata, and preserved supported extras |
| `laboratory` | `laboratory.toml` | Laboratory convention | Full venue names, canonical field spelling, `misc-eprint`, preserved URL metadata, and no private local metadata |
| `acl` | `acl-publications.toml` | `acl_natbib.bst` | ACL publication fields, including DOI, renamed `pubmed`, eprint, and web metadata |
| `aaai` | `aaai-conference.toml` | `aaai2026.bst` | AAAI publication, ISBN, EID, and eprint fields without DOI or URL |
| `acm-publications` | `acm-publications.toml` | `ACM-Reference-Format.bst` | ACM identifiers, eprints, and ACM-specific publication metadata |
| `ieee-publications` | `ieee-publications.toml` | `IEEEtran.bst` and `IEEEtranS.bst` | Shared IEEE field projection; the bibliography-order difference between the two BST files is intentionally consolidated |
| `natbib-full-author-names` | `natbib-full-author-names.toml` | `ieeenat_fullname.bst` | Author-year natbib fields with identifier fields suppressed; full-name rendering remains the BST's responsibility |
| `springer-lncs` | `springer-lncs.toml` | `splncs04.bst` | Traditional LNCS publication fields with DOI and URL metadata retained |
| `ml-conferences` | `machine-learning-conferences.toml` | `iclr2026_conference.bst`, `icml2026.bst`, and `colm2026_conference.bst` | Shared compatible projection for ICLR, ICML, and COLM fields, including DOI, URL, ISBN, ISSN, and EID |
| `lrec` | `lrec-language-resources.toml` | `lrec2026-natbib.bst` | LREC publication fields, renamed `pubmed`, and language-resource identifiers such as ISLRN and PID |
| `eamt` | `eamt-conference.toml` | `eamt26.bst` | Conservative classical publication fields supported by the EAMT style |
| `ipsj-japanese` | `information-processing-society-of-japan-japanese.toml` | `ipsjsort.bst` and `ipsjunsrt.bst` | Japanese IPSJ fields with yomi and web metadata; sorted and unsorted BST variants share one projection |
| `ipsj-english` | `information-processing-society-of-japan-english.toml` | `ipsjsort-e.bst` and `ipsjunsrt-e.bst` | English IPSJ fields with DOI and web metadata; sorted and unsorted BST variants share one projection |
| `jnlp-japanese` | `journal-of-natural-language-processing-japanese.toml` | `jnlpbbl_1.7.bst` | Japanese natural-language-processing fields with yomi, romaji, and web metadata |
| `jsai-journal` | `japanese-society-for-artificial-intelligence-journal.toml` | `jsai.bst` | JSAI journal fields with yomi metadata and identifiers suppressed to match style support |
| `classical-bst` | `classical-bst.toml` | Conservative built-in | Classical BibTeX fields with preprints represented through `howpublished` |
| `legacy-arxiv-article` | `legacy-arxiv-article.toml` | Legacy compatibility built-in | Legacy preprints represented as `@article` with an arXiv `journal` value |

The artifact-derived profiles are field-compatible optimizations informed by the referenced BST files, not executions or complete reproductions of those styles. They preserve an original BST-native entry type when it is explicitly supported, but do not reproduce bibliography sorting, citation-label construction, author-name formatting, punctuation, or entry-type-specific conditional field formatting and suppression; those remain responsibilities of a BST processor or the target publication toolchain.

Every artifact-derived profile sets `allow_unknown_work_type = false`. An unrecognized semantic work type is exported only when its original entry type is explicitly listed in `supported_entry_types`; an unsupported original type fails export instead of being silently converted to `@misc`. The general-purpose `modern` and compatibility-focused `legacy-arxiv-article` profiles retain their existing unrestricted fallback behavior and are not artifact-derived profiles.

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
