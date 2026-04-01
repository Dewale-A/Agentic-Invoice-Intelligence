import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL || "http://35.171.2.221:8081";

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();

    const res = await fetch(`${API_URL}/invoices/upload`, {
      method: "POST",
      body: formData,
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json({ error: "Failed to upload" }, { status: 502 });
  }
}
