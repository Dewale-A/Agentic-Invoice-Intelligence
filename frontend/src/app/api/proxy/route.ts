import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL || "http://35.171.2.221:8081";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { endpoint, ...data } = body;

    const res = await fetch(`${API_URL}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });

    const responseData = await res.json();
    return NextResponse.json(responseData, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: "Failed to connect to API" }, { status: 502 });
  }
}

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const endpoint = searchParams.get("endpoint") || "/health";

    const res = await fetch(`${API_URL}${endpoint}`);
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: "Failed to connect to API" }, { status: 502 });
  }
}
