# Sadakalawe Sales Management System — Project Brief

> This file is the project brief for **Claude Code**. It carries the context, decisions, and scope worked out in a planning conversation on Claude.ai. Read it before doing anything in this repo.

---

## What this is

A custom sales management system for **Sadakalawe Enterprises**, a premium electronics retailer in Tanzania. The system replaces the owner manually drafting invoices / proformas / delivery notes for staff every time a client walks in. Staff log in, generate branded documents fast, and every sale is logged automatically.

---

## Business context

**Sadakalawe Enterprises** — sells genuine electronics: MacBooks, iPhones, Anker products, JBL products, and accessories.

- **Owner:** Sey
- **Locations (two active branches):**
  - **Arusha (main):** Bondeni Street, Opposite Mega Complex
  - **Dar es Salaam:** Kariakoo, Aggrey Street
- **TIN:** 164-334-864
- **Phone:** +255 768 596 006
- **Website:** sadakalawe.com
- **VAT status:** VAT-registered with EFD — but **EFD invoicing is optional per transaction** (not every customer wants/needs an EFD receipt)
- **Target customers:** premium individuals, corporate/business (including Arusha safari operators), tech-forward youth

---

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python |
| Web framework | Flask |
| Database | SQLite (WAL mode) |
| PDF generation | ReportLab |
| Frontend | Server-rendered Jinja2 + light JS |
| Target OS | macOS (shop Mac desktop) |
| Eventual packaging | `.app` bundle via py2app (so staff just double-click to start) |
| Access pattern | Local web app — staff open `localhost` in a browser on the shop Mac |

### Why this stack
- Owner already knows Python / Flask / ReportLab
- SQLite file = trivial backup (copy one file)
- Browser UI = zero staff training
- All local = works without internet, no cloud bills

---

## Brand assets

- **Logo:** `static/logo.png` — orange "S" diamond mark + "SADAKALAWE ENTERPRISES" text, orange-on-black
- **Brand colors:**
  - Primary orange: approximately `#F26522` — **extract exact value from logo file before finalizing**
  - Black: `#000000`
  - White: `#FFFFFF`
- **Document style:** White background, black body text, orange as accent (header band, totals row, logo). Premium, clean, readable when printed.

---

## Architecture decisions (locked in)

### 1. Branch-aware everything

Two active branches means every document carries the issuing branch. Per-branch numbering:

| Doc type | Arusha | Dar es Salaam |
|---|---|---|
| Invoice | `INV-ARU-2026-0001` | `INV-DAR-2026-0001` |
| Proforma | `PRO-ARU-2026-0001` | `PRO-DAR-2026-0001` |
| Delivery Note | `DN-ARU-2026-0001` | `DN-DAR-2026-0001` |

- Sequences are independent per branch, restart each calendar year
- Staff accounts are scoped to a branch — staff see their branch's data by default
- Admin role (owner) sees everything across both branches

### 2. EFD is optional per transaction (important)

A single toggle on the document creation page switches the format:

- **Standard invoice** — no VAT line, no EFD reference (default for walk-ins who don't request EFD)
- **VAT invoice** — VAT (currently 18% in TZ — make this configurable) calculated and shown as a line, with a field to enter the EFD receipt reference number after the EFD machine prints it

### 3. Three document types in Phase 1

- **Invoice** — completed sale
- **Proforma** — quote, marked "This is not a tax invoice," with a validity period
- **Delivery Note** — goods released, signature line for recipient

### 4. Multi-user with audit trail

- Each staff has their own login
- Every document records `created_by` (staff ID) and `created_at` (timestamp)
- Owner can see who created or modified what

### 5. Backup is non-negotiable

Single shop PC per branch = single point of failure. Must include:

- SQLite WAL mode (survives sudden power loss without corruption)
- Daily automatic export of the database file to a configurable backup folder (USB stick or Google Drive sync folder)
- Manual "Export all to CSV" button accessible anytime
- Weekly snapshot retention

---

## Phase 1 — MVP scope (build this first)

1. **Login system** — staff accounts, branch scoping, admin role
2. **Customer management** — add / edit / search (name, phone, TIN if business, address, notes)
3. **Product catalog** — add / edit / search, with brand category (MacBook / iPhone / Anker / JBL / Accessories), model, price, stock count
4. **Unified document creator** — Invoice / Proforma / Delivery Note from one flow:
   - Pick customer (or quick-add new)
   - Add line items from catalog (or quick-add custom)
   - Toggle VAT on/off
   - Auto-number per branch
   - Generate branded PDF using logo + brand colors
   - Save to sales log
5. **Sales log** — searchable list, filter by branch / date / staff / customer / doc type, reprint any past document
6. **Dashboard** — today / this week / this month totals, top products, top customers, per-branch split
7. **Backup module** — daily auto-export, manual export button

### Suggested first milestone (slice, not vertical)

**Build the invoice creator + branded PDF generator first as a working slice.** Generate one beautifully branded invoice PDF end-to-end before building everything else. Sey wants to see and feel the output early — if the look is off, we fix it before the rest gets built on top.

---

## Phase 2 — once MVP is being used in shops

- Payment tracking (paid / partial / unpaid, outstanding balances report)
- Stock levels with low-stock alerts (proper inventory module)
- Convert proforma → invoice in one click
- Convert invoice → delivery note in one click
- Top sellers / top customers / slow-moving stock reports
- Export reports to Excel

## Phase 3 — longer term, ties to differentiators

- **Trade-in tracking** — key differentiator for Sadakalawe
- **Financing / installment tracking** — with risk-mitigation logic. Note: iPhones can't be remote-locked by third-party software, so iPhone financing needs stricter manual controls (higher deposits, shorter terms, verified customers, possibly employer salary-deduction partnerships)
- **WhatsApp share button** — one-click send PDF via WhatsApp Web
- **Sync with WooCommerce** (sadakalawe.com) for unified online + retail sales view

---

## Open items (resolve before/during Phase 1)

- **Existing customer / product data import** — owner hasn't confirmed yet whether existing lists exist (Excel / phone notes / paper book). If they do, build a one-time import script early. If not, catalog and customer DB fill up organically in the first few weeks of use.

---

## How the owner (Sey) works

- Casual, direct communication — match that energy, no corporate hedging
- Prefers momentum-driven phased building over exhaustive upfront spec
- Values plain-language explanations, tables, concrete examples
- Push back honestly when something doesn't make sense — he respects directness over agreement-bait
- Has Python / Flask / ReportLab basics; comfortable with code but appreciates clear reasoning behind decisions

---

## Suggested initial repo setup

```
sadakalawe/
├── CLAUDE.md                 # this file
├── README.md                 # setup + run instructions
├── requirements.txt          # flask, reportlab, etc.
├── .gitignore
├── app.py                    # Flask entry point
├── config.py                 # branch config, brand assets, VAT rate
├── database.py               # SQLite setup, WAL mode
├── models/                   # User, Customer, Product, Document, DocumentItem
├── routes/                   # auth, customers, products, documents, reports
├── services/
│   ├── numbering.py          # per-branch auto-numbering
│   ├── pdf_generator.py      # ReportLab branded PDFs
│   └── backup.py             # daily auto-backup
├── templates/                # Jinja2 templates
├── static/
│   ├── css/
│   ├── js/
│   └── logo.png              # commit Sadakalawe logo here
├── data/
│   └── sadakalawe.db         # SQLite DB (gitignore this)
└── backups/                  # daily DB exports (gitignore)
```

---

## Suggested first steps in this repo

1. Read this file end-to-end
2. Set up `requirements.txt`, `.gitignore`, basic Flask skeleton
3. Drop `logo.png` into `static/`
4. Build SQLite schema for: users, branches, customers, products, documents, document_items
5. Build the **invoice creator + branded PDF generator slice first** — full vertical for one document type
6. Show Sey the generated PDF, get feedback, iterate
7. Then build out customers, products, login, sales log, dashboard, backup in that rough order

---

End of brief. Goal: build something Sey and his staff actually use every day in both shops.
