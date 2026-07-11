import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

const reports = defineCollection({
  loader: glob({ pattern: "**/*.md", base: "./src/content/reports" }),
  schema: z.object({
    title: z.string(),
    reportId: z.string(),
    ticker: z.string().nullable(),
    sector: z.string().nullable(),
    reportType: z.string(),
    author: z.string(),
    authorModel: z.string().nullable(),
    verdict: z
      .object({
        rating: z.string(),
        confidence: z.number(),
        horizon_days: z.number(),
        price_target: z.number().nullable().optional(),
        one_liner: z.string(),
      })
      .nullable(),
    tags: z.array(z.string()),
    publishedAt: z.coerce.date(),
    supersedes: z.string().nullable(),
    provenanceCount: z.number(),
  }),
});

export const collections = { reports };
