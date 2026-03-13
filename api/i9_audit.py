"""
Preferred Maintenance – I9 Audit App
All routes are prefixed /i9/ so they can coexist with the Equipment Tracker.
Deploy: api/i9_audit.py  →  Vercel + Supabase
Local:  python api/i9_audit.py  (set FLASK_ENV=development)
"""

from flask import Flask, render_template_string, request, redirect, url_for, flash, Response, abort
from supabase import create_client
from datetime import datetime, date
import csv, io

# ── Supabase ──────────────────────────────────────────────────
SUPABASE_URL = "https://pfknmvfrsizsdvxknjmm.supabase.co"
SUPABASE_KEY = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
                ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBma25tdmZyc2l6c2R2eGtuam1tIiwic"
                "m9sZSI6ImFub24iLCJpYXQiOjE3NzI4MjM1NjgsImV4cCI6MjA4ODM5OTU2OH0"
                ".HFwO-IcBFdqkU6CITuDKg8jMCLbGsQN0VrU4pgiXJfs")
TABLE = "employees_i9"

app = Flask(__name__)
app.secret_key = "pm-i9-audit-2026"

_client = None

def db():
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ── Helpers ───────────────────────────────────────────────────

def parse_date(s):
    if not s:
        return None
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def fmt_date(d):
    d = parse_date(d)
    return d.strftime("%b %d, %Y") if d else "—"


# Status codes and their display info
_STATUS_META = {
    "ok":       ("OK",               "badge-ok",       ""),
    "missing":  ("Missing I-9",      "badge-missing",  "row-missing"),
    "expired":  ("Expired",          "badge-expired",  "row-expired"),
    "critical": ("Expiring \u226430d", "badge-critical", "row-critical"),
    "expiring": ("Expiring \u226490d", "badge-expiring", "row-expiring"),
}


def compute_status(emp):
    """
    Returns (code, days_until, doc_label):
      code: 'missing' | 'expired' | 'critical' | 'expiring' | 'ok'
      days_until: int or None
      doc_label: str or None
    """
    today = date.today()

    if not emp.get("i9_complete"):
        return "missing", None, None

    expiries = []
    doc_list = emp.get("doc_list") or ""

    if doc_list == "A":
        d = parse_date(emp.get("doc_a_expiry"))
        if d:
            expiries.append((d, emp.get("doc_a_type") or "List A Document"))
    elif doc_list == "BC":
        d = parse_date(emp.get("doc_b_expiry"))
        if d:
            expiries.append((d, emp.get("doc_b_type") or "List B Document"))
        d = parse_date(emp.get("doc_c_expiry"))
        if d:
            expiries.append((d, emp.get("doc_c_type") or "List C Document"))

    if emp.get("reverify_needed") and not emp.get("reverify_done"):
        d = parse_date(emp.get("reverify_by"))
        if d:
            expiries.append((d, "Re-verification"))

    if expiries:
        expiries.sort(key=lambda x: x[0])
        earliest_date, earliest_label = expiries[0]
        days = (earliest_date - today).days
        if days < 0:
            return "expired", days, earliest_label
        if days <= 30:
            return "critical", days, earliest_label
        if days <= 90:
            return "expiring", days, earliest_label

    return "ok", None, None


def enrich(emps):
    """Attach computed status fields to each employee dict."""
    for e in emps:
        code, days, doc = compute_status(e)
        meta = _STATUS_META[code]
        e["_status"]       = code
        e["_status_label"] = meta[0]
        e["_badge"]        = meta[1]
        e["_row_class"]    = meta[2]
        e["_doc"]          = doc or ""
        if days is None:
            e["_days_str"] = "—"
        elif days < 0:
            e["_days_str"] = f"{abs(days)}d overdue"
        elif days == 0:
            e["_days_str"] = "Today"
        else:
            e["_days_str"] = f"{days}d"
        # formatted dates
        e["_hire_fmt"] = fmt_date(e.get("hire_date"))
        e["_i9_fmt"]   = fmt_date(e.get("i9_date"))
    return emps


def get_employees(search="", status_filter=""):
    q = db().table(TABLE).select("*").order("last_name").order("first_name")
    data = q.execute().data or []
    enrich(data)
    if search:
        s = search.lower()
        data = [e for e in data if s in (e.get("last_name") or "").lower()
                or s in (e.get("first_name") or "").lower()
                or s in (e.get("department") or "").lower()
                or s in (e.get("position") or "").lower()]
    if status_filter:
        data = [e for e in data if e["_status"] == status_filter]
    return data


def get_or_404(record_id):
    resp = db().table(TABLE).select("*").eq("id", record_id).maybe_single().execute()
    if not resp.data:
        abort(404)
    return resp.data


def alert_count():
    try:
        data = db().table(TABLE).select("i9_complete,doc_list,doc_a_expiry,doc_b_expiry,"
                                        "doc_c_expiry,reverify_needed,reverify_done,"
                                        "reverify_by").execute().data or []
        enrich(data)
        return sum(1 for e in data if e["_status"] != "ok")
    except Exception:
        return 0


# ── CSS ───────────────────────────────────────────────────────

CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --navy:#1b3a5c;--navy-dark:#152e4a;--red:#c0392b;--red-dark:#922b21;
  --gray-50:#f4f6f8;--gray-100:#e9ecef;--gray-200:#dee2e6;--gray-300:#ced4da;
  --gray-500:#6c757d;--gray-700:#495057;--gray-900:#212529;
  --white:#ffffff;
  --shadow:0 2px 8px rgba(0,0,0,.12);--radius:8px;--radius-sm:5px;--t:.18s ease;
}
html{font-size:15px}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--gray-50);
  color:var(--gray-900);line-height:1.55;min-height:100vh;display:flex;flex-direction:column}
a{color:inherit;text-decoration:none}

/* ── Header ── */
.site-header{background:var(--navy);box-shadow:0 2px 8px rgba(0,0,0,.3);
  position:sticky;top:0;z-index:100}
.header-inner{max-width:1200px;margin:0 auto;padding:0 20px;
  display:flex;align-items:center;justify-content:space-between;height:60px;gap:16px}
.logo-link{display:flex;align-items:center;gap:10px;flex-shrink:0}
.logo-img{height:38px;width:auto;display:block}
.logo-text{display:flex;flex-direction:column;line-height:1.1}
.logo-top{font-size:.7rem;font-weight:700;letter-spacing:.12em;color:#c8d6e5;text-transform:uppercase}
.logo-bot{font-size:.95rem;font-weight:800;color:var(--white)}
.main-nav{display:flex;align-items:center;gap:2px;overflow-x:auto;-webkit-overflow-scrolling:touch}
.nav-link{color:rgba(255,255,255,.75);font-size:.85rem;font-weight:500;padding:8px 14px;
  border-radius:var(--radius-sm);border-bottom:2px solid transparent;white-space:nowrap;
  transition:color var(--t),background var(--t),border-color var(--t)}
.nav-link:hover{color:var(--white);background:rgba(255,255,255,.08)}
.nav-link.active{color:var(--white);font-weight:700;border-bottom-color:var(--white);
  background:rgba(255,255,255,.10)}
.badge-nav{display:inline-block;background:#dc3545;color:#fff;font-size:.62rem;
  font-weight:800;border-radius:10px;padding:1px 6px;min-width:18px;text-align:center;
  margin-left:3px;vertical-align:middle}

/* ── Flash ── */
.flash-wrap{max-width:1200px;margin:14px auto 0;padding:0 20px}
.flash{padding:11px 16px;border-radius:var(--radius-sm);font-size:.875rem;
  font-weight:500;margin-bottom:8px;border-left:4px solid}
.flash-success{background:#d4edda;color:#155724;border-color:#28a745}
.flash-error  {background:#f8d7da;color:#721c24;border-color:#dc3545}

/* ── Layout ── */
.page-content{max-width:1200px;margin:0 auto;padding:24px 20px 56px;flex:1;width:100%}
.page-header{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:22px;flex-wrap:wrap;gap:10px}
.page-header h1{font-size:1.9rem;font-weight:800;color:var(--navy)}
.card{background:var(--white);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden}
.mt-4{margin-top:22px}

/* ── Stats Grid ── */
.stats-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:4px}
.stat-card{background:var(--white);border-radius:var(--radius);padding:20px 16px;
  box-shadow:var(--shadow);border-left:4px solid var(--gray-300)}
.stat-card.total   {border-left-color:var(--navy)}
.stat-card.ok      {border-left-color:#28a745}
.stat-card.expiring{border-left-color:#fd7e14}
.stat-card.expired {border-left-color:#dc3545}
.stat-card.missing {border-left-color:var(--red)}
.stat-card a{display:block}
.stat-label{font-size:.67rem;font-weight:700;letter-spacing:.1em;color:var(--gray-500);
  text-transform:uppercase;margin-bottom:6px}
.stat-value{font-size:2.1rem;font-weight:800;color:var(--navy);line-height:1}
.stat-value.v-ok      {color:#155724}
.stat-value.v-expiring{color:#c55a11}
.stat-value.v-expired {color:#721c24}
.stat-value.v-missing {color:var(--red)}

/* ── Alert Banner ── */
.alert-banner{display:flex;align-items:flex-start;gap:12px;padding:13px 18px;
  border-radius:var(--radius);margin-bottom:18px;border-left:4px solid}
.alert-banner.warn{background:#fff3cd;border-color:#ffc107;color:#856404}
.alert-banner.danger{background:#f8d7da;border-color:#dc3545;color:#721c24}
.alert-icon{font-size:1.1rem;flex-shrink:0;margin-top:1px}
.alert-text{font-size:.875rem;font-weight:500}
.alert-text a{font-weight:700;text-decoration:underline;color:inherit}

/* ── Section Title ── */
.section-title{font-size:1rem;font-weight:700;color:var(--navy);
  padding:16px 20px 10px;border-bottom:1px solid var(--gray-100)}
.quick-actions{display:flex;gap:10px;padding:14px 20px 18px;flex-wrap:wrap}

/* ── Buttons ── */
.btn{display:inline-flex;align-items:center;gap:6px;padding:9px 18px;
  border-radius:var(--radius-sm);font-size:.875rem;font-weight:600;cursor:pointer;
  border:2px solid transparent;transition:background var(--t),color var(--t),
  border-color var(--t);white-space:nowrap;line-height:1.2}
.btn-primary{background:var(--navy);color:var(--white);border-color:var(--navy)}
.btn-primary:hover{background:var(--navy-dark);border-color:var(--navy-dark)}
.btn-outline{background:var(--white);color:var(--navy);border-color:var(--gray-300)}
.btn-outline:hover{background:var(--gray-50);border-color:var(--navy)}
.btn-danger{background:var(--white);color:var(--red);border-color:#f5c6cb}
.btn-danger:hover{background:#f8d7da;border-color:var(--red)}
.btn-success{background:#28a745;color:var(--white);border-color:#28a745}
.btn-success:hover{background:#1e7e34;border-color:#1e7e34}
.btn-sm{padding:5px 11px;font-size:.8rem}

/* ── Status Badges ── */
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:.7rem;
  font-weight:700;letter-spacing:.04em;white-space:nowrap}
.badge-ok      {background:#d4edda;color:#155724}
.badge-missing {background:#f8d7da;color:#721c24}
.badge-expired {background:#721c24;color:#ffffff}
.badge-critical{background:#fd7e14;color:#ffffff}
.badge-expiring{background:#fff3cd;color:#856404}

/* ── Table ── */
.data-table{width:100%;border-collapse:collapse}
.data-table thead tr{background:var(--navy);color:var(--white)}
.data-table thead th{padding:12px 14px;font-size:.68rem;font-weight:700;
  letter-spacing:.08em;text-align:left;white-space:nowrap}
.data-table tbody tr{border-bottom:1px solid var(--gray-100);transition:background var(--t)}
.data-table tbody tr:last-child{border-bottom:none}
.data-table tbody tr:hover{filter:brightness(.97)}
.data-table tbody td{padding:12px 14px;font-size:.875rem;color:var(--gray-700);
  vertical-align:middle}
td.bold{font-weight:600;color:var(--gray-900)}
td.actions-cell{white-space:nowrap}
td.actions-cell .btn+.btn{margin-left:4px}
.empty-row{text-align:center;color:var(--gray-500);padding:32px !important;font-style:italic}
.empty-row a{color:var(--navy);font-weight:600}

/* ── Row colors ── */
tr.row-missing  {background:#fff0f0}
tr.row-expired  {background:#ffe8e8}
tr.row-critical {background:#fff5e6}
tr.row-expiring {background:#fffde7}

/* ── Filters ── */
.filter-card{padding:14px 18px;margin-bottom:14px}
.filter-form{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.filter-form .form-control{flex:1;min-width:150px}

/* ── Forms ── */
.form-card{padding:28px 30px;max-width:860px}
.form-group{margin-bottom:18px;flex:1;min-width:200px}
.form-row{display:flex;gap:18px;flex-wrap:wrap}
label{display:block;font-size:.78rem;font-weight:700;color:var(--gray-700);
  text-transform:uppercase;letter-spacing:.06em;margin-bottom:5px}
.form-control{width:100%;padding:9px 12px;border:1.5px solid var(--gray-300);
  border-radius:var(--radius-sm);font-size:.875rem;color:var(--gray-900);
  background:var(--white);transition:border-color var(--t);
  appearance:none;-webkit-appearance:none}
.form-control:focus{outline:none;border-color:var(--navy);
  box-shadow:0 0 0 3px rgba(27,58,92,.12)}
select.form-control{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23495057'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 12px center;padding-right:32px}
textarea.form-control{resize:vertical}
.checkbox-row{display:flex;align-items:center;gap:8px;padding-top:26px}
.checkbox-row input[type=checkbox]{width:17px;height:17px;accent-color:var(--navy);
  cursor:pointer;flex-shrink:0}
.checkbox-row label{margin-bottom:0;text-transform:none;letter-spacing:0;
  font-size:.875rem;font-weight:400;cursor:pointer;color:var(--gray-700)}
.form-actions{display:flex;gap:12px;margin-top:8px;padding-top:18px;
  border-top:1px solid var(--gray-100);flex-wrap:wrap}
.form-section{margin-top:26px;padding-top:18px;border-top:2px solid var(--gray-100)}
.form-section-title{font-size:.78rem;font-weight:800;color:var(--navy);
  text-transform:uppercase;letter-spacing:.1em;margin-bottom:16px;
  display:flex;align-items:center;gap:8px}
.form-section-title::after{content:'';flex:1;height:1px;background:var(--gray-200)}

/* ── Detail View ── */
.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:0}
.detail-row{display:flex;flex-direction:column;padding:12px 20px;
  border-bottom:1px solid var(--gray-100)}
.detail-row:nth-child(odd){background:var(--gray-50)}
.detail-label{font-size:.68rem;font-weight:700;text-transform:uppercase;
  letter-spacing:.08em;color:var(--gray-500);margin-bottom:3px}
.detail-value{font-size:.9rem;color:var(--gray-900);font-weight:500}
.detail-full{grid-column:1/-1}

/* ── Footer ── */
.site-footer{background:var(--navy-dark);color:rgba(255,255,255,.45);
  text-align:center;padding:12px;font-size:.76rem}

/* ── Responsive ── */
@media(max-width:900px){.stats-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:640px){
  .stats-grid{grid-template-columns:repeat(2,1fr)}
  .header-inner{padding:0 12px;height:56px}
  .logo-text{display:none}
  .page-content{padding:14px 12px 48px}
  .page-header h1{font-size:1.4rem}
  .form-card{padding:18px 14px}
  .detail-grid{grid-template-columns:1fr}

  /* Card-style table on mobile */
  .resp-table,.resp-table thead,.resp-table tbody,
  .resp-table th,.resp-table td,.resp-table tr{display:block}
  .resp-table thead tr{display:none}
  .resp-table tbody tr{margin-bottom:12px;padding:14px;border-radius:var(--radius);
    border:1px solid var(--gray-200);box-shadow:var(--shadow)}
  .resp-table tbody tr.row-missing{border-left:4px solid var(--red)}
  .resp-table tbody tr.row-expired{border-left:4px solid #dc3545}
  .resp-table tbody tr.row-critical{border-left:4px solid #fd7e14}
  .resp-table tbody tr.row-expiring{border-left:4px solid #ffc107}
  .resp-table tbody td{padding:5px 0;border:none;display:flex;gap:8px;align-items:flex-start}
  .resp-table tbody td::before{content:attr(data-label);font-weight:700;
    font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;
    color:var(--gray-500);min-width:95px;flex-shrink:0;margin-top:2px}
  .resp-table td.actions-cell{padding-top:12px;border-top:1px solid var(--gray-100);
    margin-top:6px;flex-wrap:wrap}
  .resp-table td.actions-cell::before{display:none}
}
"""

LOGO_SVG = """<svg width="36" height="32" viewBox="0 0 36 32" fill="none" xmlns="http://www.w3.org/2000/svg">
  <polygon points="18,0 36,14 30,14 18,5 6,14 0,14" fill="#c0392b"/>
  <polygon points="18,9 36,23 30,23 18,14 6,23 0,23" fill="#c0392b"/>
  <polygon points="18,18 36,32 30,32 18,23 6,32 0,32" fill="#922b21"/>
</svg>"""

BASE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>{% block title %}I-9 Audit – PM{% endblock %}</title>
  <style>{{ css }}</style>
</head>
<body>
<header class="site-header">
  <div class="header-inner">
    <a href="{{ url_for('i9_dashboard') }}" class="logo-link">
      <img src="/static/PM.gif" alt="PM" class="logo-img"
           onerror="this.style.display='none';this.nextElementSibling.style.display='flex'"/>
      <span style="display:none">{{ logo|safe }}</span>
      <span class="logo-text">
        <span class="logo-top">Preferred Maintenance</span>
        <span class="logo-bot">I-9 Audit</span>
      </span>
    </a>
    <nav class="main-nav">
      <a href="{{ url_for('i9_dashboard') }}"
         class="nav-link {% if ep=='i9_dashboard' %}active{% endif %}">Dashboard</a>
      <a href="{{ url_for('i9_employees') }}"
         class="nav-link {% if 'i9_employee' in ep %}active{% endif %}">Employees</a>
      <a href="{{ url_for('i9_alerts') }}"
         class="nav-link {% if ep=='i9_alerts' %}active{% endif %}">
        Alerts{% if acount %}<span class="badge-nav">{{ acount }}</span>{% endif %}
      </a>
      <a href="{{ url_for('i9_export') }}" class="nav-link">Export CSV</a>
    </nav>
  </div>
</header>
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}
    <div class="flash-wrap">
      {% for cat,msg in messages %}
        <div class="flash flash-{{ cat }}">{{ msg }}</div>
      {% endfor %}
    </div>
  {% endif %}
{% endwith %}
<main class="page-content">{% block content %}{% endblock %}</main>
<footer class="site-footer">&copy; 2026 Preferred Maintenance &mdash; I-9 Audit</footer>
</body>
</html>"""


def render(body, **ctx):
    full = BASE.replace("{% block content %}{% endblock %}",
                        "{% block content %}" + body + "{% endblock %}")
    ctx.setdefault("css", CSS)
    ctx.setdefault("logo", LOGO_SVG)
    ctx.setdefault("ep", request.endpoint or "")
    ctx.setdefault("acount", 0)
    return render_template_string(full, **ctx)


# ── Page Templates ────────────────────────────────────────────

T_DASHBOARD = """
<div class="page-header">
  <h1>I-9 Audit Dashboard</h1>
  <a href="{{ url_for('i9_add_employee') }}" class="btn btn-primary">+ Add Employee</a>
</div>

{% if expired > 0 %}
<div class="alert-banner danger">
  <span class="alert-icon">&#9888;</span>
  <span class="alert-text">
    <strong>{{ expired }} employee(s)</strong> have expired I-9 documents.
    <a href="{{ url_for('i9_alerts') }}">View Alerts &rarr;</a>
  </span>
</div>
{% endif %}
{% if critical > 0 %}
<div class="alert-banner warn">
  <span class="alert-icon">&#128337;</span>
  <span class="alert-text">
    <strong>{{ critical }} employee(s)</strong> have documents expiring within 30 days.
    <a href="{{ url_for('i9_alerts') }}">View Alerts &rarr;</a>
  </span>
</div>
{% endif %}

<div class="stats-grid">
  <div class="stat-card total">
    <div class="stat-label">Total Employees</div>
    <div class="stat-value">{{ total }}</div>
  </div>
  <a href="{{ url_for('i9_employees', status='ok') }}" class="stat-card ok">
    <div class="stat-label">I-9 OK</div>
    <div class="stat-value v-ok">{{ ok }}</div>
  </a>
  <a href="{{ url_for('i9_alerts') }}" class="stat-card expiring">
    <div class="stat-label">Expiring Soon</div>
    <div class="stat-value v-expiring">{{ expiring + critical }}</div>
  </a>
  <a href="{{ url_for('i9_alerts') }}" class="stat-card expired">
    <div class="stat-label">Expired</div>
    <div class="stat-value v-expired">{{ expired }}</div>
  </a>
  <a href="{{ url_for('i9_alerts') }}" class="stat-card missing">
    <div class="stat-label">Missing I-9</div>
    <div class="stat-value v-missing">{{ missing }}</div>
  </a>
</div>

<div class="card mt-4">
  <h2 class="section-title">Quick Actions</h2>
  <div class="quick-actions">
    <a href="{{ url_for('i9_add_employee') }}" class="btn btn-primary">+ Add Employee</a>
    <a href="{{ url_for('i9_employees') }}"    class="btn btn-outline">&#128196; All Employees</a>
    <a href="{{ url_for('i9_alerts') }}"       class="btn btn-outline">&#9888; View Alerts</a>
    <a href="{{ url_for('i9_export') }}"       class="btn btn-outline">&#8595; Export CSV</a>
  </div>
</div>

<div class="card mt-4">
  <h2 class="section-title">Needs Attention</h2>
  <table class="data-table resp-table">
    <thead><tr>
      <th>EMPLOYEE</th><th>DEPT / POSITION</th><th>STATUS</th>
      <th>EXPIRING DOC</th><th>DAYS</th><th>ACTIONS</th>
    </tr></thead>
    <tbody>
      {% for e in attention %}
      <tr class="{{ e._row_class }}">
        <td data-label="Employee" class="bold">{{ e.last_name }}, {{ e.first_name }}{% if e.middle_initial %} {{ e.middle_initial }}.{% endif %}</td>
        <td data-label="Dept/Position">{{ e.department or '' }}{% if e.department and e.position %} / {% endif %}{{ e.position or '—' }}</td>
        <td data-label="Status"><span class="badge {{ e._badge }}">{{ e._status_label }}</span></td>
        <td data-label="Document">{{ e._doc or '—' }}</td>
        <td data-label="Days">{{ e._days_str }}</td>
        <td data-label="Actions" class="actions-cell">
          <a href="{{ url_for('i9_view_employee', emp_id=e.id) }}" class="btn btn-sm btn-outline">View</a>
          <a href="{{ url_for('i9_edit_employee', emp_id=e.id) }}" class="btn btn-sm btn-outline">Edit</a>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="6" class="empty-row">&#10003; All employees are in good standing!</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>"""


T_EMPLOYEES = """
<div class="page-header">
  <h1>Employees</h1>
  <a href="{{ url_for('i9_add_employee') }}" class="btn btn-primary">+ Add Employee</a>
</div>
<div class="card filter-card">
  <form method="GET" class="filter-form">
    <input type="text" name="search" class="form-control"
           placeholder="Search name, dept, position..." value="{{ search }}"/>
    <select name="status" class="form-control">
      <option value="">All Statuses</option>
      <option value="ok"       {% if status_filter=='ok'       %}selected{% endif %}>&#10003; OK</option>
      <option value="expiring" {% if status_filter=='expiring' %}selected{% endif %}>Expiring (&le;90d)</option>
      <option value="critical" {% if status_filter=='critical' %}selected{% endif %}>Expiring (&le;30d)</option>
      <option value="expired"  {% if status_filter=='expired'  %}selected{% endif %}>Expired</option>
      <option value="missing"  {% if status_filter=='missing'  %}selected{% endif %}>Missing I-9</option>
    </select>
    <button type="submit" class="btn btn-primary">Filter</button>
    <a href="{{ url_for('i9_employees') }}" class="btn btn-outline">Clear</a>
  </form>
</div>
<div class="card">
  <table class="data-table resp-table">
    <thead><tr>
      <th>NAME</th><th>HIRE DATE</th><th>DEPT / POSITION</th>
      <th>I-9 STATUS</th><th>DOC TYPE</th><th>EARLIEST EXPIRY</th><th>DAYS</th><th>ACTIONS</th>
    </tr></thead>
    <tbody>
      {% for e in employees %}
      <tr class="{{ e._row_class }}">
        <td data-label="Name" class="bold">
          {{ e.last_name }}, {{ e.first_name }}{% if e.middle_initial %} {{ e.middle_initial }}.{% endif %}
        </td>
        <td data-label="Hire Date">{{ e._hire_fmt }}</td>
        <td data-label="Dept/Position">{{ e.department or '' }}{% if e.department and e.position %} / {% endif %}{{ e.position or '—' }}</td>
        <td data-label="Status"><span class="badge {{ e._badge }}">{{ e._status_label }}</span></td>
        <td data-label="Doc Type">
          {% if e.i9_complete %}
            {% if e.doc_list == 'A' %}List A{% elif e.doc_list == 'BC' %}List B+C{% else %}—{% endif %}
          {% else %}—{% endif %}
        </td>
        <td data-label="Earliest Expiry">{{ e._doc or '—' }}</td>
        <td data-label="Days">{{ e._days_str }}</td>
        <td data-label="Actions" class="actions-cell">
          <a href="{{ url_for('i9_view_employee', emp_id=e.id) }}" class="btn btn-sm btn-outline">View</a>
          <a href="{{ url_for('i9_edit_employee', emp_id=e.id) }}" class="btn btn-sm btn-outline">Edit</a>
          <form method="POST" action="{{ url_for('i9_delete_employee', emp_id=e.id) }}"
                onsubmit="return confirm('Delete {{ e.first_name }} {{ e.last_name }}?');"
                style="display:inline;">
            <button class="btn btn-sm btn-danger">Delete</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="8" class="empty-row">
        No employees found. <a href="{{ url_for('i9_add_employee') }}">Add one.</a>
      </td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>"""


T_FORM = """
<div class="page-header">
  <h1>{{ action }} Employee I-9</h1>
  <a href="{{ url_for('i9_employees') }}" class="btn btn-outline">&#8592; Back</a>
</div>
<div class="card form-card">
<form method="POST">

  <!-- ── Section 1: Employee Info ── -->
  <div class="form-section-title">Employee Information</div>
  <div class="form-row">
    <div class="form-group">
      <label>Last Name *</label>
      <input type="text" name="last_name" class="form-control" required
             value="{{ e.last_name if e else '' }}" placeholder="Smith"/>
    </div>
    <div class="form-group">
      <label>First Name *</label>
      <input type="text" name="first_name" class="form-control" required
             value="{{ e.first_name if e else '' }}" placeholder="John"/>
    </div>
    <div class="form-group" style="max-width:100px">
      <label>M.I.</label>
      <input type="text" name="middle_initial" class="form-control" maxlength="3"
             value="{{ e.middle_initial if e and e.middle_initial else '' }}" placeholder="A"/>
    </div>
  </div>
  <div class="form-row">
    <div class="form-group">
      <label>Hire Date</label>
      <input type="date" name="hire_date" class="form-control"
             value="{{ e.hire_date[:10] if e and e.hire_date else '' }}"/>
    </div>
    <div class="form-group">
      <label>Department</label>
      <input type="text" name="department" class="form-control"
             value="{{ e.department if e and e.department else '' }}" placeholder="e.g. Operations"/>
    </div>
    <div class="form-group">
      <label>Position / Title</label>
      <input type="text" name="position" class="form-control"
             value="{{ e.position if e and e.position else '' }}" placeholder="e.g. Technician"/>
    </div>
  </div>

  <!-- ── Section 2: I-9 Status ── -->
  <div class="form-section">
    <div class="form-section-title">I-9 Completion Status</div>
    <div class="form-row">
      <div class="form-group">
        <label>I-9 on File &amp; Complete?</label>
        <select name="i9_complete" class="form-control">
          <option value="false" {% if not e or not e.i9_complete %}selected{% endif %}>No – Missing / Incomplete</option>
          <option value="true"  {% if e and e.i9_complete %}selected{% endif %}>Yes – I-9 Complete</option>
        </select>
      </div>
      <div class="form-group">
        <label>Date Section 2 Signed</label>
        <input type="date" name="i9_date" class="form-control"
               value="{{ e.i9_date[:10] if e and e.i9_date else '' }}"/>
      </div>
    </div>
  </div>

  <!-- ── Section 3: Documents ── -->
  <div class="form-section">
    <div class="form-section-title">Documents Presented</div>
    <div class="form-group">
      <label>Document List</label>
      <select name="doc_list" id="doc_list" class="form-control" onchange="toggleDocs()">
        <option value=""   {% if not e or not e.doc_list %}selected{% endif %}>— Select —</option>
        <option value="A"  {% if e and e.doc_list=='A'  %}selected{% endif %}>List A (establishes identity &amp; work authorization)</option>
        <option value="BC" {% if e and e.doc_list=='BC' %}selected{% endif %}>List B + List C (identity + work authorization)</option>
      </select>
    </div>

    <!-- List A -->
    <div id="sec-list-a" style="{{ '' if e and e.doc_list=='A' else 'display:none' }}">
      <p style="font-size:.8rem;color:var(--gray-500);margin-bottom:12px">
        Common List A docs: U.S. Passport, Permanent Resident Card (I-551),
        Employment Auth. Document (I-766), Foreign Passport with I-551
      </p>
      <div class="form-row">
        <div class="form-group">
          <label>Document Type</label>
          <select name="doc_a_type" class="form-control">
            <option value="">— Select —</option>
            {% for opt in doc_a_options %}
            <option value="{{ opt }}" {% if e and e.doc_a_type==opt %}selected{% endif %}>{{ opt }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="form-group">
          <label>Issuing Authority</label>
          <input type="text" name="doc_a_issuer" class="form-control"
                 value="{{ e.doc_a_issuer if e and e.doc_a_issuer else '' }}"
                 placeholder="e.g. U.S. Department of State"/>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Document Number</label>
          <input type="text" name="doc_a_number" class="form-control"
                 value="{{ e.doc_a_number if e and e.doc_a_number else '' }}"
                 placeholder="Document #"/>
        </div>
        <div class="form-group">
          <label>Expiration Date</label>
          <input type="date" name="doc_a_expiry" class="form-control"
                 value="{{ e.doc_a_expiry[:10] if e and e.doc_a_expiry else '' }}"/>
        </div>
      </div>
    </div>

    <!-- List B + C -->
    <div id="sec-list-bc" style="{{ '' if e and e.doc_list=='BC' else 'display:none' }}">
      <div style="font-size:.78rem;font-weight:700;color:var(--navy);text-transform:uppercase;
                  letter-spacing:.08em;margin-bottom:10px">List B – Identity Document</div>
      <div class="form-row">
        <div class="form-group">
          <label>Document Type</label>
          <select name="doc_b_type" class="form-control">
            <option value="">— Select —</option>
            {% for opt in doc_b_options %}
            <option value="{{ opt }}" {% if e and e.doc_b_type==opt %}selected{% endif %}>{{ opt }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="form-group">
          <label>Issuing Authority</label>
          <input type="text" name="doc_b_issuer" class="form-control"
                 value="{{ e.doc_b_issuer if e and e.doc_b_issuer else '' }}"
                 placeholder="e.g. State of Florida"/>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Document Number</label>
          <input type="text" name="doc_b_number" class="form-control"
                 value="{{ e.doc_b_number if e and e.doc_b_number else '' }}"
                 placeholder="License / ID #"/>
        </div>
        <div class="form-group">
          <label>Expiration Date</label>
          <input type="date" name="doc_b_expiry" class="form-control"
                 value="{{ e.doc_b_expiry[:10] if e and e.doc_b_expiry else '' }}"/>
        </div>
      </div>

      <div style="font-size:.78rem;font-weight:700;color:var(--navy);text-transform:uppercase;
                  letter-spacing:.08em;margin:16px 0 10px">List C – Work Authorization Document</div>
      <div class="form-row">
        <div class="form-group">
          <label>Document Type</label>
          <select name="doc_c_type" class="form-control">
            <option value="">— Select —</option>
            {% for opt in doc_c_options %}
            <option value="{{ opt }}" {% if e and e.doc_c_type==opt %}selected{% endif %}>{{ opt }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="form-group">
          <label>Issuing Authority</label>
          <input type="text" name="doc_c_issuer" class="form-control"
                 value="{{ e.doc_c_issuer if e and e.doc_c_issuer else '' }}"
                 placeholder="e.g. SSA"/>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Document Number</label>
          <input type="text" name="doc_c_number" class="form-control"
                 value="{{ e.doc_c_number if e and e.doc_c_number else '' }}"
                 placeholder="Doc # (if applicable)"/>
        </div>
        <div class="form-group">
          <label>Expiration Date <small style="font-weight:400;text-transform:none">(if applicable)</small></label>
          <input type="date" name="doc_c_expiry" class="form-control"
                 value="{{ e.doc_c_expiry[:10] if e and e.doc_c_expiry else '' }}"/>
        </div>
      </div>
    </div>
  </div>

  <!-- ── Section 4: Re-verification ── -->
  <div class="form-section">
    <div class="form-section-title">Re-verification (Section 3)</div>
    <div class="checkbox-row" style="padding-top:0;margin-bottom:14px">
      <input type="checkbox" id="reverify_needed" name="reverify_needed" value="yes"
             onchange="toggleReverify()"
             {% if e and e.reverify_needed %}checked{% endif %}/>
      <label for="reverify_needed">This employee requires re-verification</label>
    </div>
    <div id="sec-reverify" style="{{ '' if e and e.reverify_needed else 'display:none' }}">
      <div class="form-row">
        <div class="form-group">
          <label>Re-verify By Date</label>
          <input type="date" name="reverify_by" class="form-control"
                 value="{{ e.reverify_by[:10] if e and e.reverify_by else '' }}"/>
        </div>
        <div class="form-group" style="max-width:220px">
          <div class="checkbox-row">
            <input type="checkbox" id="reverify_done" name="reverify_done" value="yes"
                   {% if e and e.reverify_done %}checked{% endif %}/>
            <label for="reverify_done">Re-verification complete</label>
          </div>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>New Document Type</label>
          <input type="text" name="reverify_doc_type" class="form-control"
                 value="{{ e.reverify_doc_type if e and e.reverify_doc_type else '' }}"
                 placeholder="e.g. Employment Auth. Document"/>
        </div>
        <div class="form-group">
          <label>New Document Number</label>
          <input type="text" name="reverify_doc_number" class="form-control"
                 value="{{ e.reverify_doc_number if e and e.reverify_doc_number else '' }}"/>
        </div>
        <div class="form-group">
          <label>New Document Expiry</label>
          <input type="date" name="reverify_doc_expiry" class="form-control"
                 value="{{ e.reverify_doc_expiry[:10] if e and e.reverify_doc_expiry else '' }}"/>
        </div>
      </div>
    </div>
  </div>

  <!-- ── Notes ── -->
  <div class="form-section">
    <div class="form-section-title">Notes</div>
    <div class="form-group" style="min-width:100%">
      <textarea name="notes" class="form-control" rows="3"
                placeholder="Any additional notes about this employee's I-9 status...">{{ e.notes if e and e.notes else '' }}</textarea>
    </div>
  </div>

  <div class="form-actions">
    <button type="submit" class="btn btn-primary">&#10003; Save Record</button>
    <a href="{{ url_for('i9_employees') }}" class="btn btn-outline">Cancel</a>
  </div>
</form>
</div>

<script>
function toggleDocs(){
  var v=document.getElementById('doc_list').value;
  document.getElementById('sec-list-a').style.display=(v==='A'?'block':'none');
  document.getElementById('sec-list-bc').style.display=(v==='BC'?'block':'none');
}
function toggleReverify(){
  var c=document.getElementById('reverify_needed').checked;
  document.getElementById('sec-reverify').style.display=(c?'block':'none');
}
</script>"""


T_DETAIL = """
<div class="page-header">
  <h1>{{ e.first_name }} {{ e.last_name }}</h1>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <a href="{{ url_for('i9_edit_employee', emp_id=e.id) }}" class="btn btn-primary">Edit</a>
    <a href="{{ url_for('i9_employees') }}" class="btn btn-outline">&#8592; Back</a>
  </div>
</div>

<div style="margin-bottom:16px">
  <span class="badge {{ e._badge }}" style="font-size:.85rem;padding:5px 14px">{{ e._status_label }}</span>
  {% if e._doc %}
    &nbsp;<span style="font-size:.875rem;color:var(--gray-500)">{{ e._doc }} &mdash; {{ e._days_str }}</span>
  {% endif %}
</div>

<div class="card">
  <h2 class="section-title">Employee Information</h2>
  <div class="detail-grid">
    <div class="detail-row">
      <span class="detail-label">Full Name</span>
      <span class="detail-value">{{ e.last_name }}, {{ e.first_name }}{% if e.middle_initial %} {{ e.middle_initial }}.{% endif %}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Hire Date</span>
      <span class="detail-value">{{ e._hire_fmt }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Department</span>
      <span class="detail-value">{{ e.department or '—' }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Position</span>
      <span class="detail-value">{{ e.position or '—' }}</span>
    </div>
  </div>
</div>

<div class="card mt-4">
  <h2 class="section-title">I-9 Status</h2>
  <div class="detail-grid">
    <div class="detail-row">
      <span class="detail-label">I-9 Complete</span>
      <span class="detail-value">{% if e.i9_complete %}&#10003; Yes{% else %}&#10007; No{% endif %}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Date Signed (Sec. 2)</span>
      <span class="detail-value">{{ e._i9_fmt }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Document List</span>
      <span class="detail-value">
        {% if e.doc_list == 'A' %}List A{% elif e.doc_list == 'BC' %}List B + List C{% else %}—{% endif %}
      </span>
    </div>
  </div>
</div>

{% if e.doc_list %}
<div class="card mt-4">
  {% if e.doc_list == 'A' %}
  <h2 class="section-title">List A Document</h2>
  <div class="detail-grid">
    <div class="detail-row">
      <span class="detail-label">Document Type</span>
      <span class="detail-value">{{ e.doc_a_type or '—' }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Issuing Authority</span>
      <span class="detail-value">{{ e.doc_a_issuer or '—' }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Document Number</span>
      <span class="detail-value">{{ e.doc_a_number or '—' }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Expiration Date</span>
      <span class="detail-value">{{ e.doc_a_expiry|fmt_date if e.doc_a_expiry else '—' }}</span>
    </div>
  </div>
  {% else %}
  <h2 class="section-title">List B Document (Identity)</h2>
  <div class="detail-grid">
    <div class="detail-row">
      <span class="detail-label">Document Type</span>
      <span class="detail-value">{{ e.doc_b_type or '—' }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Issuing Authority</span>
      <span class="detail-value">{{ e.doc_b_issuer or '—' }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Document Number</span>
      <span class="detail-value">{{ e.doc_b_number or '—' }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Expiration Date</span>
      <span class="detail-value">{{ e.doc_b_expiry|fmt_date if e.doc_b_expiry else '—' }}</span>
    </div>
  </div>
  <h2 class="section-title" style="margin-top:0">List C Document (Work Auth.)</h2>
  <div class="detail-grid">
    <div class="detail-row">
      <span class="detail-label">Document Type</span>
      <span class="detail-value">{{ e.doc_c_type or '—' }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Issuing Authority</span>
      <span class="detail-value">{{ e.doc_c_issuer or '—' }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Document Number</span>
      <span class="detail-value">{{ e.doc_c_number or '—' }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Expiration Date</span>
      <span class="detail-value">{{ e.doc_c_expiry|fmt_date if e.doc_c_expiry else 'Does not expire' }}</span>
    </div>
  </div>
  {% endif %}
</div>
{% endif %}

{% if e.reverify_needed %}
<div class="card mt-4">
  <h2 class="section-title">Re-verification (Section 3)</h2>
  <div class="detail-grid">
    <div class="detail-row">
      <span class="detail-label">Re-verify By</span>
      <span class="detail-value">{{ e.reverify_by|fmt_date if e.reverify_by else '—' }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Status</span>
      <span class="detail-value">{% if e.reverify_done %}&#10003; Complete{% else %}&#10007; Pending{% endif %}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">New Doc Type</span>
      <span class="detail-value">{{ e.reverify_doc_type or '—' }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">New Doc Number</span>
      <span class="detail-value">{{ e.reverify_doc_number or '—' }}</span>
    </div>
    <div class="detail-row detail-full">
      <span class="detail-label">New Doc Expiry</span>
      <span class="detail-value">{{ e.reverify_doc_expiry|fmt_date if e.reverify_doc_expiry else '—' }}</span>
    </div>
  </div>
</div>
{% endif %}

{% if e.notes %}
<div class="card mt-4">
  <h2 class="section-title">Notes</h2>
  <div style="padding:16px 20px;font-size:.9rem;color:var(--gray-700);white-space:pre-wrap">{{ e.notes }}</div>
</div>
{% endif %}"""


T_ALERTS = """
<div class="page-header">
  <h1>Alerts</h1>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <a href="{{ url_for('i9_export') }}" class="btn btn-outline">&#8595; Export CSV</a>
    <a href="{{ url_for('i9_add_employee') }}" class="btn btn-primary">+ Add Employee</a>
  </div>
</div>

{% macro emp_table(rows, cols) %}
<table class="data-table resp-table">
  <thead><tr>
    <th>EMPLOYEE</th><th>HIRE DATE</th><th>DEPT / POSITION</th>
    <th>STATUS</th><th>DOCUMENT</th><th>DATE / DAYS</th><th>ACTIONS</th>
  </tr></thead>
  <tbody>
    {% for e in rows %}
    <tr class="{{ e._row_class }}">
      <td data-label="Employee" class="bold">{{ e.last_name }}, {{ e.first_name }}</td>
      <td data-label="Hire Date">{{ e._hire_fmt }}</td>
      <td data-label="Dept/Position">{{ e.department or '' }}{% if e.department and e.position %} / {% endif %}{{ e.position or '—' }}</td>
      <td data-label="Status"><span class="badge {{ e._badge }}">{{ e._status_label }}</span></td>
      <td data-label="Document">{{ e._doc or '—' }}</td>
      <td data-label="Days">{{ e._days_str }}</td>
      <td data-label="Actions" class="actions-cell">
        <a href="{{ url_for('i9_view_employee', emp_id=e.id) }}" class="btn btn-sm btn-outline">View</a>
        <a href="{{ url_for('i9_edit_employee', emp_id=e.id) }}" class="btn btn-sm btn-outline">Edit</a>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="7" class="empty-row">&#10003; None in this category.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endmacro %}

{% if not (expired or critical or expiring or missing) %}
<div style="text-align:center;padding:60px 20px;color:var(--gray-500)">
  <div style="font-size:2.5rem;margin-bottom:12px">&#10003;</div>
  <div style="font-size:1.1rem;font-weight:600">All employees are in good standing!</div>
  <div style="margin-top:8px;font-size:.875rem">No expired, expiring, or missing I-9 records found.</div>
</div>
{% endif %}

{% if expired %}
<div class="card mt-4">
  <h2 class="section-title" style="color:#721c24">
    &#9888; Expired Documents ({{ expired|length }})
  </h2>
  {{ emp_table(expired) }}
</div>
{% endif %}

{% if critical %}
<div class="card mt-4">
  <h2 class="section-title" style="color:#c55a11">
    &#128337; Expiring Within 30 Days ({{ critical|length }})
  </h2>
  {{ emp_table(critical) }}
</div>
{% endif %}

{% if expiring %}
<div class="card mt-4">
  <h2 class="section-title" style="color:#856404">
    &#128197; Expiring Within 90 Days ({{ expiring|length }})
  </h2>
  {{ emp_table(expiring) }}
</div>
{% endif %}

{% if missing %}
<div class="card mt-4">
  <h2 class="section-title" style="color:var(--red)">
    &#128196; Missing I-9 ({{ missing|length }})
  </h2>
  {{ emp_table(missing) }}
</div>
{% endif %}"""


# ── Document Type Options ─────────────────────────────────────

DOC_A_OPTIONS = [
    "U.S. Passport",
    "U.S. Passport Card",
    "Permanent Resident Card (I-551 / Green Card)",
    "Employment Authorization Document (I-766)",
    "Foreign Passport with Temporary I-551 Stamp",
    "Foreign Passport with I-94 (nonimmigrant status)",
    "Passport with Machine Readable Immigrant Visa",
    "Other List A Document",
]

DOC_B_OPTIONS = [
    "Driver's License",
    "State ID Card",
    "School ID Card with Photo",
    "Voter's Registration Card",
    "U.S. Military Card or Draft Record",
    "U.S. Military Dependent's ID Card",
    "U.S. Coast Guard Merchant Mariner Card",
    "Native American Tribal Document",
    "Canadian Driver's License",
    "School Record (under 18, no photo ID)",
    "Doctor / Hospital Record (under 18)",
    "Other List B Document",
]

DOC_C_OPTIONS = [
    "Social Security Card (unrestricted)",
    "Certification of Report of Birth (DS-1350)",
    "Consular Report of Birth Abroad (FS-240)",
    "U.S. Birth Certificate (FS-545 or DS-1350)",
    "Certified Copy of Birth Certificate",
    "Native American Tribal Document",
    "U.S. Citizen ID Card (I-197)",
    "Resident Citizen ID Card (I-179)",
    "Employment Auth. Document (DHS – Form I-94)",
    "Other List C Document",
]


# ── Jinja filter ──────────────────────────────────────────────

@app.template_filter("fmt_date")
def jinja_fmt_date(s):
    return fmt_date(s)


# ── Routes ────────────────────────────────────────────────────

@app.route("/i9/")
def i9_dashboard():
    all_emps = get_employees()
    counts = {}
    for e in all_emps:
        counts[e["_status"]] = counts.get(e["_status"], 0) + 1

    attention = [e for e in all_emps if e["_status"] != "ok"]
    attention.sort(key=lambda e: (
        {"expired": 0, "critical": 1, "missing": 2, "expiring": 3, "ok": 4}[e["_status"]],
        e.get("_days") or 9999
    ))

    ac = sum(1 for e in all_emps if e["_status"] != "ok")
    return render(T_DASHBOARD,
                  total=len(all_emps),
                  ok=counts.get("ok", 0),
                  expiring=counts.get("expiring", 0),
                  critical=counts.get("critical", 0),
                  expired=counts.get("expired", 0),
                  missing=counts.get("missing", 0),
                  attention=attention[:20],
                  acount=ac)


@app.route("/i9/employees")
def i9_employees():
    search        = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "")
    employees     = get_employees(search, status_filter)
    ac = sum(1 for e in get_employees() if e["_status"] != "ok")
    return render(T_EMPLOYEES, employees=employees,
                  search=search, status_filter=status_filter, acount=ac)


@app.route("/i9/employees/add", methods=["GET", "POST"])
def i9_add_employee():
    if request.method == "POST":
        payload = _build_payload()
        db().table(TABLE).insert(payload).execute()
        flash(f'Employee "{payload["first_name"]} {payload["last_name"]}" added.', "success")
        return redirect(url_for("i9_employees"))
    ac = alert_count()
    return render(T_FORM, action="Add", e=None,
                  doc_a_options=DOC_A_OPTIONS,
                  doc_b_options=DOC_B_OPTIONS,
                  doc_c_options=DOC_C_OPTIONS,
                  acount=ac)


@app.route("/i9/employees/<int:emp_id>/edit", methods=["GET", "POST"])
def i9_edit_employee(emp_id):
    raw = get_or_404(emp_id)
    if request.method == "POST":
        payload = _build_payload()
        db().table(TABLE).update(payload).eq("id", emp_id).execute()
        flash(f'Record for "{payload["first_name"]} {payload["last_name"]}" updated.', "success")
        return redirect(url_for("i9_view_employee", emp_id=emp_id))
    enrich([raw])
    ac = alert_count()
    return render(T_FORM, action="Edit", e=raw,
                  doc_a_options=DOC_A_OPTIONS,
                  doc_b_options=DOC_B_OPTIONS,
                  doc_c_options=DOC_C_OPTIONS,
                  acount=ac)


@app.route("/i9/employees/<int:emp_id>")
def i9_view_employee(emp_id):
    raw = get_or_404(emp_id)
    enrich([raw])
    ac = alert_count()
    return render(T_DETAIL, e=raw, acount=ac)


@app.route("/i9/employees/<int:emp_id>/delete", methods=["POST"])
def i9_delete_employee(emp_id):
    raw = get_or_404(emp_id)
    db().table(TABLE).delete().eq("id", emp_id).execute()
    flash(f'Record for "{raw.get("first_name")} {raw.get("last_name")}" deleted.', "success")
    return redirect(url_for("i9_employees"))


@app.route("/i9/alerts")
def i9_alerts():
    all_emps = get_employees()
    expired  = [e for e in all_emps if e["_status"] == "expired"]
    critical = [e for e in all_emps if e["_status"] == "critical"]
    expiring = [e for e in all_emps if e["_status"] == "expiring"]
    missing  = [e for e in all_emps if e["_status"] == "missing"]
    ac = len(expired) + len(critical) + len(expiring) + len(missing)
    return render(T_ALERTS, expired=expired, critical=critical,
                  expiring=expiring, missing=missing, acount=ac)


@app.route("/i9/export")
def i9_export():
    employees = get_employees()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Last Name", "First Name", "M.I.", "Hire Date",
        "Department", "Position",
        "I9 Complete", "I9 Date",
        "Doc List",
        "List A Type", "List A Number", "List A Issuer", "List A Expiry",
        "List B Type", "List B Number", "List B Issuer", "List B Expiry",
        "List C Type", "List C Number", "List C Issuer", "List C Expiry",
        "Reverify Needed", "Reverify By", "Reverify Done",
        "Reverify Doc Type", "Reverify Doc Number", "Reverify Doc Expiry",
        "Notes", "Status"
    ])
    for e in employees:
        writer.writerow([
            e.get("id"), e.get("last_name"), e.get("first_name"), e.get("middle_initial"),
            e.get("hire_date") or "", e.get("department") or "", e.get("position") or "",
            "Yes" if e.get("i9_complete") else "No", e.get("i9_date") or "",
            e.get("doc_list") or "",
            e.get("doc_a_type") or "", e.get("doc_a_number") or "",
            e.get("doc_a_issuer") or "", e.get("doc_a_expiry") or "",
            e.get("doc_b_type") or "", e.get("doc_b_number") or "",
            e.get("doc_b_issuer") or "", e.get("doc_b_expiry") or "",
            e.get("doc_c_type") or "", e.get("doc_c_number") or "",
            e.get("doc_c_issuer") or "", e.get("doc_c_expiry") or "",
            "Yes" if e.get("reverify_needed") else "No",
            e.get("reverify_by") or "",
            "Yes" if e.get("reverify_done") else "No",
            e.get("reverify_doc_type") or "", e.get("reverify_doc_number") or "",
            e.get("reverify_doc_expiry") or "",
            e.get("notes") or "",
            e["_status_label"]
        ])
    csv_data = output.getvalue()
    today_str = date.today().strftime("%Y-%m-%d")
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=i9_audit_{today_str}.csv"}
    )


# ── Payload builder ───────────────────────────────────────────

def _build_payload():
    f = request.form
    def d(key):
        v = f.get(key, "").strip()
        return v if v else None

    return {
        "last_name":       f.get("last_name", "").strip(),
        "first_name":      f.get("first_name", "").strip(),
        "middle_initial":  d("middle_initial"),
        "hire_date":       d("hire_date"),
        "department":      d("department"),
        "position":        d("position"),
        "i9_complete":     f.get("i9_complete") == "true",
        "i9_date":         d("i9_date"),
        "doc_list":        d("doc_list"),
        "doc_a_type":      d("doc_a_type"),
        "doc_a_number":    d("doc_a_number"),
        "doc_a_issuer":    d("doc_a_issuer"),
        "doc_a_expiry":    d("doc_a_expiry"),
        "doc_b_type":      d("doc_b_type"),
        "doc_b_number":    d("doc_b_number"),
        "doc_b_issuer":    d("doc_b_issuer"),
        "doc_b_expiry":    d("doc_b_expiry"),
        "doc_c_type":      d("doc_c_type"),
        "doc_c_number":    d("doc_c_number"),
        "doc_c_issuer":    d("doc_c_issuer"),
        "doc_c_expiry":    d("doc_c_expiry"),
        "reverify_needed": f.get("reverify_needed") == "yes",
        "reverify_by":     d("reverify_by"),
        "reverify_done":   f.get("reverify_done") == "yes",
        "reverify_doc_type":   d("reverify_doc_type"),
        "reverify_doc_number": d("reverify_doc_number"),
        "reverify_doc_expiry": d("reverify_doc_expiry"),
        "notes":           d("notes"),
    }


# ── Entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    print("I-9 Audit App running at http://localhost:5001/i9/")
    app.run(debug=True, host="0.0.0.0", port=5001)
