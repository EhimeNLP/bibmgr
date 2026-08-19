# Slack app icon

`icon.png` is the default Slack app icon. It is a 512×512 PNG rendered from [`frontend/public/favicon.svg`](../../frontend/public/favicon.svg) for compatibility with Slack's app icon upload.

Slack's regular YAML App Manifest cannot embed an icon asset. Upload `icon.png` from the app's **Basic Information** page when creating the app. A deployer can customize the app without changing the bot by uploading a different square PNG, JPEG, or GIF between 512×512 and 2000×2000 pixels.
