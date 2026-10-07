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

export function createReadinessHandler({ url, apiKey, request = fetch }) {
  return async (req) => {
    if (req.method !== "GET") {
      return new Response(JSON.stringify({ ok: false, error: "method not allowed" }), {
        status: 405, headers: { ...headers, Allow: "GET" },
      });
    }
    if (!url || !apiKey) {
      console.warn("v6 storage readiness: missing built-in configuration");
      return reply(false);
    }

    try {
      const authHeaders = { apikey: apiKey };
      // Legacy keys are JWTs. Modern secret API keys belong only in apikey.
      if (apiKey.startsWith("eyJ")) authHeaders.Authorization = `Bearer ${apiKey}`;
      const upstream = await request(`${url.replace(/\/$/, "")}/rest/v1/orders?select=id&limit=0`, {
        method: "HEAD",
        headers: authHeaders,
        signal: AbortSignal.timeout(5000),
      });
      if (!upstream.ok) console.warn("v6 storage readiness: database API HTTP", upstream.status);
      return reply(upstream.ok);
    } catch {
      console.warn("v6 storage readiness: database API connection failed");
      return reply(false);
    }
  };
}
