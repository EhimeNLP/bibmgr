use bibmgr_search::{SearchDocument, SearchIndex, SearchMode, SearchRequest};

fn document(id: &str, title: &str) -> SearchDocument {
    SearchDocument {
        id: id.into(),
        title: title.into(),
        ..SearchDocument::default()
    }
}

fn request(query: &str) -> SearchRequest {
    SearchRequest {
        query: query.into(),
        limit: 10,
        ..SearchRequest::default()
    }
}

#[test]
fn corrects_the_full_query_before_counting_sorting_and_pagination() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            (0..35)
                .map(|i| SearchDocument {
                    year: Some(2024),
                    updated_at: i,
                    ..document(&format!("{i:02}"), "Machine learning")
                })
                .collect(),
            &[],
        )
        .unwrap();
    let mut search = request("Machne learning");
    search.year = Some(2024);
    search.sort = "updated_desc".into();
    search.limit = 2;
    search.offset = 25;
    let page = index.search(&search).unwrap();
    assert_eq!(page.ids, ["09", "08"]);
    assert_eq!(page.total, 35);
    let correction = page.correction.unwrap();
    assert_eq!(correction.original_query, "Machne learning");
    assert_eq!(correction.corrected_query, "Machine learning");
    search.offset = 100;
    let page = index.search(&search).unwrap();
    assert_eq!(page.ids, [] as [String; 0]);
    assert_eq!(page.total, 35);
    assert!(page.correction.is_some());
    search.year = Some(2020);
    let page = index.search(&search).unwrap();
    assert_eq!(page.total, 0);
    assert!(page.correction.is_none());
}

#[test]
fn original_mode_disables_correction_fuzzy_prefix_and_reading_expansion() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![
                document("en", "Machine learning"),
                document("ja", "自然言語処理"),
            ],
            &[],
        )
        .unwrap();
    for query in [
        "machne learning",
        "mach learning",
        "しぜんげごしょり",
        "しぜんげんごしょり",
    ] {
        assert_eq!(index.search(&request(query)).unwrap().total, 1, "{query}");
        let mut search = request(query);
        search.search_mode = SearchMode::Original;
        let page = index.search(&search).unwrap();
        assert_eq!(page.total, 0, "{query}");
        assert!(page.correction.is_none());
    }
    index
        .apply(vec![document("literal", "machne learning")], &[])
        .unwrap();
    let mut search = request("machne learning");
    assert!(index.search(&search).unwrap().correction.is_none());
    search.search_mode = SearchMode::Original;
    assert_eq!(index.search(&search).unwrap().ids, ["literal"]);
    search.query = "ＭＡＣＨＩＮＥ learning".into();
    assert_eq!(index.search(&search).unwrap().ids, ["en"]);
}

#[test]
fn corrects_kana_compounds_using_registered_readings_and_preserves_script() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(vec![document("ja", "自然言語処理のための手法")], &[])
        .unwrap();
    for (query, corrected) in [
        ("しぜんげごしょり", "しぜんげんごしょり"),
        ("シゼンゲゴショリ", "シゼンゲンゴショリ"),
    ] {
        let page = index.search(&request(query)).unwrap();
        assert_eq!(page.ids, ["ja"]);
        assert_eq!(page.correction.unwrap().corrected_query, corrected);
    }
    assert!(index
        .search(&request("しぜんげんごしょり"))
        .unwrap()
        .correction
        .is_none());
    assert!(index
        .search(&request("自然言語処理"))
        .unwrap()
        .correction
        .is_none());
}

#[test]
fn corrects_short_voicing_errors_and_family_first_name_readings() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![SearchDocument {
                authors: vec!["太郎 山田".into()],
                author_aliases: vec!["山田 太郎".into()],
                ..document("ja", "モデル")
            }],
            &[],
        )
        .unwrap();
    for (query, expected) in [("モテル", "モデル"), ("やまたたろう", "やまだたろう")]
    {
        let page = index.search(&request(query)).unwrap();
        assert_eq!(page.ids, ["ja"]);
        assert_eq!(page.correction.unwrap().corrected_query, expected);
    }
    assert!(index
        .search(&request("モダル"))
        .unwrap()
        .correction
        .is_none());
}

#[test]
fn context_and_filters_resolve_ambiguity_without_rewriting_known_words() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![
                SearchDocument {
                    year: Some(2024),
                    ..document("cost", "Cost estimation")
                },
                SearchDocument {
                    year: Some(2020),
                    ..document("cart", "Cart design")
                },
            ],
            &[],
        )
        .unwrap();
    let page = index.search(&request("cast")).unwrap();
    assert!(page.correction.is_none());
    assert_eq!(page.total, 2);
    let page = index.search(&request("cast estimation")).unwrap();
    assert_eq!(page.correction.unwrap().corrected_query, "cost estimation");
    let mut search = request("cast");
    search.year = Some(2020);
    assert_eq!(
        index
            .search(&search)
            .unwrap()
            .correction
            .unwrap()
            .corrected_query,
        "cart"
    );
    index
        .apply(vec![document("known", "Cast members")], &[])
        .unwrap();
    assert!(index
        .search(&request("cast estimation"))
        .unwrap()
        .correction
        .is_none());
}

#[test]
fn corrections_follow_edits_deletion_and_restoration() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(vec![document("paper", "Machine learning")], &[])
        .unwrap();
    assert!(index
        .search(&request("machne learning"))
        .unwrap()
        .correction
        .is_some());
    index
        .apply(vec![document("paper", "Statistical learning")], &[])
        .unwrap();
    let page = index.search(&request("machne learning")).unwrap();
    assert_eq!(page.total, 0);
    assert!(page.correction.is_none());
    index
        .apply(vec![document("paper", "Machine learning")], &[])
        .unwrap();
    assert!(index
        .search(&request("machne learning"))
        .unwrap()
        .correction
        .is_some());
    index.apply(vec![], &["paper".into()]).unwrap();
    assert!(index
        .search(&request("machne learning"))
        .unwrap()
        .correction
        .is_none());
}

#[test]
fn protects_quotes_identifiers_short_terms_and_unknown_queries() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(vec![document("paper", "Machine learning GPT2")], &[])
        .unwrap();
    for query in [
        "\"machne learning\"",
        "\"machne\" learning",
        "doi:machne",
        "GPT3",
        "AI",
        "unrelated",
    ] {
        assert!(
            index.search(&request(query)).unwrap().correction.is_none(),
            "{query}"
        );
    }
    assert_eq!(
        index.search(&request("\"machne\" learning")).unwrap().total,
        0
    );
    let page = index.search(&request("machne \"learning\"")).unwrap();
    assert_eq!(
        page.correction.unwrap().corrected_query,
        "machine \"learning\""
    );
}

#[test]
fn supports_two_typos_and_keeps_unchanged_spacing_and_case() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(vec![document("paper", "Machine learning methods")], &[])
        .unwrap();
    let page = index.search(&request("MACHNE  lerning Methods")).unwrap();
    assert_eq!(
        page.correction.unwrap().corrected_query,
        "MACHINE  learning Methods"
    );
    assert!(index
        .search(&request("machne lerning metohds"))
        .unwrap()
        .correction
        .is_none());
}
