use crate::Person;

/// Parse a BibTeX name list while respecting braces around organizations and
/// commas inside protected groups.
pub fn parse_people(input: &str) -> Vec<Person> {
    split_names(input)
        .into_iter()
        .map(parse_person)
        .filter(|person| !person.raw.is_empty())
        .collect()
}

fn split_names(input: &str) -> Vec<&str> {
    let bytes = input.as_bytes();
    let mut result = Vec::new();
    let mut start = 0;
    let mut pos = 0;
    let mut depth = 0_u32;
    while pos < bytes.len() {
        match bytes[pos] {
            b'\\' => pos = (pos + 2).min(bytes.len()),
            b'{' => {
                depth = depth.saturating_add(1);
                pos += 1;
            }
            b'}' => {
                depth = depth.saturating_sub(1);
                pos += 1;
            }
            _ if depth == 0 && starts_with_and(bytes, pos) => {
                result.push(input[start..pos].trim());
                pos += 3;
                start = pos;
            }
            _ => pos += 1,
        }
    }
    result.push(input[start..].trim());
    result
}

fn starts_with_and(bytes: &[u8], pos: usize) -> bool {
    if pos + 3 > bytes.len() || !bytes[pos..pos + 3].eq_ignore_ascii_case(b"and") {
        return false;
    }
    let before = pos == 0 || bytes[pos - 1].is_ascii_whitespace();
    let after = pos + 3 == bytes.len() || bytes[pos + 3].is_ascii_whitespace();
    before && after
}

fn parse_person(raw: &str) -> Person {
    let raw = raw.trim();
    if is_outer_braced(raw) {
        return Person {
            raw: raw.to_string(),
            literal: Some(raw[1..raw.len() - 1].to_string()),
            ..Person::default()
        };
    }

    let comma_parts = split_top_level(raw, ',');
    let (given, prefix, family, suffix) = match comma_parts.as_slice() {
        [family_part, given_part] => {
            let (prefix, family) = split_prefix_family(family_part);
            (tokens(given_part), prefix, family, Vec::new())
        }
        [family_part, suffix_part, given_part, ..] => {
            let (prefix, family) = split_prefix_family(family_part);
            (tokens(given_part), prefix, family, tokens(suffix_part))
        }
        _ => parse_first_last(raw),
    };

    Person {
        raw: raw.to_string(),
        given,
        family,
        prefix,
        suffix,
        literal: None,
    }
}

fn parse_first_last(raw: &str) -> (Vec<String>, Vec<String>, Vec<String>, Vec<String>) {
    let parts = tokens(raw);
    if parts.is_empty() {
        return (Vec::new(), Vec::new(), Vec::new(), Vec::new());
    }
    let family_start = parts
        .iter()
        .rposition(|part| starts_uppercase(part))
        .unwrap_or(parts.len() - 1);
    let prefix_start = parts[..family_start]
        .iter()
        .rposition(|part| starts_uppercase(part))
        .map_or(0, |index| index + 1);
    (
        parts[..prefix_start].to_vec(),
        parts[prefix_start..family_start].to_vec(),
        parts[family_start..].to_vec(),
        Vec::new(),
    )
}

fn split_prefix_family(raw: &str) -> (Vec<String>, Vec<String>) {
    let parts = tokens(raw);
    let family_start = parts
        .iter()
        .position(|part| starts_uppercase(part))
        .unwrap_or(parts.len().saturating_sub(1));
    (
        parts[..family_start].to_vec(),
        parts[family_start..].to_vec(),
    )
}

fn tokens(input: &str) -> Vec<String> {
    input
        .split_whitespace()
        .filter(|part| !part.is_empty())
        .map(ToOwned::to_owned)
        .collect()
}

fn starts_uppercase(input: &str) -> bool {
    input
        .trim_start_matches(['{', '\\'])
        .chars()
        .find(char::is_ascii_alphabetic)
        .is_some_and(char::is_uppercase)
}

fn is_outer_braced(input: &str) -> bool {
    if !input.starts_with('{') || !input.ends_with('}') {
        return false;
    }
    let mut depth = 0_i32;
    for (index, character) in input.char_indices() {
        match character {
            '{' => depth += 1,
            '}' => {
                depth -= 1;
                if depth == 0 && index + character.len_utf8() != input.len() {
                    return false;
                }
            }
            _ => {}
        }
    }
    depth == 0
}

fn split_top_level(input: &str, separator: char) -> Vec<&str> {
    let mut result = Vec::new();
    let mut depth = 0_i32;
    let mut start = 0;
    for (index, character) in input.char_indices() {
        match character {
            '{' => depth += 1,
            '}' => depth = (depth - 1).max(0),
            _ if character == separator && depth == 0 => {
                result.push(input[start..index].trim());
                start = index + character.len_utf8();
            }
            _ => {}
        }
    }
    result.push(input[start..].trim());
    result
}
