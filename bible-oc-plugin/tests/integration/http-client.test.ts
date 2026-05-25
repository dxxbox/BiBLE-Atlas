import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { afterEach, describe, expect, it } from "vitest";
import { BibleAtlasClient } from "../../src/http/client.js";
import { BibleAtlasError } from "../../src/http/errors.js";

let cleanup: (() => Promise<void>) | undefined;

afterEach(async () => {
  await cleanup?.();
  cleanup = undefined;
});

describe("BibleAtlasClient", () => {
  it("calls health directly and unwraps memory search envelope", async () => {
    const { baseUrl, requests, close } = await startServer(async (req, res) => {
      if (req.url === "/health") {
        sendJson(res, { status: "ok" });
        return;
      }
      if (req.url === "/api/search/memory") {
        const body = await readJson(req);
        sendJson(res, {
          status: "ok",
          result: {
            hits: [{ memory_id: "mem_1", title: body.query, score: 0.9 }],
          },
        });
        return;
      }
      res.statusCode = 404;
      sendJson(res, { detail: "missing" });
    });
    cleanup = close;

    const client = new BibleAtlasClient({ baseUrl, timeoutMs: 2_000 });
    await expect(client.health()).resolves.toMatchObject({ status: "ok" });
    await expect(client.searchMemory({ query: "faith" })).resolves.toMatchObject({
      hits: [{ memory_id: "mem_1", title: "faith", score: 0.9 }],
    });
    expect(requests.map((request) => request.url)).toEqual(["/health", "/api/search/memory"]);
  });

  it("falls back for knowledge list and maps error envelopes", async () => {
    const { baseUrl, close } = await startServer(async (req, res) => {
      if (req.url === "/api/control/docs/list") {
        res.statusCode = 404;
        sendJson(res, { detail: "missing" });
        return;
      }
      if (req.url === "/api/v1/knowledge/list") {
        sendJson(res, { status: "ok", result: { tags: ["design"] } });
        return;
      }
      if (req.url === "/api/search/skill") {
        res.statusCode = 401;
        sendJson(res, {
          status: "error",
          error: { code: "UNAUTHENTICATED", message: "bad token" },
        });
        return;
      }
      res.statusCode = 404;
      sendJson(res, {});
    });
    cleanup = close;

    const client = new BibleAtlasClient({ baseUrl, timeoutMs: 2_000 });
    await expect(client.listKnowledge()).resolves.toEqual({ tags: ["design"] });
    await expect(client.searchSkill({ query: "x" })).rejects.toMatchObject({
      code: "BIBLE_AUTH_FAILED",
      message: "bad token",
    } satisfies Partial<BibleAtlasError>);
  });
});

async function startServer(
  handler: (req: IncomingMessage, res: ServerResponse) => void | Promise<void>,
): Promise<{
  baseUrl: string;
  requests: Array<{ method?: string; url?: string }>;
  close: () => Promise<void>;
}> {
  const requests: Array<{ method?: string; url?: string }> = [];
  const server = createServer(async (req, res) => {
    requests.push({ method: req.method, url: req.url });
    await handler(req, res);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("server did not bind to a port");
  return {
    baseUrl: `http://127.0.0.1:${address.port}`,
    requests,
    close: () => new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve()))),
  };
}

function sendJson(res: ServerResponse, payload: unknown): void {
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(payload));
}

async function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(Buffer.from(chunk));
  return JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<string, unknown>;
}
