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
//!   to reopen or quit; quitting stops the server.
//!
//! The web UI runs from a 127.0.0.1 origin and gets no Tauri IPC (see
//! `capabilities/default.json`); only the bundled start page can call `log_folder`.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::Mutex;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, RunEvent, Url, WindowEvent};

const MAX_RESTARTS: u32 = 3;

#[derive(Default)]
struct Sidecar {
    child: Mutex<Option<Child>>,
    restarts: AtomicU32,
    quitting: AtomicBool,
    /// The bundled start page's URL, so a failure can navigate back to it.
    start_url: Mutex<Option<Url>>,
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
    *app.state::<Sidecar>().child.lock().unwrap() = Some(child);

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
                if let Some(window) = handle.get_webview_window("main") {
                    let _ = window.navigate(url);
                }
            }
        }
        server_exited(&handle);
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

fn server_exited(app: &AppHandle) {
    let state = app.state::<Sidecar>();
    let exited = state.child.lock().unwrap().take();
    if let Some(mut child) = exited {
        let _ = child.wait();
    }
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
    if let Some(mut child) = running {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main(app)
        }))
        .manage(Sidecar::default())
        .invoke_handler(tauri::generate_handler![log_folder])
        .setup(|app| {
            let handle = app.handle().clone();
            if let Some(window) = app.get_webview_window("main") {
                *handle.state::<Sidecar>().start_url.lock().unwrap() = window.url().ok();
            }

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
