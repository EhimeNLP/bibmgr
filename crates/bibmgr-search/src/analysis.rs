//! Shared surface and reading analysis. Latin words never enter the segmenter.

use std::sync::OnceLock;

use super::{normalize, tokenizer, SearchError};

#[derive(Debug, Clone)]
pub(crate) enum Group {
    Word(String),
    Japanese { words: Vec<String>, reading: String },
}

#[derive(Debug, Default)]
pub(crate) struct Analysis {
    pub groups: Vec<Group>,
}

impl Analysis {
    pub fn words(&self) -> Vec<String> {
        self.groups
            .iter()
            .flat_map(|group| match group {
                Group::Word(word) => std::slice::from_ref(word),
                Group::Japanese { words, .. } => words.as_slice(),
            })
            .cloned()
            .collect()
    }

    /// Delimit non-Japanese words so phrase checks cannot match part of GPT2,
    /// cross a Latin word, or depend on Japanese morphological boundaries.
    pub fn canonical_reading(&self) -> String {
        let mut result = String::new();
        for group in &self.groups {
            match group {
                Group::Word(word) => {
                    result.push('\0');
                    result.push_str(word);
                    result.push('\0');
                }
                Group::Japanese { reading, .. } => result.push_str(reading),
            }
        }
        result
    }

    pub fn has_japanese(&self) -> bool {
        self.groups
            .iter()
            .any(|group| matches!(group, Group::Japanese { .. }))
    }
}

pub(crate) fn analyze(text: &str) -> Result<Analysis, SearchError> {
    static JAPANESE: OnceLock<regex::Regex> = OnceLock::new();
    let japanese = JAPANESE.get_or_init(|| {
        regex::Regex::new(r"[\p{Han}\p{Hiragana}\p{Katakana}ー]+")
            .expect("valid Japanese script pattern")
    });
    let normalized = normalize(text);
    let mut result = Analysis::default();
    let mut end = 0;
    for span in japanese.find_iter(&normalized) {
        append_words(&mut result, &normalized[end..span.start()]);
        let mut words = Vec::new();
        let mut reading = String::new();
        for mut token in tokenizer()?
            .segment(span.as_str().into())
            .map_err(|error| SearchError::Tokenizer(error.to_string()))?
        {
            words.extend(split_words(&token.text).map(str::to_owned));
            // Preserve literal kana, including misspellings and particles.
            // Unknown kanji keep their surface; never invent a pronunciation.
            let surface = katakana(&token.text);
            let value = if surface.chars().all(is_kana) {
                surface
            } else {
                token
                    .get_detail(7)
                    .filter(|value| !value.is_empty() && value.chars().all(is_kana))
                    .map_or(surface, katakana)
            };
            reading.extend(value.chars().filter(|c| c.is_alphanumeric() || *c == 'ー'));
        }
        if !words.is_empty() {
            result.groups.push(Group::Japanese { words, reading });
        }
        end = span.end();
    }
    append_words(&mut result, &normalized[end..]);
    Ok(result)
}

fn split_words(text: &str) -> impl Iterator<Item = &str> {
    text.split(|c: char| !c.is_alphanumeric())
        .filter(|word| !word.is_empty())
}

fn append_words(result: &mut Analysis, text: &str) {
    result
        .groups
        .extend(split_words(text).map(|word| Group::Word(word.to_owned())));
}

fn katakana(text: &str) -> String {
    text.chars()
        .map(|c| match c {
            '\u{3041}'..='\u{3096}' | '\u{309d}'..='\u{309e}' => {
                char::from_u32(u32::from(c) + 0x60).expect("hiragana has katakana counterpart")
            }
            _ => c,
        })
        .collect()
}

pub(crate) fn is_kana(c: char) -> bool {
    matches!(c, '\u{3041}'..='\u{3096}' | '\u{30a1}'..='\u{30fa}' | 'ー')
}
