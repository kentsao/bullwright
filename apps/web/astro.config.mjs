// @ts-check
import { defineConfig } from "astro/config";
import rehypeSanitize from "rehype-sanitize";

// Static output only — no server runtime, minimal attack surface.
// rehype-sanitize strips any HTML that survives the API's ingest
// rejection and the exporter's escaping (defense in depth, rule S5).
export default defineConfig({
  output: "static",
  markdown: {
    rehypePlugins: [rehypeSanitize],
  },
});
