//! Where a link clicked in the app window opens.
//!
//! The window shows the bundled start page and the local server's web UI. Postings,
//! company sites and every other outside page open in the default browser instead,
//! where the user can keep them. Local pages and files stay in the app: they need the
//! session cookie, which only the app's webviews hold.

use tauri::Url;

#[derive(Debug, PartialEq, Eq)]
pub enum Route {
    /// Load it in the app.
    App,
    /// Open it in the default browser.
    Browser,
    /// Neither: a scheme the shell never hands to the system.
    Block,
}

/// Decide where `url` belongs; `server` is the running server's URL, once it is up.
pub fn route(url: &Url, server: Option<&Url>) -> Route {
    match url.scheme() {
        "tauri" | "about" | "data" | "blob" => return Route::App,
        "mailto" => return Route::Browser,
        "http" | "https" => {}
        _ => return Route::Block,
    }
    // The bundled start page on Windows and Linux.
    if url.host_str() == Some("tauri.localhost") {
        return Route::App;
    }
    match server {
        Some(server) if server.origin() == url.origin() => Route::App,
        _ => Route::Browser,
    }
}

/// Open `url` in the default browser (or mail client, for `mailto:`).
pub fn open_in_browser(url: &Url) {
    let target = url.as_str();
    #[cfg(windows)]
    let opened = {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        std::process::Command::new("rundll32")
            .args(["url.dll,FileProtocolHandler", target])
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
    };
    #[cfg(target_os = "macos")]
    let opened = std::process::Command::new("open").arg(target).spawn();
    #[cfg(all(unix, not(target_os = "macos")))]
    let opened = std::process::Command::new("xdg-open").arg(target).spawn();
    if let Err(error) = opened {
        eprintln!("could not open {target}: {error}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn url(text: &str) -> Url {
        Url::parse(text).unwrap()
    }

    #[test]
    fn app_pages_stay_in_the_app() {
        let server = url("http://127.0.0.1:51234/?t=abc");
        for page in [
            "http://127.0.0.1:51234/apply",
            "http://127.0.0.1:51234/api/jobs/abc/preview.pdf",
            "http://tauri.localhost/index.html",
            "tauri://localhost/index.html",
            "about:blank",
        ] {
            assert_eq!(route(&url(page), Some(&server)), Route::App, "{page}");
        }
    }

    #[test]
    fn outside_pages_open_in_the_browser() {
        let server = url("http://127.0.0.1:51234/");
        for page in [
            "https://jobs.ashbyhq.com/quora/123/application",
            "http://127.0.0.1:9999/",
            "http://localhost:51234/",
            "mailto:someone@example.com",
        ] {
            assert_eq!(route(&url(page), Some(&server)), Route::Browser, "{page}");
        }
        assert_eq!(route(&url("https://example.com/"), None), Route::Browser);
    }

    #[test]
    fn other_schemes_are_blocked() {
        assert_eq!(route(&url("file:///C:/Windows/"), None), Route::Block);
        assert_eq!(route(&url("javascript:alert(1)"), None), Route::Block);
    }
}
