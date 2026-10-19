//! Windows: switches off WebView2's browser accelerator keys (F5, Ctrl+R, Ctrl+P, Ctrl+U,
//! F12, ...) and its default context menus for the main window.
//!
//! `lockdown.js` blocks the same things from page script, but only in the main frame;
//! these settings also cover the embedded PDF viewer, which page script cannot reach.
//! Editing keys (Ctrl+C/V/X/Z/A) are not browser accelerators and keep working, and
//! the page still receives every `keydown` and `contextmenu` event.
//!
//! Debug builds keep both, so DevTools and Inspect stay available while developing.

#[cfg(windows)]
pub fn lock(window: &tauri::WebviewWindow) {
    if cfg!(debug_assertions) {
        return;
    }
    let result = window.with_webview(|webview| unsafe {
        use webview2_com::Microsoft::Web::WebView2::Win32::ICoreWebView2Settings3;
        use windows_core::Interface;

        let Ok(core) = webview.controller().CoreWebView2() else {
            return;
        };
        let Ok(settings) = core.Settings() else {
            return;
        };
        let _ = settings.SetAreDefaultContextMenusEnabled(false);
        if let Ok(settings3) = settings.cast::<ICoreWebView2Settings3>() {
            let _ = settings3.SetAreBrowserAcceleratorKeysEnabled(false);
        }
    });
    if let Err(error) = result {
        eprintln!("could not lock the webview: {error}");
    }
}

#[cfg(not(windows))]
pub fn lock(_window: &tauri::WebviewWindow) {}
