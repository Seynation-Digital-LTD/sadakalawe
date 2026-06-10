/* Sadakalawe — Document Creator */

document.addEventListener('DOMContentLoaded', () => {
  if (!document.getElementById('doc-form')) return;

  const VAT = typeof VAT_RATE !== 'undefined' ? parseFloat(VAT_RATE) : 18;
  let rowCount = 0;

  // ── Payment Type Toggle ────────────────────────────────────
  const optCash    = document.getElementById('opt-cash');
  const optCredit  = document.getElementById('opt-credit');
  const dueSec     = document.getElementById('due-date-section');

  function updatePaymentUI() {
    const isCash = document.querySelector('input[name="payment_type"]:checked')?.value === 'cash';
    dueSec && (dueSec.style.display = isCash ? 'none' : '');
    if (optCash)   optCash.classList.toggle('active', isCash);
    if (optCredit) optCredit.classList.toggle('active', !isCash);
  }

  document.querySelectorAll('input[name="payment_type"]').forEach(r =>
    r.addEventListener('change', updatePaymentUI));
  updatePaymentUI();

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
  const custSearch = document.getElementById('customer-search');
  const custDrop   = document.getElementById('customer-dropdown');
  const custId     = document.getElementById('customer_id');
  const custCard   = document.getElementById('customer-selected-card');
  const pickerWrap = document.getElementById('customer-picker-wrap');
  const selName    = document.getElementById('sel-name');
  const selPhone   = document.getElementById('sel-phone');
  const selAvatar  = document.getElementById('sel-avatar');
  const clearBtn   = document.getElementById('clear-customer');

  let custTimer;

  custSearch && custSearch.addEventListener('input', () => {
    clearTimeout(custTimer);
    const q = custSearch.value.trim();
    if (!q) { custDrop.style.display = 'none'; return; }
    custTimer = setTimeout(() => searchCustomers(q), 240);
  });

  custSearch && custSearch.addEventListener('blur', () => {
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
    custId.value   = c.id;
    selName.textContent  = c.name;
    selPhone.textContent = c.phone || '';
    selAvatar.textContent = c.name.charAt(0).toUpperCase();
    custCard.style.display  = '';
    pickerWrap.style.display = 'none';
    custDrop.style.display  = 'none';
  }

  clearBtn && clearBtn.addEventListener('click', () => {
    custId.value     = '';
    custSearch.value = '';
    custCard.style.display   = 'none';
    pickerWrap.style.display = '';
    custSearch.focus();
  });

  // ── Line items ─────────────────────────────────────────────
  const itemsBody = document.getElementById('items-body');
  const addBtn    = document.getElementById('add-item-btn');
  const prodPopup = document.getElementById('product-popup');

  addBtn && addBtn.addEventListener('click', () => addRow());
  addRow(); // start with one row

  function addRow(desc = '', qty = 1, price = '') {
    rowCount++;
    const tr = document.createElement('tr');
    tr.dataset.row = rowCount;
    tr.innerHTML = `
      <td class="row-num">${rowCount}</td>
      <td style="position:relative">
        <input type="text" name="item_description[]" class="desc-inp"
               value="${esc(desc)}" placeholder="Jina la bidhaa…" autocomplete="off">
        <input type="hidden" name="item_product_id[]" class="pid-inp" value="">
      </td>
      <td>
        <input type="number" name="item_qty[]" class="qty-inp"
               value="${qty}" min="0" step="any" style="text-align:right">
      </td>
      <td>
        <input type="number" name="item_price[]" class="price-inp"
               value="${price}" min="0" step="100" placeholder="0" style="text-align:right">
      </td>
      <td class="line-total" data-val="0">—</td>
      <td>
        <button type="button" class="btn-row-del" title="Futa safu">
          <i class="bi bi-x-lg"></i>
        </button>
      </td>`;
    itemsBody.appendChild(tr);

    const descInp  = tr.querySelector('.desc-inp');
    const qtyInp   = tr.querySelector('.qty-inp');
    const priceInp = tr.querySelector('.price-inp');
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

    [qtyInp, priceInp].forEach(el =>
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
    const total = qty * price;
    const cell  = tr.querySelector('.line-total');
    cell.textContent = total ? 'TZS ' + fmt(total) : '—';
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
          const div = document.createElement('div');
          div.className = 'ac-item';
          div.innerHTML =
            `<div class="ac-item__main">${esc(p.brand_category)} — ${esc(p.model)}</div>` +
            `<div class="ac-item__sub">TZS ${fmt(p.price)} &nbsp;·&nbsp; Hisa: ${p.stock_count ?? '—'}</div>`;
          div.addEventListener('mousedown', () => {
            tr.querySelector('.desc-inp').value  = `${p.brand_category} — ${p.model}`;
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
      alert('Ongeza angalau bidhaa moja kabla ya kuendelea.');
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
