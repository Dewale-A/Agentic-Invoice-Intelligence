"use client";

import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { Toaster, toast } from "sonner";
import {
  Upload, FileText, Shield, BarChart3, AlertTriangle, CheckCircle2,
  Clock, Users, Eye, ChevronRight, XCircle, Loader2, RefreshCw,
  FileSearch, Scale, ArrowRight, Sparkles, X,
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

type Tab = "dashboard" | "upload" | "invoices" | "reviews" | "governance";

// Animated counter component
function AnimatedCounter({ value, duration = 1.5 }: { value: number; duration?: number }) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    let start = 0;
    const end = value;
    if (start === end) return;
    const increment = end / (duration * 60);
    const timer = setInterval(() => {
      start += increment;
      if (start >= end) {
        setCount(end);
        clearInterval(timer);
      } else {
        setCount(Math.floor(start));
      }
    }, 1000 / 60);
    return () => clearInterval(timer);
  }, [value, duration]);
  return <>{count}</>;
}

// Timeline event component
function TimelineEvent({ entry, index, isLast }: { entry: any; index: number; isLast: boolean }) {
  const eventColors: Record<string, string> = {
    "invoice.received": "bg-blue-500",
    "agent.document_intake": "bg-indigo-500",
    "agent.data_extraction": "bg-indigo-500",
    "agent.validation": "bg-indigo-500",
    "agent.anomaly_detection": "bg-indigo-500",
    "governance.agent_confidence_gate": "bg-amber-500",
    "governance.unknown_vendor": "bg-red-500",
    "governance.materiality_gate": "bg-orange-500",
    "governance.duplicate_detection": "bg-red-500",
    "invoice.status_change": "bg-slate-500",
    "human_review": "bg-emerald-500",
  };
  const dotColor = eventColors[entry.event_type] || "bg-gray-400";

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.08 }}
      className="flex gap-3"
    >
      <div className="flex flex-col items-center">
        <div className={`w-3 h-3 rounded-full ${dotColor} ring-4 ring-white shadow-sm`} />
        {!isLast && <div className="w-0.5 flex-1 bg-gray-200 mt-1" />}
      </div>
      <div className="pb-5 flex-1">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-gray-700">{entry.event_type.replace(/\./g, " > ")}</span>
          <span className="text-[10px] text-gray-400">{new Date(entry.timestamp).toLocaleTimeString()}</span>
        </div>
        <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">{entry.description}</p>
        <span className="text-[10px] text-gray-400">Actor: {entry.actor}</span>
      </div>
    </motion.div>
  );
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>("dashboard");
  const [govDashboard, setGovDashboard] = useState<GovDashboard | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [pendingReviews, setPendingReviews] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadStep, setUploadStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selectedInvoice, setSelectedInvoice] = useState<string | null>(null);
  const [invoiceAudit, setInvoiceAudit] = useState<any>(null);
  const [healthOk, setHealthOk] = useState(false);
  const [vendorCount, setVendorCount] = useState(0);

  const [reviewForm, setReviewForm] = useState({
    reviewer_id: "", reviewer_name: "", decision: "approve",
    rationale_category: "amount_within_variance", rationale_text: "",
  });

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    await Promise.all([fetchHealth(), fetchDashboard(), fetchInvoices(), fetchPendingReviews()]);
    setLoading(false);
  };

  const fetchHealth = async () => {
    try {
      const res = await fetch(`${PROXY}?endpoint=/health`);
      if (res.ok) { const d = await res.json(); setHealthOk(d.status === "healthy"); setVendorCount(d.vendor_count || 0); }
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
      if (res.ok) { const d = await res.json(); setInvoices(d.invoices || []); }
    } catch (e) {}
  };

  const fetchPendingReviews = async () => {
    try {
      const res = await fetch(`${PROXY}?endpoint=/reviews/pending`);
      if (res.ok) { const d = await res.json(); setPendingReviews(d.pending_reviews || []); }
    } catch (e) {}
  };

  const fetchAuditTrail = async (invoiceId: string) => {
    try {
      const res = await fetch(`${PROXY}?endpoint=/invoices/${invoiceId}/audit`);
      if (res.ok) { setInvoiceAudit(await res.json()); setSelectedInvoice(invoiceId); }
    } catch (e) {}
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadStep(1);

    const steps = [1, 2, 3, 4, 5];
    const stepTimer = setInterval(() => {
      setUploadStep((prev) => (prev < 5 ? prev + 1 : prev));
    }, 3000);

    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch("/api/upload", { method: "POST", body: formData });
      clearInterval(stepTimer);
      if (res.ok) {
        setUploadStep(6);
        toast.success(`"${file.name}" processed successfully`, { description: "5 agents completed processing" });
        fetchAll();
      } else {
        toast.error("Processing failed", { description: "Check the server logs" });
      }
    } catch (e) {
      clearInterval(stepTimer);
      toast.error("Upload failed", { description: "Server unreachable" });
    } finally {
      setTimeout(() => { setUploading(false); setUploadStep(0); }, 2000);
    }
  };

  const submitReview = async (invoiceId: string) => {
    const params = new URLSearchParams({
      reviewer_id: reviewForm.reviewer_id, reviewer_name: reviewForm.reviewer_name,
      decision: reviewForm.decision, rationale_category: reviewForm.rationale_category,
      rationale_text: reviewForm.rationale_text,
    });
    try {
      const res = await fetch(PROXY, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint: `/reviews/${invoiceId}/decide?${params.toString()}` }),
      });
      if (res.ok) {
        const result = await res.json();
        toast.success("Decision recorded", { description: result.consistency_note });
        fetchAll();
      }
    } catch (e) { toast.error("Failed to submit review"); }
  };

  const statusColor = (s: string) => {
    const map: Record<string, string> = {
      approved: "bg-emerald-100 text-emerald-700", rejected: "bg-red-100 text-red-700",
      flagged: "bg-amber-100 text-amber-700", on_hold: "bg-amber-100 text-amber-700",
      pending: "bg-blue-100 text-blue-700", processing: "bg-indigo-100 text-indigo-700",
    };
    return map[s] || "bg-gray-100 text-gray-600";
  };

  const pipelineStages = ["Intake", "Extract", "Validate", "Anomaly", "Reconcile"];

  const tabs: { id: Tab; label: string; icon: React.ReactNode; badge?: number }[] = [
    { id: "dashboard", label: "Dashboard", icon: <BarChart3 className="w-4 h-4" /> },
    { id: "upload", label: "Upload", icon: <Upload className="w-4 h-4" /> },
    { id: "invoices", label: "Invoices", icon: <FileText className="w-4 h-4" /> },
    { id: "reviews", label: "Reviews", icon: <Users className="w-4 h-4" />, badge: pendingReviews.length || undefined },
    { id: "governance", label: "Governance", icon: <Shield className="w-4 h-4" /> },
  ];

  // Chart data
  const pieData = govDashboard ? [
    { name: "Auto-Approved", value: govDashboard.auto_approved, color: "#059669" },
    { name: "Pending", value: govDashboard.pending_review, color: "#d97706" },
    { name: "Blocked", value: govDashboard.blocked, color: "#dc2626" },
  ].filter(d => d.value > 0) : [];

  const escalationData = govDashboard ? [
    { name: "L1 Manager", count: govDashboard.escalated_l1 },
    { name: "L2 Controller", count: govDashboard.escalated_l2 },
    { name: "L3 VP/CFO", count: govDashboard.escalated_l3 },
  ] : [];

  return (
    <div className="min-h-screen flex flex-col bg-[#f8fafc]">
      <Toaster position="top-right" richColors closeButton />

      {/* Header */}
      <header className="bg-[#0f172a] text-white border-b border-slate-700/50 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-3">
              <motion.div
                whileHover={{ scale: 1.05 }}
                className="w-9 h-9 rounded-lg bg-gradient-to-br from-indigo-400 to-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/20"
              >
                <FileSearch className="w-5 h-5 text-white" />
              </motion.div>
              <div>
                <h1 className="text-lg font-bold tracking-tight">
                  Invoice<span className="text-indigo-400">Intelligence</span>
                </h1>
                <p className="text-[10px] text-slate-400 tracking-wide uppercase">AI-Powered Processing</p>
              </div>
            </div>

            <nav className="flex bg-slate-800/50 rounded-lg p-0.5">
              {tabs.map((tab) => (
                <motion.button
                  key={tab.id}
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all relative ${
                    activeTab === tab.id ? "bg-indigo-500/20 text-indigo-400 shadow-sm" : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {tab.icon}
                  <span className="hidden sm:inline">{tab.label}</span>
                  {tab.badge ? (
                    <motion.span
                      initial={{ scale: 0 }} animate={{ scale: 1 }}
                      className="absolute -top-1 -right-1 w-4 h-4 bg-amber-500 text-white text-[9px] font-bold rounded-full flex items-center justify-center"
                    >
                      {tab.badge}
                    </motion.span>
                  ) : null}
                </motion.button>
              ))}
            </nav>

            <div className="flex items-center gap-2">
              {healthOk && (
                <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 bg-slate-800/50 rounded-lg">
                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="text-[11px] text-slate-400">{vendorCount} vendors</span>
                </div>
              )}
              <motion.button whileHover={{ rotate: 180 }} transition={{ duration: 0.3 }} onClick={fetchAll} className="p-2 text-slate-400 hover:text-indigo-400 transition">
                <RefreshCw className="w-4 h-4" />
              </motion.button>
            </div>
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 py-6">
        <AnimatePresence mode="wait">
          <motion.div key={activeTab} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} transition={{ duration: 0.2 }}>

        {/* ============ DASHBOARD ============ */}
        {activeTab === "dashboard" && (
          <div>
            <h2 className="text-xl font-bold text-gray-900 mb-6">Governance Dashboard</h2>
            {govDashboard ? (
              <>
                {/* Stat Cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
                  {[
                    { label: "Total Processed", value: govDashboard.total_processed, icon: <FileText className="w-5 h-5" />, color: "indigo" },
                    { label: "Auto-Approved", value: govDashboard.auto_approved, icon: <CheckCircle2 className="w-5 h-5" />, color: "emerald" },
                    { label: "Pending Review", value: govDashboard.pending_review, icon: <Clock className="w-5 h-5" />, color: "amber" },
                    { label: "Blocked", value: govDashboard.blocked, icon: <XCircle className="w-5 h-5" />, color: "red" },
                  ].map((stat, i) => {
                    const colors: Record<string, string> = {
                      indigo: "from-indigo-50 to-indigo-100/50 border-indigo-100 text-indigo-600",
                      emerald: "from-emerald-50 to-emerald-100/50 border-emerald-100 text-emerald-600",
                      amber: "from-amber-50 to-amber-100/50 border-amber-100 text-amber-600",
                      red: "from-red-50 to-red-100/50 border-red-100 text-red-600",
                    };
                    return (
                      <motion.div key={i} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.1 }}
                        whileHover={{ y: -2, boxShadow: "0 8px 25px rgba(0,0,0,0.08)" }}
                        className={`bg-gradient-to-br ${colors[stat.color]} border rounded-2xl p-5`}
                      >
                        <div className="flex items-center justify-between mb-2"><span className="opacity-60">{stat.icon}</span></div>
                        <p className="text-3xl font-bold"><AnimatedCounter value={stat.value} /></p>
                        <p className="text-xs opacity-70 mt-1 font-medium">{stat.label}</p>
                      </motion.div>
                    );
                  })}
                </div>

                {/* Charts Row */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 mb-8">
                  {/* Pie Chart */}
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }}
                    className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
                    <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Status Distribution</h3>
                    {pieData.length > 0 ? (
                      <div className="flex items-center justify-center">
                        <ResponsiveContainer width={200} height={200}>
                          <PieChart>
                            <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={5} dataKey="value">
                              {pieData.map((entry, i) => (<Cell key={i} fill={entry.color} />))}
                            </Pie>
                            <Tooltip />
                          </PieChart>
                        </ResponsiveContainer>
                        <div className="ml-4 space-y-2">
                          {pieData.map((d, i) => (
                            <div key={i} className="flex items-center gap-2 text-xs">
                              <div className="w-3 h-3 rounded-full" style={{ backgroundColor: d.color }} />
                              <span className="text-gray-600">{d.name}: {d.value}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <p className="text-center text-gray-400 text-sm py-8">Upload invoices to see distribution</p>
                    )}
                  </motion.div>

                  {/* Bar Chart */}
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.4 }}
                    className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
                    <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Escalation Levels</h3>
                    {escalationData.some(d => d.count > 0) ? (
                      <ResponsiveContainer width="100%" height={200}>
                        <BarChart data={escalationData}>
                          <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                          <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                          <Tooltip />
                          <Bar dataKey="count" fill="#6366f1" radius={[6, 6, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <p className="text-center text-gray-400 text-sm py-8">No escalations yet</p>
                    )}
                  </motion.div>
                </div>

                {/* Flags */}
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.5 }}
                  className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
                  <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Governance Flags</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
                    {[
                      { label: "Duplicate Invoices", count: govDashboard.duplicate_flags, icon: <AlertTriangle className="w-4 h-4 text-amber-500" /> },
                      { label: "Unknown Vendors", count: govDashboard.unknown_vendor_flags, icon: <AlertTriangle className="w-4 h-4 text-red-500" /> },
                      { label: "Amount Variances", count: govDashboard.amount_variance_flags, icon: <AlertTriangle className="w-4 h-4 text-orange-500" /> },
                      { label: "Avg Confidence", count: null, icon: <Sparkles className="w-4 h-4 text-indigo-500" />,
                        custom: <span className={`text-lg font-bold ${govDashboard.avg_confidence > 0.8 ? "text-emerald-600" : govDashboard.avg_confidence > 0.6 ? "text-amber-600" : "text-red-600"}`}>{(govDashboard.avg_confidence * 100).toFixed(1)}%</span> },
                    ].map((flag, i) => (
                      <div key={i} className="flex items-center gap-3 p-3 bg-gray-50 rounded-xl">
                        {flag.icon}
                        <div>
                          {flag.custom || <p className="text-lg font-bold text-gray-800">{flag.count}</p>}
                          <p className="text-[10px] text-gray-500">{flag.label}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </motion.div>
              </>
            ) : (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-center py-20">
                {loading ? <Loader2 className="w-8 h-8 animate-spin mx-auto text-indigo-400" /> : (
                  <div>
                    <div className="w-20 h-20 rounded-2xl bg-indigo-50 flex items-center justify-center mx-auto mb-4">
                      <Upload className="w-10 h-10 text-indigo-300" />
                    </div>
                    <h3 className="text-lg font-bold text-gray-800 mb-2">No data yet</h3>
                    <p className="text-sm text-gray-500 mb-4">Upload your first invoice to see the governance dashboard in action</p>
                    <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
                      onClick={() => setActiveTab("upload")}
                      className="px-6 py-2.5 bg-gradient-to-r from-indigo-500 to-indigo-600 text-white rounded-xl text-sm font-semibold hover:shadow-lg hover:shadow-indigo-500/25 transition inline-flex items-center gap-2"
                    >
                      Upload Invoice <ArrowRight className="w-4 h-4" />
                    </motion.button>
                  </div>
                )}
              </motion.div>
            )}
          </div>
        )}

        {/* ============ UPLOAD ============ */}
        {activeTab === "upload" && (
          <div className="max-w-2xl mx-auto py-10">
            <div className="flex items-center gap-3 mb-8">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-400 to-indigo-600 flex items-center justify-center">
                <Upload className="w-5 h-5 text-white" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-900">Upload Invoice</h2>
                <p className="text-xs text-gray-500">Five AI agents will process, validate, and reconcile your invoice</p>
              </div>
            </div>

            <motion.label whileHover={{ borderColor: "#6366f1", backgroundColor: "rgba(99,102,241,0.03)" }}
              className="block border-2 border-dashed border-gray-300 rounded-2xl p-16 text-center transition-all cursor-pointer"
            >
              {uploading ? (
                <div>
                  <Loader2 className="w-10 h-10 text-indigo-500 animate-spin mx-auto mb-4" />
                  <p className="text-sm font-medium text-gray-700 mb-6">Processing with 5 AI agents...</p>

                  {/* Pipeline Progress */}
                  <div className="flex items-center justify-center gap-2">
                    {pipelineStages.map((stage, i) => (
                      <div key={stage} className="flex items-center">
                        <motion.div
                          animate={{ scale: uploadStep === i + 1 ? [1, 1.2, 1] : 1, backgroundColor: uploadStep > i ? "#4f46e5" : uploadStep === i + 1 ? "#6366f1" : "#e2e8f0" }}
                          transition={{ duration: 0.5, repeat: uploadStep === i + 1 ? Infinity : 0 }}
                          className="w-8 h-8 rounded-full flex items-center justify-center text-[10px] font-bold text-white"
                        >
                          {uploadStep > i + 1 ? <CheckCircle2 className="w-4 h-4" /> : i + 1}
                        </motion.div>
                        <p className="text-[9px] text-gray-500 ml-1 mr-2">{stage}</p>
                        {i < 4 && <ChevronRight className="w-3 h-3 text-gray-300" />}
                      </div>
                    ))}
                  </div>
                </div>
              ) : uploadStep === 6 ? (
                <motion.div initial={{ scale: 0.8 }} animate={{ scale: 1 }}>
                  <CheckCircle2 className="w-14 h-14 text-emerald-500 mx-auto mb-3" />
                  <p className="text-sm font-medium text-emerald-700">Invoice processed successfully!</p>
                </motion.div>
              ) : (
                <div>
                  <div className="w-14 h-14 rounded-2xl bg-gray-100 flex items-center justify-center mx-auto mb-4">
                    <Upload className="w-7 h-7 text-gray-400" />
                  </div>
                  <p className="text-sm font-medium text-gray-700 mb-1">Drop an invoice here or click to browse</p>
                  <p className="text-xs text-gray-400">Supports PDF invoices</p>
                </div>
              )}
              <input type="file" accept=".pdf,application/pdf,*/*" onChange={handleUpload} className="hidden" disabled={uploading} />
            </motion.label>

            {/* How it works */}
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}
              className="mt-10 bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">Processing Pipeline</h3>
              <div className="flex items-center justify-between mb-4">
                {pipelineStages.map((stage, i) => (
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
              <div className="pt-4 border-t border-gray-100 flex items-center justify-center gap-2">
                <Scale className="w-4 h-4 text-indigo-400" />
                <span className="text-xs text-gray-500">Governance engine evaluates at every stage</span>
              </div>
            </motion.div>
          </div>
        )}

        {/* ============ INVOICES ============ */}
        {activeTab === "invoices" && (
          <div>
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-gray-900">Processed Invoices</h2>
              <span className="text-xs text-gray-400">{invoices.length} invoices</span>
            </div>

            {invoices.length > 0 ? (
              <div className="bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
                {invoices.map((inv, i) => (
                  <motion.div key={inv.invoice_id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                    whileHover={{ backgroundColor: "rgba(248,250,252,1)" }}
                    className="px-6 py-4 border-b border-gray-100 last:border-0 flex items-center justify-between transition"
                  >
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
                        <span>Confidence: <span className={inv.extraction_confidence > 0.7 ? "text-emerald-500" : "text-amber-500"}>{(inv.extraction_confidence * 100).toFixed(0)}%</span></span>
                      </div>
                    </div>
                    <motion.button whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}
                      onClick={() => fetchAuditTrail(inv.invoice_id)}
                      className="px-3 py-1.5 text-xs text-indigo-500 hover:bg-indigo-50 rounded-lg transition flex items-center gap-1"
                    >
                      <Eye className="w-3 h-3" /> Audit Trail
                    </motion.button>
                  </motion.div>
                ))}
              </div>
            ) : (
              <div className="text-center py-20">
                <div className="w-20 h-20 rounded-2xl bg-gray-50 flex items-center justify-center mx-auto mb-4">
                  <FileText className="w-10 h-10 text-gray-300" />
                </div>
                <h3 className="text-lg font-bold text-gray-800 mb-2">No invoices yet</h3>
                <p className="text-sm text-gray-500 mb-4">Upload an invoice to see it processed by 5 AI agents</p>
                <motion.button whileHover={{ scale: 1.02 }} onClick={() => setActiveTab("upload")}
                  className="px-6 py-2.5 bg-gradient-to-r from-indigo-500 to-indigo-600 text-white rounded-xl text-sm font-semibold inline-flex items-center gap-2"
                >
                  Upload Invoice <ArrowRight className="w-4 h-4" />
                </motion.button>
              </div>
            )}

            {/* Audit Trail Modal */}
            <AnimatePresence>
              {selectedInvoice && invoiceAudit && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                  className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50" onClick={() => setSelectedInvoice(null)}
                >
                  <motion.div initial={{ scale: 0.9, y: 20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.9, y: 20 }}
                    className="bg-white rounded-2xl p-6 max-w-2xl w-full mx-4 shadow-2xl max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}
                  >
                    <div className="flex items-center justify-between mb-6">
                      <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center">
                          <Clock className="w-4 h-4 text-indigo-500" />
                        </div>
                        <div>
                          <h3 className="text-sm font-bold text-gray-900">Audit Timeline</h3>
                          <p className="text-[10px] text-gray-400">{invoiceAudit.total_entries} events</p>
                        </div>
                      </div>
                      <motion.button whileHover={{ scale: 1.1 }} onClick={() => setSelectedInvoice(null)} className="p-1.5 hover:bg-gray-100 rounded-lg">
                        <X className="w-4 h-4 text-gray-400" />
                      </motion.button>
                    </div>
                    <div>
                      {invoiceAudit.audit_trail?.map((entry: any, i: number) => (
                        <TimelineEvent key={i} entry={entry} index={i} isLast={i === invoiceAudit.audit_trail.length - 1} />
                      ))}
                      {invoiceAudit.audit_trail?.length === 0 && (
                        <p className="text-center text-gray-400 text-sm py-8">No audit entries yet.</p>
                      )}
                    </div>
                  </motion.div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}

        {/* ============ REVIEWS ============ */}
        {activeTab === "reviews" && (
          <div>
            <div className="flex items-center gap-3 mb-6">
              <h2 className="text-xl font-bold text-gray-900">Human Review Queue</h2>
              {pendingReviews.length > 0 && (
                <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }}
                  className="px-2.5 py-0.5 bg-amber-100 text-amber-700 text-xs font-bold rounded-full"
                >
                  {pendingReviews.length} pending
                </motion.span>
              )}
            </div>

            {pendingReviews.length > 0 ? (
              <div className="space-y-4">
                {pendingReviews.map((pr: any, i: number) => (
                  <motion.div key={pr.invoice_id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.1 }}
                    className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm"
                  >
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-gray-800">{pr.vendor_name || "Unknown"}</span>
                        <span className="px-2 py-0.5 bg-amber-100 text-amber-700 text-[10px] font-bold rounded-full">{pr.escalation_level}</span>
                      </div>
                      <span className="text-xs text-gray-400">{pr.currency} {pr.total?.toLocaleString()}</span>
                    </div>
                    <p className="text-xs text-gray-500 mb-4">
                      <span className="font-medium text-gray-700">Flag:</span> {pr.rule_triggered} | <span className="font-medium text-gray-700">Reason:</span> {pr.escalation_reason}
                    </p>
                    <div className="bg-gray-50 rounded-xl p-4 space-y-3">
                      <div className="grid grid-cols-2 gap-3">
                        <input type="text" placeholder="Reviewer ID" value={reviewForm.reviewer_id}
                          onChange={(e) => setReviewForm({ ...reviewForm, reviewer_id: e.target.value })}
                          className="px-3 py-2 bg-white border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500" />
                        <input type="text" placeholder="Reviewer Name" value={reviewForm.reviewer_name}
                          onChange={(e) => setReviewForm({ ...reviewForm, reviewer_name: e.target.value })}
                          className="px-3 py-2 bg-white border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500" />
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <select value={reviewForm.decision} onChange={(e) => setReviewForm({ ...reviewForm, decision: e.target.value })}
                          className="px-3 py-2 bg-white border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500">
                          <option value="approve">Approve</option>
                          <option value="adjust_and_approve">Adjust and Approve</option>
                          <option value="reject">Reject</option>
                          <option value="escalate_further">Escalate Further</option>
                        </select>
                        <select value={reviewForm.rationale_category} onChange={(e) => setReviewForm({ ...reviewForm, rationale_category: e.target.value })}
                          className="px-3 py-2 bg-white border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500">
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
                      <input type="text" placeholder="One-line rationale (required)" value={reviewForm.rationale_text}
                        onChange={(e) => setReviewForm({ ...reviewForm, rationale_text: e.target.value })}
                        className="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500" />
                      <motion.button whileHover={{ scale: 1.01 }} whileTap={{ scale: 0.99 }}
                        onClick={() => submitReview(pr.invoice_id)}
                        disabled={!reviewForm.reviewer_id || !reviewForm.reviewer_name}
                        className="w-full py-2.5 bg-gradient-to-r from-indigo-500 to-indigo-600 text-white rounded-lg text-xs font-semibold hover:shadow-lg transition disabled:opacity-40"
                      >
                        Submit Decision
                      </motion.button>
                    </div>
                  </motion.div>
                ))}
              </div>
            ) : (
              <div className="text-center py-20">
                <motion.div initial={{ scale: 0.8 }} animate={{ scale: 1 }}>
                  <CheckCircle2 className="w-16 h-16 text-emerald-300 mx-auto mb-4" />
                  <h3 className="text-lg font-bold text-gray-800 mb-2">All clear</h3>
                  <p className="text-sm text-gray-500">No invoices pending human review</p>
                </motion.div>
              </div>
            )}
          </div>
        )}

        {/* ============ GOVERNANCE ============ */}
        {activeTab === "governance" && (
          <div>
            <div className="flex items-center gap-3 mb-8">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-400 to-indigo-600 flex items-center justify-center">
                <Shield className="w-5 h-5 text-white" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-900">Governance Engine</h2>
                <p className="text-xs text-gray-500">Agent and human decisions under one audit framework</p>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
              {[
                { icon: <Shield className="w-8 h-8 text-indigo-400" />, value: govDashboard?.total_processed || 0, label: "Governed Decisions" },
                { icon: <Users className="w-8 h-8 text-indigo-400" />, value: pendingReviews.length, label: "Awaiting Human Review" },
                { icon: <Scale className="w-8 h-8 text-indigo-400" />, value: null, label: "Avg Confidence",
                  custom: <span className="text-2xl font-bold">{govDashboard?.avg_confidence ? `${(govDashboard.avg_confidence * 100).toFixed(0)}%` : "N/A"}</span> },
              ].map((card, i) => (
                <motion.div key={i} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.1 }}
                  whileHover={{ y: -2 }}
                  className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm text-center"
                >
                  <div className="mx-auto mb-2">{card.icon}</div>
                  {card.custom || <p className="text-2xl font-bold text-gray-900"><AnimatedCounter value={card.value!} /></p>}
                  <p className="text-xs text-gray-500 mt-1">{card.label}</p>
                </motion.div>
              ))}
            </div>

            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }}
              className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">How It Works</h3>
              <div className="space-y-4">
                {[
                  { num: "1", title: "Agent Decisions", desc: "Each of the 5 agents logs confidence scores, processing time, and outputs. The governance engine evaluates every decision inline." },
                  { num: "2", title: "Automated Rules", desc: "Duplicate detection, unknown vendor checks, amount variance thresholds, OCR confidence gates. Violations trigger escalation." },
                  { num: "3", title: "Human Review", desc: "Escalated invoices enter the review queue. Reviewers use structured decision templates with mandatory rationale." },
                  { num: "4", title: "Consistency Scoring", desc: "Every human decision is scored against historical patterns. Reviewer drift is flagged automatically." },
                  { num: "5", title: "Unified Audit Trail", desc: "Agent decisions and human decisions are recorded in the same immutable log. Both sides of the loop are accountable." },
                ].map((step, i) => (
                  <motion.div key={i} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.4 + i * 0.1 }}
                    className="flex items-start gap-4"
                  >
                    <div className="w-8 h-8 rounded-full bg-indigo-50 flex items-center justify-center text-xs font-bold text-indigo-600 shrink-0">{step.num}</div>
                    <div>
                      <p className="text-sm font-semibold text-gray-800">{step.title}</p>
                      <p className="text-xs text-gray-500 leading-relaxed">{step.desc}</p>
                    </div>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          </div>
        )}

          </motion.div>
        </AnimatePresence>
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-200/80 py-4">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex items-center justify-between">
          <p className="text-[11px] text-gray-400">
            Powered by <a href="https://veristack.ca" className="text-indigo-500 hover:text-indigo-600 font-medium transition" target="_blank">VeriStack</a>
          </p>
          <p className="text-[11px] text-gray-400">Invoice Intelligence v1.0 | Governance-First AI Processing</p>
        </div>
      </footer>
    </div>
  );
}
