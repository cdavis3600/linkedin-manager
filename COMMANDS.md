# Discord Bot Commands

| Command | Description |
|---|---|
| `!inspire <url>` | Fetch a LinkedIn post and generate a draft in your voice |
| `!inspire <text>` | Use pasted text directly as source material |
| `!schedule` | Show current daily schedule and next run time |
| `!schedule 14:30` | Change daily run time (24h or 12h like `2:30pm`) |
| `!status` | Show last 10 posts and their status |
| `!pending` | List posts awaiting approval |
| `!team` | Show team roster by department |

**DM shortcut:** Send the bot a LinkedIn URL via DM (no command needed) to auto-generate a post. Add commentary alongside the URL to hint at your angle.

**Scheduled pipeline:** Runs daily at the configured time and sends an approval to your Discord channel automatically.

**Post types:**
- **TFG** (company posts) -- auto-reshare on Approve (repost with your commentary, original post embedded)
- **Inspiration / Industry** -- choose between Post Now (standalone) or Reshare (repost with embedded original)
