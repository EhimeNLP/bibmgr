# Slack-only export profiles

Place additional BibMgR export profile TOML files in this directory and rebuild the Slack image. The Slack app loads them once at startup. Profile IDs must not duplicate built-in IDs, and `validation_profile` must reference an existing built-in validation policy.
