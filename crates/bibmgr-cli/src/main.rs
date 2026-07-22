use bibmgr_core::{
    analyze, apply_fix_plan_with_options, apply_safe_fixes, export_source, plan_fixes,
    AnalysisOptions, Diagnostic, ExportError, ExportProfile, FixApplicability, FixId, FixSelection,
    ParseMode, ParseOptions, ProfileId, Severity, ValidationPolicy, SCHEMA_VERSION,
};
use clap::{ArgAction, ArgGroup, Parser, Subcommand, ValueEnum};
use rayon::prelude::*;
use serde::Serialize;
use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};

const EXIT_OK: i32 = 0;
const EXIT_BLOCKING: i32 = 1;
const EXIT_USAGE_OR_IO: i32 = 2;
const EXIT_INTERNAL: i32 = 3;

#[derive(Debug, Parser)]
#[command(
    name = "bibmgr",
    version,
    about = "Lossless BibTeX analysis and export"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Analyze one or more BibTeX documents without modifying them.
    Lint {
        #[arg(required = true)]
        files: Vec<PathBuf>,
        #[arg(long, value_enum, default_value_t = OutputFormat::Human)]
        format: OutputFormat,
        #[arg(long, default_value = "laboratory")]
        profile: String,
        /// Recover partial entries instead of using strict parsing.
        #[arg(long)]
        tolerant: bool,
    },
    /// Apply source-preserving fixes to a BibTeX document.
    Fix {
        file: PathBuf,
        /// Restrict selection to fixes proven semantics-preserving.
        #[arg(long)]
        safe: bool,
        /// Print the diff but do not replace the file.
        #[arg(long)]
        dry_run: bool,
        /// Apply exactly these fix identifiers (repeatable).
        #[arg(long = "fix-id", action = ArgAction::Append, requires = "source_revision")]
        fix_ids: Vec<String>,
        /// Revision returned by the analysis that produced explicit fix IDs.
        #[arg(long, requires = "fix_ids")]
        source_revision: Option<String>,
        #[arg(long, default_value = "laboratory")]
        profile: String,
        #[arg(long, value_enum, default_value_t = OutputFormat::Human)]
        format: OutputFormat,
    },
    /// Generate fresh BibTeX from the semantic bibliography.
    Export {
        file: PathBuf,
        #[arg(long, default_value = "laboratory")]
        profile: String,
        #[arg(long, value_enum, default_value_t = OutputFormat::Human)]
        format: OutputFormat,
        #[arg(short, long)]
        output: Option<PathBuf>,
    },
    /// Inspect an internal, parser-independent snapshot.
    #[command(group(
        ArgGroup::new("view")
            .required(true)
            .multiple(false)
            .args(["ast", "cst"])
    ))]
    Inspect {
        file: PathBuf,
        #[arg(long)]
        ast: bool,
        #[arg(long)]
        cst: bool,
        #[arg(long)]
        tolerant: bool,
    },
}

#[derive(Debug, Clone, Copy, ValueEnum, PartialEq, Eq)]
enum OutputFormat {
    Human,
    Json,
}

#[derive(Debug, Serialize)]
struct MultiFileResult<T> {
    schema_version: &'static str,
    files: Vec<T>,
}

#[derive(Debug, Serialize)]
struct FileAnalysis {
    path: String,
    #[serde(skip)]
    source: String,
    #[serde(flatten)]
    analysis: bibmgr_core::AnalysisResult,
}

fn main() {
    let code = match run(Cli::parse()) {
        Ok(code) => code,
        Err(error) => {
            eprintln!("bibmgr: {error}");
            if error.internal {
                EXIT_INTERNAL
            } else {
                EXIT_USAGE_OR_IO
            }
        }
    };
    std::process::exit(code);
}

fn run(cli: Cli) -> Result<i32, CliError> {
    match cli.command {
        Command::Lint {
            files,
            format,
            profile,
            tolerant,
        } => lint(&files, format, &profile, tolerant),
        Command::Fix {
            file,
            safe,
            dry_run,
            fix_ids,
            source_revision,
            profile,
            format,
        } => fix(
            &file,
            safe,
            dry_run,
            &fix_ids,
            source_revision.as_deref(),
            &profile,
            format,
        ),
        Command::Export {
            file,
            profile,
            format,
            output,
        } => export_file(&file, &profile, format, output.as_deref()),
        Command::Inspect {
            file,
            ast,
            cst,
            tolerant,
        } => inspect(&file, ast, cst, tolerant),
    }
}

fn lint(
    paths: &[PathBuf],
    format: OutputFormat,
    profile: &str,
    tolerant: bool,
) -> Result<i32, CliError> {
    let options = analysis_options(profile, tolerant)?;
    let results: Vec<_> = paths
        .par_iter()
        .map(|path| {
            read_source(path).map(|source| {
                let analysis = analyze(&source, &options);
                FileAnalysis {
                    path: display_path(path),
                    source,
                    analysis,
                }
            })
        })
        .collect::<Result<_, _>>()?;
    let blocking = results
        .iter()
        .any(|result| result.analysis.has_blocking_diagnostics());

    match format {
        OutputFormat::Json if results.len() == 1 => {
            println!("{}", to_pretty_json(&results[0].analysis)?);
        }
        OutputFormat::Json => println!(
            "{}",
            to_pretty_json(&MultiFileResult {
                schema_version: SCHEMA_VERSION,
                files: results,
            })?
        ),
        OutputFormat::Human => {
            for result in &results {
                render_diagnostics(&result.path, &result.source, &result.analysis.diagnostics);
            }
        }
    }
    Ok(if blocking { EXIT_BLOCKING } else { EXIT_OK })
}

fn fix(
    path: &Path,
    safe: bool,
    dry_run: bool,
    requested_ids: &[String],
    requested_revision: Option<&str>,
    profile: &str,
    format: OutputFormat,
) -> Result<i32, CliError> {
    if path == Path::new("-") && !dry_run {
        return Err(CliError::usage("fixing stdin requires --dry-run"));
    }
    let source = read_source(path)?;
    let options = analysis_options(profile, true)?;
    let analysis = analyze(&source, &options);
    let applied = if requested_ids.is_empty() {
        // Bulk operation is always restricted to safe fixes. Overlapping safe
        // edits are applied in separate, revision-checked passes by the core.
        apply_safe_fixes(&source, &options).map_err(|error| CliError::message(error.to_string()))?
    } else {
        let expected_revision = requested_revision
            .ok_or_else(|| CliError::usage("--source-revision is required with --fix-id"))?;
        if expected_revision != analysis.source_revision.as_str() {
            return Err(CliError::usage(format!(
                "source revision is stale: expected {expected_revision}, got {}",
                analysis.source_revision
            )));
        }
        if safe {
            reject_non_safe_requested_fixes(&analysis, requested_ids)?;
        }
        let selection = FixSelection::Ids(
            requested_ids
                .iter()
                .map(|id| FixId::new(id.as_str()))
                .collect(),
        );
        let plan = plan_fixes(&analysis, &selection)
            .map_err(|error| CliError::message(error.to_string()))?;
        apply_fix_plan_with_options(&source, &plan, &options)
            .map_err(|error| CliError::message(error.to_string()))?
    };

    if format == OutputFormat::Json {
        println!("{}", to_pretty_json(&applied)?);
    } else if applied.diff.is_empty() {
        eprintln!("{}: no applicable changes", display_path(path));
    } else {
        print!("{}", applied.diff);
    }

    if !dry_run && applied.source != source {
        fs::write(path, &applied.source).map_err(|error| CliError::io(path, error))?;
    }
    Ok(if applied.analysis.has_blocking_diagnostics() {
        EXIT_BLOCKING
    } else {
        EXIT_OK
    })
}

fn reject_non_safe_requested_fixes(
    analysis: &bibmgr_core::AnalysisResult,
    requested_ids: &[String],
) -> Result<(), CliError> {
    for requested_id in requested_ids {
        if let Some(fix) = analysis
            .available_fixes
            .iter()
            .find(|fix| fix.id.as_str() == requested_id)
        {
            if fix.applicability != FixApplicability::Safe {
                return Err(CliError::usage(format!(
                    "fix `{requested_id}` is {}; remove --safe to select it explicitly",
                    match fix.applicability {
                        FixApplicability::Safe => "safe",
                        FixApplicability::RequiresConfirmation => "confirmation-required",
                        FixApplicability::Unsafe => "unsafe",
                    }
                )));
            }
        }
    }
    Ok(())
}

fn export_file(
    path: &Path,
    profile_name: &str,
    format: OutputFormat,
    output: Option<&Path>,
) -> Result<i32, CliError> {
    let source = read_source(path)?;
    let profile = ExportProfile::for_profile(&ProfileId::from(profile_name))
        .map_err(|error| CliError::message(error.to_string()))?;
    let exported = match export_source(&source, &profile) {
        Ok(exported) => exported,
        Err(ExportError::BlockingDiagnostics(codes)) => {
            eprintln!(
                "{}: export blocked by {}",
                display_path(path),
                codes
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
                    .join(", ")
            );
            return Ok(EXIT_BLOCKING);
        }
        Err(error) => return Err(CliError::message(error.to_string())),
    };
    if let Some(output) = output {
        fs::write(output, &exported.source).map_err(|error| CliError::io(output, error))?;
    }
    match format {
        OutputFormat::Json => println!("{}", to_pretty_json(&exported)?),
        OutputFormat::Human if output.is_none() => print!("{}", exported.source),
        OutputFormat::Human => {}
    }
    Ok(EXIT_OK)
}

fn inspect(path: &Path, ast: bool, cst: bool, tolerant: bool) -> Result<i32, CliError> {
    let source = read_source(path)?;
    let mode = if tolerant {
        ParseMode::Tolerant
    } else {
        ParseMode::Strict
    };
    let options = ParseOptions {
        mode,
        source_id: display_path(path).as_str().into(),
    };
    if cst {
        println!(
            "{}",
            to_pretty_json(&bibmgr_core::inspect_cst(&source, options))?
        );
    } else if ast {
        println!(
            "{}",
            to_pretty_json(&bibmgr_core::inspect_ast(&source, options))?
        );
    }
    Ok(EXIT_OK)
}

fn analysis_options(profile: &str, tolerant: bool) -> Result<AnalysisOptions, CliError> {
    let validation_policy = ValidationPolicy::for_profile(&ProfileId::from(profile))
        .map_err(|error| CliError::message(error.to_string()))?;
    Ok(AnalysisOptions {
        parse_mode: if tolerant {
            ParseMode::Tolerant
        } else {
            ParseMode::Strict
        },
        validation_policy,
        ..AnalysisOptions::default()
    })
}

fn read_source(path: &Path) -> Result<String, CliError> {
    if path == Path::new("-") {
        let mut source = String::new();
        io::stdin()
            .read_to_string(&mut source)
            .map_err(|error| CliError::message(format!("failed reading stdin: {error}")))?;
        Ok(source)
    } else {
        fs::read_to_string(path).map_err(|error| CliError::io(path, error))
    }
}

fn display_path(path: &Path) -> String {
    if path == Path::new("-") {
        "<stdin>".to_owned()
    } else {
        path.display().to_string()
    }
}

fn render_diagnostics(path: &str, source: &str, diagnostics: &[Diagnostic]) {
    for diagnostic in diagnostics {
        let (line, column) = diagnostic
            .primary_location
            .as_ref()
            .map_or((1, 1), |location| line_column(source, location.range.start));
        let severity = match diagnostic.severity {
            Severity::Error => "error",
            Severity::Warning => "warning",
            Severity::Information => "info",
            Severity::Hint => "hint",
        };
        let blocking = if diagnostic.blocking {
            " [blocking]"
        } else {
            ""
        };
        eprintln!(
            "{path}:{line}:{column}: {severity}[{}]{blocking}: {}",
            diagnostic.code, diagnostic.message
        );
    }
}

fn line_column(source: &str, byte_offset: u32) -> (usize, usize) {
    let mut offset = (byte_offset as usize).min(source.len());
    while !source.is_char_boundary(offset) {
        offset -= 1;
    }
    let prefix = &source[..offset];
    let line = prefix.bytes().filter(|byte| *byte == b'\n').count() + 1;
    let column = prefix.rsplit_once('\n').map_or_else(
        || prefix.chars().count() + 1,
        |(_, tail)| tail.chars().count() + 1,
    );
    (line, column)
}

fn to_pretty_json(value: &impl Serialize) -> Result<String, CliError> {
    serde_json::to_string_pretty(value).map_err(CliError::internal)
}

#[derive(Debug)]
struct CliError {
    message: String,
    internal: bool,
}

impl CliError {
    fn message(message: String) -> Self {
        Self {
            message,
            internal: false,
        }
    }

    fn usage(message: impl Into<String>) -> Self {
        Self::message(message.into())
    }

    #[allow(clippy::needless_pass_by_value)]
    fn io(path: &Path, error: io::Error) -> Self {
        Self::message(format!("{}: {error}", display_path(path)))
    }

    fn internal(error: impl std::fmt::Display) -> Self {
        Self {
            message: error.to_string(),
            internal: true,
        }
    }
}

impl std::fmt::Display for CliError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn byte_offsets_are_rendered_as_unicode_columns() {
        assert_eq!(line_column("é\n日x", 6), (2, 2));
    }
}
