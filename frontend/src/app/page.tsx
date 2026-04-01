"use client";

import { useState, useEffect } from "react";
import {
  Upload,
  FileText,
  Shield,
  BarChart3,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Users,
  Eye,
  ChevronRight,
  XCircle,
  Loader2,
  RefreshCw,
  FileSearch,
  Scale,
} from "lucide-react";

const PROXY = "/api/proxy";

interface GovDashboard {
  total_processed: number;
  pending_review: number;
  auto_approved: number;
  escalated_l1: number;
  escalated_l2: number;
  escalated_l3: number;
  blocked: number;
  avg_confidence: number;
  duplicate_flags: number;
  unknown_vendor_flags: number;
  amount_variance_flags: number;
}

interface Invoice {
  invoice_id: string;
  source_filename: string;
  vendor_name: string;
  invoice_number: string;
  total: number;
  currency: string;
  status: string;
  extraction_confidence: number;
  created_at: string;
}

interface HealthData {
  status: string;
  database: string;
  vendor_count: number;
}

type Tab = "dashboard" | "upload" | "invoices" | "reviews" | "governance";

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>("dashboard");
  const [health, setHealth] = useState<HealthData | null>(null);
  const [govDashboard, setGovDashboard] = useState<GovDashboard | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [pendingReviews, setPendingReviews] = useState<any[]>([]);
  const [auditTrail, setAuditTrail] = useState<any[]>([]);
  const [uploadStatus, setUploadStatus] = useState("");
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selectedInvoice, setSelectedInvoice] = useState<string | null>(null);
  const [invoiceAudit, setInvoiceAudit] = useState<any>(null);

  // Review form state
  const [reviewForm, setReviewForm] = useState({
    reviewer_id: "",
    reviewer_name: "",
    decision: "approve",
    rationale_category: "amount_within_variance",
    rationale_text: "",
  });
  const [reviewResult, setReviewResult] = useState<any>(null);

  useEffect(() => {
    fetchAll();
  }, []);

  const fetchAll = async () => {
    setLoading(true);
    await Promise.all([fetchHealth(), fetchDashboard(), fetchInvoices(), fetchPendingReviews()]);
    setLoading(false);
  };

  const fetchHealth = async () => {
    try {
      const res = await fetch(`${PROXY}?endpoint=/health`);
      if (res.ok) setHealth(await res.json());
    } catch (e) {}
  };

  const fetchDashboard = async () => {
    try {
      const res = await fetch(`${PROXY}?endpoint=/governance/dashboard`);
      if (res.ok) setGovDashboard(await res.json());
    } catch (e) {}
  };

  const fetchInvoices = async () => {
    try {
      const res = await fetch(`${PROXY}?endpoint=/invoices`);
      if (res.ok) {
        const data = await res.json();
        setInvoices(data.invoices || []);
      }
    } catch (e) {}
  };

  const fetchPendingReviews = async () => {
    try {
      const res = await fetch(`${PROXY}?endpoint=/reviews/pending`);
      if (res.ok) {
        const data = await res.json();
        setPendingReviews(data.pending_reviews || []);
      }
    } catch (e) {}
  };

  const fetchAuditTrail = async (invoiceId: string) => {
    try {
      const res = await fetch(`${PROXY}?endpoint=/governance/audit-trail/${invoiceId}`);
      if (res.ok) {
        setInvoiceAudit(await res.json());
        setSelectedInvoice(invoiceId);
      }
    } catch (e) {}
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadStatus("");
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/upload", { method: "POST", body: formData });
      if (res.ok) {
        const data = await res.json();
        setUploadStatus(`"${file.name}" processed successfully. Invoice ID: ${data.invoice_id || "assigned"}`);
        fetchAll();
      } else {
        const err = await res.json();
        setUploadStatus(`Processing failed: ${err.detail || "Unknown error"}`);
      }
    } catch (e) {
      setUploadStatus("Upload failed. Server unreachable.");
    } finally {
      setUploading(false);
    }
  };

  const submitReview = async (invoiceId: string) => {
    try {
      const params = new URLSearchParams({
        reviewer_id: reviewForm.reviewer_id,
        reviewer_name: reviewForm.reviewer_name,
        decision: reviewForm.decision,
        rationale_category: reviewForm.rationale_category,
        rationale_text: reviewForm.rationale_text,
      });

      const res = await fetch(PROXY, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          endpoint: `/reviews/${invoiceId}/decide?${params.toString()}`,
        }),
      });

      if (res.ok) {
        setReviewResult(await res.json());
        fetchAll();
      }
    } catch (e) {}
  };

  const statusColor = (s: string) => {
    switch (s) {
      case "approved": return "bg-emerald-100 text-emerald-700";
      case "rejected": return "bg-red-100 text-red-700";
      case "flagged": case "on_hold": return "bg-amber-100 text-amber-700";
      case "pending": return "bg-blue-100 text-blue-700";
      default: return "bg-gray-100 text-gray-600";
    }
  };

  const tabs: { id: Tab; label: string; icon: React.ReactNode; badge?: number }[] = [
    { id: "dashboard", label: "Dashboard", icon: <BarChart3 className="w-4 h-4" /> },
    { id: "upload", label: "Upload", icon: <Upload className="w-4 h-4" /> },
    { id: "invoices", label: "Invoices", icon: <FileText className="w-4 h-4" /> },
    { id: "reviews", label: "Reviews", icon: <Users className="w-4 h-4" />, badge: pendingReviews.length },
    { id: "governance", label: "Governance", icon: <Shield className="w-4 h-4" /> },
  ];

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-[#0f172a] text-white border-b border-slate-700/50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-indigo-400 to-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                <FileSearch className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-lg font-bold tracking-tight">
                  Invoice<span className="text-indigo-400">Intelligence</span>
                </h1>
                <p className="text-[10px] text-slate-400 tracking-wide uppercase">
                  AI-Powered Processing
                </p>
              </div>
            </div>

            <nav className="flex bg-slate-800/50 rounded-lg p-0.5">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all relative ${
                    activeTab === tab.id
                      ? "bg-indigo-500/20 text-indigo-400 shadow-sm"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {tab.icon}
                  <span className="hidden sm:inline">{tab.label}</span>
                  {tab.badge ? (
                    <span className="absolute -top-1 -right-1 w-4 h-4 bg-amber-500 text-white text-[9px] font-bold rounded-full flex items-center justify-center">
                      {tab.badge}
                    </span>
                  ) : null}
                </button>
              ))}
            </nav>

            <div className="flex items-center gap-2">
              {health && (
                <div className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800/50 rounded-lg">
                  <div className={`w-1.5 h-1.5 rounded-full ${health.status === "healthy" ? "bg-emerald-400 animate-pulse" : "bg-red-400"}`} />
                  <span className="text-[11px] text-slate-400">
                    {health.vendor_count} vendors
                  </span>
                </div>
              )}
              <button onClick={fetchAll} className="p-2 text-slate-400 hover:text-indigo-400 transition">
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 py-6">

        {/* Dashboard */}
        {activeTab === "dashboard" && (
          <div className="animate-fade-in">
            <h2 className="text-xl font-bold text-gray-900 mb-6">Governance Dashboard</h2>

            {govDashboard ? (
              <>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
                  <StatCard label="Total Processed" value={govDashboard.total_processed} icon={<FileText className="w-5 h-5" />} color="indigo" />
                  <StatCard label="Auto-Approved" value={govDashboard.auto_approved} icon={<CheckCircle2 className="w-5 h-5" />} color="emerald" />
                  <StatCard label="Pending Review" value={govDashboard.pending_review} icon={<Clock className="w-5 h-5" />} color="amber" />
                  <StatCard label="Blocked" value={govDashboard.blocked} icon={<XCircle className="w-5 h-5" />} color="red" />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 mb-8">
                  {/* Escalation Breakdown */}
                  <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
                    <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Escalation Levels</h3>
                    <div className="space-y-3">
                      <EscalationBar label="L1 - Manager" count={govDashboard.escalated_l1} total={govDashboard.total_processed || 1} color="bg-amber-400" />
                      <EscalationBar label="L2 - Controller" count={govDashboard.escalated_l2} total={govDashboard.total_processed || 1} color="bg-orange-400" />
                      <EscalationBar label="L3 - VP/CFO" count={govDashboard.escalated_l3} total={govDashboard.total_processed || 1} color="bg-red-400" />
                    </div>
                  </div>

                  {/* Flags */}
                  <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
                    <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Governance Flags</h3>
                    <div className="space-y-3">
                      <FlagRow label="Duplicate Invoices" count={govDashboard.duplicate_flags} icon={<AlertTriangle className="w-4 h-4 text-amber-500" />} />
                      <FlagRow label="Unknown Vendors" count={govDashboard.unknown_vendor_flags} icon={<AlertTriangle className="w-4 h-4 text-red-500" />} />
                      <FlagRow label="Amount Variances" count={govDashboard.amount_variance_flags} icon={<AlertTriangle className="w-4 h-4 text-orange-500" />} />
                    </div>
                    <div className="mt-4 pt-4 border-t border-gray-100">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-gray-500">Avg Agent Confidence</span>
                        <span className={`text-sm font-bold ${govDashboard.avg_confidence > 0.8 ? "text-emerald-600" : govDashboard.avg_confidence > 0.6 ? "text-amber-600" : "text-red-600"}`}>
                          {(govDashboard.avg_confidence * 100).toFixed(1)}%
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div className="text-center py-20 text-gray-400">
                {loading ? <Loader2 className="w-6 h-6 animate-spin mx-auto" /> : "No governance data available. Upload an invoice to get started."}
              </div>
            )}
          </div>
        )}

        {/* Upload */}
        {activeTab === "upload" && (
          <div className="animate-fade-in max-w-2xl mx-auto py-10">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-400 to-indigo-600 flex items-center justify-center">
                <Upload className="w-5 h-5 text-white" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-900">Upload Invoice</h2>
                <p className="text-xs text-gray-500">Five AI agents will process, validate, and reconcile your invoice</p>
              </div>
            </div>

            <label className="block border-2 border-dashed border-gray-300 rounded-2xl p-16 text-center hover:border-indigo-400 hover:bg-indigo-50/30 transition-all cursor-pointer group">
              {uploading ? (
                <div>
                  <Loader2 className="w-10 h-10 text-indigo-500 animate-spin mx-auto mb-3" />
                  <p className="text-sm font-medium text-gray-700">Processing invoice with 5 AI agents...</p>
                  <p className="text-xs text-gray-400 mt-1">This may take 30-60 seconds</p>
                </div>
              ) : (
                <div>
                  <div className="w-14 h-14 rounded-2xl bg-gray-100 group-hover:bg-indigo-100 flex items-center justify-center mx-auto mb-4 transition">
                    <Upload className="w-7 h-7 text-gray-400 group-hover:text-indigo-500 transition" />
                  </div>
                  <p className="text-sm font-medium text-gray-700 mb-1">Drop an invoice here or click to browse</p>
                  <p className="text-xs text-gray-400">Supports PDF invoices</p>
                </div>
              )}
              <input type="file" accept=".pdf,application/pdf" onChange={handleUpload} className="hidden" disabled={uploading} />
            </label>

            {uploadStatus && (
              <div className={`mt-4 p-4 rounded-xl text-sm flex items-center gap-2 ${uploadStatus.includes("failed") ? "bg-red-50 border border-red-200 text-red-700" : "bg-emerald-50 border border-emerald-200 text-emerald-700"}`}>
                <div className={`w-2 h-2 rounded-full ${uploadStatus.includes("failed") ? "bg-red-500" : "bg-emerald-500"}`} />
                {uploadStatus}
              </div>
            )}

            {/* Pipeline Visualization */}
            <div className="mt-10 bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Processing Pipeline</h3>
              <div className="flex items-center justify-between">
                {["Intake", "Extract", "Validate", "Anomaly", "Reconcile"].map((stage, i) => (
                  <div key={stage} className="flex items-center">
                    <div className="text-center">
                      <div className="w-10 h-10 rounded-full bg-indigo-50 border-2 border-indigo-200 flex items-center justify-center text-xs font-bold text-indigo-600 mx-auto">
                        {i + 1}
                      </div>
                      <p className="text-[10px] text-gray-500 mt-1 font-medium">{stage}</p>
                    </div>
                    {i < 4 && <ChevronRight className="w-4 h-4 text-gray-300 mx-1" />}
                  </div>
                ))}
              </div>
              <div className="mt-4 pt-4 border-t border-gray-100 flex items-center justify-center gap-2">
                <Scale className="w-4 h-4 text-indigo-400" />
                <span className="text-xs text-gray-500">Governance engine evaluates at every stage</span>
              </div>
            </div>
          </div>
        )}

        {/* Invoices */}
        {activeTab === "invoices" && (
          <div className="animate-fade-in">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-gray-900">Processed Invoices</h2>
              <span className="text-xs text-gray-400">{invoices.length} invoices</span>
            </div>

            {invoices.length > 0 ? (
              <div className="bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
                <div className="divide-y divide-gray-100">
                  {invoices.map((inv) => (
                    <div key={inv.invoice_id} className="px-6 py-4 hover:bg-gray-50/50 transition flex items-center justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-3 mb-1">
                          <span className="text-sm font-semibold text-gray-800">{inv.vendor_name || "Unknown Vendor"}</span>
                          <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${statusColor(inv.status)}`}>{inv.status}</span>
                        </div>
                        <div className="flex items-center gap-3 text-[11px] text-gray-400">
                          <span>{inv.invoice_number || inv.invoice_id.slice(0, 8)}</span>
                          <span className="w-1 h-1 rounded-full bg-gray-300" />
                          <span>{inv.currency} {inv.total?.toLocaleString() || "N/A"}</span>
                          <span className="w-1 h-1 rounded-full bg-gray-300" />
                          <span>Confidence: {(inv.extraction_confidence * 100).toFixed(0)}%</span>
                          <span className="w-1 h-1 rounded-full bg-gray-300" />
                          <span>{inv.source_filename}</span>
                        </div>
                      </div>
                      <button
                        onClick={() => fetchAuditTrail(inv.invoice_id)}
                        className="px-3 py-1.5 text-xs text-indigo-500 hover:bg-indigo-50 rounded-lg transition flex items-center gap-1"
                      >
                        <Eye className="w-3 h-3" /> Audit Trail
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-center py-20 text-gray-400 text-sm">
                No invoices processed yet. Upload an invoice to get started.
              </div>
            )}

            {/* Audit Trail Modal */}
            {selectedInvoice && invoiceAudit && (
              <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
                <div className="bg-white rounded-2xl p-6 max-w-2xl w-full mx-4 shadow-2xl max-h-[80vh] overflow-y-auto">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-bold text-gray-900">
                      Audit Trail: {selectedInvoice.slice(0, 12)}...
                    </h3>
                    <button onClick={() => setSelectedInvoice(null)} className="p-1 hover:bg-gray-100 rounded-lg">
                      <XCircle className="w-4 h-4 text-gray-400" />
                    </button>
                  </div>
                  <div className="space-y-3">
                    {invoiceAudit.audit_entries?.map((entry: any, i: number) => (
                      <div key={i} className="bg-gray-50 rounded-xl p-3 text-xs">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-semibold text-gray-700">{entry.event_type}</span>
                          <span className="text-gray-400">{entry.timestamp}</span>
                        </div>
                        <p className="text-gray-600">{entry.description}</p>
                        <span className="text-gray-400">Actor: {entry.actor}</span>
                      </div>
                    ))}
                    {invoiceAudit.human_decisions?.map((hd: any, i: number) => (
                      <div key={`hd-${i}`} className="bg-indigo-50 rounded-xl p-3 text-xs border border-indigo-200">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-semibold text-indigo-700">Human Review</span>
                          <span className="text-indigo-400">{hd.timestamp}</span>
                        </div>
                        <p className="text-indigo-600">Decision: {hd.decision} | {hd.rationale_category}</p>
                        <p className="text-indigo-500">Reviewer: {hd.reviewer_name} | Consistency: {hd.consistency_score >= 0 ? `${(hd.consistency_score * 100).toFixed(0)}%` : "N/A"}</p>
                      </div>
                    ))}
                  </div>
                  {invoiceAudit.audit_entries?.length === 0 && invoiceAudit.human_decisions?.length === 0 && (
                    <p className="text-center text-gray-400 text-sm py-8">No audit entries yet.</p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Reviews */}
        {activeTab === "reviews" && (
          <div className="animate-fade-in">
            <div className="flex items-center gap-3 mb-6">
              <h2 className="text-xl font-bold text-gray-900">Human Review Queue</h2>
              {pendingReviews.length > 0 && (
                <span className="px-2 py-0.5 bg-amber-100 text-amber-700 text-xs font-bold rounded-full">
                  {pendingReviews.length} pending
                </span>
              )}
            </div>

            {pendingReviews.length > 0 ? (
              <div className="space-y-4">
                {pendingReviews.map((pr: any) => (
                  <div key={pr.invoice_id} className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <span className="text-sm font-semibold text-gray-800">{pr.vendor_name || "Unknown"}</span>
                        <span className="ml-2 px-2 py-0.5 bg-amber-100 text-amber-700 text-[10px] font-bold rounded-full">{pr.escalation_level}</span>
                      </div>
                      <span className="text-xs text-gray-400">{pr.currency} {pr.total?.toLocaleString()}</span>
                    </div>
                    <p className="text-xs text-gray-500 mb-4">
                      <span className="font-medium">Flag:</span> {pr.rule_triggered} | <span className="font-medium">Reason:</span> {pr.escalation_reason}
                    </p>

                    {/* Review Form */}
                    <div className="bg-gray-50 rounded-xl p-4 space-y-3">
                      <div className="grid grid-cols-2 gap-3">
                        <input
                          type="text"
                          placeholder="Reviewer ID"
                          value={reviewForm.reviewer_id}
                          onChange={(e) => setReviewForm({ ...reviewForm, reviewer_id: e.target.value })}
                          className="px-3 py-2 bg-white border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        />
                        <input
                          type="text"
                          placeholder="Reviewer Name"
                          value={reviewForm.reviewer_name}
                          onChange={(e) => setReviewForm({ ...reviewForm, reviewer_name: e.target.value })}
                          className="px-3 py-2 bg-white border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        />
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <select
                          value={reviewForm.decision}
                          onChange={(e) => setReviewForm({ ...reviewForm, decision: e.target.value })}
                          className="px-3 py-2 bg-white border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        >
                          <option value="approve">Approve</option>
                          <option value="adjust_and_approve">Adjust and Approve</option>
                          <option value="reject">Reject</option>
                          <option value="escalate_further">Escalate Further</option>
                        </select>
                        <select
                          value={reviewForm.rationale_category}
                          onChange={(e) => setReviewForm({ ...reviewForm, rationale_category: e.target.value })}
                          className="px-3 py-2 bg-white border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        >
                          <option value="amount_within_variance">Amount Within Variance</option>
                          <option value="vendor_confirmed_correction">Vendor Confirmed Correction</option>
                          <option value="po_mismatch_resolved">PO Mismatch Resolved</option>
                          <option value="duplicate_confirmed_void">Duplicate Confirmed, Void</option>
                          <option value="anomaly_is_legitimate">Anomaly Is Legitimate</option>
                          <option value="requires_senior_review">Requires Senior Review</option>
                          <option value="policy_exception_granted">Policy Exception Granted</option>
                          <option value="other">Other</option>
                        </select>
                      </div>
                      <input
                        type="text"
                        placeholder="One-line rationale (required)"
                        value={reviewForm.rationale_text}
                        onChange={(e) => setReviewForm({ ...reviewForm, rationale_text: e.target.value })}
                        className="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      />
                      <button
                        onClick={() => submitReview(pr.invoice_id)}
                        disabled={!reviewForm.reviewer_id || !reviewForm.reviewer_name}
                        className="w-full py-2.5 bg-gradient-to-r from-indigo-500 to-indigo-600 text-white rounded-lg text-xs font-semibold hover:shadow-lg transition disabled:opacity-40"
                      >
                        Submit Decision
                      </button>
                    </div>

                    {reviewResult && reviewResult.invoice_id === pr.invoice_id && (
                      <div className="mt-3 p-3 bg-emerald-50 border border-emerald-200 rounded-xl text-xs text-emerald-700">
                        Decision recorded. Consistency: {reviewResult.consistency_note}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-20">
                <CheckCircle2 className="w-12 h-12 text-emerald-300 mx-auto mb-3" />
                <p className="text-sm text-gray-500">No invoices pending review. All clear.</p>
              </div>
            )}
          </div>
        )}

        {/* Governance */}
        {activeTab === "governance" && (
          <div className="animate-fade-in">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-400 to-indigo-600 flex items-center justify-center">
                <Shield className="w-5 h-5 text-white" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-900">Governance Engine</h2>
                <p className="text-xs text-gray-500">Agent and human decisions under one audit framework</p>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
              <div className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm text-center">
                <Shield className="w-8 h-8 text-indigo-400 mx-auto mb-2" />
                <p className="text-2xl font-bold text-gray-900">{govDashboard?.total_processed || 0}</p>
                <p className="text-xs text-gray-500 mt-1">Total Governed Decisions</p>
              </div>
              <div className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm text-center">
                <Users className="w-8 h-8 text-indigo-400 mx-auto mb-2" />
                <p className="text-2xl font-bold text-gray-900">{pendingReviews.length}</p>
                <p className="text-xs text-gray-500 mt-1">Awaiting Human Review</p>
              </div>
              <div className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm text-center">
                <Scale className="w-8 h-8 text-indigo-400 mx-auto mb-2" />
                <p className="text-2xl font-bold text-gray-900">{govDashboard?.avg_confidence ? `${(govDashboard.avg_confidence * 100).toFixed(0)}%` : "N/A"}</p>
                <p className="text-xs text-gray-500 mt-1">Avg Agent Confidence</p>
              </div>
            </div>

            <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">How It Works</h3>
              <div className="space-y-3 text-sm text-gray-600">
                <p><span className="font-semibold text-gray-800">1. Agent Decisions:</span> Each of the 5 agents logs confidence scores, processing time, and outputs. The governance engine evaluates every decision inline.</p>
                <p><span className="font-semibold text-gray-800">2. Automated Rules:</span> Duplicate detection, unknown vendor checks, amount variance thresholds, OCR confidence gates. Violations trigger escalation.</p>
                <p><span className="font-semibold text-gray-800">3. Human Review:</span> Escalated invoices enter the review queue. Reviewers use structured decision templates with mandatory rationale.</p>
                <p><span className="font-semibold text-gray-800">4. Consistency Scoring:</span> Every human decision is scored against historical patterns. Reviewer drift is flagged automatically.</p>
                <p><span className="font-semibold text-gray-800">5. Unified Audit Trail:</span> Agent decisions and human decisions are recorded in the same immutable log. Both sides of the loop are accountable.</p>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-200/80 py-4">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex items-center justify-between">
          <p className="text-[11px] text-gray-400">
            Powered by{" "}
            <a href="https://veristack.ca" className="text-indigo-500 hover:text-indigo-600 font-medium transition" target="_blank" rel="noopener noreferrer">
              VeriStack
            </a>
          </p>
          <p className="text-[11px] text-gray-400">Invoice Intelligence v1.0 | Governance-First AI Processing</p>
        </div>
      </footer>
    </div>
  );
}

// Helper Components

function StatCard({ label, value, icon, color }: { label: string; value: number; icon: React.ReactNode; color: string }) {
  const colors: Record<string, string> = {
    indigo: "from-indigo-50 to-indigo-100/50 border-indigo-100 text-indigo-600",
    emerald: "from-emerald-50 to-emerald-100/50 border-emerald-100 text-emerald-600",
    amber: "from-amber-50 to-amber-100/50 border-amber-100 text-amber-600",
    red: "from-red-50 to-red-100/50 border-red-100 text-red-600",
  };
  return (
    <div className={`bg-gradient-to-br ${colors[color]} border rounded-2xl p-5 shadow-sm`}>
      <div className="flex items-center justify-between mb-2">
        <span className="opacity-60">{icon}</span>
      </div>
      <p className="text-3xl font-bold">{value}</p>
      <p className="text-xs opacity-70 mt-1 font-medium">{label}</p>
    </div>
  );
}

function EscalationBar({ label, count, total, color }: { label: string; count: number; total: number; color: string }) {
  const pct = Math.round((count / total) * 100);
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-gray-600">{label}</span>
        <span className="text-xs font-bold text-gray-700">{count}</span>
      </div>
      <div className="w-full bg-gray-100 rounded-full h-2">
        <div className={`${color} rounded-full h-2 transition-all`} style={{ width: `${Math.max(pct, 2)}%` }} />
      </div>
    </div>
  );
}

function FlagRow({ label, count, icon }: { label: string; count: number; icon: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-xs text-gray-600">{label}</span>
      </div>
      <span className="text-sm font-bold text-gray-700">{count}</span>
    </div>
  );
}
