# Security Policy

> In italiano: per segnalare una vulnerabilità usa "Report a vulnerability" nella
> tab Security del repository, mai una issue pubblica. Il modello di minaccia
> completo è in [`docs/sicurezza.md`](docs/sicurezza.md).

TreasureIQ is a prototype built for the SuperAgents Civic Hackathon 2026. It
matches a citizen's profile with municipal services and benefits, reading public
municipal portals.

## Reporting a vulnerability

- Use GitHub **private vulnerability reporting**: Security tab → "Report a
  vulnerability". Do not open a public issue or PR for a security problem.
- Include affected path or endpoint, steps to reproduce, and impact.
- Expect an acknowledgement within 5 working days. This is a volunteer-run
  project: there is no bug bounty.

## Supported versions

Only the `main` branch is supported. There are no maintained releases.

## Scope

In scope:

- The API in `api/` and the web app in `web/`.
- Abuse of the API (cost, resource exhaustion, scraping amplification).
- Prompt injection through content fetched from municipal portals.
- Leaks of citizen profile data to logs, third parties or other sessions.
- Secrets or personal data committed to the repository.

Out of scope:

- Weaknesses of third-party municipal portals themselves.
- The SPID flow: it is simulated for the hackathon and verifies no real credential.
- Findings that need a malicious local operator with access to the host.
- Volumetric denial of service against a demo deployment.

## How the project handles data and secrets

- API keys (for example `ANTHROPIC_API_KEY`, `BRAVE_SEARCH_API_KEY`) live only
  in the deployment environment, never in the repository.
- The chat works without any model; models only narrate, and receive the
  minimum profile data needed.
- Crawling of municipal portals follows the courtesy limits in
  `docs/sicurezza.md`.

Known limits and the ordered list of open hardening work are documented in
[`docs/sicurezza.md`](docs/sicurezza.md).
