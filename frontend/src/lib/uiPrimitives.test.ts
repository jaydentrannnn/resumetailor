import { describe as suite, expect, it } from "vitest";
import { stepState } from "./stepState";
import { ApiError, describe } from "./errors";
import { GLOSSARY } from "./glossary";
import { defaultTimeout, MAX_TOASTS, type Toast, toastReducer } from "./toast";

suite("errors.describe", () => {
  it("maps known server messages to plain language", () => {
    expect(describe(new Error("Could not reach http://localhost:11434/v1: refused")).title).toBe(
      "Can't reach the AI model",
    );
    expect(describe(new Error("Could not reach http://localhost:11434/v1: x")).detail).toContain(
      "http://localhost:11434",
    );
    expect(describe("LibreOffice binary not found at 'soffice'.").code).toBe("soffice_missing");
    const missing = describe("http://h/v1 has no model 'llama3.1'. Pull it with ...");
    expect(missing.code).toBe("model_missing");
    expect(missing.detail).toContain("ollama pull llama3.1");
    expect(describe("No API key found for the 'anthropic' provider").action?.to).toBe("/settings");
  });
  it("prefers the server's code, and falls back to the raw text", () => {
    expect(describe(new ApiError("whatever", 401, "auth")).title).toBe("Your session expired");
    const unknown = describe(new ApiError("Odd failure", 500, undefined, "Try X"));
    expect(unknown).toMatchObject({ code: "unknown", detail: "Try X", raw: "Odd failure" });
    expect(describe(new TypeError("Failed to fetch")).code).toBe("network");
  });
});

suite("toastReducer", () => {
  const toast = (id: number, title = `t${id}`): Toast => ({
    id,
    kind: "info",
    title,
    timeoutMs: 5000,
  });
  it("caps the stack and de-duplicates identical messages", () => {
    let state: Toast[] = [];
    for (let i = 1; i <= MAX_TOASTS + 2; i++)
      state = toastReducer(state, { type: "push", toast: toast(i) });
    expect(state.map((t) => t.id)).toEqual([3, 4, 5, 6]);
    state = toastReducer(state, { type: "push", toast: toast(9, "t4") });
    expect(state.map((t) => t.id)).toEqual([3, 5, 6, 9]);
    expect(toastReducer(state, { type: "dismiss", id: 5 }).map((t) => t.id)).toEqual([3, 6, 9]);
  });
  it("keeps errors until dismissed", () => {
    expect(defaultTimeout("error")).toBeNull();
    expect(defaultTimeout("success")).toBe(5000);
  });
});

suite("stepState", () => {
  it("marks done, current, upcoming and failed steps", () => {
    expect([0, 1, 2, 3].map((i) => stepState(i, 2))).toEqual([
      "done",
      "done",
      "current",
      "upcoming",
    ]);
    expect(stepState(2, 2, 2)).toBe("error");
  });
});

suite("glossary", () => {
  it("has a label and an explanation for every term", () => {
    for (const entry of Object.values(GLOSSARY)) {
      expect(entry.label.length).toBeGreaterThan(3);
      expect(entry.help.length).toBeGreaterThan(20);
    }
  });
});
