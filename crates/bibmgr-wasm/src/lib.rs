//! General-purpose WebAssembly JSON bridge to the shared core.
//! This adapter has no filesystem, network, database, or search dependency.

use bibmgr_core::{
    AnalysisOptions, ExportProfile, ExportSourceOptions, ParseMode, ProfileId, RegistrationPolicy,
    ValidationPolicy, VenueNameStyle,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use wasm_bindgen::prelude::wasm_bindgen;

/// The browser and this adapter both cap a document at two MiB of UTF-8.
pub const MAX_SOURCE_BYTES: usize = 2 * 1024 * 1024;

#[derive(Debug, Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
enum Request {
    Catalog {},
    Analyze {
        source: String,
        profile: String,
    },
    Fix {
        source: String,
        profile: String,
    },
    ValidateRegistration {
        source: String,
        profile: String,
        #[serde(default)]
        apply_safe_fixes: bool,
    },
    Export {
        source: String,
        profile: String,
        venue_name_style: VenueNameStyle,
    },
}

#[derive(Debug, Serialize)]
struct Failure {
    code: &'static str,
    message: String,
}

impl Failure {
    fn new(code: &'static str, message: &(impl ToString + ?Sized)) -> Self {
        Self {
            code,
            message: message.to_string(),
        }
    }
}

fn options(profile: &str) -> Result<AnalysisOptions, Failure> {
    Ok(AnalysisOptions {
        parse_mode: ParseMode::Strict,
        validation_policy: ValidationPolicy::for_profile(&ProfileId::from(profile))
            .map_err(|error| Failure::new("invalid_profile", &error))?,
        ..AnalysisOptions::default()
    })
}

fn value(result: impl Serialize) -> Result<Value, Failure> {
    serde_json::to_value(result).map_err(|error| Failure::new("serialization_failed", &error))
}

fn dispatch(request: Request) -> Result<Value, Failure> {
    let source = match &request {
        Request::Catalog {} => "",
        Request::Analyze { source, .. }
        | Request::Fix { source, .. }
        | Request::ValidateRegistration { source, .. }
        | Request::Export { source, .. } => source,
    };
    if source.len() > MAX_SOURCE_BYTES {
        return Err(Failure::new(
            "source_too_large",
            "BibTeX must be 2 MiB or smaller.",
        ));
    }
    match request {
        Request::Catalog {} => {
            let catalog = bibmgr_core::export_profiles()
                .map_err(|error| Failure::new("invalid_profile", &error))?;
            Ok(json!({ "schema_version": bibmgr_core::SCHEMA_VERSION,
                "engine_version": env!("CARGO_PKG_VERSION"), "profiles": catalog.profiles }))
        }
        Request::Analyze { source, profile } => {
            value(bibmgr_core::analyze(&source, &options(&profile)?))
        }
        Request::Fix { source, profile } => value(
            bibmgr_core::apply_safe_fixes(&source, &options(&profile)?)
                .map_err(|error| Failure::new("fix_failed", &error))?,
        ),
        Request::ValidateRegistration {
            source,
            profile,
            apply_safe_fixes,
        } => {
            let mut policy = RegistrationPolicy::for_profile(&ProfileId::from(profile.as_str()))
                .map_err(|error| Failure::new("invalid_profile", &error))?;
            policy.apply_safe_fixes = apply_safe_fixes;
            value(bibmgr_core::validate_for_registration(&source, &policy))
        }
        Request::Export {
            source,
            profile,
            venue_name_style,
        } => {
            let profile = ExportProfile::for_profile(&ProfileId::from(profile.as_str()))
                .map_err(|error| Failure::new("invalid_profile", &error))?;
            value(
                bibmgr_core::export_source_workflow(
                    &source,
                    &profile,
                    &ExportSourceOptions {
                        venue_name_style,
                        ..ExportSourceOptions::default()
                    },
                )
                .map_err(|error| Failure::new("export_failed", &error))?,
            )
        }
    }
}

/// Execute a schema-v1 request and return an `{ ok, result | error }` envelope.
/// Core DTOs are preserved, including UTF-8 byte ranges and source revisions.
/// No confirmation-required or unsafe fixes are selected by this API.
#[wasm_bindgen]
pub fn invoke(request_json: &str) -> String {
    let result = if request_json.len() > MAX_SOURCE_BYTES * 6 + 4096 {
        Err(Failure::new(
            "source_too_large",
            "Request exceeds the document size limit.",
        ))
    } else {
        serde_json::from_str::<Request>(request_json)
            .map_err(|error| Failure::new("invalid_request", &error))
            .and_then(dispatch)
    };
    match result {
        Ok(result) => json!({ "ok": true, "result": result }).to_string(),
        Err(error) => json!({ "ok": false, "error": error }).to_string(),
    }
}
