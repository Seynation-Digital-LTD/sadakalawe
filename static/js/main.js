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
  addRow(); // start with one row

  function addRow(desc = '', qty = 1, price = '', specs = '', disc = 0) {
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

    let prodTimer;
    descInp.addEventListener('input', () => {
      clearTimeout(prodTimer);
      pidInp.value = '';
      const q = descInp.value.trim();
      if (!q) { hideProd(); return; }
      prodTimer = setTimeout(() => searchProducts(q, descInp, tr), 240);
    });
    descInp.addEventListener('blur', () => setTimeout(hideProd, 200));

    [qtyInp, priceInp, discInp].forEach(el =>
      el.addEventListener('input', () => { updateRow(tr); recalc(); }));

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
  function searchProducts(q, inp, tr) {
    fetch(`${PRODUCT_SEARCH_URL}?q=${encodeURIComponent(q)}`)
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
          const div = document.createElement('div');
          div.className = 'ac-item';
          div.innerHTML =
            `<div class="ac-item__main">${esc(p.model)}</div>` +
            `<div class="ac-item__sub">${esc(catLabel)}${catLabel ? ' &nbsp;·&nbsp; ' : ''}TZS ${fmt(p.price)} &nbsp;·&nbsp; Stock: ${p.stock_count ?? '—'}</div>`;
          div.addEventListener('mousedown', () => {
            tr.querySelector('.desc-inp').value  = descLine;
            tr.querySelector('.pid-inp').value   = p.id;
            tr.querySelector('.price-inp').value = p.price;
            updateRow(tr); recalc(); hideProd();
          });
          prodPopup.appendChild(div);
        });
        prodPopup.style.display = '';
      });
  }

  function hideProd() { prodPopup.style.display = 'none'; }

  // ── Form validation ────────────────────────────────────────
  document.getElementById('doc-form').addEventListener('submit', e => {
    const hasItem = [...itemsBody.querySelectorAll('.desc-inp')]
      .some(inp => inp.value.trim() !== '');
    if (!hasItem) {
      e.preventDefault();
      alert('Please add at least one item before proceeding.');
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
});
