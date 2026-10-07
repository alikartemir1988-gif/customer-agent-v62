import { createReadinessHandler } from "./handler.mjs";
import postgres from "npm:postgres@3.4.7";

// The built-in connection stays inside Supabase. No Render or Data API dependency.
const connectionString = Deno.env.get("SUPABASE_DB_URL") ?? "";
const sql = connectionString ? postgres(connectionString, {
  prepare: false,
  max: 1,
  connect_timeout: 5,
  idle_timeout: 5,
  connection: { application_name: "v6-storage-readiness", statement_timeout: 5000 },
}) : null;

Deno.serve(createReadinessHandler(sql ? async () => {
  // Confirms table access without retrieving or returning customer records.
  await sql`SELECT 1 FROM public.orders WHERE false`;
} : null));
