use bibmgr_semantics::{
    analyze, parse_people, Confidence, OriginKind, Repository, SyntaxOrigin, ValueStatus, WorkType,
};
use bibmgr_syntax::{parse_tolerant, ParseOptions};
use proptest::prelude::*;
use std::fmt::Write as _;

fn one(source: &str) -> bibmgr_semantics::BibliographicRecord {
    let document = parse_tolerant(source);
    analyze(&document).records.remove(0)
}

fn origin_text<'a>(source: &'a str, origin: &SyntaxOrigin) -> &'a str {
    &source[origin.range.start as usize..origin.range.end as usize]
}

#[test]
fn all_supported_arxiv_spellings_produce_the_same_identity() {
    let sources = [
        "@misc{k,eprint={1706.03762},archivePrefix={arXiv}}",
        "@misc{k,howpublished={arXiv:1706.03762}}",
        "@article{k,journal={arXiv:1706.03762}}",
        "@online{k,url={https://arxiv.org/abs/1706.03762}}",
    ];
    for source in sources {
        let record = one(source);
        let preprint = record.preprint.expect("preprint recognized");
        assert_eq!(preprint.value.repository, Repository::ArXiv);
        assert_eq!(preprint.value.identifier, "1706.03762");
        assert_eq!(
            record.identifiers.primary_arxiv().unwrap().value.as_str(),
            "1706.03762"
        );
        assert_eq!(record.work_type.value, WorkType::Preprint);
        assert!(!preprint.origins.is_empty());
    }
}

#[test]
fn explicit_non_arxiv_repositories_produce_preprints() {
    let sources = [
        (
            "@misc{k,eprint={10.1101/2025.01.02.123456},archivePrefix={bioRxiv}}",
            "bioRxiv",
            "10.1101/2025.01.02.123456",
            "archivePrefix",
        ),
        (
            "@online{k,eprint={1234567},eprintType={Zenodo}}",
            "Zenodo",
            "1234567",
            "eprintType",
        ),
    ];

    for (source, repository, identifier, repository_field) in sources {
        let record = one(source);
        let preprint = record.preprint.expect("preprint recognized");
        assert_eq!(
            preprint.value.repository,
            Repository::Other(repository.to_string())
        );
        assert_eq!(preprint.value.identifier, identifier);
        assert_eq!(preprint.status, ValueStatus::Parsed);
        assert_eq!(preprint.confidence, Confidence::High);
        assert_eq!(record.work_type.value, WorkType::Preprint);
        assert!(record.identifiers.arxiv.is_empty());
        assert!(preprint
            .origins
            .iter()
            .any(|origin| origin.field_name.as_deref() == Some("eprint")));
        assert!(preprint
            .origins
            .iter()
            .any(|origin| origin.field_name.as_deref() == Some(repository_field)));
    }
}

#[test]
fn explicit_non_arxiv_repository_takes_priority_over_arxiv_shaped_eprint() {
    let record = one("@misc{k,eprint={2401.12345},archivePrefix={bioRxiv}}");
    let preprint = record.preprint.expect("preprint recognized");
    assert_eq!(
        preprint.value.repository,
        Repository::Other("bioRxiv".to_string())
    );
    assert_eq!(preprint.value.identifier, "2401.12345");
    assert!(record.identifiers.arxiv.is_empty());
}

#[test]
fn article_venue_matching_an_explicit_repository_is_inferred_as_preprint() {
    let record = one(
        "@article{k,journal={bioRxiv: preprint},eprint={10.1101/123456},archivePrefix={bioRxiv}}",
    );
    assert_eq!(record.work_type.value, WorkType::Preprint);
    assert!(record
        .conflicts
        .iter()
        .any(|conflict| conflict.field == "work_type"));
}

#[test]
fn published_article_can_retain_a_non_arxiv_preprint_without_becoming_preprint() {
    let record = one(
        "@article{k,journal={Journal of Tests},doi={10.1000/published},eprint={10.1101/123456},archivePrefix={bioRxiv}}",
    );
    assert_eq!(record.work_type.value, WorkType::JournalArticle);
    assert_eq!(
        record.preprint.unwrap().value.repository,
        Repository::Other("bioRxiv".to_string())
    );
}

#[test]
fn conflicting_explicit_repository_fields_remain_ambiguous() {
    let record =
        one("@misc{k,eprint={10.1101/123456},archivePrefix={bioRxiv},eprintType={medRxiv}}");
    let preprint = record.preprint.expect("preprint recognized");
    assert_eq!(
        preprint.value.repository,
        Repository::Other("bioRxiv".to_string())
    );
    let ambiguity = record
        .ambiguities
        .iter()
        .find(|ambiguity| ambiguity.kind == "multiple-preprint-repositories")
        .expect("repository ambiguity retained");
    assert_eq!(
        ambiguity
            .candidates
            .iter()
            .map(|candidate| candidate.value.as_str())
            .collect::<Vec<_>>(),
        ["bioRxiv", "medRxiv"]
    );
    assert_eq!(ambiguity.origins.len(), 2);
    assert!(ambiguity
        .origins
        .iter()
        .all(|origin| !origin.range.is_empty()));
}

#[test]
fn published_article_can_retain_a_related_preprint_without_becoming_preprint() {
    let record = one(
        "@article{k,journal={Journal of Tests},doi={https://doi.org/10.1000/ABC},eprint={1706.03762},archivePrefix={arXiv}}",
    );
    assert_eq!(record.work_type.value, WorkType::JournalArticle);
    assert!(record.preprint.is_some());
    assert_eq!(
        record.identifiers.primary_doi().unwrap().value.as_str(),
        "10.1000/abc"
    );
}

#[test]
fn macros_concatenation_and_months_resolve_recursively() {
    let source = r#"
@string{base = "Journal"}
@string{venue = base # " of Testing"}
@article{k, title={A } # venue, journal=venue, month=jan, year=2026}
"#;
    let record = one(source);
    assert_eq!(record.title.unwrap().value.as_str(), "A Journal of Testing");
    assert_eq!(record.venue.unwrap().value.raw, "Journal of Testing");
    assert_eq!(record.date.unwrap().value.month, Some(1));
}

#[test]
fn canonical_semantic_rule_codes_cover_macros_and_concatenation() {
    struct Case {
        name: &'static str,
        source: &'static str,
        invalid_code: Option<&'static str>,
    }

    let cases = [
        Case {
            name: "DOI valid macro",
            source: "@string{value={10.1000/macro}}\n@article{k,doi=value}",
            invalid_code: None,
        },
        Case {
            name: "DOI invalid macro",
            source: "@string{value={not-a-doi}}\n@article{k,doi=value}",
            invalid_code: Some("BIB-SEMANTIC-001"),
        },
        Case {
            name: "DOI valid concatenation",
            source: "@article{k,doi={10.1000/} # {concatenated}}",
            invalid_code: None,
        },
        Case {
            name: "DOI invalid concatenation",
            source: "@article{k,doi={10.1000} # {concatenated}}",
            invalid_code: Some("BIB-SEMANTIC-001"),
        },
        Case {
            name: "arXiv valid macro",
            source: "@string{value={1706.03762}}\n@misc{k,arxiv=value}",
            invalid_code: None,
        },
        Case {
            name: "arXiv invalid macro",
            source: "@string{value={not-an-arxiv-id}}\n@misc{k,arxiv=value}",
            invalid_code: Some("BIB-SEMANTIC-002"),
        },
        Case {
            name: "arXiv valid concatenation",
            source: "@misc{k,arxiv={1706.} # {03762}}",
            invalid_code: None,
        },
        Case {
            name: "arXiv invalid concatenation",
            source: "@misc{k,arxiv={1706.} # {invalid}}",
            invalid_code: Some("BIB-SEMANTIC-002"),
        },
        Case {
            name: "date/year valid macro",
            source: "@string{value={2024}}\n@article{k,date={2024-01},year=value}",
            invalid_code: None,
        },
        Case {
            name: "date/year invalid macro",
            source: "@string{value={2025}}\n@article{k,date={2024-01},year=value}",
            invalid_code: Some("BIB-SEMANTIC-007"),
        },
        Case {
            name: "date/year valid concatenation",
            source: "@article{k,date={2024-} # {01},year={202} # {4}}",
            invalid_code: None,
        },
        Case {
            name: "date/year invalid concatenation",
            source: "@article{k,date={2024-} # {01},year={202} # {5}}",
            invalid_code: Some("BIB-SEMANTIC-007"),
        },
    ];
    let canonical_codes = ["BIB-SEMANTIC-001", "BIB-SEMANTIC-002", "BIB-SEMANTIC-007"];
    let retired_codes = ["BIB-SEMANTIC-103", "BIB-SEMANTIC-104", "BIB-SEMANTIC-105"];

    for case in cases {
        let bibliography = analyze(&parse_tolerant(case.source));
        for code in canonical_codes {
            let count = bibliography
                .diagnostics
                .iter()
                .filter(|diagnostic| diagnostic.code.as_str() == code)
                .count();
            let expected = usize::from(case.invalid_code == Some(code));
            assert_eq!(
                count, expected,
                "{}: unexpected count for {code}",
                case.name
            );
        }
        for code in retired_codes {
            assert_eq!(
                bibliography
                    .diagnostics
                    .iter()
                    .filter(|diagnostic| diagnostic.code.as_str() == code)
                    .count(),
                0,
                "{}: retired diagnostic {code} reappeared",
                case.name
            );
        }
    }
}

#[test]
fn nested_and_ambiguous_macro_origins_are_precise_and_candidate_specific() {
    let source = "@string{base={One}}\n@string{base={Two}}\n@string{outer=base # {-X}}\n@article{k,title=outer}";
    let document = parse_tolerant(source);
    let bibliography = analyze(&document);
    let record = &bibliography.records[0];
    let title = record.title.as_ref().expect("resolved title");
    assert_eq!(title.value.as_str(), "Two-X");

    let title_origins = title
        .origins
        .iter()
        .map(|origin| {
            (
                origin.kind,
                origin.field_name.as_deref(),
                origin_text(source, origin),
            )
        })
        .collect::<Vec<_>>();
    assert_eq!(
        title_origins,
        [
            (OriginKind::FieldValue, Some("title"), "outer"),
            (OriginKind::MacroReference, Some("title"), "outer"),
            (
                OriginKind::StringDefinition,
                Some("outer"),
                "@string{outer=base # {-X}}",
            ),
            (OriginKind::MacroReference, Some("outer"), "base"),
            (
                OriginKind::StringDefinition,
                Some("base"),
                "@string{base={One}}",
            ),
            (
                OriginKind::StringDefinition,
                Some("base"),
                "@string{base={Two}}",
            ),
        ]
    );

    let ambiguity = record
        .ambiguities
        .iter()
        .find(|ambiguity| ambiguity.kind == "ambiguous-macro-expansion")
        .expect("macro ambiguity");
    let one = ambiguity
        .candidates
        .iter()
        .find(|candidate| candidate.value == "One-X")
        .expect("first definition candidate");
    let two = ambiguity
        .candidates
        .iter()
        .find(|candidate| candidate.value == "Two-X")
        .expect("second definition candidate");
    let one_definitions = one
        .origins
        .iter()
        .filter(|origin| origin.kind == OriginKind::StringDefinition)
        .map(|origin| origin_text(source, origin))
        .collect::<Vec<_>>();
    let two_definitions = two
        .origins
        .iter()
        .filter(|origin| origin.kind == OriginKind::StringDefinition)
        .map(|origin| origin_text(source, origin))
        .collect::<Vec<_>>();
    assert_eq!(
        one_definitions,
        ["@string{outer=base # {-X}}", "@string{base={One}}"]
    );
    assert_eq!(
        two_definitions,
        ["@string{outer=base # {-X}}", "@string{base={Two}}"]
    );
    assert!(one.origins.iter().any(|origin| {
        origin.kind == OriginKind::MacroReference && origin_text(source, origin) == "base"
    }));
    assert!(two.origins.iter().any(|origin| {
        origin.kind == OriginKind::MacroReference && origin_text(source, origin) == "base"
    }));
}

#[test]
fn publication_date_origins_include_every_contributing_field_and_macro_chain() {
    let source = "@string{pubyear={2025}}\n@string{pubmonth=jan}\n@article{k,date={forthcoming},year=pubyear,month=pubmonth,day={21}}";
    let document = parse_tolerant(source);
    let bibliography = analyze(&document);
    let date = bibliography.records[0]
        .date
        .as_ref()
        .expect("publication date");
    assert_eq!(date.value.year, Some(2025));
    assert_eq!(date.value.month, Some(1));
    assert_eq!(date.value.day, Some(21));
    assert_eq!(date.status, ValueStatus::Resolved);

    let field_values = date
        .origins
        .iter()
        .filter(|origin| origin.kind == OriginKind::FieldValue)
        .map(|origin| (origin.field_name.as_deref(), origin_text(source, origin)))
        .collect::<Vec<_>>();
    assert_eq!(
        field_values,
        [
            (Some("date"), "{forthcoming}"),
            (Some("year"), "pubyear"),
            (Some("month"), "pubmonth"),
            (Some("day"), "{21}"),
        ]
    );
    let definitions = date
        .origins
        .iter()
        .filter(|origin| origin.kind == OriginKind::StringDefinition)
        .map(|origin| origin_text(source, origin))
        .collect::<Vec<_>>();
    assert_eq!(
        definitions,
        ["@string{pubyear={2025}}", "@string{pubmonth=jan}"]
    );
}

#[test]
fn unresolved_macro_is_not_silently_treated_as_literal() {
    let document = parse_tolerant("@article{k,title=missing_macro}");
    let bibliography = analyze(&document);
    assert!(bibliography.records[0].title.is_none());
    assert_eq!(bibliography.records[0].unresolved_values.len(), 1);
    assert_eq!(
        bibliography.records[0].unresolved_values[0]
            .value
            .unresolved_macros,
        ["missing_macro"]
    );
    assert!(bibliography.records[0]
        .ambiguities
        .iter()
        .any(|ambiguity| ambiguity.kind == "unresolved-value"));
    assert!(bibliography
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code.as_str() == "BIB-SEMANTIC-101"));
    assert_eq!(
        bibliography.diagnostics[0]
            .primary_location
            .as_ref()
            .unwrap()
            .range,
        document.entries()[0].fields[0].value.range
    );
}

#[test]
fn duplicate_conflicting_fields_are_retained_as_ambiguity_and_conflict() {
    let record = one("@article{k,title={First},TITLE={Second},year={2024},year={2025}}");
    assert_eq!(record.title.unwrap().value.as_str(), "First");
    assert!(record
        .ambiguities
        .iter()
        .any(|item| item.message.contains("title")));
    assert!(record.conflicts.iter().any(|item| item.field == "title"));
    assert!(record.conflicts.iter().any(|item| item.field == "year"));
}

#[test]
fn conflicting_explicit_and_inferred_identifiers_are_all_retained() {
    let record = one(
        "@article{k,doi={10.1000/explicit},url={https://doi.org/10.1000/inferred},journal={Journal}}",
    );
    assert_eq!(record.identifiers.dois.len(), 2);
    assert!(record
        .ambiguities
        .iter()
        .any(|ambiguity| ambiguity.kind == "multiple-doi-identifiers"));
    let conflict = record
        .conflicts
        .iter()
        .find(|conflict| conflict.field == "doi")
        .unwrap();
    assert_eq!(conflict.explicit_values, ["10.1000/explicit"]);
    assert_eq!(conflict.inferred_values, ["10.1000/inferred"]);
}

#[test]
fn people_dates_identifiers_urls_and_provenance_are_structured() {
    let record = one(r"@inproceedings{k,
 author = {Doe, Jr., Jane and {The Unicode Consortium} and Ludwig van Beethoven},
 title = {A Study},
 booktitle = {Proceedings of Testing},
 date = {2025-07-21},
 doi = {doi:10.5555/XYZ},
 url = {https://example.org/paper}
}");
    assert_eq!(record.work_type.value, WorkType::ConferencePaper);
    assert_eq!(record.authors.len(), 3);
    assert_eq!(record.authors[0].value.family, ["Doe"]);
    assert_eq!(record.authors[0].value.suffix, ["Jr."]);
    assert_eq!(
        record.authors[1].value.literal.as_deref(),
        Some("The Unicode Consortium")
    );
    assert_eq!(record.authors[2].value.prefix, ["van"]);
    assert_eq!(record.date.unwrap().value.day, Some(21));
    assert_eq!(record.urls[0].value.as_str(), "https://example.org/paper");
    assert!(record
        .origins
        .iter()
        .any(|origin| origin.kind == OriginKind::Entry));
    assert!(!record.title.unwrap().origins[0].range.is_empty());
}

#[test]
fn date_conflicts_and_macro_definition_conflicts_remain_visible() {
    let document = parse_tolerant(
        "@string{x={One}}\n@string{x={Two}}\n@article{k,title=x,date={2024-01},year={2025}}",
    );
    let bibliography = analyze(&document);
    let record = &bibliography.records[0];
    assert!(record
        .conflicts
        .iter()
        .any(|conflict| conflict.field == "date/year"));
    let title = record.title.as_ref().unwrap();
    assert_eq!(title.value.as_str(), "Two");
    assert_eq!(title.status, ValueStatus::Resolved);
    assert_eq!(title.confidence, Confidence::High);
    assert!(bibliography
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code.as_str() == "BIB-SEMANTIC-102"));
    let macro_ambiguity = record
        .ambiguities
        .iter()
        .find(|ambiguity| ambiguity.kind == "ambiguous-macro-expansion")
        .unwrap();
    assert_eq!(
        macro_ambiguity
            .candidates
            .iter()
            .map(|candidate| candidate.value.as_str())
            .collect::<Vec<_>>(),
        ["One", "Two"]
    );
    assert!(!macro_ambiguity.origins[0].range.is_empty());
}

#[test]
fn person_parser_supports_common_bibtex_forms() {
    let people = parse_people("Jean de La Fontaine and von Neumann, John and Smith, Jr., Jane");
    assert_eq!(people.len(), 3);
    assert_eq!(people[1].family, ["Neumann"]);
    assert_eq!(people[1].prefix, ["von"]);
    assert_eq!(people[2].given, ["Jane"]);
    assert_eq!(people[2].suffix, ["Jr."]);
}

#[test]
fn semantic_dtos_serialize_without_syntax_or_parser_types() {
    let bibliography = analyze(&parse_tolerant("@book{k,title={T},year=2026}"));
    let json = serde_json::to_string(&bibliography).expect("serialize bibliography");
    let restored: bibmgr_semantics::Bibliography =
        serde_json::from_str(&json).expect("deserialize bibliography");
    assert_eq!(restored, bibliography);
}

#[test]
fn original_entry_kind_survives_coarser_work_type_mapping() {
    let masters = one("@mastersthesis{k,title={T},school={S},year={2024}}");
    assert_eq!(masters.work_type.value, WorkType::Thesis);
    assert_eq!(masters.entry_type.value, "mastersthesis");
    assert_eq!(masters.entry_type.origins[0].kind, OriginKind::EntryType);

    let proceedings = one("@proceedings{k,title={T},year={2024}}");
    assert_eq!(proceedings.work_type.value, WorkType::Book);
    assert_eq!(proceedings.entry_type.value, "proceedings");
}

#[test]
fn very_deep_macro_chains_become_unresolved_instead_of_overflowing_the_stack() {
    let mut source = String::new();
    for index in 0..1_000 {
        let next = index + 1;
        writeln!(source, "@string{{m{index}=m{next}}}").expect("write to String");
    }
    source.push_str("@article{k,title=m0}");
    let bibliography = analyze(&parse_tolerant(&source));
    let record = &bibliography.records[0];
    assert_eq!(record.unresolved_values.len(), 1);
    assert!(record.unresolved_values[0].value.unresolved_macros[0]
        .contains("macro expansion depth exceeded"));
}

proptest! {
    #[test]
    fn semantic_analysis_never_panics_for_arbitrary_utf8(source in any::<String>()) {
        let document = bibmgr_syntax::parse(&source, ParseOptions::tolerant());
        let bibliography = analyze(&document);
        prop_assert!(bibliography.records.len() <= document.entries().len());
    }
}
