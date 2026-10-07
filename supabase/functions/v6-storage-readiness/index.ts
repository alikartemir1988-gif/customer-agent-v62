import { createReadinessHandler } from "./handler.mjs";

// Built-in server credentials stay inside Supabase; nothing is sent to Render.
let apiKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
if (!apiKey) {
  try {
    apiKey = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") ?? "{}").default ?? "";
  } catch {
    apiKey = "";
  }
}

Deno.serve(createReadinessHandler({
  url: Deno.env.get("SUPABASE_URL") ?? "",
  apiKey,
}));
