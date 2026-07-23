# Venue registry

Venue identity is independent from how a profile displays that venue. The registry is an entity catalog, not a sequence of string replacements.

```toml
[[venues]]
id = "acl-annual-meeting"
full_name = "Annual Meeting of the Association for Computational Linguistics"
short_name = "ACL"
aliases = ["Proceedings of ACL", "Annual Meeting of ACL"]
kind = "conference"
```

## Adding a venue

1. Choose a stable lowercase kebab-case ID. The ID survives future renames.
2. Use the proceedings/publication's canonical full name and its unambiguous established abbreviation.
3. Add only observed aliases that uniquely identify this entity. Do not add a generic token such as `Proceedings` or an acronym shared by another venue.
4. Set `kind` to `conference`, `journal`, `workshop`, `book-series`, or `other` as appropriate.
5. Run configuration validation and registry tests. Alias matching is based on normalized case and whitespace, so visually different aliases may collide.
6. Add resolution fixtures for full name, short name, and every alias, plus a negative ambiguous example when relevant.

Changing an alias does not change stored bibliographic identity. Removing an alias can make historical input unresolved, so treat it as a compatibility change. Never merge two venue IDs merely because an export profile renders the same abbreviation.

## Display

`venue_style = "full"` emits `full_name`; `short` emits `short_name` when available; `preserve` prefers the source spelling represented by provenance. Resolution and display are separate steps. A validation rule may require a resolvable venue while allowing a profile to choose any display style. The resolved kind is also retained in the semantic venue reference. Rule `BIB-SEMANTIC-004` uses it to flag `article` entries that resolve to conference or workshop venues and `inproceedings` entries that resolve to journals. The suggested entry-type edit always requires confirmation.

Repository entities such as arXiv are in `repositories.toml`. They additionally define identifier syntax and canonical URL construction; no runtime online lookup is performed.
