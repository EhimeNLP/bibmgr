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

Venue presentation is an export-request option rather than part of an output profile. `venue_name_style = "full"` emits `full_name` and is the default for every profile. `abbreviated` emits `short_name`; when no abbreviation is registered, export falls back to `full_name`, then the recorded source spelling, and returns a warning. The option applies consistently to conference `booktitle`, journal `journal`, and other venue-derived `howpublished` fields. It never changes stored source, AST, or CST data.

Resolution tolerates a trailing publication year and common proceedings wrappers such as an ordinal edition and a volume suffix. For example, both `Findings of the Association for Computational Linguistics: EMNLP 2023` and a registered year-free alias resolve deterministically. Do not add fuzzy aliases that could identify more than one venue.

The built-in registry covers the central ACL venues and journals plus common AI and machine-learning venues, including ACL, AACL, EACL, EMNLP, NAACL, CoNLL, COLING, LREC, IJCNLP, AAAI, IJCAI, NeurIPS, ICML, ICLR, AISTATS, UAI, CL, TACL, NLE, JNLP, JMLR, ML, AIJ, and JAIR. Authenticated users can add, edit, and delete effective mappings in Application settings. Database rows are overrides over the embedded registry, so deleting a built-in override restores the embedded mapping and the binary remains usable without runtime configuration. Each change uses optimistic revision checking and records its actor and before/after data.

Resolution and display remain separate steps. A validation rule may require a resolvable venue while allowing either display style. The resolved kind is retained in the semantic venue reference. Rule `BIB-SEMANTIC-004` uses it to flag `article` entries that resolve to conference or workshop venues and `inproceedings` entries that resolve to journals. The suggested entry-type edit always requires confirmation.

Repository entities such as arXiv are in `repositories.toml`. They additionally define identifier syntax and canonical URL construction; no runtime online lookup is performed.
