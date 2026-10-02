// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AskAnswerCard } from "./AskAnswerCard";

const answer = vi.hoisted(() => vi.fn());
vi.mock("../api", () => ({ answerApplicationQuestion: answer }));

// No `test.globals`, so Testing Library's automatic cleanup never registers.
afterEach(() => {
  cleanup();
  answer.mockReset();
});

const draft = { answer: "", offenders: [], warnings: [], source: "llm", model: "m" };

function ask(question = "Why us?", context = "") {
  render(<AskAnswerCard jobId="job1" />);
  fireEvent.change(screen.getByLabelText("Question"), { target: { value: question } });
  if (context) {
    fireEvent.change(screen.getByLabelText(/Extra context/), { target: { value: context } });
  }
  fireEvent.click(screen.getByRole("button", { name: "Generate answer" }));
}

describe("AskAnswerCard", () => {
  it("disables Generate until a question is typed", () => {
    render(<AskAnswerCard jobId="job1" />);
    const button = screen.getByRole("button", { name: "Generate answer" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("sends the question and context and shows the draft with its length", async () => {
    answer.mockResolvedValue({ ...draft, answer: "I fit well.", warnings: ["truncated"] });
    ask("Why us?", "I led a club.");
    expect(await screen.findByText("I fit well.")).toBeTruthy();
    expect(answer).toHaveBeenCalledWith("job1", {
      question: "Why us?",
      context: "I led a club.",
      maxChars: 1500,
      regenerate: false,
    });
    expect(screen.getByText("11 characters")).toBeTruthy();
    expect(screen.getByText("truncated")).toBeTruthy();
  });

  it("regenerates without the cache", async () => {
    answer.mockResolvedValue({ ...draft, answer: "First." });
    ask();
    fireEvent.click(await screen.findByRole("button", { name: "Regenerate" }));
    await waitFor(() => expect(answer).toHaveBeenCalledTimes(2));
    expect(answer.mock.calls[1][1].regenerate).toBe(true);
  });

  it("explains a blocked draft and points at Extra context", async () => {
    answer.mockResolvedValue({ ...draft, offenders: ["kubernetes"] });
    ask();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("kubernetes");
    expect(alert.textContent).toContain("Extra context");
  });

  it("shows a request failure", async () => {
    answer.mockRejectedValue(new Error("boom"));
    ask();
    expect((await screen.findByRole("alert")).textContent).toContain("boom");
  });
});

describe("AskAnswerCard suggestions", () => {
  it("fills the question from an unanswered-question chip", () => {
    render(<AskAnswerCard jobId="job1" suggestions={["Why do you want to work here?"]} />);
    fireEvent.click(screen.getByRole("button", { name: "Why do you want to work here?" }));
    expect((screen.getByLabelText("Question") as HTMLTextAreaElement).value).toBe(
      "Why do you want to work here?",
    );
  });

  it("clamps the character limit when sending", async () => {
    answer.mockResolvedValue({ ...draft, answer: "Ok." });
    render(<AskAnswerCard jobId="job1" />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Why?" } });
    fireEvent.change(screen.getByLabelText("Character limit"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate answer" }));
    await screen.findByText("Ok.");
    expect(answer.mock.calls[0][1].maxChars).toBe(1500);
  });
});
