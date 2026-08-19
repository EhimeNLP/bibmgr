//! Atomic, source-preserving application of [`bibmgr_model::TextEdit`] values.
//!
//! This crate deliberately knows nothing about BibTeX syntax. It applies edits
//! produced by validation while preserving every byte outside their ranges.

use bibmgr_model::{Fix, FixApplicability, FixId, SourceRevision, TextEdit, TextRange};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

/// Which fixes from an analysis should be included in a plan.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(tag = "kind", content = "fix_ids", rename_all = "snake_case")]
pub enum FixSelection {
    /// Every fix explicitly marked safe.
    #[default]
    AllSafe,
    /// Every available fix, including unsafe fixes.
    All,
    /// Exactly these fix identifiers.
    Ids(Vec<FixId>),
}

/// A checked, deterministic collection of edits targeting one source revision.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FixPlan {
    pub source_revision: SourceRevision,
    /// Sorted fix identifiers included in this plan.
    pub fixes: Vec<FixId>,
    /// Edits sorted by `(start, end, replacement)` for stable serialization.
    pub edits: Vec<TextEdit>,
}

impl FixPlan {
    pub fn is_empty(&self) -> bool {
        self.edits.is_empty()
    }
}

/// A pair of fixes whose edit sets cannot be applied atomically.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FixConflict {
    pub first_fix: FixId,
    pub second_fix: FixId,
    pub first_range: TextRange,
    pub second_range: TextRange,
}

/// Result of applying a checked plan.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ApplyFixResult {
    pub source: String,
    pub source_revision: SourceRevision,
    pub applied_fix_ids: Vec<FixId>,
    /// A deterministic unified-style preview. Empty when the source is unchanged.
    pub diff: String,
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum FixPlanError {
    #[error("fix selection contains the duplicate id `{0}`")]
    DuplicateSelection(FixId),
    #[error("selected fix `{0}` does not exist")]
    UnknownFix(FixId),
    #[error("available fixes contain duplicate id `{0}`")]
    DuplicateAvailableFix(FixId),
    #[error("fix `{fix_id}` targets revision {actual}, not requested revision {expected}")]
    RevisionMismatch {
        fix_id: FixId,
        expected: SourceRevision,
        actual: SourceRevision,
    },
    #[error("fix `{fix_id}` contains an invalid range {start}..{end}")]
    InvalidRange { fix_id: FixId, start: u32, end: u32 },
    #[error("fix `{fix_id}` contains overlapping edits")]
    InternalOverlap { fix_id: FixId },
    #[error("selected fixes `{first}` and `{second}` conflict")]
    Conflict { first: FixId, second: FixId },
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum EditError {
    #[error("fix plan is stale: expected {expected}, got {actual}")]
    StaleRevision {
        expected: SourceRevision,
        actual: SourceRevision,
    },
    #[error("edit range {start}..{end} is reversed")]
    ReversedRange { start: u32, end: u32 },
    #[error("edit range {start}..{end} exceeds the {source_len}-byte source")]
    OutOfBounds {
        start: u32,
        end: u32,
        source_len: usize,
    },
    #[error("edit offset {offset} is not a UTF-8 character boundary")]
    InvalidUtf8Boundary { offset: u32 },
    #[error("edits {first_start}..{first_end} and {second_start}..{second_end} overlap")]
    OverlappingEdits {
        first_start: u32,
        first_end: u32,
        second_start: u32,
        second_end: u32,
    },
}

/// Build a deterministic edit plan and reject unknown, stale, or conflicting fixes.
pub fn plan_fixes(
    source_revision: &SourceRevision,
    available_fixes: &[Fix],
    selection: &FixSelection,
) -> Result<FixPlan, FixPlanError> {
    let mut by_id = BTreeMap::new();
    for fix in available_fixes {
        if by_id.insert(fix.id.clone(), fix).is_some() {
            return Err(FixPlanError::DuplicateAvailableFix(fix.id.clone()));
        }
    }

    let selected_ids = select_ids(&by_id, selection)?;
    let mut selected = Vec::with_capacity(selected_ids.len());
    for id in &selected_ids {
        let fix = by_id
            .get(id)
            .copied()
            .ok_or_else(|| FixPlanError::UnknownFix(id.clone()))?;
        if &fix.source_revision != source_revision {
            return Err(FixPlanError::RevisionMismatch {
                fix_id: fix.id.clone(),
                expected: source_revision.clone(),
                actual: fix.source_revision.clone(),
            });
        }
        validate_fix_ranges(fix)?;
        selected.push(fix);
    }

    if let Some(conflict) = detect_conflicts_in(&selected).into_iter().next() {
        return Err(FixPlanError::Conflict {
            first: conflict.first_fix,
            second: conflict.second_fix,
        });
    }

    let mut edits: Vec<_> = selected
        .iter()
        .flat_map(|fix| fix.edits.iter().cloned())
        .collect();
    sort_edits(&mut edits);

    Ok(FixPlan {
        source_revision: source_revision.clone(),
        fixes: selected_ids,
        edits,
    })
}

/// Return all pairwise fix conflicts in stable identifier/range order.
pub fn detect_conflicts(fixes: &[Fix]) -> Vec<FixConflict> {
    let mut ordered: Vec<_> = fixes.iter().collect();
    ordered.sort_by(|left, right| left.id.cmp(&right.id));
    detect_conflicts_in(&ordered)
}

/// Apply every edit atomically after rechecking revision, bounds, UTF-8, and overlap.
pub fn apply_fix_plan(source: &str, plan: &FixPlan) -> Result<ApplyFixResult, EditError> {
    let actual_revision = SourceRevision::of(source);
    if actual_revision != plan.source_revision {
        return Err(EditError::StaleRevision {
            expected: plan.source_revision.clone(),
            actual: actual_revision,
        });
    }

    let mut edits = plan.edits.clone();
    sort_edits(&mut edits);
    validate_edits_for_source(source, &edits)?;

    let mut output = source.to_owned();
    for edit in edits.iter().rev() {
        let start = edit.range.start as usize;
        let end = edit.range.end as usize;
        output.replace_range(start..end, &edit.replacement);
    }

    let source_revision = SourceRevision::of(&output);
    let diff = unified_diff(source, &output);
    Ok(ApplyFixResult {
        source: output,
        source_revision,
        applied_fix_ids: plan.fixes.clone(),
        diff,
    })
}

/// Produce the same deterministic diff used by [`apply_fix_plan`].
pub fn unified_diff(before: &str, after: &str) -> String {
    if before == after {
        return String::new();
    }

    let before_lines: Vec<_> = before.split_inclusive('\n').collect();
    let after_lines: Vec<_> = after.split_inclusive('\n').collect();
    let prefix = before_lines
        .iter()
        .zip(&after_lines)
        .take_while(|(left, right)| left == right)
        .count();
    let suffix = before_lines[prefix..]
        .iter()
        .rev()
        .zip(after_lines[prefix..].iter().rev())
        .take_while(|(left, right)| left == right)
        .count();
    let before_end = before_lines.len().saturating_sub(suffix);
    let after_end = after_lines.len().saturating_sub(suffix);
    let old_count = before_end.saturating_sub(prefix);
    let new_count = after_end.saturating_sub(prefix);

    let mut diff = format!(
        "--- before\n+++ after\n@@ -{},{} +{},{} @@\n",
        prefix + 1,
        old_count,
        prefix + 1,
        new_count
    );
    for line in &before_lines[prefix..before_end] {
        push_diff_line(&mut diff, '-', line);
    }
    for line in &after_lines[prefix..after_end] {
        push_diff_line(&mut diff, '+', line);
    }
    diff
}

fn select_ids(
    by_id: &BTreeMap<FixId, &Fix>,
    selection: &FixSelection,
) -> Result<Vec<FixId>, FixPlanError> {
    match selection {
        FixSelection::AllSafe => Ok(by_id
            .values()
            .filter(|fix| fix.applicability == FixApplicability::Safe)
            .map(|fix| fix.id.clone())
            .collect()),
        FixSelection::All => Ok(by_id.keys().cloned().collect()),
        FixSelection::Ids(ids) => {
            let mut seen = BTreeSet::new();
            for id in ids {
                if !seen.insert(id.clone()) {
                    return Err(FixPlanError::DuplicateSelection(id.clone()));
                }
                if !by_id.contains_key(id) {
                    return Err(FixPlanError::UnknownFix(id.clone()));
                }
            }
            Ok(seen.into_iter().collect())
        }
    }
}

fn validate_fix_ranges(fix: &Fix) -> Result<(), FixPlanError> {
    for edit in &fix.edits {
        if !edit.range.is_valid() {
            return Err(FixPlanError::InvalidRange {
                fix_id: fix.id.clone(),
                start: edit.range.start,
                end: edit.range.end,
            });
        }
    }
    let mut edits = fix.edits.clone();
    sort_edits(&mut edits);
    for pair in edits.windows(2) {
        if edits_conflict(&pair[0], &pair[1]) {
            return Err(FixPlanError::InternalOverlap {
                fix_id: fix.id.clone(),
            });
        }
    }
    Ok(())
}

fn detect_conflicts_in(fixes: &[&Fix]) -> Vec<FixConflict> {
    let mut conflicts = Vec::new();
    for (index, first) in fixes.iter().enumerate() {
        for second in fixes.iter().skip(index + 1) {
            for first_edit in &first.edits {
                for second_edit in &second.edits {
                    if edits_conflict(first_edit, second_edit) {
                        conflicts.push(FixConflict {
                            first_fix: first.id.clone(),
                            second_fix: second.id.clone(),
                            first_range: first_edit.range,
                            second_range: second_edit.range,
                        });
                    }
                }
            }
        }
    }
    conflicts.sort_by(|left, right| {
        (
            &left.first_fix,
            &left.second_fix,
            left.first_range,
            left.second_range,
        )
            .cmp(&(
                &right.first_fix,
                &right.second_fix,
                right.first_range,
                right.second_range,
            ))
    });
    conflicts
}

fn validate_edits_for_source(source: &str, edits: &[TextEdit]) -> Result<(), EditError> {
    for edit in edits {
        let start = edit.range.start;
        let end = edit.range.end;
        if start > end {
            return Err(EditError::ReversedRange { start, end });
        }
        if end as usize > source.len() {
            return Err(EditError::OutOfBounds {
                start,
                end,
                source_len: source.len(),
            });
        }
        if !source.is_char_boundary(start as usize) {
            return Err(EditError::InvalidUtf8Boundary { offset: start });
        }
        if !source.is_char_boundary(end as usize) {
            return Err(EditError::InvalidUtf8Boundary { offset: end });
        }
    }
    for pair in edits.windows(2) {
        if edits_conflict(&pair[0], &pair[1]) {
            return Err(EditError::OverlappingEdits {
                first_start: pair[0].range.start,
                first_end: pair[0].range.end,
                second_start: pair[1].range.start,
                second_end: pair[1].range.end,
            });
        }
    }
    Ok(())
}

fn edits_conflict(left: &TextEdit, right: &TextEdit) -> bool {
    let left_range = left.range;
    let right_range = right.range;
    if left_range.overlaps(right_range) {
        return true;
    }
    if left_range.is_empty() && right_range.is_empty() {
        return left_range.start == right_range.start;
    }
    if left_range.is_empty() {
        return right_range.start <= left_range.start && left_range.start <= right_range.end;
    }
    if right_range.is_empty() {
        return left_range.start <= right_range.start && right_range.start <= left_range.end;
    }
    false
}

fn sort_edits(edits: &mut [TextEdit]) {
    edits.sort_by(|left, right| {
        (left.range.start, left.range.end, &left.replacement).cmp(&(
            right.range.start,
            right.range.end,
            &right.replacement,
        ))
    });
}

fn push_diff_line(output: &mut String, marker: char, line: &str) {
    output.push(marker);
    output.push_str(line);
    if !line.ends_with('\n') {
        output.push('\n');
        output.push_str("\\ No newline at end of file\n");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    fn fix(id: &str, source: &str, range: TextRange, replacement: &str) -> Fix {
        Fix {
            id: FixId::new(id),
            title: id.to_owned(),
            applicability: FixApplicability::Safe,
            source_revision: SourceRevision::of(source),
            edits: vec![TextEdit {
                range,
                replacement: replacement.to_owned(),
            }],
        }
    }

    #[test]
    fn applies_multiple_edits_without_touching_other_bytes() {
        let source = "@misc{k,\r\n  TITLE = {old},\r\n}\r\n% keep\r\n";
        let revision = SourceRevision::of(source);
        let title_start = source.find("TITLE").unwrap();
        let old_start = source.find("old").unwrap();
        let fixes = vec![
            fix(
                "a",
                source,
                TextRange::checked(title_start, title_start + "TITLE".len()).unwrap(),
                "title",
            ),
            fix(
                "b",
                source,
                TextRange::checked(old_start, old_start + "old".len()).unwrap(),
                "new",
            ),
        ];
        let plan = plan_fixes(&revision, &fixes, &FixSelection::AllSafe).unwrap();
        let result = apply_fix_plan(source, &plan).unwrap();
        assert_eq!(
            result.source,
            "@misc{k,\r\n  title = {new},\r\n}\r\n% keep\r\n"
        );
        assert!(result.source.ends_with("% keep\r\n"));
    }

    #[test]
    fn rejects_stale_source_before_touching_it() {
        let fix = fix("a", "old", TextRange::new(0, 3), "new");
        let plan = plan_fixes(&SourceRevision::of("old"), &[fix], &FixSelection::AllSafe).unwrap();
        assert!(matches!(
            apply_fix_plan("changed", &plan),
            Err(EditError::StaleRevision { .. })
        ));
    }

    #[test]
    fn rejects_utf8_split() {
        let source = "a著b";
        let plan = FixPlan {
            source_revision: SourceRevision::of(source),
            fixes: vec![],
            edits: vec![TextEdit {
                range: TextRange::new(2, 3),
                replacement: "x".to_owned(),
            }],
        };
        assert_eq!(
            apply_fix_plan(source, &plan),
            Err(EditError::InvalidUtf8Boundary { offset: 2 })
        );
    }

    #[test]
    fn detects_cross_fix_overlap_deterministically() {
        let source = "abcdef";
        let fixes = vec![
            fix("z", source, TextRange::new(1, 4), "x"),
            fix("a", source, TextRange::new(3, 5), "y"),
        ];
        let conflicts = detect_conflicts(&fixes);
        assert_eq!(conflicts[0].first_fix, FixId::new("a"));
        assert_eq!(conflicts[0].second_fix, FixId::new("z"));
        assert!(matches!(
            plan_fixes(
                &SourceRevision::of(source),
                &fixes,
                &FixSelection::AllSafe
            ),
            Err(FixPlanError::Conflict { first, second })
                if first == FixId::new("a") && second == FixId::new("z")
        ));
    }

    #[test]
    fn same_offset_insertions_conflict() {
        let source = "ab";
        let fixes = vec![
            fix("a", source, TextRange::new(1, 1), "x"),
            fix("b", source, TextRange::new(1, 1), "y"),
        ];
        assert_eq!(detect_conflicts(&fixes).len(), 1);
    }

    #[test]
    fn safe_selection_omits_confirmation_and_unsafe_fixes() {
        let source = "abc";
        let mut confirmation = fix("confirmation", source, TextRange::new(0, 1), "A");
        confirmation.applicability = FixApplicability::RequiresConfirmation;
        let mut unsafe_fix = fix("unsafe", source, TextRange::new(1, 2), "B");
        unsafe_fix.applicability = FixApplicability::Unsafe;
        let safe = fix("safe", source, TextRange::new(2, 3), "C");
        let plan = plan_fixes(
            &SourceRevision::of(source),
            &[confirmation, unsafe_fix, safe],
            &FixSelection::AllSafe,
        )
        .unwrap();
        assert_eq!(plan.fixes, vec![FixId::new("safe")]);
    }

    #[test]
    fn explicit_ids_are_sorted_but_duplicate_selection_is_rejected() {
        let source = "ab";
        let fixes = vec![
            fix("b", source, TextRange::new(1, 2), "B"),
            fix("a", source, TextRange::new(0, 1), "A"),
        ];
        let revision = SourceRevision::of(source);
        let plan = plan_fixes(
            &revision,
            &fixes,
            &FixSelection::Ids(vec![FixId::new("b"), FixId::new("a")]),
        )
        .unwrap();
        assert_eq!(plan.fixes, vec![FixId::new("a"), FixId::new("b")]);
        assert!(matches!(
            plan_fixes(
                &revision,
                &fixes,
                &FixSelection::Ids(vec![FixId::new("a"), FixId::new("a")])
            ),
            Err(FixPlanError::DuplicateSelection(_))
        ));
    }

    #[test]
    fn unchanged_replacement_is_idempotent_and_has_no_diff() {
        let source = "abc";
        let fixes = [fix("same", source, TextRange::new(1, 2), "b")];
        let plan = plan_fixes(&SourceRevision::of(source), &fixes, &FixSelection::AllSafe).unwrap();
        let first = apply_fix_plan(source, &plan).unwrap();
        let second = apply_fix_plan(&first.source, &plan).unwrap();
        assert_eq!(first.source, second.source);
        assert!(first.diff.is_empty());
    }

    #[test]
    fn diff_keeps_context_outside_changed_hunk() {
        let diff = unified_diff("keep\nold\ntail\n", "keep\nnew\ntail\n");
        assert_eq!(diff, "--- before\n+++ after\n@@ -2,1 +2,1 @@\n-old\n+new\n");
    }

    proptest! {
        #[test]
        fn replacing_valid_ascii_subrange_never_panics(
            source in "[ -~]{0,128}",
            replacement in "[ -~]{0,32}",
            first in any::<usize>(),
            second in any::<usize>(),
        ) {
            let len = source.len();
            let start = if len == 0 { 0 } else { first % (len + 1) };
            let end_seed = if len == 0 { 0 } else { second % (len + 1) };
            let end = start.max(end_seed);
            let fix = fix(
                "property",
                &source,
                TextRange::checked(start, end).unwrap(),
                &replacement,
            );
            let plan = plan_fixes(
                &SourceRevision::of(&source),
                &[fix],
                &FixSelection::AllSafe,
            ).unwrap();
            let result = apply_fix_plan(&source, &plan).unwrap();
            prop_assert_eq!(
                result.source,
                format!("{}{}{}", &source[..start], replacement, &source[end..])
            );
        }
    }
}
