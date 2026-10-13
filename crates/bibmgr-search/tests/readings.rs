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
        limit: 100,
        sort: "relevance".into(),
        ..SearchRequest::default()
    }
}

fn ids(index: &SearchIndex, query: &str) -> Vec<String> {
    index.search(&request(query)).unwrap().ids
}

#[test]
fn retrieves_researcher_names_from_neologd_readings() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![
                SearchDocument {
                    authors: vec!["山中伸弥".into()],
                    ..document("stem-cells", "幹細胞研究")
                },
                SearchDocument {
                    authors: vec!["本庶佑".into()],
                    ..document("immunity", "免疫学研究")
                },
                document("other", "自然言語処理"),
            ],
            &[],
        )
        .unwrap();
    for (query, expected) in [
        ("やまなかしんや", "stem-cells"),
        ("ほんじょたすく", "immunity"),
        ("ホンジョタスク 免疫学", "immunity"),
        ("\"ほんじょたすく\"", "immunity"),
        ("しぜんげんごしょり", "other"),
    ] {
        let page = index.search(&request(query)).unwrap();
        assert_eq!(page.ids, [expected], "{query}");
        assert!(page.correction.is_none(), "{query}");
    }
}

#[test]
fn retrieves_kana_homophones_names_and_mixed_model_names() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![
                SearchDocument {
                    authors: vec!["山田 太郎".into(), "Jörg Müller".into()],
                    venues: vec!["情報処理学会".into()],
                    ..document("paper", "Word2VecとGPT2による自然言語処理と機械学習モデル")
                },
                document(
                    "other",
                    "Word representations 2 comparisons with Vec and GPT models",
                ),
            ],
            &[],
        )
        .unwrap();
    for query in [
        "しぜんげんごしょり",
        "シゼンゲンゴショリ",
        "ｼｾﾞﾝｹﾞﾝｺﾞｼｮﾘ",
        "しせ\u{3099}んけ\u{3099}んこ\u{3099}しょり",
        "自然げんごしょり",
        "きかいがくしゅう",
        "機会学習",
        "もでる",
        "モテル",
        "やまだ",
        "やまだたろう",
        "じょうほうしょりがっかい",
        "GPT2しぜんげんご",
        "Ｗｏｒｄ２Ｖｅｃしぜんげんご",
        "しぜんげんご GPT2 Muller",
        "word2v やまだ",
    ] {
        assert_eq!(ids(&index, query), ["paper"], "{query}");
    }
    assert_eq!(ids(&index, "GPT3しぜんげんご"), [] as [String; 0]);
    assert_eq!(
        ids(&index, "unknownenglish しぜんげんご"),
        [] as [String; 0]
    );
}

#[test]
fn tolerates_edits_across_morphological_boundaries() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![
                document("nlp", "自然言語処理"),
                document("library", "図書館"),
                document("unknown", "ヌペラトガサ"),
            ],
            &[],
        )
        .unwrap();
    for query in [
        "しぜんげごしょり",
        "しぜんげんごしょりい",
        "しぜんけんごしょり",
        "しぜげんんごしょり",
    ] {
        assert_eq!(ids(&index, query), ["nlp"], "{query}");
    }
    // A middle transposition in four characters leaves no shared bigram.
    assert_eq!(ids(&index, "としょかん"), ["library"]);
    assert_eq!(ids(&index, "ヌペトラガサ"), ["unknown"]);
    assert_eq!(ids(&index, "しぜげごしり"), [] as [String; 0]);
}

#[test]
fn four_character_transposition_survives_candidate_generation() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(vec![document("paper", "ヌペラト")], &[])
        .unwrap();
    assert_eq!(ids(&index, "ぬらぺと"), ["paper"]);
}

#[test]
fn retains_candidates_for_every_single_edit_position() {
    for text in ["ぬぺらと", "ぬぺらとが", "ぬぺらとがさみよ"] {
        let index = SearchIndex::new().unwrap();
        let katakana: String = text
            .chars()
            .map(|c| char::from_u32(u32::from(c) + 0x60).unwrap())
            .collect();
        index
            .apply(vec![document("paper", &format!("研究{katakana}研究"))], &[])
            .unwrap();
        let original: Vec<_> = text.chars().collect();
        let mut queries = Vec::new();
        for i in 0..=original.len() {
            let mut inserted = original.clone();
            inserted.insert(i, 'ほ');
            queries.push(inserted);
        }
        for i in 0..original.len() {
            let mut replaced = original.clone();
            replaced[i] = 'ほ';
            queries.push(replaced);
            if original.len() > 4 {
                let mut deleted = original.clone();
                deleted.remove(i);
                queries.push(deleted);
            }
            if i + 1 < original.len() {
                let mut swapped = original.clone();
                swapped.swap(i, i + 1);
                queries.push(swapped);
            }
        }
        for query in queries {
            let query: String = query.into_iter().collect();
            assert_eq!(ids(&index, &query), ["paper"], "{text}: {query}");
        }
    }
}

#[test]
fn limits_short_kana_and_keeps_distinct_sounds() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![
                document("model", "モデル"),
                document("map", "地図"),
                document("different", "モトル"),
                document("letter", "AI"),
            ],
            &[],
        )
        .unwrap();
    assert_eq!(ids(&index, "もでる"), ["model"]);
    assert_eq!(ids(&index, "モテル"), ["model"]);
    assert_eq!(ids(&index, "ちず"), ["map"]);
    for query in ["ちす", "もて", "モダル", "AJ"] {
        assert!(ids(&index, query).is_empty(), "{query}");
    }
}

#[test]
fn ranks_surface_then_reading_then_typo_regardless_of_bm25() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![
                document("surface", "機械学習と文献管理の研究"),
                document("homophone", "機会学習"),
                document("typo", "キカイガクシュ"),
            ],
            &[],
        )
        .unwrap();
    assert_eq!(ids(&index, "機械学習"), ["surface", "homophone", "typo"]);
    assert_eq!(ids(&index, "機会学習")[0], "homophone");
}

#[test]
fn rejects_disconnected_grams_and_separate_field_values() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![
                document("correct", "自然 言語 処理"),
                SearchDocument {
                    authors: vec!["自然言語".into(), "処理".into()],
                    ..document("authors", "irrelevant")
                },
                SearchDocument {
                    venues: vec!["言語処理".into()],
                    ..document("fields", "自然")
                },
                document("scattered", "シゼンaaaゼンゲbbbゲンゴcccゴショdddショリ"),
                document("latin", "自然GPT2言語処理"),
            ],
            &[],
        )
        .unwrap();
    assert_eq!(ids(&index, "しぜんげんごしょり"), ["correct"]);
    assert_eq!(
        index.search(&request("しぜんげんごしょり")).unwrap().total,
        1
    );
}

#[test]
fn quotes_require_contiguous_readings_with_exact_latin_words() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![
                document("correct", "GPT2と自然言語処理のモデル"),
                document("reversed", "自然言語処理とGPT2のモデル"),
                document("number", "GPT20と自然言語処理のモデル"),
                document("gap", "GPT2と効率的な自然言語処理のモデル"),
            ],
            &[],
        )
        .unwrap();
    assert_eq!(ids(&index, "\"GPT2としぜんげんごしょり\""), ["correct"]);
    assert_eq!(ids(&index, "\"GPT2としぜんげごしょり\""), [] as [String; 0]);
    assert_eq!(ids(&index, "\"モテル\""), [] as [String; 0]);
    assert_eq!(ids(&index, "\"GPT2と自然言語処理\""), ["correct"]);
}

#[test]
fn reading_expansion_does_not_apply_to_identifiers_body_or_filters() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![
                SearchDocument {
                    identifiers: vec!["自然言語処理".into()],
                    ..document("id", "identifiers")
                },
                SearchDocument {
                    body: "自然言語処理".into(),
                    ..document("body", "source")
                },
                SearchDocument {
                    authors: vec!["山田".into()],
                    ..document("title", "自然言語処理")
                },
            ],
            &[],
        )
        .unwrap();
    assert_eq!(ids(&index, "しぜんげんごしょり"), ["title"]);
    assert_eq!(index.search(&request("自然言語処理")).unwrap().total, 3);
    let mut query = request("しぜんげんごしょり");
    query.author = Some("やまだ".into());
    assert_eq!(index.search(&query).unwrap().total, 0);
    query.author = Some("山田".into());
    assert_eq!(index.search(&query).unwrap().ids, ["title"]);
}

#[test]
fn author_aliases_only_extend_japanese_readings() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(
            vec![SearchDocument {
                authors: vec!["太郎 山田".into(), "John Smith".into()],
                author_aliases: vec!["山田 太郎".into(), "Smith John".into()],
                ..document("paper", "Neural retrieval")
            }],
            &[],
        )
        .unwrap();
    for query in ["やまだたろう", "たろうやまだ", "\"やまだたろう\""] {
        assert_eq!(ids(&index, query), ["paper"]);
    }
    assert_eq!(ids(&index, "\"Smith John\""), [] as [String; 0]);
    assert_eq!(ids(&index, "\"John Smith\""), ["paper"]);
    let mut query = request("やまだたろう");
    query.author = Some("山田 太郎".into());
    assert_eq!(index.search(&query).unwrap().total, 0);
    query.author = Some("太郎 山田".into());
    assert_eq!(index.search(&query).unwrap().total, 1);
}

#[test]
fn counts_all_verified_filtered_hits_before_pagination() {
    let index = SearchIndex::new().unwrap();
    let mut documents: Vec<_> = (0..150)
        .map(|i| SearchDocument {
            year: Some(2020 + i % 2),
            updated_at: i,
            ..document(&format!("{i:03}"), "自然言語処理")
        })
        .collect();
    documents.extend((0..150).map(|i| document(&format!("noise{i}"), "シゼンxxxゲンゴxxxショリ")));
    index.apply(documents, &[]).unwrap();
    let mut query = request("しぜんげごしょり");
    query.year = Some(2021);
    query.limit = 3;
    query.sort = "updated_desc".into();
    query.offset = 60;
    let page = index.search(&query).unwrap();
    assert_eq!(page.total, 75);
    assert_eq!(page.ids, ["029", "027", "025"]);
    for offset in [75, 500, usize::MAX] {
        query.offset = offset;
        let page = index.search(&query).unwrap();
        assert_eq!(page.total, 75);
        assert_eq!(page.ids, [] as [String; 0]);
    }
}

#[test]
fn updates_deletes_and_rebuilds_readings_without_stale_hits() {
    let index = SearchIndex::new().unwrap();
    index
        .apply(vec![document("paper", "自然言語処理")], &[])
        .unwrap();
    assert_eq!(ids(&index, "しぜんげんごしょり"), ["paper"]);
    index
        .apply(vec![document("paper", "機械学習")], &[])
        .unwrap();
    assert_eq!(ids(&index, "しぜんげんごしょり"), [] as [String; 0]);
    assert_eq!(ids(&index, "きかいがくしゅう"), ["paper"]);
    index.apply(vec![], &["paper".into()]).unwrap();
    assert_eq!(ids(&index, "きかいがくしゅう"), [] as [String; 0]);
    index
        .apply(vec![document("paper", "自然言語処理")], &[])
        .unwrap();
    assert_eq!(ids(&index, "しぜんげんごしょり"), ["paper"]);
}

#[test]
fn bounds_fuzzy_work_and_retains_exact_long_queries_and_unknown_kanji() {
    let index = SearchIndex::new().unwrap();
    let long = "ぬ".repeat(512);
    index
        .apply(
            vec![document("long", &long), document("unknown", "𠮷𠮷研究")],
            &[],
        )
        .unwrap();
    assert_eq!(ids(&index, &long), ["long"]);
    assert_eq!(
        ids(&index, &format!("{}へ", "ぬ".repeat(511))),
        [] as [String; 0]
    );
    assert!(index.search(&request(&"ぬ".repeat(513))).is_err());
    assert_eq!(ids(&index, "𠮷𠮷研究"), ["unknown"]);
}

#[test]
fn concurrent_readers_observe_a_complete_generation() {
    let index = SearchIndex::new().unwrap();
    let batch = |title| (0..20).map(|i| document(&i.to_string(), title)).collect();
    index.apply(batch("自然言語処理"), &[]).unwrap();
    std::thread::scope(|scope| {
        for _ in 0..3 {
            let index = &index;
            scope.spawn(move || {
                for _ in 0..30 {
                    let page = index.search(&request("しぜんげんごしょり")).unwrap();
                    assert!([0, 20].contains(&page.total));
                    assert_eq!(page.total, page.ids.len());
                }
            });
        }
        for i in 0..8 {
            index
                .apply(
                    batch(if i % 2 == 0 {
                        "機械学習"
                    } else {
                        "自然言語処理"
                    }),
                    &[],
                )
                .unwrap();
        }
    });
}
