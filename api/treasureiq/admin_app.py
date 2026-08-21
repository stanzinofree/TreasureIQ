"""Read-only operator view for sweep and source-inventory diagnostics.

This service is intentionally separate from the citizen API. It has no write
routes and is published on loopback by compose; production access is expected
through an SSH tunnel until authentication is introduced.
"""

from __future__ import annotations

import json
import os
import sqlite3
from html import escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

DATA_DIR = Path(os.environ.get("TREASUREIQ_DATA_DIR", "/data"))
LIVE_DIR = Path(os.environ.get("TREASUREIQ_LIVE_DIR", "/live"))
DB_PATH = DATA_DIR / "storico.db"

app = FastAPI(title="TreasureIQ Admin", docs_url="/docs", redoc_url=None)

_STYLE = """
:root{--paper:#fff;--ink:#0a0a0a;--muted:#5b6472;--mint:#b8f5d0;--lemon:#fff79a;--lavender:#d8c6ff;--sky:#b9e5ff;--pink:#ffbcd9;--acid:#b8ff00;--yellow:#ffe600;--cyan:#00e8ff;--shadow:4px 4px 0 var(--ink);--mono:'Fira Code','SFMono-Regular',Consolas,monospace}
*,*:before,*:after{box-sizing:border-box}
html{background:var(--paper)}
body{font:15px/1.55 ui-rounded,'Avenir Next',system-ui,sans-serif;max-width:1280px;margin:0 auto;padding:0 24px 56px;color:var(--ink);background:radial-gradient(circle at 5% 0%,var(--mint),transparent 30%),radial-gradient(circle at 100% 10%,var(--lavender),transparent 34%),var(--paper);min-height:100vh}
body:before{content:"";position:fixed;inset:0;pointer-events:none;z-index:-1;background-image:linear-gradient(var(--ink) 1px,transparent 1px),linear-gradient(90deg,var(--ink) 1px,transparent 1px);background-size:32px 32px;opacity:.035}
a{color:#075fc2;font-weight:700;text-underline-offset:3px}a:hover{color:#000;background:var(--yellow)}
code{background:#f0f2f5;border:1px solid #b9c0ca;border-radius:5px;padding:2px 5px;font-family:var(--mono);font-size:.85em;word-break:break-all}
h1{font-size:clamp(2rem,5vw,3.6rem);line-height:1;margin:28px 0 10px;letter-spacing:-.04em}h2{margin-top:30px;letter-spacing:-.02em}h3{margin-bottom:8px}
p{color:#374151}.topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:20px 0 16px;border-bottom:2px dashed var(--ink)}
.brand{display:inline-flex;align-items:center;gap:9px;background:var(--acid);border:2.5px solid var(--ink);border-radius:999px;padding:7px 15px;font-weight:900;box-shadow:3px 3px 0 var(--ink);transform:rotate(-1deg)}
.brand-mark{display:inline-grid;place-items:center;width:24px;height:24px;background:var(--paper);border:2px solid var(--ink);border-radius:50%}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a{display:inline-block;background:var(--paper);border:2px solid var(--ink);border-radius:999px;padding:5px 12px;text-decoration:none;box-shadow:2px 2px 0 var(--ink);font-size:13px}.nav a:hover{background:var(--yellow);transform:translate(-1px,-1px)}
main,article,.grid>article{background:var(--paper);border:2.5px solid var(--ink);border-radius:16px;box-shadow:var(--shadow)}
main{padding:20px}article{padding:18px}.grid>article{box-shadow:3px 3px 0 var(--ink)}
main article:nth-child(4n+1){background:var(--mint)}main article:nth-child(4n+2){background:var(--lemon)}main article:nth-child(4n+3){background:var(--lavender)}main article:nth-child(4n+4){background:var(--sky)}
table{width:100%;border-collapse:separate;border-spacing:0;overflow:hidden;background:var(--paper);border:2.5px solid var(--ink);border-radius:14px;box-shadow:3px 3px 0 var(--ink)}th,td{padding:11px 12px;border-bottom:1.5px solid #cbd5e1;text-align:left}th{background:var(--acid);font-size:12px;text-transform:uppercase;letter-spacing:.08em}tr:last-child td{border-bottom:0}tbody tr:hover td{background:var(--yellow)}
input{font:inherit;border:2px solid var(--ink);border-radius:999px;padding:11px 15px;background:var(--paper);box-shadow:2px 2px 0 var(--ink)}
.search-button,.clear-search{display:inline-block;margin-left:8px;font:700 14px inherit;border:2px solid var(--ink);border-radius:999px;padding:9px 15px;background:var(--acid);color:var(--ink);box-shadow:2px 2px 0 var(--ink);text-decoration:none;cursor:pointer}.clear-search{background:var(--paper)}.result-note{font-size:13px;color:var(--muted)}
pre{background:#f4f5f7;border:2px solid var(--ink);border-radius:10px;padding:14px;font:12px/1.55 var(--mono);white-space:pre-wrap;word-break:break-word;box-shadow:3px 3px 0 var(--ink)}
details{background:var(--paper);border:2px solid var(--ink);border-radius:12px;padding:10px 14px;margin:12px 0;box-shadow:2px 2px 0 var(--ink)}summary{cursor:pointer;font-weight:800}.pill{display:inline-block;border:2px solid var(--ink);border-radius:999px;padding:2px 9px;background:var(--acid);font:700 12px var(--mono)}
@media(max-width:760px){body{padding:0 13px 36px}.grid,main{display:block!important}.grid>article{margin:12px 0}table{display:block;overflow-x:auto;white-space:nowrap}.topbar{align-items:flex-start}}
"""


def _nav(active: str = "") -> str:
    links = (("Overview", "/"), ("Comuni", "/comuni"), ("Pattern", "/patterns"), ("API", "/docs"))
    return (
        "<header class='topbar'><a class='brand' href='/'><span class='brand-mark'>✦</span>TreasureIQ · Admin</a>"
        "<nav class='nav'>"
        + "".join(
            f"<a href='{href}'" + (" aria-current='page'" if label.lower() == active else "") + f">{label}</a>"
            for label, href in links
        )
        + "</nav></header>"
    )


def _inventory_files() -> list[Path]:
    return sorted((LIVE_DIR / "inventario").glob("*.json")) if (LIVE_DIR / "inventario").exists() else []


def _recognition_files() -> list[Path]:
    root = LIVE_DIR / "riconoscimento"
    return sorted(root.glob("**/*.json")) if root.exists() else []


def _check_files() -> list[Path]:
    root = LIVE_DIR / "check"
    return sorted(root.glob("**/*.json")) if root.exists() else []


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _db_connection() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        return None
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def _latest_rows(limit: int = 100, query: str = "") -> list[dict[str, Any]]:
    conn = _db_connection()
    if conn is None:
        return []
    conn.row_factory = sqlite3.Row
    try:
        query = query.strip()
        where = ""
        params: list[Any] = []
        if query:
            where = (
                "WHERE p.nome LIKE ? OR CAST(p.codice_istat AS TEXT) LIKE ? "
                "OR p.piattaforma LIKE ? OR p.piattaforma_at LIKE ?"
            )
            params = [f"%{query}%"] * 4
        rows = conn.execute(
            f"""
            SELECT p.*
            FROM portale_snapshot p
            JOIN (
              SELECT codice_istat, MAX(rilevato_il) AS giorno
              FROM portale_snapshot GROUP BY codice_istat
            ) latest ON latest.codice_istat = p.codice_istat
                       AND latest.giorno = p.rilevato_il
            {where}
            ORDER BY p.codice_istat
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _overview() -> dict[str, Any]:
    conn = _db_connection()
    snapshot: dict[str, Any] = {"latest_day": None, "rows": 0, "errors": 0, "platforms": {}}
    if conn is not None:
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT MAX(rilevato_il) AS giorno, COUNT(*) AS righe, "
                "SUM(CASE WHEN errore IS NOT NULL THEN 1 ELSE 0 END) AS errori "
                "FROM portale_snapshot"
            ).fetchone()
            snapshot.update({
                "latest_day": row["giorno"],
                "rows": row["righe"] or 0,
                "errors": row["errori"] or 0,
            })
            snapshot["platforms"] = {
                row["piattaforma"] or "ignota": row["n"]
                for row in conn.execute(
                    "SELECT piattaforma, COUNT(*) AS n FROM portale_snapshot "
                    "WHERE rilevato_il = (SELECT MAX(rilevato_il) FROM portale_snapshot) "
                    "GROUP BY piattaforma ORDER BY n DESC"
                )
            }
        finally:
            conn.close()
    inventories = [_read_json(path) for path in _inventory_files()]
    inventories = [item for item in inventories if item is not None]
    recognitions = [_read_json(path) for path in _recognition_files()]
    recognitions = [item for item in recognitions if item is not None]
    checks = [_read_json(path) for path in _check_files()]
    checks = [item for item in checks if item is not None]
    return {
        "snapshot": snapshot,
        "inventories": len(inventories),
        "service_portal_candidates": sum(
            len(item.get("service_portals", ())) for item in inventories
        ),
        "base_platforms": {
            platform: sum(1 for item in inventories if item.get("base_platform") == platform)
            for platform in sorted({item.get("base_platform") for item in inventories if item.get("base_platform")})
        },
        "inventory_source_health": {
            "reachable": sum(1 for item in inventories if item.get("base_source_health") is True),
            "unreachable": sum(1 for item in inventories if item.get("base_source_health") is False),
            "unknown": sum(1 for item in inventories if item.get("base_source_health") is None),
        },
        "inventory_failures": _count_values(
            [item.get("base_failure_reason") for item in inventories]
        ),
        "recognitions": len(recognitions),
        "recognition_plugins": _count_values(
            [item.get("connector_id") for item in recognitions]
        ),
        "recognition_confidence": _count_values(
            [item.get("confidence") for item in recognitions]
        ),
        "recognitions_low_score": sum(
            1 for item in recognitions if (item.get("recognition_score") or 0) < 0.80
        ),
        "coverage_low": sum(
            1 for item in recognitions
            if item.get("coverage_score") is not None and item["coverage_score"] < 0.80
        ),
        "checks": len(checks),
        "checks_degraded": sum(1 for item in checks if item.get("status") != "ok"),
    }


def _bucket(value: Any) -> str:
    if value is None:
        return "unknown"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if number >= 0.8:
        return "high"
    if number >= 0.6:
        return "medium"
    return "low"


def _count_values(values: list[Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        if value in (None, ""):
            continue
        key = str(value)
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items(), key=lambda item: (-item[1], item[0])))


def _patterns() -> dict[str, Any]:
    rows = _latest_rows(10000)
    inventories = [_read_json(path) or {} for path in _inventory_files()]
    recognitions = [_read_json(path) or {} for path in _recognition_files()]
    checks = [_read_json(path) or {} for path in _check_files()]

    def count(values: list[Any]) -> dict[str, int]:
        result: dict[str, int] = {}
        for value in values:
            key = str(value or "unknown")
            result[key] = result.get(key, 0) + 1
        return dict(sorted(result.items(), key=lambda item: (-item[1], item[0])))

    candidates = [candidate for item in inventories for candidate in item.get("service_portals", ())]
    platform_groups: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        platform = str(candidate.get("provider_hint") or "unknown")
        group = platform_groups.setdefault(platform, {"entrypoints": 0, "roles": {}})
        group["entrypoints"] += 1
        role = str(candidate.get("role") or "unknown")
        group["roles"][role] = group["roles"].get(role, 0) + 1
    return {
        "municipalities": len(rows),
        "base_platforms": count([row.get("piattaforma") for row in rows]),
        "source_identity_status": count([item.get("status") for item in checks]),
        "recognition_score": count([_bucket(item.get("recognition_score")) for item in recognitions]),
        "coverage_score": count([_bucket(item.get("coverage_score")) for item in recognitions]),
        "recognition_actions": count([item.get("action") for item in recognitions]),
        "recognition_plugins": count([item.get("connector_id") for item in recognitions]),
        "recognition_fingerprint_versions": count(
            [item.get("fingerprint_version") for item in recognitions]
        ),
        "recognition_confidence": count([item.get("confidence") for item in recognitions]),
        "recognition_failures": count([item.get("failure_reason") for item in recognitions]),
        "service_portal_providers": count([item.get("provider_hint") for item in candidates]),
        "service_portal_roles": count([item.get("role") for item in candidates]),
        "service_portal_platforms": platform_groups,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    return _overview()


@app.get("/api/patterns")
def patterns() -> dict[str, Any]:
    return _patterns()


@app.get("/api/municipalities")
def municipalities(
    limit: int = Query(default=1000, ge=1, le=10000),
    q: str = Query(default="", max_length=120),
) -> list[dict[str, Any]]:
    inventories = {
        path.stem: _read_json(path) or {} for path in _inventory_files()
    }
    recognitions = {
        path.stem: _read_json(path) or {} for path in _recognition_files()
    }
    checks = {path.stem: _read_json(path) or {} for path in _check_files()}
    result = []
    for row in _latest_rows(limit, query=q):
        inventory = inventories.get(row["codice_istat"], {})
        result.append({
            "codice_istat": row["codice_istat"],
            "nome": row["nome"],
            "piattaforma": row["piattaforma"],
            "piattaforma_at": row.get("piattaforma_at"),
            "stato_http": row["stato_http"],
            "errore": row["errore"],
            "service_portals": len(inventory.get("service_portals", ())),
            "base_platform": inventory.get("base_platform"),
            "recognition": recognitions.get(row["codice_istat"]),
            "source_identity": checks.get(row["codice_istat"]),
        })
    return result


@app.get("/api/municipalities/{source_id}")
def municipality(source_id: str) -> dict[str, Any]:
    inventory_path = LIVE_DIR / "inventario" / f"{source_id}.json"
    inventory = _read_json(inventory_path)
    recognition = {
        path.parent.name: _read_json(path)
        for path in _recognition_files()
        if path.stem == source_id
    }
    source_identity = {
        path.parent.name: _read_json(path)
        for path in _check_files()
        if path.stem == source_id
    }
    conn = _db_connection()
    rows: list[dict[str, Any]] = []
    if conn is not None:
        conn.row_factory = sqlite3.Row
        try:
            rows = [
                dict(row) for row in conn.execute(
                    "SELECT rilevato_il, nome, piattaforma, piattaforma_at, stato_http, "
                    "errore, richieste, secondi FROM portale_snapshot "
                    "WHERE codice_istat = ? ORDER BY rilevato_il DESC LIMIT 20",
                    (source_id,),
                )
            ]
        finally:
            conn.close()
    if inventory is None and not rows:
        raise HTTPException(status_code=404, detail="Comune non presente nell'inventario")
    return {
        "source_id": source_id,
        "inventory": inventory,
        "recognition": recognition,
        "source_identity": source_identity,
        "snapshots": rows,
    }


@app.get("/comuni", response_class=HTMLResponse)
def municipalities_page(q: str = Query(default="", max_length=120)) -> str:
    # Keep the DOM bounded: filtering thousands of rendered rows in the
    # browser made every keystroke look like a Docker freeze. Search is now a
    # parameterized SQLite query and the page renders at most 500 rows.
    rows = municipalities(limit=500, q=q)
    body = "".join(
        "<tr>"
        f"<td><a href='/comune/{escape(str(row['codice_istat']))}'>{escape(str(row['nome']))}</a></td>"
        f"<td>{escape(str(row['codice_istat']))}</td>"
        f"<td>{escape(str(row.get('piattaforma') or '—'))}</td>"
        f"<td>{escape(str((row.get('recognition') or {}).get('recognition_score', '—')))}</td>"
        f"<td>{escape(str((row.get('recognition') or {}).get('coverage_score', '—')))}</td>"
        f"<td>{escape(str((row.get('source_identity') or {}).get('status', '—')))}</td>"
        f"<td>{row.get('service_portals', 0)}</td>"
        "</tr>"
        for row in rows
    )
    return f"""<!doctype html><html lang="it"><meta charset="utf-8"><title>TIQ Admin · Comuni</title>
<style>{_STYLE} input{{width:100%;margin:18px 0}}</style>
{_nav("comuni")}
<h1>Comuni e analisi</h1><p><a href="/">← overview</a> · <a href="/patterns">pattern</a></p>
<form method="get" action="/comuni"><input id="q" name="q" value="{escape(q)}" placeholder="Cerca comune, codice o piattaforma" aria-label="Cerca comune, codice o piattaforma"><button class="search-button" type="submit">Cerca</button>{f"<a class='clear-search' href='/comuni'>Azzera</a>" if q else ""}</form>
<table><thead><tr><th>Comune</th><th>ISTAT</th><th>BASE</th><th>match</th><th>coverage</th><th>fonte</th><th>SP</th></tr></thead>
<tbody id="rows">{body}</tbody></table>
<p class="result-note">Mostrati {len(rows)} risultati{f" per <b>{escape(q)}</b>" if q else ""}. La ricerca interroga il catalogo lato server.</p>
"""


@app.get("/comune/{source_id}", response_class=HTMLResponse)
def municipality_page(source_id: str) -> str:
    data = municipality(source_id)
    inventory = data.get("inventory") or {}
    identity = next(iter((data.get("source_identity") or {}).values()), None) or {}
    recognition = next(iter((data.get("recognition") or {}).values()), None) or {}
    inventory_health = inventory.get("base_source_health")
    inventory_health_label = (
        "raggiungibile" if inventory_health is True
        else "irraggiungibile" if inventory_health is False
        else "non verificata"
    )
    candidates = inventory.get("service_portals", ())
    grouped: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        grouped.setdefault(str(candidate.get("provider_hint") or "da_classificare"), []).append(candidate)
    portal_groups = "".join(
        f"<h3>{escape(platform)} · {len(items)} entrypoint</h3><ul>" +
        "".join(
            f"<li>{escape(str(item.get('role') or 'unknown'))} · "
            f"<a href='{escape(str(item.get('url') or '#'))}' target='_blank' rel='noreferrer'>"
            f"{escape(str(item.get('label') or item.get('url') or 'link'))}</a></li>"
            for item in items
        ) + "</ul>"
        for platform, items in sorted(grouped.items())
    ) or "<p>nessun entrypoint SP</p>"
    portal_rows = "".join(
        f"<li><b>{escape(str(item.get('role') or 'unknown'))}</b> · "
        f"{escape(str(item.get('provider_hint') or 'unknown'))} · "
        f"<a href='{escape(str(item.get('url') or '#'))}' target='_blank' rel='noreferrer'>"
        f"{escape(str(item.get('label') or item.get('url') or 'link'))}</a></li>"
        for item in candidates
    ) or "<li>nessun candidato SP</li>"
    snapshots = "".join(
        f"<tr><td>{escape(str(row.get('rilevato_il')))}</td><td>{escape(str(row.get('piattaforma') or '—'))}</td>"
        f"<td>{escape(str(row.get('stato_http') or '—'))}</td><td>{escape(str(row.get('richieste') or '—'))}</td>"
        f"<td>{escape(str(row.get('secondi') or '—'))}</td><td>{escape(str(row.get('errore') or '—'))}</td></tr>"
        for row in data.get("snapshots", ())
    ) or "<tr><td colspan='6'>nessuno snapshot</td></tr>"
    return f"""<!doctype html><html lang="it"><meta charset="utf-8"><title>TIQ Admin · {escape(source_id)}</title>
<style>{_STYLE} .grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}</style>
{_nav("comuni")}
<h1>{escape(str(data.get('source_id')))}</h1><p><a href="/comuni">← comuni</a> · <a href="/patterns">pattern</a></p>
<div class="grid"><article><b>Fonte</b><p>status: {escape(str(identity.get('status','—')))}<br>completezza: {escape(str(identity.get('completeness_score','—')))}<br>HTTP: {escape(str(identity.get('identity',{}).get('http_status','—')))}</p></article>
<article><b>Inventario</b><p>BASE: {escape(inventory_health_label)}<br>causa: {escape(str(inventory.get('base_failure_reason') or '—'))}<br>URL: <a href="{escape(str(inventory.get('base_url') or '#'))}" target="_blank" rel="noreferrer">entrypoint</a></p></article>
<article><b>BASE</b><p>match: {escape(str(recognition.get('recognition_score','—')))}<br>coverage: {escape(str(recognition.get('coverage_score','—')))}<br>azione: {escape(str(recognition.get('action','—')))}</p></article>
<article><b>Riconoscimento</b><p>plugin: {escape(str(recognition.get('connector_id','—')))}<br>confidence: {escape(str(recognition.get('confidence','—')))}<br>score: {escape(str(recognition.get('recognition_score','—')))}</p></article>
<article><b>Versioni</b><p>connettore: {escape(str(recognition.get('connector_version','—')))}<br>fingerprint: {escape(str(recognition.get('fingerprint_version','—')))}<br>impronta: <code>{escape(str(recognition.get('fingerprint','—')))}</code><br>causa: {escape(str(recognition.get('failure_reason','—')))}</p></article></div>
<h2>Superficie SP</h2>{portal_groups}
<details><summary>Elenco completo entrypoint</summary><ul>{portal_rows}</ul></details>
<h2>Storico sweep</h2><table><tr><th>Data</th><th>BASE</th><th>HTTP</th><th>Richieste</th><th>Secondi</th><th>Errore</th></tr>{snapshots}</table>
<h2>JSON diagnostico</h2><pre>{escape(json.dumps(data, ensure_ascii=False, indent=2, default=str))}</pre>
"""


@app.get("/patterns", response_class=HTMLResponse)
def patterns_page() -> str:
    data = _patterns()
    sections = "".join(
        f"<article><h2>{escape(str(title))}</h2><ul>" +
        "".join(f"<li>{escape(str(key))}: <b>{value}</b></li>" for key, value in values.items()) +
        "</ul></article>"
        for title, values in data.items() if isinstance(values, dict)
    )
    return f"""<!doctype html><html lang="it"><meta charset="utf-8"><title>TIQ Admin · Pattern</title>
<style>{_STYLE} main{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}</style>
{_nav("pattern")}
<h1>Pattern comuni</h1><p><a href="/">← overview</a> · <a href="/comuni">comuni</a></p><main>{sections}</main>
<p><a href="/api/patterns">JSON patterns</a></p>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    data = _overview()
    snapshot = data["snapshot"]
    platforms = "".join(
        f"<li>{escape(str(name))}: {count}</li>"
        for name, count in data["base_platforms"].items()
    ) or "<li>nessun inventario</li>"
    return f"""<!doctype html>
<html lang="it"><meta charset="utf-8"><title>TIQ Admin</title>
<style>{_STYLE} main{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}</style>
{_nav("overview")}
<h1>TreasureIQ · Admin read-only</h1>
<p>Servizio operativo separato. Nessuna rotta di scrittura.</p>
<main><article><b>Ultimo sweep</b><p>{escape(str(snapshot['latest_day'] or 'mai'))}</p></article>
<article><b>Righe snapshot</b><p>{snapshot['rows']}</p></article>
<article><b>Errori registrati</b><p>{snapshot['errors']}</p></article>
<article><b>Inventari fonte</b><p>{data['inventories']}</p></article>
<article><b>Candidati SP</b><p>{data['service_portal_candidates']}</p></article>
<article><b>Riconoscimenti</b><p>{data['recognitions']} · score bassi: {data['recognitions_low_score']}</p></article>
<article><b>Check fonte</b><p>{data['checks']} · degradati: {data['checks_degraded']}</p></article>
<article><b>API</b><p><a href="/docs">OpenAPI</a></p></article></main>
<h2>Piattaforme BASE negli inventari</h2><ul>{platforms}</ul>
<p><a href="/comuni">Consulta ogni comune</a> · <a href="/patterns">Pattern comuni</a> · <a href="/api/municipalities">JSON comuni</a> · <a href="/api/overview">JSON overview</a></p>
"""
