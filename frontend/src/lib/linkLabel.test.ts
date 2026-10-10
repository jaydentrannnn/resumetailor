import { describe, expect, it } from "vitest";
import { labelForUrl, nextLinkLabel } from "./linkLabel";

describe("labelForUrl", () => {
  it.each([
    ["https://github.com/me/repo", "GitHub"],
    ["github.com/me/repo", "GitHub"],
    ["https://www.youtube.com/watch?v=x", "YouTube"],
    ["https://youtu.be/x", "YouTube"],
    ["https://huggingface.co/spaces/me/demo", "Hugging Face"],
    ["https://gist.github.com/me/1", "GitHub"],
    ["https://me.github.io/site", "Live demo"],
    ["https://my-app.vercel.app", "Live demo"],
    ["https://example.com/thing", "Example"],
    ["https://devpost.com/software/x", "Devpost"],
  ])("%s → %s", (url, label) => {
    expect(labelForUrl(url)).toBe(label);
  });

  it("returns empty for empty or unparseable input", () => {
    expect(labelForUrl("")).toBe("");
    expect(labelForUrl("   ")).toBe("");
    expect(labelForUrl("not a url")).toBe("");
    expect(labelForUrl("localhost")).toBe("");
  });
});

describe("nextLinkLabel", () => {
  it("fills an empty label from the new URL", () => {
    expect(nextLinkLabel("", "", "https://github.com/me/x")).toBe("GitHub");
  });

  it("follows the URL while the label is still the derived default", () => {
    expect(nextLinkLabel("GitHub", "https://github.com/me/x", "https://devpost.com/x")).toBe(
      "Devpost",
    );
  });

  it("replaces the legacy Github default", () => {
    expect(nextLinkLabel("Github", "https://github.com/me/x", "https://github.com/me/y")).toBe(
      "GitHub",
    );
  });

  it("keeps a label the user typed", () => {
    expect(nextLinkLabel("Source", "https://github.com/me/x", "https://gitlab.com/me/x")).toBe(
      "Source",
    );
  });

  it("clears a derived label when the URL is cleared", () => {
    expect(nextLinkLabel("GitHub", "https://github.com/me/x", "")).toBe("");
  });
});
