import assert from "node:assert/strict";
import test from "node:test";
import { createReadinessHandler } from "./handler.mjs";

test("checks database access with HEAD and never returns customer data or a key", async () => {
  const handler = createReadinessHandler({
    url: "https://project.supabase.co/", apiKey: "eyJ-private-test",
    request: async (url, options) => {
      assert.equal(url, "https://project.supabase.co/rest/v1/orders?select=id&limit=0");
      assert.equal(options.method, "HEAD");
      assert.equal(options.headers.Authorization, "Bearer eyJ-private-test");
      return new Response("private customer data");
    },
  });
  const response = await handler(new Request("https://function.example"));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), {
    ok: true, service: "v6-storage-readiness", database: "ok",
    runtime: "supabase-edge", scope: "database-only",
  });
});

test("modern API keys are not used as bearer JWTs", async () => {
  const handler = createReadinessHandler({
    url: "https://project.supabase.co", apiKey: "sb_secret_test",
    request: async (_url, options) => {
      assert.equal(options.headers.apikey, "sb_secret_test");
      assert.equal(options.headers.Authorization, undefined);
      return new Response(null, { status: 200 });
    },
  });
  assert.equal((await handler(new Request("https://function.example"))).status, 200);
});

test("upstream rejection and timeout fail closed without leaking errors", async () => {
  for (const request of [
    async () => new Response("secret error", { status: 401 }),
    async () => { throw new Error("private credentials"); },
  ]) {
    const handler = createReadinessHandler({ url: "https://project.supabase.co", apiKey: "key", request });
    const response = await handler(new Request("https://function.example"));
    assert.equal(response.status, 503);
    assert.equal((await response.json()).database, "error");
  }
});

test("missing configuration and write methods never access the database", async () => {
  const handler = createReadinessHandler({
    url: "", apiKey: "", request: () => { throw new Error("unexpected request"); },
  });
  assert.equal((await handler(new Request("https://function.example"))).status, 503);
  const response = await handler(new Request("https://function.example", { method: "POST" }));
  assert.equal(response.status, 405);
  assert.equal(response.headers.get("Allow"), "GET");
});
