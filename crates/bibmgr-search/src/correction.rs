//! Conservative, corpus-derived spelling correction. Candidate enumeration and
//! full-query verification are bounded; exhaustion means no automatic rewrite.

use std::collections::{BTreeSet, HashMap};
use std::sync::{Arc, OnceLock};

use levenshtein_automata::{Distance, LevenshteinAutomatonBuilder, DFA};
use tantivy::collector::Count;
use tantivy::schema::Schema;
use tantivy::Searcher;
use tantivy_fst::Automaton;

use super::analysis::{is_kana, Analysis, Group};
use super::{
    analyze, build_query, field, identifier_query, normalize, term_query, Metadata, Retrieval,
    SearchCorrection, SearchError, SearchRequest,
};

pub(crate) const FIELD: &str = "spelling";
const MAX_CANDIDATES: usize = 8;
const MAX_REWRITES: usize = 16;

pub(crate) fn terms(analysis: &Analysis) -> BTreeSet<String> {
    let mut terms: BTreeSet<_> = analysis
        .groups
        .iter()
        .filter_map(|group| match group {
            Group::Word(word) if eligible(word) => Some(word.clone()),
            _ => None,
        })
        .collect();
    // Token boundaries keep Japanese corrections grounded in complete words
    // and compounds. Bound each window by characters, even for long titles.
    for tokens in &analysis.reading_tokens {
        for start in 0..tokens.len() {
            let mut value = String::new();
            let mut length = 0;
            for token in &tokens[start..] {
                length += token.chars().count();
                if length > 32 || !token.chars().all(is_kana) {
                    break;
                }
                value.push_str(token);
                if length >= 3 {
                    terms.insert(value.clone());
                }
            }
        }
    }
    terms
}

fn eligible(value: &str) -> bool {
    let length = value.chars().count();
    ((4..=32).contains(&length) && value.chars().all(|c| c.is_ascii_alphabetic()))
        || ((3..=32).contains(&length) && value.chars().all(is_kana))
}

pub(crate) fn suggest(
    searcher: &Searcher,
    schema: &Schema,
    request: &SearchRequest,
    metadata: &Arc<HashMap<u64, Arc<Metadata>>>,
) -> Result<Option<SearchCorrection>, SearchError> {
    static TOKENS: OnceLock<regex::Regex> = OnceLock::new();
    if request.query.trim().is_empty() {
        return Ok(None);
    }
    let mut exact = request.clone();
    exact.query = identifier_query(&request.query);
    let query = build_query(
        schema,
        &exact,
        &analyze(&exact.query)?,
        metadata,
        Retrieval::ExactReading,
    )?;
    if searcher.search(&query, &Count)? > 0 {
        return Ok(None);
    }
    let tokens = TOKENS.get_or_init(|| {
        regex::Regex::new(r#""[^"]*(?:"|$)|[^\s"]+"#).expect("valid query span pattern")
    });
    let spans: Vec<_> = tokens.find_iter(&request.query).collect();
    if spans.len() > 16 {
        return Ok(None);
    }
    let mut rewrites = vec![String::new()];
    let mut end = 0;
    let mut changes = 0;
    for span in spans {
        let original = span.as_str();
        let analysis = analyze(original)?;
        let normalized = normalize(original);
        let key = if normalized.chars().all(is_kana) {
            analysis.canonical_reading()
        } else {
            normalized
        };
        let choices = if eligible(&key) && !original.contains('"') {
            candidates(searcher, schema, &key)?
        } else {
            vec![key.clone()]
        };
        // A known spelling (including a rare name) is never changed.
        if choices.contains(&key) {
            for rewrite in &mut rewrites {
                rewrite.push_str(&request.query[end..span.end()]);
            }
        } else {
            changes += 1;
            if choices.is_empty() || changes > 2 || rewrites.len() * choices.len() > MAX_REWRITES {
                return Ok(None);
            }
            rewrites = rewrites
                .iter()
                .flat_map(|prefix| {
                    choices.iter().map(move |choice| {
                        format!(
                            "{}{}{}",
                            prefix,
                            &request.query[end..span.start()],
                            display_spelling(choice, original)
                        )
                    })
                })
                .collect();
        }
        end = span.end();
    }
    if changes == 0 {
        return Ok(None);
    }
    let mut scored = Vec::new();
    for mut rewrite in rewrites {
        rewrite.push_str(&request.query[end..]);
        exact.query = identifier_query(&rewrite);
        let query = build_query(
            schema,
            &exact,
            &analyze(&exact.query)?,
            metadata,
            Retrieval::ExactReading,
        )?;
        let count = searcher.search(&query, &Count)?;
        if count > 0 {
            scored.push((count, rewrite));
        }
    }
    scored.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
    let Some((best_count, best)) = scored.first() else {
        return Ok(None);
    };
    // Co-occurrence and active filters decide ambiguity; alphabetical order
    // must never decide which spelling the user supposedly intended.
    if scored
        .get(1)
        .is_some_and(|(count, _)| *best_count < count.saturating_mul(4))
    {
        return Ok(None);
    }
    Ok(Some(SearchCorrection {
        original_query: request.query.clone(),
        corrected_query: best.clone(),
    }))
}

fn candidates(searcher: &Searcher, schema: &Schema, key: &str) -> Result<Vec<String>, SearchError> {
    static BUILDER: OnceLock<LevenshteinAutomatonBuilder> = OnceLock::new();
    let spelling = field(schema, FIELD);
    if searcher.search(&term_query(spelling, key), &Count)? > 0 {
        return Ok(vec![key.to_owned()]);
    }
    if key.chars().count() == 3 && key.chars().all(is_kana) {
        let mut live = Vec::new();
        for variant in super::reading::voicing_variants(&key.chars().collect::<Vec<_>>()) {
            let value: String = variant.into_iter().collect();
            if searcher.search(&term_query(spelling, &value), &Count)? > 0 {
                live.push(value);
            }
        }
        return Ok(live);
    }
    let builder = BUILDER.get_or_init(|| LevenshteinAutomatonBuilder::new(1, true));
    let mut candidates = BTreeSet::new();
    for segment in searcher.segment_readers() {
        let index = segment.inverted_index(spelling)?;
        let mut stream = index
            .terms()
            .search(Levenshtein(builder.build_dfa(key)))
            .into_stream()
            .map_err(tantivy::TantivyError::from)?;
        while stream.advance() {
            if let Ok(value) = std::str::from_utf8(stream.key()) {
                candidates.insert(value.to_owned());
                if candidates.len() > MAX_CANDIDATES {
                    return Ok(Vec::new());
                }
            }
        }
    }
    // Immutable segments can still contain deleted spellings. Counts consult
    // the live document set, as does full-query verification above.
    let mut live = Vec::new();
    for value in candidates {
        if searcher.search(&term_query(spelling, &value), &Count)? > 0 {
            live.push(value);
        }
    }
    Ok(live)
}

fn display_spelling(value: &str, original: &str) -> String {
    if original
        .chars()
        .any(|c| matches!(c, '\u{3041}'..='\u{3096}'))
    {
        value
            .chars()
            .map(|c| match c {
                '\u{30a1}'..='\u{30f6}' => char::from_u32(u32::from(c) - 0x60).unwrap_or(c),
                _ => c,
            })
            .collect()
    } else if original.chars().all(|c| c.is_ascii_uppercase()) {
        value.to_ascii_uppercase()
    } else if original.starts_with(|c: char| c.is_ascii_uppercase()) {
        let mut chars = value.chars();
        chars
            .next()
            .map(|c| c.to_ascii_uppercase())
            .into_iter()
            .chain(chars)
            .collect()
    } else {
        value.to_owned()
    }
}

struct Levenshtein(DFA);

impl Automaton for Levenshtein {
    type State = u32;
    fn start(&self) -> u32 {
        self.0.initial_state()
    }
    fn is_match(&self, state: &u32) -> bool {
        matches!(self.0.distance(*state), Distance::Exact(_))
    }
    fn can_match(&self, state: &u32) -> bool {
        *state != levenshtein_automata::SINK_STATE
    }
    fn accept(&self, state: &u32, byte: u8) -> u32 {
        self.0.transition(*state, byte)
    }
}
