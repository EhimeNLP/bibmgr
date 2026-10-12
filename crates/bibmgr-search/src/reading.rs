//! Verified reading retrieval. N-grams generate candidates, never final hits.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::sync::Arc;

use tantivy::fastfield::Column;
use tantivy::query::{
    BooleanQuery, EmptyQuery, EnableScoring, Explanation, Occur, Query, Scorer, TermQuery, Weight,
};
use tantivy::schema::{IndexRecordOption, Schema};
use tantivy::{DocId, DocSet, Score, SegmentReader, TantivyError, Term, TERMINATED};

use super::analysis::{is_kana, Analysis, Group};
use super::{field, Metadata};

pub(crate) const GRAM_FIELD: &str = "reading_grams";
const MAX_FUZZY_LENGTH: usize = 32;

#[derive(Debug, Default)]
pub(crate) struct Readings {
    pub surface_words: HashSet<String>,
    values: Vec<ReadingValue>,
}

#[derive(Debug)]
struct ReadingValue {
    canonical: String,
    runs: Vec<Vec<char>>,
    weight: Score,
}

impl Readings {
    pub fn add(&mut self, name: &str, analysis: &Analysis) {
        if name != "author_aliases" {
            for group in &analysis.groups {
                if let Group::Japanese { words, .. } = group {
                    self.surface_words.extend(words.iter().cloned());
                }
            }
        }
        let weight = match name {
            "title" => 5.0,
            "authors" | "author_aliases" => 3.0,
            "venues" => 2.0,
            _ => return,
        };
        if analysis.has_japanese() {
            let canonical = analysis.canonical_reading();
            let runs = japanese_runs(&canonical)
                .map(|run| run.chars().collect())
                .collect();
            self.values.push(ReadingValue {
                canonical,
                runs,
                weight,
            });
        }
    }

    pub fn grams(&self) -> String {
        let mut grams = BTreeSet::new();
        for value in &self.values {
            for run in &value.runs {
                // Unigrams cover short queries and four-character transpositions
                // that can destroy every bigram. Terms are deduplicated per doc.
                for size in 1..=2 {
                    grams.extend(
                        run.windows(size)
                            .map(|chars| chars.iter().collect::<String>()),
                    );
                }
            }
        }
        grams.into_iter().collect::<Vec<_>>().join(" ")
    }

    pub fn exact(&self, pattern: &Pattern) -> bool {
        self.values
            .iter()
            .any(|value| value.canonical.contains(&pattern.text))
    }

    fn score(&self, pattern: &Pattern) -> Option<Score> {
        // Even an exact venue reading outranks a fuzzy title reading. Check
        // all exact readings first to avoid edit work on common author names.
        let exact = self
            .values
            .iter()
            .filter(|value| value.canonical.contains(&pattern.text))
            .map(|value| value.weight * 0.6)
            .max_by(Score::total_cmp);
        if exact.is_some() || !pattern.fuzzy {
            return exact;
        }
        self.values
            .iter()
            .filter_map(|value| {
                if value.runs.iter().any(|run| pattern.matches_fuzzy(run)) {
                    Some(value.weight * 0.15)
                } else {
                    None
                }
            })
            .max_by(Score::total_cmp)
    }
}

fn japanese_runs(canonical: &str) -> impl Iterator<Item = &str> {
    // Odd components are Latin words; even components contain Japanese only.
    canonical
        .split('\0')
        .step_by(2)
        .filter(|run| !run.is_empty())
}

#[derive(Debug, Clone)]
pub(crate) struct Pattern {
    text: String,
    chars: Vec<char>,
    fuzzy: bool,
    short_forms: Vec<Vec<char>>,
}

impl Pattern {
    pub fn new(text: String, allow_fuzzy: bool) -> Self {
        let chars: Vec<_> = text.chars().collect();
        let fuzzy = allow_fuzzy
            && (3..=MAX_FUZZY_LENGTH).contains(&chars.len())
            && chars.iter().copied().all(is_kana);
        let short_forms = if fuzzy && chars.len() == 3 {
            voicing_variants(&chars)
        } else {
            Vec::new()
        };
        Self {
            text,
            chars,
            fuzzy,
            short_forms,
        }
    }

    fn matches_fuzzy(&self, text: &[char]) -> bool {
        if text.iter().any(|&c| !is_kana(c)) {
            return text
                .split(|&c| !is_kana(c))
                .any(|run| self.matches_fuzzy(run));
        }
        if self.chars.len() == 3 {
            return self
                .short_forms
                .iter()
                .any(|form| text.windows(3).any(|window| window == form));
        }
        within_one_edit(&self.chars, text)
    }

    fn candidate(&self, schema: &Schema) -> Box<dyn Query> {
        if self.fuzzy && self.chars.len() == 3 {
            // Voicing variants are finite; intersect their bigrams rather than
            // visiting every document sharing one common kana character.
            return Box::new(BooleanQuery::new(
                std::iter::once(&self.chars)
                    .chain(&self.short_forms)
                    .map(|form| {
                        (
                            Occur::Should,
                            Self::new(form.iter().collect(), false).candidate(schema),
                        )
                    })
                    .collect(),
            ));
        }
        let mut grams = BTreeSet::new();
        for run in japanese_runs(&self.text) {
            let chars: Vec<_> = run.chars().collect();
            let size = if self.fuzzy && self.chars.len() <= 4 {
                1
            } else {
                2.min(chars.len())
            };
            grams.extend(
                chars
                    .windows(size)
                    .map(|part| part.iter().collect::<String>()),
            );
        }
        if grams.is_empty() {
            return Box::new(EmptyQuery);
        }
        // A single edit destroys at most three bigrams (a transposition).
        // At length >= 5 at least one survives. No top-K candidate truncation.
        let occur = if self.fuzzy {
            Occur::Should
        } else {
            Occur::Must
        };
        Box::new(BooleanQuery::new(
            grams
                .into_iter()
                .map(|gram| {
                    (
                        occur,
                        Box::new(TermQuery::new(
                            Term::from_field_text(field(schema, GRAM_FIELD), &gram),
                            IndexRecordOption::Basic,
                        )) as Box<dyn Query>,
                    )
                })
                .collect(),
        ))
    }
}

pub(crate) fn voicing_variants(chars: &[char]) -> Vec<Vec<char>> {
    let groups = [
        "カガ",
        "キギ",
        "クグ",
        "ケゲ",
        "コゴ",
        "サザ",
        "シジ",
        "スズ",
        "セゼ",
        "ソゾ",
        "タダ",
        "チヂ",
        "ツヅ",
        "テデ",
        "トド",
        "ハバパ",
        "ヒビピ",
        "フブプ",
        "ヘベペ",
        "ホボポ",
        "ウヴ",
    ];
    let mut variants = Vec::new();
    for (i, &character) in chars.iter().enumerate() {
        for group in groups.iter().filter(|group| group.contains(character)) {
            for alternative in group.chars().filter(|&c| c != character) {
                let mut variant = chars.to_vec();
                variant[i] = alternative;
                variants.push(variant);
            }
        }
    }
    variants
}

/// Optimal-string-alignment distance against any contiguous substring.
/// Rows use fixed storage; only queries of at most 32 characters reach here.
fn within_one_edit(pattern: &[char], text: &[char]) -> bool {
    let mut previous_previous = [0u16; MAX_FUZZY_LENGTH + 1];
    let mut previous = [0u16; MAX_FUZZY_LENGTH + 1];
    for (i, value) in previous.iter_mut().enumerate().take(pattern.len() + 1) {
        *value = u16::try_from(i).expect("bounded query length");
    }
    let mut current = [0u16; MAX_FUZZY_LENGTH + 1];
    for (j, &character) in text.iter().enumerate() {
        current[0] = 0;
        for i in 1..=pattern.len() {
            current[i] = (previous[i] + 1)
                .min(current[i - 1] + 1)
                .min(previous[i - 1] + u16::from(pattern[i - 1] != character));
            if i > 1 && j > 0 && pattern[i - 1] == text[j - 1] && pattern[i - 2] == character {
                current[i] = current[i].min(previous_previous[i - 2] + 1);
            }
        }
        if current[pattern.len()] <= 1 {
            return true;
        }
        std::mem::swap(&mut previous_previous, &mut previous);
        std::mem::swap(&mut previous, &mut current);
    }
    false
}

#[derive(Debug)]
pub(crate) struct ReadingQuery {
    candidate: Box<dyn Query>,
    pattern: Arc<Pattern>,
    metadata: Arc<HashMap<u64, Arc<Metadata>>>,
}

impl ReadingQuery {
    pub fn new(
        schema: &Schema,
        pattern: Pattern,
        metadata: &Arc<HashMap<u64, Arc<Metadata>>>,
    ) -> Self {
        Self {
            candidate: pattern.candidate(schema),
            pattern: Arc::new(pattern),
            metadata: Arc::clone(metadata),
        }
    }
}

impl Clone for ReadingQuery {
    fn clone(&self) -> Self {
        Self {
            candidate: self.candidate.box_clone(),
            pattern: Arc::clone(&self.pattern),
            metadata: Arc::clone(&self.metadata),
        }
    }
}

impl Query for ReadingQuery {
    fn weight(&self, scoring: EnableScoring<'_>) -> tantivy::Result<Box<dyn Weight>> {
        Ok(Box::new(ReadingWeight {
            candidate: self
                .candidate
                .weight(EnableScoring::disabled_from_schema(scoring.schema()))?,
            pattern: Arc::clone(&self.pattern),
            metadata: Arc::clone(&self.metadata),
        }))
    }
}

struct ReadingWeight {
    candidate: Box<dyn Weight>,
    pattern: Arc<Pattern>,
    metadata: Arc<HashMap<u64, Arc<Metadata>>>,
}

impl Weight for ReadingWeight {
    fn scorer(&self, reader: &SegmentReader, boost: Score) -> tantivy::Result<Box<dyn Scorer>> {
        let mut scorer = ReadingScorer {
            candidate: self.candidate.scorer(reader, 1.0)?,
            ordinals: reader.fast_fields().u64("ordinal")?,
            pattern: Arc::clone(&self.pattern),
            metadata: Arc::clone(&self.metadata),
            boost,
            score: 0.0,
        };
        scorer.skip_unverified();
        Ok(Box::new(scorer))
    }

    fn explain(&self, reader: &SegmentReader, doc: DocId) -> tantivy::Result<Explanation> {
        let mut scorer = self.scorer(reader, 1.0)?;
        if scorer.seek(doc) != doc {
            return Err(TantivyError::InvalidArgument(format!(
                "Document {doc} does not match the reading"
            )));
        }
        Ok(Explanation::new(
            "Verified Japanese reading",
            scorer.score(),
        ))
    }
}

struct ReadingScorer {
    candidate: Box<dyn Scorer>,
    ordinals: Column<u64>,
    pattern: Arc<Pattern>,
    metadata: Arc<HashMap<u64, Arc<Metadata>>>,
    boost: Score,
    score: Score,
}

impl ReadingScorer {
    fn skip_unverified(&mut self) -> DocId {
        while self.candidate.doc() != TERMINATED {
            // Deleted ordinals may remain in immutable segment postings.
            let score = self
                .ordinals
                .first(self.candidate.doc())
                .and_then(|ordinal| self.metadata.get(&ordinal))
                .and_then(|data| data.readings.score(&self.pattern));
            if let Some(score) = score {
                self.score = score * self.boost;
                break;
            }
            self.candidate.advance();
        }
        self.candidate.doc()
    }
}

impl DocSet for ReadingScorer {
    fn advance(&mut self) -> DocId {
        self.candidate.advance();
        self.skip_unverified()
    }
    fn seek(&mut self, target: DocId) -> DocId {
        self.candidate.seek(target);
        self.skip_unverified()
    }
    fn doc(&self) -> DocId {
        self.candidate.doc()
    }
    fn size_hint(&self) -> u32 {
        self.candidate.size_hint()
    }
}

impl Scorer for ReadingScorer {
    fn score(&mut self) -> Score {
        self.score
    }
}
