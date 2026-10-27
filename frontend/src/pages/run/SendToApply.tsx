import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { sendRunToApply } from "../../api";
import { Modal } from "../../components/Modal";
import { Button } from "../../components/ui";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";

/**
 * "Send to Apply" for a finished run (audit #29): name the posting it was tailored for
 * and Apply tracks it with this run's files, ready to Fill. A posting already on Apply
 * takes the run instead of being added twice. Opens the application afterwards.
 */
export function SendToApply({ jobId, title }: { jobId: string; title: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        Send to Apply
      </Button>
      {open && <SendDialog jobId={jobId} title={title} onClose={() => setOpen(false)} />}
    </>
  );
}

function SendDialog({
  jobId,
  title,
  onClose,
}: {
  jobId: string;
  title: string;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [company, setCompany] = useState("");
  const [role, setRole] = useState(title);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      const result = await sendRunToApply(jobId, {
        posting_url: url.trim(),
        company: company.trim(),
        role: role.trim(),
      });
      const app = result.application;
      toast.success(
        result.created ? `${app.company} added to Apply` : `${app.company} now uses this run`,
        result.reasons.length ? "Open it to see what Fill still needs." : "Ready to Fill.",
      );
      onClose();
      navigate(`/applications/${encodeURIComponent(app.source_job_id)}`);
    } catch (reason) {
      setError(describe(reason).detail);
    } finally {
      setBusy(false);
    }
  }

  const field = "field mt-1 w-full text-sm";
  return (
    <Modal title="Send to Apply" onClose={onClose}>
      <form
        className="mt-4 space-y-3 text-sm"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <p className="text-ink-muted">
          Apply tracks this posting with the resume you just tailored, ready to Fill.
        </p>
        <label className="block text-xs">
          <span className="font-medium">Link to the posting</span>
          <input
            type="url"
            required
            className={field}
            placeholder="https://…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </label>
        <label className="block text-xs">
          <span className="font-medium">Company</span>
          <input className={field} value={company} onChange={(e) => setCompany(e.target.value)} />
        </label>
        <label className="block text-xs">
          <span className="font-medium">Role</span>
          <input className={field} value={role} onChange={(e) => setRole(e.target.value)} />
        </label>
        {error && (
          <p role="alert" className="rounded-sm bg-danger-soft px-3 py-2 text-danger">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="plain" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" size="sm" disabled={busy || !url.trim()}>
            {busy ? "Sending…" : "Send to Apply"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
