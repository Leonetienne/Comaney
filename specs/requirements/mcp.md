# MCP Server

Sources: `mcp_server/`, `api/registry.py`, `feusers/templates/feusers/profile.html` (Agent keys card),
docs `user-manual/ai-assistants.md`. Protocol: Model Context Protocol, Streamable HTTP transport.

## Transport

### Endpoint
`req~mcp.endpoint~1`

The system shall serve an MCP server at `/mcp` that accepts JSON-RPC requests (single or batched) by POST, answers each request with one JSON response, answers a POST carrying only notifications with 202 and no body, keeps no session between requests, and answers other methods with 405.

Covers:
- `feat~mcp~1`

### Protocol versions
`req~mcp.versions~1`

When a client sends `initialize`, the system shall confirm the requested protocol version if it supports it (2025-06-18, 2025-03-26, 2024-11-05) and offer 2025-06-18 otherwise.

Covers:
- `feat~mcp~1`

### Server instructions
`req~mcp.instructions~1`

When a client sends `initialize`, the system shall return instructions explaining the domain (owners, participants and overlays, transaction types, currency, financial periods, the query language, notifications to other people), telling the agent to look features up in the user manual before explaining them or answering support questions, to preview two-step operations and ask the user before deleting or contacting others, and that missing tools mean a restricted key.

Covers:
- `feat~mcp~1`

### Tools from the registry
`req~mcp.tools~1`

The system shall offer every API operation (see [api.md](api.md)) the key allows as a tool with the operation's name, description, required permission and JSON schema, marked `readOnlyHint` for read operations, `destructiveHint` for operations that delete or irreversibly replace data, and never `openWorldHint`.

Covers:
- `feat~mcp~1`

### Tool errors
`req~mcp.errors~1`

If a tool call fails validation or a business rule, then the system shall return a result flagged `isError` with a message naming the offending argument or rule; an unexpected server failure shall be logged and reported to the agent as a failed tool call.

Covers:
- `feat~mcp~1`

### Origin check
`req~mcp.origin~1`

If a request carries an `Origin` header naming a host other than this site, then the system shall answer 403.

Rationale:
Protects against DNS rebinding from browsers; non-browser clients send no Origin.

Covers:
- `feat~mcp~1`

Tags: Security

## Agent keys

### Bearer authentication
`req~mcp.auth~1`

The system shall authenticate every MCP request by `Authorization: Bearer <agent key>` and answer 401 if the key is missing, unknown or revoked, or belongs to an inactive or demo account.

Covers:
- `feat~mcp~1`

Tags: Security

### Keys stay separate
`req~mcp.keys.separate~1`

The system shall accept agent keys only at `/mcp` and the API key only under `/api/v2/`.

Covers:
- `feat~mcp~1`

Tags: Security

### Multiple keys
`req~mcp.keys.multiple~1`

The system shall let a feuser create any number of agent keys in the profile's "Agent keys (MCP)" card, each with a name of up to 64 characters ("Agent" if left empty).

Rationale:
One key per assistant lets a feuser restrict or revoke one without affecting the others.

Covers:
- `feat~mcp~1`

### Key format and storage
`req~mcp.keys.format~1`

When a feuser creates an agent key, the system shall generate `cmy_` followed by 256 random bits, show the full key exactly once with a copy button, and store only its SHA-256 hash and its first 12 characters.

Covers:
- `feat~mcp~1`

Tags: Security

### Key list
`req~mcp.keys.list~1`

The system shall list a feuser's agent keys with name, visible prefix, creation date, last use (to the minute, or "never used") and "Full access" or "Restricted", and show the MCP server address with a copy button.

Covers:
- `feat~mcp~1`

Tags: UI

### Key revocation
`req~mcp.keys.revoke~1`

When a feuser confirms revoking an agent key, the system shall delete it so it no longer authenticates.

Covers:
- `feat~mcp~1`

Tags: Security

### Demo restriction
`req~mcp.keys.demo~1`

If a demo user requests an agent key, then the system shall refuse it; the card shows the create button disabled.

Covers:
- `feat~mcp~1`

Tags: Demo, Security

## Permissions

### Permission concerns
`req~mcp.scopes.concerns~1`

The system shall group the API operations into these concerns, each with a separate read and write permission per agent key: Expenses, Recurring expenses, Categories and tags, Dashboard, Projects, Contacts, Approvals and settlements, Catalog partnership, Account settings.

Covers:
- `feat~mcp~1`

### Default permissions
`req~mcp.scopes.default~1`

When an agent key is created, the system shall grant it read and write on every concern.

Covers:
- `feat~mcp~1`

### Restrict panel
`req~mcp.scopes.restrict~1`

When a feuser clicks "Restrict" on an agent key, the system shall show one row per concern with a Read and a Write checkbox and save the selection for that key with "Save permissions".

Covers:
- `feat~mcp~1`

Tags: UI

### Write implies read
`req~mcp.scopes.write-read~1`

The system shall treat write permission on a concern as including read: ticking Write ticks Read, unticking Read unticks Write, and a stored write permission always counts as read.

Covers:
- `feat~mcp~1`

### Tool list follows permissions
`req~mcp.scopes.list~1`

When a client sends `tools/list`, the system shall list only the operations the key's permissions allow, plus the manual tools.

Covers:
- `feat~mcp~1`

Tags: Security

### Permission enforcement
`req~mcp.scopes.enforce~1`

If a client calls an operation the key's permissions do not allow, then the system shall perform no part of it and return an error result naming the missing concern and permission and where the feuser can change it.

Covers:
- `feat~mcp~1`

Tags: Security

### Excluded actions
`req~mcp.excluded~1`

The system shall offer no tool that creates or deletes an account, changes the password or email address, manages second factors, manages the API key or agent keys, or reads or changes own AI settings.

Rationale:
A leaked agent key must not turn into an account takeover or a credential leak.

Covers:
- `feat~mcp~1`

Tags: Security

## User manual

### Manual tools
`req~mcp.docs.tools~1`

The system shall offer every agent key, whatever its permissions, a `docs_search` tool that ranks user manual pages by the query's words and returns path, title, public URL and a snippet, and a `docs_read` tool that returns one page's markdown and public URL.

Covers:
- `feat~mcp~1`

### Manual resources
`req~mcp.docs.resources~1`

The system shall list every user manual page as a markdown resource `comaney://docs/user-manual/<path>` and, for keys with Dashboard read permission, the card YAML reference as `comaney://reference/dashboard-cards`.

Covers:
- `feat~mcp~1`
