//! ResumeTailor desktop shell (plan Phase 5, DK1–DK4).
//!
//! The app itself is the local FastAPI server plus its web UI. This shell:
//!
//! - starts the bundled server (`server/resumetailor-server`, a PyInstaller folder built
//!   from `desktop/sidecar/resumetailor.spec`) and reads its stdout until the line
//!   `READY <port> <token>`, then points the window at `http://127.0.0.1:<port>/?t=<token>`;
//! - restarts the server if it exits on its own; after `MAX_RESTARTS` exits in a row
//!   without a READY line in between, shows the bundled start page's failure state with
//!   the log folder;
//! - starts the server with `--exit-with-stdin` and holds its stdin, so the server
//!   stops with the shell even when the shell is killed rather than quit;
//! - keeps one instance (a second launch focuses the first window);
//! - hides the window on close so the nightly scheduler keeps running, with a tray menu
//!   to reopen or quit (on macOS the Dock icon reopens it too); quitting stops the server;
//! - checks for, downloads and installs updates when the server asks (`update.rs`);
//! - opens the native Save dialog and sets the window title when the server asks
//!   (`window_requests.rs`);
//! - opens outside links in the default browser, keeping the window on the app
//!   (`links.rs`);
//! - switches off browser behaviours that do not belong in an app window: reload,
//!   history navigation, the browser's menus, print/save-page, page zoom, file drops
//!   that would replace the app (`lockdown.js`, plus `webview_settings.rs` on Windows).
//!
//! The web UI runs from a 127.0.0.1 origin and gets no Tauri IPC (see
//! `capabilities/default.json`); only the bundled start page can call `log_folder`.
//! Everything else between the web UI and the shell goes through the server's pipes:
//! `READY` and `SHELL <command>` lines on its stdout, `UPDATE <json>` and `DIALOG <json>`
//! lines on its stdin.

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::Mutex;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewWindowBuilder, WindowEvent};

mod links;
mod update;
mod webview_settings;
mod window_requests;

const MAX_RESTARTS: u32 = 3;

#[derive(Default)]
struct Sidecar {
    child: Mutex<Option<Child>>,
    /// The server's stdin: held open (its end stops the server) and written to with
    /// update events.
    stdin: Mutex<Option<ChildStdin>>,
    restarts: AtomicU32,
    quitting: AtomicBool,
    /// The bundled start page's URL, so a failure can navigate back to it.
    start_url: Mutex<Option<Url>>,
    /// The running server's URL, so links to it stay in the app (`links::route`).
    server_url: Mutex<Option<Url>>,
}

fn server_program(app: &AppHandle) -> tauri::Result<PathBuf> {
    let name = if cfg!(windows) {
        "resumetailor-server.exe"
    } else {
        "resumetailor-server"
    };
    // `bundle.resources` maps the PyInstaller folder to `server/`; accept the folder
    // itself or its contents there, whichever layout the bundler produced.
    let server = app.path().resource_dir()?.join("server");
    let flat = server.join(name);
    if flat.is_file() {
        return Ok(flat);
    }
    Ok(server.join("resumetailor-server").join(name))
}

/// Where the server writes `app.log` (`desktop_main.app_data_dir()` + `output/logs`).
fn log_folder_path() -> PathBuf {
    let home = std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
        .map(PathBuf::from)
        .unwrap_or_default();
    let root = if cfg!(windows) {
        std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join("AppData").join("Local"))
            // Not `ResumeTailor`: the per-user installer puts the program there.
            .join("ResumeTailorData")
    } else if cfg!(target_os = "macos") {
        home.join("Library")
            .join("Application Support")
            .join("ResumeTailor")
    } else {
        std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".local").join("share"))
            .join("resumetailor")
    };
    root.join("output").join("logs")
}

#[tauri::command]
fn log_folder() -> String {
    log_folder_path().display().to_string()
}

fn theme_path() -> PathBuf {
    log_folder_path()
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("theme.json")
}

fn theme_script_from_json(text: &str) -> String {
    let value = serde_json::from_str::<serde_json::Value>(text).ok();
    let preference = value
        .as_ref()
        .and_then(|v| v.get("preference").and_then(|p| p.as_str()))
        .filter(|p| matches!(*p, "light" | "dark" | "system"))
        .unwrap_or("system");
    let accent = value
        .as_ref()
        .and_then(|v| v.get("accent").and_then(|a| a.as_str()))
        .filter(|a| {
            a.len() == 7 && a.starts_with('#') && a.chars().skip(1).all(|c| c.is_ascii_hexdigit())
        });
    format!(
        "window.__RT_DESKTOP_THEME__={};window.__RT_DESKTOP_ACCENT__={};",
        serde_json::to_string(&preference).unwrap(),
        serde_json::to_string(&accent).unwrap()
    )
}

/// Seed the bundled startup page before paint, from the app's last saved preference.
fn theme_script() -> String {
    theme_script_from_json(&std::fs::read_to_string(theme_path()).unwrap_or_default())
}

/// UI scale from theme.json (1.0 when missing or invalid).
fn scale_from_theme() -> f64 {
    let allowed = [0.9, 1.0, 1.1, 1.25, 1.5];
    std::fs::read_to_string(theme_path())
        .ok()
        .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).ok())
        .and_then(|value| value.get("scale").and_then(|s| s.as_f64()))
        .filter(|s| allowed.contains(s))
        .unwrap_or(1.0)
}

/// True when launched with ``--hidden`` (start with computer: tray only).
fn start_hidden() -> bool {
    std::env::args().any(|arg| arg == "--hidden")
}

/// `lockdown.js`, told whether this is a debug build (which keeps the DevTools keys).
fn lockdown_script() -> String {
    format!(
        "window.__RT_DEBUG__={};\n{}",
        cfg!(debug_assertions),
        include_str!("lockdown.js")
    )
}

fn start_server(app: &AppHandle) -> Result<(), String> {
    let program = server_program(app).map_err(|e| e.to_string())?;
    let mut command = Command::new(&program);
    // The server exits when this pipe closes, so it never outlives the shell, even
    // when the shell is killed rather than quit.
    command
        .env("RESUME_TAILOR_THEME_PATH", theme_path())
        .env(
            "RESUME_TAILOR_SHELL_EXE",
            std::env::current_exe().unwrap_or_default(),
        )
        .arg("--exit-with-stdin")
        .arg("--app-version")
        .arg(app.package_info().version.to_string())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = command
        .spawn()
        .map_err(|e| format!("could not start {}: {e}", program.display()))?;
    let stdout = child.stdout.take().ok_or("the server has no stdout")?;
    let pid = child.id();
    let state = app.state::<Sidecar>();
    *state.stdin.lock().unwrap() = child.stdin.take();
    *state.child.lock().unwrap() = Some(child);

    let handle = app.clone();
    std::thread::spawn(move || {
        // Keep reading after READY: the pipe must not fill up, and its end means the
        // server exited. Lines are decoded leniently: `lines()` stops at the first one
        // that is not UTF-8, which closed the pipe on a server still running, so every
        // later Save dialog or title request failed.
        for line in read_lines_lossy(stdout) {
            if let Some(url) = ready_url(&line) {
                handle
                    .state::<Sidecar>()
                    .restarts
                    .store(0, Ordering::SeqCst);
                *handle.state::<Sidecar>().server_url.lock().unwrap() = Some(url.clone());
                if let Some(window) = handle.get_webview_window("main") {
                    let _ = window.navigate(url);
                }
                update::on_ready(&handle);
            } else if let Some(command) = update::parse_command(&line) {
                update::handle(&handle, command);
            } else if let Some(request) = window_requests::parse(&line) {
                window_requests::handle(&handle, request);
            }
        }
        server_exited(&handle, pid);
    });
    Ok(())
}

/// Each line of `stream` until it ends or fails, with any bytes that are not UTF-8
/// replaced rather than ending the stream, and without the line ending.
fn read_lines_lossy(stream: impl std::io::Read) -> impl Iterator<Item = String> {
    let mut reader = BufReader::new(stream);
    std::iter::from_fn(move || {
        let mut buf = Vec::new();
        match reader.read_until(b'\n', &mut buf) {
            Ok(0) | Err(_) => None,
            Ok(_) => {
                let text = String::from_utf8_lossy(&buf);
                Some(text.trim_end_matches(['\r', '\n']).to_owned())
            }
        }
    })
}

/// `READY <port> <token>` → the URL that signs the window in.
fn ready_url(line: &str) -> Option<Url> {
    let mut parts = line.strip_prefix("READY ")?.split_whitespace();
    let port: u16 = parts.next()?.parse().ok()?;
    let token = parts.next()?;
    Url::parse(&format!("http://127.0.0.1:{port}/?t={token}")).ok()
}

/// Write one line to the server's stdin; a server that is not running just misses it.
fn send_to_server(app: &AppHandle, line: &str) {
    if let Some(stdin) = app.state::<Sidecar>().stdin.lock().unwrap().as_mut() {
        let _ = writeln!(stdin, "{line}").and_then(|()| stdin.flush());
    }
}

fn server_exited(app: &AppHandle, pid: u32) {
    let state = app.state::<Sidecar>();
    let exited = {
        let mut current = state.child.lock().unwrap();
        // Already stopped (quit, update) or replaced by a newer server: not ours to
        // restart.
        if current.as_ref().map(Child::id) != Some(pid) {
            return;
        }
        current.take()
    };
    if let Some(mut child) = exited {
        let _ = child.wait();
    }
    *state.stdin.lock().unwrap() = None;
    if state.quitting.load(Ordering::SeqCst) {
        return;
    }
    let attempt = state.restarts.fetch_add(1, Ordering::SeqCst) + 1;
    if attempt <= MAX_RESTARTS && start_server(app).is_ok() {
        return;
    }
    show_failure(app);
}

fn show_failure(app: &AppHandle) {
    let start = app.state::<Sidecar>().start_url.lock().unwrap().clone();
    if let (Some(window), Some(mut url)) = (app.get_webview_window("main"), start) {
        url.set_fragment(Some("failed"));
        let _ = window.navigate(url);
        let _ = window.show();
    }
}

fn stop_server(app: &AppHandle) {
    let state = app.state::<Sidecar>();
    state.quitting.store(true, Ordering::SeqCst);
    let running = state.child.lock().unwrap().take();
    *state.stdin.lock().unwrap() = None;
    if let Some(mut child) = running {
        let _ = child.kill();
        let _ = child.wait();
    }
}

/// Start the server again after `stop_server`, e.g. when an update failed to install.
fn restart_server(app: &AppHandle) {
    let state = app.state::<Sidecar>();
    state.quitting.store(false, Ordering::SeqCst);
    state.restarts.store(0, Ordering::SeqCst);
    if let Err(message) = start_server(app) {
        eprintln!("{message}");
        show_failure(app);
    }
}

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

/// The main window from `tauri.conf.json` (`"create": false`), with its link handling.
fn main_window(app: &AppHandle) -> tauri::Result<tauri::WebviewWindow> {
    let config = app
        .config()
        .app
        .windows
        .iter()
        .find(|window| window.label == "main")
        .cloned()
        .expect("tauri.conf.json defines the main window");
    let navigation = app.clone();
    let popup = app.clone();
    let mut builder = WebviewWindowBuilder::from_config(app, &config)?
        .initialization_script(theme_script())
        .initialization_script(lockdown_script());
    if start_hidden() {
        builder = builder.visible(false);
    }
    let window = builder
        .on_navigation(move |url| {
            // A link followed in the window itself.
            let server = navigation
                .state::<Sidecar>()
                .server_url
                .lock()
                .unwrap()
                .clone();
            match links::route(url, server.as_ref()) {
                links::Route::App => true,
                links::Route::Browser => {
                    links::open_in_browser(url);
                    false
                }
                links::Route::Block => false,
            }
        })
        .on_new_window(move |url, _features| {
            // A `target="_blank"` link or `window.open`: local files (a PDF preview) open
            // in an app window, which shares the session cookie; the rest go outside.
            let server = popup.state::<Sidecar>().server_url.lock().unwrap().clone();
            match links::route(&url, server.as_ref()) {
                links::Route::App => NewWindowResponse::Allow,
                links::Route::Browser => {
                    links::open_in_browser(&url);
                    NewWindowResponse::Deny
                }
                links::Route::Block => NewWindowResponse::Deny,
            }
        })
        .build()?;
    webview_settings::lock(&window);
    let scale = scale_from_theme();
    if (scale - 1.0).abs() > f64::EPSILON {
        let _ = window.set_zoom(scale);
    }
    Ok(window)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main(app)
        }))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Sidecar::default())
        .manage(update::Updates::default())
        .invoke_handler(tauri::generate_handler![log_folder])
        .setup(|app| {
            let handle = app.handle().clone();
            let window = main_window(&handle)?;
            *handle.state::<Sidecar>().start_url.lock().unwrap() = window.url().ok();

            let open = MenuItem::with_id(app, "open", "Open ResumeTailor", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &quit])?;
            let mut tray = TrayIconBuilder::new()
                .tooltip("ResumeTailor")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => show_main(app),
                    "quit" => {
                        stop_server(app);
                        app.exit(0);
                    }
                    _ => {}
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;

            if let Err(message) = start_server(&handle) {
                eprintln!("{message}");
                show_failure(&handle);
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing hides: the scheduler and any running fill keep going.
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building the ResumeTailor shell");

    app.run(|handle, event| match event {
        RunEvent::Exit => stop_server(handle),
        // A Dock click (or a launch from Finder) on the running app: macOS sends this
        // instead of starting a second copy, so the window hidden on close comes back.
        #[cfg(target_os = "macos")]
        RunEvent::Reopen {
            has_visible_windows: false,
            ..
        } => show_main(handle),
        _ => {}
    });
}

#[cfg(test)]
mod tests {
    use super::{
        lockdown_script, read_lines_lossy, ready_url, scale_from_theme, theme_script_from_json,
    };

    #[test]
    fn server_output_keeps_flowing_past_a_line_that_is_not_utf8() {
        // "caf\xe9" is "café" in the Windows code page: not UTF-8.
        let output: &[u8] = b"READY 8000 t\r\ncaf\xe9\nSHELL save {}\n";
        let lines: Vec<String> = read_lines_lossy(output).collect();
        assert_eq!(lines, ["READY 8000 t", "caf\u{fffd}", "SHELL save {}"]);
    }

    #[test]
    fn lockdown_script_states_the_build_kind_before_the_lockdown() {
        let script = lockdown_script();
        let flag = format!("window.__RT_DEBUG__={};", cfg!(debug_assertions));
        assert!(script.starts_with(&flag));
        assert!(script.contains("window.__RT_LOCKDOWN__"));
    }

    #[test]
    fn startup_theme_accepts_saved_preferences_and_defaults_invalid_input() {
        for preference in ["light", "dark", "system"] {
            let text = format!(r#"{{"preference":"{preference}"}}"#);
            assert_eq!(
                theme_script_from_json(&text),
                format!(
                    "window.__RT_DESKTOP_THEME__=\"{preference}\";window.__RT_DESKTOP_ACCENT__=null;"
                )
            );
        }
        let with_accent = r##"{"preference":"dark","accent":"#3b82f6"}"##;
        assert_eq!(
            theme_script_from_json(with_accent),
            "window.__RT_DESKTOP_THEME__=\"dark\";window.__RT_DESKTOP_ACCENT__=\"#3b82f6\";"
        );
        for text in ["", "null", "{}", r#"{"preference":"invalid"}"#] {
            assert_eq!(
                theme_script_from_json(text),
                "window.__RT_DESKTOP_THEME__=\"system\";window.__RT_DESKTOP_ACCENT__=null;"
            );
        }
    }

    #[test]
    fn scale_from_theme_reads_allowed_values_only() {
        // scale_from_theme reads theme_path(); without a file it is 1.0.
        assert!((scale_from_theme() - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn ready_line_becomes_the_sign_in_url() {
        let url = ready_url("READY 8003 abc_DEF-123").unwrap();
        assert_eq!(url.as_str(), "http://127.0.0.1:8003/?t=abc_DEF-123");
    }

    #[test]
    fn other_lines_are_ignored() {
        assert!(ready_url("ResumeTailor: open http://127.0.0.1:<port>/?t=x").is_none());
        assert!(ready_url("READY notaport token").is_none());
        assert!(ready_url("READY 8000").is_none());
    }
}
