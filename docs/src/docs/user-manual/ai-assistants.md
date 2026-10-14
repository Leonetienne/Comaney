# AI Assistants (MCP)

You can connect an AI assistant such as Claude to your Comaney account. The assistant then works with your data on your behalf: it answers questions about your spending, records expenses, sets up projects, and more. It connects through MCP (Model Context Protocol), a standard many assistants support.

Things you can ask, for example:

- "How much did I spend at Amazon this week?"
- "I got groceries at Edeka for 15 euros." … "Oh, it was 13. 2 euros were for parking."
- "We're leaving for Ibiza tomorrow. Create a project and invite Berta and Bernd from my contacts."
- "Is anything waiting for my approval?"
- "Create a dashboard with the cards I need for my business."
- "Turn off all email notifications."

The assistant can also look things up in this manual, so you can ask it how Comaney works.

## Creating an agent key

Each assistant gets its own agent key, so you can restrict or revoke one without affecting the others.

1. Go to **Settings → Advanced → Agent keys (MCP)**.
2. Enter a name, for example "Claude Desktop", and click **Create agent key**.
3. Copy the key right away. It is shown only once.

## Connecting your assistant

Your assistant needs two things:

- the **MCP server address** shown in the Agent keys card (it ends in `/mcp`)
- the header `Authorization: Bearer <your agent key>`

With Claude Code, for example:

```bash
claude mcp add --transport http comaney https://your-comaney-address/mcp --header "Authorization: Bearer cmy_..."
```

Many other assistants take a configuration like this:

```json
{
  "mcpServers": {
    "comaney": {
      "type": "http",
      "url": "https://your-comaney-address/mcp",
      "headers": { "Authorization": "Bearer cmy_..." }
    }
  }
}
```

Assistants that only offer sign-in style connectors cannot connect yet.

## Restricting what an assistant may do

A new key may do everything listed below. Click **Restrict** next to a key to choose, per area, whether the assistant may only **read** or also **write** (change, create, delete). Write always includes read.

| Area | Covers |
|---|---|
| Expenses | Your expenses, searching and summing them, your own classification of shared expenses |
| Recurring expenses | Recurring expense templates |
| Categories and tags | Your categories and tags |
| Dashboard | Dashboards and their cards |
| Projects | Projects, members and invitations |
| Contacts | Contacts, offline contacts and auto-accept |
| Approvals and settlements | Things waiting for your decision, recording settlements |
| Catalog partnership | Your Catalog Partnership |
| Account settings | Name, currency, financial month and notification settings |

Looking things up in this manual is always allowed.

## What an assistant can never do

No key, however unrestricted, lets an assistant create or delete your account, change your email address or password, manage two-factor authentication, see or change your API key, agent keys or your own AI settings.

Before deleting several expenses at once or joining a Catalog Partnership, the assistant first gets a preview of what would happen and has to confirm it. A good assistant shows you that preview and asks you first.

Actions behave exactly as on the website: sharing an expense, inviting someone or recording a settlement notifies the other people involved.

## Revoking a key

Click **Revoke** next to the key. The assistant loses access immediately.

The Agent keys card shows when each key was last used.

!!! note
    Agent keys are not available on demo accounts.
