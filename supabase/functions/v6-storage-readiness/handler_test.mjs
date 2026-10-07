import assert from "node:assert/strict";
import test from "node:test";
import { createReadinessHandler } from "./handler.mjs";

test("a database probe never returns customer data or credentials", async () => {
  let checked = false;
  const handler = createReadinessHandler(async () => {
    checked = true;
    return "private customer data and credentials";
  });
  const response = await handler(new Request("https://function.example"));
  assert.equal(checked, true);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), {
    ok: true, service: "v6-storage-readiness", database: "ok",
    runtime: "supabase-edge", scope: "database-only",
  });
});

test("a failed database connection does not leak its error", async () => {
  const handler = createReadinessHandler(async () => { throw new Error("private credentials"); });
  const response = await handler(new Request("https://function.example"));
  assert.equal(response.status, 503);
  assert.equal((await response.json()).database, "error");
});

test("missing built-in configuration fails closed", async () => {
  const handler = createReadinessHandler(null);
  assert.equal((await handler(new Request("https://function.example"))).status, 503);
});

test("write methods never access the database", async () => {
  const handler = createReadinessHandler(() => { throw new Error("unexpected query"); });
  const response = await handler(new Request("https://function.example", { method: "POST" }));
  assert.equal(response.status, 405);
  assert.equal(response.headers.get("Allow"), "GET");
});
