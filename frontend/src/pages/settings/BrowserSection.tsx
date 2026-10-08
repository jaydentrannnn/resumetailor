import { useCallback, useEffect, useState } from "react";
import {
  createExtensionPairingCode,
  listExtensionPairings,
  revokeExtensionPairing,
  type ExtensionPairing,
} from "../../api";
import { Button, Card, Modal } from "../../components/ui";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";
import { pairingCountdown, pairingDate, secondsRemaining } from "./browserPairing";
import { SettingRow } from "./SettingRow";

const RELEASES_URL = "https://github.com/jaydentrannnn/resumetailor/releases/latest";
/** Chrome Web Store / Edge Add-ons pages, once published (extension/store/SUBMITTING.md). */
const STORE_LINKS: { label: string; url: string }[] = [];

export function BrowserSection() {
  const toast = useToast();
  const [pairings, setPairings] = useState<ExtensionPairing[]>([]);
  const [code, setCode] = useState("");
  const [expiresAt, setExpiresAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [confirm, setConfirm] = useState<ExtensionPairing | null>(null);

  const refresh = useCallback(() => {
    void listExtensionPairings()
      .then(setPairings)
      .catch((error) => {
        toast.error("Could not load paired browsers", describe(error).detail);
      });
  }, [toast]);

  useEffect(() => {
    refresh();
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [refresh]);

  useEffect(() => {
    if (!code) return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    const listTimer = window.setInterval(refresh, 5000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(listTimer);
    };
  }, [code, refresh]);

  async function createCode() {
    setCreating(true);
    try {
      const result = await createExtensionPairingCode();
      const current = Date.now();
      setNow(current);
      setCode(result.code);
      setExpiresAt(current + result.expires_in * 1000);
    } catch (error) {
      toast.error("Could not create pairing code", describe(error).detail);
    } finally {
      setCreating(false);
    }
  }

  async function revoke() {
    if (!confirm) return;
    setRevoking(true);
    try {
      await revokeExtensionPairing(confirm.id);
      setConfirm(null);
      refresh();
      toast.success("Browser revoked");
    } catch (error) {
      toast.error("Could not revoke browser", describe(error).detail);
      refresh();
    } finally {
      setRevoking(false);
    }
  }

  const remaining = secondsRemaining(expiresAt, now);
  return (
    <div className="space-y-4">
      <Card
        title="Browser extension"
        description="Capture the job you are viewing, save jobs from LinkedIn and Indeed search results, and see what is already in your queue."
      >
        {STORE_LINKS.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {STORE_LINKS.map((store) => (
              <a
                key={store.label}
                className="rounded-sm border border-line px-3 py-2 text-sm"
                href={store.url}
                target="_blank"
                rel="noreferrer"
              >
                {store.label} ↗
              </a>
            ))}
          </div>
        )}
        <ol className="list-decimal space-y-1 pl-5 text-sm">
          <li>
            Download <span className="font-mono">resumetailor-extension-&lt;version&gt;.zip</span>{" "}
            from the{" "}
            <a className="rt-link" href={RELEASES_URL} target="_blank" rel="noreferrer">
              latest release
            </a>{" "}
            and unzip it.
          </li>
          <li>
            In Chrome open <span className="font-mono">chrome://extensions</span> (Edge:{" "}
            <span className="font-mono">edge://extensions</span>) and turn on Developer mode.
          </li>
          <li>Choose Load unpacked and select the unzipped folder.</li>
          <li>Pin ResumeTailor to the toolbar, then pair it below.</li>
        </ol>
        <p className="mt-3 text-sm text-ink-muted">
          In the extension&apos;s options, allow LinkedIn and Indeed to save jobs from search
          results and complete them when you open them. Everything stays on this computer.
        </p>
      </Card>
      <Card title="Pair a browser">
        <SettingRow
          label="Pairing code"
          description="Type the code into the ResumeTailor extension popup."
        >
          {code && remaining > 0 ? (
            <div className="space-y-2">
              <p className="font-mono text-3xl tracking-widest" aria-label={`Pairing code ${code}`}>
                {code}
              </p>
              <p className="text-sm text-ink-muted" role="timer">
                Expires in {pairingCountdown(remaining)}
              </p>
            </div>
          ) : code ? (
            <p className="text-sm text-ink-muted">Code expired.</p>
          ) : null}
          <Button loading={creating} onClick={() => void createCode()}>
            {code ? "New code" : "Pair a browser"}
          </Button>
          {code && (
            <p className="mt-2 text-xs text-ink-muted">A new code replaces the previous one.</p>
          )}
        </SettingRow>
      </Card>
      <Card title="Paired browsers">
        {pairings.length === 0 ? (
          <p className="text-sm text-ink-muted">No browsers paired yet.</p>
        ) : (
          <ul className="divide-y divide-line">
            {pairings.map((pairing) => (
              <li
                key={pairing.id}
                className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm"
              >
                <div>
                  <p className="font-medium">{pairing.label}</p>
                  <p className="text-ink-muted">
                    Paired {pairingDate(pairing.created_at)} · Last seen{" "}
                    {pairingDate(pairing.last_seen)}
                  </p>
                </div>
                <Button onClick={() => setConfirm(pairing)}>Revoke</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {confirm && (
        <Modal title="Revoke browser?" onClose={() => setConfirm(null)}>
          <p className="my-4 text-sm">{confirm.label} will need a new pairing code to reconnect.</p>
          <Button variant="danger" loading={revoking} onClick={() => void revoke()}>
            Revoke
          </Button>
        </Modal>
      )}
    </div>
  );
}
