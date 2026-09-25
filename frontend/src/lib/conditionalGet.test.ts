import { afterEach, describe, expect, it, vi } from "vitest";
import { conditionalGet } from "../api";

afterEach(() => vi.unstubAllGlobals());

describe("conditionalGet", () => {
  it("returns the cached object on 304 and sends the stored ETag", async () => {
    const calls: RequestInit[] = [];
    const responses = [
      new Response(JSON.stringify({ rows: [1] }), { status: 200, headers: { ETag: 'W/"a"' } }),
      new Response(null, { status: 304, headers: { ETag: 'W/"a"' } }),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_path: string, init: RequestInit) => {
        calls.push(init);
        return responses.shift()!;
      }),
    );
    const first = await conditionalGet<{ rows: number[] }>("/api/x-etag-test");
    const second = await conditionalGet<{ rows: number[] }>("/api/x-etag-test");
    expect(second).toBe(first);
    expect(calls[1].headers).toEqual({ "If-None-Match": 'W/"a"' });
  });

  it("throws the server's detail on an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "nope" }), { status: 422 })),
    );
    await expect(conditionalGet("/api/x-error-test")).rejects.toThrow("nope");
  });
});
