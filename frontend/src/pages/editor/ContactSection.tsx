import { Tile } from "../../components/ui";
import { type MasterResume, looksLikeHttpUrl } from "../../lib/resumeEdit";
import { TextField } from "./TextField";

export function ContactSection({
  resume,
  setResume,
}: {
  resume: MasterResume;
  setResume: (resume: MasterResume) => void;
}) {
  return (
    <Tile title="Contact">
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <TextField
          label="Name"
          value={resume.contact.name}
          onChange={(v) => setResume({ ...resume, contact: { ...resume.contact, name: v } })}
        />
        <TextField
          label="Email"
          value={resume.contact.email}
          onChange={(v) => setResume({ ...resume, contact: { ...resume.contact, email: v } })}
        />
        <TextField
          label="Phone"
          value={resume.contact.phone ?? ""}
          onChange={(v) => setResume({ ...resume, contact: { ...resume.contact, phone: v } })}
        />
        <TextField
          label="Location"
          value={resume.contact.location ?? ""}
          onChange={(v) => setResume({ ...resume, contact: { ...resume.contact, location: v } })}
        />
        <TextField
          label="LinkedIn URL"
          value={resume.contact.linkedin ?? ""}
          onChange={(v) => setResume({ ...resume, contact: { ...resume.contact, linkedin: v } })}
        />
        <TextField
          label="GitHub URL"
          value={resume.contact.github ?? ""}
          onChange={(v) => setResume({ ...resume, contact: { ...resume.contact, github: v } })}
        />
      </div>
      {(resume.contact.linkedin ?? "").trim() &&
        !looksLikeHttpUrl(resume.contact.linkedin ?? "") && (
          <p className="mt-2 text-xs text-attn">
            LinkedIn URL should start with http:// or https://.
          </p>
        )}
      {(resume.contact.github ?? "").trim() && !looksLikeHttpUrl(resume.contact.github ?? "") && (
        <p className="mt-2 text-xs text-attn">GitHub URL should start with http:// or https://.</p>
      )}
    </Tile>
  );
}
