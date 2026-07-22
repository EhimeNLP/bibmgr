use crate::{
    parse_people, Ambiguity, ArxivId, BibliographicRecord, Bibliography, CitationKey, Confidence,
    Doi, Identifiers, Isbn, Issn, OriginKind, OtherIdentifier, Person, Preprint, PublicationDate,
    Repository, SemanticCandidate, SemanticConflict, SemanticField, SemanticValue, Sourced,
    SyntaxOrigin, Title, Url, ValueStatus, VenueRef, WorkType,
};
use bibmgr_model::{Diagnostic, DiagnosticId, RuleCode, Severity, SourceLocation, TextRange};
use bibmgr_syntax::{
    EntryNode, FieldNode, StringNode, SyntaxDocument, ValueAtomKind, ValueExpression,
};
use std::collections::{BTreeMap, BTreeSet};

pub(crate) fn analyze(document: &SyntaxDocument) -> Bibliography {
    let resolver = MacroResolver::new(document);
    let mut bibliography = Bibliography::default();
    for entry in document.entries() {
        bibliography.records.push(analyze_entry(
            document,
            entry,
            &resolver,
            &mut bibliography.diagnostics,
        ));
    }
    bibliography
}

#[derive(Debug)]
struct EvaluatedField<'a> {
    node: &'a FieldNode,
    value: SemanticValue,
    /// Macro references and every `@string` definition considered while
    /// resolving this field. This is the union across ambiguous branches.
    resolution_origins: Vec<SyntaxOrigin>,
    /// Candidate-specific provenance, retained separately so ambiguity DTOs
    /// do not attribute one definition branch to another candidate.
    candidates: Vec<ResolvedCandidate>,
}

impl EvaluatedField<'_> {
    fn text(&self) -> Option<&str> {
        self.value.resolved.as_deref()
    }
}

#[allow(clippy::too_many_lines)]
fn analyze_entry(
    document: &SyntaxDocument,
    entry: &EntryNode,
    resolver: &MacroResolver<'_>,
    diagnostics: &mut Vec<Diagnostic>,
) -> BibliographicRecord {
    let source_id = document.source_id().clone();
    let entry_origin = SyntaxOrigin::new(source_id.clone(), entry.range, OriginKind::Entry);
    let type_origin = SyntaxOrigin::new(
        source_id.clone(),
        entry.entry_type.range,
        OriginKind::EntryType,
    );
    let key_origin = SyntaxOrigin::new(
        source_id.clone(),
        entry.citation_key.range,
        OriginKind::CitationKey,
    );

    let fields = entry
        .fields
        .iter()
        .map(|node| {
            let evaluation = resolver.evaluate(&node.value, &node.name.text);
            EvaluatedField {
                node,
                value: evaluation.value,
                resolution_origins: evaluation.origins,
                candidates: evaluation.candidates,
            }
        })
        .collect::<Vec<_>>();

    emit_value_diagnostics(document, &fields, diagnostics);

    let mut ambiguities = field_ambiguities(document, &fields);
    ambiguities.extend(macro_expansion_ambiguities(document, &fields));
    ambiguities.extend(unresolved_ambiguities(document, &fields));
    let mut conflicts = field_conflicts(document, &fields);
    let title = first_field(&fields, "title")
        .and_then(|field| sourced_text(document, field, Title::new, ValueStatus::Parsed));
    let authors = people_from_field(document, first_field(&fields, "author"));
    let editors = people_from_field(document, first_field(&fields, "editor"));
    let date = analyze_date(document, &fields, &mut conflicts, diagnostics);
    let mut identifiers = analyze_identifiers(document, &fields, diagnostics);
    let urls = analyze_urls(document, &fields, diagnostics);
    infer_identifiers_from_urls(document, &fields, &urls, &mut identifiers);
    retain_identifier_conflicts(&identifiers, &mut ambiguities, &mut conflicts);
    let venue = analyze_venue(document, &fields);
    let preprint = analyze_preprint(document, &fields, &identifiers, &mut ambiguities);

    let explicit_type = work_type_from_entry_type(&entry.entry_type.text);
    let mut work_type = Sourced {
        value: explicit_type,
        origins: vec![type_origin.clone()],
        status: ValueStatus::Parsed,
        confidence: if explicit_type == WorkType::Unknown {
            Confidence::Low
        } else {
            Confidence::High
        },
    };
    if let Some(preprint_value) = &preprint {
        let venue_is_only_preprint = venue.as_ref().is_none_or(|venue| {
            venue_matches_repository(&venue.value.raw, &preprint_value.value.repository)
        });
        let has_published_doi = !identifiers.dois.is_empty();
        if matches!(
            explicit_type,
            WorkType::Miscellaneous | WorkType::WebResource | WorkType::Unknown
        ) || (explicit_type == WorkType::JournalArticle
            && venue_is_only_preprint
            && !has_published_doi)
        {
            work_type.value = WorkType::Preprint;
            work_type.status = ValueStatus::Inferred;
            work_type.confidence = preprint_value.confidence;
            work_type.origins.extend(preprint_value.origins.clone());
            if !matches!(explicit_type, WorkType::Miscellaneous | WorkType::Unknown) {
                conflicts.push(SemanticConflict {
                    field: "work_type".to_string(),
                    explicit_values: vec![entry.entry_type.text.clone()],
                    inferred_values: vec!["preprint".to_string()],
                    origins: work_type.origins.clone(),
                });
            }
        }
    }

    let known = [
        "title",
        "author",
        "editor",
        "date",
        "year",
        "month",
        "day",
        "journal",
        "journaltitle",
        "booktitle",
        "eventtitle",
        "doi",
        "url",
        "eprint",
        "archiveprefix",
        "eprinttype",
        "primaryclass",
        "eprintclass",
        "isbn",
        "issn",
        "pmid",
        "pmcid",
    ];
    let extra_fields = fields
        .iter()
        .filter(|field| {
            !known
                .iter()
                .any(|name| field.node.name.text.eq_ignore_ascii_case(name))
        })
        .map(|field| SemanticField {
            name: field.node.name.text.clone(),
            value: field.value.clone(),
            origins: field_origins(document, field, OriginKind::Field),
        })
        .collect();
    let unresolved_values = fields
        .iter()
        .filter(|field| field.value.resolved.is_none())
        .map(|field| SemanticField {
            name: field.node.name.text.clone(),
            value: field.value.clone(),
            origins: field_origins(document, field, OriginKind::FieldValue),
        })
        .collect();

    BibliographicRecord {
        citation_key: Sourced::explicit(
            CitationKey::new(entry.citation_key.text.clone()),
            key_origin,
        ),
        entry_type: Sourced::explicit(entry.entry_type.text.clone(), type_origin.clone()),
        work_type,
        title,
        authors,
        editors,
        date,
        venue,
        preprint,
        identifiers,
        urls,
        extra_fields,
        unresolved_values,
        ambiguities,
        conflicts,
        origins: vec![entry_origin, type_origin],
    }
}

struct MacroResolver<'a> {
    document: &'a SyntaxDocument,
    definitions: BTreeMap<String, Vec<&'a StringNode>>,
}

const MAX_MACRO_EXPANSION_DEPTH: usize = 256;

#[derive(Debug, Clone, Default)]
struct ResolvedCandidate {
    value: String,
    origins: Vec<SyntaxOrigin>,
}

#[derive(Debug, Default)]
struct ValueEvaluation {
    value: SemanticValue,
    selected: Option<ResolvedCandidate>,
    candidates: Vec<ResolvedCandidate>,
    origins: Vec<SyntaxOrigin>,
}

#[derive(Debug, Default)]
struct AtomResolution {
    selected: Option<ResolvedCandidate>,
    candidates: Vec<ResolvedCandidate>,
    unresolved: Vec<String>,
    origins: Vec<SyntaxOrigin>,
}

impl AtomResolution {
    fn prepend_origin(&mut self, origin: &SyntaxOrigin) {
        prepend_unique_origin(&mut self.origins, origin.clone());
        if let Some(selected) = &mut self.selected {
            prepend_unique_origin(&mut selected.origins, origin.clone());
        }
        for candidate in &mut self.candidates {
            prepend_unique_origin(&mut candidate.origins, origin.clone());
        }
    }
}

impl<'a> MacroResolver<'a> {
    fn new(document: &'a SyntaxDocument) -> Self {
        let mut definitions: BTreeMap<String, Vec<&StringNode>> = BTreeMap::new();
        for definition in document.strings() {
            definitions
                .entry(definition.name.text.to_ascii_lowercase())
                .or_default()
                .push(definition);
        }
        Self {
            document,
            definitions,
        }
    }

    fn evaluate(&self, expression: &ValueExpression, field_name: &str) -> ValueEvaluation {
        self.evaluate_inner(expression, field_name, &mut Vec::new())
    }

    fn evaluate_inner(
        &self,
        expression: &ValueExpression,
        field_name: &str,
        stack: &mut Vec<String>,
    ) -> ValueEvaluation {
        let raw = self
            .document
            .slice(expression.range)
            .unwrap_or_default()
            .to_string();
        let mut selected = Some(ResolvedCandidate::default());
        let mut all_candidates = vec![ResolvedCandidate::default()];
        let mut unresolved = Vec::new();
        let mut origins = Vec::new();

        for atom in &expression.atoms {
            let mut resolution = match atom.kind {
                ValueAtomKind::Braced { .. }
                | ValueAtomKind::Quoted { .. }
                | ValueAtomKind::Number => {
                    let value = self
                        .document
                        .slice(atom.content_range)
                        .unwrap_or_default()
                        .to_string();
                    AtomResolution {
                        selected: Some(ResolvedCandidate {
                            value: value.clone(),
                            origins: Vec::new(),
                        }),
                        candidates: vec![ResolvedCandidate {
                            value,
                            origins: Vec::new(),
                        }],
                        unresolved: Vec::new(),
                        origins: Vec::new(),
                    }
                }
                ValueAtomKind::Macro => {
                    let name = self.document.slice(atom.content_range).unwrap_or_default();
                    self.resolve_macro(name, stack)
                }
                ValueAtomKind::Invalid => AtomResolution {
                    selected: None,
                    candidates: Vec::new(),
                    unresolved: vec![self
                        .document
                        .slice(atom.content_range)
                        .unwrap_or_default()
                        .to_string()],
                    origins: Vec::new(),
                },
            };
            if atom.kind == ValueAtomKind::Macro {
                resolution.prepend_origin(
                    &SyntaxOrigin::new(
                        self.document.source_id().clone(),
                        atom.content_range,
                        OriginKind::MacroReference,
                    )
                    .for_field(field_name),
                );
            }
            selected = concatenate_selected(selected, resolution.selected.as_ref());
            unresolved.extend(resolution.unresolved);
            let atom_candidates = if resolution.candidates.is_empty() {
                vec![ResolvedCandidate {
                    value: String::new(),
                    origins: resolution.origins.clone(),
                }]
            } else {
                resolution.candidates
            };
            all_candidates = concatenate_candidates(&all_candidates, &atom_candidates);
            extend_unique_origins(&mut origins, resolution.origins);
        }

        deduplicate(&mut unresolved);
        normalize_candidates(&mut all_candidates);
        if let Some(selected) = &mut selected {
            selected.value = selected.value.trim().to_string();
        }
        let resolved = unresolved
            .is_empty()
            .then(|| selected.as_ref().map(|candidate| candidate.value.clone()))
            .flatten();
        ValueEvaluation {
            value: SemanticValue {
                raw,
                resolved,
                candidates: all_candidates
                    .iter()
                    .map(|candidate| candidate.value.clone())
                    .collect(),
                unresolved_macros: unresolved,
            },
            selected,
            candidates: all_candidates,
            origins,
        }
    }

    fn resolve_macro(&self, name: &str, stack: &mut Vec<String>) -> AtomResolution {
        let canonical = name.trim().to_ascii_lowercase();
        if let Some(month) = month_name(&canonical) {
            return AtomResolution {
                selected: Some(ResolvedCandidate {
                    value: month.to_string(),
                    origins: Vec::new(),
                }),
                candidates: vec![ResolvedCandidate {
                    value: month.to_string(),
                    origins: Vec::new(),
                }],
                unresolved: Vec::new(),
                origins: Vec::new(),
            };
        }
        if stack.contains(&canonical) {
            let mut cycle = stack.clone();
            cycle.push(canonical);
            return AtomResolution {
                selected: None,
                candidates: Vec::new(),
                unresolved: vec![cycle.join(" -> ")],
                origins: Vec::new(),
            };
        }
        if stack.len() >= MAX_MACRO_EXPANSION_DEPTH {
            return AtomResolution {
                selected: None,
                candidates: Vec::new(),
                unresolved: vec![format!("macro expansion depth exceeded at {name}")],
                origins: Vec::new(),
            };
        }
        let Some(definitions) = self.definitions.get(&canonical) else {
            return AtomResolution {
                selected: None,
                candidates: Vec::new(),
                unresolved: vec![name.to_string()],
                origins: Vec::new(),
            };
        };

        stack.push(canonical);
        let mut evaluated = definitions
            .iter()
            .map(|definition| {
                let mut evaluation =
                    self.evaluate_inner(&definition.value, &definition.name.text, stack);
                let origin = SyntaxOrigin::new(
                    self.document.source_id().clone(),
                    definition.range,
                    OriginKind::StringDefinition,
                )
                .for_field(definition.name.text.clone());
                prepend_unique_origin(&mut evaluation.origins, origin.clone());
                if let Some(selected) = &mut evaluation.selected {
                    prepend_unique_origin(&mut selected.origins, origin.clone());
                }
                for candidate in &mut evaluation.candidates {
                    prepend_unique_origin(&mut candidate.origins, origin.clone());
                }
                evaluation
            })
            .collect::<Vec<_>>();
        stack.pop();
        let selected = evaluated
            .last()
            .and_then(|evaluation| evaluation.selected.clone());
        let mut candidates = Vec::new();
        for evaluation in &mut evaluated {
            if evaluation.candidates.is_empty() {
                candidates.extend(evaluation.selected.clone());
            } else {
                candidates.append(&mut evaluation.candidates);
            }
        }
        let mut unresolved = evaluated
            .iter()
            .flat_map(|evaluation| evaluation.value.unresolved_macros.clone())
            .collect::<Vec<_>>();
        let mut origins = Vec::new();
        for evaluation in evaluated {
            extend_unique_origins(&mut origins, evaluation.origins);
        }
        normalize_candidates(&mut candidates);
        deduplicate(&mut unresolved);
        AtomResolution {
            selected,
            candidates,
            unresolved,
            origins,
        }
    }
}

fn concatenate_selected(
    prefix: Option<ResolvedCandidate>,
    suffix: Option<&ResolvedCandidate>,
) -> Option<ResolvedCandidate> {
    let mut prefix = prefix?;
    let suffix = suffix?;
    prefix.value.push_str(&suffix.value);
    extend_unique_origins(&mut prefix.origins, suffix.origins.clone());
    Some(prefix)
}

fn concatenate_candidates(
    left: &[ResolvedCandidate],
    right: &[ResolvedCandidate],
) -> Vec<ResolvedCandidate> {
    let mut output = Vec::new();
    for prefix in left {
        for suffix in right {
            if output.len() >= 32 {
                return output;
            }
            let mut origins = prefix.origins.clone();
            extend_unique_origins(&mut origins, suffix.origins.clone());
            output.push(ResolvedCandidate {
                value: format!("{}{}", prefix.value, suffix.value),
                origins,
            });
        }
    }
    output
}

fn normalize_candidates(candidates: &mut Vec<ResolvedCandidate>) {
    let mut normalized = Vec::<ResolvedCandidate>::new();
    for mut candidate in std::mem::take(candidates) {
        candidate.value = candidate.value.trim().to_string();
        if candidate.value.is_empty() {
            continue;
        }
        if let Some(existing) = normalized
            .iter_mut()
            .find(|existing| existing.value == candidate.value)
        {
            extend_unique_origins(&mut existing.origins, candidate.origins);
        } else {
            normalized.push(candidate);
        }
    }
    *candidates = normalized;
}

fn first_field<'a>(fields: &'a [EvaluatedField<'a>], name: &str) -> Option<&'a EvaluatedField<'a>> {
    fields
        .iter()
        .find(|field| field.node.name.text.eq_ignore_ascii_case(name))
}

fn fields_named<'a>(
    fields: &'a [EvaluatedField<'a>],
    name: &'a str,
) -> impl Iterator<Item = &'a EvaluatedField<'a>> {
    fields
        .iter()
        .filter(move |field| field.node.name.text.eq_ignore_ascii_case(name))
}

fn sourced_text<T>(
    document: &SyntaxDocument,
    field: &EvaluatedField<'_>,
    constructor: impl FnOnce(String) -> T,
    plain_status: ValueStatus,
) -> Option<Sourced<T>> {
    let text = field.text()?.trim();
    if text.is_empty() {
        return None;
    }
    let has_macros = field
        .node
        .value
        .atoms
        .iter()
        .any(|atom| atom.kind == ValueAtomKind::Macro);
    Some(Sourced {
        value: constructor(text.to_string()),
        origins: field_origins(document, field, OriginKind::FieldValue),
        status: if has_macros {
            ValueStatus::Resolved
        } else {
            plain_status
        },
        confidence: Confidence::High,
    })
}

fn people_from_field(
    document: &SyntaxDocument,
    field: Option<&EvaluatedField<'_>>,
) -> Vec<Sourced<Person>> {
    let Some(field) = field else {
        return Vec::new();
    };
    let Some(text) = field.text() else {
        return Vec::new();
    };
    let origins = field_origins(document, field, OriginKind::FieldValue);
    parse_people(text)
        .into_iter()
        .map(|person| Sourced {
            value: person,
            origins: origins.clone(),
            status: ValueStatus::Parsed,
            confidence: Confidence::High,
        })
        .collect()
}

#[allow(clippy::too_many_lines)]
fn analyze_date(
    document: &SyntaxDocument,
    fields: &[EvaluatedField<'_>],
    conflicts: &mut Vec<SemanticConflict>,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<Sourced<PublicationDate>> {
    let date_field = first_field(fields, "date");
    let year_field = first_field(fields, "year");
    let month_field = first_field(fields, "month");
    let day_field = first_field(fields, "day");

    let parsed_date = date_field
        .and_then(EvaluatedField::text)
        .map(parse_publication_date);
    let parsed_year = year_field
        .and_then(EvaluatedField::text)
        .and_then(parse_year);
    let parsed_month = month_field
        .and_then(EvaluatedField::text)
        .and_then(parse_month);
    let parsed_day = day_field.and_then(EvaluatedField::text).and_then(parse_day);
    if let (Some(date), Some(year)) = (&parsed_date, parsed_year) {
        if date.year.is_some_and(|date_year| date_year != year) {
            let mut origins = Vec::new();
            if let Some(field) = date_field {
                extend_unique_origins(
                    &mut origins,
                    field_origins(document, field, OriginKind::FieldValue),
                );
            }
            if let Some(field) = year_field {
                extend_unique_origins(
                    &mut origins,
                    field_origins(document, field, OriginKind::FieldValue),
                );
            }
            conflicts.push(SemanticConflict {
                field: "date/year".to_string(),
                explicit_values: vec![date.raw.clone(), year.to_string()],
                inferred_values: Vec::new(),
                origins: origins.clone(),
            });
            diagnostics.push(semantic_diagnostic(
                document,
                "BIB-SEMANTIC-007",
                Severity::Warning,
                false,
                "date and year fields disagree",
                origins.first().map(|origin| origin.range),
                diagnostics.len(),
            ));
        }
    }

    if let (Some(field), Some(mut date)) = (date_field, parsed_date) {
        let mut origins = field_origins(document, field, OriginKind::FieldValue);
        if date.year.is_none() {
            date.year = parsed_year;
            if parsed_year.is_some() {
                if let Some(year_field) = year_field {
                    extend_unique_origins(
                        &mut origins,
                        field_origins(document, year_field, OriginKind::FieldValue),
                    );
                }
            }
        }
        if date.month.is_none() {
            date.month = parsed_month;
            if parsed_month.is_some() {
                if let Some(month_field) = month_field {
                    extend_unique_origins(
                        &mut origins,
                        field_origins(document, month_field, OriginKind::FieldValue),
                    );
                }
            }
        }
        if date.day.is_none() {
            date.day = parsed_day;
            if parsed_day.is_some() {
                if let Some(day_field) = day_field {
                    extend_unique_origins(
                        &mut origins,
                        field_origins(document, day_field, OriginKind::FieldValue),
                    );
                }
            }
        }
        let has_year = date.year.is_some();
        let resolved_macro = origins
            .iter()
            .any(|origin| origin.kind == OriginKind::MacroReference);
        return Some(Sourced {
            value: date,
            origins,
            status: if has_year {
                if resolved_macro {
                    ValueStatus::Resolved
                } else {
                    ValueStatus::Parsed
                }
            } else {
                ValueStatus::Unresolved
            },
            confidence: if has_year {
                Confidence::High
            } else {
                Confidence::Low
            },
        });
    }
    let field = year_field?;
    let year = parsed_year;
    let mut origins = field_origins(document, field, OriginKind::FieldValue);
    if parsed_month.is_some() {
        if let Some(month_field) = month_field {
            extend_unique_origins(
                &mut origins,
                field_origins(document, month_field, OriginKind::FieldValue),
            );
        }
    }
    if parsed_day.is_some() {
        if let Some(day_field) = day_field {
            extend_unique_origins(
                &mut origins,
                field_origins(document, day_field, OriginKind::FieldValue),
            );
        }
    }
    let resolved_macro = origins
        .iter()
        .any(|origin| origin.kind == OriginKind::MacroReference);
    Some(Sourced {
        value: PublicationDate {
            raw: field.text().unwrap_or_default().to_string(),
            year,
            month: parsed_month,
            day: parsed_day,
        },
        origins,
        status: if year.is_some() {
            if resolved_macro {
                ValueStatus::Resolved
            } else {
                ValueStatus::Parsed
            }
        } else {
            ValueStatus::Unresolved
        },
        confidence: if year.is_some() {
            Confidence::High
        } else {
            Confidence::Low
        },
    })
}

fn analyze_venue(
    document: &SyntaxDocument,
    fields: &[EvaluatedField<'_>],
) -> Option<Sourced<VenueRef>> {
    ["journal", "journaltitle", "booktitle", "eventtitle"]
        .iter()
        .find_map(|name| first_field(fields, name))
        .and_then(|field| {
            sourced_text(
                document,
                field,
                |raw| VenueRef {
                    full_name: Some(raw.clone()),
                    raw,
                    venue_id: None,
                    short_name: None,
                    kind: None,
                },
                ValueStatus::Explicit,
            )
        })
}

#[allow(clippy::too_many_lines)]
fn analyze_identifiers(
    document: &SyntaxDocument,
    fields: &[EvaluatedField<'_>],
    diagnostics: &mut Vec<Diagnostic>,
) -> Identifiers {
    let mut identifiers = Identifiers::default();
    for field in fields_named(fields, "doi") {
        let Some(raw) = field.text() else {
            continue;
        };
        if let Some(doi) = normalize_doi(raw) {
            push_unique(
                &mut identifiers.dois,
                Sourced {
                    value: Doi::new(doi),
                    origins: field_origins(document, field, OriginKind::FieldValue),
                    status: ValueStatus::Normalized,
                    confidence: Confidence::High,
                },
                |value| value.as_str(),
            );
        } else {
            diagnostics.push(semantic_diagnostic(
                document,
                "BIB-SEMANTIC-001",
                Severity::Warning,
                false,
                format!("invalid DOI: {raw}"),
                Some(field.node.value.range),
                diagnostics.len(),
            ));
        }
    }
    for field in fields_named(fields, "isbn") {
        if let Some(value) = field
            .text()
            .map(normalize_isbn)
            .filter(|value| !value.is_empty())
        {
            push_unique(
                &mut identifiers.isbns,
                normalized_sourced(document, field, Isbn::new(value)),
                |value| value.as_str(),
            );
        }
    }
    for field in fields_named(fields, "issn") {
        if let Some(value) = field
            .text()
            .map(normalize_issn)
            .filter(|value| !value.is_empty())
        {
            push_unique(
                &mut identifiers.issns,
                normalized_sourced(document, field, Issn::new(value)),
                |value| value.as_str(),
            );
        }
    }
    for scheme in ["pmid", "pmcid"] {
        for field in fields_named(fields, scheme) {
            if let Some(value) = field
                .text()
                .map(str::trim)
                .filter(|value| !value.is_empty())
            {
                identifiers.other.push(Sourced {
                    value: OtherIdentifier {
                        scheme: scheme.to_string(),
                        value: value.to_string(),
                    },
                    origins: field_origins(document, field, OriginKind::FieldValue),
                    status: ValueStatus::Normalized,
                    confidence: Confidence::High,
                });
            }
        }
    }

    let explicit_repository = preprint_repository_field(fields)
        .and_then(EvaluatedField::text)
        .map(str::trim)
        .filter(|value| !value.is_empty());
    let archive_is_arxiv = explicit_repository.is_some_and(contains_arxiv);
    let eprint_may_be_arxiv = explicit_repository.is_none() || archive_is_arxiv;
    for field in fields_named(fields, "arxiv") {
        let Some(raw) = field.text() else {
            continue;
        };
        if let Some(parsed) = parse_arxiv(raw) {
            push_unique(
                &mut identifiers.arxiv,
                Sourced {
                    value: ArxivId::new(parsed.full),
                    origins: field_origins(document, field, OriginKind::FieldValue),
                    status: ValueStatus::Normalized,
                    confidence: Confidence::High,
                },
                |value| value.as_str(),
            );
        } else {
            diagnostics.push(semantic_diagnostic(
                document,
                "BIB-SEMANTIC-002",
                Severity::Warning,
                false,
                format!("invalid arXiv identifier: {raw}"),
                Some(field.node.value.range),
                diagnostics.len(),
            ));
        }
    }
    for field in fields_named(fields, "eprint") {
        let Some(raw) = field.text() else {
            continue;
        };
        if eprint_may_be_arxiv {
            if let Some(parsed) = parse_arxiv(raw) {
                push_unique(
                    &mut identifiers.arxiv,
                    Sourced {
                        value: ArxivId::new(parsed.full),
                        origins: field_origins(document, field, OriginKind::FieldValue),
                        status: ValueStatus::Normalized,
                        confidence: if archive_is_arxiv {
                            Confidence::High
                        } else {
                            Confidence::Medium
                        },
                    },
                    |value| value.as_str(),
                );
            } else {
                diagnostics.push(semantic_diagnostic(
                    document,
                    "BIB-SEMANTIC-002",
                    Severity::Warning,
                    false,
                    format!("invalid arXiv identifier: {raw}"),
                    Some(field.node.value.range),
                    diagnostics.len(),
                ));
            }
        }
    }
    for name in ["journal", "journaltitle", "howpublished", "note"] {
        for field in fields_named(fields, name) {
            let Some(raw) = field.text() else {
                continue;
            };
            if contains_arxiv(raw) {
                if let Some(parsed) = parse_arxiv(raw) {
                    push_unique(
                        &mut identifiers.arxiv,
                        Sourced {
                            value: ArxivId::new(parsed.full),
                            origins: field_origins(document, field, OriginKind::Inference),
                            status: ValueStatus::Inferred,
                            confidence: Confidence::Medium,
                        },
                        |value| value.as_str(),
                    );
                }
            }
        }
    }
    identifiers
}

fn analyze_urls(
    document: &SyntaxDocument,
    fields: &[EvaluatedField<'_>],
    diagnostics: &mut Vec<Diagnostic>,
) -> Vec<Sourced<Url>> {
    let mut urls = Vec::new();
    for field in fields_named(fields, "url") {
        let Some(raw) = field
            .text()
            .map(str::trim)
            .filter(|value| !value.is_empty())
        else {
            continue;
        };
        match url::Url::parse(raw) {
            Ok(parsed) if matches!(parsed.scheme(), "http" | "https") => {
                push_unique(
                    &mut urls,
                    Sourced {
                        value: Url::new(parsed.to_string()),
                        origins: field_origins(document, field, OriginKind::FieldValue),
                        status: ValueStatus::Normalized,
                        confidence: Confidence::High,
                    },
                    |value| value.as_str(),
                );
            }
            _ => diagnostics.push(semantic_diagnostic(
                document,
                "BIB-SEMANTIC-106",
                Severity::Warning,
                false,
                format!("invalid absolute URL: {raw}"),
                Some(field.node.value.range),
                diagnostics.len(),
            )),
        }
    }
    urls
}

fn infer_identifiers_from_urls(
    document: &SyntaxDocument,
    fields: &[EvaluatedField<'_>],
    urls: &[Sourced<Url>],
    identifiers: &mut Identifiers,
) {
    for url in urls {
        if let Some(doi) = normalize_doi(url.value.as_str()) {
            push_unique(
                &mut identifiers.dois,
                Sourced {
                    value: Doi::new(doi),
                    origins: url.origins.clone(),
                    status: ValueStatus::Inferred,
                    confidence: Confidence::High,
                },
                |value| value.as_str(),
            );
        }
        if let Some(arxiv) = parse_arxiv(url.value.as_str()) {
            push_unique(
                &mut identifiers.arxiv,
                Sourced {
                    value: ArxivId::new(arxiv.full),
                    origins: url.origins.clone(),
                    status: ValueStatus::Inferred,
                    confidence: Confidence::High,
                },
                |value| value.as_str(),
            );
        }
    }
    // A malformed URL can still carry a useful identifier.
    for field in fields_named(fields, "url") {
        let Some(raw) = field.text() else {
            continue;
        };
        if let Some(arxiv) = parse_arxiv(raw) {
            push_unique(
                &mut identifiers.arxiv,
                Sourced {
                    value: ArxivId::new(arxiv.full),
                    origins: field_origins(document, field, OriginKind::Inference),
                    status: ValueStatus::Inferred,
                    confidence: Confidence::Medium,
                },
                |value| value.as_str(),
            );
        }
    }
}

fn analyze_preprint(
    document: &SyntaxDocument,
    fields: &[EvaluatedField<'_>],
    identifiers: &Identifiers,
    ambiguities: &mut Vec<Ambiguity>,
) -> Option<Sourced<Preprint>> {
    retain_repository_ambiguity(document, fields, ambiguities);
    if let Some(repository_field) = preprint_repository_field(fields) {
        let repository_name = repository_field.text()?.trim();
        if !contains_arxiv(repository_name) {
            return analyze_explicit_preprint(document, fields, repository_field, repository_name);
        }
    }

    let first = identifiers.arxiv.first()?;
    if identifiers.arxiv.len() > 1 {
        ambiguities.push(Ambiguity {
            kind: "multiple-arxiv-identifiers".to_string(),
            message: "multiple distinct arXiv identifiers are present".to_string(),
            candidates: identifiers
                .arxiv
                .iter()
                .map(|identifier| SemanticCandidate {
                    value: identifier.value.to_string(),
                    status: identifier.status,
                    confidence: identifier.confidence,
                    origins: identifier.origins.clone(),
                })
                .collect(),
            origins: identifiers
                .arxiv
                .iter()
                .flat_map(|identifier| identifier.origins.clone())
                .collect(),
        });
    }
    let parsed = parse_arxiv(first.value.as_str())?;
    let primary_category_field = ["primaryclass", "eprintclass"]
        .iter()
        .find_map(|name| first_field(fields, name));
    let primary_category = primary_category_field
        .and_then(EvaluatedField::text)
        .map(ToOwned::to_owned);
    let mut origins = first.origins.clone();
    for field in ["archiveprefix", "eprinttype"]
        .iter()
        .filter_map(|name| first_field(fields, name))
    {
        extend_unique_origins(
            &mut origins,
            field_origins(document, field, OriginKind::Inference),
        );
    }
    if let Some(field) = primary_category_field {
        extend_unique_origins(
            &mut origins,
            field_origins(document, field, OriginKind::FieldValue),
        );
    }
    Some(Sourced {
        value: Preprint {
            repository: Repository::ArXiv,
            identifier: parsed.base,
            version: parsed.version,
            primary_category,
        },
        origins,
        status: if first.status == ValueStatus::Explicit {
            ValueStatus::Parsed
        } else {
            ValueStatus::Inferred
        },
        confidence: first.confidence,
    })
}

fn analyze_explicit_preprint(
    document: &SyntaxDocument,
    fields: &[EvaluatedField<'_>],
    repository_field: &EvaluatedField<'_>,
    repository_name: &str,
) -> Option<Sourced<Preprint>> {
    let identifier_field = fields_named(fields, "eprint").find(|field| {
        field
            .text()
            .is_some_and(|identifier| !identifier.trim().is_empty())
    })?;
    let identifier = identifier_field.text()?.trim().to_string();
    let primary_category_field = ["primaryclass", "eprintclass"]
        .iter()
        .find_map(|name| first_field(fields, name));
    let primary_category = primary_category_field
        .and_then(EvaluatedField::text)
        .map(str::trim)
        .filter(|category| !category.is_empty())
        .map(ToOwned::to_owned);
    let mut origins = field_origins(document, identifier_field, OriginKind::FieldValue);
    extend_unique_origins(
        &mut origins,
        field_origins(document, repository_field, OriginKind::Inference),
    );
    if let Some(field) = primary_category_field {
        extend_unique_origins(
            &mut origins,
            field_origins(document, field, OriginKind::FieldValue),
        );
    }
    let contains_resolved_macro = [identifier_field, repository_field].iter().any(|field| {
        field
            .node
            .value
            .atoms
            .iter()
            .any(|atom| atom.kind == ValueAtomKind::Macro)
    });

    Some(Sourced {
        value: Preprint {
            repository: Repository::Other(repository_name.to_string()),
            identifier,
            version: None,
            primary_category,
        },
        origins,
        status: if contains_resolved_macro {
            ValueStatus::Resolved
        } else {
            ValueStatus::Parsed
        },
        confidence: Confidence::High,
    })
}

fn preprint_repository_field<'a>(
    fields: &'a [EvaluatedField<'a>],
) -> Option<&'a EvaluatedField<'a>> {
    ["archiveprefix", "eprinttype"]
        .iter()
        .flat_map(|name| fields_named(fields, name))
        .find(|field| {
            field
                .text()
                .is_some_and(|repository| !repository.trim().is_empty())
        })
}

fn retain_repository_ambiguity(
    document: &SyntaxDocument,
    fields: &[EvaluatedField<'_>],
    ambiguities: &mut Vec<Ambiguity>,
) {
    let repository_fields = ["archiveprefix", "eprinttype"]
        .iter()
        .flat_map(|name| fields_named(fields, name))
        .filter_map(|field| {
            field
                .text()
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(|value| (field, value))
        })
        .collect::<Vec<_>>();
    let mut distinct_repositories = Vec::<(&EvaluatedField<'_>, &str)>::new();
    for (field, repository) in repository_fields {
        if !distinct_repositories
            .iter()
            .any(|(_, existing)| existing.eq_ignore_ascii_case(repository))
        {
            distinct_repositories.push((field, repository));
        }
    }
    if distinct_repositories.len() < 2 {
        return;
    }

    let candidates = distinct_repositories
        .iter()
        .map(|(field, repository)| SemanticCandidate {
            value: (*repository).to_string(),
            status: ValueStatus::Explicit,
            confidence: Confidence::High,
            origins: field_origins(document, field, OriginKind::FieldValue),
        })
        .collect::<Vec<_>>();
    let origins = candidates
        .iter()
        .flat_map(|candidate| candidate.origins.clone())
        .collect();
    ambiguities.push(Ambiguity {
        kind: "multiple-preprint-repositories".to_string(),
        message: "archivePrefix and eprintType identify different repositories".to_string(),
        candidates,
        origins,
    });
}

fn retain_identifier_conflicts(
    identifiers: &Identifiers,
    ambiguities: &mut Vec<Ambiguity>,
    conflicts: &mut Vec<SemanticConflict>,
) {
    if identifiers.dois.len() < 2 {
        return;
    }
    let candidates = identifiers
        .dois
        .iter()
        .map(|identifier| SemanticCandidate {
            value: identifier.value.to_string(),
            status: identifier.status,
            confidence: identifier.confidence,
            origins: identifier.origins.clone(),
        })
        .collect::<Vec<_>>();
    let origins = identifiers
        .dois
        .iter()
        .flat_map(|identifier| identifier.origins.clone())
        .collect::<Vec<_>>();
    ambiguities.push(Ambiguity {
        kind: "multiple-doi-identifiers".to_string(),
        message: "multiple distinct DOI identifiers are present".to_string(),
        candidates,
        origins: origins.clone(),
    });
    conflicts.push(SemanticConflict {
        field: "doi".to_string(),
        explicit_values: identifiers
            .dois
            .iter()
            .filter(|identifier| identifier.status != ValueStatus::Inferred)
            .map(|identifier| identifier.value.to_string())
            .collect(),
        inferred_values: identifiers
            .dois
            .iter()
            .filter(|identifier| identifier.status == ValueStatus::Inferred)
            .map(|identifier| identifier.value.to_string())
            .collect(),
        origins,
    });
}

fn field_ambiguities(document: &SyntaxDocument, fields: &[EvaluatedField<'_>]) -> Vec<Ambiguity> {
    let mut by_name: BTreeMap<String, Vec<&EvaluatedField<'_>>> = BTreeMap::new();
    for field in fields {
        by_name
            .entry(field.node.name.text.to_ascii_lowercase())
            .or_default()
            .push(field);
    }
    by_name
        .into_iter()
        .filter(|(_, fields)| fields.len() > 1)
        .filter_map(|(name, fields)| {
            let mut values = fields
                .iter()
                .filter_map(|field| field.text())
                .map(ToOwned::to_owned)
                .collect::<Vec<_>>();
            deduplicate(&mut values);
            (values.len() > 1).then(|| {
                let candidates = fields
                    .iter()
                    .filter_map(|field| {
                        field.text().map(|value| SemanticCandidate {
                            value: value.to_string(),
                            status: ValueStatus::Explicit,
                            confidence: Confidence::High,
                            origins: field_origins(document, field, OriginKind::FieldValue),
                        })
                    })
                    .collect::<Vec<_>>();
                let origins = candidates
                    .iter()
                    .flat_map(|candidate| candidate.origins.clone())
                    .collect();
                Ambiguity {
                    kind: "duplicate-field".to_string(),
                    message: format!("field '{name}' has multiple distinct values"),
                    candidates,
                    origins,
                }
            })
        })
        .collect()
}

fn macro_expansion_ambiguities(
    document: &SyntaxDocument,
    fields: &[EvaluatedField<'_>],
) -> Vec<Ambiguity> {
    fields
        .iter()
        .filter(|field| field.candidates.len() > 1)
        .map(|field| {
            let field_value_origin = field_origin(document, field.node, OriginKind::FieldValue);
            Ambiguity {
                kind: "ambiguous-macro-expansion".to_string(),
                message: format!(
                    "macro expansion for field '{}' has multiple candidates",
                    field.node.name.text
                ),
                candidates: field
                    .candidates
                    .iter()
                    .map(|candidate| SemanticCandidate {
                        value: candidate.value.clone(),
                        status: ValueStatus::Ambiguous,
                        confidence: Confidence::Low,
                        origins: {
                            let mut origins = vec![field_value_origin.clone()];
                            extend_unique_origins(&mut origins, candidate.origins.clone());
                            origins
                        },
                    })
                    .collect(),
                origins: field_origins(document, field, OriginKind::FieldValue),
            }
        })
        .collect()
}

fn unresolved_ambiguities(
    document: &SyntaxDocument,
    fields: &[EvaluatedField<'_>],
) -> Vec<Ambiguity> {
    fields
        .iter()
        .filter(|field| !field.value.unresolved_macros.is_empty())
        .map(|field| {
            let origins = field_origins(document, field, OriginKind::FieldValue);
            Ambiguity {
                kind: "unresolved-value".to_string(),
                message: format!(
                    "field '{}' contains unresolved macro(s): {}",
                    field.node.name.text,
                    field.value.unresolved_macros.join(", ")
                ),
                candidates: vec![SemanticCandidate {
                    value: field.value.raw.clone(),
                    status: ValueStatus::Unresolved,
                    confidence: Confidence::Unknown,
                    origins: origins.clone(),
                }],
                origins,
            }
        })
        .collect()
}

fn field_conflicts(
    document: &SyntaxDocument,
    fields: &[EvaluatedField<'_>],
) -> Vec<SemanticConflict> {
    field_ambiguities(document, fields)
        .into_iter()
        .map(|ambiguity| SemanticConflict {
            field: ambiguity
                .message
                .split('\'')
                .nth(1)
                .unwrap_or("unknown")
                .to_string(),
            explicit_values: ambiguity
                .candidates
                .iter()
                .map(|candidate| candidate.value.clone())
                .collect(),
            inferred_values: Vec::new(),
            origins: ambiguity.origins,
        })
        .collect()
}

fn emit_value_diagnostics(
    document: &SyntaxDocument,
    fields: &[EvaluatedField<'_>],
    diagnostics: &mut Vec<Diagnostic>,
) {
    for field in fields {
        if !field.value.unresolved_macros.is_empty() {
            diagnostics.push(semantic_diagnostic(
                document,
                "BIB-SEMANTIC-101",
                Severity::Warning,
                false,
                format!(
                    "unresolved BibTeX macro(s): {}",
                    field.value.unresolved_macros.join(", ")
                ),
                Some(field.node.value.range),
                diagnostics.len(),
            ));
        }
        if field.value.candidates.len() > 1 {
            diagnostics.push(semantic_diagnostic(
                document,
                "BIB-SEMANTIC-102",
                Severity::Warning,
                false,
                format!(
                    "macro expansion for '{}' is ambiguous",
                    field.node.name.text
                ),
                Some(field.node.value.range),
                diagnostics.len(),
            ));
        }
    }
}

fn semantic_diagnostic(
    document: &SyntaxDocument,
    code: &str,
    severity: Severity,
    blocking: bool,
    message: impl Into<String>,
    range: Option<TextRange>,
    index: usize,
) -> Diagnostic {
    let start = range.map_or(0, |range| range.start);
    Diagnostic {
        id: DiagnosticId::new(format!("semantic:{code}:{start}:{index}")),
        code: RuleCode::new(code),
        severity,
        blocking,
        message: message.into(),
        primary_location: range
            .map(|range| SourceLocation::new(document.source_id().clone(), range)),
        related_locations: Vec::new(),
        notes: Vec::new(),
        fixes: Vec::new(),
    }
}

fn field_origin(document: &SyntaxDocument, field: &FieldNode, kind: OriginKind) -> SyntaxOrigin {
    let range = match kind {
        OriginKind::FieldName => field.name.range,
        OriginKind::FieldValue | OriginKind::Inference => field.value.range,
        _ => field.range,
    };
    SyntaxOrigin::new(document.source_id().clone(), range, kind).for_field(field.name.text.clone())
}

fn field_origins(
    document: &SyntaxDocument,
    field: &EvaluatedField<'_>,
    kind: OriginKind,
) -> Vec<SyntaxOrigin> {
    let mut origins = vec![field_origin(document, field.node, kind)];
    extend_unique_origins(&mut origins, field.resolution_origins.clone());
    origins
}

fn prepend_unique_origin(origins: &mut Vec<SyntaxOrigin>, origin: SyntaxOrigin) {
    if let Some(index) = origins.iter().position(|existing| existing == &origin) {
        origins.remove(index);
    }
    origins.insert(0, origin);
}

fn extend_unique_origins(
    origins: &mut Vec<SyntaxOrigin>,
    additional: impl IntoIterator<Item = SyntaxOrigin>,
) {
    for origin in additional {
        if !origins.contains(&origin) {
            origins.push(origin);
        }
    }
}

fn normalized_sourced<T>(
    document: &SyntaxDocument,
    field: &EvaluatedField<'_>,
    value: T,
) -> Sourced<T> {
    Sourced {
        value,
        origins: field_origins(document, field, OriginKind::FieldValue),
        status: ValueStatus::Normalized,
        confidence: Confidence::High,
    }
}

fn push_unique<T>(values: &mut Vec<Sourced<T>>, candidate: Sourced<T>, key: impl Fn(&T) -> &str) {
    if let Some(existing) = values
        .iter_mut()
        .find(|existing| key(&existing.value).eq_ignore_ascii_case(key(&candidate.value)))
    {
        for origin in candidate.origins {
            if !existing.origins.contains(&origin) {
                existing.origins.push(origin);
            }
        }
        if candidate.confidence < existing.confidence {
            existing.confidence = candidate.confidence;
        }
    } else {
        values.push(candidate);
    }
}

fn work_type_from_entry_type(entry_type: &str) -> WorkType {
    match entry_type.to_ascii_lowercase().as_str() {
        "article" | "periodical" => WorkType::JournalArticle,
        "inproceedings" | "conference" => WorkType::ConferencePaper,
        "book" | "mvbook" | "booklet" | "collection" | "mvcollection" | "proceedings"
        | "mvproceedings" => WorkType::Book,
        "inbook" | "bookinbook" | "suppbook" => WorkType::InBook,
        "incollection" | "suppcollection" | "inreference" => WorkType::InCollection,
        "mastersthesis" | "phdthesis" | "thesis" => WorkType::Thesis,
        "techreport" | "report" => WorkType::TechnicalReport,
        "dataset" => WorkType::Dataset,
        "software" => WorkType::Software,
        "online" => WorkType::WebResource,
        "misc" | "unpublished" | "manual" => WorkType::Miscellaneous,
        _ => WorkType::Unknown,
    }
}

fn parse_publication_date(raw: &str) -> PublicationDate {
    let trimmed = raw.trim();
    let parts = trimmed.split(['-', '/']).collect::<Vec<_>>();
    PublicationDate {
        raw: trimmed.to_string(),
        year: parts.first().and_then(|part| parse_year(part)),
        month: parts.get(1).and_then(|part| parse_month(part)),
        day: parts
            .get(2)
            .and_then(|part| part.parse::<u8>().ok())
            .filter(|day| (1..=31).contains(day)),
    }
}

fn parse_year(raw: &str) -> Option<i32> {
    let raw = raw.trim();
    (raw.len() == 4 && raw.as_bytes().iter().all(u8::is_ascii_digit))
        .then(|| raw.parse::<i32>().ok())
        .flatten()
}

fn parse_day(raw: &str) -> Option<u8> {
    raw.trim()
        .parse::<u8>()
        .ok()
        .filter(|day| (1..=31).contains(day))
}

fn parse_month(raw: &str) -> Option<u8> {
    let normalized = raw.trim().to_ascii_lowercase();
    normalized
        .parse::<u8>()
        .ok()
        .filter(|month| (1..=12).contains(month))
        .or_else(
            || match normalized.get(..3).unwrap_or(normalized.as_str()) {
                "jan" => Some(1),
                "feb" => Some(2),
                "mar" => Some(3),
                "apr" => Some(4),
                "may" => Some(5),
                "jun" => Some(6),
                "jul" => Some(7),
                "aug" => Some(8),
                "sep" => Some(9),
                "oct" => Some(10),
                "nov" => Some(11),
                "dec" => Some(12),
                _ => None,
            },
        )
}

fn month_name(name: &str) -> Option<&'static str> {
    match name {
        "jan" => Some("January"),
        "feb" => Some("February"),
        "mar" => Some("March"),
        "apr" => Some("April"),
        "may" => Some("May"),
        "jun" => Some("June"),
        "jul" => Some("July"),
        "aug" => Some("August"),
        "sep" => Some("September"),
        "oct" => Some("October"),
        "nov" => Some("November"),
        "dec" => Some("December"),
        _ => None,
    }
}

fn normalize_doi(raw: &str) -> Option<String> {
    let mut value = raw.trim().trim_matches(['{', '}', '"']).trim();
    for prefix in [
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ] {
        if value
            .get(..prefix.len())
            .is_some_and(|head| head.eq_ignore_ascii_case(prefix))
        {
            value = &value[prefix.len()..];
            break;
        }
    }
    value = value.trim().trim_end_matches(['.', ',', ';']);
    let (registrant, suffix) = value.split_once('/')?;
    let valid_prefix = registrant.starts_with("10.")
        && registrant[3..].len() >= 4
        && registrant[3..].bytes().all(|byte| byte.is_ascii_digit());
    if valid_prefix && !suffix.trim().is_empty() && !value.chars().any(char::is_whitespace) {
        Some(value.to_ascii_lowercase())
    } else {
        None
    }
}

#[derive(Debug)]
struct ParsedArxiv {
    base: String,
    version: Option<String>,
    full: String,
}

fn parse_arxiv(raw: &str) -> Option<ParsedArxiv> {
    let lower = raw.to_ascii_lowercase();
    let mut value = raw.trim();
    if let Some(index) = lower.find("arxiv.org/abs/") {
        value = &raw[index + "arxiv.org/abs/".len()..];
    } else if let Some(index) = lower.find("arxiv.org/pdf/") {
        value = &raw[index + "arxiv.org/pdf/".len()..];
    } else if let Some(index) = lower.find("arxiv:") {
        value = &raw[index + "arxiv:".len()..];
    }
    value = value
        .trim()
        .trim_matches(['{', '}', '"'])
        .split_whitespace()
        .next()?;
    value = value
        .trim_end_matches(".pdf")
        .trim_end_matches(['.', ',', ';']);
    let (base, version) = split_arxiv_version(value);
    if !valid_arxiv_base(base) {
        return None;
    }
    let version = version.map(ToOwned::to_owned);
    let full = version
        .as_ref()
        .map_or_else(|| base.to_string(), |version| format!("{base}{version}"));
    Some(ParsedArxiv {
        base: base.to_string(),
        version,
        full,
    })
}

fn split_arxiv_version(value: &str) -> (&str, Option<&str>) {
    if let Some(index) = value.rfind(['v', 'V']) {
        let tail = &value[index + 1..];
        if !tail.is_empty() && tail.bytes().all(|byte| byte.is_ascii_digit()) {
            return (&value[..index], Some(&value[index..]));
        }
    }
    (value, None)
}

fn valid_arxiv_base(value: &str) -> bool {
    if let Some((left, right)) = value.split_once('.') {
        if left.len() == 4
            && left.bytes().all(|byte| byte.is_ascii_digit())
            && matches!(right.len(), 4 | 5)
            && right.bytes().all(|byte| byte.is_ascii_digit())
        {
            return true;
        }
    }
    if let Some((category, number)) = value.rsplit_once('/') {
        return !category.is_empty()
            && category
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-'))
            && number.len() == 7
            && number.bytes().all(|byte| byte.is_ascii_digit());
    }
    false
}

fn contains_arxiv(value: &str) -> bool {
    value.to_ascii_lowercase().contains("arxiv")
}

fn venue_matches_repository(value: &str, repository: &Repository) -> bool {
    match repository {
        Repository::ArXiv => contains_arxiv(value),
        Repository::Other(name) => contains_repository_name(value, name),
    }
}

fn contains_repository_name(value: &str, repository_name: &str) -> bool {
    let value = value.to_ascii_lowercase();
    let repository_name = repository_name.trim().to_ascii_lowercase();
    if repository_name.is_empty() {
        return false;
    }
    value
        .match_indices(&repository_name)
        .any(|(start, matched)| {
            let end = start + matched.len();
            let starts_at_boundary = value[..start]
                .chars()
                .next_back()
                .is_none_or(|character| !character.is_alphanumeric());
            let ends_at_boundary = value[end..]
                .chars()
                .next()
                .is_none_or(|character| !character.is_alphanumeric());
            starts_at_boundary && ends_at_boundary
        })
}

fn normalize_isbn(value: &str) -> String {
    value
        .chars()
        .filter(|character| character.is_ascii_digit() || matches!(character, 'x' | 'X'))
        .map(|character| character.to_ascii_uppercase())
        .collect()
}

fn normalize_issn(value: &str) -> String {
    let compact = normalize_isbn(value);
    if compact.len() == 8 {
        format!("{}-{}", &compact[..4], &compact[4..])
    } else {
        compact
    }
}

fn deduplicate(values: &mut Vec<String>) {
    let mut seen = BTreeSet::new();
    values.retain(|value| seen.insert(value.clone()));
}
