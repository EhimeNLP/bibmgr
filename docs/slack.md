# Slack app

The BibMgR Slack app receives one syntactically valid BibTeX entry in a code block, asks the submitting user to choose an export profile, applies every safe fix (including lint fixes), and returns the exported entry. In channels it receives app mentions and replies in the original thread. In a direct message it does not require a mention and replies in the direct conversation. Validation findings that cannot be fixed do not block deterministic export; they are reported with the result. Syntax errors, ambiguous values, and conflicting values are not guessed.

The app uses Slack Socket Mode and does not expose an HTTP endpoint. It stores each pending profile-selection request in process memory for ten minutes by default. Restarting the container expires pending selections.

## Create the Slack app

1. Open [Slack API: Your Apps](https://api.slack.com/apps), select **Create New App**, and choose **From an app manifest**.
2. Select the workspace and paste [`slack/app-manifest.yaml`](../slack/app-manifest.yaml).
3. Create the app, open **Basic Information**, and upload [`slack/assets/icon.png`](../slack/assets/icon.png) as the app icon. This 512×512 PNG is generated from [`frontend/public/favicon.svg`](../frontend/public/favicon.svg). To customize the icon, upload a different square PNG, JPEG, or GIF between 512×512 and 2000×2000 pixels instead.
4. Open **OAuth & Permissions**, and select **Install to Workspace**. Copy the **Bot User OAuth Token** beginning with `xoxb-`.
5. Open **Basic Information**, select **Generate Token and Scopes** under **App-Level Tokens**, add the `connections:write` scope, and copy the token beginning with `xapp-`.
6. Invite `@BibMgR` to every channel where it should respond.

No app ID, bot ID, team ID, signing secret, request URL, or public port is required at startup. The app obtains its identity with Slack's `auth.test` method.

If the app was installed from an older manifest without direct-message support, reinstallation alone does not import changes from the repository. Open **App Manifest** in the Slack app settings, replace its contents with the current [`slack/app-manifest.yaml`](../slack/app-manifest.yaml), and save the changes. Then open **App Home** and verify that the Messages tab is enabled and users are allowed to send messages. Finally, reinstall the app to the workspace to grant the newly required `im:history` bot scope. The app subscribes only to direct messages and app mentions; it does not read ordinary channel messages.

The regular YAML App Manifest does not include app icon data, and the Socket Mode runtime tokens cannot update app configuration. Icon selection therefore remains a deployment-time setting in Slack rather than a bot startup setting.

## Start locally with interactive token entry

The local Docker-based Poe task builds the native extension and Slack app, starts a temporary TTY container, and prompts for both tokens without echoing them:

```bash
uv run poe slack
```

English is the default user-facing language. To use Japanese, set the language for the startup command:

```bash
BIBMGR_SLACK_LANGUAGE=ja uv run poe slack
```

This task is intended for local operation and troubleshooting, not unattended deployment.

## Start in production

For unattended deployment, build the image as a separate release step:

```bash
uv run poe slack-build
```

Provide `SLACK_APP_TOKEN` and `SLACK_BOT_TOKEN` through the deployment environment or its secret manager, then start the existing image:

```bash
uv run poe slack-up
```

The production task does not allocate a TTY, does not rebuild the image, and starts the container in the background with `restart: unless-stopped`. Both tokens are required before Docker creates the container; missing credentials cause configuration to fail instead of opening a prompt.

Follow its logs or stop the deployment with:

```bash
uv run poe slack-logs
uv run poe slack-down
```

Do not place tokens directly in a committed Compose file or image. Inject them from the host environment or a production secret-management system.

## Environment settings

Both local and production startup accept settings from environment variables. Local startup prompts for missing credentials only when stdin is a TTY; production startup always requires both credentials in the environment.

```bash
BIBMGR_SLACK_LANGUAGE=en uv run poe slack
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

## Use the app in a channel

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

## Use the app in a direct message

Open the app's **Messages** tab and send exactly one code block. A mention is not required.

````text
```
@misc{example,
  title = {An Example},
}
```
````

Messages posted by bots and message subtypes such as edits are ignored. Direct-message responses remain in the main conversation unless the submission itself is already in a thread.

## Slack-only export profiles

Built-in profiles come from `bibmgr_native`. Additional profiles placed under [`slack/config/export-profiles/`](../slack/config/export-profiles/) are bundled into the Slack image, loaded once at startup, and passed to the native extension as validated profile snapshots. They do not change the CLI or web catalogs.

To add a Slack-only profile:

1. Add a TOML file to `slack/config/export-profiles/`.
2. Use a profile ID that does not duplicate a built-in ID.
3. Set `validation_profile` to an existing built-in validation policy.
4. Run `uv run poe slack` again to rebuild and start the image.

An invalid profile or duplicate ID prevents the app from starting.
