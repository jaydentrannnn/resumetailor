//! Window requests the web UI makes through the server (`desktop_shell.py`):
//!
//! - `SHELL save {"id", "name", "ext"}` opens the native Save dialog over the main
//!   window and answers `DIALOG {"id", "path"}` on the server's stdin (`path` is null
//!   when the person cancels);
//! - `SHELL title {"title"}` sets the main window's title;
//! - `SHELL zoom {"scale"}` sets the webview zoom factor.
//!
//! The web UI has no Tauri IPC, so dialogs only ever open from here. `rfd` directly
//! rather than tauri-plugin-dialog: every plugin release that fits needs a newer tauri
//! than the shell pins, and the shell needs only Save.

use serde_json::{json, Value};
use tauri::{AppHandle, Manager};

#[derive(Debug, PartialEq)]
pub enum Request {
    Save {
        id: String,
        name: String,
        ext: String,
    },
    Title(String),
    Zoom(f64),
}

/// `SHELL save {...}` / `SHELL title {...}` / `SHELL zoom {...}` from the server's stdout.
pub fn parse(line: &str) -> Option<Request> {
    let rest = line.strip_prefix("SHELL ")?;
    let (command, payload) = rest.split_once(' ')?;
    let value: Value = serde_json::from_str(payload).ok()?;
    let text = |key: &str| value.get(key).and_then(Value::as_str).map(str::to_owned);
    match command {
        "save" => Some(Request::Save {
            id: text("id")?,
            name: text("name").unwrap_or_default(),
            ext: text("ext").unwrap_or_default(),
        }),
        "title" => Some(Request::Title(text("title")?)),
        "zoom" => {
            let scale = value.get("scale")?.as_f64()?;
            Some(Request::Zoom(scale))
        }
        _ => None,
    }
}

/// The Save dialog's file-type label for an extension.
pub fn filter_label(ext: &str) -> String {
    match ext {
        "pdf" => "PDF document".to_owned(),
        "docx" => "Word document".to_owned(),
        "zip" => "ZIP archive".to_owned(),
        "csv" => "CSV file".to_owned(),
        "md" => "Markdown file".to_owned(),
        "" => "File".to_owned(),
        other => format!("{} file", other.to_uppercase()),
    }
}

/// `DIALOG {...}` for the server.
pub fn dialog_line(id: &str, path: Option<String>) -> String {
    format!("DIALOG {}", json!({ "id": id, "path": path }))
}

pub fn handle(app: &AppHandle, request: Request) {
    match request {
        Request::Title(title) => {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_title(&title);
            }
        }
        Request::Zoom(scale) => {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_zoom(scale);
            }
        }
        Request::Save { id, name, ext } => {
            let mut dialog = rfd::AsyncFileDialog::new().set_file_name(&name);
            if !ext.is_empty() {
                dialog = dialog.add_filter(filter_label(&ext), &[ext.as_str()]);
            }
            if let Some(window) = app.get_webview_window("main") {
                dialog = dialog.set_parent(&window);
            }
            let handle = app.clone();
            // The async dialog runs on the main thread where macOS requires it; this
            // task only waits for the answer.
            tauri::async_runtime::spawn(async move {
                let path = dialog
                    .save_file()
                    .await
                    .map(|file| file.path().display().to_string());
                crate::send_to_server(&handle, &dialog_line(&id, path));
            });
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{dialog_line, filter_label, parse, Request};

    #[test]
    fn parses_save_and_title_requests() {
        assert_eq!(
            parse(r#"SHELL save {"id":"a1","name":"Resume.pdf","ext":"pdf"}"#),
            Some(Request::Save {
                id: "a1".into(),
                name: "Resume.pdf".into(),
                ext: "pdf".into()
            })
        );
        assert_eq!(
            parse(r#"SHELL title {"title":"Acme — ResumeTailor"}"#),
            Some(Request::Title("Acme — ResumeTailor".into()))
        );
        assert_eq!(
            parse(r#"SHELL zoom {"scale":1.25}"#),
            Some(Request::Zoom(1.25))
        );
    }

    #[test]
    fn leaves_other_lines_alone() {
        for line in [
            "SHELL check",
            "SHELL save",
            "SHELL save not-json",
            r#"SHELL save {"name":"no id"}"#,
            r#"SHELL open {"id":"x"}"#,
            "READY 8000 t",
        ] {
            assert_eq!(parse(line), None, "{line}");
        }
    }

    #[test]
    fn dialog_answers_carry_the_path_or_null() {
        assert_eq!(dialog_line("a1", None), r#"DIALOG {"id":"a1","path":null}"#);
        assert_eq!(
            dialog_line("a1", Some("C:\\x.pdf".into())),
            r#"DIALOG {"id":"a1","path":"C:\\x.pdf"}"#
        );
        assert_eq!(filter_label("docx"), "Word document");
        assert_eq!(filter_label("txt"), "TXT file");
    }
}
