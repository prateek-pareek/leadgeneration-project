# ProspectOS Comment Assist (Chrome Extension)

Auto-fills approved sales comments on social platforms. **You always review and click Post** — the extension never submits comments automatically.

## Supported platforms

| Platform | Auto-fill |
|----------|-----------|
| LinkedIn | Yes |
| Threads | Yes |
| X / Twitter | Yes |
| Reddit | Yes |
| Dev.to | Yes |
| Hacker News | Yes |

## Install (development)

1. Open Chrome → `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked**
4. Select this folder: `apps/extension`
5. Open ProspectOS at `http://localhost:3000` — the extension connects automatically

## How to use

1. In ProspectOS, go to **Comments → Ready to post**
2. Click **Assist post** on an approved comment
3. The extension stores your draft and opens the post in a new tab
4. The comment box is filled — **review it and click Post yourself**
5. Back in ProspectOS, click **Mark as posted**

## Production domains

To use on a deployed ProspectOS URL, add your domain to `manifest.json`:

```json
"content_scripts": [
  {
    "matches": ["https://your-app.example.com/*"],
    "js": ["content-scripts/bridge.js"],
    "run_at": "document_idle"
  }
]
```

Also add it under `host_permissions` if needed.

## Safety

- Does **not** auto-submit comments (avoids LinkedIn/Threads bans)
- Pending comments expire after 30 minutes
- Clipboard is used as fallback if the extension is not installed

## Troubleshooting

- **Comment not filled?** Click the comment/reply button on the post first, then reload — or use Copy only
- **Extension not detected?** Reload ProspectOS after installing the extension
- **Wrong post?** URLs are matched loosely; clear pending from the extension popup
