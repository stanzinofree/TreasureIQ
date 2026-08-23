//! Rust mirror of `api/treasureiq/chat/intent_scorer.py::score_intent`.
//!
//! This crate does NOT own the taxonomy: it reads the same
//! `tiq_intent/taxonomy.toml` the Python oracle reads, at runtime, once,
//! lazily. Do not duplicate topic/keyword data into Rust source — the
//! oracle in `intent_scorer.py` and `cases.json` are the source of truth;
//! this file is the parity gate's target, not a second definition.
//!
//! ## Taxonomy path resolution
//! Resolved in this order:
//!   1. `TIQ_TAXONOMY_PATH` env var, if set (absolute or relative to CWD).
//!   2. `tiq_intent/taxonomy.toml` relative to CWD (matches running the
//!      harness from `api/`, e.g. `-w /src` in the Makefile's `make test`).
//!   3. `taxonomy.toml` relative to CWD (matches running from inside
//!      `tiq_intent/` directly).
//! The Dockerfile sets `TIQ_TAXONOMY_PATH=/app/tiq_intent/taxonomy.toml` in
//! the `base` stage so `import tiq_intent` works regardless of CWD or of a
//! bind-mount overlaying `/src` at container run time (env vars survive a
//! volume mount; a file baked into the image outside the mounted path does
//! too).
//!
//! ## casefold() vs to_lowercase()
//! Python's `str.casefold()` is a more aggressive normalization than
//! `str.lower()` (e.g. German "ß" -> "ss"). We use Rust's `to_lowercase()`
//! (Unicode-aware simple lowercasing). For the Italian corpus this crate
//! actually sees (ASCII + accented vowels à/è/é/ì/ò/ù, no ß-class
//! characters), `to_lowercase()` and `casefold()` agree on every input in
//! `cases.json` and in the taxonomy's own keyword set. This is a deliberate,
//! documented approximation, not an oversight — Rust's `regex`/`std` have no
//! built-in `casefold()`.

use pyo3::prelude::*;
use pyo3::wrap_pyfunction;
use regex::Regex;
use serde::Deserialize;
use std::collections::{HashMap, HashSet};
use std::sync::{Mutex, OnceLock};

const SOGLIA_CONFIDENCE: f64 = 0.60;

#[derive(Debug, Deserialize)]
struct RawTaxonomy {
    informational_by_nature: Vec<String>,
    kind: KindMarkers,
    topic: HashMap<String, TopicCfg>,
}

#[derive(Debug, Deserialize)]
struct KindMarkers {
    agevolazione_markers: Vec<String>,
    informazione_markers: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct TopicCfg {
    keywords: Vec<String>,
}

struct Taxonomy {
    topic_keywords: HashMap<String, Vec<String>>,
    informational_by_nature: HashSet<String>,
    agevolazione_markers: Vec<String>,
    informazione_markers: Vec<String>,
}

static TAXONOMY: OnceLock<Taxonomy> = OnceLock::new();
static MATCHER_CACHE: OnceLock<Mutex<HashMap<String, Regex>>> = OnceLock::new();

fn taxonomy_path() -> String {
    if let Ok(p) = std::env::var("TIQ_TAXONOMY_PATH") {
        return p;
    }
    for candidate in ["tiq_intent/taxonomy.toml", "taxonomy.toml"] {
        if std::path::Path::new(candidate).exists() {
            return candidate.to_string();
        }
    }
    // Nothing found: fall through to the first candidate so the error
    // message below names the path we actually tried.
    "tiq_intent/taxonomy.toml".to_string()
}

fn load_taxonomy() -> Taxonomy {
    let path = taxonomy_path();
    let content = std::fs::read_to_string(&path).unwrap_or_else(|e| {
        panic!("tiq_intent: cannot read taxonomy at '{path}' (set TIQ_TAXONOMY_PATH): {e}")
    });
    let raw: RawTaxonomy = toml::from_str(&content)
        .unwrap_or_else(|e| panic!("tiq_intent: cannot parse taxonomy at '{path}': {e}"));
    let topic_keywords = raw
        .topic
        .into_iter()
        .map(|(name, cfg)| (name, cfg.keywords))
        .collect();
    Taxonomy {
        topic_keywords,
        informational_by_nature: raw.informational_by_nature.into_iter().collect(),
        agevolazione_markers: raw.kind.agevolazione_markers,
        informazione_markers: raw.kind.informazione_markers,
    }
}

fn get_taxonomy() -> &'static Taxonomy {
    TAXONOMY.get_or_init(load_taxonomy)
}

/// Mirrors `_peso`: number of whitespace tokens of `keyword.rstrip("-")`,
/// minimum 1.
fn peso(keyword: &str) -> usize {
    let trimmed = keyword.trim_end_matches('-');
    let n = trimmed.split_whitespace().count();
    if n == 0 {
        1
    } else {
        n
    }
}

/// Mirrors `_matcher`: word-boundary match; a trailing "-" means "stem"
/// (left boundary only, open on the right).
fn build_matcher(keyword: &str) -> Regex {
    let pattern = if let Some(stem) = keyword.strip_suffix('-') {
        format!(r"\b{}", regex::escape(stem))
    } else {
        format!(r"\b{}\b", regex::escape(keyword))
    };
    Regex::new(&pattern)
        .unwrap_or_else(|e| panic!("tiq_intent: invalid regex for keyword '{keyword}': {e}"))
}

fn presente(keyword: &str, testo: &str) -> bool {
    let cache = MATCHER_CACHE.get_or_init(|| Mutex::new(HashMap::new()));
    let mut guard = cache.lock().expect("tiq_intent: matcher cache poisoned");
    let re = guard
        .entry(keyword.to_string())
        .or_insert_with(|| build_matcher(keyword));
    re.is_match(testo)
}

/// Mirrors `_kind_per`.
fn kind_per(topic: &str, testo: &str, tax: &Taxonomy) -> &'static str {
    if tax.informational_by_nature.contains(topic) {
        return "informazione";
    }
    let ag = tax.agevolazione_markers.iter().any(|m| presente(m, testo));
    let info = tax
        .informazione_markers
        .iter()
        .any(|m| presente(m, testo));
    if ag && !info {
        "agevolazione"
    } else {
        // Tie or absence: the conservative choice makes no verdict.
        "informazione"
    }
}

/// Mirrors `score_intent` exactly, including its tie-break and confidence
/// semantics. See module docs for the casefold vs to_lowercase caveat.
fn score_impl(message: &str) -> (String, String, f64) {
    if message.trim().is_empty() {
        return ("sconosciuto".to_string(), "informazione".to_string(), 0.0);
    }
    let tax = get_taxonomy();
    let testo = message.to_lowercase();

    let mut punteggi: Vec<(&str, usize)> = Vec::new();
    for (topic, keywords) in tax.topic_keywords.iter() {
        let mut best = 0usize;
        for kw in keywords {
            if presente(kw, &testo) {
                let p = peso(kw);
                if p > best {
                    best = p;
                }
            }
        }
        if best > 0 {
            punteggi.push((topic.as_str(), best));
        }
    }

    if punteggi.is_empty() {
        return ("sconosciuto".to_string(), "informazione".to_string(), 0.0);
    }

    // Order among ties never changes the output: a tie at the max always
    // resolves to "sconosciuto" below regardless of which topic sorts
    // first, and a unique max is unambiguous. So an unstable sort by score
    // descending is sufficient here (see module docs / lib.rs comments).
    punteggi.sort_by(|a, b| b.1.cmp(&a.1));
    let (top_topic, top_score) = punteggi[0];
    let secondo = if punteggi.len() > 1 { punteggi[1].1 } else { 0 };

    if secondo == top_score {
        return ("sconosciuto".to_string(), "informazione".to_string(), 0.5);
    }

    let confidence = top_score as f64 / (top_score + secondo) as f64;
    if confidence < SOGLIA_CONFIDENCE {
        return (
            "sconosciuto".to_string(),
            "informazione".to_string(),
            confidence,
        );
    }

    let kind = kind_per(top_topic, &testo, tax);
    (top_topic.to_string(), kind.to_string(), confidence)
}

/// Python entry point: `tiq_intent.score(message) -> (topic, kind, confidence)`.
#[pyfunction]
fn score(message: &str) -> (String, String, f64) {
    score_impl(message)
}

#[pymodule]
fn tiq_intent(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(score, m)?)?;
    Ok(())
}
