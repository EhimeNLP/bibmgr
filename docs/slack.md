# Slack app

The BibMgR Slack app receives one syntactically valid BibTeX entry in a code block, asks the submitting user to choose an export profile, applies every safe fix (including lint fixes), and replies in the original thread with the exported entry. Validation findings that cannot be fixed do not block deterministic export; they are reported with the result. Syntax errors, ambiguous values, and conflicting values are not guessed.

The app uses Slack Socket Mode and does not expose an HTTP endpoint. It stores each pending profile-selection request in process memory for ten minutes by default. Restarting the container expires pending selections.

## Create the Slack app

1. Open [Slack API: Your Apps](https://api.slack.com/apps), select **Create New App**, and choose **From an app manifest**.
2. Select the workspace and paste [`slack/app-manifest.yaml`](../slack/app-manifest.yaml).
3. Create the app, open **OAuth & Permissions**, and select **Install to Workspace**. Copy the **Bot User OAuth Token** beginning with `xoxb-`.
4. Open **Basic Information**, select **Generate Token and Scopes** under **App-Level Tokens**, add the `connections:write` scope, and copy the token beginning with `xapp-`.
5. Invite `@BibMgR` to every channel where it should respond.

No app ID, bot ID, team ID, signing secret, request URL, or public port is required at startup. The app obtains its identity with Slack's `auth.test` method.

## Start with interactive token entry

The Docker-based Poe task builds the native extension and Slack app, starts a TTY container, and prompts for both tokens without echoing them:

```bash
uv run poe slack
```

English is the default user-facing language. To use Japanese, set the language for the startup command:

```bash
BIBMGR_SLACK_LANGUAGE=ja uv run poe slack
```

## Start from environment variables

For unattended startup, provide both tokens as environment variables. Missing credentials are only prompted for when stdin is a TTY; a non-interactive container fails closed with a configuration error.

```bash
SLACK_APP_TOKEN=xapp-... \
SLACK_BOT_TOKEN=xoxb-... \
BIBMGR_SLACK_LANGUAGE=en \
uv run poe slack
```

Supported startup settings are:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SLACK_APP_TOKEN` | none | App-level `xapp-` token with `connections:write` |
| `SLACK_BOT_TOKEN` | none | Bot `xoxb-` token |
| `BIBMGR_SLACK_LANGUAGE` | `en` | User-facing language: `en` or `ja` |
| `BIBMGR_SLACK_REQUEST_TTL_SECONDS` | `600` | Lifetime of a pending profile selection |
| `BIBMGR_SLACK_MAX_INPUT_BYTES` | `12000` | Maximum UTF-8 size of one code-block input |

Do not commit tokens to the repository or include them in the image.

## Use the app

Mention the app with exactly one code block. No code-block language is required.

````text
@BibMgR
```
@misc{example,
  title = {An Example},
}
```
````

Only the submitting user can use the profile selector. The final BibTeX is sent as a preformatted rich-text block so its content is not interpreted as Slack markup.

## Slack-only export profiles

Built-in profiles come from `bibmgr_native`. Additional profiles placed under [`slack/config/export-profiles/`](../slack/config/export-profiles/) are bundled into the Slack image, loaded once at startup, and passed to the native extension as validated profile snapshots. They do not change the CLI or web catalogs.

To add a Slack-only profile:

1. Add a TOML file to `slack/config/export-profiles/`.
2. Use a profile ID that does not duplicate a built-in ID.
3. Set `validation_profile` to an existing built-in validation policy.
4. Run `uv run poe slack` again to rebuild and start the image.

An invalid profile or duplicate ID prevents the app from starting.
