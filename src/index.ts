#!/usr/bin/env bun

import { existsSync } from "node:fs"
import { parseArgs } from "node:util"
import { createInterface } from "node:readline"

const POE_API_URL = "https://api.poe.com/v1/models"
const DEFAULT_OUTPUT = "~/.config/opencode/opencode.jsonc"

interface PoeModel {
  id: string
  object: string
  created: number
  description?: string
  owned_by: string
  permission: unknown[]
  root: string
  parent: null
  architecture: {
    input_modalities: string[]
    output_modalities: string[]
    modality: string
  }
  supported_features?: string[]
  supported_endpoints?: string[]
  pricing: {
    prompt: string | null
    completion: string | null
    image: null | string
    request: null
    input_cache_read?: string
    input_cache_write?: string
  } | null
  context_window?: {
    context_length: number
    max_output_tokens: number
  }
  context_length?: number
  reasoning?: {
    budget: null | string
    required: boolean
    supports_reasoning_effort: boolean
  }
  parameters?: Array<{
    name: string
    schema: Record<string, unknown>
    default_value?: unknown
    description?: string
  }>
}

interface PoeApiResponse {
  object: string
  data: PoeModel[]
}

interface OpencodeModel {
  id: string
  name: string
  family?: string
  release_date: string
  attachment: boolean
  reasoning: boolean
  temperature: boolean
  tool_call: boolean
  interleaved?: boolean | { field: "reasoning_content" | "reasoning_details" }
  cost?: {
    input: number
    output: number
    cache_read?: number
    cache_write?: number
  }
  limit: {
    context: number
    input?: number
    output: number
  }
  modalities?: {
    input: string[]
    output: string[]
  }
  options: Record<string, unknown>
}

function unixToISO(unixMs: number): string {
  return new Date(unixMs).toISOString().split("T")[0]
}

function parsePricing(price: string | null | undefined): number {
  if (!price) return 0
  const parsed = parseFloat(price)
  return isNaN(parsed) ? 0 : parsed
}

function mapModel(poeModel: PoeModel): OpencodeModel {
  const inputMods = poeModel.architecture.input_modalities.map((m) =>
    m.toLowerCase() === "image" ? "image" : m.toLowerCase() === "text" ? "text" : m.toLowerCase(),
  )
  const outputMods = poeModel.architecture.output_modalities.map((m) =>
    m.toLowerCase() === "image" ? "image" : m.toLowerCase() === "text" ? "text" : m.toLowerCase(),
  )
  const pricing = poeModel.pricing ?? { prompt: null, completion: null, image: null, request: null }
  const supportedFeatures = poeModel.supported_features ?? []
  const contextWindow = poeModel.context_window ?? { context_length: 100000, max_output_tokens: 16000 }
  const contextLength = contextWindow.context_length || 100000
  const maxOutput = contextWindow.max_output_tokens || 16000

  return {
    id: poeModel.id,
    name: poeModel.id,
    release_date: unixToISO(poeModel.created),
    attachment: inputMods.includes("image"),
    reasoning: poeModel.reasoning?.supports_reasoning_effort ?? false,
    temperature: true,
    tool_call: supportedFeatures.includes("tools"),
    cost: {
      input: parsePricing(pricing.prompt),
      output: parsePricing(pricing.completion),
      cache_read: parsePricing(pricing.input_cache_read),
      cache_write: parsePricing(pricing.input_cache_write),
    },
    limit: {
      context: contextLength,
      output: maxOutput,
    },
    modalities: {
      input: inputMods.length > 0 ? inputMods : ["text"],
      output: outputMods.length > 0 ? outputMods : ["text"],
    },
    options: {},
  }
}

async function fetchPoeModels(apiKey: string): Promise<PoeApiResponse> {
  const response = await fetch(POE_API_URL, {
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
  })

  if (!response.ok) {
    throw new Error(`Poe API error: ${response.status} ${response.statusText}`)
  }

  return response.json() as Promise<PoeApiResponse>
}

function parseConfig(content: string): Record<string, unknown> {
  try {
    return JSON.parse(content)
  } catch {
    return {}
  }
}

function stringifyJsonc(obj: unknown): string {
  return JSON.stringify(obj, null, 2)
}

async function confirm(prompt: string): Promise<boolean> {
  const answer = await question(`${prompt} (y/N): `)
  return answer.toLowerCase() === "y"
}

async function question(prompt: string): Promise<string> {
  const rl = createInterface({ input: process.stdin, output: process.stdout })
  return new Promise((resolve) => {
    rl.question(prompt, (answer) => {
      rl.close()
      resolve(answer)
    })
  })
}

async function main() {
  const args = parseArgs({
    options: {
      key: { type: "string", short: "k" },
      output: { type: "string", short: "o", default: DEFAULT_OUTPUT },
      help: { type: "boolean", short: "h", default: false },
    },
    allowPositionals: true,
  })

  if (args.values.help) {
    console.log(`
Poe Models Config Generator

Usage:
  bun run src/index.ts --key <POE_API_KEY> [options]

Options:
  -k, --key <API_KEY>       Poe API key (required)
  -o, --output <PATH>       Output config path (default: ~/.config/opencode/opencode.jsonc)
  -h, --help                Show this help message

Example:
  bun run src/index.ts --key sk-test-12345
`)
    process.exit(0)
  }

  const apiKey = args.values.key ?? (args.positionals[0] as string | undefined)
  if (!apiKey) {
    console.error("Error: API key is required. Use --key or pass as positional argument.")
    console.error("Run with --help for usage information.")
    process.exit(1)
  }

  const outputPath = args.values.output!.replace(/^~/, process.env.HOME ?? "")

  console.log("Fetching models from Poe API...")
  let poeData: PoeApiResponse
  try {
    poeData = await fetchPoeModels(apiKey)
  } catch (err) {
    console.error(`Error fetching models: ${err instanceof Error ? err.message : String(err)}`)
    process.exit(1)
  }

  console.log(`Found ${poeData.data.length} models`)

  const models: Record<string, OpencodeModel> = {}
  for (const model of poeData.data) {
    models[model.id] = mapModel(model)
  }

  const existingConfig: Record<string, unknown> = {}
  if (existsSync(outputPath)) {
    console.log(`\nWarning: ${outputPath} already exists!`)
    console.log("This script will replace the entire 'provider.poe.models' section.\n")
    const proceed = await confirm("Continue?")
    if (!proceed) {
      console.log("Aborted.")
      process.exit(0)
    }
    try {
      const file = Bun.file(outputPath)
      const content = await file.text()
      Object.assign(existingConfig, parseConfig(content))
    } catch {
      console.log("Could not parse existing file, starting fresh.")
    }
  }

  const provider = (existingConfig.provider as Record<string, unknown> | undefined) ?? {}
  const poeProvider = (provider["poe"] as Record<string, unknown> | undefined) ?? {}
  poeProvider["models"] = models
  provider["poe"] = poeProvider
  existingConfig["provider"] = provider

  try {
    await Bun.write(outputPath, stringifyJsonc(existingConfig))
    console.log(`\nConfig written to ${outputPath}`)
    console.log(`Run opencode to use models like: poe/Claude-Sonnet-4.5`)
  } catch (err) {
    console.error(`Error writing config: ${err instanceof Error ? err.message : String(err)}`)
    process.exit(1)
  }
}

main()
