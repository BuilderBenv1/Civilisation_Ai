// ClawGig webhook receiver — stores events in clawgig_events table
// Deploy: npx supabase functions deploy clawgig-webhook --project-ref fvolfirncahihzrddbrd
// URL: https://fvolfirncahihzrddbrd.supabase.co/functions/v1/clawgig-webhook

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

Deno.serve(async (req) => {
  // ClawGig sends POST with JSON body
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "POST only" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  try {
    const body = await req.json();
    const eventType = body.event || body.type || "unknown";

    const supabase = createClient(supabaseUrl, supabaseKey);

    const { error } = await supabase.from("clawgig_events").insert({
      event_type: eventType,
      payload: body,
    });

    if (error) {
      console.error("Insert error:", error);
      return new Response(JSON.stringify({ error: error.message }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }

    console.log(`ClawGig event received: ${eventType}`);
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (e) {
    console.error("Webhook error:", e);
    return new Response(JSON.stringify({ error: "Invalid request" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }
});
