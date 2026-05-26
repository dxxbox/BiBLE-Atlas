import { afterEach, describe, expect, it } from "vitest";
import { createServer, type Server } from "node:http";
import { BibleAtlasClient } from "../../src/http/client.js";

let server: Server | undefined;
afterEach(() => new Promise<void>((resolve) => server ? server.close(() => resolve()) : resolve()));

async function start(handler: Parameters<typeof createServer>[0]) {
  server = createServer(handler);
  await new Promise<void>((resolve) => server!.listen(0, "127.0.0.1", resolve));
  const addr = server.address();
  if (!addr || typeof addr === "string") throw new Error("bad addr");
  return `http://127.0.0.1:${addr.port}`;
}

describe("HTTP client", () => {
  it("unwraps health and search envelopes", async () => {
    const baseUrl = await start((req, res) => {
      res.setHeader("Content-Type", "application/json");
      if (req.url === "/health") res.end(JSON.stringify({ status: "ok" }));
      else if (req.url === "/api/search/memory") res.end(JSON.stringify({ status: "ok", result: { hits: [{ memory_id: "m1" }] } }));
      else { res.statusCode = 404; res.end(JSON.stringify({ detail: "missing" })); }
    });
    const client = new BibleAtlasClient({ baseUrl, timeoutMs: 1000 });
    await expect(client.health()).resolves.toMatchObject({ status: "ok" });
    await expect(client.searchMemory({ query: "hello" })).resolves.toMatchObject({ hits: [{ memory_id: "m1" }] });
  });

  it("maps 4xx, 5xx, and timeout", async () => {
    const baseUrl = await start((req, res) => {
      res.setHeader("Content-Type", "application/json");
      if (req.url === "/api/search/memory") { res.statusCode = 422; res.end(JSON.stringify({ status: "error", error: { code: "INVALID_ARGUMENT", message: "bad" } })); }
      else if (req.url === "/api/search/skill") { res.statusCode = 503; res.end(JSON.stringify({ detail: "down" })); }
      else if (req.url === "/health") setTimeout(() => res.end(JSON.stringify({ status: "ok" })), 50);
    });
    const client = new BibleAtlasClient({ baseUrl, timeoutMs: 1000 });
    await expect(client.searchMemory({ query: "x" })).rejects.toMatchObject({ code: "BIBLE_CONTRACT_MISMATCH" });
    await expect(client.searchSkill({ query: "x" })).rejects.toMatchObject({ code: "BIBLE_SERVICE_UNAVAILABLE" });

    const timeoutClient = new BibleAtlasClient({ baseUrl, timeoutMs: 10 });
    await expect(timeoutClient.health()).rejects.toMatchObject({ code: "BIBLE_TIMEOUT" });
  });
});
