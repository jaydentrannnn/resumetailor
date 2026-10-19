import { describe, expect, it } from "vitest";
import { type Command, matchCommands } from "./commands";

const command = (id: string, title: string, group: string, extra: Partial<Command> = {}) =>
  ({ id, title, group, run: () => {}, ...extra }) as Command;

const COMMANDS = [
  command("reload", "Reload window", "App"),
  command("go-resume", "Resume", "Go to"),
  command("save-pdf", "Save resume as PDF", "Document", { keywords: "download" }),
  command("tailor", "Tailor resume", "Tailor"),
  command("busy", "Find jobs", "Apply", { disabled: true }),
];

const ids = (list: Command[]) => list.map((c) => c.id);

describe("matchCommands", () => {
  it("lists page commands before navigation and the app, without disabled ones", () => {
    expect(ids(matchCommands(COMMANDS, ""))).toEqual(["tailor", "save-pdf", "go-resume", "reload"]);
  });

  it("ranks a title that starts with the query first", () => {
    expect(ids(matchCommands(COMMANDS, "res"))).toEqual(["go-resume", "tailor", "save-pdf"]);
    expect(ids(matchCommands(COMMANDS, "resume pdf"))).toEqual(["save-pdf"]);
  });

  it("matches keywords and group names, and keeps the first of a repeated id", () => {
    expect(ids(matchCommands(COMMANDS, "download"))).toEqual(["save-pdf"]);
    expect(ids(matchCommands(COMMANDS, "go to"))).toEqual(["go-resume"]);
    const twice = [...COMMANDS, command("reload", "Reload again", "App")];
    expect(matchCommands(twice, "reload").map((c) => c.title)).toEqual(["Reload window"]);
  });
});
