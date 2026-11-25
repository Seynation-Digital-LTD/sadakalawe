/* Sadakalawe — Document Creator */

document.addEventListener('DOMContentLoaded', () => {
  if (!document.getElementById('doc-form')) return;

  const VAT = typeof VAT_RATE !== 'undefined' ? parseFloat(VAT_RATE) : 18;
  let rowCount = 0;

  // Payment toggle is handled inline in new.html (supports multi-method grid).

  // ── VAT toggle ─────────────────────────────────────────────
  const vatBox = document.getElementById('is_vat');
  const vatRow = document.getElementById('vat-row');
  const efdSec = document.getElementById('efd-section');

  vatBox && vatBox.addEventListener('change', () => {
    vatRow && (vatRow.style.display = vatBox.checked ? '' : 'none');
    efdSec && (efdSec.style.display = vatBox.checked ? '' : 'none');
    recalc();
  });

  // ── Customer search ────────────────────────────────────────
  const walkinInp  = document.getElementById('walkin_name');
  const custDrop   = document.getElementById('customer-dropdown');
  const custId     = document.getElementById('customer_id');
  const phoneDisp  = document.getElementById('customer-phone-display');

  let custTimer;

  walkinInp && walkinInp.addEventListener('input', () => {
    clearTimeout(custTimer);
    custId.value = '';
    if (phoneDisp) phoneDisp.value = '';
    const q = walkinInp.value.trim();
    if (!q || q.length < 2) { custDrop.style.display = 'none'; return; }
    custTimer = setTimeout(() => searchCustomers(q), 240);
  });

  walkinInp && walkinInp.addEventListener('blur', () => {
    setTimeout(() => { custDrop.style.display = 'none'; }, 200);
  });

  function searchCustomers(q) {
    fetch(`${CUSTOMER_SEARCH_URL}?q=${encodeURIComponent(q)}`)
      .then(r => r.json())
      .then(data => {
        custDrop.innerHTML = '';
        if (!data.length) { custDrop.style.display = 'none'; return; }
        data.forEach(c => {
          const div = document.createElement('div');
          div.className = 'ac-item';
          div.innerHTML =
            `<div class="ac-item__main">${esc(c.name)}</div>` +
            `<div class="ac-item__sub">${esc(c.phone || '')}${c.tin ? ' · TIN ' + esc(c.tin) : ''}</div>`;
          div.addEventListener('mousedown', () => pickCustomer(c));
          custDrop.appendChild(div);
        });
        custDrop.style.display = '';
      });
  }

  function pickCustomer(c) {
    custId.value        = c.id;
    walkinInp.value     = c.name;
    if (phoneDisp) phoneDisp.value = c.phone || '';
    custDrop.style.display = 'none';
  }

  // ── Line items ─────────────────────────────────────────────
  const itemsBody = document.getElementById('items-body');
  const addBtn    = document.getElementById('add-item-btn');
  const prodPopup = document.getElementById('product-popup');

  addBtn && addBtn.addEventListener('click', () => addRow());

  // Defer initial row: if PREFILL_DATA is set, populate from it; else add blank row
  if (typeof PREFILL_DATA !== 'undefined' && PREFILL_DATA.length) {
    PREFILL_DATA.forEach(item =>
      addRow(item.description || '', item.qty || 1, item.price || '', item.specs || '', item.discount || 0, item.product_id || ''));
    recalcOnce = true;
  } else {
    addRow();
  }

  function addRow(desc = '', qty = 1, price = '', specs = '', disc = 0, pid = '') {
    rowCount++;
    const tr = document.createElement('tr');
    tr.dataset.row = rowCount;
    tr.innerHTML = `
      <td class="row-num">${rowCount}</td>
      <td style="position:relative">
        <input type="text" name="item_description[]" class="desc-inp"
               value="${esc(desc)}" placeholder="Item name or description…" autocomplete="off">
        <input type="text" name="item_specs[]" class="specs-inp"
               value="${esc(specs)}" placeholder="Specs / details (optional)…" style="margin-top:3px;font-size:12px;color:#6b7280">
        <input type="hidden" name="item_product_id[]" class="pid-inp" value="">
        <input type="hidden" name="item_units[]" class="units-inp" value="">
        <div class="units-box" style="display:none;margin-top:6px;padding:6px 8px;border:1px solid #e5e7eb;border-radius:6px;background:#fafafa"></div>
      </td>
      <td>
        <input type="number" name="item_qty[]" class="qty-inp"
               value="${qty}" step="any" style="text-align:right">
      </td>
      <td>
        <input type="number" name="item_price[]" class="price-inp"
               value="${price}" min="0" step="100" placeholder="0" style="text-align:right">
      </td>
      <td>
        <div style="display:flex;align-items:center;gap:2px">
          <input type="number" name="item_discount[]" class="disc-inp"
                 value="${disc}" min="0" max="100" step="1" placeholder="0"
                 style="text-align:right;width:52px" title="Discount %">
          <span style="font-size:11px;color:#9ca3af">%</span>
        </div>
      </td>
      <td class="line-total" data-val="0">-</td>
      <td>
        <button type="button" class="btn-row-del" title="Futa safu">
          <i class="bi bi-x-lg"></i>
        </button>
      </td>`;
    itemsBody.appendChild(tr);

    const descInp  = tr.querySelector('.desc-inp');
    const qtyInp   = tr.querySelector('.qty-inp');
    const priceInp = tr.querySelector('.price-inp');
    const discInp  = tr.querySelector('.disc-inp');
    const pidInp   = tr.querySelector('.pid-inp');
    if (pid) pidInp.value = pid;

    let prodTimer;
    descInp.addEventListener('input', () => {
      clearTimeout(prodTimer);
      pidInp.value = '';
      clearUnits(tr);   // typing a new description drops the old product's units
      const q = descInp.value.trim();
      if (!q) { hideProd(); return; }
      prodTimer = setTimeout(() => searchProducts(q, descInp, tr), 240);
    });
    descInp.addEventListener('blur', () => setTimeout(hideProd, 200));

    [qtyInp, priceInp, discInp].forEach(el =>
      el.addEventListener('input', () => { updateRow(tr); recalc(); }));
    qtyInp.addEventListener('input', () => syncUnits(tr));

    tr.querySelector('.btn-row-del').addEventListener('click', () => {
      tr.remove(); renumber(); recalc();
    });

    if (price) { updateRow(tr); recalc(); }
    descInp.focus();
  }

  function updateRow(tr) {
    const qty   = parseFloat(tr.querySelector('.qty-inp').value) || 0;
    const price = parseFloat(tr.querySelector('.price-inp').value) || 0;
    const disc  = Math.min(100, Math.max(0, parseFloat(tr.querySelector('.disc-inp')?.value) || 0));
    const total = qty * price * (1 - disc / 100);
    const cell  = tr.querySelector('.line-total');
    if (total) {
      cell.innerHTML = disc > 0
        ? `<span style="text-decoration:line-through;color:#9ca3af;font-size:11px">TZS ${fmt(qty*price)}</span><br><b>TZS ${fmt(total)}</b>`
        : `TZS ${fmt(total)}`;
    } else {
      cell.textContent = '-';
    }
    cell.dataset.val = total;
  }

  function recalc() {
    let sub = 0;
    itemsBody.querySelectorAll('.line-total').forEach(c => { sub += parseFloat(c.dataset.val || 0); });
    const vat   = vatBox && vatBox.checked ? sub * VAT / 100 : 0;
    const total = sub + vat;
    const sd = document.getElementById('subtotal-display');
    const vd = document.getElementById('vat-display');
    const td = document.getElementById('total-display');
    if (sd) sd.textContent = 'TZS ' + fmt(sub);
    if (vd) vd.textContent = 'TZS ' + fmt(vat);
    if (td) td.textContent = 'TZS ' + fmt(total);
  }

  function renumber() {
    itemsBody.querySelectorAll('tr').forEach((r, i) => {
      const n = r.querySelector('.row-num');
      if (n) n.textContent = i + 1;
    });
  }

  // ── Product popup ──────────────────────────────────────────
  function currentBranch() {
    const el = document.getElementById('branch_id');
    return el ? el.value : '';
  }

  function searchProducts(q, inp, tr) {
    fetch(`${PRODUCT_SEARCH_URL}?q=${encodeURIComponent(q)}&branch_id=${encodeURIComponent(currentBranch())}`)
      .then(r => r.json())
      .then(data => {
        if (!data.length) { hideProd(); return; }
        prodPopup.innerHTML = '';
        const rect = inp.getBoundingClientRect();
        Object.assign(prodPopup.style, {
          top:   (rect.bottom + window.scrollY + 2) + 'px',
          left:  (rect.left  + window.scrollX) + 'px',
          width: rect.width + 'px',
        });
        data.forEach(p => {
          const catLabel = p.subcategory_name
            ? `${p.category_name} › ${p.subcategory_name}`
            : (p.category_name || '');
          const descLine = catLabel ? `${catLabel} — ${p.model}` : p.model;
          const here = Number(p.branch_stock ?? 0);
          const div = document.createElement('div');
          div.className = 'ac-item';
          if (here <= 0) div.style.opacity = '0.55';
          div.innerHTML =
            `<div class="ac-item__main">${esc(p.model)}</div>` +
            `<div class="ac-item__sub">${esc(catLabel)}${catLabel ? ' &nbsp;·&nbsp; ' : ''}TZS ${fmt(p.price)} &nbsp;·&nbsp; ` +
            (here > 0
              ? `<span style="color:#15803d;font-weight:600">In stock here: ${fmt(here)}</span>`
              : `<span style="color:#b91c1c;font-weight:600">Out of stock at this branch</span>`) +
            `</div>`;
          div.addEventListener('mousedown', () => {
            if (here <= 0) {
              alert(`${p.model} is out of stock at this branch.\n\nReceive it first (Stock → Add / Adjust Stock) or transfer it from another branch.`);
              return;
            }
            tr.querySelector('.desc-inp').value  = descLine;
            tr.querySelector('.pid-inp').value   = p.id;
            tr.querySelector('.price-inp').value = p.price;
            updateRow(tr); recalc(); hideProd();
            loadUnits(tr, p);
          });
          prodPopup.appendChild(div);
        });
        prodPopup.style.display = '';
      });
  }

  function hideProd() { prodPopup.style.display = 'none'; }

  // ── Per-unit (IMEI) picker ─────────────────────────────────
  // Products flagged track_units are sold one physical device at a time, so the
  // staff member picks exactly which units leave the shelf.
  function clearUnits(tr) {
    const box = tr.querySelector('.units-box');
    const inp = tr.querySelector('.units-inp');
    if (inp) inp.value = '';
    if (box) { box.style.display = 'none'; box.innerHTML = ''; }
  }

  function loadUnits(tr, product) {
    clearUnits(tr);
    if (!product.track_units) return;

    const box      = tr.querySelector('.units-box');
    const branchEl = document.getElementById('branch_id');
    const branchId = branchEl ? branchEl.value : '';

    fetch(`${UNITS_API_URL}?product_id=${product.id}&branch_id=${encodeURIComponent(branchId)}`)
      .then(r => r.json())
      .then(units => {
        box.style.display = '';
        if (!units.length) {
          box.innerHTML =
            '<div style="font-size:12px;color:#b91c1c">' +
            'No units with IMEI in stock at this branch. Add them under Stock → Add / Adjust Stock.' +
            '</div>';
          return;
        }
        box.innerHTML =
          '<div style="font-size:11px;color:#6b7280;margin-bottom:4px">' +
          'Select the device(s) being sold — must match the quantity:</div>';
        units.forEach(u => {
          const bits = [u.color, u.storage, u.condition].filter(Boolean).join(' · ');
          const lbl = document.createElement('label');
          lbl.style.cssText = 'display:block;font-size:12px;cursor:pointer;padding:1px 0';
          lbl.innerHTML =
            `<input type="checkbox" class="unit-cb" value="${esc(u.imei)}" style="margin-right:6px">` +
            `<span style="font-family:monospace">${esc(u.imei)}</span>` +
            (bits ? ` <span style="color:#6b7280">— ${esc(bits)}</span>` : '');
          lbl.querySelector('.unit-cb').addEventListener('change', () => syncUnits(tr));
          box.appendChild(lbl);
        });
        box.appendChild(document.createElement('div')).className = 'units-msg';
        syncUnits(tr);
      })
      .catch(() => clearUnits(tr));
  }

  function syncUnits(tr) {
    const box = tr.querySelector('.units-box');
    if (!box || box.style.display === 'none') return;
    const picked = [...box.querySelectorAll('.unit-cb:checked')].map(cb => cb.value);
    tr.querySelector('.units-inp').value = picked.join(',');

    const qty = parseFloat(tr.querySelector('.qty-inp').value) || 0;
    const msg = box.querySelector('.units-msg');
    if (msg) {
      const ok = picked.length === qty;
      msg.style.cssText = 'font-size:11px;margin-top:3px;color:' + (ok ? '#15803d' : '#b91c1c');
      msg.textContent = ok
        ? `${picked.length} of ${qty} selected ✓`
        : `${picked.length} of ${qty} selected`;
    }
  }

  // ── Form validation ────────────────────────────────────────
  document.getElementById('doc-form').addEventListener('submit', e => {
    const hasItem = [...itemsBody.querySelectorAll('.desc-inp')]
      .some(inp => inp.value.trim() !== '');
    if (!hasItem) {
      e.preventDefault();
      alert('Please add at least one item before proceeding.');
      return;
    }

    // Every item must be picked from the product list so it comes out of stock.
    const typed = [];
    itemsBody.querySelectorAll('tr').forEach(tr => {
      const d = tr.querySelector('.desc-inp');
      if (d && d.value.trim() && !tr.querySelector('.pid-inp').value) {
        typed.push(d.value.trim());
        d.style.borderColor = '#ef4444';
      }
    });
    if (typed.length) {
      e.preventDefault();
      e.stopImmediatePropagation();
      alert('Pick these items from the product list (type, then click the product):\n\n• ' +
            typed.join('\n• ') +
            '\n\nIf a product is missing, ask the admin to add it to the catalogue.');
      return;
    }

    // Unit-tracked lines must have exactly `qty` IMEIs picked
    const bad = [];
    itemsBody.querySelectorAll('tr').forEach(tr => {
      const box = tr.querySelector('.units-box');
      if (!box || box.style.display === 'none') return;
      const qty    = parseFloat(tr.querySelector('.qty-inp').value) || 0;
      const picked = (tr.querySelector('.units-inp').value || '')
                       .split(',').filter(Boolean).length;
      if (picked !== qty) {
        bad.push(`${tr.querySelector('.desc-inp').value || 'Item'}: ${picked} of ${qty} IMEIs selected`);
      }
    });
    if (bad.length) {
      e.preventDefault();
      alert('Select the IMEI for every unit being sold:\n\n' + bad.join('\n'));
    }
  });

  // ── Utilities ──────────────────────────────────────────────
  function fmt(n) {
    return Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 });
  }

  function esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  if (typeof recalcOnce !== 'undefined' && recalcOnce) recalc();

  // Expose for barcode scan handler
  window._addDocRow = addRow;
  window._docRowSearchProducts = searchProducts;
});
