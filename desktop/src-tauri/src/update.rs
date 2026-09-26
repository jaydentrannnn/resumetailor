//! In-app updates (tauri-plugin-updater), driven by the server over the sidecar's pipes.
//!
//! The web UI has no Tauri IPC, so the server relays for it (`desktop_update.py`):
//!
//! - server → shell, on its stdout: `SHELL check`, `SHELL download`, `SHELL apply`;
//! - shell → server, on its stdin: `UPDATE <json>` events (`checking`, `available`,
//!   `up_to_date`, `downloading`, `ready`, `error`).
//!
//! Checks run 30 s after the server first starts and every 12 h after that, plus on
//! request. Nothing downloads until the user clicks Install. `SHELL apply` comes only
//! once the server is idle and has backed up its data; the shell then stops the server
//! and hands the signature-checked installer to the plugin, which on Windows runs it in
//! passive mode (it replaces the files and starts the app again) and exits this process.
//!
//! `RESUMETAILOR_UPDATE_ENDPOINT` replaces the release feed, for testing against a local
//! `latest.json`. Signatures are still checked against the key in `tauri.conf.json`.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use serde_json::{json, Value};
use tauri::{AppHandle, Manager, Url};
use tauri_plugin_updater::{Update, UpdaterExt};

const FIRST_CHECK_DELAY: Duration = Duration::from_secs(30);
const CHECK_INTERVAL: Duration = Duration::from_secs(12 * 60 * 60);

#[derive(Default)]
pub struct Updates {
    /// The update the last check found, until a download takes it.
    found: Mutex<Option<Update>>,
    /// A downloaded, signature-checked update waiting for `SHELL apply`.
    downloaded: Mutex<Option<(Update, Vec<u8>)>>,
    /// The last check result or failure, sent again whenever the server (re)starts.
    last_event: Mutex<Option<String>>,
    /// A download or install is under way; periodic checks stand aside.
    busy: AtomicBool,
    scheduled: AtomicBool,
}

#[derive(Debug, PartialEq, Eq)]
pub enum Command {
    Check,
    Download,
    Apply,
}

/// `SHELL <command>` from the server's stdout.
pub fn parse_command(line: &str) -> Option<Command> {
    match line.strip_prefix("SHELL ")?.trim() {
        "check" => Some(Command::Check),
        "download" => Some(Command::Download),
        "apply" => Some(Command::Apply),
        _ => None,
    }
}

/// One `UPDATE <json>` line; serde_json keeps it on one line (newlines are escaped).
pub fn event_line(event: &Value) -> String {
    format!("UPDATE {event}")
}

fn send(app: &AppHandle, event: Value) {
    crate::send_to_server(app, &event_line(&event));
}

fn remember_and_send(app: &AppHandle, event: Value) {
    let line = event_line(&event);
    *app.state::<Updates>().last_event.lock().unwrap() = Some(line.clone());
    crate::send_to_server(app, &line);
}

/// The server printed READY: repeat the last result to it (it may have restarted) and
/// start the periodic checks the first time.
pub fn on_ready(app: &AppHandle) {
    let state = app.state::<Updates>();
    let last = state.last_event.lock().unwrap().clone();
    if let Some(line) = last {
        crate::send_to_server(app, &line);
    }
    if state.scheduled.swap(true, Ordering::SeqCst) {
        return;
    }
    let handle = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(FIRST_CHECK_DELAY);
        loop {
            tauri::async_runtime::block_on(check(&handle));
            std::thread::sleep(CHECK_INTERVAL);
        }
    });
}

/// Run a command from the server without blocking the stdout reader.
pub fn handle(app: &AppHandle, command: Command) {
    let handle = app.clone();
    match command {
        Command::Check => {
            tauri::async_runtime::spawn(async move { check(&handle).await });
        }
        Command::Download => {
            tauri::async_runtime::spawn(async move { download(&handle).await });
        }
        // Its own thread: it stops the server whose stdout the caller is reading.
        Command::Apply => {
            std::thread::spawn(move || apply(&handle));
        }
    }
}

async fn find(app: &AppHandle) -> tauri_plugin_updater::Result<Option<Update>> {
    let mut builder = app.updater_builder();
    if let Some(url) = std::env::var("RESUMETAILOR_UPDATE_ENDPOINT")
        .ok()
        .and_then(|raw| Url::parse(raw.trim()).ok())
    {
        builder = builder.endpoints(vec![url])?;
    }
    builder.build()?.check().await
}

async fn check(app: &AppHandle) {
    let state = app.state::<Updates>();
    if state.busy.load(Ordering::SeqCst) {
        return;
    }
    send(app, json!({ "state": "checking" }));
    let event = match find(app).await {
        Ok(Some(update)) => {
            let event = json!({
                "state": "available",
                "version": update.version.clone(),
                "notes": update.body.clone().unwrap_or_default(),
                "date": update.raw_json.get("pub_date").and_then(Value::as_str).unwrap_or(""),
            });
            *state.found.lock().unwrap() = Some(update);
            event
        }
        Ok(None) => {
            *state.found.lock().unwrap() = None;
            json!({ "state": "up_to_date" })
        }
        Err(error) => json!({
            "state": "error",
            "message": format!("Could not check for updates: {error}"),
        }),
    };
    remember_and_send(app, event);
}

async fn download(app: &AppHandle) {
    let state = app.state::<Updates>();
    let Some(update) = state.found.lock().unwrap().take() else {
        send(
            app,
            json!({ "state": "error", "message": "No update to download. Check for updates again." }),
        );
        return;
    };
    state.busy.store(true, Ordering::SeqCst);
    let progress = app.clone();
    let mut received: u64 = 0;
    let mut reported: u64 = 0;
    let result = update
        .download(
            |chunk, total| {
                received += chunk as u64;
                if let Some(total) = total.filter(|total| *total > 0) {
                    let pct = (received * 100 / total).min(100);
                    if pct >= reported + 5 {
                        reported = pct;
                        send(&progress, json!({ "state": "downloading", "pct": pct }));
                    }
                }
            },
            || {},
        )
        .await;
    match result {
        Ok(bytes) => {
            *state.downloaded.lock().unwrap() = Some((update, bytes));
            send(app, json!({ "state": "ready" }));
        }
        Err(error) => {
            state.busy.store(false, Ordering::SeqCst);
            remember_and_send(
                app,
                json!({ "state": "error", "message": format!("The download failed: {error}") }),
            );
        }
    }
}

fn apply(app: &AppHandle) {
    let state = app.state::<Updates>();
    let Some((update, bytes)) = state.downloaded.lock().unwrap().take() else {
        send(
            app,
            json!({ "state": "error", "message": "The update is no longer downloaded. Check again." }),
        );
        return;
    };
    // Stop first so the installer can replace the server's files.
    crate::stop_server(app);
    match update.install(&bytes) {
        // Windows exits inside `install` once the installer is running, so this is
        // reached only where the files were replaced in place (macOS).
        Ok(()) => app.restart(),
        Err(error) => {
            state.busy.store(false, Ordering::SeqCst);
            // Sent again by `on_ready` once the restarted server is listening.
            *state.last_event.lock().unwrap() = Some(event_line(&json!({
                "state": "error",
                "message": format!("The update could not be installed: {error}"),
            })));
            crate::restart_server(app);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shell_lines_become_commands() {
        assert_eq!(parse_command("SHELL check"), Some(Command::Check));
        assert_eq!(parse_command("SHELL download"), Some(Command::Download));
        assert_eq!(parse_command("SHELL apply\r"), Some(Command::Apply));
    }

    #[test]
    fn other_lines_are_not_commands() {
        assert_eq!(parse_command("READY 8000 token"), None);
        assert_eq!(parse_command("SHELL rm -rf"), None);
        assert_eq!(parse_command("shell check"), None);
        assert_eq!(parse_command(""), None);
    }

    #[test]
    fn events_are_single_lines() {
        let line = event_line(&json!({ "state": "available", "notes": "one\ntwo" }));
        assert!(line.starts_with("UPDATE {"));
        assert!(!line.contains('\n'));
        let parsed: Value = serde_json::from_str(line.strip_prefix("UPDATE ").unwrap()).unwrap();
        assert_eq!(parsed["notes"], "one\ntwo");
    }
}
