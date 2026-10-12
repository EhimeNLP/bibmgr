//! CPU-only, field-aware bibliography retrieval. `PostgreSQL` owns the source data;
//! this index is a disposable, incrementally updated projection.

use std::cmp::Ordering;
use std::collections::HashMap;
use std::ops::Bound;
use std::sync::{Arc, OnceLock};

use lindera::segmenter::Segmenter;
use serde::{Deserialize, Serialize};
use tantivy::collector::{Count, TopDocs};
use tantivy::query::{
    AllQuery, BooleanQuery, BoostQuery, ConstScoreQuery, EmptyQuery, FuzzyTermQuery, Occur,
    PhraseQuery, Query, RangeQuery, RegexQuery, TermQuery,
};
use tantivy::schema::{
    Field, IndexRecordOption, Schema, TextFieldIndexing, TextOptions, FAST, INDEXED, STORED,
    STRING, TEXT,
};
use tantivy::{
    Index, IndexReader, IndexWriter, ReloadPolicy, SegmentReader, TantivyDocument, Term,
};
use unicode_normalization::{char::is_combining_mark, UnicodeNormalization};

mod analysis;
mod reading;

use analysis::{analyze, Analysis, Group};
use reading::{Pattern, ReadingQuery, Readings};

#[derive(Debug, thiserror::Error)]
pub enum SearchError {
    #[error("{0}")]
    Index(#[from] tantivy::TantivyError),
    #[error("Japanese tokenizer: {0}")]
    Tokenizer(String),
    #[error("Invalid search request: {0}")]
    InvalidRequest(String),
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct SearchDocument {
    pub id: String,
    pub title: String,
    pub authors: Vec<String>,
    /// Additional name orders used only by Japanese reading retrieval.
    pub author_aliases: Vec<String>,
    pub venues: Vec<String>,
    pub identifiers: Vec<String>,
    pub body: String,
    pub year: Option<i64>,
    pub entry_type: String,
    pub created_by: String,
    pub updated_at: i64,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct SearchRequest {
    pub query: String,
    pub year: Option<i64>,
    pub author: Option<String>,
    pub venue: Option<String>,
    pub identifier: Option<String>,
    pub entry_type: Option<String>,
    pub created_by: Option<String>,
    pub updated_from: Option<i64>,
    pub updated_to: Option<i64>,
    pub sort: String,
    pub limit: usize,
    pub offset: usize,
}

#[derive(Debug, Serialize)]
pub struct SearchPage {
    pub ids: Vec<String>,
    pub total: usize,
}

#[derive(Debug)]
struct Metadata {
    id: String,
    title: String,
    identifiers: Vec<String>,
    year: Option<i64>,
    updated_at: i64,
    readings: Readings,
}

#[derive(Clone)]
pub struct SearchIndex {
    inner: Arc<std::sync::Mutex<IndexState>>,
}

impl std::fmt::Debug for SearchIndex {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SearchIndex").finish_non_exhaustive()
    }
}

struct IndexState {
    index: Index,
    reader: IndexReader,
    writer: IndexWriter,
    metadata: Arc<HashMap<u64, Arc<Metadata>>>,
    ordinals: HashMap<String, u64>,
    next_ordinal: u64,
}

fn tokenizer() -> Result<&'static Segmenter, SearchError> {
    static TOKENIZER: OnceLock<Result<Segmenter, String>> = OnceLock::new();
    TOKENIZER
        .get_or_init(|| {
            Segmenter::from_config(&serde_json::json!({
                "dictionary": {"kind": "ipadic"}, "mode": "normal"
            }))
            .map_err(|error| error.to_string())
        })
        .as_ref()
        .map_err(|error| SearchError::Tokenizer(error.clone()))
}

fn normalize(text: &str) -> String {
    text.nfkc()
        .flat_map(char::to_lowercase)
        .collect::<String>()
        .nfd()
        .filter(|c| !is_combining_mark(*c) || matches!(c, '\u{3099}' | '\u{309a}'))
        .nfc()
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

impl SearchIndex {
    pub fn new() -> Result<Self, SearchError> {
        tokenizer()?;
        let mut schema = Schema::builder();
        schema.add_text_field("id", STRING);
        schema.add_u64_field("ordinal", FAST | STORED);
        for name in ["title", "authors", "venues", "identifiers", "body"] {
            schema.add_text_field(name, TEXT);
        }
        schema.add_text_field(
            reading::GRAM_FIELD,
            TextOptions::default().set_indexing_options(
                TextFieldIndexing::default()
                    .set_tokenizer("default")
                    .set_index_option(IndexRecordOption::Basic)
                    .set_fieldnorms(false),
            ),
        );
        for name in [
            "author_filter",
            "venue_filter",
            "identifier_filter",
            "entry_type",
            "created_by",
        ] {
            schema.add_text_field(name, STRING);
        }
        schema.add_i64_field("year", INDEXED | FAST);
        schema.add_i64_field("updated_at", INDEXED | FAST);
        let index = Index::create_in_ram(schema.build());
        index.tokenizers().register(
            "default",
            tantivy::tokenizer::WhitespaceTokenizer::default(),
        );
        // Use one writer thread and a fixed buffer independently of CPU count.
        let writer = index.writer_with_num_threads(1, 15_000_000)?;
        let reader = index
            .reader_builder()
            .reload_policy(ReloadPolicy::Manual)
            .try_into()?;
        Ok(Self {
            inner: Arc::new(std::sync::Mutex::new(IndexState {
                index,
                reader,
                writer,
                metadata: Arc::default(),
                ordinals: HashMap::new(),
                next_ordinal: 0,
            })),
        })
    }

    pub fn apply(
        &self,
        documents: Vec<SearchDocument>,
        deleted_ids: &[String],
    ) -> Result<(), SearchError> {
        let mut state = self
            .inner
            .lock()
            .map_err(|_| SearchError::InvalidRequest("index lock poisoned".into()))?;
        // Tokenize before touching the writer so malformed documents cannot leave a partial batch.
        let schema = state.index.schema();
        let mut prepared = Vec::with_capacity(documents.len());
        for input in &documents {
            let mut doc = TantivyDocument::default();
            let mut readings = Readings::default();
            doc.add_text(field(&schema, "id"), &input.id);
            for (name, values) in [
                ("title", vec![input.title.as_str()]),
                (
                    "authors",
                    input.authors.iter().map(String::as_str).collect(),
                ),
                ("venues", input.venues.iter().map(String::as_str).collect()),
                (
                    "identifiers",
                    input.identifiers.iter().map(String::as_str).collect(),
                ),
                ("body", vec![input.body.as_str()]),
            ] {
                for value in values {
                    let analysis = analyze(value)?;
                    doc.add_text(field(&schema, name), analysis.words().join(" "));
                    readings.add(name, &analysis);
                }
            }
            for alias in &input.author_aliases {
                readings.add("author_aliases", &analyze(alias)?);
            }
            doc.add_text(field(&schema, reading::GRAM_FIELD), readings.grams());
            for (name, values) in [
                ("author_filter", &input.authors),
                ("venue_filter", &input.venues),
                ("identifier_filter", &input.identifiers),
            ] {
                for value in values {
                    doc.add_text(field(&schema, name), normalize(value));
                }
            }
            doc.add_text(field(&schema, "entry_type"), normalize(&input.entry_type));
            doc.add_text(field(&schema, "created_by"), normalize(&input.created_by));
            if let Some(year) = input.year {
                doc.add_i64(field(&schema, "year"), year);
            }
            doc.add_i64(field(&schema, "updated_at"), input.updated_at);
            prepared.push((doc, readings));
        }
        for id in deleted_ids
            .iter()
            .chain(documents.iter().map(|doc| &doc.id))
        {
            state
                .writer
                .delete_term(Term::from_field_text(field(&schema, "id"), id));
            if let Some(ordinal) = state.ordinals.remove(id) {
                Arc::make_mut(&mut state.metadata).remove(&ordinal);
            }
        }
        for (input, (mut doc, readings)) in documents.into_iter().zip(prepared) {
            let ordinal = state.next_ordinal;
            state.next_ordinal += 1;
            doc.add_u64(field(&schema, "ordinal"), ordinal);
            state.writer.add_document(doc)?;
            state.ordinals.insert(input.id.clone(), ordinal);
            Arc::make_mut(&mut state.metadata).insert(
                ordinal,
                Arc::new(Metadata {
                    id: input.id,
                    title: normalize(&input.title),
                    identifiers: input
                        .identifiers
                        .iter()
                        .map(|value| normalize(value))
                        .collect(),
                    year: input.year,
                    updated_at: input.updated_at,
                    readings,
                }),
            );
        }
        state.writer.commit()?;
        state.reader.reload()?;
        Ok(())
    }

    /// Retrieve one ranked page and the exact number of filtered matches.
    ///
    /// # Panics
    /// Panics if an internally created segment violates the owned index schema.
    pub fn search(&self, request: &SearchRequest) -> Result<SearchPage, SearchError> {
        if !(1..=100).contains(&request.limit) || request.query.chars().count() > 512 {
            return Err(SearchError::InvalidRequest(
                "limit must be 1..100 and query at most 512 characters".into(),
            ));
        }
        let state = self
            .inner
            .lock()
            .map_err(|_| SearchError::InvalidRequest("index lock poisoned".into()))?;
        let schema = state.index.schema();
        let mut request = request.clone();
        request.query = identifier_query(&request.query);
        let searcher = state.reader.searcher();
        let metadata = Arc::clone(&state.metadata);
        // Pin the reader and its corresponding metadata together. Readers can
        // finish on this immutable snapshot while another batch is committed.
        drop(state);
        let analysis = analyze(&request.query)?;
        let query = build_query(&schema, &request, &analysis, &metadata)?;
        if u64::try_from(request.offset).unwrap_or(u64::MAX) >= searcher.num_docs() {
            return Ok(SearchPage {
                total: searcher.search(&query, &Count)?,
                ids: Vec::new(),
            });
        }
        let sort = request.sort.clone();
        let normalized_query = normalize(&request.query);
        let japanese: Vec<_> = analysis
            .groups
            .into_iter()
            .filter_map(|group| match group {
                Group::Japanese { words, reading } => Some((words, Pattern::new(reading, false))),
                Group::Word(_) => None,
            })
            .collect();
        let collector = TopDocs::with_limit(request.limit)
            .and_offset(request.offset)
            .tweak_score(move |segment: &SegmentReader| {
                let ordinals = segment
                    .fast_fields()
                    .u64("ordinal")
                    .expect("index schema contains ordinal")
                    .first_or_default_col(0);
                let metadata = Arc::clone(&metadata);
                let sort = sort.clone();
                let query = normalized_query.clone();
                let japanese = japanese.clone();
                move |doc, score| {
                    let data = &metadata[&ordinals.get_val(doc)];
                    let exact = if data.identifiers.contains(&query) {
                        2
                    } else {
                        u8::from(data.title == query)
                    };
                    Rank {
                        sort: sort.clone(),
                        exact,
                        quality: japanese
                            .iter()
                            .map(|(words, pattern)| {
                                if words
                                    .iter()
                                    .all(|word| data.readings.surface_words.contains(word))
                                {
                                    3
                                } else if data.readings.exact(pattern) {
                                    2
                                } else {
                                    1
                                }
                            })
                            .min()
                            .unwrap_or(3),
                        score,
                        data: data.clone(),
                    }
                }
            });
        let (total, hits) = searcher.search(&query, &(Count, collector))?;
        Ok(SearchPage {
            total,
            ids: hits
                .into_iter()
                .map(|(rank, _)| rank.data.id.clone())
                .collect(),
        })
    }
}

fn field(schema: &Schema, name: &str) -> Field {
    schema.get_field(name).expect("owned search schema")
}

fn term_query(field: Field, value: &str) -> Box<dyn Query> {
    Box::new(TermQuery::new(
        Term::from_field_text(field, value),
        IndexRecordOption::WithFreqs,
    ))
}

fn identifier_query(query: &str) -> String {
    let query = normalize(query);
    for prefix in [
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "doi:",
        "https://arxiv.org/abs/",
        "arxiv:",
    ] {
        if let Some(value) = query.strip_prefix(prefix) {
            return value.trim().to_owned();
        }
    }
    query
}

fn word_query(schema: &Schema, word: &str) -> Box<dyn Query> {
    let mut alternatives = Vec::new();
    for (name, weight) in [
        ("title", 5.0),
        ("authors", 3.0),
        ("identifiers", 4.0),
        ("venues", 2.0),
        ("body", 0.5),
    ] {
        let search_field = field(schema, name);
        alternatives.push((
            Occur::Should,
            Box::new(BoostQuery::new(term_query(search_field, word), weight)) as Box<dyn Query>,
        ));
        // Short words require exact matches. Bound expansion by Unicode
        // character count, including long Japanese and accented Latin terms.
        if (4..=32).contains(&word.chars().count())
            && word.chars().all(char::is_alphabetic)
            && name != "identifiers"
        {
            alternatives.push((
                Occur::Should,
                Box::new(BoostQuery::new(
                    Box::new(FuzzyTermQuery::new(
                        Term::from_field_text(search_field, word),
                        1,
                        true,
                    )),
                    weight * 0.15,
                )),
            ));
        }
        if word.len() >= 3 && word.is_ascii() {
            alternatives.push((
                Occur::Should,
                Box::new(BoostQuery::new(
                    Box::new(FuzzyTermQuery::new_prefix(
                        Term::from_field_text(search_field, word),
                        0,
                        false,
                    )),
                    weight * 0.3,
                )),
            ));
        }
    }
    Box::new(BooleanQuery::new(alternatives))
}

fn build_query(
    schema: &Schema,
    request: &SearchRequest,
    analysis: &Analysis,
    metadata: &Arc<HashMap<u64, Arc<Metadata>>>,
) -> Result<Box<dyn Query>, SearchError> {
    let words = analysis.words();
    let mut clauses: Vec<(Occur, Box<dyn Query>)> = Vec::new();
    if words.is_empty() {
        clauses.push((
            Occur::Must,
            if request.query.trim().is_empty() {
                Box::new(AllQuery)
            } else {
                Box::new(EmptyQuery)
            },
        ));
    }
    for group in &analysis.groups {
        let query = match group {
            Group::Word(word) => word_query(schema, word),
            Group::Japanese { words, reading } => {
                let surface = BooleanQuery::new(
                    words
                        .iter()
                        .map(|word| (Occur::Must, word_query(schema, word)))
                        .collect(),
                );
                Box::new(BooleanQuery::new(vec![
                    (Occur::Should, Box::new(surface)),
                    (
                        Occur::Should,
                        Box::new(ReadingQuery::new(
                            schema,
                            Pattern::new(reading.clone(), true),
                            metadata,
                        )),
                    ),
                ]))
            }
        };
        clauses.push((Occur::Must, query));
    }
    if words.len() > 1 {
        clauses.push((
            Occur::Should,
            Box::new(BoostQuery::new(
                Box::new(PhraseQuery::new(
                    words
                        .iter()
                        .map(|word| Term::from_field_text(field(schema, "title"), word))
                        .collect(),
                )),
                5.0,
            )),
        ));
    }
    // Balanced quotes require consecutive tokens within one field. Treat all
    // other punctuation literally; never pass user input to a query parser.
    for phrase in request
        .query
        .split('"')
        .skip(1)
        .step_by(2)
        .take(request.query.matches('"').count() / 2)
    {
        let phrase_analysis = analyze(phrase)?;
        let phrase_words = phrase_analysis.words();
        if phrase_words.len() > 1 || phrase_analysis.has_japanese() {
            let mut alternatives: Vec<_> = ["title", "authors", "venues", "identifiers", "body"]
                .into_iter()
                .map(|name| {
                    (
                        Occur::Should,
                        if phrase_words.len() == 1 {
                            term_query(field(schema, name), &phrase_words[0])
                        } else {
                            Box::new(PhraseQuery::new(
                                phrase_words
                                    .iter()
                                    .map(|word| Term::from_field_text(field(schema, name), word))
                                    .collect(),
                            )) as Box<dyn Query>
                        },
                    )
                })
                .collect();
            if phrase_analysis.has_japanese() {
                alternatives.push((
                    Occur::Should,
                    Box::new(ReadingQuery::new(
                        schema,
                        Pattern::new(phrase_analysis.canonical_reading(), false),
                        metadata,
                    )),
                ));
            }
            clauses.push((Occur::Must, Box::new(BooleanQuery::new(alternatives))));
        }
    }
    append_filters(schema, request, &mut clauses)?;
    Ok(Box::new(BooleanQuery::new(clauses)))
}

fn append_filters(
    schema: &Schema,
    request: &SearchRequest,
    clauses: &mut Vec<(Occur, Box<dyn Query>)>,
) -> Result<(), SearchError> {
    for (name, value) in [
        ("author_filter", &request.author),
        ("venue_filter", &request.venue),
        ("identifier_filter", &request.identifier),
        ("created_by", &request.created_by),
    ] {
        if let Some(value) = value
            .as_deref()
            .map(normalize)
            .filter(|value| !value.is_empty())
        {
            let pattern = format!(".*{}.*", regex::escape(&value));
            clauses.push((
                Occur::Must,
                Box::new(ConstScoreQuery::new(
                    Box::new(RegexQuery::from_pattern(&pattern, field(schema, name))?),
                    0.0,
                )),
            ));
        }
    }
    if let Some(value) = request
        .entry_type
        .as_deref()
        .map(normalize)
        .filter(|value| !value.is_empty())
    {
        clauses.push((
            Occur::Must,
            Box::new(ConstScoreQuery::new(
                term_query(field(schema, "entry_type"), &value),
                0.0,
            )),
        ));
    }
    for (name, lower, upper) in [
        ("year", request.year, request.year),
        ("updated_at", request.updated_from, request.updated_to),
    ] {
        if lower.is_some() || upper.is_some() {
            let search_field = field(schema, name);
            clauses.push((
                Occur::Must,
                Box::new(ConstScoreQuery::new(
                    Box::new(RangeQuery::new(
                        lower.map_or(Bound::Unbounded, |value| {
                            Bound::Included(Term::from_field_i64(search_field, value))
                        }),
                        upper.map_or(Bound::Unbounded, |value| {
                            Bound::Included(Term::from_field_i64(search_field, value))
                        }),
                    )),
                    0.0,
                )),
            ));
        }
    }
    Ok(())
}

#[derive(Debug, Clone)]
struct Rank {
    sort: String,
    exact: u8,
    quality: u8,
    score: f32,
    data: Arc<Metadata>,
}

impl PartialEq for Rank {
    fn eq(&self, other: &Self) -> bool {
        self.cmp(other) == Ordering::Equal
    }
}
impl Eq for Rank {}
impl PartialOrd for Rank {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
impl Ord for Rank {
    fn cmp(&self, other: &Self) -> Ordering {
        // TopDocs selects the greatest key; reverse ascending keys and UUIDs.
        let order = match self.sort.as_str() {
            "updated_asc" => other.data.updated_at.cmp(&self.data.updated_at),
            "updated_desc" => self.data.updated_at.cmp(&other.data.updated_at),
            "title_asc" => title_order(&self.data.title, &other.data.title),
            "year_asc" | "year_desc" => self
                .data
                .year
                .is_some()
                .cmp(&other.data.year.is_some())
                .then_with(|| {
                    if self.sort == "year_asc" {
                        other.data.year.cmp(&self.data.year)
                    } else {
                        self.data.year.cmp(&other.data.year)
                    }
                })
                .then_with(|| title_order(&self.data.title, &other.data.title)),
            _ => self
                .exact
                .cmp(&other.exact)
                .then_with(|| self.quality.cmp(&other.quality))
                .then_with(|| self.score.total_cmp(&other.score)),
        };
        order.then_with(|| other.data.id.cmp(&self.data.id))
    }
}

fn title_order(left: &str, right: &str) -> Ordering {
    right
        .is_empty()
        .cmp(&left.is_empty())
        .then_with(|| right.cmp(left))
}
