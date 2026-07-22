//! Stable, parser-independent data transfer types shared by every bibmgr adapter.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fmt;

/// Version of JSON and Python DTOs returned by this workspace.
pub const SCHEMA_VERSION: &str = "1";

macro_rules! string_id {
    ($name:ident) => {
        #[derive(
            Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize, Default,
        )]
        #[serde(transparent)]
        pub struct $name(pub String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Self {
                Self(value.into())
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str(&self.0)
            }
        }

        impl From<&str> for $name {
            fn from(value: &str) -> Self {
                Self(value.to_owned())
            }
        }

        impl From<String> for $name {
            fn from(value: String) -> Self {
                Self(value)
            }
        }
    };
}

string_id!(SourceId);
string_id!(DiagnosticId);
string_id!(RuleCode);
string_id!(FixId);
string_id!(ProfileId);

/// Half-open UTF-8 byte range in the original source.
#[derive(
    Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize, Default,
)]
pub struct TextRange {
    pub start: u32,
    pub end: u32,
}

impl TextRange {
    pub const fn new(start: u32, end: u32) -> Self {
        Self { start, end }
    }

    pub const fn is_valid(self) -> bool {
        self.start <= self.end
    }

    pub const fn is_empty(self) -> bool {
        self.start == self.end
    }

    pub const fn len(self) -> u32 {
        self.end.saturating_sub(self.start)
    }

    pub const fn overlaps(self, other: Self) -> bool {
        self.start < other.end && other.start < self.end
    }

    pub const fn contains(self, offset: u32) -> bool {
        self.start <= offset && offset < self.end
    }

    pub fn checked(start: usize, end: usize) -> Result<Self, RangeError> {
        if start > end {
            return Err(RangeError::Reversed { start, end });
        }
        let start = u32::try_from(start).map_err(|_| RangeError::TooLarge { offset: start })?;
        let end = u32::try_from(end).map_err(|_| RangeError::TooLarge { offset: end })?;
        Ok(Self { start, end })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum RangeError {
    #[error("range start {start} is after end {end}")]
    Reversed { start: usize, end: usize },
    #[error("source offset {offset} exceeds the u32 source model")]
    TooLarge { offset: usize },
}

/// A byte range associated with a logical input source.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct SourceLocation {
    pub source_id: SourceId,
    pub range: TextRange,
}

impl SourceLocation {
    pub fn new(source_id: impl Into<SourceId>, range: TextRange) -> Self {
        Self {
            source_id: source_id.into(),
            range,
        }
    }
}

/// Display position derived from a byte range; never used as an edit coordinate.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct LineColumn {
    pub line: u32,
    pub column: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RelatedLocation {
    pub message: String,
    pub location: SourceLocation,
}

#[derive(
    Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize, Default,
)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    #[default]
    Error,
    Warning,
    Information,
    Hint,
}

impl Severity {
    pub const fn rank(self) -> u8 {
        match self {
            Self::Error => 3,
            Self::Warning => 2,
            Self::Information => 1,
            Self::Hint => 0,
        }
    }

    /// Returns whether this severity is at least as serious as `minimum`.
    pub const fn meets(self, minimum: Self) -> bool {
        self.rank() >= minimum.rank()
    }
}

/// A deterministic, frontend-neutral validation result.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Diagnostic {
    pub id: DiagnosticId,
    pub code: RuleCode,
    pub severity: Severity,
    pub blocking: bool,
    pub message: String,
    pub primary_location: Option<SourceLocation>,
    #[serde(default)]
    pub related_locations: Vec<RelatedLocation>,
    #[serde(default)]
    pub notes: Vec<String>,
    #[serde(default)]
    pub fixes: Vec<FixId>,
}

impl Diagnostic {
    pub fn new(
        id: impl Into<DiagnosticId>,
        code: impl Into<RuleCode>,
        severity: Severity,
        blocking: bool,
        message: impl Into<String>,
        primary_location: Option<SourceLocation>,
    ) -> Self {
        Self {
            id: id.into(),
            code: code.into(),
            severity,
            blocking,
            message: message.into(),
            primary_location,
            related_locations: Vec::new(),
            notes: Vec::new(),
            fixes: Vec::new(),
        }
    }

    /// Key used by adapters to retain a deterministic source-first ordering.
    pub fn sort_key(&self) -> (u32, u32, &str, &str) {
        let range = self
            .primary_location
            .as_ref()
            .map_or(TextRange::new(u32::MAX, u32::MAX), |location| {
                location.range
            });
        (range.start, range.end, self.code.as_str(), self.id.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FixApplicability {
    Safe,
    RequiresConfirmation,
    Unsafe,
}

/// A replacement against a half-open UTF-8 byte range.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TextEdit {
    pub range: TextRange,
    pub replacement: String,
}

/// Content-addressed source revision used to reject stale fixes.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct SourceRevision(pub String);

impl SourceRevision {
    pub fn of(source: &str) -> Self {
        let digest = Sha256::digest(source.as_bytes());
        Self(format!("sha256:{digest:x}"))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for SourceRevision {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

/// An atomic group of edits that all target the same source revision.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Fix {
    pub id: FixId,
    pub title: String,
    pub applicability: FixApplicability,
    pub source_revision: SourceRevision,
    pub edits: Vec<TextEdit>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn revision_is_stable_and_content_addressed() {
        assert_eq!(SourceRevision::of("same"), SourceRevision::of("same"));
        assert_ne!(SourceRevision::of("same"), SourceRevision::of("different"));
    }

    #[test]
    fn half_open_overlap_ignores_touching_edits() {
        assert!(TextRange::new(1, 4).overlaps(TextRange::new(3, 5)));
        assert!(!TextRange::new(1, 4).overlaps(TextRange::new(4, 5)));
    }
}
