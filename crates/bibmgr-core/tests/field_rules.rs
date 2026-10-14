use bibmgr_core::{
    analyze, apply_safe_fixes, validate_for_registration_with_options, AnalysisOptions,
    RegistrationPolicy, RuleCode, Severity, ValidationPolicy,
};

const POLICY: &str = r#"
profile = "archive"
field_order = []
[required_fields]

[[field_rules]]
code = "CUSTOM-VENUE-001"
entry_type = "article"
field = "journal"
pattern = '(?i)^restricted venue$'
message = "Choose an allowed journal."
enabled = true
severity = "error"
blocking = true
"#;

fn options() -> AnalysisOptions {
    AnalysisOptions {
        validation_policy: ValidationPolicy::from_toml(POLICY).unwrap(),
        ..AnalysisOptions::default()
    }
}

#[test]
fn resolved_fields_emit_stable_diagnostics_without_rewriting_source() {
    let options = options();
    for expression in [
        "{Restricted Venue}",
        "\"RESTRICTED VENUE\"",
        "venue",
        "prefix # { Venue}",
    ] {
        let source = format!(
            "@string{{prefix={{Restricted}}}}\n@string{{venue=prefix # {{ Venue}}}}\n\
             @ArTiClE{{k,title={{日本語}},JOURNAL={expression}}}"
        );
        let analysis = analyze(&source, &options);
        assert_eq!(analysis, analyze(&source, &options));
        let diagnostic = analysis
            .diagnostics
            .iter()
            .find(|d| d.code.as_str() == "CUSTOM-VENUE-001")
            .unwrap();
        assert_eq!(diagnostic.id.as_str(), "CUSTOM-VENUE-001:0");
        assert_eq!(diagnostic.message, "Choose an allowed journal.");
        assert_eq!(diagnostic.severity, Severity::Error);
        assert!(diagnostic.blocking);
        assert_eq!(diagnostic.fixes, [] as [bibmgr_core::FixId; 0]);
        let range = diagnostic.primary_location.as_ref().unwrap().range;
        assert_eq!(
            &source[range.start as usize..range.end as usize],
            expression
        );
        assert_eq!(diagnostic.related_locations.len(), 1);
        let range = diagnostic.related_locations[0].location.range;
        assert_eq!(&source[range.start as usize..range.end as usize], "ArTiClE");
        let registered = validate_for_registration_with_options(
            &source,
            &RegistrationPolicy::archive(),
            &options,
        );
        assert!(!registered.accepted);
        assert_eq!(registered.source, source);
        assert_eq!(registered.diagnostics, analysis.diagnostics);
        let fixed = apply_safe_fixes(&source, &options).unwrap();
        assert!(fixed
            .analysis
            .diagnostics
            .iter()
            .any(|d| d.code.as_str() == "CUSTOM-VENUE-001" && d.blocking));
    }
}

#[test]
fn rules_match_only_the_configured_type_field_and_resolved_value() {
    for source in [
        "@misc{k,journal={Restricted Venue}}",
        "@article{k,booktitle={Restricted Venue}}",
        "@article{k,journal={Allowed Venue}}",
        "@article{k,journal=missing}",
        "@string{v={Restricted Venue}} @string{v={Allowed Venue}} @article{k,journal=v}",
        "@string{v=v} @article{k,journal=v}",
        "@article{k,title={Restricted Venue}}",
        "@article{k,journal={{Restricted Venue}}}",
    ] {
        let result = validate_for_registration_with_options(
            source,
            &RegistrationPolicy::archive(),
            &options(),
        );
        assert!(result.accepted, "{source}: {:?}", result.diagnostics);
        assert!(result
            .diagnostics
            .iter()
            .all(|d| !d.code.as_str().starts_with("CUSTOM-")));
    }
}

#[test]
fn supports_arbitrary_fields_repeated_occurrences_and_multiple_rules() {
    let mut options = options();
    let rule = &mut options.validation_policy.field_rules[0];
    rule.entry_type = "misc".into();
    rule.field = "customfield".into();
    rule.pattern = "[0-9]+".into();
    let mut second = rule.clone();
    second.code = "CUSTOM-VALUE-002".into();
    second.message = "A second diagnostic".into();
    options.validation_policy.field_rules.push(second);
    let source = "@misc{k,customfield={12},CUSTOMFIELD={34}} @misc{j,customfield={56}}";
    let analysis = analyze(source, &options);
    let findings: Vec<_> = analysis
        .diagnostics
        .iter()
        .filter(|d| d.code.as_str().starts_with("CUSTOM-"))
        .collect();
    assert_eq!(findings.len(), 6);
    assert_eq!(
        findings.iter().map(|d| d.id.as_str()).collect::<Vec<_>>(),
        [
            "CUSTOM-VALUE-002:0",
            "CUSTOM-VENUE-001:0",
            "CUSTOM-VALUE-002:1",
            "CUSTOM-VENUE-001:1",
            "CUSTOM-VALUE-002:2",
            "CUSTOM-VENUE-001:2",
        ]
    );
}

#[test]
fn settings_and_registration_selectors_use_the_existing_policy_path() {
    let source = "@article{k,journal={Restricted Venue}}";
    let mut options = options();
    options.validation_policy.field_rules[0].blocking = false;
    assert!(
        validate_for_registration_with_options(source, &RegistrationPolicy::archive(), &options)
            .accepted
    );
    let mut registration = RegistrationPolicy::archive();
    registration
        .blocking_rules
        .include
        .insert("CUSTOM-VENUE-001".into());
    assert!(!validate_for_registration_with_options(source, &registration, &options).accepted);
    registration
        .blocking_rules
        .include
        .insert("CUSTOM-UNKNOWN".into());
    let unknown = validate_for_registration_with_options(source, &registration, &options);
    assert!(!unknown.accepted);
    assert!(unknown
        .diagnostics
        .iter()
        .any(|d| d.code.as_str() == "BIB-CONFIG-001"));
    options.validation_policy.field_rules[0].enabled = false;
    assert!(!analyze(source, &options)
        .diagnostics
        .iter()
        .any(|d| d.code.as_str() == "CUSTOM-VENUE-001"));
    options.validation_policy.rules.insert(
        RuleCode::from("CUSTOM-VENUE-001"),
        bibmgr_validation::RuleSetting {
            enabled: true,
            severity: Severity::Hint,
            blocking: true,
        },
    );
    assert!(analyze(source, &options)
        .diagnostics
        .iter()
        .any(|d| d.code.as_str() == "CUSTOM-VENUE-001"
            && d.severity == Severity::Hint
            && d.blocking));
}

#[test]
fn invalid_configuration_is_rejected_and_programmatic_errors_block() {
    for (old, new) in [
        ("CUSTOM-VENUE-001", "BIB-SYNTAX-001"),
        ("CUSTOM-VENUE-001", "CUSTOM-"),
        ("CUSTOM-VENUE-001", "CUSTOM--EMPTY"),
        ("CUSTOM-VENUE-001", "CUSTOM-lowercase"),
        ("entry_type = \"article\"", "entry_type = \"\""),
        ("field = \"journal\"", "field = \"bad field\""),
        ("(?i)^restricted venue$", "["),
        ("(?i)^restricted venue$", ""),
        ("Choose an allowed journal.", " "),
        ("blocking = true", "blockng = true"),
    ] {
        assert!(
            ValidationPolicy::from_toml(&POLICY.replace(old, new)).is_err(),
            "{old} -> {new}"
        );
    }
    let mut options = options();
    options
        .validation_policy
        .field_rules
        .push(options.validation_policy.field_rules[0].clone());
    assert!(options.validation_policy.validate_configuration().is_err());
    assert!(analyze("@article{k,journal={Restricted Venue}}", &options)
        .diagnostics
        .iter()
        .any(|d| d.code.as_str() == "BIB-CONFIG-001" && d.blocking));
}

#[test]
fn field_rules_round_trip_and_are_empty_in_builtin_policies() {
    let policy = options().validation_policy;
    let json = serde_json::to_string(&policy).unwrap();
    assert_eq!(
        policy,
        serde_json::from_str::<ValidationPolicy>(&json).unwrap()
    );
    for profile in ["archive", "modern", "acl", "classical-bst"] {
        let policy = ValidationPolicy::builtin(profile).unwrap();
        assert_eq!(policy.field_rules, [] as [bibmgr_core::FieldRule; 0]);
        assert!(serde_json::to_value(policy)
            .unwrap()
            .get("field_rules")
            .is_none());
    }
}
