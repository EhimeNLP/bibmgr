use bibmgr_search::{SearchDocument, SearchIndex, SearchRequest};

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
        sort: "relevance".into(),
        ..SearchRequest::default()
    }
}

#[test]
fn ranks_exact_titles_and_identifiers_above_fuzzy_matches() {
    let index = SearchIndex::new().unwrap();
    let mut paper = document("paper", "Attention Is All You Need");
    paper.authors = vec!["Ashish Vaswani".into()];
    paper.identifiers = vec!["vaswani2017attention".into(), "10.1234/attention".into()];
    index
        .apply(
            vec![
                paper,
                document("typo", "Atention Is All You Need"),
                document("other", "Vaswani bibliography"),
            ],
            &[],
        )
        .unwrap();
    assert_eq!(
        index
            .search(&request("attention is all you need"))
            .unwrap()
            .ids[0],
        "paper"
    );
    assert_eq!(
        index.search(&request("Vaswani atention")).unwrap().ids,
        ["paper"]
    );
    assert_eq!(
        index
            .search(&request("https://doi.org/10.1234/attention"))
            .unwrap()
            .ids,
        ["paper"]
    );
    assert_eq!(
        index.search(&request("vaswani2017attention")).unwrap().ids,
        ["paper"]
    );
}

#[test]
fn tokenizes_japanese_and_normalizes_width_and_accents() {
    let index = SearchIndex::new().unwrap();
    let mut paper = document("ja", "自然言語処理のためのＢＥＲＴモデル");
    paper.authors = vec!["山田 太郎".into(), "Jörg Müller".into()];
    index
        .apply(vec![paper, document("other", "自然科学と画像処理")], &[])
        .unwrap();
    assert_eq!(
        index.search(&request("山田 自然言語 BERT")).unwrap().ids,
        ["ja"]
    );
    assert_eq!(index.search(&request("Muller bert")).unwrap().ids, ["ja"]);
    assert_eq!(index.search(&request("モテル")).unwrap().total, 0);
}

#[test]
fn preserves_english_model_names_in_english_and_mixed_text() {
    let index = SearchIndex::new().unwrap();
    let mut english = document("english", "Word2Vec and GPT2 Representations");
    english.authors = vec!["Jörg Müller".into()];
    index
        .apply(
            vec![
                english,
                document("mixed", "Ｗｏｒｄ２ＶｅｃとＧＰＴ２による自然言語処理"),
                document(
                    "unrelated",
                    "Word representations: 2 comparisons with Vec and GPT models",
                ),
            ],
            &[],
        )
        .unwrap();
    for query in ["word2vec", "GPT2", "word2v"] {
        let mut ids = index.search(&request(query)).unwrap().ids;
        ids.sort();
        assert_eq!(ids, ["english", "mixed"], "{query}");
    }
    for query in [
        "Muller word2vec",
        "GPT2 represenattions",
        "\"word2vec and gpt2\"",
    ] {
        assert_eq!(
            index.search(&request(query)).unwrap().ids,
            ["english"],
            "{query}"
        );
    }
    assert_eq!(
        index.search(&request("自然言語 GPT2")).unwrap().ids,
        ["mixed"]
    );
}

#[test]
fn supports_prefixes_and_quoted_phrases_without_query_syntax_injection() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![
                document("one", "neural machine translation"),
                document("two", "machine assisted neural translation"),
                document("three", "AI models"),
            ],
            &[],
        )
        .unwrap();
    assert_eq!(index.search(&request("neural translat")).unwrap().total, 2);
    assert_eq!(
        index.search(&request("\"neural machine\"")).unwrap().ids,
        ["one"]
    );
    assert_eq!(index.search(&request("AJ")).unwrap().total, 0);
    assert_eq!(index.search(&request("*:*")).unwrap().total, 0);
}

#[test]
fn allows_one_edit_in_long_japanese_words() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(vec![document("computer", "コンピューター科学")], &[])
        .unwrap();
    assert_eq!(
        index.search(&request("コンピュータ")).unwrap().ids,
        ["computer"]
    );
}

#[test]
fn filters_before_counting_and_paginating_and_updates_incrementally() {
    let index = SearchIndex::new().unwrap();
    let papers = (0..30)
        .map(|i| SearchDocument {
            id: format!("{i:02}"),
            title: "neural retrieval".into(),
            year: Some(2020 + i % 2),
            authors: vec!["Grace Hopper".into()],
            venues: vec!["TACL".into()],
            identifiers: vec![format!("key{i}")],
            entry_type: "article".into(),
            created_by: "person@example.test".into(),
            updated_at: i,
            ..SearchDocument::default()
        })
        .collect();
    index.apply(papers, &[]).unwrap();
    let mut search = request("neurla retrieval");
    search.year = Some(2021);
    search.author = Some("Hopper".into());
    search.venue = Some("acl".into());
    search.identifier = Some("key".into());
    search.entry_type = Some("ARTICLE".into());
    search.created_by = Some("@example.test".into());
    search.updated_from = Some(5);
    search.updated_to = Some(25);
    search.limit = 2;
    search.offset = 2;
    search.sort = "updated_desc".into();
    let page = index.search(&search).unwrap();
    assert_eq!(page.total, 11);
    assert_eq!(page.ids, ["21", "19"]);
    index
        .apply(vec![document("21", "unrelated")], &["19".into()])
        .unwrap();
    let page = index.search(&search).unwrap();
    assert_eq!(page.total, 9);
    assert_eq!(page.ids, ["17", "15"]);
    search.offset = 100;
    assert_eq!(
        index.search(&search).unwrap().ids,
        [] as [std::string::String; 0]
    );
    search.offset = usize::MAX;
    let page = index.search(&search).unwrap();
    assert_eq!(page.ids, [] as [std::string::String; 0]);
    assert_eq!(page.total, 9);
}

#[test]
fn ties_are_stable_and_missing_years_sort_last() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![
                document("b", "neural retrieval"),
                document("a", "neural retrieval"),
                SearchDocument {
                    year: Some(2024),
                    ..document("c", "neural retrieval")
                },
            ],
            &[],
        )
        .unwrap();
    assert_eq!(
        index.search(&request("retrieval")).unwrap().ids,
        ["a", "b", "c"]
    );
    for sort in ["year_asc", "year_desc"] {
        let mut search = request("retrieval");
        search.sort = sort.into();
        assert_eq!(index.search(&search).unwrap().ids, ["c", "a", "b"]);
    }
}
