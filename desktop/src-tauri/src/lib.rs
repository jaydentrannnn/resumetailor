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
//!   to reopen or quit; quitting stops the server;
//! - checks for, downloads and installs updates when the server asks (`update.rs`);
//! - opens outside links in the default browser, keeping the window on the app
//!   (`links.rs`).
//!
//! The web UI runs from a 127.0.0.1 origin and gets no Tauri IPC (see
//! `capabilities/default.json`); only the bundled start page can call `log_folder`.
//! Everything else between the web UI and the shell goes through the server's pipes:
//! `READY` and `SHELL <command>` lines on its stdout, `UPDATE <json>` lines on its stdin.

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

fn start_server(app: &AppHandle) -> Result<(), String> {
    let program = server_program(app).map_err(|e| e.to_string())?;
    let mut command = Command::new(&program);
    // The server exits when this pipe closes, so it never outlives the shell, even
    // when the shell is killed rather than quit.
    command
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
        // server exited.
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
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
            }
        }
        server_exited(&handle, pid);
    });
    Ok(())
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
    WebviewWindowBuilder::from_config(app, &config)?
        .on_navigation(move |url| {
            // A link followed in the window itself.
            let server = navigation.state::<Sidecar>().server_url.lock().unwrap().clone();
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
        .build()
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

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            stop_server(handle);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::ready_url;

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
