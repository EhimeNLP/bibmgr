use bibmgr_model::TextRange;
use bibmgr_syntax::{
    parse, parse_tolerant, CommentKind, EntryDelimiter, ParseMode, ParseOptions, ParseStatus,
    ValueAtomKind,
};
use proptest::prelude::*;
use std::fmt::Write as _;

#[test]
fn representative_documents_round_trip_byte_for_byte() {
    let fixtures = [
        "",
        "\n@article{k, title={T}}\n",
        "\r\n% comment\r\n@BOOK(Key,\r\n\tTITLE = \"Unicode 文献\",\r\n)\r\n",
        "@string{J = \"Journal\"}\n@article{k, title={A} # \" B\", journal=J}",
        "@article{k, title={first}, TITLE=\"second\",}\n",
        "prefix text\n@comment{kept {verbatim}}\nsuffix text",
        "@preamble{\"prefix \" # macro}\n@unknown{x, Weird_Field=123}",
        "@article{broken, title={not closed\n@book{next,title={Recovered}}",
        "@article{k, title=\"not closed}",
        "@article{k, title={deep {{{{{value}}}}}}}",
    ];
    for source in fixtures {
        for mode in [ParseMode::Strict, ParseMode::Tolerant] {
            let document = parse(
                source,
                ParseOptions {
                    mode,
                    ..ParseOptions::default()
                },
            );
            assert_eq!(document.to_source().as_bytes(), source.as_bytes());
            let rebuilt = document
                .blocks()
                .iter()
                .filter_map(|block| document.block_source(block))
                .collect::<String>();
            assert_eq!(rebuilt.as_bytes(), source.as_bytes());
        }
    }
}

#[test]
fn unicode_entries_are_parsed_with_original_byte_ranges() {
    let source = "% 日本語のコメント\n@inproceedings{yamada-解析,\n  author = {山田, 太郎},\n  title = {構文解析の研究},\n  booktitle = {ACL},\n  year = {2026},\n}\n";

    for mode in [ParseMode::Strict, ParseMode::Tolerant] {
        let document = parse(
            source,
            ParseOptions {
                mode,
                ..ParseOptions::default()
            },
        );
        assert_eq!(document.summary().status, ParseStatus::Ok);
        assert_eq!(document.entries().len(), 1);
        let entry = &document.entries()[0];
        assert_eq!(entry.citation_key.text, "yamada-解析");
        assert_eq!(
            document.slice(entry.field("title").unwrap().value.atoms[0].content_range),
            Some("構文解析の研究")
        );
        assert_eq!(document.to_source(), source);
    }
}

#[test]
fn fields_keep_order_case_duplicates_delimiters_and_concatenation() {
    let source = "@ArTiClE(Key, TITLE={One}, title=\"Two\" # suffix, year=2026,)";
    let document = parse_tolerant(source);
    let entry = &document.entries()[0];
    assert_eq!(entry.entry_type.text, "ArTiClE");
    assert_eq!(entry.citation_key.text, "Key");
    assert_eq!(entry.delimiter, EntryDelimiter::Parentheses);
    assert_eq!(entry.fields.len(), 3);
    assert_eq!(entry.fields[0].name.text, "TITLE");
    assert_eq!(entry.fields[1].name.text, "title");
    assert_eq!(entry.fields_named("title").count(), 2);
    assert!(entry.trailing_comma);
    assert_eq!(entry.fields[1].value.concatenation_ranges.len(), 1);
    assert!(matches!(
        entry.fields[1].value.atoms[0].kind,
        ValueAtomKind::Quoted { closed: true }
    ));
    assert_eq!(entry.fields[1].value.atoms[1].kind, ValueAtomKind::Macro);
    assert_eq!(
        document.slice(entry.fields[0].value.atoms[0].content_range),
        Some("One")
    );
}

#[test]
fn malformed_input_is_retained_and_diagnosed_without_panicking() {
    let source = "@article{a, title={oops\n@book{b, title={ok}}";
    let strict = parse(source, ParseOptions::strict());
    let tolerant = parse(source, ParseOptions::tolerant());
    assert_eq!(strict.to_source(), source);
    assert_eq!(tolerant.to_source(), source);
    assert_ne!(strict.summary().status, ParseStatus::Ok);
    assert!(!strict.diagnostics().is_empty());
    assert!(!tolerant.diagnostics().is_empty());
    assert!(tolerant
        .entries()
        .iter()
        .any(|entry| entry.citation_key.text == "b"));
}

#[test]
fn source_slice_checks_utf8_boundaries() {
    let document = parse_tolerant("文献");
    assert_eq!(document.slice(TextRange::new(0, 3)), Some("文"));
    assert_eq!(document.slice(TextRange::new(1, 3)), None);
    assert_eq!(document.slice(TextRange::new(3, 0)), None);
    assert_eq!(document.line_column(0).unwrap().line, 1);
    assert_eq!(document.line_column(3).unwrap().column, 2);
    assert!(document.line_column(1).is_none());
}

#[test]
fn percent_and_explicit_comments_are_distinct_and_interstitial_text_is_retained() {
    let source = "leading\n% line comment\n@comment{explicit {body}}\ntrailing";
    let document = parse_tolerant(source);
    assert_eq!(document.to_source(), source);
    assert!(document
        .comments()
        .iter()
        .any(|comment| comment.kind == CommentKind::Percent));
    assert!(document
        .comments()
        .iter()
        .any(|comment| comment.kind == CommentKind::Explicit));
    assert!(!document.text_blocks().is_empty());
    for comment in document.comments() {
        assert!(document.slice(comment.range).is_some());
        assert!(document.slice(comment.content_range).is_some());
    }
    let rebuilt = document
        .blocks()
        .iter()
        .filter_map(|block| document.block_source(block))
        .collect::<String>();
    assert_eq!(rebuilt, source);
}

#[test]
fn inline_percent_comment_recovers_following_fields_with_original_ranges() {
    let source = "@article{k,\r\n  year={2026}, % 年の注釈\r\n  title={Recovered},\r\n  author={Doe, Jane},\r\n}\r\n";

    for mode in [ParseMode::Strict, ParseMode::Tolerant] {
        let document = parse(
            source,
            ParseOptions {
                mode,
                ..ParseOptions::default()
            },
        );
        assert_eq!(document.to_source(), source);
        assert_eq!(document.entries().len(), 1);

        let entry = &document.entries()[0];
        assert_eq!(entry.status, bibmgr_syntax::EntryStatus::Recovered);
        assert_eq!(
            entry
                .fields
                .iter()
                .map(|field| field.name.text.as_str())
                .collect::<Vec<_>>(),
            ["year", "title", "author"]
        );
        assert_eq!(entry.inline_comments.len(), 1);
        let comment = &entry.inline_comments[0];
        assert_eq!(comment.kind, CommentKind::Percent);
        assert_eq!(document.slice(comment.range), Some("% 年の注釈"));
        assert_eq!(document.slice(comment.content_range), Some(" 年の注釈"));
        assert!(entry.fields[0].range.end <= comment.range.start);
        assert!(comment.range.end <= entry.fields[1].name.range.start);

        let diagnostic = document
            .diagnostics()
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == "BIB-SYNTAX-104")
            .expect("the untouched parser view still diagnoses the comment");
        assert_eq!(
            document.slice(diagnostic.primary_location.as_ref().unwrap().range),
            Some("%")
        );
        assert_eq!(document.summary().status, ParseStatus::Partial);

        let rebuilt = document
            .blocks()
            .iter()
            .filter_map(|block| document.block_source(block))
            .collect::<String>();
        assert_eq!(rebuilt.as_bytes(), source.as_bytes());
    }
}

#[test]
fn percent_signs_in_values_are_not_reclassified_as_inline_comments() {
    let source = "@misc(k,\n  title={100% ready},\n  note=\"50% done\",\n  year={2026}, % actual comment\n  author={Doe, Jane},\n)\n@comment{literal % body}\n";
    let document = parse_tolerant(source);
    let entry = &document.entries()[0];

    assert_eq!(
        entry
            .fields
            .iter()
            .map(|field| field.name.text.as_str())
            .collect::<Vec<_>>(),
        ["title", "note", "year", "author"]
    );
    assert_eq!(entry.inline_comments.len(), 1);
    assert_eq!(
        document.slice(entry.inline_comments[0].range),
        Some("% actual comment")
    );
    assert_eq!(document.to_source(), source);
}

#[test]
fn syntax_dtos_are_serializable_without_backend_types() {
    let document = parse_tolerant("@article{k,title={T}}");
    let json = serde_json::to_string(&document).expect("serialize syntax document");
    let restored: bibmgr_syntax::SyntaxDocument =
        serde_json::from_str(&json).expect("deserialize syntax document");
    assert_eq!(restored.to_source(), document.to_source());
    assert_eq!(restored.entries(), document.entries());
}

#[test]
fn deep_long_and_many_entry_inputs_remain_lossless() {
    let deep = format!(
        "@article{{deep,title={{{}{}}}}}",
        "{".repeat(4_096),
        "}".repeat(4_096)
    );
    let deep_document = parse_tolerant(&deep);
    assert_eq!(deep_document.to_source(), deep);
    assert_eq!(deep_document.entries().len(), 1);

    let long_value = "x".repeat(256 * 1_024);
    let long = format!("@article{{long,title={{{long_value}}}}}");
    let long_document = parse_tolerant(&long);
    assert_eq!(long_document.to_source(), long);
    assert_eq!(long_document.entries()[0].fields.len(), 1);

    let mut many = String::new();
    for index in 0..1_000 {
        writeln!(many, "@misc{{k{index},title={{T{index}}}}}").expect("write to String");
    }
    let many_document = parse_tolerant(&many);
    assert_eq!(many_document.to_source(), many);
    assert_eq!(many_document.entries().len(), 1_000);
}

proptest! {
    #[test]
    fn arbitrary_utf8_never_panics_and_round_trips(source in any::<String>(), tolerant in any::<bool>()) {
        let options = ParseOptions {
            mode: if tolerant { ParseMode::Tolerant } else { ParseMode::Strict },
            ..ParseOptions::default()
        };
        let document = parse(&source, options);
        prop_assert_eq!(document.to_source().as_bytes(), source.as_bytes());
        let rebuilt = document.blocks().iter()
            .filter_map(|block| document.block_source(block))
            .collect::<String>();
        prop_assert_eq!(rebuilt.as_bytes(), source.as_bytes());
    }

    #[test]
    fn generated_valid_entries_keep_all_fields(
        field_names in prop::collection::vec("[A-Za-z][A-Za-z0-9_]{0,12}", 0..30),
        values in prop::collection::vec("[A-Za-z0-9 ]{0,30}", 0..30),
    ) {
        let count = field_names.len().min(values.len());
        let fields = field_names.iter().zip(values.iter()).take(count)
            .map(|(name, value)| format!("{name}={{{value}}}"))
            .collect::<Vec<_>>()
            .join(",");
        let source = format!("@custom{{key,{fields}}}");
        let document = parse_tolerant(&source);
        prop_assert_eq!(document.to_source(), source.as_str());
        prop_assert_eq!(document.entries().len(), 1);
        prop_assert_eq!(document.entries()[0].fields.len(), count);
    }

    #[test]
    fn arbitrary_utf8_inline_comments_recover_the_next_field(comment in any::<String>()) {
        let comment = comment.replace(['\r', '\n'], " ");
        let source = format!(
            "@misc{{鍵,\n  year={{2026}}, % {comment}\n  title={{後続フィールド}},\n}}\n"
        );
        let document = parse_tolerant(&source);

        prop_assert_eq!(document.to_source().as_bytes(), source.as_bytes());
        prop_assert_eq!(document.entries().len(), 1);
        let entry = &document.entries()[0];
        prop_assert_eq!(
            entry.fields.iter().map(|field| field.name.text.as_str()).collect::<Vec<_>>(),
            ["year", "title"]
        );
        prop_assert_eq!(entry.inline_comments.len(), 1);
        prop_assert!(document.slice(entry.inline_comments[0].range).is_some());
        prop_assert!(document.slice(entry.inline_comments[0].content_range).is_some());

        let rebuilt = document.blocks().iter()
            .filter_map(|block| document.block_source(block))
            .collect::<String>();
        prop_assert_eq!(rebuilt.as_bytes(), source.as_bytes());
    }
}
