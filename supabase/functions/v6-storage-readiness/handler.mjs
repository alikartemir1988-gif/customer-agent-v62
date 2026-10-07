const headers = {
  "Content-Type": "application/json",
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
};

const reply = (ok) => new Response(JSON.stringify({
  ok,
  service: "v6-storage-readiness",
  database: ok ? "ok" : "error",
  runtime: "supabase-edge",
  scope: "database-only",
}), { status: ok ? 200 : 503, headers });

export function createReadinessHandler(checkDatabase) {
  return async (req) => {
    if (req.method !== "GET") {
      return new Response(JSON.stringify({ ok: false, error: "method not allowed" }), {
        status: 405, headers: { ...headers, Allow: "GET" },
      });
    }
    if (!checkDatabase) {
      console.warn("v6 storage readiness: missing built-in configuration");
      return reply(false);
    }

    try {
      await checkDatabase();
      return reply(true);
    } catch {
      console.warn("v6 storage readiness: database connection failed");
      return reply(false);
    }
  };
}
