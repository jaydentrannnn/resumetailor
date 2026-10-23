import { useState } from "react";
import { Link } from "react-router-dom";
import type { CompanyResearchRequest } from "../../../api";
import { Button, Tile } from "../../../components/ui";
import { researchMeta, splitAddition } from "../../../lib/companyResearch";
import { describe } from "../../../lib/errors";
import { useToast } from "../../../lib/toast";
import { useCompanyResearch } from "../../../lib/useCompanyResearch";
import { CompanyFacts } from "./CompanyFacts";

/**
 * "Company": facts about the employer, each quoted from a page that was read (the
 * posting, the company's site, news, or what the student adds). Research runs only when
 * asked. Never counted as the student's experience.
 */
export function CompanyTile({ sourceJobId }: { sourceJobId: string }) {
  const toast = useToast();
  const company = useCompanyResearch(sourceJobId);
  const [adding, setAdding] = useState(false);
  const [addition, setAddition] = useState("");
  const { view, busy } = company;
  if (!view) return null;
  const research = view.research;

  const run = async (body: CompanyResearchRequest, failed: string) => {
    try {
      await company.research(body);
      return true;
    } catch (reason) {
      toast.error(failed, describe(reason).detail);
      return false;
    }
  };
  const add = async () => {
    if (await run(splitAddition(addition), "Could not add that")) {
      setAddition("");
      setAdding(false);
    }
  };
  const remove = (factId: string) =>
    company
      .remove(factId)
      .catch((reason) => toast.error("Could not remove", describe(reason).detail));

  return (
    <Tile
      title="Company"
      meta={
        <span className="text-xs text-ink-muted">
          {researchMeta(research)}
          {view.stale ? " · over 30 days old" : ""}
        </span>
      }
      actions={
        research ? (
          <div className="flex gap-2">
            <Button size="sm" variant="plain" disabled={busy} onClick={() => setAdding(true)}>
              Add a page or note
            </Button>
            <Button
              size="sm"
              variant={view.stale ? "secondary" : "plain"}
              loading={busy && !adding}
              disabled={busy}
              onClick={() => void run({ refresh: true }, "Could not refresh")}
            >
              Refresh
            </Button>
          </div>
        ) : (
          <Button
            size="sm"
            loading={busy}
            onClick={() => void run({}, `Could not research ${view.company}`)}
          >
            Research company
          </Button>
        )
      }
    >
      <p className="mb-3 text-xs text-ink-muted">
        About the company, from the pages listed. Never counted as your experience.
        {!view.search && (
          <>
            {" "}
            Only the posting and pages you add are read; a Brave or Tavily key in{" "}
            <Link className="rt-link" to="/settings?tab=ai">
              Settings
            </Link>{" "}
            also searches the web.
          </>
        )}
      </p>
      {adding && (
        <div className="mb-4 space-y-2">
          <textarea
            className="field min-h-20 w-full"
            aria-label="A link or a note about the company"
            placeholder="Paste a link to a page about the company, or type a note"
            value={addition}
            onChange={(event) => setAddition(event.target.value)}
          />
          <div className="flex gap-2">
            <Button size="sm" loading={busy} disabled={!addition.trim()} onClick={() => void add()}>
              Add
            </Button>
            <Button size="sm" variant="plain" disabled={busy} onClick={() => setAdding(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
      {research ? (
        <CompanyFacts research={research} busy={busy} onRemove={(id) => void remove(id)} />
      ) : (
        <p className="text-sm text-ink-muted">
          Not researched yet. Research company reads the posting
          {view.search ? ", the company's site and recent news" : ""} and lists what they say.
        </p>
      )}
    </Tile>
  );
}
