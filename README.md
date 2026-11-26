# NYPL API Bridge

Ask plain-English questions about the [New York Public Library Digital Collections](https://digitalcollections.nypl.org/).

The project has two parts:

- **An MCP server** (`nypl-api-bridge`). It exposes the NYPL Repo API **v2** as tools that Claude Code, Claude Desktop or any other MCP client can use.
- **A chat app** (`nypl-chat`). It's a local Streamlit page where Claude answers questions using those tools, in a persona you pick.

> **Heads-up:** NYPL marked the Repo API as deprecated from 1 August 2026, and no public replacement is planned. It was still responding in November 2026, but it may be switched off without notice. Only v2 is supported, because v1 has been retired.

## Quick start

You need [uv](https://docs.astral.sh/uv/) installed. It provides Python 3.13 automatically.

1. **Get the keys:**
   - **NYPL API token:** sign up at <https://api.repo.nypl.org/sign_up> and the token is emailed to you.
   - **Anthropic API key:** in the [Claude Console](https://platform.claude.com), go to **Settings → API Keys → Create Key**. You'll need credits under **Settings → Billing**. Instead of a key, you can run `ant auth login` once.
2. **Add them to `.env`.** This file is git-ignored:
   ```bash
   cp .env.example .env   # then edit .env and fill in both values
   ```
3. **Run the chat app:**
   ```bash
   uv run nypl-chat
   ```
   This opens <http://localhost:8501>. Press Ctrl+C to stop it.

## The chat app

- **Choosing a persona:** pick one in the sidebar: 💬 Standard Claude (the default, with no character voice), 🚕 Taxi driver from Queens, 🪶 Founding father, 🎭 Broadway star or 🕵️ Noir detective. You can switch partway through a conversation, and the next reply uses the new voice.
- **The persona changes only the voice.** Facts come only from the NYPL tools, and Claude is told never to invent items, dates or links. It may show public-domain images, but only using links the API returned.
- **Watching the tool calls:** a status panel lists each tool call as it runs.
- **Starting over:** **New conversation** in the sidebar clears the chat.

**Model and settings:**
- It uses `claude-opus-5-5` at `medium` effort.
- If Claude declines a request on safety grounds, the API retries it on another model (the server-side fallbacks feature).
- Repeated parts of each request are cached, so follow-up questions in the same chat cost less.

**Cost:** a question usually takes a few Claude calls, which typically comes to a few cents. You can set a spend limit in the Console under **Settings → Limits**.

### Adding a persona

Add an entry to `PERSONAS` in `src/nypl_api_bridge/personas.py`:

```python
Persona(
    key="noir_detective",
    label="🕵️ Noir detective",
    instructions="Answer as a 1940s hard-boiled private eye: clipped sentences, rain-soaked metaphors...",
)
```

Put it inside the tuple of entries, with a comma after the closing parenthesis.

It appears in the sidebar the next time you start the app.

## The MCP server

### Claude Code

The `.mcp.json` file in this repository registers the server as `nypl`. Start Claude Code in this folder with `NYPL_API_TOKEN` exported, and approve the server when prompted.

### Claude Desktop or other MCP clients

Add the server to the client's MCP configuration:

```json
{
  "mcpServers": {
    "nypl": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/nypl-api-bridge", "nypl-api-bridge"],
      "env": { "NYPL_API_TOKEN": "your-nypl-token" }
    }
  }
}
```

The server uses stdio. To run it on its own, use `NYPL_API_TOKEN=... uv run nypl-api-bridge`.

### Hosting it online (Vercel)

The server can also run over HTTP, so any MCP client can connect to it by URL. **It has no login:** anyone with the URL can use it, and every request uses your NYPL token's daily quota of 10,000 requests.

- **Endpoints:** `/mcp` for MCP and `/health` for health checks. `index.py` in the repository root is the entrypoint Vercel serves.
- **Deploy:** import the repository at <https://vercel.com/new>, or run `vercel deploy` from this folder. Add `NYPL_API_TOKEN` under **Settings → Environment Variables**. The server won't start without it.
- **Logs:** on Vercel the server logs only to stderr, which appears in the project's **Logs** tab, because the filesystem there is read-only. Each tool call shows its arguments and a result preview. To see full results and raw NYPL responses too, set `NYPL_LOG_LEVEL=DEBUG` as an environment variable and redeploy.
- **Test locally:** `NYPL_API_TOKEN=... uv run uvicorn index:app --port 8000` serves it at <http://localhost:8000/mcp>.

To connect once it's deployed:

- **Claude Code:** `claude mcp add --transport http nypl https://<your-project>.vercel.app/mcp`
- **claude.ai:** **Settings → Connectors → Add custom connector**, with the same URL.
- **Claude Desktop and other clients:** use the client's "remote" or "HTTP" server option with the same URL.

### Tools

All tools are read-only.

| Tool | What it does | NYPL endpoint |
|---|---|---|
| `search_items` | Keyword search, with optional MODS field, `public_domain_only` and facet filters | `GET /items/search` |
| `list_collections` | List or search top-level collections | `GET /collections` |
| `browse_collection` | A collection's children, sub-collections only, or items only | `GET /collections/{uuid}[/subcollections\|/items]` |
| `get_item` | Summary of an item, container or collection | `GET /items/{uuid}` |
| `get_captures` | Digitised images or pages under any UUID | `GET /items/mods_captures/{uuid}` |
| `get_capture_details` | One capture with image links and sibling captures | `GET /items/item_details/{uuid}` |
| `get_mods` | Full bibliographic (MODS) record | `GET /mods/{uuid}` |
| `find_by_identifier` | Look up a UUID from an image ID, b-number, barcode, OCLC, ISBN and so on | `GET /items/{type}/{id}` |
| `get_rights` | Rights and use statement | `GET /items/rights/{uuid}` |
| `get_plain_text` | Text recognised from a capture's image (OCR) | `GET /items/plain_text/{uuid}` |
| `get_recent_items` / `get_featured_items` / `get_total_items` | Collection-wide overview | `GET /items/recent` / `featured` / `total` |

**Notes:**
- **Page size:** results return 10 per page by default. `per_page` is capped at 100 to keep responses small; the API itself allows up to 500.
- **UUID checks:** UUIDs are checked before any request is made.
- **Endpoints left out:** `POST /items/counts` (its request format isn't documented), `/items/roots` (one huge unpaginated list), `/items/collection/all` (the docs don't say how it differs from `/items/collection`) and the raw ALTO OCR endpoints. `get_plain_text` covers the useful part of the OCR endpoints.
- **Rate limit:** NYPL allows 10,000 requests per day per token.

## Logging

Both the chat app and the MCP server log each step of a question: the question, each Claude call (stop reason, model, request ID, token and cache usage), each tool call and its result, and every NYPL HTTP request (full URL, status, time, size).

- **Turn IDs:** in the chat app, every line for one question has the same tag, such as `[turn 4ed74d16]`. To see one question from start to finish, run `grep 'turn 4ed74d16' logs/nypl.log`.
- **MCP server:** logs every tool call it handles, whichever client sent it: the tool name and arguments, then a preview of the result with its size and time. A tool call and the NYPL requests it makes share one turn ID.
- **Terminal:** INFO level by default, written to stderr. Set `NYPL_LOG_LEVEL=DEBUG` to see full detail there too.
- **File:** `logs/nypl.log` in the working directory (or `NYPL_LOG_DIR`). It is always at DEBUG, so it also has full tool results, raw NYPL response bodies (up to 4,000 characters) and Claude's full text. It rotates at 5 MB.
- **Anthropic SDK internals:** set `ANTHROPIC_LOG=debug` to also see the SDK's own HTTP logging.

The NYPL token is sent in a header, so it never appears in logged URLs.

## Development

```bash
uv run pytest        # tests run offline against fake NYPL and Claude responses
uv run ruff check .  # lint
uv run ruff format . # format
```

### Project layout

```
src/nypl_api_bridge/
  api.py        # async client for the NYPL v2 API (auth, input checks, response unwrapping)
  server.py     # FastMCP server: tool definitions and instructions for Claude
  remote.py     # the same server over HTTP, for hosting online
  personas.py   # persona definitions and the base system prompt
  chat.py       # one chat turn: Claude plus MCP tool calls
  app.py        # Streamlit UI
  launch.py     # `nypl-chat` entry point: loads .env, checks keys, starts Streamlit
  logs.py       # logging setup: stderr plus logs/nypl.log, with a turn ID per question
tests/          # offline tests for the server, the HTTP app and the chat loop
index.py        # Vercel entrypoint: builds the HTTP app from environment variables
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `NYPL_API_TOKEN is missing` | Add it to `.env` in the folder you run the command from. |
| `NYPL API rejected the token (401)` | Check the token value. It's the token string from your NYPL email, not your password. |
| `AuthenticationError` on the first question | `ANTHROPIC_API_KEY` is missing or invalid, or your Console account has no credits. |
| `Port 8501 is already in use` | Stop the other Streamlit app, or change `PORT` in `launch.py`. |
| Every NYPL call fails | The deprecated API may have been switched off. Check <https://api.repo.nypl.org/>. |
