import { useEffect, useRef, useState } from "react";
import { cancelVertexAuth, disconnectVertex, fetchVertexAuth, startVertexAuth } from "../../api";
import { Button } from "../../components/ui";
import { startAdaptivePoll } from "../../lib/adaptivePoll";
import { describe } from "../../lib/errors";
import { useVertexConnection, vertexChanged } from "./useVertexConnection";

export function VertexConnectionPanel() {
  const { connection, detail: loadDetail } = useVertexConnection(true);
  const [flow, setFlow] = useState<{ flow_id: string; authorization_url: string } | null>(null);
  const [detail, setDetail] = useState("");
  const [busy, setBusy] = useState(false);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    if (!flow) return;
    const poll = startAdaptivePoll(async () => {
      try {
        const status = await fetchVertexAuth(flow.flow_id);
        if (!live.current) return false;
        if (status.status === "pending") return true;
        setDetail(status.detail);
        setFlow(null);
        vertexChanged();
      } catch (err) {
        if (live.current) {
          setDetail(describe(err).detail);
          setFlow(null);
        }
      }
      return false;
    });
    return () => poll.stop();
  }, [flow]);
  async function act(action: "connect" | "disconnect" | "cancel") {
    setBusy(true);
    setDetail("");
    try {
      if (action === "connect") {
        const next = await startVertexAuth();
        if (live.current) {
          setFlow(next);
          // Tauri routes outside links to the system browser, never the app webview.
          const link = document.createElement("a");
          link.href = next.authorization_url;
          link.target = "_blank";
          link.rel = "noreferrer";
          link.click();
        }
      } else if (action === "cancel" && flow) {
        await cancelVertexAuth(flow.flow_id);
        if (live.current) setFlow(null);
      } else {
        await disconnectVertex();
        if (live.current) {
          setFlow(null);
          vertexChanged();
        }
      }
    } catch (err) {
      if (live.current) setDetail(describe(err).detail);
    } finally {
      if (live.current) setBusy(false);
    }
  }
  return (
    <div className="mt-4 border-t border-line pt-4">
      <h3 className="text-sm font-semibold">Google Cloud connection</h3>
      <p className="mt-1 text-xs text-ink-muted">
        {connection?.connected
          ? `Connected as ${connection.email}. Shared by Light and Heavy.`
          : "Connect your Google account, then confirm your project and location."}
      </p>
      {connection && !connection.configured && (
        <p className="mt-2 text-xs text-ink-muted">
          Google connection unavailable. This app build needs ResumeTailor's Desktop OAuth
          configuration.
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {!flow && (
          <Button
            size="sm"
            disabled={!connection?.configured || busy}
            onClick={() => void act("connect")}
          >
            {connection?.connected ? "Reconnect / change account" : "Connect Google Cloud"}
          </Button>
        )}
        {flow && (
          <>
            <a
              className="rt-link text-sm"
              href={flow.authorization_url}
              target="_blank"
              rel="noreferrer"
            >
              Continue sign-in in browser
            </a>
            <Button size="sm" variant="plain" disabled={busy} onClick={() => void act("cancel")}>
              Cancel sign-in
            </Button>
          </>
        )}
        {connection?.connected && (
          <Button size="sm" variant="plain" disabled={busy} onClick={() => void act("disconnect")}>
            Disconnect / remove credentials
          </Button>
        )}
      </div>
      {(detail || loadDetail) && (
        <p role="status" className="mt-2 text-xs text-ink-muted">
          {detail || loadDetail}
        </p>
      )}
      <p className="mt-3 text-xs text-ink-muted">
        Usage is billed to your selected Google Cloud project. Credit coverage depends on your
        billing account and Google's terms.{" "}
        <a
          className="rt-link"
          href="https://console.cloud.google.com/billing"
          target="_blank"
          rel="noreferrer"
        >
          Check billing and credits
        </a>
        .
      </p>
      <p className="mt-1 text-xs text-ink-muted">
        Disconnect removes credentials from this app. To revoke Google's grant, visit{" "}
        <a
          className="rt-link"
          href="https://myaccount.google.com/connections"
          target="_blank"
          rel="noreferrer"
        >
          Google account permissions
        </a>
        .
      </p>
    </div>
  );
}
