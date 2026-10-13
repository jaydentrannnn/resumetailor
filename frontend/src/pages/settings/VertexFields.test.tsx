// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import type { ModelSelection } from "../../lib/aiModels";
import { VertexFields } from "./VertexFields";
import { VertexModelField } from "./VertexModelField";
import type { RoleModel } from "./useRoleModel";

afterEach(cleanup);

const defaults: ModelSelection = {
  provider: "vertex_ai",
  model_name: "vertex_ai/claude-sonnet-5-5",
  api_format: "openai",
  base_url: "",
  plan: null,
  vertex_project: "test-project",
  vertex_location: "global",
};
const models = [
  {
    id: "gemini-3.8-flash",
    name: "Gemini 3.8 Flash",
    publisher: "Google",
    locations: ["global"],
    reasoning: true,
  },
  {
    id: "claude-sonnet-5-5",
    name: "Claude Sonnet 5.5",
    publisher: "Anthropic",
    locations: ["global"],
    reasoning: true,
  },
  {
    id: "zai-org/glm-5.2-maas",
    name: "GLM 5.2 API Service",
    publisher: "Zai-org",
    locations: ["global"],
    reasoning: false,
  },
];

function Fields({
  initial = defaults,
  changed = vi.fn(),
}: {
  initial?: ModelSelection;
  changed?: (fields: Partial<ModelSelection>) => void;
}) {
  const [selection, setSelection] = useState(initial);
  const model = {
    selection,
    patch: (fields: Partial<ModelSelection>) => {
      changed(fields);
      setSelection((prior) => ({ ...prior, ...fields }));
    },
    connection: { vertex: { models, projects: [] } },
  } as unknown as RoleModel;
  return (
    <>
      <VertexModelField model={model} />
      <VertexFields model={model} id="test" />
    </>
  );
}

describe("Vertex settings dropdowns", () => {
  it("shows friendly model names and saves the publisher-qualified managed ID", () => {
    const changed = vi.fn();
    render(<Fields changed={changed} />);
    const dropdown = screen.getByRole("combobox", { name: "Model" }) as HTMLSelectElement;
    expect(dropdown.tagName).toBe("SELECT");
    expect(dropdown.value).toBe("claude-sonnet-5-5");
    expect(screen.getByRole("option", { name: "Claude Sonnet 5.5" })).toBeTruthy();
    fireEvent.change(dropdown, { target: { value: "zai-org/glm-5.2-maas" } });
    expect(changed).toHaveBeenLastCalledWith({ model_name: "zai-org/glm-5.2-maas" });
  });

  it("preserves existing custom IDs and lets the user return to the catalog", () => {
    const changed = vi.fn();
    render(
      <Fields initial={{ ...defaults, model_name: "vertex_ai/new-model" }} changed={changed} />,
    );
    expect(
      (screen.getByRole("textbox", { name: "Custom model ID" }) as HTMLInputElement).value,
    ).toBe("new-model");
    expect(changed).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: "Custom model ID" }), {
      target: { value: "newer-model" },
    });
    expect(changed).toHaveBeenLastCalledWith({ model_name: "newer-model" });
    fireEvent.change(screen.getByRole("combobox", { name: "Model" }), {
      target: { value: "claude-sonnet-5-5" },
    });
    expect(screen.queryByRole("textbox", { name: "Custom model ID" })).toBeNull();
  });

  it("explains welcome-credit eligibility for partner models", () => {
    render(<Fields />);
    expect(screen.getByText(/\$300 welcome credit/)).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Google Cloud credit terms" }).getAttribute("href"),
    ).toBe("https://docs.cloud.google.com/free/docs/free-cloud-features");
    fireEvent.change(screen.getByRole("combobox", { name: "Model" }), {
      target: { value: "gemini-3.8-flash" },
    });
    expect(screen.queryByText(/\$300 welcome credit/)).toBeNull();
  });

  it("uses a location dropdown while preserving a saved region outside the model suggestions", () => {
    const changed = vi.fn();
    render(<Fields initial={{ ...defaults, vertex_location: "us-east5" }} changed={changed} />);
    const location = screen.getByRole("combobox", { name: "Vertex location" });
    expect(location.tagName).toBe("SELECT");
    expect(screen.getByRole("textbox", { name: "Custom location" })).toBeTruthy();
    expect(changed).not.toHaveBeenCalled();
    fireEvent.change(location, { target: { value: "global" } });
    expect(changed).toHaveBeenLastCalledWith({ vertex_location: "global" });
    expect(screen.queryByRole("textbox", { name: "Custom location" })).toBeNull();
    fireEvent.change(location, { target: { value: "__custom__" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Custom location" }), {
      target: { value: "us" },
    });
    expect(changed).toHaveBeenLastCalledWith({ vertex_location: "us" });
  });
});
