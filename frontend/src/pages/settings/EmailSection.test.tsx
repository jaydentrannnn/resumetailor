// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MailAccount } from "../../api";
import { EmailSection } from "./EmailSection";

const api = vi.hoisted(() => ({
  getMailAccount: vi.fn(),
  saveMailAccount: vi.fn(),
  removeMailAccount: vi.fn(),
  testMailAccount: vi.fn(),
  checkMailNow: vi.fn(),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  ...api,
}));
vi.mock("../../lib/toast", () => ({ useToast: () => toast }));

const empty: MailAccount = {
  host: "",
  port: 993,
  username: "",
  password_set: false,
  every_hours: 3,
  auto_close: false,
  last_checked: "",
  last_error: "",
  last_result: null,
  running: false,
  confident_pending: 0,
};
const saved: MailAccount = { ...empty, host: "mail.example.com", username: "me@example.com", password_set: true };

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const type = (name: string, value: string) =>
  fireEvent.change(screen.getByRole("textbox", { name }), { target: { value } });

describe("EmailSection", () => {
  it("saves an account with a write-only password and says it is read-only", async () => {
    api.getMailAccount.mockResolvedValue(empty);
    api.saveMailAccount.mockResolvedValue(saved);
    render(<EmailSection />);
    await screen.findByText(/never marks, moves or deletes mail/);
    expect(screen.getByRole("switch", { name: "Close confident rejections automatically" })).toHaveProperty(
      "disabled",
      true,
    );
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toHaveProperty("disabled", true);

    type("IMAP server", " mail.example.com ");
    type("Username", "me@example.com");
    const password = screen.getByLabelText("Password") as HTMLInputElement;
    expect(password.type).toBe("password");
    fireEvent.change(password, { target: { value: "s3cret" } });
    fireEvent.click(save);
    await waitFor(() =>
      expect(api.saveMailAccount).toHaveBeenCalledWith({
        host: "mail.example.com",
        port: 993,
        username: "me@example.com",
        password: "s3cret",
        every_hours: 3,
        auto_close: false,
      }),
    );
    expect(await screen.findByText("Saved")).toBeTruthy();
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
  });

  it("shows a test's result, and a refused login in plain words", async () => {
    api.getMailAccount.mockResolvedValue(saved);
    api.testMailAccount.mockResolvedValueOnce({ folders: 3 });
    render(<EmailSection />);
    fireEvent.click(await screen.findByRole("button", { name: "Test connection" }));
    expect((await screen.findByRole("status")).textContent).toContain("3 folders");
    expect(api.testMailAccount).toHaveBeenCalledWith({
      host: "mail.example.com",
      port: 993,
      username: "me@example.com",
      password: "",
    });

    api.testMailAccount.mockRejectedValueOnce(new Error("The mail server refused that username or password."));
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Could not connect");
    expect(alert.textContent).toContain("refused that username or password");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("turns automatic closing on, shows what it would close, checks now and removes", async () => {
    api.getMailAccount.mockResolvedValue({ ...saved, confident_pending: 2 });
    api.saveMailAccount.mockImplementation(async (body) => ({ ...saved, ...body, password: undefined }));
    api.checkMailNow.mockResolvedValue({ ...saved, running: true });
    api.removeMailAccount.mockResolvedValue(empty);
    render(<EmailSection />);
    expect(await screen.findByText(/2 would close now/)).toBeTruthy();

    fireEvent.click(screen.getByRole("switch", { name: "Close confident rejections automatically" }));
    await waitFor(() => expect(api.saveMailAccount).toHaveBeenCalledWith(expect.objectContaining({ auto_close: true, password: "" })));
    fireEvent.change(screen.getByRole("combobox", { name: "Check every" }), { target: { value: "0" } });
    await waitFor(() => expect(api.saveMailAccount).toHaveBeenLastCalledWith(expect.objectContaining({ every_hours: 0 })));

    fireEvent.click(screen.getByRole("button", { name: "Check now" }));
    expect(await screen.findByText("Checking now…")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Remove account" }));
    await waitFor(() => expect(api.removeMailAccount).toHaveBeenCalled());
    expect(await screen.findByText("Not set")).toBeTruthy();
  });
});
