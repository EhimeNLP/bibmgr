//! Deployment-independent duplicate policy and batch comparison API.
use crate::{compare_records, ComparisonRecord, DuplicateComparison, DuplicateKind};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum DuplicateAction {
    Ignore,
    #[default]
    Warn,
    Confirm,
    Reject,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct DuplicatePolicy {
    pub identifier: DuplicateAction,
    pub arxiv_family: DuplicateAction,
    pub corroborated_title: DuplicateAction,
    pub title: DuplicateAction,
    pub citation_key: DuplicateAction,
}

impl Default for DuplicatePolicy {
    fn default() -> Self {
        Self {
            identifier: DuplicateAction::Reject,
            arxiv_family: DuplicateAction::Warn,
            corroborated_title: DuplicateAction::Warn,
            title: DuplicateAction::Warn,
            citation_key: DuplicateAction::Warn,
        }
    }
}

impl DuplicatePolicy {
    pub fn action(&self, kind: DuplicateKind) -> DuplicateAction {
        match kind {
            DuplicateKind::Identifier => self.identifier,
            DuplicateKind::ArxivFamily => self.arxiv_family,
            DuplicateKind::CorroboratedTitle => self.corroborated_title,
            DuplicateKind::Title => self.title,
            DuplicateKind::CitationKey => self.citation_key,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DuplicateFinding {
    pub incoming_index: usize,
    /// An earlier incoming record if `existing` is false; otherwise a candidate index.
    pub candidate_index: usize,
    pub existing: bool,
    pub action: DuplicateAction,
    pub comparison: DuplicateComparison,
}

#[derive(Debug, thiserror::Error)]
pub enum DuplicateAssessmentError {
    #[error("Too many duplicate candidates; submit a smaller batch")]
    Limit,
    #[error("Unsupported comparison data version")]
    Version,
}

fn keys(record: &ComparisonRecord) -> Vec<(u8, String)> {
    let mut result = Vec::new();
    if !record.citation_key.is_empty() {
        result.push((0, record.citation_key.clone()));
    }
    if let Some(title) = &record.title {
        result.push((1, title.clone()));
    }
    result.extend(record.dois.iter().map(|id| (2, id.clone())));
    result.extend(record.arxiv_families.iter().map(|id| (3, id.clone())));
    result
}

pub fn assess_duplicates(
    incoming: &[ComparisonRecord],
    candidates: &[ComparisonRecord],
    policy: &DuplicatePolicy,
) -> Result<Vec<DuplicateFinding>, DuplicateAssessmentError> {
    use std::collections::{BTreeMap, BTreeSet};
    if incoming
        .iter()
        .chain(candidates)
        .any(|r| r.version != bibmgr_semantics::duplicates::COMPARISON_VERSION)
    {
        return Err(DuplicateAssessmentError::Version);
    }
    let mut index = BTreeMap::<(u8, String), Vec<(bool, usize)>>::new();
    for (j, candidate) in candidates.iter().enumerate() {
        for key in keys(candidate) {
            index.entry(key).or_default().push((true, j));
        }
    }
    let mut findings = Vec::new();
    let mut comparisons = 0;
    for (i, record) in incoming.iter().enumerate() {
        let record_keys = keys(record);
        let matches: BTreeSet<_> = record_keys
            .iter()
            .filter_map(|key| index.get(key))
            .flatten()
            .copied()
            .collect();
        for (existing, j) in matches {
            comparisons += 1;
            if comparisons > 1000 {
                return Err(DuplicateAssessmentError::Limit);
            }
            let candidate = if existing {
                &candidates[j]
            } else {
                &incoming[j]
            };
            if let Some(comparison) = compare_records(record, candidate) {
                let action = policy.action(comparison.kind);
                if action != DuplicateAction::Ignore {
                    findings.push(DuplicateFinding {
                        incoming_index: i,
                        candidate_index: j,
                        existing,
                        action,
                        comparison,
                    });
                }
            }
        }
        for key in record_keys {
            index.entry(key).or_default().push((false, i));
        }
    }
    Ok(findings)
}
