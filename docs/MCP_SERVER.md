# MCP server

`src/inkfall/mcp_server.py` exposes the vault to MCP clients (Claude Code, Claude Desktop, any client that speaks
the Model Context Protocol over stdio). It is built on the official Python SDK (`mcp==2.3.0`, `MCPServer`).

## Tools

| Tool | Arguments | Returns |
|---|---|---|
| `search` | `query` (≤ 500 chars), `as_of` (ISO date, optional), `method` (`bm25` / `dense` / `hybrid`) | extractive answer sentences with exact citations (version id + character offsets), the top authorized source passages with their injection flags, conflicts, abstention |
| `fetch_document` | `version_id` | full text + metadata of one version the identity may read |
| `cite` | `version_id`, `char_start`, `char_end`, optional `quote` | whether the citation is valid for this identity, and the exact stored quote |

All three are annotated read-only (`readOnlyHint`, not destructive, idempotent, closed world). They call the same
functions as the HTTP API: `authorized_versions` before retrieval, `get_authorized_version` for reads,
`verify_citation` for citations, and they write audit events (`via: mcp`).

## Security model

- **Identity is bound at launch.** The server reads `INKFALL_MCP_USER` (or `--user`) once, when it starts. No tool
  has a `user`, `tenant`, `role` or similar parameter, and the identity cannot change while the process runs, so a
  model talking to the server cannot ask to act as someone else. `test_tools_take_no_identity_arguments` checks the
  published input schemas; `test_identity_arguments_cannot_escalate` sends `user`/`role`/`tenant` arguments anyway.
- **No existence oracle.** A version the identity may not read returns exactly the same `not_found` error as an id
  that does not exist, from both `fetch_document` and `cite`. `test_forbidden_equals_missing_and_zero_forbidden_content`
  checks this for every identity × every unreadable version, and runs a `search` built from each unreadable
  version's own title/text, asserting that none of its canaries (doc key, 60-character text prefixes not present in
  any readable document) appear in the result.
- **Untrusted content.** Document text in results is data, not instructions: results carry
  `untrusted_content: true` and per-passage `injection_flags`, and the server instructions say so. Per the MCP
  specification, clients should treat tool descriptions and annotations as untrusted unless the server is trusted;
  this server's descriptions are static strings that never contain document content.
- **What it does not do.** No authentication of the MCP client itself (stdio = whoever can start the process, the
  same trust as the mock login on 127.0.0.1); no write tools; no generation (the client's own model does that).

## Add it to Claude Code

From the repository root, after `make setup` and `make seed`:

```bash
claude mcp add inkfall-vault -e INKFALL_MCP_USER=dana.whitcombe -- uv run --directory "$PWD" python -m inkfall.mcp_server
```

Then ask Claude Code something like "Use inkfall-vault to find the Orion SLA availability commitment and cite it".
Change the identity by removing and re-adding the server with a different `INKFALL_MCP_USER`.

## Add it to Claude Desktop

Add an entry to `claude_desktop_config.json` (Settings → Developer → Edit Config), with the absolute path of your
clone, and restart Claude Desktop:

```json
{
  "mcpServers": {
    "inkfall-vault": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/inkfall-vault", "python", "-m", "inkfall.mcp_server"],
      "env": { "INKFALL_MCP_USER": "dana.whitcombe" }
    }
  }
}
```

If `uv` is not on the PATH that Claude Desktop sees, use its absolute path (`which uv`).

## Run / test locally

```bash
make mcp                    # INKFALL_MCP_USER=dana.whitcombe by default; speaks MCP on stdin/stdout
uv run pytest tests/test_mcp_server.py -s
```

The tests use the SDK's in-process `Client(server)` against the real tools and the seeded test database, plus one
test that launches the server as a real stdio subprocess.
