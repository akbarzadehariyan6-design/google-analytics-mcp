import { NextResponse } from "next/server";
import OpenAI from "openai";

const DEFAULT_MODEL = "gpt-5-mini";

export async function GET() {
  const configured = Boolean(process.env.OPENAI_API_KEY?.trim());

  return NextResponse.json({
    configured,
    demoMode: !configured,
    model: process.env.OPENAI_MODEL?.trim() || DEFAULT_MODEL,
  });
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);

  if (!body?.message || typeof body.message !== "string") {
    return NextResponse.json(
      { error: "A message is required." },
      { status: 400 },
    );
  }

  const apiKey = (body.apiKey as string | undefined)?.trim() || process.env.OPENAI_API_KEY?.trim();
  const model = (body.model as string | undefined)?.trim() || DEFAULT_MODEL;

  if (!apiKey) {
    return NextResponse.json({
      id: `demo-${Date.now()}`,
      text: `Demo mode: you said "${body.message}". Add an OpenAI API key to get live responses.`,
      demoMode: true,
    });
  }

  try {
    const client = new OpenAI({ apiKey });

    const response = await client.responses.create({
      model,
      input: body.message,
      previous_response_id: body.previousResponseId ?? undefined,
    });

    return NextResponse.json({
      id: response.id,
      text: response.output_text,
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "The OpenAI request failed.";

    return NextResponse.json(
      { error: message, setupRequired: true },
      { status: 502 },
    );
  }
}
