//! POST captured JSON to `<api_url>/api/runs`.
//!
//! Matches the `.exe` extractor's request shape (see
//! `tools/memory_extractor/dump_it_run.py:674`) so the server
//! endpoint doesn't need to distinguish plugin vs extractor uploads:
//!
//! - `POST <api_url>/api/runs`
//! - `Authorization: Bearer <token>`
//! - `X-Filename: <extractor-style filename>`
//! - `Content-Type: application/json`
//! - Body: raw JSON bytes
//!
//! Response codes we care about:
//! - 201 Created — new run stored, response has `{id, filename, url}`
//! - 409 Conflict — already have this run (filename or content dupe);
//!    server returns `{error: "duplicate", message: ...}`, treat as
//!    success from the user's POV (they don't need to know it's not
//!    a fresh row)
//! - other 4xx/5xx — surface to the user via notification
//!
//! **Blocking on the game's GUI thread.** ureq is sync. On a modest
//! upload (~200-400 KB) over a reasonable connection this returns in
//! well under a second, which is acceptable for a menu-click action.
//! If uploads start taking multiple seconds we can move this to a
//! background thread — but that would need the notification callback
//! to be main-thread-safe, which we haven't validated. Keep it simple
//! until we have evidence we need async.

use std::time::Duration;

/// Outcome the caller uses to build a notification. The `message`
/// on each variant is what we'd show the user — kept short so it
/// fits in a Hachimi toast without wrapping.
pub enum UploadOutcome {
    /// 201 Created. `url` is the run's detail page if the server
    /// returned one (nice to log but not shown to user — they can
    /// find it themselves on the site).
    Created { url: Option<String> },
    /// 409 Conflict. Server already has this run. From the user's
    /// POV this is fine — the previous upload worked.
    Duplicate,
    /// Any other HTTP status. `code` is the numeric status,
    /// `body_snippet` is the first ~120 chars of the response for
    /// diagnostic logging.
    HttpError { code: u16, body_snippet: String },
    /// Network / TLS / DNS error before we got a response.
    Transport(String),
    /// Config wasn't ready (missing token or URL). Not really an
    /// error — just means we didn't try. Kept separate so the UI
    /// can distinguish "silent skip" from a real failure.
    NotConfigured,
}

/// Upload a capture. Returns synchronously.
///
/// - `api_url`: base URL, already normalized (no trailing slash)
/// - `token`: raw Bearer token, no `Bearer ` prefix
/// - `filename`: extractor-style filename passed in `X-Filename` for
///    server-side validation against the JSON contents
/// - `json_body`: the exact bytes we wrote to disk
pub fn upload_run(
    api_url: &str,
    token: &str,
    filename: &str,
    json_body: &[u8],
) -> UploadOutcome {
    if api_url.is_empty() || token.is_empty() {
        return UploadOutcome::NotConfigured;
    }
    let endpoint = format!("{}/api/runs", api_url.trim_end_matches('/'));
    // 30s total timeout — matches the server's new gunicorn --timeout
    // 120 with plenty of headroom. If we hit this, either the server
    // is down or the user's network is unusable.
    let agent = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(30))
        .user_agent(concat!("uma-it-plugin/", env!("CARGO_PKG_VERSION")))
        .build();

    let bearer = format!("Bearer {}", token);
    let result = agent
        .post(&endpoint)
        .set("Authorization", &bearer)
        .set("X-Filename", filename)
        .set("Content-Type", "application/json")
        .send_bytes(json_body);

    match result {
        Ok(resp) => {
            // 201 path. Try to extract "url" from response body if
            // present — it's nice for logs but we don't require it
            // to be there (extractor also skips body parsing on
            // success for this reason).
            let url = extract_url_field(&resp.into_string().unwrap_or_default());
            UploadOutcome::Created { url }
        }
        Err(ureq::Error::Status(code, resp)) => {
            let body = resp.into_string().unwrap_or_default();
            if code == 409 {
                UploadOutcome::Duplicate
            } else {
                let mut snippet: String = body.chars().take(120).collect();
                if body.len() > snippet.len() {
                    snippet.push('…');
                }
                UploadOutcome::HttpError {
                    code,
                    body_snippet: snippet,
                }
            }
        }
        Err(ureq::Error::Transport(t)) => UploadOutcome::Transport(t.to_string()),
    }
}

/// Cheap extraction of `"url": "..."` from a JSON blob. We don't
/// pull in serde_json for one field. Returns None if the shape isn't
/// what we expected — caller treats that as "no URL to log."
fn extract_url_field(body: &str) -> Option<String> {
    let key = "\"url\"";
    let idx = body.find(key)?;
    let after = &body[idx + key.len()..];
    let colon = after.find(':')?;
    let after_colon = &after[colon + 1..];
    let start = after_colon.find('"')? + 1;
    let rest = &after_colon[start..];
    let end = rest.find('"')?;
    Some(rest[..end].to_string())
}
